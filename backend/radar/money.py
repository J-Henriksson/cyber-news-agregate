"""Money in the news: the amounts a text states, what kind of money each is
(a ransom asked, a theft, a fine...), and the amount in US dollars at the
European Central Bank's rates of the day.

An amount is only ever one the text states. A kind the words around it do
not settle is "other", and the views leave "other" and "business" (a
funding round, a market) out of the damage they add up."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET

#: Kinds that are damage, in the order a headline figure prefers them.
DAMAGE_KINDS = ("theft", "ransom_paid", "loss", "fine", "settlement", "ransom_demand")
KINDS = DAMAGE_KINDS + ("reward", "business", "other")

_SYMBOL = {
    "$": "USD", "us$": "USD", "usd": "USD", "dollars": "USD", "dollar": "USD",
    "€": "EUR", "eur": "EUR", "euros": "EUR", "euro": "EUR",
    "£": "GBP", "gbp": "GBP", "pounds": "GBP",
    "sek": "SEK", "kronor": "SEK", "kr": "SEK", "nok": "NOK", "dkk": "DKK",
    "chf": "CHF", "¥": "JPY", "jpy": "JPY", "yen": "JPY", "inr": "INR", "₹": "INR", "rupees": "INR",
    "a$": "AUD", "aud": "AUD", "c$": "CAD", "cad": "CAD",
    "nt$": "TWD", "twd": "TWD", "hk$": "HKD", "hkd": "HKD", "s$": "SGD", "sgd": "SGD", "r$": "BRL", "brl": "BRL",
}
_MULT = {
    "thousand": 1e3, "k": 1e3, "million": 1e6, "m": 1e6, "mn": 1e6, "mln": 1e6, "miljoner": 1e6,
    "billion": 1e9, "bn": 1e9, "b": 1e9, "miljarder": 1e9, "trillion": 1e12,
}
_NUM = r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?"
_MULTS = r"thousand|million|billion|trillion|miljoner|miljarder|mln|mn|bn|[kmb](?![a-z])"
_PRE = re.compile(
    rf"(?P<cur>\b(?:US|NT|HK|A|C|S|R)\$|(?<![A-Za-z])\$|€|£|¥|₹|\b(?:USD|EUR|GBP|SEK|NOK|DKK|CHF|JPY|INR|AUD|CAD|TWD|HKD|SGD|BRL)\b)"
    rf"\s?(?P<num>{_NUM})\s?(?P<mult>{_MULTS})?",
    re.I,
)
_POST = re.compile(
    rf"(?<![\w$€£])(?P<num>{_NUM})\s?(?P<mult>{_MULTS})?\s?(?P<cur>dollars|euros|pounds|kronor|yen|rupees|USD|EUR|GBP|SEK|NOK|DKK|CHF)\b",
    re.I,
)

_KIND_WORDS: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (kind, re.compile(pattern, re.I))
    for kind, pattern in (
        ("ransom_paid", r"\bpaid\b.{0,40}\bransom|\bransom\b.{0,40}\b(paid|payment)"),
        ("ransom_demand", r"\bransom|\bdemand(ed|ing|s)?\b|\bextort"),
        ("theft", r"\bstole|\bstolen|\btheft|\bdrain(ed)?\b|\bheist|\bsiphon|\blaunder|\bexploit(ed)? for|\blost\b.{0,20}\bto (hackers|attackers|an exploit)"),
        ("fine", r"\bfine[ds]?\b|\bpenalt"),
        ("settlement", r"\bsettle"),
        ("reward", r"\breward|\bbounty|\bbounties"),
        ("business", r"\braise[sd]?\b|\bfunding|\bseries [a-f]\b|\bvaluation|\bacqui|\brevenue|\binvest|\bmarket (size|cap)|\bbudget|\bipo\b|\bcontract"),
        ("loss", r"\bcost|\blosses|\bloss\b|\bdamage|\bimpact|\bexpense|\bcharge[sd]?\b|\bwrite-?down|\bdisrupt"),
    )
)


_SENTENCE_END = re.compile(r"[.!?;]\s")


def kind_of(before: str, after: str = "") -> str:
    """The kind the nearest cue word says, within the amount's own sentence
    ("stole $3M and was fined EUR 10M": the 10M is a fine)."""
    cut = [m.end() for m in _SENTENCE_END.finditer(before)]
    if cut:
        before = before[cut[-1]:]
    end = _SENTENCE_END.search(after)
    if end:
        after = after[:end.start()]
    best: tuple[int, int, str] | None = None
    for rank, (kind, pattern) in enumerate(_KIND_WORDS):
        for m in pattern.finditer(before):
            d = len(before) - m.end()
            if best is None or (d, rank) < best[:2]:
                best = (d, rank, kind)
        m = pattern.search(after)
        if m and (best is None or (m.start(), rank) < best[:2]):
            best = (m.start(), rank, kind)
    return best[2] if best else "other"


def _number(num: str, mult: str | None) -> float:
    value = float(num.replace(",", ""))
    if mult:
        value *= _MULT.get(mult.lower(), 1.0)
    return value


def find_amounts(text: str) -> list[dict]:
    """Every amount the text states with a currency: the number, the
    currency, its kind by the words around it, and the words themselves."""
    found: list[dict] = []
    taken: list[tuple[int, int]] = []
    for pattern in (_PRE, _POST):
        for m in pattern.finditer(text):
            if any(a < m.end() and m.start() < b for a, b in taken):
                continue
            cur = _SYMBOL.get(m.group("cur").lower(), m.group("cur").upper())
            mult = m.group("mult")
            amount = _number(m.group("num"), mult)
            # A bare "$5" without a multiplier is usually a price, not news.
            if amount < 1000:
                continue
            start, end = m.start(), m.end()
            before = text[max(0, start - 90):start]
            after = text[end:end + 60]
            taken.append((start, end))
            found.append({
                "amount": amount, "currency": cur, "kind": kind_of(before, after),
                "quote": text[max(0, start - 40):min(len(text), end + 30)].strip(),
            })
    return found


# -- exchange rates ---------------------------------------------------------------------------

ECB_DAILY = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml"
#: Used until the first ECB answer, and said to be approximate when used.
FALLBACK_PER_EUR = {"EUR": 1.0, "USD": 1.08, "GBP": 0.85, "SEK": 11.4, "NOK": 11.6, "DKK": 7.46, "CHF": 0.94,
                    "JPY": 160.0, "INR": 90.0, "AUD": 1.65, "CAD": 1.48}


def parse_ecb(xml_text: str) -> dict:
    root = ET.fromstring(xml_text)
    rates = {"EUR": 1.0}
    day = None
    for el in root.iter():
        if el.tag.endswith("Cube") and el.get("time"):
            day = el.get("time")
        if el.tag.endswith("Cube") and el.get("currency"):
            rates[el.get("currency")] = float(el.get("rate"))
    return {"day": day, "per_eur": rates}


def to_usd(amount: float, currency: str, per_eur: dict[str, float]) -> float | None:
    if currency == "USD":
        return amount
    if currency not in per_eur or "USD" not in per_eur:
        return None
    return amount / per_eur[currency] * per_eur["USD"]
