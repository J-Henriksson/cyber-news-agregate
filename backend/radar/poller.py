"""The poller: a thread that reads every source whose time has come, then
lets the model read the new items, scores the new CVEs' chance of being
exploited (FIRST's EPSS), takes the day's exchange rates from the ECB,
and looks up the companies the incidents name on Wikidata.

When a source was last read is kept in the store, so a restart (uvicorn
--reload) does not read everything again at once."""

from __future__ import annotations

import asyncio
import logging
import threading
import time

import httpx

from . import companies, llm
from .config import USER_AGENT
from .extract import rules_of
from .money import ECB_DAILY, parse_ecb
from .sources import SOURCES, Source, Unchanged, fetch_kev

log = logging.getLogger(__name__)

TICK_S = 30.0
RETRY_S = 300.0
DAY = 86400.0


class Poller(threading.Thread):
    def __init__(self, store, radar):
        super().__init__(daemon=True, name="radar-poller")
        self.store = store
        self.radar = radar
        self.stop = threading.Event()
        self.wake = threading.Event()
        self.force = False
        self.busy: set[str] = set()
        self.last_round: dict = {}
        #: Failures in a row, by source.
        self.fails: dict[str, int] = {}

    def refresh(self) -> None:
        """Read every source now (one not read in the last two minutes)."""
        self.force = True
        self.wake.set()

    def run(self) -> None:
        asyncio.run(self._loop())

    async def _loop(self) -> None:
        async with httpx.AsyncClient(headers={"User-Agent": USER_AGENT}, timeout=40.0) as client:
            while not self.stop.is_set():
                try:
                    await self.round(client)
                except Exception:  # noqa: BLE001 - the poller never dies of one bad round
                    log.exception("poll round failed")
                self.wake.wait(TICK_S)
                self.wake.clear()

    def due(self, now: float, force: bool) -> list[Source]:
        tried = {s["name"]: s.get("last_try") or 0 for s in self.store.sources()}
        out = []
        for src in SOURCES:
            last = tried.get(src.name, 0)
            # A source that just failed (the laptop was asleep, a DNS blip) is
            # asked again in five minutes, three times, before its usual wait.
            wait = min(src.every, RETRY_S) if 0 < self.fails.get(src.name, 0) <= 3 else src.every
            if now - last >= wait or (force and now - last >= 120):
                out.append(src)
        return out

    async def round(self, client: httpx.AsyncClient) -> None:
        force, self.force = self.force, False
        now = time.time()
        due = self.due(now, force)
        gate = asyncio.Semaphore(5)

        async def read(src: Source) -> None:
            async with gate:
                self.busy.add(src.name)
                try:
                    items = await src.fetch(client)
                    new = await asyncio.to_thread(self.store.upsert_items, items, rules_of)
                    self.store.source_result(src.name, src.kind, src.url, True, len(items), new, None)
                    self.fails.pop(src.name, None)
                    if src.fetch is fetch_kev:
                        self.store.put("kev_catalog", getattr(fetch_kev, "catalog", []), bump=True)
                    if new:
                        log.info("%s: %d items, %d new", src.name, len(items), new)
                except Unchanged:
                    self.store.source_unchanged(src.name)
                    self.fails.pop(src.name, None)
                except Exception as err:  # noqa: BLE001 - a source that fails is said, the rest go on
                    detail = f"HTTP {err.response.status_code}" if isinstance(err, httpx.HTTPStatusError) else (
                        str(err) or type(err).__name__)
                    self.store.source_result(src.name, src.kind, src.url, False, 0, 0, detail[:200])
                    self.fails[src.name] = self.fails.get(src.name, 0) + 1
                    if self.fails[src.name] in (1, 4):
                        log.warning("%s failed: %s", src.name, detail)
                finally:
                    self.busy.discard(src.name)

        if due:
            await asyncio.gather(*(read(s) for s in due))
        await self.rates(client)
        await self.epss(client)
        did = await asyncio.to_thread(llm.run, self.store)
        names = self.company_names()
        looked = await asyncio.to_thread(companies.enrich, self.store, names)
        social_before = time.time() - 14 * DAY
        pruned = self.store.prune(time.time() - 90 * DAY)
        with self.store.lock:
            cur = self.store.db.execute("DELETE FROM items WHERE kind IN ('social','community') AND published < ?",
                                        (social_before,))
            self.store.db.commit()
            pruned += cur.rowcount
        # Rebuild now, off the readers' path: the page is told when it is in.
        await asyncio.to_thread(self.radar.incidents)
        self.last_round = {"at": time.time(), "read": [s.name for s in due], "model": did, "wikidata": looked,
                           "pruned": pruned}

    async def rates(self, client: httpx.AsyncClient) -> None:
        if self.store.get("fx", DAY / 2) is not None:
            return
        try:
            r = await client.get(ECB_DAILY)
            r.raise_for_status()
            self.store.put("fx", parse_ecb(r.text), bump=True)
        except Exception as err:  # noqa: BLE001
            log.info("ECB rates: %s", err)

    async def epss(self, client: httpx.AsyncClient) -> None:
        """Scores for the CVEs of the last month not scored today."""
        cves = set()
        for item in self.store.items_since(time.time() - 30 * DAY):
            cves.update((item.get("rules") or {}).get("cves") or [])
        known = self.store.get_many("epss:")
        fresh_since = time.time() - DAY
        todo = sorted(c for c in cves if c not in known or (known[c].get("at") or 0) < fresh_since)
        for start in range(0, len(todo), 80):
            chunk = todo[start:start + 80]
            try:
                r = await client.get("https://api.first.org/data/v1/epss", params={"cve": ",".join(chunk)})
                r.raise_for_status()
            except httpx.HTTPError as err:
                log.info("EPSS: %s", err)
                return
            got = {row["cve"]: row for row in r.json().get("data", [])}
            for c in chunk:
                row = got.get(c)
                self.store.put(f"epss:{c}", {"epss": float(row["epss"]), "percentile": float(row["percentile"]),
                                             "date": row.get("date"), "at": time.time()} if row else {"at": time.time()})
            self.store.version += 1

    def company_names(self) -> list[str]:
        names: list[str] = []
        for inc in self.radar.window(30)[:80]:
            for e in inc["entities"]:
                if e["type"] == "company" and e["role"] in ("victim", "vendor") and e["name"] not in names:
                    names.append(e["name"])
        return names
