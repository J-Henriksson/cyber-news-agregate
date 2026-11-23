"""The sources, each read on its own clock, each turned into items of one
shape: ``id``, ``source``, ``kind``, ``url``, ``title``, ``text``,
``published`` (epoch seconds), ``data`` (what a structured source states:
a victim, a group, an amount) and ``llm`` (whether the model should read it).

Kinds: news, advisory, social, community, ransomware, breach, crypto,
filing, vuln, tool, research. All keyless and free; probed 2026-11-20.
Two desks: cybersecurity, and AI news (its items carry ``data.topic = "ai"``).
X (Twitter) is not read: its API is paid and scraping it breaks its terms.
Bluesky and Mastodon carry much of the same scene."""

from __future__ import annotations

import asyncio
import calendar
import hashlib
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Awaitable, Callable
from urllib.parse import quote, urlparse

import feedparser
import httpx

from .config import KEEP_DAYS
from .text import clean


@dataclass(frozen=True)
class Source:
    name: str
    kind: str
    url: str
    every: float  # seconds between reads
    fetch: Callable[[httpx.AsyncClient], Awaitable[list[dict]]]
    reliability: str
    #: The desk it serves: "cyber" or "ai". An AI source's items carry topic "ai".
    topic: str = "cyber"


#: Sites that put some or all of their articles behind a subscription: the
#: link may not open, and only the headline and teaser were read.
PAYWALLED = ("wsj.com", "nytimes.com", "ft.com", "bloomberg.com", "theinformation.com", "economist.com",
             "washingtonpost.com", "theatlantic.com", "newyorker.com", "wired.com", "technologyreview.com",
             "404media.co", "businessinsider.com", "theverge.com", "the-decoder.com", "reuters.com", "forbes.com",
             "telegraph.co.uk", "thetimes.co.uk", "dn.se", "svd.se", "di.se")


def paywalled(url: str | None) -> bool:
    host = (urlparse(url or "").hostname or "").removeprefix("www.")
    return any(host == p or host.endswith("." + p) for p in PAYWALLED)


def item_id(source: str, key: str) -> str:
    return hashlib.sha1(f"{source}|{key}".encode()).hexdigest()[:16]


def _item(source: str, kind: str, key: str, url: str | None, title: str, text: str, published: float,
          data: dict | None = None, llm: bool = True) -> dict:
    return {"id": item_id(source, key), "source": source, "kind": kind, "url": url, "title": clean(title, 300),
            "text": clean(text, 1600), "published": published, "data": data or {}, "llm": llm}


def _recent(ts: float | None, days: float = KEEP_DAYS) -> bool:
    return ts is not None and ts >= time.time() - days * 86400


def _iso(value: str | None) -> float | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        try:
            dt = datetime.strptime(value[:19], "%Y-%m-%d %H:%M:%S")
        except ValueError:
            try:
                dt = datetime.strptime(value[:10], "%Y-%m-%d")
            except ValueError:
                return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


class Unchanged(Exception):
    """The source says nothing changed since it was last read (HTTP 304)."""


#: What each feed said identified its last answer: sent back so an unchanged
#: feed answers with a few bytes instead of its whole file.
_validators: dict[str, dict[str, str]] = {}


async def _get(client: httpx.AsyncClient, url: str, **kw) -> httpx.Response:
    r = await client.get(url, follow_redirects=True, **kw)
    r.raise_for_status()
    return r


# -- news, advisories and research by feed ----------------------------------------------------

