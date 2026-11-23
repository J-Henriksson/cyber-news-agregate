"""The graph's four lenses. One network of everything was a hairball that
answered nothing in particular; each lens is built for one question.

    us          Why does this matter to us?  Our organisation in the
                middle, around it the parts of the profile that matched
                (software we run, groups we watch, the tools we build on...),
                and on each the incidents it gave points to.
    links       What is connected?  Incidents and only what joins two or
                more of them: a company hit twice, a group, a flaw. What an
                incident shares with nothing is left to the feed.
    companies   Which companies are tied together?  Hit in the same
                incident (many at once: the incident stands between them),
                hit through another's product, or owned by one another
                (Wikidata). Those that matter to us but are tied to no
                other stand apart.
    groups      Who hits whom?  Each group and the organisations it hit.

Every node carries the same measures (``relevance``, ``usd``, ``reports``,
``incidents``), so the page sizes by whichever the reader picks, and
``ours`` when the profile names it. Ids are stable across lenses:
``i:<incident>``, ``e:<name>``, ``c:<cve>``, ``f:<facet>:<name>``, ``us``."""

from __future__ import annotations

from collections import Counter, defaultdict

from .gazetteer import placeholder
from .relevance import SECURITY, Scorer
from .text import norm_name

LENSES = ("us", "links", "companies", "groups")
#: The parts of the profile, in the order they stand around "us": the
#: heading over a part, and what one node of it is.
FACETS: dict[str, tuple[str, str]] = {
    "tool": ("Tools we build on", "a tool we build on"),
    "supplier": ("Suppliers", "a supplier"),
    "stack": ("Software we run", "software we run"),
    "authority": ("Authorities", "an authority we answer to"),
    "peer": ("Peers", "a peer"),
    "actor": ("Groups we watch", "a group we watch"),
    "sector": ("Our sectors", "a sector of ours"),
    "country": ("Our countries", "a country of ours"),
    "interest": ("What we work on", "what the team works on"),
}
ENTITY_KINDS = ("actor", "person", "product", "government")
#: The most CVE dots one incident brings (an article listing twenty flaws is one incident).
CVES_PER_INCIDENT = 6
#: Victims of one group shown; the rest are counted on the group.
VICTIMS_PER_GROUP = 10


def incident_node(inc: dict) -> dict:
    return {"id": f"i:{inc['id']}", "kind": "incident", "label": inc["title"], "category": inc["category"],
            "relevance": inc["relevance"], "usd": inc.get("headline_usd") or 0.0, "reports": len(inc["sources"]),
            "incidents": 1, "last_seen": inc["last_seen"], "claim": set(inc["kinds"]) <= {"social", "ransomware"}}


class _Nodes:
    """The nodes of a graph being built, with each entity's measures summed over its incidents."""

    def __init__(self, scorer: Scorer):
        self.scorer = scorer
        self.by_id: dict[str, dict] = {}
        self._counted: set[tuple[str, str]] = set()

    def incident(self, inc: dict) -> dict:
        key = f"i:{inc['id']}"
        if key not in self.by_id:
            self.by_id[key] = incident_node(inc)
        return self.by_id[key]

    def entity(self, e: dict, inc: dict, role: str) -> dict:
        key = f"e:{norm_name(e['name'])}"
        n = self.by_id.get(key)
        if n is None:
            n = self.by_id[key] = {
                "id": key, "kind": e["type"] if e["type"] in ENTITY_KINDS else "company", "label": e["name"],
                "sector": e.get("sector"), "country": e.get("country"), "relevance": 0, "usd": 0.0, "reports": 0,
                "incidents": 0, "roles": Counter(), "ours": self.scorer.ours(e["name"])}
        self._count(n, inc, role)
        n["sector"] = n["sector"] or e.get("sector")
        n["country"] = n["country"] or e.get("country")
        return n

    def cve(self, c: dict, inc: dict) -> dict:
        key = f"c:{c['id']}"
        n = self.by_id.get(key)
        if n is None:
            n = self.by_id[key] = {"id": key, "kind": "cve", "label": c["id"], "kev": c["kev"], "epss": c.get("epss"),
                                   "sub": " ".join(x for x in (c.get("vendor"), c.get("product")) if x) or None,
                                   "relevance": 0, "usd": 0.0, "reports": 0, "incidents": 0, "roles": Counter(), "ours": None}
        self._count(n, inc, "flaw")
        return n

    def _count(self, n: dict, inc: dict, role: str) -> None:
        if (n["id"], inc["id"]) in self._counted:
            return
        self._counted.add((n["id"], inc["id"]))
        n["incidents"] += 1
        n["reports"] += len(inc["sources"])
        n["relevance"] = max(n["relevance"], inc["relevance"])
        n["roles"][role] += 1
        if role == "victim":
            n["usd"] += inc.get("headline_usd") or 0.0

    def out(self) -> list[dict]:
        rows = []
        for n in self.by_id.values():
            roles = n.pop("roles", None)
            if roles:
                n["role"] = roles.most_common(1)[0][0]
            rows.append(n)
        return rows


