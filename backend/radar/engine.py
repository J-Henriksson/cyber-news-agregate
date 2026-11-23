"""The incidents and the views of them. Incidents are built from the
store once per change (the store's version or the profile) and scored
against the profile; every view is cut from that one list, so the feed,
the graph, the companies and the money always agree."""

from __future__ import annotations

import hashlib
import threading
import time
from collections import Counter, defaultdict

from . import profile as profile_mod
from .cluster import cluster
from . import graphs
from .gazetteer import placeholder
from .money import DAMAGE_KINDS, FALLBACK_PER_EUR
from .relevance import Scorer
from .sources import SOURCES
from .store import Store
from .text import norm_name

DAY = 86400.0


def top_score(inc: dict, now: float) -> float:
    """An incident's standing in "Top": its relevance, less as it ages
    (half of the fading part gone every three days, never below half), so
    a 90 of three days ago still stands above a 58 of this morning."""
    age_days = max(0.0, now - inc["last_seen"]) / DAY
    return inc["relevance"] * (0.5 + 0.5 * 0.5 ** (age_days / 3.0)) + min(len(inc["sources"]), 6) * 0.3


def assign_ids(incs: list[dict], known: dict[str, str]) -> dict[str, str]:
    """Give each incident a lasting id: the one most of its items carried
    before (the bigger incident keeps an id two would claim), else a new
    one from its earliest item. Returns each item's incident id. An
    incident keeps its id as reports join it, so a star or a link holds."""
    claims = sorted(((count, n, cid) for n, inc in enumerate(incs)
                     for cid, count in Counter(known[it["id"]] for it in inc["items"] if it["id"] in known).items()),
                    key=lambda c: (-c[0], c[1]))
    given: dict[int, str] = {}
    taken: set[str] = set()
    for _count, n, cid in claims:
        if n not in given and cid not in taken:
            given[n] = cid
            taken.add(cid)
    for n, inc in enumerate(incs):
        if n not in given:
            cid, k = inc["id"], 0
            while cid in taken:
                k += 1
                cid = hashlib.sha1(f"{inc['id']}:{k}".encode()).hexdigest()[:12]
            given[n] = cid
            taken.add(cid)
        inc["was"] = sorted({known[it["id"]] for it in inc["items"] if it["id"] in known} - {given[n]})
        inc["id"] = given[n]
    return {it["id"]: inc["id"] for inc in incs for it in inc["items"]}


