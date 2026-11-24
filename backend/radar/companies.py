"""The companies around a company, from Wikidata: its parent and owners,
its subsidiaries, its industry, country, staff and stock listing. Looked
up for the companies the incidents name, a few per round, and kept for a
fortnight (a name Wikidata does not know is kept as unknown too).

A name is matched to Wikidata's best search hit whose kind is a company
or organisation; a name that is also a person or a place is left alone
rather than guessed.

Wikimedia asks a script to say what it is and how to reach whoever runs
it, and turns away one that poses as a browser. So this reader names
itself, adds RADAR_CONTACT when .env gives one, asks one thing at a time,
and when it is refused it stops and waits rather than ask again."""

from __future__ import annotations

import logging
import time

import httpx

from . import config
from .text import norm_name

log = logging.getLogger(__name__)

API = "https://www.wikidata.org/w/api.php"
KEEP_S = 14 * 86400
#: Where the store keeps until when Wikidata is left alone, and why.
WAIT_KEY = "wikidata_wait"
#: Not asked again for this long after a refusal, and after a request that did not get through.
REFUSED_S = 3600.0
FAILED_S = 300.0
#: Between two names (Wikimedia: one request at a time, well under five a second).
PAUSE_S = 1.0
#: Instance-of values that make a hit a company or an organisation outright.
ORG_KINDS = frozenset((
    "Q4830453", "Q783794", "Q6881511", "Q891723", "Q167037", "Q161726", "Q1058914", "Q18388277", "Q1589009",
    "Q219577", "Q22687", "Q43229", "Q210167", "Q786820",
))
#: Otherwise: a description with one of these words, and the claims a firm has.
ORG_WORDS = ("company", "corporation", "manufacturer", "business", "bank", "firm", "enterprise", "conglomerate",
             "developer", "publisher", "retailer", "airline", "operator", "provider", "group", "organization",
             "organisation", "agency", "brand", "chain", "insurer", "carrier", "maker", "exchange", "platform")
FIRM_CLAIMS = ("P452", "P159", "P1128", "P414")
PROPS = {"P749": "parent", "P127": "owned_by", "P355": "subsidiaries", "P452": "industry", "P17": "country",
         "P414": "exchange", "P159": "headquarters"}


def _claims_ids(entity: dict, prop: str) -> list[str]:
    out = []
    for c in entity.get("claims", {}).get(prop, []):
        v = c.get("mainsnak", {}).get("datavalue", {}).get("value")
        if isinstance(v, dict) and v.get("id"):
            out.append(v["id"])
    return out


def _quantity(entity: dict, prop: str) -> float | None:
    best = None
    for c in entity.get("claims", {}).get(prop, []):
        v = c.get("mainsnak", {}).get("datavalue", {}).get("value")
        if isinstance(v, dict) and "amount" in v:
            try:
                best = float(v["amount"])
            except ValueError:
                pass
    return best


def user_agent() -> str:
    """What this reader says it is: its name, a way to reach whoever runs
    it if .env gives one, and its library. Never a browser's name."""
    who = f" ({config.contact()})" if config.contact() else ""
    return f"cyber-news-agregate/0.1{who} python-httpx/{httpx.__version__}"


def _ask(client: httpx.Client, **params) -> dict:
    """One question to Wikidata. A refusal is raised as what it is, not as an answer that will not parse."""
    r = client.get(API, params={**params, "format": "json"})
    r.raise_for_status()
    return r.json()


