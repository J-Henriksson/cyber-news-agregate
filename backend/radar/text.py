"""Small text helpers: markup out, whitespace even, names comparable."""

from __future__ import annotations

import html
import re

_TAG = re.compile(r"<[^>]+>")
_SPACE = re.compile(r"\s+")
_SUFFIX = re.compile(
    r"[,.]?\s+(inc|inc\.|incorporated|corp|corp\.|corporation|co\.|company|ltd|ltd\.|limited|llc|l\.l\.c\.|plc|ab|ab \(publ\)|"
    r"asa|as|a/s|oy|oyj|gmbh|ag|se|sa|s\.a\.|nv|n\.v\.|bv|b\.v\.|spa|s\.p\.a\.|srl|pty|group|holdings|holding)$",
    re.I,
)

STOPWORDS = frozenset(
    """a an the and or of to in on for by with from at as is are was were be been it its this that these those
    after before over under into about than then new says said say report reports reported warns warn amid
    via how why what who when will would could can may might has have had not no more most up out off
    cyber cybersecurity security attack attacks hackers hacker hacked data breach
    patch patches patched fix fixes fixed update updates zero-day zero-days 0-day exploit exploits exploited exploiting
    critical severe flaw flaws vulnerability vulnerabilities bug bugs malware ransomware threat threats campaign
    campaigns actor actors group groups gang gangs attacker attackers users customers million billion warn warns
    target targets targeting targeted used using use uses linked tied via access remote code execution systems
    networks network servers server devices device since week weeks today year years month months
    january february march april may june july august september october november december""".split()
)


def clean(text: str | None, limit: int | None = None) -> str:
    """Markup and entities out, whitespace collapsed, cut at a word."""
    if not text:
        return ""
    out = _SPACE.sub(" ", html.unescape(_TAG.sub(" ", text))).strip()
    if limit and len(out) > limit:
        cut = out[:limit].rsplit(" ", 1)[0]
        out = cut + " ..."
    return out


def norm_name(name: str) -> str:
    """A name as a key: lowercase, no company suffix, no punctuation edges."""
    n = _SPACE.sub(" ", name).strip().strip(".,;:'\"()[]")
    # "The Gentlemen" and "Gentlemen" are one gang, "the BBC" is the BBC.
    if n[:4].lower() == "the " and len(n) > 6:
        n = n[4:]
    for _ in range(2):
        n2 = _SUFFIX.sub("", n)
        if n2 == n:
            break
        n = n2
    return n.lower().strip()


def tokens(text: str) -> set[str]:
    """Content words of a title, for telling stories apart."""
    words = re.findall(r"[a-z0-9][a-z0-9$\-]{2,}", text.lower())
    return {w for w in words if w not in STOPWORDS}


def jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def contains(haystack: str, needle: str) -> bool:
    """Case- and whitespace-blind containment (for checking a model's quote)."""
    h = _SPACE.sub(" ", haystack).lower()
    n = _SPACE.sub(" ", needle).lower().strip()
    return bool(n) and n in h
