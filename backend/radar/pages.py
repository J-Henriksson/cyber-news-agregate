"""A read-only copy of the page for GitHub Pages: the built page and, as
files beside it, the data of every view at every desk and window, as it
stood when the copy was made. The page opens such a copy by itself: a
``radar-snapshot`` tag in its index.html says it is one (frontend api.ts).

The copy is made and pushed from this machine while the app runs: once
when the sources have been read after a start, then at most every
RADAR_PAGES_EVERY_MIN minutes when something changed. Nothing is made
unless RADAR_PAGES says where to push (a remote of this repository, or an
address). By hand, from backend/:

    uv run python -m radar.pages            # make the copy and push it
    uv run python -m radar.pages --no-push  # only make it (data/pages)

What a copy leaves out: the reader's own (stars, notes, what was opened),
the profile's editor, the model's calls and spend, and every incident
that writes a word of RADAR_PAGES_WITHHOLD. What was dismissed is left
out as it is from every view. A copy that would still hold a withheld
word is not pushed."""

from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import subprocess
import threading
import time
from pathlib import Path

from . import config
from .engine import Radar, _brief

log = logging.getLogger(__name__)

#: The page's windows in days (App.tsx WINDOWS; 0 is today) and its desks.
WINDOWS = (0, 3, 7, 14, 30, 90)
DESKS = ("", "cyber", "ai")
LENSES = ("us", "links", "companies", "groups")
#: The graph's two controls stand at these in a copy (Graph.tsx hides them there).
GRAPH_LIMIT = 120
GRAPH_MIN_RELEVANCE = {"us": 10, "links": 10}
#: After a push that failed, the next is tried this much later.
RETRY_S = 300.0
#: The files of a copy that are text: these are searched for withheld words.
TEXT = frozenset((".html", ".js", ".css", ".json", ".svg", ".txt", ".map"))
TAG = '<meta name="radar-snapshot" content="{at}" data-midnight="{midnight}" />'


class Withheld(Exception):
    """The copy holds a word it must not: it is not pushed."""


def _holds(words: list[str]):
    """Whether a value, as it would be written, holds a withheld word."""
    if not words:
        return lambda _value: False
    return lambda value: any(w in json.dumps(value, ensure_ascii=False, default=str).lower() for w in words)


class _Kept:
    """The store as a copy may see it: of the reader's own only what was
    dismissed, and nothing of Wikidata that holds a withheld word."""

    def __init__(self, store, holds):
        self._store, self._holds = store, holds

    def __getattr__(self, name):
        return getattr(self._store, name)

    def states(self) -> dict[str, dict]:
        return {k: {"starred": False, "dismissed": True, "seen": None, "note": None}
                for k, v in self._store.states().items() if v["dismissed"]}

    def get(self, key: str, max_age: float | None = None):
        value = self._store.get(key, max_age)
        return None if key.startswith("wd:") and self._holds(value) else value

    def get_many(self, prefix: str) -> dict:
        got = self._store.get_many(prefix)
        return {k: v for k, v in got.items() if not self._holds(v)} if prefix == "wd:" else got


class _Copy(Radar):
    """The incidents as they stand, less the withheld. Every file of a copy
    is cut from this one list, so its views agree with one another even if
    news arrives while it is written."""

    def __init__(self, radar: Radar, words: list[str]):
        holds = _holds(words)
        self.store = _Kept(radar.store, holds)
        self.profile = radar.profile
        self.profile_version = radar.profile_version
        self._incidents = [i for i in radar.incidents()
                           if not holds({k: v for k, v in i.items() if not k.startswith("_")})]
        self._by_id = {i["id"]: i for i in self._incidents}
        self._makers = None
        self._key = radar.version()
        self.built, self.built_at, self.build_seconds = radar.built, radar.built_at, radar.build_seconds
        self._building = threading.Lock()

    def stale(self) -> bool:
        return False

    def incidents(self) -> list[dict]:
        return self._incidents


def _sources(copy: Radar) -> dict:
    """The sources as they last answered, without the model's calls and spend."""
    out = copy.sources()
    out["model"] = {"name": out["model"]["name"], "key": out["model"]["key"], "daily_calls": 0, "cost_today_usd": 0.0,
                    "states": {}, "today": {"calls": 0, "items": 0, "prompt_tokens": 0, "output_tokens": 0, "failed": 0,
                                            "last": None}}
    return out | {"busy": [], "last_round": {}, "polling": False}