def _named(inc: dict) -> list[tuple[dict, str]]:
    """The entities of an incident that say something about it, with the
    part each plays. A company named in passing is noise in a security
    story; in AI news it is what the story is about."""
    out = []
    for e in inc["entities"]:
        about = inc["category"] == "ai" and e["role"] == "mentioned" and e["type"] in ("company", "government", "product")
        if placeholder(e["name"]) or (e["role"] in ("mentioned", "other") and not about):
            continue
        out.append((e, "about" if about else e["role"]))
    return out


def _components(nodes: list[dict], links: list[dict]) -> None:
    """Number each connected part, the largest first (``group``), so the page can lay the parts out side by side."""
    parent = {n["id"]: n["id"] for n in nodes}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for link in links:
        if link["source"] in parent and link["target"] in parent:
            parent[find(link["source"])] = find(link["target"])
    size = Counter(find(n["id"]) for n in nodes)
    order = {root: k for k, (root, _n) in enumerate(sorted(size.items(), key=lambda kv: (-kv[1], kv[0])))}
    for n in nodes:
        n["group"] = order[find(n["id"])]


def _owners(nodes: _Nodes, wd: dict, links: list[dict]) -> None:
    """Ownership between the companies shown (Wikidata). A parent that is
    not in the news itself is drawn only when it ties two of them together."""
    shown = {k: n for k, n in nodes.by_id.items() if n["kind"] == "company"}
    absent: dict[str, list[str]] = defaultdict(list)
    label: dict[str, str] = {}
    for key in shown:
        info = wd.get(key[2:])
        if not info or info.get("unknown"):
            continue
        shown[key]["wikidata"] = info.get("url")
        for parent in info.get("parent") or []:
            pk = f"e:{norm_name(parent)}"
            if pk == key:
                continue
            if pk in shown:
                links.append({"source": pk, "target": key, "kind": "owns", "weight": 1})
            else:
                absent[pk].append(key)
                label[pk] = parent
    for pk, children in absent.items():
        if len(children) >= 2:
            nodes.by_id[pk] = {"id": pk, "kind": "company", "label": label[pk], "sector": None, "country": None,
                               "relevance": max(shown[c]["relevance"] for c in children), "usd": 0.0, "reports": 0,
                               "incidents": 0, "ours": nodes.scorer.ours(label[pk]), "outside": True}
            links.extend({"source": pk, "target": c, "kind": "owns", "weight": 1} for c in children)


def links_lens(radar, incs: list[dict], limit: int) -> dict:
    scorer = Scorer(radar.profile)
    picked = sorted(incs, key=lambda i: -i["relevance"])[:limit]
    uses: dict[str, list[tuple[dict, dict, str]]] = defaultdict(list)
    for inc in picked:
        if inc.get("roundup"):
            continue  # a digest lists unrelated things: what it names ties nothing together
        for e, role in _named(inc):
            uses[f"e:{norm_name(e['name'])}"].append((inc, e, role))
        for c in sorted(inc["cves"], key=lambda c: (not c["kev"], -(c.get("epss") or 0)))[:CVES_PER_INCIDENT]:
            uses[f"c:{c['id']}"].append((inc, c, "flaw"))
    nodes = _Nodes(scorer)
    links: list[dict] = []
    for key, rows in uses.items():
        if len({inc["id"] for inc, _e, _r in rows}) < 2:
            continue  # joins nothing: the incident's own panel shows it
        for inc, e, role in rows:
            nodes.incident(inc)
            node = nodes.cve(e, inc) if key.startswith("c:") else nodes.entity(e, inc, role)
            links.append({"source": node["id"], "target": f"i:{inc['id']}", "kind": role, "weight": 1})
    _owners(nodes, radar.store.get_many("wd:"), links)
    links = _unique(links)
    rows = nodes.out()
    _components(rows, links)
    shown = sum(1 for n in rows if n["kind"] == "incident")
    return {"lens": "links", "nodes": rows, "links": links, "of": len(picked), "alone": len(picked) - shown}


