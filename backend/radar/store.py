"""The store: every item read, what was found in it, how each source last
answered, the model's calls, and small caches (exchange rates, Wikidata,
exploit scores). One SQLite file, one lock: the poller writes from its
thread, the API reads from the event loop."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Iterable

SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
  id TEXT PRIMARY KEY,
  source TEXT NOT NULL,
  kind TEXT NOT NULL,
  url TEXT,
  title TEXT,
  text TEXT,
  published REAL,
  fetched REAL,
  data TEXT,
  rules TEXT,
  llm TEXT,
  llm_state TEXT NOT NULL DEFAULT 'pending'
);
CREATE INDEX IF NOT EXISTS items_published ON items(published);
CREATE INDEX IF NOT EXISTS items_llm ON items(llm_state);
CREATE TABLE IF NOT EXISTS source_status (
  name TEXT PRIMARY KEY,
  kind TEXT,
  url TEXT,
  last_try REAL,
  last_ok REAL,
  items INTEGER,
  new_items INTEGER,
  error TEXT
);
CREATE TABLE IF NOT EXISTS llm_calls (
  at REAL,
  model TEXT,
  items INTEGER,
  prompt_tokens INTEGER,
  output_tokens INTEGER,
  ok INTEGER,
  error TEXT
);
CREATE TABLE IF NOT EXISTS incident_ids (
  item_id TEXT PRIMARY KEY,
  incident_id TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS incident_state (
  incident_id TEXT PRIMARY KEY,
  starred INTEGER NOT NULL DEFAULT 0,
  dismissed INTEGER NOT NULL DEFAULT 0,
  seen REAL,
  note TEXT
);
CREATE TABLE IF NOT EXISTS kv (
  key TEXT PRIMARY KEY,
  value TEXT,
  at REAL
);
"""