def _feed(name: str, url: str, kind: str = "news", days: float = KEEP_DAYS, llm: bool = True, topic: str | None = None,
          skip: str | None = None):
    """A reader for one RSS or Atom feed. ``skip``: headlines matching it are left out
    (a feed's daily podcast, its squid post)."""
    skip_re = re.compile(skip, re.I) if skip else None

    async def fetch(client: httpx.AsyncClient) -> list[dict]:
        r = await client.get(url, follow_redirects=True, headers=_validators.get(url, {}))
        if r.status_code == 304:
            raise Unchanged(name)
        r.raise_for_status()
        seen = {h: r.headers[k] for k, h in (("etag", "If-None-Match"), ("last-modified", "If-Modified-Since")) if k in r.headers}
        if seen:
            _validators[url] = seen
        parsed = feedparser.parse(r.content)
        out = []
        for e in parsed.entries:
            when = e.get("published_parsed") or e.get("updated_parsed")
            ts = calendar.timegm(when) if when else None
            if not _recent(ts, days):
                continue
            if skip_re and skip_re.search(e.get("title", "")):
                continue
            summary = e.get("summary") or e.get("description") or ""
            link = e.get("link") or ""
            data = {"authors": [a.get("name") for a in e.get("authors", []) if a.get("name")]}
            if topic:
                data["topic"] = topic
            out.append(_item(name, kind, e.get("id") or link or e.get("title", ""), link, e.get("title", ""),
                             summary, ts, data, llm))
        return out

    return fetch


NEWS_FEEDS = (
    ("BleepingComputer", "https://www.bleepingcomputer.com/feed/", "trade press, usually confirmed"),
    ("The Record", "https://therecord.media/feed", "newsroom (Recorded Future News), editorial standards"),
    ("KrebsOnSecurity", "https://krebsonsecurity.com/feed/", "investigative journalist, usually confirmed"),
    ("SecurityWeek", "https://www.securityweek.com/feed/", "trade press, usually confirmed"),
    ("The Hacker News", "https://feeds.feedburner.com/TheHackersNews", "trade press, often vendor-sourced"),
    ("Dark Reading", "https://www.darkreading.com/rss.xml", "trade press, usually confirmed"),
    ("DataBreaches.net", "https://databreaches.net/feed/", "breach reporting, often first, sometimes unconfirmed"),
    ("CyberScoop", "https://cyberscoop.com/feed/", "newsroom, editorial standards"),
    ("Help Net Security", "https://www.helpnetsecurity.com/feed/", "trade press, often vendor-sourced"),
)
#: More of the press, and the research teams' own write-ups: first-hand and
#: detailed, each with its employer's interest. (name, url, how far to trust it, headlines to skip)
MORE_FEEDS = (
    ("The Register", "https://www.theregister.com/security/headlines.atom", "tech press, editorial standards", None),
    ("TechCrunch Security", "https://techcrunch.com/category/security/feed/", "tech press, often company-sourced", None),
    ("Ars Technica Security", "https://arstechnica.com/security/feed/", "tech press, editorial standards", None),
    ("404 Media", "https://www.404media.co/rss/", "investigative newsroom, usually confirmed", r"^podcast:"),
    ("Risky Bulletin", "https://news.risky.biz/rss/", "newsletter digest of the day's security news", None),
    ("Schneier on Security", "https://www.schneier.com/feed/atom/", "practitioner's weblog", r"squid"),
    ("SANS ISC", "https://isc.sans.edu/rssfeed_full.xml", "handlers' diaries: first-hand observations", r"stormcast"),
    ("Cisco Talos", "https://blog.talosintelligence.com/rss/", "vendor research: first-hand, its own interest", None),
    ("Unit 42", "https://unit42.paloaltonetworks.com/feed/", "vendor research: first-hand, its own interest", None),
    ("Google Project Zero", "https://googleprojectzero.blogspot.com/feeds/posts/default", "vulnerability research: first-hand", None),
    ("Securelist", "https://securelist.com/feed/", "vendor research (Kaspersky): first-hand, its own interest", None),
    ("SentinelLabs", "https://www.sentinelone.com/labs/feed/", "vendor research: first-hand, its own interest", None),
    ("watchTowr Labs", "https://labs.watchtowr.com/rss/", "vulnerability research: first-hand", None),
    ("GreyNoise", "https://www.greynoise.io/blog/rss.xml", "internet-wide scanning observations: first-hand", None),
    ("Wiz Research", "https://www.wiz.io/feed/rss.xml", "vendor research: first-hand, its own interest", None),
    ("Microsoft Security", "https://www.microsoft.com/en-us/security/blog/feed/", "vendor blog: threat reports among product news",
     r"gartner|forrester|named a leader"),
    ("Embrace The Red", "https://embracethered.com/blog/index.xml", "researcher's weblog: prompt injection and agent attacks", None),
)
MORE_ADVISORY_FEEDS = (
    ("CERT-EU", "https://cert.europa.eu/publications/security-advisories-rss", "the EU institutions' CERT: official"),
    ("NCSC-FI", "https://www.kyberturvallisuuskeskus.fi/feed/rss/en", "Finland's national cyber centre: official"),
)
MORE_AI_FEEDS = (
    ("Mistral", "https://mistral.ai/rss.xml", "lab: its own announcements"),
    ("Latent Space", "https://www.latent.space/feed", "newsletter and podcast for AI engineers"),
    ("NVIDIA blog", "https://blogs.nvidia.com/feed/", "company blog: its own announcements"),
    ("AI Snake Oil", "https://www.aisnakeoil.com/feed", "researchers' newsletter: sceptical analysis"),
)
AI_FEEDS = (
    ("OpenAI", "https://openai.com/news/rss.xml", "lab: its own announcements"),
    ("Google DeepMind", "https://deepmind.google/blog/rss.xml", "lab: its own announcements"),
    ("Google AI", "https://blog.google/technology/ai/rss/", "company blog: its own announcements"),
    ("Hugging Face blog", "https://huggingface.co/blog/feed.xml", "platform blog: releases and research notes"),
    ("The Verge AI", "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml", "tech press, editorial standards"),
    ("TechCrunch AI", "https://techcrunch.com/category/artificial-intelligence/feed/", "tech press, often company-sourced"),
    ("Ars Technica AI", "https://arstechnica.com/ai/feed/", "tech press, editorial standards"),
    ("MIT Technology Review AI", "https://www.technologyreview.com/topic/artificial-intelligence/feed", "magazine, editorial standards"),
    ("Simon Willison", "https://simonwillison.net/atom/everything/", "practitioner's weblog: LLMs, agents, prompt injection"),
    ("Import AI", "https://importai.substack.com/feed", "newsletter on AI research and policy"),
    ("The Decoder", "https://the-decoder.com/feed/", "AI trade press"),
    ("AI Incident Database", "https://incidentdatabase.ai/rss.xml", "database of harms caused by AI systems, reported"),
)
ADVISORY_FEEDS = (
    ("CERT-SE", "https://www.cert.se/feed/rss.xml", "Sweden's national CSIRT: official"),
    ("NCSC UK", "https://www.ncsc.gov.uk/api/1/services/v1/report-rss-feed.xml", "UK national cyber centre: official"),
    ("CISA advisories", "https://www.cisa.gov/cybersecurity-advisories/all.xml", "US cyber agency: official"),
)


