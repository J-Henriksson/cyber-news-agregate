"""From items to incidents. Twenty outlets on one breach, the gang's own
leak-site post and the company's SEC filing are one incident with many
sources. Items join when they share a victim within a fortnight (and say
something alike about it), are each about the same one CVE, or, from
different sources within a few days, carry nearly the same headline, two
uncommon words one of which is a name, or a flaw of the same seldom-named
maker. A digest of many stories joins nothing.

Each item's facts are first merged from the rules and the model
(``merged``); an incident then gathers its items' facts."""

from __future__ import annotations

import hashlib
import math
import re
from collections import Counter, defaultdict

from .extract import KIND_CATEGORY
from .gazetteer import MATCHER, ROUNDUP, SECURITY_CATEGORIES
from .llm import _ABOUT_ITSELF, LLM_VERSION
from .money import DAMAGE_KINDS, to_usd
from .sources import paywalled
from .text import jaccard, norm_name, tokens

DAY = 86400.0
STRUCTURED = ("ransomware", "breach", "crypto", "filing", "vuln")
NEWSLIKE = ("news", "advisory", "community")
#: Which item's headline names the incident, best first.
TITLE_ORDER = ("news", "advisory", "filing", "breach", "ransomware", "crypto", "vuln", "community", "research", "tool", "social")
#: Victims that are no one in particular.
GENERIC = frozenset("""users customers people individuals victims organizations organisations companies businesses
    government governments employees members patients students the company firms agencies banks hospitals""".split())


def merged(item: dict) -> dict:
    """One item's facts: the rules' and the model's together. The model's
    roles, kinds and summary win; a structured source's own statements
    (its victim, its amount) always stand."""
    rules = item.get("rules") or {}
    model = item.get("llm") or {}
    # A reading from before the answers were checked against their item is not used.
    if model and (model.get("v") or 1) < LLM_VERSION:
        model = {}
    entities: dict[str, dict] = {}
    for e in (rules.get("entities") or []) + (model.get("entities") or []):
        known = MATCHER.canonical(e["name"])
        if known and known.name != e["name"]:
            e = {**e, "name": known.name, "sector": e.get("sector") or known.sector, "country": e.get("country") or known.country}
        key = e["name"].lower()
        had = entities.get(key)
        if had is None:
            entities[key] = dict(e)
        else:
            if e.get("role") and e["role"] not in ("mentioned", "other") and had.get("role") in ("mentioned", "other", None):
                had["role"] = e["role"]
            had["sector"] = had.get("sector") or e.get("sector")
            had["country"] = had.get("country") or e.get("country")
    kind = item["kind"]
    from_ai = (item.get("data") or {}).get("topic") == "ai"
    category = KIND_CATEGORY.get(kind) or (
        model.get("category") if model.get("category") not in (None, "other") else rules.get("category", "other")
    )
    if from_ai and category in ("other", "policy") and kind not in ("tool", "research"):
        category = "ai"
    # An agency's advisory that names CVEs is about flaws, whatever words it uses.
    if kind == "advisory" and (rules.get("cves") or []):
        category = "vulnerability"
    topics = set()
    if from_ai or rules.get("ai") or category == "ai":
        topics.add("ai")
    if category in SECURITY_CATEGORIES or (not from_ai and category != "ai"):
        topics.add("cyber")
    stated = [m for m in rules.get("money") or [] if m.get("stated_by_source")]
    money = stated + (model.get("money") if model else [m for m in rules.get("money") or [] if not m.get("stated_by_source")])
    cves = set(rules.get("cves") or []) | {v.upper() for v in model.get("via") or [] if v.upper().startswith("CVE-")}
    countries = set(rules.get("countries") or []) | {e["country"] for e in entities.values() if e.get("country")}
    return {
        "category": category or "other",
        "summary": None if _ABOUT_ITSELF.search(model.get("summary") or "") else model.get("summary"),
        "entities": list(entities.values()),
        "money": money,
        "records": (item.get("data") or {}).get("pwn_count") or model.get("records") or rules.get("records"),
        "cves": sorted(cves),
        "countries": sorted(countries),
        "via": [v for v in model.get("via") or [] if not v.upper().startswith("CVE-")],
        "read_by": "model" if model else "rules",
        "topics": sorted(topics),
    }