def lookup(client: httpx.Client, name: str) -> dict | None:
    """The company a name is, with the companies around it, or None."""
    found = _ask(client, action="wbsearchentities", search=name, language="en", type="item", limit=5).get("search", [])
    if not found:
        return None
    ids = [h["id"] for h in found]
    ents = _ask(client, action="wbgetentities", ids="|".join(ids), props="claims|labels|descriptions",
                languages="en").get("entities", {})
    hit = None
    for qid in ids:
        e = ents.get(qid) or {}
        desc = ((e.get("descriptions", {}).get("en") or {}).get("value") or "").lower()
        firm = any(e.get("claims", {}).get(p) for p in FIRM_CLAIMS)
        if ORG_KINDS & set(_claims_ids(e, "P31")) or (firm and any(w in desc for w in ORG_WORDS)):
            hit = e
            break
    if hit is None:
        return None
    refs = {p: _claims_ids(hit, p) for p in PROPS}
    want = sorted({q for qs in refs.values() for q in qs})[:50]
    labels = {}
    if want:
        got = _ask(client, action="wbgetentities", ids="|".join(want), props="labels", languages="en").get("entities", {})
        labels = {q: (v.get("labels", {}).get("en") or {}).get("value", q) for q, v in got.items()}
    named = {key: [labels.get(q, q) for q in refs[p]] for p, key in PROPS.items()}
    return {
        "qid": hit["id"],
        "label": (hit.get("labels", {}).get("en") or {}).get("value", name),
        "description": (hit.get("descriptions", {}).get("en") or {}).get("value"),
        "url": f"https://www.wikidata.org/wiki/{hit['id']}",
        "parent": named["parent"][:3] + [o for o in named["owned_by"][:3] if o not in named["parent"]],
        "subsidiaries": named["subsidiaries"][:25],
        "industry": named["industry"][:3],
        "country": (named["country"] or [None])[0],
        "exchange": named["exchange"][:2],
        "employees": _quantity(hit, "P1128"),
    }


def status(store) -> dict:
    """How the lookups stand, for the Sources view: how many companies are
    known, and if Wikidata is being left alone, why and until when."""
    records = store.get_many("wd:")
    wait = store.get(WAIT_KEY) or {}
    waiting = (wait.get("until") or 0) > time.time()
    return {"known": sum(1 for v in records.values() if not v.get("unknown")), "asked": len(records),
            "error": wait.get("error") if waiting else None, "until": wait.get("until") if waiting else None,
            "contact": bool(config.contact())}


def _refused(err: Exception) -> tuple[str, float]:
    """What went wrong, in a few words, and how long to leave Wikidata alone for it."""
    if isinstance(err, httpx.HTTPStatusError):
        wait = REFUSED_S
        try:
            # Its own word on when to come back counts, if it is longer.
            wait = max(wait, float(err.response.headers.get("retry-after", "")))
        except ValueError:
            pass
        return f"HTTP {err.response.status_code}", min(wait, 86400.0)
    return (str(err) or type(err).__name__)[:120], FAILED_S


def enrich(store, names: list[str], max_new: int = 12) -> int:
    """Look up the names not yet known (or known too long ago), at most
    ``max_new`` in one round. Returns how many were looked up. After a
    refusal or a failure nothing is asked until the wait is over: the same
    names asked again every round is what gets a reader turned away."""
    wait = store.get(WAIT_KEY) or {}
    if (wait.get("until") or 0) > time.time():
        return 0
    todo = []
    for name in names:
        key = norm_name(name)
        if key and store.get(f"wd:{key}", KEEP_S) is None and key not in [norm_name(t) for t in todo]:
            todo.append(name)
        if len(todo) >= max_new:
            break
    if not todo:
        return 0
    done = 0
    with httpx.Client(headers={"User-Agent": user_agent()}, timeout=20) as client:
        for name in todo:
            try:
                found = lookup(client, name)
            except (httpx.HTTPError, ValueError) as err:
                why, wait_s = _refused(err)
                store.put(WAIT_KEY, {"until": time.time() + wait_s, "error": why})
                log.warning("wikidata: %s; not asked again for %d min", why, wait_s // 60)
                return done
            store.put(f"wd:{norm_name(name)}", found or {"unknown": True}, bump=bool(found))
            done += 1
            time.sleep(PAUSE_S)
    if wait:
        store.put(WAIT_KEY, {})
    return done