# -- exploited flaws ----------------------------------------------------------------------------

KEV_URL = "https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json"


async def fetch_kev(client: httpx.AsyncClient) -> list[dict]:
    """CISA's list of flaws known to be exploited. Items for the ones added
    within the kept days; the whole list is kept aside (kev_catalog) for
    the exposure view."""
    doc = (await _get(client, KEV_URL)).json()
    out = []
    for v in doc.get("vulnerabilities", []):
        ts = _iso(v.get("dateAdded"))
        if not _recent(ts):
            continue
        cve = v.get("cveID", "")
        title = f"{cve}: {v.get('vendorProject')} {v.get('product')}: {v.get('vulnerabilityName')}"
        text = f"{v.get('shortDescription', '')} Required action: {v.get('requiredAction', '')}"
        out.append(_item("CISA KEV", "vuln", cve, f"https://nvd.nist.gov/vuln/detail/{cve}", title, text, ts, {
            "cve": cve, "vendor": v.get("vendorProject"), "product": v.get("product"),
            "ransomware_use": v.get("knownRansomwareCampaignUse"), "due": v.get("dueDate"),
        }, llm=False))
    fetch_kev.catalog = [  # type: ignore[attr-defined]
        {"cve": v.get("cveID"), "vendor": v.get("vendorProject"), "product": v.get("product"),
         "name": v.get("vulnerabilityName"), "added": v.get("dateAdded"), "ransomware_use": v.get("knownRansomwareCampaignUse")}
        for v in doc.get("vulnerabilities", [])
    ]
    return out


# -- leak sites, breach lists, crypto thefts, filings -------------------------------------------

