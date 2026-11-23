"""The companies around a company, from Wikidata: its parent and owners,
its subsidiaries, its industry, country, staff and stock listing. Looked
up for the companies the incidents name, a few per round, and kept for a
fortnight (a name Wikidata does not know is kept as unknown too).

A name is matched to Wikidata's best search hit whose kind is a company
or organisation; a name that is also a person or a place is left alone
rather than guessed."""

from __future__ import annotations

import logging
import time

import httpx

from .config import USER_AGENT
from .text import norm_name

log = logging.getLogger(__name__)

API = "https://www.wikidata.org/w/api.php"
KEEP_S = 14 * 86400
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


def lookup(client: httpx.Client, name: str) -> dict | None:
    """The company a name is, with the companies around it, or None."""
    found = client.get(API, params={"action": "wbsearchentities", "search": name, "language": "en", "type": "item",
                                    "limit": 5, "format": "json"}).json().get("search", [])
    if not found:
        return None
    ids = [h["id"] for h in found]
    ents = client.get(API, params={"action": "wbgetentities", "ids": "|".join(ids), "props": "claims|labels|descriptions",
                                   "languages": "en", "format": "json"}).json().get("entities", {})
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
        got = client.get(API, params={"action": "wbgetentities", "ids": "|".join(want), "props": "labels", "languages": "en",
                                      "format": "json"}).json().get("entities", {})
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


def enrich(store, names: list[str], max_new: int = 12) -> int:
    """Look up the names not yet known (or known too long ago), at most
    ``max_new`` in one round. Returns how many were looked up."""
    todo = []
    for name in names:
        key = norm_name(name)
        if key and store.get(f"wd:{key}", KEEP_S) is None and key not in [norm_name(t) for t in todo]:
            todo.append(name)
        if len(todo) >= max_new:
            break
    if not todo:
        return 0
    with httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=20) as client:
        for name in todo:
            try:
                found = lookup(client, name)
            except (httpx.HTTPError, ValueError) as err:
                log.info("wikidata %s: %s", name, err)
                continue
            store.put(f"wd:{norm_name(name)}", found or {"unknown": True}, bump=bool(found))
            time.sleep(0.3)
    return len(todo)
