"""How much an incident matters to us, 0 to 100, with every point's
reason. The points are a judgement written down so it can be argued
with: change them here or in the profile, never in the views.

    names us                                  +60
    names a tool we build on (ARTEX)          +40
    a supplier hit                            +40
    software we run, in a security story (exploited +20, ransomware +5,
    EPSS over 0.5 +10)                        +25
    an authority of ours advises on it (CERT-SE)
                                              its weight in the profile
    a peer (same field) hit                   +15
    our sector                                +12
    a country of ours                         its weight in the profile
    a group we watch                          +15
    what the team works on                    the interest's points (the two best);
                                              a third of them when one keyword
                                              stands only in the body text
    a major company hit                       +6
    $10M or more / $100M or more              +8 / +15
    a million records or more                 +8
    more sources                              +3 each past the first, up to +15
    a roundup of many stories                 x0.6
    an unconfirmed claim only (social, leak site)
                                              x0.7
"""

from __future__ import annotations

from .gazetteer import MATCHER, REGION_OF, ROUNDUP
from .text import norm_name

CAP = 100
#: The kinds of story in which a vendor we use means risk to us.
SECURITY = ("vulnerability", "malware", "breach", "ransomware", "actor", "ddos")
#: How many of the team's topics can count for one incident.
INTERESTS_COUNTED = 2


def _wordish(ch: str) -> bool:
    return ch.isalnum() or ch == "_"


class Phrases:
    """Whole words or phrases found in a text, any case ("ARTEX", not
    "cleartext"). A substring search per phrase and a look at the letters
    either side: a pattern of many alternatives with look-behinds took
    1.7 s to score 1,400 incidents (2026-11-20), this takes a few ms."""

    def __init__(self, phrases: list[str]):
        self.phrases = [p.strip().lower() for p in phrases if p.strip()]

    def find(self, text: str, lower: str, skip: frozenset[str] = frozenset()) -> str | None:
        """The first phrase written in ``text`` (``lower`` is its lowercase), as written there."""
        for p in self.phrases:
            if p in skip:
                continue
            at = lower.find(p)
            while at >= 0:
                end = at + len(p)
                if (at == 0 or not _wordish(lower[at - 1])) and (end == len(lower) or not _wordish(lower[end])):
                    return text[at:end]
                at = lower.find(p, at + 1)
        return None

    def found(self, text: str, lower: str, skip: frozenset[str] = frozenset(), most: int = 2) -> list[str]:
        """The first ``most`` different phrases written in ``text``, as written there."""
        out: list[str] = []
        for p in self.phrases:
            if p in skip:
                continue
            at = lower.find(p)
            while at >= 0:
                end = at + len(p)
                if (at == 0 or not _wordish(lower[at - 1])) and (end == len(lower) or not _wordish(lower[end])):
                    out.append(text[at:end])
                    break
                at = lower.find(p, at + 1)
            if len(out) >= most:
                break
        return out


def _names(values: list[str]) -> set[str]:
    out = set()
    for v in values:
        known = MATCHER.canonical(v)
        out.add(norm_name(known.name if known else v))
        if known:
            out.update(norm_name(a) for a in known.aliases)
    return {n for n in out if n}


def _spellings(values: list[str]) -> dict[str, list[str]]:
    """For each name (normalised): every way it is written, lowercase
    ("Atlassian" is also "Jira" and "Confluence")."""
    out: dict[str, list[str]] = {}
    for v in values:
        known = MATCHER.canonical(v)
        written = [known.name, *known.aliases] if known else [v]
        for w in written:
            out.setdefault(norm_name(known.name if known else v), []).append(w.lower())
    return out


