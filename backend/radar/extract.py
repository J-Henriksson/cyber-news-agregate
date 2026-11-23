"""What the rules find in one item, without a model: its kind of story,
the known groups and companies it names, CVE ids, countries, amounts and
how many people or records it says were hit. A structured source (a leak
site, a breach list, a filing) says its victim outright, and that is
taken as said.

The result has the same shape as the model's (llm.py), so the two merge:
``category``, ``entities`` ([{name, type, role, sector, country}]),
``money``, ``records``, ``countries``, ``cves``, ``summary``."""

from __future__ import annotations

import re

from .gazetteer import MATCHER, SECURITY_CATEGORIES, category_of, find_countries, is_ai
from .money import find_amounts

#: Bump when the rules change: stored items are read again at the next start.
RULES_VERSION = 7

CVE = re.compile(r"\bCVE-\d{4}-\d{4,7}\b", re.I)
_RECORDS = re.compile(
    r"(?P<num>\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)\s?(?P<mult>million|billion|thousand|[mkb](?![a-z]))?\s+"
    r"(?:\w+\s){0,2}(?P<what>records|accounts|users|customers|people|individuals|patients|subscribers|members|employees|emails)",
    re.I,
)
_MULT = {"thousand": 1e3, "k": 1e3, "million": 1e6, "m": 1e6, "billion": 1e9, "b": 1e9}

#: Structured kinds whose category is the kind itself.
KIND_CATEGORY = {"ransomware": "ransomware", "breach": "breach", "crypto": "crypto", "vuln": "vulnerability",
                 "filing": "breach", "tool": "tool", "research": "tool"}


def records_in(text: str) -> int | None:
    best = None
    for m in _RECORDS.finditer(text):
        n = float(m.group("num").replace(",", ""))
        if m.group("mult"):
            n *= _MULT.get(m.group("mult").lower(), 1)
        if n >= 100 and (best is None or n > best):
            best = int(n)
    return best


def rules_of(item: dict) -> dict:
    title = item.get("title") or ""
    body = item.get("text") or ""
    text = f"{title}. {body}"
    data = item.get("data") or {}
    kind = item.get("kind")
    entities: list[dict] = []

    def add(name: str, type_: str, role: str, sector: str | None = None, country: str | None = None) -> None:
        if not name:
            return
        known = MATCHER.canonical(name)
        if known:
            name, sector, country = known.name, sector or known.sector, country or known.country
            type_ = known.type
        for e in entities:
            if e["name"].lower() == name.lower():
                if e["role"] == "mentioned" and role != "mentioned":
                    e["role"] = role
                return
        entities.append({"name": name, "type": type_, "role": role, "sector": sector, "country": country})

    # What a structured source states outright.
    if kind == "ransomware":
        add(data.get("victim", ""), "company", "victim", country=data.get("country"))
        add(data.get("group", ""), "actor", "attacker")
    elif kind == "breach":
        add(data.get("victim", ""), "company", "victim")
    elif kind == "crypto":
        add(data.get("victim", ""), "company", "victim", sector="crypto")
    elif kind == "filing":
        add(data.get("company", ""), "company", "victim", country="United States")
    elif kind == "vuln":
        add(data.get("vendor", ""), "company", "vendor")

    for known in MATCHER.find(text):
        role = "attacker" if known.type in ("actor", "person") else "mentioned"
        add(known.name, known.type, role, known.sector, known.country)

    cves = sorted({c.upper() for c in CVE.findall(text)} | ({data["cve"]} if data.get("cve") else set()))
    # A leak-site post describes its victim (revenue, staff): no damage in it.
    # A paper's or a repository's figures are statistics, not an incident's money.
    money = [] if kind in ("ransomware", "research", "tool") else find_amounts(text)
    if data.get("amount_usd"):
        stated = float(data["amount_usd"])
        money = [{"amount": stated, "currency": "USD", "kind": "theft",
                  "quote": f"{data.get('victim', '')}: {data['amount_usd']:,} USD lost ({data.get('technique') or 'technique not given'})",
                  "stated_by_source": True}] + [m for m in money if abs(m["amount"] - stated) > 0.01 * stated]
    records = data.get("pwn_count") or records_in(text)
    category = KIND_CATEGORY.get(kind) or category_of(text)
    # An AI source's story is AI news unless it is security (a flaw, a breach...).
    if data.get("topic") == "ai" and kind not in ("tool", "research") and category not in SECURITY_CATEGORIES:
        category = "ai"
    return {
        # A security story is on the AI desk too when its headline or opening says AI, not a passing mention.
        "ai": data.get("topic") == "ai" or is_ai(f"{title}. {body[:300]}"),
        "category": category,
        "entities": entities,
        "money": money,
        "records": records,
        "countries": find_countries(text),
        "cves": cves,
        "summary": None,
        "by": "rules",
    }