async def fetch_ransomlook(client: httpx.AsyncClient) -> list[dict]:
    """The newest posts on ransomware gangs' leak sites, as RansomLook
    mirrors them: a group's claim, not a confirmed attack."""
    rows = (await _get(client, "https://www.ransomlook.io/api/recent")).json()
    out = []
    for r in rows:
        ts = _iso(r.get("discovered"))
        victim, group = (r.get("post_title") or "").strip(), (r.get("group_name") or "").strip()
        if not victim or not _recent(ts):
            continue
        link = r.get("link") or ""
        url = f"https://www.ransomlook.io/group/{quote(group)}" if group else "https://www.ransomlook.io/recent"
        out.append(_item("RansomLook", "ransomware", f"{group}|{victim}", url, f"{group} claims {victim}",
                         r.get("description") or "", ts, {"group": group, "victim": victim, "post": link}, llm=False))
    return out


async def fetch_hibp(client: httpx.AsyncClient) -> list[dict]:
    """Breaches Have I Been Pwned has verified and loaded, by the day they
    were added."""
    rows = (await _get(client, "https://haveibeenpwned.com/api/v3/breaches")).json()
    out = []
    for b in rows:
        ts = _iso(b.get("AddedDate"))
        if not _recent(ts):
            continue
        n = b.get("PwnCount") or 0
        title = f"{b.get('Title')} breach: {n:,} accounts ({', '.join((b.get('DataClasses') or [])[:4])})"
        out.append(_item("Have I Been Pwned", "breach", b.get("Name", ""), f"https://haveibeenpwned.com/PwnedWebsites#{b.get('Name')}",
                         title, b.get("Description") or "", ts, {
                             "victim": b.get("Title"), "domain": b.get("Domain"), "pwn_count": n,
                             "breach_date": b.get("BreachDate"), "data_classes": b.get("DataClasses"),
                             "verified": b.get("IsVerified"),
                         }, llm=False))
    return out


async def fetch_defillama(client: httpx.AsyncClient) -> list[dict]:
    """Crypto thefts with the amount lost, as DefiLlama records them."""
    rows = (await _get(client, "https://api.llama.fi/hacks")).json()
    out = []
    for h in rows:
        ts = float(h.get("date") or 0)
        if not _recent(ts):
            continue
        amount = h.get("amount")
        name = h.get("name") or ""
        technique = h.get("technique") or h.get("classification") or ""
        title = f"{name}: {'$' + format(int(amount), ',') if amount else 'amount not given'} lost ({technique})"
        out.append(_item("DefiLlama hacks", "crypto", f"{name}|{int(ts)}", h.get("source") or "https://defillama.com/hacks", title,
                         h.get("description") or "", ts, {
                             "victim": name, "amount_usd": amount, "technique": technique,
                             "chain": h.get("chain"), "returned_usd": h.get("returnedFunds"),
                         }, llm=False))
    return out


async def fetch_sec(client: httpx.AsyncClient) -> list[dict]:
    """Form 8-K item 1.05 filings: a US-listed company telling investors of
    a material cybersecurity incident, within four business days."""
    start = datetime.fromtimestamp(time.time() - KEEP_DAYS * 86400, timezone.utc).strftime("%Y-%m-%d")
    end = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out = []
    for offset in (0, 100):
        url = ("https://efts.sec.gov/LATEST/search-index?q=%22Item%201.05%22&forms=8-K"
               f"&dateRange=custom&startdt={start}&enddt={end}&from={offset}")
        hits = (await _get(client, url)).json().get("hits", {}).get("hits", [])
        for h in hits:
            s = h.get("_source", {})
            if "1.05" not in (s.get("items") or []):
                continue
            ts = _iso(s.get("file_date"))
            company = (s.get("display_names") or [""])[0].split("  (")[0].strip()
            adsh = s.get("adsh", "")
            cik = (s.get("ciks") or ["0"])[0].lstrip("0")
            filename = h.get("_id", ":").split(":", 1)[1]
            link = f"https://www.sec.gov/Archives/edgar/data/{cik}/{adsh.replace('-', '')}/{filename}"
            title = f"{company} tells the SEC of a material cybersecurity incident ({s.get('form')})"
            out.append(_item("SEC 8-K item 1.05", "filing", adsh, link, title,
                             f"{company} filed form {s.get('form')} under item 1.05 on {s.get('file_date')}.", ts,
                             {"company": company, "cik": cik, "form": s.get("form")}, llm=False))
        if len(hits) < 100:
            break
    return out