class Scorer:
    def __init__(self, profile: dict):
        self.profile = profile
        self.us = _names([profile.get("organization", ""), *profile.get("aliases", [])])
        #: Our names as the profile writes them, looked for in the text: the
        #: lists of known companies need not hold the organisation.
        self.us_written = Phrases([profile.get("organization", ""), *profile.get("aliases", [])])
        self.suppliers = _names(profile.get("suppliers", []))
        self.peers = _names(profile.get("peers", []))
        self.stack = _names(profile.get("stack", []))
        self.stack_written = _spellings(profile.get("stack", []))
        self.actors = _names(profile.get("actors", []))
        self.sectors = {s.lower() for s in profile.get("sectors", [])}
        self.countries = profile.get("countries", {})
        self.authorities = profile.get("authorities", {})
        self.own = [(name, Phrases([name])) for name in profile.get("own_tools", []) if name.strip()]
        self.own_lower = frozenset(name.lower() for name, _p in self.own)
        self.interests = [(it, Phrases(it.get("keywords", []))) for it in profile.get("interests", [])
                          if any(w.strip() for w in it.get("keywords", []))]

    def ours(self, name: str) -> str | None:
        """What a name is to us, if anything: "us", "tool", "supplier", "stack", "peer" or "actor"."""
        n = norm_name(name)
        if name.lower() in self.own_lower:
            return "tool"
        for kind, names in (("us", self.us), ("supplier", self.suppliers), ("stack", self.stack), ("peer", self.peers),
                            ("actor", self.actors)):
            if n in names:
                return kind
        return None

    def score(self, inc: dict) -> tuple[int, list[dict]]:
        reasons: list[dict] = []

        def add(points: float, why: str, facet: str | None = None, names: list[str] | tuple = ()) -> None:
            """``facet``: the part of the profile the points come from (the graph's
            "us" lens draws it); ``names``: what in that part matched."""
            reasons.append({"points": round(points), "why": why, "facet": facet, "names": list(names)})

        names = {norm_name(e["name"]): e for e in inc["entities"]}
        titles = " ".join([inc["title"], *[i.get("title") or "" for i in inc["items"]]]).lower()
        text = " ".join([inc["title"], inc.get("summary") or "", inc.get("_text") or ""])
        lower = text.lower()
        hit_us = [e["name"] for n, e in names.items() if n in self.us]
        if not hit_us:
            # No reading named us: one of our names written in the text counts the same.
            written = self.us_written.find(text, lower)
            hit_us = [written] if written else []
        if hit_us:
            add(60, f"names us ({hit_us[0]})", "us", hit_us[:1])
        own = [name for name, phrases in self.own if phrases.find(text, lower)]
        if own:
            add(40, f"names a tool we build on ({', '.join(own)})", "tool", own)
        sup = [e["name"] for n, e in names.items() if n in self.suppliers and e["role"] == "victim"]
        if sup:
            add(40, f"a supplier hit: {', '.join(sup[:3])}", "supplier", sup[:3])
        # A vendor named in passing ("Microsoft said...") is not its software
        # at risk: only as the flawed product's maker, the victim, or when a
        # headline names it or one of its products ("Jira" for Atlassian).
        stack = [e["name"] for n, e in names.items() if n in self.stack and (
            e["role"] in ("vendor", "victim")
            or (e["role"] == "mentioned" and any(w in titles for w in self.stack_written.get(n, [e["name"].lower()]))))]
        stack += [c["vendor"] for c in inc["cves"] if c.get("vendor") and norm_name(c["vendor"]) in self.stack]
        stack += [c["product"] for c in inc["cves"] if c.get("product") and norm_name(c["product"]) in self.stack]
        # A product update or a business story about a vendor we use is not a risk to us.
        if stack and inc["category"] in SECURITY:
            ours = sorted(set(stack))[:3]
            add(25, f"software we run: {', '.join(ours)}", "stack", ours)
            if any(c["kev"] for c in inc["cves"]):
                add(20, "and it is being exploited (CISA KEV)", "stack", ours)
            if any(c.get("ransomware_use") == "Known" for c in inc["cves"]):
                add(5, "used by ransomware gangs", "stack", ours)
            if any((c.get("epss") or 0) >= 0.5 for c in inc["cves"]):
                add(10, "EPSS: likely exploited within 30 days", "stack", ours)
        # An advisory of an authority we answer to, on this very thing (not its weekly letter).
        advised = max(((self.authorities.get(i["source"], 0), i["source"]) for i in inc["items"]
                       if i["kind"] == "advisory" and not ROUNDUP.search(i.get("title") or "")), default=(0, None))
        if advised[0]:
            add(advised[0], f"{advised[1]} advises on it", "authority", [advised[1]])
        peer = [e["name"] for n, e in names.items() if n in self.peers and e["role"] == "victim"]
        if peer:
            add(15, f"a peer hit: {', '.join(peer[:3])}", "peer", peer[:3])
        sectors = {(e.get("sector") or "").lower() for e in inc["entities"] if e["role"] == "victim"} & self.sectors
        if sectors and not peer and not hit_us:
            add(12, f"our sector: {', '.join(sorted(sectors))}", "sector", sorted(sectors))
        best_country = max(((self.countries.get(c, 0), c) for c in inc["countries"]), default=(0, None))
        if best_country[0]:
            add(best_country[0], f"in {best_country[1]}", "country", [best_country[1]])
        elif any(REGION_OF.get(c) in ("nordic", "baltic") for c in inc["countries"]):
            add(4, "in our region", "country", ["our region"])
        actors = [e["name"] for n, e in names.items() if n in self.actors]
        if actors:
            add(15, f"a group we watch: {', '.join(actors[:3])}", "actor", actors[:3])
        found = []
        for interest, phrases in self.interests:
            hits = phrases.found(text, lower, self.own_lower)
            if not hits:
                continue
            # A story about the topic says so in a headline, or in more than one
            # of its words. One word somewhere in the body ("agentic", "loader")
            # is a mention in passing: a third of the points.
            about = len(hits) > 1 or phrases.find(titles, titles, self.own_lower) is not None
            points = interest.get("points", 10)
            found.append((points if about else max(2, round(points / 3)), interest, hits[0], about))
        for points, interest, hit, about in sorted(found, key=lambda f: -f[0])[:INTERESTS_COUNTED]:
            add(points, f"{interest['name']} ({interest.get('project') or 'interest'}): \"{hit}\"{'' if about else ', in passing'}",
                "interest", [interest["name"]])
        major = [e["name"] for e in inc["entities"] if e["role"] == "victim" and e["type"] == "company"
                 and MATCHER.canonical(e["name"]) is not None]
        if major and not (hit_us or peer or sup):
            add(6, f"a major company hit: {', '.join(major[:3])}")
        usd = inc.get("headline_usd") or 0
        if usd >= 1e8:
            add(15, f"${usd / 1e6:,.0f}M reported ({inc['headline_kind']})")
        elif usd >= 1e7:
            add(8, f"${usd / 1e6:,.0f}M reported ({inc['headline_kind']})")
        if (inc.get("records") or 0) >= 1e6:
            add(8, f"{inc['records']:,} records or people")
        extra = len(inc["sources"]) - 1
        if extra > 0:
            add(min(15, 3 * extra), f"{len(inc['sources'])} sources")
        total = sum(r["points"] for r in reasons)
        if inc.get("roundup") and total:
            reasons.append({"points": -round(total * 0.4), "why": "a roundup of many stories, not one", "facet": None, "names": []})
            total = round(total * 0.6)
        if set(inc["kinds"]) <= {"social", "ransomware"} and total:
            reasons.append({"points": -round(total * 0.3), "why": "only claims so far (social posts or a leak site)", "facet": None,
                            "names": []})
            total = round(total * 0.7)
        return min(CAP, max(0, total)), reasons