def _clear(out: Path) -> None:
    """Empty the folder of the last copy, keeping its .git. A folder that
    holds anything else is not touched."""
    out.mkdir(parents=True, exist_ok=True)
    old = [p for p in out.iterdir() if p.name != ".git"]
    if old and not ((out / ".nojekyll").is_file() and (out / "data").is_dir()):
        raise ValueError(f"{out} holds something that is not a copy of the page: give the copy a folder of its own")
    for p in old:
        if p.is_dir() and not p.is_symlink():
            shutil.rmtree(p)
        else:
            p.unlink()


def _gate(out: Path, words: list[str]) -> None:
    """Nothing of a copy may hold a withheld word, the page's own files included."""
    for path in sorted(out.rglob("*")):
        rel = path.relative_to(out)
        if rel.parts[0] == ".git" or not path.is_file() or path.suffix not in TEXT:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore").lower()
        if any(w in text for w in words):
            raise Withheld(f"{rel} holds a withheld word")


def snapshot(radar: Radar, out: Path, dist: Path | None = None, words: list[str] | None = None) -> dict:
    """Write a copy to ``out`` (the last copy there is replaced). Returns
    what was written: files, bytes, incidents, seconds."""
    dist = dist or config.FRONTEND_DIST
    if not (dist / "index.html").is_file():
        raise FileNotFoundError("the page is not built (frontend/dist): ./run.sh builds it")
    words = config.pages_withhold() if words is None else [w.lower() for w in words if w]
    started = time.time()
    copy = _Copy(radar, words)
    # "Today" in a copy is the day it was made, by this machine's clock.
    midnight = time.mktime((*time.localtime(started)[:3], 0, 0, 0, 0, 0, -1))
    _clear(out)
    shutil.copytree(dist, out, dirs_exist_ok=True)
    (out / ".nojekyll").write_text("")
    index = (out / "index.html").read_text(encoding="utf-8")
    if "</head>" not in index:
        raise ValueError("the built page has no </head> to mark as a copy")
    tag = TAG.format(at=int(started), midnight=int(midnight))
    (out / "index.html").write_text(index.replace("</head>", f"  {tag}\n  </head>", 1), encoding="utf-8")

    data = out / "data"
    (data / "incident").mkdir(parents=True)
    written = {"files": 0, "bytes": 0}

    def put(name: str, value) -> None:
        raw = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()
        (data / f"{name}.json").write_bytes(raw)
        written["files"] += 1
        written["bytes"] += len(raw)

    # The feed is cut in the browser (desk, window, kind, search, order): one list of every row, with what search reads.
    rows = copy.window(90)
    put("feed", {"rows": [_brief(i) | {"hay": i["_hay"]} for i in rows]})
    windows = [("today", 1, midnight) if w == 0 else (str(w), w, None) for w in WINDOWS]
    for desk in DESKS:
        d, on = desk or "all", desk or None
        put(f"brief-today-{d}", copy.brief(24, on, midnight))
        for hours in sorted({min(w, 3) * 24 for w in WINDOWS if w}):
            put(f"brief-{hours}-{d}", copy.brief(hours, on))
        for key, days, since in windows:
            at = f"{key}-{d}"
            nodes: dict[str, dict] = {}
            for lens in LENSES:
                graph = copy.graph(days, GRAPH_MIN_RELEVANCE.get(lens, 0), GRAPH_LIMIT, on, since, lens)
                put(f"graph-{lens}-{at}", graph)
                for n in graph["nodes"]:
                    if not n["id"].startswith("i:") and n["id"] not in nodes:
                        detail = copy.node(n["id"], days, on, since)
                        if detail is not None:
                            nodes[n["id"]] = detail
            put(f"nodes-{at}", nodes)
            put(f"companies-{at}", copy.companies(days, on, since))
            put(f"money-{at}", copy.money(days, on, since))
            put(f"timeline-{at}", copy.timeline(days, on, since))
    for inc in rows:
        if inc["id"].isalnum():
            put(f"incident/{inc['id']}", copy.incident(inc["id"]))
    put("sources", _sources(copy))
    for name in ("index.html", ".nojekyll"):
        written["files"] += 1
        written["bytes"] += (out / name).stat().st_size
    if words:
        _gate(out, words)
    return {**written, "incidents": len(rows), "seconds": round(time.time() - started, 1)}


# -- pushing it ---------------------------------------------------------------------------------

def _git(cwd: Path, *args: str, env: dict | None = None, timeout: float = 120) -> str:
    """One git command there, never waiting for a person: a failure is raised with what git said."""
    r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=timeout,
                       env={**os.environ, "GIT_TERMINAL_PROMPT": "0", **(env or {})})
    if r.returncode != 0:
        raise RuntimeError(f"git {args[0]}: {(r.stderr or r.stdout).strip()[-300:]}")
    return r.stdout.strip()