# -- the scene: Bluesky, Mastodon, Hacker News ---------------------------------------------------

BSKY_QUERIES = ("ransomware", "data breach", "zero-day", "hacked", "leaked", "cyberattack", "infostealer", "exploited")
#: Likes and reposts a post needs to count: below it is noise.
BSKY_MIN = 10


async def fetch_bluesky(client: httpx.AsyncClient) -> list[dict]:
    since = datetime.fromtimestamp(time.time() - 2 * 86400, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    out: dict[str, dict] = {}
    for q in BSKY_QUERIES:
        url = f"https://api.bsky.app/xrpc/app.bsky.feed.searchPosts?q={quote(q)}&sort=top&limit=40&since={since}&lang=en"
        try:
            posts = (await _get(client, url)).json().get("posts", [])
        except httpx.HTTPError:
            continue
        for p in posts:
            engagement = (p.get("likeCount") or 0) + (p.get("repostCount") or 0)
            if engagement < BSKY_MIN:
                continue
            rec = p.get("record") or {}
            handle = (p.get("author") or {}).get("handle", "")
            rkey = p.get("uri", "").rsplit("/", 1)[-1]
            text = rec.get("text") or ""
            out[p["uri"]] = _item("Bluesky", "social", p["uri"], f"https://bsky.app/profile/{handle}/post/{rkey}",
                                  f"@{handle}: {text[:140]}", text, _iso(rec.get("createdAt")) or time.time(),
                                  {"author": handle, "likes": p.get("likeCount"), "reposts": p.get("repostCount")})
        await asyncio.sleep(0.5)
    return list(out.values())


#: The scene's own voices on infosec.exchange (looked up 2026-11-20): read
#: whole, no engagement bar. Boosts count: what they pass on is the news.
MASTODON_ACCOUNTS = ("briankrebs", "malwaretech", "mttaggart", "josephcox", "0xabad1dea", "SwiftOnSecurity",
                     "dangoodin", "lorenzofb", "zackwhittaker", "campuscodi")
MASTODON_HOST = "https://infosec.exchange"
_mastodon_ids: dict[str, str | None] = {}


async def fetch_mastodon(client: httpx.AsyncClient) -> list[dict]:
    out: dict[str, dict] = {}
    since = time.time() - 4 * 86400
    for acct in MASTODON_ACCOUNTS:
        if acct not in _mastodon_ids:
            try:
                r = await client.get(f"{MASTODON_HOST}/api/v1/accounts/lookup", params={"acct": acct})
                _mastodon_ids[acct] = r.json().get("id") if r.status_code == 200 else None
            except (httpx.HTTPError, ValueError):
                continue
        account_id = _mastodon_ids.get(acct)
        if not account_id:
            continue
        try:
            posts = (await _get(client, f"{MASTODON_HOST}/api/v1/accounts/{account_id}/statuses",
                                params={"limit": 30, "exclude_replies": "true"})).json()
        except httpx.HTTPError:
            continue
        for p in posts:
            shown = p.get("reblog") or p
            ts = _iso(shown.get("created_at") or p.get("created_at"))
            if not ts or ts < since:
                continue
            author = (shown.get("account") or {}).get("acct", acct)
            text = clean(shown.get("content"))
            card = shown.get("card") or {}
            if card.get("title"):
                text = f"{text} [{card.get('title')}: {clean(card.get('description'), 300)}]"
            if len(text) < 30:
                continue
            out[shown.get("uri") or p["uri"]] = _item(
                "Mastodon", "social", shown.get("uri") or p["uri"], card.get("url") or shown.get("url") or p.get("url"),
                f"@{author}: {clean(shown.get('content'))[:140]}", text, ts,
                {"author": author, "via": acct if author != acct else None,
                 "likes": shown.get("favourites_count"), "reposts": shown.get("reblogs_count")})
        await asyncio.sleep(0.3)
    return list(out.values())


HN_QUERIES = ("security", "vulnerability", "breach", "hacked", "exploit", "ransomware", "malware", "CVE", "leak", "zero-day")
HN_AI_QUERIES = ("LLM", "GPT", "OpenAI", "Anthropic", "Claude", "Gemini", "DeepSeek", "AI agent", "AI model", "open weights")


def _hn(name: str, queries: tuple[str, ...], min_points: int, topic: str | None = None):
    async def fetch(client: httpx.AsyncClient) -> list[dict]:
        since = int(time.time() - 4 * 86400)
        out: dict[str, dict] = {}
        for q in queries:
            url = (f"https://hn.algolia.com/api/v1/search_by_date?tags=story&query={quote(q)}"
                   f"&numericFilters=points>={min_points},created_at_i>{since}&hitsPerPage=30")
            for h in (await _get(client, url)).json().get("hits", []):
                hn_url = f"https://news.ycombinator.com/item?id={h['objectID']}"
                data = {"points": h.get("points"), "comments": h.get("num_comments"), "hn_url": hn_url}
                if topic:
                    data["topic"] = topic
                out[h["objectID"]] = _item(name, "community", h["objectID"], h.get("url") or hn_url, h.get("title", ""),
                                           h.get("story_text") or "", float(h.get("created_at_i") or time.time()), data)
        return list(out.values())

    return fetch


fetch_hn = _hn("Hacker News", HN_QUERIES, 40)


# -- new tools and methods ----------------------------------------------------------------------

GITHUB_TOPICS = ("pentest", "red-team", "offensive-security", "malware-analysis", "exploit", "llm-security",
                 "ai-security", "bugbounty", "threat-intelligence", "reverse-engineering")
GITHUB_AI_TOPICS = ("ai-agents", "llm", "mcp", "mcp-server", "agentic-ai", "rag")
GITHUB_MIN_STARS = 25


def _github(name: str, topics: tuple[str, ...], min_stars: int, topic: str | None = None):
    async def fetch(client: httpx.AsyncClient) -> list[dict]:
        """Repositories made in the last fortnight that people starred."""
        since = datetime.fromtimestamp(time.time() - 14 * 86400, timezone.utc).strftime("%Y-%m-%d")
        out: dict[str, dict] = {}
        for t in topics:
            url = f"https://api.github.com/search/repositories?q=topic:{t}+created:>{since}&sort=stars&order=desc&per_page=15"
            try:
                repos = (await _get(client, url, headers={"Accept": "application/vnd.github+json"})).json().get("items", [])
            except httpx.HTTPStatusError as err:
                if err.response.status_code in (403, 429):
                    break  # the hourly allowance is spent: the rest next time
                raise
            for r in repos:
                if (r.get("stargazers_count") or 0) < min_stars:
                    continue
                data = {"stars": r.get("stargazers_count"), "language": r.get("language"), "topics": r.get("topics")}
                if topic:
                    data["topic"] = topic
                out[r["full_name"]] = _item(name, "tool", r["full_name"], r.get("html_url"),
                                            f"{r['full_name']}: {r.get('description') or 'no description'}",
                                            f"{r.get('description') or ''} Topics: {', '.join(r.get('topics') or [])}.",
                                            _iso(r.get("created_at")) or time.time(), data, llm=False)
            await asyncio.sleep(7)  # 10 searches a minute without a token
        return list(out.values())

    return fetch


fetch_github = _github("GitHub", GITHUB_TOPICS, GITHUB_MIN_STARS)

#: Likes a new model needs on Hugging Face to count.
HF_MIN_LIKES = 100


async def fetch_hf_models(client: httpx.AsyncClient) -> list[dict]:
    """Models made in the last month that are trending on Hugging Face."""
    rows = (await _get(client, "https://huggingface.co/api/models", params={"sort": "trendingScore", "limit": 40})).json()
    out = []
    for m in rows:
        ts = _iso(m.get("createdAt"))
        if not _recent(ts, 30) or (m.get("likes") or 0) < HF_MIN_LIKES:
            continue
        tags = [t for t in m.get("tags") or [] if not t.startswith(("region:", "license:", "arxiv:", "base_model:"))]
        title = f"{m['id']}: trending model ({m.get('pipeline_tag') or 'no task given'})"
        out.append(_item("Hugging Face models", "tool", m["id"], f"https://huggingface.co/{m['id']}", title,
                         f"{m.get('likes', 0):,} likes, {m.get('downloads', 0):,} downloads. Tags: {', '.join(tags[:12])}.", ts,
                         {"likes": m.get("likes"), "downloads": m.get("downloads"), "pipeline": m.get("pipeline_tag"),
                          "topic": "ai"}, llm=False))
    return out


ARXIV = ("https://export.arxiv.org/api/query?search_query=cat:cs.CR"
         "&sortBy=submittedDate&sortOrder=descending&max_results=80")


# -- the registry -------------------------------------------------------------------------------

HOUR = 3600.0
SOURCES: tuple[Source, ...] = (
    *(Source(n, "news", u, 15 * 60, _feed(n, u), rel) for n, u, rel in NEWS_FEEDS),
    *(Source(n, "advisory", u, 30 * 60, _feed(n, u, "advisory"), rel) for n, u, rel in ADVISORY_FEEDS),
    Source("CISA KEV", "vuln", KEV_URL, 6 * HOUR, fetch_kev, "US cyber agency: exploitation confirmed"),
    Source("RansomLook", "ransomware", "https://www.ransomlook.io/recent", 30 * 60, fetch_ransomlook,
           "leak-site post: the gang's own claim, not confirmed"),
    Source("Have I Been Pwned", "breach", "https://haveibeenpwned.com/PwnedWebsites", 6 * HOUR, fetch_hibp,
           "verified breach corpus"),
    Source("DefiLlama hacks", "crypto", "https://defillama.com/hacks", 6 * HOUR, fetch_defillama,
           "crypto theft tracker, amounts from on-chain records"),
    Source("SEC 8-K item 1.05", "filing", "https://efts.sec.gov/LATEST/search-index", 6 * HOUR, fetch_sec,
           "company's own filing to the SEC: official"),
    Source("Bluesky", "social", "https://bsky.app/search", 20 * 60, fetch_bluesky, "social post: unverified"),
    Source("Mastodon", "social", "https://infosec.exchange", 20 * 60, fetch_mastodon, "social post: unverified"),
    Source("Hacker News", "community", "https://news.ycombinator.com", 30 * 60, fetch_hn, "community link: as good as its link"),
    Source("GitHub", "tool", "https://github.com/topics/pentest", 12 * HOUR, fetch_github, "repository: claims of its author"),
    Source("arXiv cs.CR", "research", "https://arxiv.org/list/cs.CR/recent", 12 * HOUR,
           _feed("arXiv cs.CR", ARXIV, "research", days=14, llm=False), "preprint: not peer reviewed"),
    *(Source(n, "news", u, 30 * 60, _feed(n, u, days=30, skip=skip), rel) for n, u, rel, skip in MORE_FEEDS),
    *(Source(n, "advisory", u, 60 * 60, _feed(n, u, "advisory", days=30), rel) for n, u, rel in MORE_ADVISORY_FEEDS),
    # The AI desk
    *(Source(n, "news", u, 30 * 60, _feed(n, u, days=30, topic="ai"), rel, topic="ai") for n, u, rel in AI_FEEDS),
    *(Source(n, "news", u, 60 * 60, _feed(n, u, days=30, topic="ai"), rel, topic="ai") for n, u, rel in MORE_AI_FEEDS),
    Source("Hacker News AI", "community", "https://news.ycombinator.com", 30 * 60,
           _hn("Hacker News AI", HN_AI_QUERIES, 100, topic="ai"), "community link: as good as its link", topic="ai"),
    Source("GitHub AI", "tool", "https://github.com/topics/ai-agents", 12 * HOUR,
           _github("GitHub AI", GITHUB_AI_TOPICS, 100, topic="ai"), "repository: claims of its author", topic="ai"),
    Source("Hugging Face models", "tool", "https://huggingface.co/models?sort=trending", 6 * HOUR, fetch_hf_models,
           "model card: claims of its makers", topic="ai"),
)
SOURCE_BY_NAME = {s.name: s for s in SOURCES}