class _Union:
    def __init__(self, n: int):
        self.parent = list(range(n))

    def find(self, i: int) -> int:
        while self.parent[i] != i:
            self.parent[i] = self.parent[self.parent[i]]
            i = self.parent[i]
        return i

    def join(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[max(ra, rb)] = min(ra, rb)


def _victims(item: dict, facts: dict) -> set[str]:
    out = set()
    for e in facts["entities"]:
        if e.get("role") == "victim":
            n = norm_name(e["name"])
            if n and n not in GENERIC and len(n) > 2:
                out.add(n)
    return out


_WORD = re.compile(r"[\w&'.\-]+")


def _named_in(text: str, names: dict, firsts: set[str]) -> set[str]:
    """The names (normalised) that a text writes out: runs of one to four
    words. A single word counts only when capitalised and six letters or
    more, so "Global" or "Delta" in a sentence is not a victim."""
    words = _WORD.findall(text)
    out = set()
    for k, w in enumerate(words):
        if w.lower().strip(".,'") not in firsts:
            continue
        for n in range(1, 5):
            gram = " ".join(words[k:k + n])
            key = norm_name(gram)
            if key in names and (n >= 2 or (len(key) >= 6 and gram[:1].isupper())):
                out.add(key)
    return out


#: A word in more headlines than this within four days either side is common.
RARE_DF = 8
#: Headlines this alike (share of their words in common) are one story.
ALIKE = 0.45
#: A vendor named as the flawed product's maker in more items than this
#: within three days either side is too common to join stories by.
RARE_VENDOR = 6
#: An item naming more victims than this is a digest of several stories.
MANY_VICTIMS = 4
_TITLE_WORD = re.compile(r"[A-Za-z0-9][\w$.\-]*")


def _join_alike_titles(items: list[dict], newsish: list[int], toks: list[set[str]], u: "_Union") -> None:
    """Join news-like items of different sources whose headlines share
    ALIKE of their words within four days. Candidates come from an index
    of each headline's rarest words (two sets that alike must share one of
    them), so a quarter of a year of headlines is not compared pair by pair."""
    df = Counter(w for i in newsish for w in toks[i])
    index: dict[str, list[int]] = defaultdict(list)
    for i in newsish:
        words = sorted(toks[i], key=lambda w: (df[w], w))
        if not words:
            continue
        prefix = words[: len(words) - math.ceil(ALIKE * len(words)) + 1]
        t = items[i].get("published") or 0
        candidates: set[int] = set()
        for w in prefix:
            for j in reversed(index[w]):
                if t - (items[j].get("published") or 0) > 4 * DAY:
                    break
                candidates.add(j)
        for j in candidates:
            if items[i]["source"] != items[j]["source"] and jaccard(toks[i], toks[j]) >= ALIKE:
                u.join(i, j)
        for w in prefix:
            index[w].append(i)


def _namelike(title: str, own: set[str], entity_words: set[str]) -> set[str]:
    """The words of a headline that are names: written with a digit or an
    inner capital (vCenter, Java4Shell), part of a name found in the item,
    or capitalised mid-sentence in a headline that is not in title case.
    "Child", "abuse" and "material" are words; "Drupal" is a name."""
    words = _TITLE_WORD.findall(title)
    capped = sum(1 for w in words if w[:1].isupper())
    title_case = len(words) >= 4 and capped / len(words) > 0.7
    out = set()
    for k, w in enumerate(words):
        for token in tokens(w) & own:
            inner = any(c.isupper() for c in w[1:]) or any(c.isdigit() for c in w)
            if inner or token in entity_words or (not title_case and k > 0 and w[:1].isupper()):
                out.add(token)
    return out


def _join_by_rare_words(items: list[dict], newsish: list[int], toks: list[set[str]], facts: list[dict], u: "_Union") -> None:
    """Join headlines worded apart that share two uncommon words of those
    days, one of them a name ("VMware vCenter zero-day" told five ways)."""
    day_of = {i: int((items[i].get("published") or 0) // DAY) for i in newsish}
    per_day: dict[int, Counter] = defaultdict(Counter)
    for i in newsish:
        per_day[day_of[i]].update(toks[i])

    def local_df(word: str, day: int) -> int:
        return sum(per_day[d][word] for d in range(day - 4, day + 5) if d in per_day)

    rare_of = {i: {w for w in toks[i] if local_df(w, day_of[i]) <= RARE_DF} for i in newsish}
    holders: dict[str, list[int]] = defaultdict(list)
    for i in newsish:
        for w in rare_of[i]:
            holders[w].append(i)
    shared: dict[tuple[int, int], set[str]] = defaultdict(set)
    for word, idx in holders.items():
        if len(idx) < 2:
            continue
        for a in range(len(idx)):
            for b in range(a + 1, len(idx)):
                i, j = idx[a], idx[b]
                if abs(day_of[i] - day_of[j]) <= 4 and items[i]["source"] != items[j]["source"]:
                    shared[(i, j)].add(word)
    names: dict[int, set[str]] = {}

    def names_of(i: int) -> set[str]:
        if i not in names:
            entity_words = tokens(" ".join(e["name"] for e in facts[i]["entities"]))
            names[i] = _namelike(items[i].get("title") or "", toks[i], entity_words)
        return names[i]

    for (i, j), words in shared.items():
        if len(words) >= 2 and words & (names_of(i) | names_of(j)) and jaccard(toks[i], toks[j]) >= 0.15:
            u.join(i, j)


def _join_by_rare_vendor(items: list[dict], newsish: list[int], facts: list[dict], u: "_Union") -> None:
    """Join stories about a flaw in the same maker's product within three
    days, when few stories of those days are about that maker ("Drupal
    patches a critical flaw" told with no word in common but Drupal)."""
    holders: dict[str, list[int]] = defaultdict(list)
    for i in newsish:
        if facts[i]["category"] != "vulnerability":
            continue
        for e in facts[i]["entities"]:
            if e.get("role") == "vendor":
                holders[norm_name(e["name"])].append(i)
    for vendor, idx in holders.items():
        if not vendor or len(idx) < 2:
            continue
        for a in range(len(idx)):
            i = idx[a]
            ti = items[i].get("published") or 0
            near = [j for j in idx if abs((items[j].get("published") or 0) - ti) <= 3 * DAY]
            if len(near) > RARE_VENDOR:
                continue
            for j in near:
                if j != i and items[i]["source"] != items[j]["source"]:
                    u.join(i, j)


def cluster(items: list[dict], kev: dict[str, dict] | None = None, epss: dict[str, dict] | None = None,
            per_eur: dict[str, float] | None = None) -> list[dict]:
    """Incidents from items (each with ``rules`` and ``llm``)."""
    items = sorted(items, key=lambda it: it.get("published") or 0)
    facts = [merged(it) for it in items]
    toks = [tokens(it.get("title") or "") for it in items]
    victims = [_victims(it, f) for it, f in zip(items, facts)]
    actors = [{norm_name(e["name"]) for e in f["entities"] if e.get("type") in ("actor", "person")} for f in facts]
    # A digest tells many stories: it joins none of them (it would chain them all into one).
    digest = [bool(ROUNDUP.search(it.get("title") or "")) or len(v) > MANY_VICTIMS for it, v in zip(items, victims)]
    u = _Union(len(items))

    # An agency's advisories for one vendor on one day are one batch (the
    # vendor is the headline's first word, unless that is the agency itself).
    # A batch stands on its own: one of fourteen Siemens advisories naming
    # the Brotli flaw pulled all fourteen into the Brotli story (2026-11-20).
    # The shared flaw still shows them as related incidents.
    batches: dict[tuple, list[int]] = defaultdict(list)
    for i, it in enumerate(items):
        if it["kind"] == "advisory" and not digest[i]:
            first = (it.get("title") or "").split(" ", 1)[0].lower()
            if first and first != it["source"].split(" ", 1)[0].lower():
                batches[(it["source"], first, int((it.get("published") or 0) // DAY))].append(i)
    for members in batches.values():
        if len(members) >= 2:
            for i in members:
                digest[i] = True
                u.join(i, members[0])

    by_victim: dict[str, list[int]] = defaultdict(list)
    by_cve: dict[str, list[int]] = defaultdict(list)
    for i, it in enumerate(items):
        if digest[i]:
            continue
        t = it.get("published") or 0
        structured = it["kind"] in STRUCTURED
        for v in victims[i]:
            for j in reversed(by_victim[v]):
                if t - (items[j].get("published") or 0) > 14 * DAY:
                    break
                alike = (structured or items[j]["kind"] in STRUCTURED or jaccard(toks[i], toks[j]) >= 0.12
                         or actors[i] & actors[j] or set(facts[i]["cves"]) & set(facts[j]["cves"]))
                if alike:
                    u.join(i, j)
            by_victim[v].append(i)
        cves = facts[i]["cves"]
        # Only an item about one flaw joins by it: roundups of three each
        # chained a month of unrelated flaws into one incident.
        if len(cves) == 1:
            for c in cves:
                for j in by_cve[c]:
                    if t - (items[j].get("published") or 0) <= 45 * DAY:
                        u.join(i, j)
                by_cve[c].append(i)
    # A story that names a victim a leak site, a breach list or a filing
    # stated: one incident, whether or not anything read the story's roles.
    stated: dict[str, list[int]] = defaultdict(list)
    for i, it in enumerate(items):
        if it["kind"] in ("ransomware", "breach", "crypto", "filing"):
            for v in victims[i]:
                stated[v].append(i)
    if stated:
        firsts = {v.split(" ", 1)[0] for v in stated}
        for i, it in enumerate(items):
            if it["kind"] not in NEWSLIKE + ("social",) or digest[i]:
                continue
            # Named in the headline, or read as the victim: a body that only
            # mentions Binance is not the Binance theft.
            title = it.get("title") or ""
            named = victims[i] | _named_in(title, stated, firsts) | {
                norm_name(e["name"]) for e in facts[i]["entities"] if e["name"].lower() in title.lower()}
            t = it.get("published") or 0
            for v in named & stated.keys():
                for j in stated[v]:
                    if abs(t - (items[j].get("published") or 0)) <= 14 * DAY:
                        u.join(i, j)
    # By their headlines: news-like items only (two short posts alike in
    # words are not one story), and never two items of one source (a
    # source's series, "CISA Adds One Known Exploited Vulnerability to
    # Catalog", is the same headline every week).
    newsish = [i for i, it in enumerate(items) if it["kind"] in NEWSLIKE and not digest[i]]
    _join_alike_titles(items, newsish, toks, u)
    _join_by_rare_words(items, newsish, toks, facts, u)
    _join_by_rare_vendor(items, newsish, facts, u)
    groups: dict[int, list[int]] = defaultdict(list)
    for i in range(len(items)):
        groups[u.find(i)].append(i)
    return [_incident([items[i] for i in idx], [facts[i] for i in idx], kev or {}, epss or {}, per_eur or {})
            for idx in groups.values()]


def _incident(items: list[dict], facts: list[dict], kev: dict, epss: dict, per_eur: dict) -> dict:
    best = min(range(len(items)), key=lambda i: (TITLE_ORDER.index(items[i]["kind"]) if items[i]["kind"] in TITLE_ORDER else 99,
                                                 items[i].get("published") or 0))
    structured = [f["category"] for it, f in zip(items, facts) if it["kind"] in STRUCTURED]
    votes = Counter(f["category"] for f in facts if f["category"] != "other")
    category = structured[0] if structured else (votes.most_common(1)[0][0] if votes else "other")

    entities: dict[str, dict] = {}
    for it, f in zip(items, facts):
        for e in f["entities"]:
            key = norm_name(e["name"]) or e["name"].lower()
            had = entities.setdefault(key, {"name": e["name"], "type": e.get("type") or "company", "roles": set(),
                                            "sector": None, "country": None, "items": 0})
            if e.get("role"):
                had["roles"].add(e["role"])
            had["sector"] = had["sector"] or e.get("sector")
            had["country"] = had["country"] or e.get("country")
            had["items"] += 1
    ents = []
    for e in entities.values():
        roles = e["roles"] - {"mentioned", "other"}
        role = next((r for r in ("victim", "attacker", "vendor") if r in roles), "mentioned")
        ents.append({**{k: v for k, v in e.items() if k != "roles"}, "role": role})

    money, seen = [], set()
    for it, f in zip(items, facts):
        for m in f["money"]:
            usd = to_usd(m["amount"], m["currency"], per_eur) if per_eur else (m["amount"] if m["currency"] == "USD" else None)
            key = round(usd or m["amount"], -4)
            if key in seen:
                # The same amount told twice: keep the telling that says what kind it is.
                had = next(x for x in money if round(x.get("usd") or x["amount"], -4) == key)
                if had["kind"] == "other" and m["kind"] != "other":
                    had.update({**m, "usd": usd, "item": it["id"], "source": it["source"]})
                continue
            seen.add(key)
            money.append({**m, "usd": usd, "item": it["id"], "source": it["source"]})
    damage = [m for m in money if m["kind"] in DAMAGE_KINDS and m.get("usd")]
    headline = max(damage, key=lambda m: m["usd"]) if damage else None

    cves = sorted({c for f in facts for c in f["cves"]})
    cve_rows = [{"id": c, "kev": c in kev, "ransomware_use": (kev.get(c) or {}).get("ransomware_use"),
                 "epss": (epss.get(c) or {}).get("epss"), "percentile": (epss.get(c) or {}).get("percentile"),
                 "vendor": (kev.get(c) or {}).get("vendor"), "product": (kev.get(c) or {}).get("product")} for c in cves]
    # Under a hundred it is a sentence misread ("4 records"), not the size of a breach.
    records = max((f["records"] for f in facts if (f.get("records") or 0) >= 100), default=None)
    first = items[0].get("published") or 0
    sources = sorted({it["source"] for it in items})
    title = items[best].get("title") or ""
    summary = next((f["summary"] for f in facts if f.get("summary")), None)
    if len(items) > 1 and all(it["kind"] == "advisory" for it in items) and len(sources) == 1:
        vendor = title.split(" ", 1)[0]
        title = f"{vendor}: {len(items)} advisories from {sources[0]}"
        summary = "; ".join((it.get("title") or "") for it in items[:8]) + (" ..." if len(items) > 8 else "")
    return {
        "id": hashlib.sha1(items[0]["id"].encode()).hexdigest()[:12],
        "title": title,
        "summary": summary,
        # For scoring only (the API leaves keys starting with _ out).
        "_text": " ".join(f"{it.get('title') or ''}. {(it.get('text') or '')[:700]}" for it in items[:12]),
        "category": category,
        "first_seen": first,
        "last_seen": max(it.get("published") or 0 for it in items),
        "kinds": sorted({it["kind"] for it in items}),
        "sources": sources,
        "items": [{"id": it["id"], "source": it["source"], "kind": it["kind"], "title": it.get("title"), "url": it.get("url"),
                   "published": it.get("published"), "read_by": f["read_by"], "data": it.get("data") or {},
                   "paywall": paywalled(it.get("url"))}
                  for it, f in zip(items, facts)],
        "roundup": bool(ROUNDUP.search(items[best].get("title") or "")),
        "entities": sorted(ents, key=lambda e: (-e["items"], e["name"])),
        "victims": [e["name"] for e in ents if e["role"] == "victim"],
        "attackers": [e["name"] for e in ents if e["role"] == "attacker"],
        "vendors": [e["name"] for e in ents if e["role"] == "vendor"],
        "cves": cve_rows,
        "money": sorted(money, key=lambda m: -(m.get("usd") or 0)),
        "headline_usd": headline["usd"] if headline else None,
        "headline_kind": headline["kind"] if headline else None,
        "records": records,
        "countries": sorted({c for f in facts for c in f["countries"]}),
        "via": sorted({v for f in facts for v in f.get("via") or []}),
        "read_by_model": sum(1 for f in facts if f["read_by"] == "model"),
        "topics": sorted({t for f in facts for t in f["topics"]}) or ["cyber"],
    }