class Store:
    def __init__(self, path: Path | str):
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path), check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.lock = threading.RLock()
        #: Bumped on every write that changes what the views show.
        self.version = 0
        #: Bumped when an incident is starred, dismissed, seen or noted (no rebuild needed).
        self.state_version = 0
        with self.lock:
            self.db.executescript(SCHEMA)
            self.db.execute("PRAGMA journal_mode=WAL")

    # -- items --------------------------------------------------------------------------------

    def upsert_items(self, items: Iterable[dict], rules_of) -> int:
        """Insert new items (with their rule extraction), refresh the text of
        known ones. Returns how many were new."""
        new = 0
        changed = False
        now = time.time()
        with self.lock:
            for it in items:
                row = self.db.execute("SELECT title, text, data FROM items WHERE id = ?", (it["id"],)).fetchone()
                data = json.dumps(it.get("data") or {}, sort_keys=True)
                if row is None:
                    self.db.execute(
                        "INSERT INTO items (id, source, kind, url, title, text, published, fetched, data, rules, llm_state)"
                        " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                        (it["id"], it["source"], it["kind"], it.get("url"), it.get("title"), it.get("text"),
                         it.get("published") or now, now, data, json.dumps(rules_of(it)),
                         "pending" if it.get("llm", True) else "skipped"),
                    )
                    new += 1
                elif (row["title"], row["text"], row["data"]) != (it.get("title"), it.get("text"), data):
                    self.db.execute(
                        "UPDATE items SET title = ?, text = ?, data = ?, rules = ? WHERE id = ?",
                        (it.get("title"), it.get("text"), data, json.dumps(rules_of(it)), it["id"]),
                    )
                    changed = True
            self.db.commit()
            if new or changed:
                self.version += 1
        return new

    def reread_rules(self, rules_of, version: int) -> int:
        """Every stored item read again by the current rules, once per rules version."""
        if self.get("rules_version") == version:
            return 0
        with self.lock:
            rows = self.db.execute("SELECT * FROM items").fetchall()
            for row in rows:
                it = _item(row)
                self.db.execute("UPDATE items SET rules = ? WHERE id = ?", (json.dumps(rules_of(it)), it["id"]))
            self.db.commit()
            self.version += 1
        self.put("rules_version", version)
        return len(rows)

    def reread_llm(self, version: int) -> int:
        """Items the model read under an older version back in line to be read again."""
        with self.lock:
            rows = self.db.execute("SELECT id, llm FROM items WHERE llm_state = 'done'").fetchall()
            stale = [r["id"] for r in rows if (json.loads(r["llm"] or "{}").get("v") or 1) < version]
            # What the model failed on gets one more try at every start.
            stale += [r["id"] for r in self.db.execute("SELECT id FROM items WHERE llm_state = 'failed'")]
            for item_id in stale:
                self.db.execute("UPDATE items SET llm_state = 'pending' WHERE id = ?", (item_id,))
            self.db.commit()
        return len(stale)

    def items_since(self, since: float) -> list[dict]:
        with self.lock:
            rows = self.db.execute("SELECT * FROM items WHERE published >= ? ORDER BY published", (since,)).fetchall()
        return [_item(r) for r in rows]

    def pending_for_llm(self, limit: int, kinds_first: tuple[str, ...]) -> list[dict]:
        order = " ".join(f"WHEN '{k}' THEN {i}" for i, k in enumerate(kinds_first))
        with self.lock:
            rows = self.db.execute(
                f"SELECT * FROM items WHERE llm_state = 'pending' ORDER BY CASE kind {order} ELSE 99 END, published DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [_item(r) for r in rows]

    def set_llm(self, results: dict[str, dict | None], state_missing: str = "failed") -> None:
        with self.lock:
            for item_id, out in results.items():
                if out is None:
                    self.db.execute("UPDATE items SET llm_state = ? WHERE id = ?", (state_missing, item_id))
                else:
                    self.db.execute("UPDATE items SET llm = ?, llm_state = 'done' WHERE id = ?", (json.dumps(out), item_id))
            self.db.commit()
            self.version += 1

    def count_items(self) -> dict[str, int]:
        with self.lock:
            rows = self.db.execute("SELECT llm_state, COUNT(*) AS n FROM items GROUP BY llm_state").fetchall()
        return {r["llm_state"]: r["n"] for r in rows}

    def prune(self, before: float) -> int:
        with self.lock:
            cur = self.db.execute("DELETE FROM items WHERE published < ?", (before,))
            self.db.commit()
            if cur.rowcount:
                self.version += 1
            return cur.rowcount

    # -- incidents: their lasting ids and what the reader did with them ------------------------

    def incident_ids(self) -> dict[str, str]:
        """Which incident each item was last part of."""
        with self.lock:
            return {r["item_id"]: r["incident_id"] for r in self.db.execute("SELECT item_id, incident_id FROM incident_ids")}

    def save_incident_ids(self, changed: dict[str, str]) -> None:
        if not changed:
            return
        with self.lock:
            self.db.executemany(
                "INSERT INTO incident_ids (item_id, incident_id) VALUES (?,?)"
                " ON CONFLICT(item_id) DO UPDATE SET incident_id=excluded.incident_id", list(changed.items()))
            self.db.execute("DELETE FROM incident_ids WHERE item_id NOT IN (SELECT id FROM items)")
            self.db.commit()

    def states(self) -> dict[str, dict]:
        with self.lock:
            rows = self.db.execute("SELECT * FROM incident_state").fetchall()
        return {r["incident_id"]: {"starred": bool(r["starred"]), "dismissed": bool(r["dismissed"]), "seen": r["seen"],
                                   "note": r["note"]} for r in rows}

    def set_state(self, incident_id: str, **fields) -> dict:
        """Star, dismiss, mark seen or note an incident. Only the fields given change."""
        allowed = {k: v for k, v in fields.items() if k in ("starred", "dismissed", "seen", "note") and v is not None}
        with self.lock:
            self.db.execute("INSERT OR IGNORE INTO incident_state (incident_id) VALUES (?)", (incident_id,))
            for key, value in allowed.items():
                if key in ("starred", "dismissed"):
                    value = int(bool(value))
                elif key == "note":
                    value = str(value)[:2000] or None
                self.db.execute(f"UPDATE incident_state SET {key} = ? WHERE incident_id = ?", (value, incident_id))
            self.db.execute("DELETE FROM incident_state WHERE starred = 0 AND dismissed = 0 AND seen IS NULL AND note IS NULL")
            self.db.commit()
            self.state_version += 1
        return self.states().get(incident_id, {"starred": False, "dismissed": False, "seen": None, "note": None})

    # -- sources ------------------------------------------------------------------------------

    def source_result(self, name: str, kind: str, url: str, ok: bool, items: int, new: int, error: str | None) -> None:
        now = time.time()
        with self.lock:
            had = self.db.execute("SELECT last_ok FROM source_status WHERE name = ?", (name,)).fetchone()
            last_ok = now if ok else (had["last_ok"] if had else None)
            self.db.execute(
                "INSERT INTO source_status (name, kind, url, last_try, last_ok, items, new_items, error) VALUES (?,?,?,?,?,?,?,?)"
                " ON CONFLICT(name) DO UPDATE SET kind=excluded.kind, url=excluded.url, last_try=excluded.last_try,"
                " last_ok=excluded.last_ok, items=excluded.items, new_items=excluded.new_items, error=excluded.error",
                (name, kind, url, now, last_ok, items, new, error),
            )
            self.db.commit()

    def source_unchanged(self, name: str) -> None:
        """The source answered that nothing has changed since the last read."""
        now = time.time()
        with self.lock:
            self.db.execute("UPDATE source_status SET last_try = ?, last_ok = ?, new_items = 0, error = NULL WHERE name = ?",
                            (now, now, name))
            self.db.commit()

    def sources(self) -> list[dict]:
        with self.lock:
            rows = self.db.execute("SELECT * FROM source_status ORDER BY kind, name").fetchall()
            counts = {r["source"]: r["n"] for r in self.db.execute("SELECT source, COUNT(*) AS n FROM items GROUP BY source")}
        return [dict(r) | {"stored": counts.get(r["name"], 0)} for r in rows]

    # -- model calls --------------------------------------------------------------------------

    def log_llm(self, model: str, items: int, prompt_tokens: int, output_tokens: int, ok: bool, error: str | None) -> None:
        with self.lock:
            self.db.execute(
                "INSERT INTO llm_calls VALUES (?,?,?,?,?,?,?)",
                (time.time(), model, items, prompt_tokens, output_tokens, int(ok), error),
            )
            self.db.commit()

    def llm_since(self, since: float) -> dict[str, Any]:
        with self.lock:
            row = self.db.execute(
                "SELECT COUNT(*) AS calls, COALESCE(SUM(items),0) AS items, COALESCE(SUM(prompt_tokens),0) AS p,"
                " COALESCE(SUM(output_tokens),0) AS o, COALESCE(SUM(1 - ok),0) AS failed FROM llm_calls WHERE at >= ?",
                (since,),
            ).fetchone()
            last = self.db.execute("SELECT at, ok, error FROM llm_calls ORDER BY at DESC LIMIT 1").fetchone()
        return {"calls": row["calls"], "items": row["items"], "prompt_tokens": row["p"], "output_tokens": row["o"],
                "failed": row["failed"], "last": dict(last) if last else None}

    # -- cache --------------------------------------------------------------------------------

    def get(self, key: str, max_age: float | None = None) -> Any:
        with self.lock:
            row = self.db.execute("SELECT value, at FROM kv WHERE key = ?", (key,)).fetchone()
        if row is None or (max_age is not None and time.time() - row["at"] > max_age):
            return None
        return json.loads(row["value"])

    def put(self, key: str, value: Any, bump: bool = False) -> None:
        with self.lock:
            self.db.execute(
                "INSERT INTO kv (key, value, at) VALUES (?,?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value, at=excluded.at",
                (key, json.dumps(value), time.time()),
            )
            self.db.commit()
            if bump:
                self.version += 1

    def get_many(self, prefix: str) -> dict[str, Any]:
        with self.lock:
            rows = self.db.execute("SELECT key, value FROM kv WHERE key LIKE ?", (prefix + "%",)).fetchall()
        return {r["key"][len(prefix):]: json.loads(r["value"]) for r in rows}


def _item(row: sqlite3.Row) -> dict:
    out = dict(row)
    for key in ("data", "rules", "llm"):
        out[key] = json.loads(out[key]) if out.get(key) else None
    return out