def us_lens(radar, incs: list[dict], limit: int) -> dict:
    scorer = Scorer(radar.profile)
    org = radar.profile.get("organization") or "Us"
    picked = [i for i in sorted(incs, key=lambda i: -i["relevance"]) if any(r.get("facet") for r in i["reasons"])][:limit]
    nodes: dict[str, dict] = {"us": {"id": "us", "kind": "us", "label": org, "relevance": 100, "usd": 0.0, "reports": 0,
                                     "incidents": len(picked), "points": 0}}
    weight: dict[tuple[str, str], float] = defaultdict(float)
    for inc in picked:
        nodes[f"i:{inc['id']}"] = incident_node(inc)
        for r in inc["reasons"]:
            facet = r.get("facet")
            if not facet or r["points"] <= 0:
                continue
            if facet == "us":
                weight[("us", f"i:{inc['id']}")] += r["points"]
                continue
            names = r.get("names") or [FACETS[facet][0]]
            for name in names:
                key = f"f:{facet}:{norm_name(name) or name.lower()}"
                node = nodes.setdefault(key, {"id": key, "kind": "facet", "facet": facet, "label": name,
                                              "sub": FACETS[facet][1], "relevance": 0, "usd": 0.0, "reports": 0,
                                              "incidents": 0, "points": 0.0, "seen": set()})
                node["points"] += r["points"] / len(names)
                node["relevance"] = max(node["relevance"], inc["relevance"])
                if inc["id"] not in node["seen"]:
                    node["seen"].add(inc["id"])
                    node["incidents"] += 1
                    node["reports"] += len(inc["sources"])
                    node["usd"] += inc.get("headline_usd") or 0.0
                weight[(key, f"i:{inc['id']}")] += r["points"] / len(names)
    links = [{"source": a, "target": b, "kind": "why", "weight": round(w, 1)} for (a, b), w in weight.items()]
    for key, node in nodes.items():
        if node["kind"] == "facet":
            node.pop("seen")
            node["points"] = round(node["points"])
            links.append({"source": "us", "target": key, "kind": "ours", "weight": node["points"]})
    order = {f: k for k, f in enumerate(FACETS)}
    rows = sorted(nodes.values(), key=lambda n: (n["kind"] != "us", n["kind"] != "facet", order.get(n.get("facet"), 0),
                                                 -n.get("points", 0), -n["relevance"]))
    return {"lens": "us", "nodes": rows, "links": links, "of": len(incs), "alone": 0,
            "facets": [{"id": f, "label": FACETS[f][0]} for f in FACETS if any(n.get("facet") == f for n in rows)]}