def _of_project(key: str) -> str:
    """A setting of this repository's git (its own, or the user's), or nothing."""
    r = subprocess.run(["git", "-C", str(config.ROOT), "config", key], capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else ""


def _remote_url(remote: str) -> str:
    """A remote of this repository by its name, or the address itself."""
    r = subprocess.run(["git", "-C", str(config.ROOT), "remote", "get-url", remote], capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 and r.stdout.strip() else remote


def publish(site: Path, remote: str, branch: str | None = None) -> None:
    """Push the copy in ``site`` as the one commit of ``branch``: a copy
    replaces the last, the branch keeps no history. The folder has a git
    of its own, so this repository's branches and index are not touched."""
    branch = branch or config.PAGES_BRANCH
    ref = f"refs/heads/{branch}"
    if not (site / ".git").exists():
        _git(site, "init", "--quiet")
        # No record of the copies replaced: they are to be forgotten.
        _git(site, "config", "core.logAllRefUpdates", "false")
    _git(site, "add", "--all", "--force", ".")
    tree = _git(site, "write-tree")
    name = _of_project("user.name") or "cyber-news-agregate"
    mail = _of_project("user.email") or "cyber-news-agregate@localhost"
    who = {"GIT_AUTHOR_NAME": name, "GIT_AUTHOR_EMAIL": mail, "GIT_COMMITTER_NAME": name, "GIT_COMMITTER_EMAIL": mail}
    commit = _git(site, "commit-tree", tree, "-m", f"The page as of {time.strftime('%Y-%m-%d %H:%M %Z')}", env=who)
    _git(site, "update-ref", ref, commit)
    # Never a question at a terminal nobody watches: without a key that answers by itself, the push fails and says so.
    ssh = os.environ.get("GIT_SSH_COMMAND") or f"{_of_project('core.sshCommand') or 'ssh'} -o BatchMode=yes"
    _git(site, "push", "--force", "--quiet", _remote_url(remote), f"{ref}:{ref}", env={"GIT_SSH_COMMAND": ssh}, timeout=300)
    subprocess.run(["git", "-c", "gc.pruneExpire=now", "gc", "--auto", "--quiet"], cwd=site, capture_output=True, timeout=300)


class Publisher:
    """Says when a copy is due, makes it and pushes it. Never raises: the
    poller goes on, and the Sources view says what happened."""

    def __init__(self, radar: Radar):
        self.radar = radar
        self.last_try = 0.0
        #: What the last pushed copy was made from; None until one is pushed after this start.
        self.seen: tuple | None = None
        self.last: dict | None = None

    def due(self, now: float) -> bool:
        if not config.pages_remote():
            return False
        gap = now - self.last_try
        if self.seen is None:
            return gap >= RETRY_S
        return config.PAGES_EVERY_MIN > 0 and self.radar.version() != self.seen and gap >= config.PAGES_EVERY_MIN * 60

    def run(self) -> None:
        self.last_try = time.time()
        version = self.radar.version()
        try:
            made = snapshot(self.radar, config.PAGES_DIR)
            publish(config.PAGES_DIR, config.pages_remote())
        except Exception as err:  # noqa: BLE001 - a copy that fails is said, the rest goes on
            self.last = {"at": time.time(), "ok": False, "error": str(err)[:300]}
            log.warning("pages: not pushed: %s", err)
            return
        self.seen = version
        self.last = {"at": time.time(), "ok": True, **made}
        log.info("pages: pushed %d files (%.1f MB, %d incidents) in %.0f s", made["files"], made["bytes"] / 1e6,
                 made["incidents"], time.time() - self.last_try)

    def status(self) -> dict:
        return {"on": bool(config.pages_remote()), "last": self.last}


def main(argv: list[str] | None = None) -> int:
    from .store import Store

    ap = argparse.ArgumentParser(description="Make the read-only copy of the page and push it.")
    ap.add_argument("--no-push", action="store_true", help="only make the copy")
    ap.add_argument("--out", type=Path, default=config.PAGES_DIR, help="where to make it (default: data/pages)")
    args = ap.parse_args(argv)
    made = snapshot(Radar(Store(config.DB_PATH)), args.out)
    print(f"{made['files']} files, {made['bytes'] / 1e6:.1f} MB, {made['incidents']} incidents, in {made['seconds']} s: {args.out}")
    if args.no_push:
        return 0
    if not config.pages_remote():
        print("RADAR_PAGES is not set in .env: nothing to push to")
        return 1
    publish(args.out, config.pages_remote())
    print(f"pushed to {config.pages_remote()}, branch {config.PAGES_BRANCH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