class Radar:
    def __init__(self, store: Store):
        self.store = store
        self.profile = profile_mod.load()
        self.profile_version = 0
        self._key: tuple | None = None
        self._incidents: list[dict] = []
        self._by_id: dict[str, dict] = {}
        self.built_at = 0.0
        self.build_seconds = 0.0
        #: Counts the rebuilds: the event stream tells the page when it moves.
        self.built = 0
        self._building = threading.Lock()

    def version(self) -> tuple[int, int]:
        """What the views are built from: changes whenever anything they show could."""
        return (self.store.version, self.profile_version)

    def stale(self) -> bool:
        return self.version() != self._key

    def news_since(self, known_items: set[str] | None) -> tuple[set[str], list[dict]]:
        """Every item id now held, and the incidents with an item not among
        ``known_items`` (``None``: the first look, nothing is new). An
        incident regrouped without a new item is not new."""
        incs = self.incidents()
        items = {it["id"] for inc in incs for it in inc["items"]}
        if known_items is None:
            return items, []
        fresh = [i for i in incs if any(it["id"] not in known_items for it in i["items"])]
        return items, fresh

    # -- the one list -------------------------------------------------------------------------

    def set_profile(self, profile: dict) -> None:
        profile_mod.save(profile)
        self.profile = profile_mod.load()
        self.profile_version += 1

    def incidents(self) -> list[dict]:
        """The incidents, rebuilt if anything changed. While another thread
        is rebuilding, the last list serves: a reader never waits for a
        rebuild it did not start (the event stream tells the page when
        the new list is in)."""
        if self.stale():
            if self._key is not None and self._building.locked():
                return self._incidents
            with self._building:
                if self.stale():
                    self._rebuild()
        return self._incidents

    def _rebuild(self) -> None:
        key = self.version()
        started = time.time()
        items = self.store.items_since(time.time() - 90 * DAY)
        kev = {r["cve"]: r for r in self.store.get("kev_catalog") or []}
        epss = self.store.get_many("epss:")
        fx = self.store.get("fx") or {"per_eur": FALLBACK_PER_EUR, "day": None}
        incs = cluster(items, kev, epss, fx["per_eur"])
        known = self.store.incident_ids()
        now_ids = assign_ids(incs, known)
        self.store.save_incident_ids({k: v for k, v in now_ids.items() if known.get(k) != v})
        self._carry_stars(incs)
        scorer = Scorer(self.profile)
        for inc in incs:
            inc["relevance"], inc["reasons"] = scorer.score(inc)
            inc["_hay"] = " ".join([inc["title"], inc.get("summary") or "", *[e["name"] for e in inc["entities"]],
                                    *[c["id"] for c in inc["cves"]], *inc["sources"],
                                    *[it.get("title") or "" for it in inc["items"]]]).lower()
        incs.sort(key=lambda i: (-i["relevance"], -i["last_seen"]))
        self._incidents = incs
        self._by_id = {i["id"]: i for i in incs}
        self._key = key
        self.built += 1
        self.built_at = time.time()
        self.build_seconds = round(time.time() - started, 2)

    def _carry_stars(self, incs: list[dict]) -> None:
        """An incident that swallowed a starred one is starred: the star follows the story."""
        states = self.store.states()
        for inc in incs:
            if any(states.get(old, {}).get("starred") for old in inc["was"]) and not states.get(inc["id"], {}).get("starred"):
                self.store.set_state(inc["id"], starred=True)

    def window(self, days: float, desk: str | None = None, since: float | None = None, dismissed: bool = False) -> list[dict]:
        """The incidents told within ``days`` (or since the moment ``since``, which the
        page sends for "today": its own midnight), on one desk ("cyber", "ai") or both.
        What the reader dismissed is left out of every view unless asked for."""
        start = since if since is not None else time.time() - days * DAY
        hidden = set() if dismissed else {k for k, v in self.store.states().items() if v["dismissed"]}
        return [i for i in self.incidents() if i["last_seen"] >= start and (not desk or desk in i["topics"])
                and i["id"] not in hidden]

    # -- views --------------------------------------------------------------------------------

    def feed(self, days: float = 14, category: str | None = None, q: str | None = None, sort: str = "top",
             min_relevance: int = 0, limit: int = 300, kinds: str | None = None, desk: str | None = None,
             since: float | None = None, show: str | None = None) -> dict:
        """``show``: "starred", "updated" (told again since the reader last opened it) or
        "dismissed"; otherwise everything not dismissed."""
        states = self.store.states()
        rows = self.window(days, desk, since, dismissed=show == "dismissed")
        if show == "dismissed":
            rows = [i for i in rows if states.get(i["id"], {}).get("dismissed")]
        elif show == "starred":
            rows = [i for i in rows if states.get(i["id"], {}).get("starred")]
        elif show == "updated":
            rows = [i for i in rows if _updated(i, states.get(i["id"]))]
        base = rows
        if category:
            rows = [i for i in rows if i["category"] == category]
        if kinds:
            want = set(kinds.split(","))
            rows = [i for i in rows if want & set(i["kinds"])]
        if q:
            words = q.lower().split()
            rows = [i for i in rows if all(w in i["_hay"] for w in words)]
        rows = [i for i in rows if i["relevance"] >= min_relevance]
        now = time.time()
        if sort == "recent":
            rows.sort(key=lambda i: -i["last_seen"])
        elif sort == "money":
            rows.sort(key=lambda i: -(i.get("headline_usd") or 0))
        elif sort == "relevance":
            rows.sort(key=lambda i: (-i["relevance"], -len(i["sources"]), -i["last_seen"]))
        else:
            rows.sort(key=lambda i: -top_score(i, now))
        counts = Counter(i["category"] for i in base)
        return {"total": len(rows), "categories": dict(counts),
                "incidents": [_brief(i, states.get(i["id"])) for i in rows[:limit]]}

    def incident(self, incident_id: str) -> dict | None:
        self.incidents()
        i = self._by_id.get(incident_id)
        if i is None:
            # Regrouped under another id since the page read it: follow the items.
            moved = next((x for x in self._incidents if incident_id in x.get("was", ())), None)
            if moved is None:
                return None
            i = moved
        wd = self.store.get_many("wd:")
        companies = {e["name"]: wd.get(norm_name(e["name"])) for e in i["entities"] if e["type"] == "company"}
        public = {k: v for k, v in i.items() if not k.startswith("_")}
        return {**public, "kev": any(c["kev"] for c in i["cves"]),
                "companies": {k: v for k, v in companies.items() if v and not v.get("unknown")},
                "state": _state(i, self.store.states().get(i["id"])), "related": self.related(i)}

    def related(self, inc: dict, limit: int = 8) -> list[dict]:
        """Other incidents of the last 60 days that share a victim, a group,
        a flaw or (when few stories name it) a maker with this one."""
        def keys(i: dict) -> set[str]:
            out = {f"c:{c['id']}" for c in i["cves"]}
            for e in i["entities"]:
                if e["role"] in ("victim", "attacker") and not placeholder(e["name"]):
                    out.add(f"{e['role'][0]}:{norm_name(e['name'])}")
                elif e["role"] == "vendor":
                    out.add(f"m:{norm_name(e['name'])}")
            return out

        mine = keys(inc)
        if not mine:
            return []
        since = time.time() - 60 * DAY
        makers = Counter(k for i in self._incidents if i["last_seen"] >= since for k in keys(i) if k.startswith("m:"))
        mine = {k for k in mine if not k.startswith("m:") or makers[k] <= 12}
        found = []
        for other in self._incidents:
            if other is inc or other["last_seen"] < since:
                continue
            shared = mine & keys(other)
            if shared:
                names = sorted({k.split(":", 1)[1] for k in shared})
                found.append((len(shared), other["relevance"], other, names))
        found.sort(key=lambda f: (-f[0], -f[1]))
        return [{"id": o["id"], "title": o["title"], "category": o["category"], "relevance": o["relevance"],
                 "last_seen": o["last_seen"], "shares": names[:4]} for _n, _r, o, names in found[:limit]]

    def trending(self, desk: str | None = None, limit: int = 12) -> list[dict]:
        """What is named more in the last day than on a day of the week
        before: groups, victims, makers, flaws. At least two incidents in
        the day, and more than twice the week's daily rate."""
        now = time.time()
        recent: Counter = Counter()
        before: Counter = Counter()
        label: dict[str, tuple[str, str]] = {}
        best: dict[str, dict] = {}
        for inc in self.window(8, desk):
            bucket = recent if inc["last_seen"] >= now - DAY else before
            named = [(f"{e['type']}:{norm_name(e['name'])}", e["name"], e["type"]) for e in inc["entities"]
                     if e["role"] != "mentioned" and not placeholder(e["name"])]
            named += [(f"cve:{c['id']}", c["id"], "cve") for c in inc["cves"][:6]]
            for key, name, kind in named:
                bucket[key] += 1
                label[key] = (name, kind)
                if bucket is recent and (key not in best or inc["relevance"] > best[key]["relevance"]):
                    best[key] = inc
        rows = []
        for key, n in recent.items():
            daily = before[key] / 7.0
            if n >= 2 and n > 2 * daily:
                top = best[key]
                rows.append({"name": label[key][0], "kind": label[key][1], "today": n, "daily_before": round(daily, 2),
                             "incident": {"id": top["id"], "title": top["title"], "relevance": top["relevance"]}})
        rows.sort(key=lambda r: (-(r["today"] / (r["daily_before"] + 0.5)), -r["today"]))
        return rows[:limit]

    def brief(self, hours: float = 24, desk: str | None = None, since: float | None = None) -> dict:
        """The day on one page: what matters most, what is being exploited
        in our stack, the money, what is rising, new tools for the team's
        work, AI news, and what the reader starred."""
        now = time.time()
        start = since if since is not None else now - hours * 3600
        states = self.store.states()
        day = self.window(hours / 24, desk, since)
        week = self.window(7, desk)
        brief = lambda rows, n: [_brief(i, states.get(i["id"])) for i in rows[:n]]  # noqa: E731
        by_rel = sorted(day, key=lambda i: (-i["relevance"], -i["last_seen"]))
        exposure = [r for r in self.exposure(7)["rows"] if r["ours"]]
        # A digest's figures belong to stories it only lists: not one incident's money.
        money = [f for f in self.money(7, desk)["facts"] if f["usd"] and f["kind"] in DAMAGE_KINDS and not f["roundup"]][:6]
        tools = sorted((i for i in week if i["category"] == "tool" and i["relevance"] >= 15), key=lambda i: -top_score(i, now))
        ai = sorted((i for i in self.window(2, "ai") if i["category"] == "ai"), key=lambda i: -top_score(i, now))
        starred = sorted((i for i in self.incidents() if states.get(i["id"], {}).get("starred")), key=lambda i: -i["last_seen"])
        return {
            "since": start,
            "counts": {"incidents": len(day), "by_category": dict(Counter(i["category"] for i in day)),
                       "high": sum(1 for i in day if i["relevance"] >= 50),
                       "sources": len({s for i in day for s in i["sources"]})},
            "top": brief([i for i in by_rel if i["relevance"] >= 20], 8),
            "exploited": exposure[:8],
            "money": money,
            "trending": self.trending(desk),
            "tools": brief(tools, 6),
            "ai": brief(ai, 6),
            "starred": brief(starred, 10),
        }

    def graph(self, days: float = 14, min_relevance: int = 0, limit: int = 120, desk: str | None = None,
              since: float | None = None, lens: str = "links") -> dict:
        """One of the graph's lenses (graphs.py): "us", "links", "companies" or "groups"."""
        incs = [i for i in self.window(days, desk, since) if i["relevance"] >= min_relevance]
        return graphs.build(self, lens, incs, limit)

    def node(self, node_id: str, days: float = 14, desk: str | None = None, since: float | None = None) -> dict | None:
        """What stands behind one node of the graph."""
        return graphs.node_detail(self, node_id, self.window(days, desk, since))

    def companies(self, days: float = 30, desk: str | None = None, since: float | None = None) -> dict:
        wd = self.store.get_many("wd:")
        rows: dict[str, dict] = {}
        for inc in self.window(days, desk, since):
            for e in inc["entities"]:
                if e["type"] not in ("company", "government") or e["role"] not in ("victim", "vendor") or placeholder(e["name"]):
                    continue
                key = norm_name(e["name"])
                r = rows.setdefault(key, {"key": key, "name": e["name"], "type": e["type"], "sector": e.get("sector"),
                                          "country": e.get("country"), "as_victim": 0, "as_vendor": 0, "usd": 0.0,
                                          "records": 0, "relevance": 0, "incidents": [], "partners": Counter()})
                r["sector"] = r["sector"] or e.get("sector")
                r["country"] = r["country"] or e.get("country")
                r["as_victim" if e["role"] == "victim" else "as_vendor"] += 1
                if e["role"] == "victim":
                    r["usd"] += inc.get("headline_usd") or 0
                    r["records"] += inc.get("records") or 0
                r["relevance"] = max(r["relevance"], inc["relevance"])
                r["incidents"].append({"id": inc["id"], "title": inc["title"], "relevance": inc["relevance"],
                                       "role": e["role"], "usd": inc.get("headline_usd"), "last_seen": inc["last_seen"]})
                for other in inc["entities"]:
                    if other["type"] == "company" and norm_name(other["name"]) != key and other["role"] in ("victim", "vendor"):
                        r["partners"][other["name"]] += 1
        out = []
        for key, r in rows.items():
            info = wd.get(key)
            info = info if info and not info.get("unknown") else None
            related = []
            if info:
                for p in info.get("parent") or []:
                    if norm_name(p) != key:
                        related.append({"name": p, "how": "parent", "in_news": norm_name(p) in rows})
                for s in info.get("subsidiaries") or []:
                    if norm_name(s) != key:
                        related.append({"name": s, "how": "subsidiary", "in_news": norm_name(s) in rows})
            for name, n in r["partners"].most_common(8):
                related.append({"name": name, "how": f"same incident ({n})", "in_news": True})
            sector = r["sector"] or (_sector_from(info) if info else None) or "other"
            out.append({**{k: v for k, v in r.items() if k != "partners"}, "sector": sector, "wikidata": info,
                        "related": related})
        out.sort(key=lambda r: (-r["relevance"], -(r["as_victim"] + r["as_vendor"])))
        return {"companies": out}

    def money(self, days: float = 90, desk: str | None = None, since: float | None = None) -> dict:
        facts = []
        for inc in self.window(days, desk, since):
            for m in inc["money"]:
                facts.append({"incident": inc["id"], "title": inc["title"], "category": inc["category"],
                              "relevance": inc["relevance"], "victims": inc["victims"][:3], "kind": m["kind"],
                              "amount": m["amount"], "currency": m["currency"], "usd": m.get("usd"),
                              "quote": m.get("quote"), "source": m.get("source"), "when": inc["first_seen"],
                              "roundup": inc["roundup"]})
        damage = [f for f in facts if f["kind"] in DAMAGE_KINDS and f["usd"]]
        by_kind = defaultdict(float)
        for f in damage:
            by_kind[f["kind"]] += f["usd"]
        fx = self.store.get("fx") or {}
        return {"facts": sorted(facts, key=lambda f: -(f["usd"] or 0)), "by_kind": dict(by_kind),
                "fx_day": fx.get("day"), "fx_source": "ECB" if fx.get("day") else "fallback rates (approximate)"}

    def timeline(self, days: float = 30, desk: str | None = None, since: float | None = None) -> dict:
        """Incidents per hour (a window of two days or less) or per day, by kind, and each
        group's incidents. A bucket is its start in epoch seconds."""
        incs = self.window(days, desk, since)
        start = since if since is not None else time.time() - days * DAY
        bucket = 3600 if time.time() - start <= 2 * DAY else int(DAY)
        watched = set(self.profile.get("actors", []))
        per: dict[int, Counter] = defaultdict(Counter)
        actors: dict[str, list[dict]] = defaultdict(list)
        for inc in incs:
            # Counted when it was last told, inside the window (it may have begun before).
            t = int(inc["last_seen"] // bucket * bucket)
            per[t][inc["category"]] += 1
            for e in inc["entities"]:
                # Groups only (and the people we watch): "FBI" or a CEO read as the attacker is not a lane.
                if e["role"] == "attacker" and (e["type"] == "actor" or e["name"] in watched):
                    actors[e["name"]].append({"t": t, "id": inc["id"], "title": inc["title"], "relevance": inc["relevance"]})
        top_actors = sorted(actors.items(), key=lambda kv: -len(kv[1]))[:20]
        return {"start": start, "bucket": bucket, "buckets": [{"t": t, **c} for t, c in sorted(per.items())],
                "actors": [{"name": n, "events": ev} for n, ev in top_actors],
                "incidents": [{"id": i["id"], "title": i["title"], "category": i["category"], "relevance": i["relevance"],
                               "first_seen": i["first_seen"], "sources": len(i["sources"]), "usd": i.get("headline_usd")}
                              for i in incs]}

    def exposure(self, days: float = 60, since: float | None = None) -> dict:
        stack = {norm_name(s) for s in self.profile.get("stack", [])}
        catalog = self.store.get("kev_catalog") or []
        epss = self.store.get_many("epss:")
        start = since if since is not None else time.time() - days * DAY
        # CISA dates its additions by the day: "today" is the entries of today's date.
        since_day = time.strftime("%Y-%m-%d", time.localtime(start) if since is not None else time.gmtime(start))
        cve_incidents = defaultdict(list)
        for inc in self.window(days, None, since):
            for c in inc["cves"]:
                cve_incidents[c["id"]].append({"id": inc["id"], "title": inc["title"], "relevance": inc["relevance"]})
        rows = []
        for v in catalog:
            if (v.get("added") or "") < since_day:
                continue
            ours = norm_name(v.get("vendor") or "") in stack or norm_name(v.get("product") or "") in stack
            e = epss.get(v["cve"]) or {}
            rows.append({**v, "ours": ours, "epss": e.get("epss"), "percentile": e.get("percentile"),
                         "incidents": cve_incidents.get(v["cve"], [])})
        rows.sort(key=lambda r: (not r["ours"], r["added"]), reverse=False)
        rows.sort(key=lambda r: r["ours"], reverse=True)
        return {"since": since_day, "stack": self.profile.get("stack", []), "rows": rows}

    def sources(self) -> dict:
        from . import llm

        status = {s["name"]: s for s in self.store.sources()}
        rows = []
        for src in SOURCES:
            st = status.get(src.name, {})
            rows.append({"name": src.name, "kind": src.kind, "desk": src.topic, "url": src.url, "every_min": round(src.every / 60),
                         "reliability": src.reliability, "last_try": st.get("last_try"), "last_ok": st.get("last_ok"),
                         "items": st.get("items"), "new_items": st.get("new_items"), "stored": st.get("stored", 0),
                         "error": st.get("error")})
        from .config import LLM_DAILY_CALLS, LLM_MODEL, LLM_PRICE, gemini_key

        today = self.store.llm_since(llm.day_start())
        cost = today["prompt_tokens"] / 1e6 * LLM_PRICE[0] + today["output_tokens"] / 1e6 * LLM_PRICE[1]
        return {
            "sources": rows,
            "not_read": [{"name": "X (Twitter)", "why": "its API is paid and scraping it breaks its terms; Bluesky and "
                                                       "Mastodon carry much of the same scene"},
                         {"name": "Reddit", "why": "refuses this client (HTTP 403)"},
                         {"name": "Telegram and leak forums", "why": "not read directly; their claims arrive through "
                                                                    "RansomLook and the press"}],
            "model": {"name": LLM_MODEL, "key": bool(gemini_key()), "daily_calls": LLM_DAILY_CALLS, "today": today,
                      "cost_today_usd": round(cost, 4), "states": self.store.count_items()},
            "built_at": self.built_at, "build_seconds": self.build_seconds,
        }


def _updated(i: dict, state: dict | None) -> bool:
    """Told again since the reader last opened it."""
    return bool(state and state.get("seen") and i["last_seen"] > state["seen"] + 60)


def _state(i: dict, state: dict | None) -> dict:
    state = state or {}
    return {"starred": bool(state.get("starred")), "dismissed": bool(state.get("dismissed")), "seen": state.get("seen"),
            "note": state.get("note"), "updated": _updated(i, state)}


def _brief(i: dict, state: dict | None = None) -> dict:
    return {k: i[k] for k in ("id", "title", "summary", "category", "first_seen", "last_seen", "relevance", "kinds",
                              "sources", "victims", "attackers", "vendors", "headline_usd", "headline_kind", "records",
                              "countries", "topics", "roundup")} | {
        "reasons": i["reasons"], "cves": [c["id"] for c in i["cves"]][:6], "kev": any(c["kev"] for c in i["cves"]),
        "items": len(i["items"]), "url": next((it["url"] for it in i["items"] if it.get("url")), None),
        "state": _state(i, state),
    }


def _sector_from(info: dict) -> str | None:
    words = " ".join(info.get("industry") or []).lower() + " " + (info.get("description") or "").lower()
    for sector, keys in (("defense", ("defence", "defense", "arms")), ("aerospace", ("aerospace", "aircraft", "aviation")),
                         ("finance", ("bank", "financ", "insur")), ("health", ("health", "hospital", "pharma")),
                         ("telecom", ("telecom",)), ("retail", ("retail",)), ("automotive", ("automo", "vehicle")),
                         ("energy", ("energy", "oil", "electric")), ("gaming", ("video game",)),
                         ("education", ("universit", "school", "education")), ("government", ("government", "agency")),
                         ("technology", ("software", "technology", "internet", "computer"))):
        if any(k in words for k in keys):
            return sector
    return None