def companies_lens(radar, incs: list[dict], limit: int) -> dict:
    scorer = Scorer(radar.profile)
    nodes = _Nodes(scorer)
    weight: dict[tuple[str, str, str], int] = defaultdict(int)
    many: list[tuple[dict, list[str]]] = []
    orgs = ("company", "government")
    for inc in incs:
        victims = [e for e in inc["entities"] if e["type"] in orgs and e["role"] == "victim" and not placeholder(e["name"])]
        vendors = [e for e in inc["entities"] if e["type"] in orgs and e["role"] == "vendor" and not placeholder(e["name"])]
        for e in victims:
            nodes.entity(e, inc, "victim")
        for e in vendors:
            nodes.entity(e, inc, "vendor")
        if inc.get("roundup"):
            continue  # a digest lists unrelated companies
        keys = list(dict.fromkeys(f"e:{norm_name(e['name'])}" for e in victims))
        through = [k for k in dict.fromkeys(f"e:{norm_name(v['name'])}" for v in vendors[:3]) if k not in keys]
        if through and keys and len(keys) <= 12 and inc["category"] in SECURITY:
            # Hit through another's product: the product's maker is what ties them.
            for v in through:
                for k in keys:
                    weight[(v, k, "through")] += 1
        elif 2 <= len(keys) <= 3:
            for a in range(len(keys)):
                for b in range(a + 1, len(keys)):
                    weight[(*sorted((keys[a], keys[b])), "together")] += 1
        elif 4 <= len(keys) <= 12:
            many.append((inc, keys))
    # Many hit in one incident: the incident itself is drawn between them. A
    # line for every pair of nine companies is thirty-six lines that say one thing.
    told: list[set[str]] = []
    for inc, keys in sorted(many, key=lambda m: (-len(m[1]), -m[0]["relevance"])):
        if any(set(keys) <= had for had in told):
            continue  # the same event told again
        told.append(set(keys))
        hub = nodes.incident(inc)
        for k in keys:
            weight[(hub["id"], k, "together")] += 1
    links = [{"source": a, "target": b, "kind": kind, "weight": w} for (a, b, kind), w in weight.items()]
    tied = {x for link in links for x in (link["source"], link["target"])}
    # The tied companies first, the ones that matter most to us; then the untied ones that matter on their own.
    score = lambda n: (n["relevance"], n["incidents"], n["usd"])  # noqa: E731
    keep = sorted((n for k, n in nodes.by_id.items() if k in tied), key=score, reverse=True)[:limit]
    alone = sorted((n for k, n in nodes.by_id.items() if k not in tied and (n["relevance"] >= 40 or n["ours"])),
                   key=score, reverse=True)[:max(10, limit // 5)]
    kept = {n["id"] for n in keep} | {n["id"] for n in alone}
    total = sum(1 for n in nodes.by_id.values() if n["kind"] != "incident")
    links = [link for link in links if link["source"] in kept and link["target"] in kept]
    # An incident drawn between companies stays only while it still ties two of them.
    ties = Counter(link["source"] for link in links if link["source"].startswith("i:"))
    kept = {k for k in kept if not k.startswith("i:") or ties[k] >= 2}
    nodes.by_id = {k: n for k, n in nodes.by_id.items() if k in kept}
    links = [link for link in links if link["source"] in kept and link["target"] in kept]
    _owners(nodes, radar.store.get_many("wd:"), links)
    links = _unique(links)
    rows = nodes.out()
    # By what is tied together, not by sector: a sector's companies pulled apart by their ties read as nothing.
    _components(rows, links)
    shown = sum(1 for n in rows if n["kind"] != "incident")
    return {"lens": "companies", "nodes": rows, "links": links, "of": total, "alone": total - shown}


def groups_lens(radar, incs: list[dict], limit: int) -> dict:
    scorer = Scorer(radar.profile)
    nodes = _Nodes(scorer)
    hits: dict[str, dict[str, dict]] = defaultdict(dict)  # group -> victim -> the best incident's measures
    for inc in incs:
        # Groups, and of people only those the profile watches: the model
        # reads "attacker" into senators and chief executives.
        attackers = [e for e in inc["entities"] if e["role"] == "attacker" and not placeholder(e["name"])
                     and (e["type"] == "actor" or (e["type"] == "person" and scorer.ours(e["name"]) == "actor"))]
        victims = [e for e in inc["entities"] if e["role"] == "victim" and e["type"] in ("company", "government")
                   and not placeholder(e["name"])]
        if not attackers or not victims or inc.get("roundup"):
            continue
        for a in attackers[:3]:
            group = nodes.entity(a, inc, "attacker")
            for v in victims[:12]:
                victim = nodes.entity(v, inc, "victim")
                h = hits[group["id"]].setdefault(victim["id"], {"weight": 0, "relevance": 0})
                h["weight"] += 1
                h["relevance"] = max(h["relevance"], inc["relevance"])
    groups = sorted((nodes.by_id[g] for g in hits), key=lambda n: (-n["relevance"], -n["incidents"]))[:max(8, limit // 5)]
    hit_by = Counter(v for g in hits for v in hits[g])
    keep: set[str] = set()
    links: list[dict] = []
    for g in groups:
        ranked = sorted(hits[g["id"]].items(), key=lambda kv: (-(hit_by[kv[0]] > 1), -kv[1]["relevance"], -kv[1]["weight"]))
        shown = ranked[:VICTIMS_PER_GROUP]
        g["victims"] = len(ranked)
        g["more"] = len(ranked) - len(shown)
        keep.add(g["id"])
        for victim, h in shown:
            keep.add(victim)
            links.append({"source": g["id"], "target": victim, "kind": "hit", "weight": h["weight"]})
    total = len(hits)
    nodes.by_id = {k: n for k, n in nodes.by_id.items() if k in keep}
    rows = nodes.out()
    _components(rows, links)
    return {"lens": "groups", "nodes": rows, "links": links, "of": total, "alone": total - len(groups)}


def _unique(links: list[dict]) -> list[dict]:
    seen: dict[tuple, dict] = {}
    for link in links:
        key = (link["source"], link["target"], link["kind"])
        if key in seen:
            seen[key]["weight"] += link["weight"]
        else:
            seen[key] = dict(link)
    return list(seen.values())


BUILDERS = {"us": us_lens, "links": links_lens, "companies": companies_lens, "groups": groups_lens}


def build(radar, lens: str, incs: list[dict], limit: int) -> dict:
    return BUILDERS.get(lens, links_lens)(radar, incs, limit)


def node_detail(radar, node_id: str, incs: list[dict]) -> dict | None:
    """What stands behind one node: its incidents, the parts it played, and
    for a company what Wikidata knows of it."""
    kind, _, rest = node_id.partition(":")
    matched: list[tuple[dict, str]] = []
    label, sub, node_kind = rest, None, kind
    if node_id == "us":
        label, node_kind = radar.profile.get("organization") or "Us", "us"
        sub = "every incident the profile gave points to"
        matched = [(i, "") for i in incs if any(r.get("facet") for r in i["reasons"])]
    elif kind == "e":
        node_kind = "company"
        for inc in incs:
            e = next((e for e in inc["entities"] if norm_name(e["name"]) == rest), None)
            if e is not None:
                matched.append((inc, e["role"]))
                label = e["name"]
                node_kind = e["type"] if e["type"] in ENTITY_KINDS else "company"
                sub = ", ".join(x for x in (e.get("sector"), e.get("country")) if x) or sub
    elif kind == "c":
        node_kind = "cve"
        for inc in incs:
            c = next((c for c in inc["cves"] if c["id"] == rest), None)
            if c is not None:
                matched.append((inc, "flaw"))
                sub = " ".join(x for x in (c.get("vendor"), c.get("product")) if x) or sub
                if c["kev"]:
                    sub = f"{sub + ', ' if sub else ''}exploited (CISA KEV)"
    elif kind == "f":
        facet, _, name = rest.partition(":")
        node_kind, sub = "facet", FACETS.get(facet, ("", ""))[1]
        for inc in incs:
            for r in inc["reasons"]:
                if r.get("facet") == facet and any((norm_name(n) or n.lower()) == name for n in r.get("names") or []):
                    matched.append((inc, r["why"]))
                    label = next(n for n in r["names"] if (norm_name(n) or n.lower()) == name)
                    break
    else:
        return None
    if not matched:
        return None
    matched.sort(key=lambda m: (-m[0]["relevance"], -m[0]["last_seen"]))
    roles = Counter(role for _i, role in matched if role in ("victim", "attacker", "vendor", "flaw"))
    info = radar.store.get(f"wd:{rest}") if kind == "e" else None
    return {
        "id": node_id, "label": label, "kind": node_kind, "sub": sub, "total": len(matched), "roles": dict(roles),
        "usd": sum(i.get("headline_usd") or 0 for i, role in matched if role == "victim"),
        "wikidata": info if info and not info.get("unknown") else None,
        "incidents": [{"id": i["id"], "title": i["title"], "category": i["category"], "relevance": i["relevance"],
                       "last_seen": i["last_seen"], "role": role, "usd": i.get("headline_usd"), "sources": len(i["sources"])}
                      for i, role in matched[:40]],
    }
