"""What the rules know without a model: the groups and their many names,
well-known companies with their sector and country, countries, and the
words that say what kind of story an item is.

The model (llm.py) finds names the lists do not hold; these lists make the
rules useful without it and keep the names the model finds comparable
(one group, one name)."""

from __future__ import annotations

import re
from dataclasses import dataclass

SECTORS = (
    "technology", "security", "telecom", "finance", "crypto", "government", "defense", "aerospace",
    "health", "retail", "manufacturing", "automotive", "energy", "transport", "education", "media",
    "gaming", "legal", "hospitality", "other",
)

CATEGORIES = (
    "ransomware", "breach", "vulnerability", "malware", "actor", "tool", "policy", "crypto", "ddos", "ai", "other",
)
#: The kinds of story that are security, whichever desk's source told it.
SECURITY_CATEGORIES = ("ransomware", "breach", "vulnerability", "malware", "actor", "crypto", "ddos")

#: Words that put a story on the AI desk (as well as the cyber one, if it is security).
AI_WORDS = re.compile(
    r"(?<![\w])(?:AI|A\.I\.|GenAI)(?![\w])|(?<![\w])(?:artificial intelligence|machine learning|LLMs?|large language models?|"
    r"GPT-?\d[\w.]*|ChatGPT|OpenAI|Anthropic|Claude|Gemini|DeepSeek|Llama|Mistral|Qwen|Copilot|AI agents?|agentic|"
    r"chatbots?|deepfakes?|neural networks?|generative AI|diffusion models?|foundation models?|frontier models?|"
    r"model weights|open[- ]weights?|prompt injection|jailbreak(?:s|ing)?|Hugging Face)(?![\w])",
    re.I,
)
_AI_CASE = re.compile(r"(?<![\w])AI(?![\w])")


def is_ai(text: str) -> bool:
    """Whether a text is about AI. "AI" itself only in capitals ("ai" is a word in many languages)."""
    for m in AI_WORDS.finditer(text):
        if m.group(0).lower() != "ai" or _AI_CASE.match(m.group(0)):
            return True
    return False


@dataclass(frozen=True)
class Known:
    name: str
    type: str  # actor, person, company
    aliases: tuple[str, ...] = ()
    sector: str | None = None
    country: str | None = None
    #: Match the name itself only with this case (a word like "Play").
    exact_case: bool = False
    #: The name alone is too common a word: match only the aliases.
    aliases_only: bool = False


def _a(name: str, *aliases: str, aliases_only: bool = False, country: str | None = None) -> Known:
    return Known(name, "actor", tuple(aliases), country=country, aliases_only=aliases_only)


ACTORS: tuple[Known, ...] = (
    # Extortion crews of the English-speaking scene
    _a("Lapsus$", "LAPSUS$", "Lapsus", "DEV-0537", "Strawberry Tempest"),
    _a("Scattered Spider", "UNC3944", "Octo Tempest", "0ktapus", "Scatter Swine", "Muddled Libra"),
    _a("ShinyHunters", "Shiny Hunters", "UNC6040"),
    _a("Scattered LAPSUS$ Hunters", "Scattered Lapsus$ Hunters", "SLSH"),
    _a("BreachForums", "Breach Forums"),
    _a("IntelBroker", "Intel Broker"),
    # Russia
    _a("APT28", "Fancy Bear", "Forest Blizzard", "Sofacy", "Sednit", "Pawn Storm", "STRONTIUM", country="Russia"),
    _a("APT29", "Cozy Bear", "Midnight Blizzard", "NOBELIUM", "The Dukes", country="Russia"),
    _a("Sandworm", "APT44", "Seashell Blizzard", "Voodoo Bear", country="Russia"),
    _a("Turla", "Secret Blizzard", "Venomous Bear", "Uroburos", country="Russia"),
    _a("Gamaredon", "Aqua Blizzard", "Primitive Bear", "Shuckworm", country="Russia"),
    _a("Star Blizzard", "ColdRiver", "Cold River", "Callisto Group", "SEABORGIUM", country="Russia"),
    _a("NoName057(16)", "NoName057", "NoName 057(16)", "NoName05716", country="Russia"),
    _a("Killnet", "KillNet", country="Russia"),
    _a("Cyber Army of Russia Reborn", "CARR", country="Russia"),
    _a("Evil Corp", "Indrik Spider", country="Russia"),
    # China
    _a("Volt Typhoon", "Vanguard Panda", "Bronze Silhouette", country="China"),
    _a("Salt Typhoon", "GhostEmperor", "FamousSparrow", "Earth Estries", country="China"),
    _a("Silk Typhoon", "Hafnium", country="China"),
    _a("APT41", "Wicked Panda", "Brass Typhoon", "Double Dragon", country="China"),
    _a("Mustang Panda", "Earth Preta", "Twill Typhoon", "RedDelta", country="China"),
    _a("Flax Typhoon", "Ethereal Panda", country="China"),
    _a("Linen Typhoon", "APT27", "Emissary Panda", country="China"),
    # North Korea
    _a("Lazarus Group", "Lazarus", "APT38", "TraderTraitor", "Hidden Cobra", "Diamond Sleet", "Jade Sleet", country="North Korea"),
    _a("Kimsuky", "APT43", "Emerald Sleet", "Velvet Chollima", country="North Korea"),
    _a("Andariel", "Onyx Sleet", "APT45", country="North Korea"),
    # Iran
    _a("Charming Kitten", "APT35", "Mint Sandstorm", "Phosphorus", country="Iran"),
    _a("MuddyWater", "Mango Sandstorm", "Seedworm", "Static Kitten", country="Iran"),
    _a("APT33", "Peach Sandstorm", "Refined Kitten", country="Iran"),
    _a("CyberAv3ngers", "Cyber Av3ngers", country="Iran"),
    _a("Handala", "Handala Hack", country="Iran"),
    # Ransomware brands
    _a("LockBit", "LockBit 3.0", "LockBitSupp"),
    _a("ALPHV", "BlackCat", "ALPHV/BlackCat", "Noberus"),
    _a("Cl0p", "Clop", "Lace Tempest"),
    _a("Akira", "Akira ransomware", aliases_only=True),
    _a("Qilin", "Agenda ransomware"),
    _a("Play", "Play ransomware", "PlayCrypt", aliases_only=True),
    _a("RansomHub", "Ransom Hub"),
    _a("Black Basta", "BlackBasta"),
    _a("BianLian"),
    _a("Rhysida"),
    _a("Medusa", "Medusa ransomware", aliases_only=True),
    _a("INC Ransom", "INC Ransomware"),
    _a("Hunters International"),
    _a("DragonForce", "Dragon Force"),
    _a("SafePay", "SafePay ransomware"),
    _a("Interlock", "Interlock ransomware", aliases_only=True),
    _a("Lynx", "Lynx ransomware", aliases_only=True),
    _a("Fog", "Fog ransomware", aliases_only=True),
    _a("8Base"),
    _a("BlackSuit", "Black Suit", "Royal ransomware"),
    _a("Everest", "Everest ransomware", aliases_only=True),
    _a("Warlock", "Warlock ransomware", "Storm-2603", aliases_only=True),
    _a("Embargo", "Embargo ransomware", aliases_only=True),
    _a("Cicada3301"),
    _a("FIN7", "Carbanak"),
    # People the scene follows
    Known("Arion Kurtaj", "person", ("teapotuberhacker",)),
)

_c = lambda name, sector, country, *aliases, exact_case=False: Known(  # noqa: E731
    name, "company", tuple(aliases), sector=sector, country=country, exact_case=exact_case
)

COMPANIES: tuple[Known, ...] = (
    # Software and cloud, the vendors whose flaws make the news
    _c("Microsoft", "technology", "United States"),
    _c("Google", "technology", "United States", "Alphabet", "Google Cloud", "Mandiant"),
    _c("Apple", "technology", "United States", exact_case=True),
    _c("Amazon", "technology", "United States", "AWS", "Amazon Web Services"),
    _c("Meta", "technology", "United States", "Meta Platforms", "Facebook", "WhatsApp", "Instagram", exact_case=True),
    _c("Oracle", "technology", "United States", exact_case=True),
    _c("SAP", "technology", "Germany", exact_case=True),
    _c("Salesforce", "technology", "United States"),
    _c("Atlassian", "technology", "Australia", "Confluence", "Jira"),
    _c("Adobe", "technology", "United States"),
    _c("IBM", "technology", "United States", exact_case=True),
    _c("Broadcom", "technology", "United States", "VMware", "Symantec"),
    _c("Citrix", "technology", "United States", "NetScaler"),
    _c("Ivanti", "technology", "United States", "Pulse Secure"),
    _c("Progress Software", "technology", "United States", "MOVEit"),
    _c("Fortra", "technology", "United States", "GoAnywhere"),
    _c("SolarWinds", "technology", "United States"),
    _c("Veeam", "technology", "Switzerland"),
    _c("Zimbra", "technology", "United States"),
    _c("GitHub", "technology", "United States"),
    _c("GitLab", "technology", "United States"),
    _c("Snowflake", "technology", "United States", exact_case=True),
    _c("Okta", "security", "United States"),
    _c("Cloudflare", "technology", "United States"),
    _c("Zoom", "technology", "United States", "Zoom Video", exact_case=True),
    _c("Slack", "technology", "United States", exact_case=True),
    _c("Dropbox", "technology", "United States"),
    _c("Twilio", "technology", "United States"),
    _c("OpenAI", "technology", "United States", "ChatGPT"),
    _c("Anthropic", "technology", "United States"),
    _c("Hugging Face", "technology", "United States"),
    _c("Nvidia", "technology", "United States", "NVIDIA"),
    _c("Intel", "technology", "United States", exact_case=True),
    _c("AMD", "technology", "United States", exact_case=True),
    _c("Qualcomm", "technology", "United States"),
    _c("Samsung", "technology", "South Korea"),
    _c("Dell", "technology", "United States", exact_case=True),
    _c("HP", "technology", "United States", "Hewlett-Packard", "HP Inc", "HPE", "Hewlett Packard Enterprise", exact_case=True),
    _c("Lenovo", "technology", "China"),
    _c("Huawei", "telecom", "China"),
    _c("ZTE", "telecom", "China", exact_case=True),
    _c("Hikvision", "technology", "China"),
    _c("Tietoevry", "technology", "Finland", "Tieto"),
    _c("Visma", "technology", "Norway"),
    _c("Spotify", "media", "Sweden"),
    _c("Klarna", "finance", "Sweden"),
    # Security vendors and network gear
    _c("Cisco", "technology", "United States"),
    _c("Fortinet", "security", "United States", "FortiGate", "FortiOS"),
    _c("Palo Alto Networks", "security", "United States", "PAN-OS", "GlobalProtect"),
    _c("Check Point", "security", "Israel"),
    _c("SonicWall", "security", "United States"),
    _c("Juniper Networks", "technology", "United States", "Juniper"),
    _c("F5", "technology", "United States", "BIG-IP", exact_case=True),
    _c("Zscaler", "security", "United States"),
    _c("CrowdStrike", "security", "United States"),
    _c("SentinelOne", "security", "United States"),
    _c("Sophos", "security", "United Kingdom"),
    _c("Trend Micro", "security", "Japan"),
    _c("ESET", "security", "Slovakia", exact_case=True),
    _c("Kaspersky", "security", "Russia"),
    _c("WatchGuard", "security", "United States"),
    _c("Barracuda Networks", "security", "United States", "Barracuda"),
    _c("Rapid7", "security", "United States"),
    _c("Tenable", "security", "United States"),
    _c("LastPass", "security", "United States"),
    _c("1Password", "security", "Canada"),
    _c("Proofpoint", "security", "United States"),
    _c("Recorded Future", "security", "United States"),
    _c("Ericsson", "telecom", "Sweden"),
    _c("Nokia", "telecom", "Finland"),
    # Industry and operational technology
    _c("Siemens", "manufacturing", "Germany"),
    _c("Schneider Electric", "manufacturing", "France"),
    _c("Rockwell Automation", "manufacturing", "United States"),
    _c("ABB", "manufacturing", "Switzerland", exact_case=True),
    _c("Honeywell", "manufacturing", "United States"),
    _c("Volvo", "automotive", "Sweden", "Volvo Cars", "Volvo Group"),
    _c("Scania", "automotive", "Sweden"),
    _c("Jaguar Land Rover", "automotive", "United Kingdom", "JLR"),
    _c("Toyota", "automotive", "Japan"),
    _c("Volkswagen", "automotive", "Germany"),
    _c("Tesla", "automotive", "United States"),
    _c("Asahi", "manufacturing", "Japan", "Asahi Group"),
    # Defense and aerospace
    _c("BAE Systems", "defense", "United Kingdom"),
    _c("Lockheed Martin", "defense", "United States"),
    _c("Boeing", "aerospace", "United States"),
    _c("Airbus", "aerospace", "France"),
    _c("Thales", "defense", "France"),
    _c("Leonardo", "defense", "Italy", exact_case=True),
    _c("Rheinmetall", "defense", "Germany"),
    _c("Kongsberg", "defense", "Norway", "Kongsberg Gruppen"),
    _c("Nammo", "defense", "Norway"),
    _c("Patria", "defense", "Finland", exact_case=True),
    _c("Northrop Grumman", "defense", "United States"),
    _c("RTX", "defense", "United States", "Raytheon", exact_case=True),
    _c("General Dynamics", "defense", "United States"),
    _c("L3Harris", "defense", "United States"),
    _c("MBDA", "defense", "France", exact_case=True),
    _c("Elbit Systems", "defense", "Israel", "Elbit"),
    _c("Dassault Aviation", "aerospace", "France"),
    _c("Naval Group", "defense", "France"),
    _c("Collins Aerospace", "aerospace", "United States"),
    # Telecom
    _c("AT&T", "telecom", "United States"),
    _c("Verizon", "telecom", "United States"),
    _c("T-Mobile", "telecom", "United States"),
    _c("Telia", "telecom", "Sweden", "Telia Company"),
    _c("Tele2", "telecom", "Sweden"),
    _c("Telenor", "telecom", "Norway"),
    _c("Orange", "telecom", "France", exact_case=True),
    _c("Vodafone", "telecom", "United Kingdom"),
    # Finance and crypto
    _c("Nordea", "finance", "Finland"),
    _c("SEB", "finance", "Sweden", exact_case=True),
    _c("Swedbank", "finance", "Sweden"),
    _c("Handelsbanken", "finance", "Sweden"),
    _c("JPMorgan Chase", "finance", "United States", "JPMorgan", "JP Morgan", "J.P. Morgan", "JP Morgan Chase", "Chase Bank"),
    _c("Coinbase", "crypto", "United States"),
    _c("Binance", "crypto", "Malta"),
    _c("Bybit", "crypto", "United Arab Emirates"),
    _c("Kraken", "crypto", "United States", exact_case=True),
    _c("OKX", "crypto", "Seychelles", exact_case=True),
    _c("Visa", "finance", "United States", exact_case=True),
    _c("Mastercard", "finance", "United States"),
    # Health
    _c("UnitedHealth", "health", "United States", "UnitedHealth Group", "Change Healthcare", "Optum"),
    _c("Ascension", "health", "United States", exact_case=True),
    _c("Kaiser Permanente", "health", "United States"),
    # Retail, travel, services
    _c("Marks & Spencer", "retail", "United Kingdom", "M&S"),
    _c("Co-op", "retail", "United Kingdom", "Co-operative Group", exact_case=True),
    _c("Harrods", "retail", "United Kingdom"),
    _c("H&M", "retail", "Sweden", "Hennes & Mauritz"),
    _c("IKEA", "retail", "Sweden", "Ingka", exact_case=True),
    _c("Ticketmaster", "media", "United States", "Live Nation"),
    _c("Uber", "transport", "United States"),
    _c("SAS", "transport", "Sweden", "Scandinavian Airlines", exact_case=True),
    _c("Finnair", "transport", "Finland"),
    _c("23andMe", "health", "United States"),
    _c("Qantas", "transport", "Australia"),
    _c("Allianz", "finance", "Germany"),
    # Games (the leaks the scene follows)
    _c("Rockstar Games", "gaming", "United States", "Rockstar", "GTA 6", "GTA VI", "Grand Theft Auto"),
    _c("Take-Two Interactive", "gaming", "United States", "Take-Two"),
    _c("Ubisoft", "gaming", "France"),
    _c("Electronic Arts", "gaming", "United States", "EA Games"),
    _c("Activision Blizzard", "gaming", "United States", "Activision", "Blizzard Entertainment"),
    _c("Nintendo", "gaming", "Japan"),
    _c("Sony", "gaming", "Japan", "PlayStation", "Insomniac Games"),
    _c("Epic Games", "gaming", "United States"),
    _c("Valve", "gaming", "United States", "Steam", exact_case=True),
    _c("Roblox", "gaming", "United States"),
)

_g = lambda name, country, *aliases, exact_case=False: Known(  # noqa: E731
    name, "government", tuple(aliases), sector="government", country=country, exact_case=exact_case
)

#: Agencies the news names in several ways: one name each.
AGENCIES: tuple[Known, ...] = (
    _g("CISA", "United States", "Cybersecurity and Infrastructure Security Agency",
       "U.S. Cybersecurity and Infrastructure Security Agency", "US Cybersecurity and Infrastructure Security Agency", exact_case=True),
    _g("FBI", "United States", "Federal Bureau of Investigation", exact_case=True),
    _g("NSA", "United States", "National Security Agency", exact_case=True),
    _g("US Department of Justice", "United States", "Department of Justice", "Justice Department", "DOJ", "DoJ"),
    _g("SEC", "United States", "Securities and Exchange Commission", exact_case=True),
    _g("Europol", None),
    _g("Interpol", None, "INTERPOL"),
    _g("ENISA", None, exact_case=True),
    _g("European Commission", None, "EU Commission"),
    _g("NCSC UK", "United Kingdom", "UK National Cyber Security Centre", "UK's National Cyber Security Centre"),
    _g("CERT-SE", "Sweden"),
    _g("Säkerhetspolisen", "Sweden", "Swedish Security Service", "SÄPO", "Säpo"),
    _g("MSB", "Sweden", "Swedish Civil Contingencies Agency", exact_case=True),
)

#: Country, the words that name it, its region. The region decides how near
#: a story is to a profile that names a neighbour.
COUNTRIES: tuple[tuple[str, tuple[str, ...], str], ...] = (
    ("Sweden", ("Swedish", "Sverige"), "nordic"),
    ("Norway", ("Norwegian",), "nordic"),
    ("Denmark", ("Danish",), "nordic"),
    ("Finland", ("Finnish",), "nordic"),
    ("Iceland", ("Icelandic",), "nordic"),
    ("Estonia", ("Estonian",), "baltic"),
    ("Latvia", ("Latvian",), "baltic"),
    ("Lithuania", ("Lithuanian",), "baltic"),
    ("Poland", ("Polish",), "europe"),
    ("Germany", ("German",), "europe"),
    ("France", ("French",), "europe"),
    ("Netherlands", ("Dutch",), "europe"),
    ("Belgium", ("Belgian",), "europe"),
    ("United Kingdom", ("UK", "British", "Britain", "England", "Scotland", "Wales"), "europe"),
    ("Ireland", ("Irish",), "europe"),
    ("Spain", ("Spanish",), "europe"),
    ("Italy", ("Italian",), "europe"),
    ("Switzerland", ("Swiss",), "europe"),
    ("Austria", ("Austrian",), "europe"),
    ("Czech Republic", ("Czech", "Czechia"), "europe"),
    ("Romania", ("Romanian",), "europe"),
    ("Ukraine", ("Ukrainian",), "europe"),
    ("Moldova", ("Moldovan",), "europe"),
    ("Russia", ("Russian",), "adversary"),
    ("Belarus", ("Belarusian",), "adversary"),
    ("China", ("Chinese", "PRC"), "adversary"),
    ("North Korea", ("North Korean", "DPRK"), "adversary"),
    ("Iran", ("Iranian",), "adversary"),
    ("Israel", ("Israeli",), "world"),
    ("United States", ("US", "U.S.", "USA", "American"), "world"),
    ("Canada", ("Canadian",), "world"),
    ("Australia", ("Australian",), "world"),
    ("Japan", ("Japanese",), "world"),
    ("South Korea", ("South Korean",), "world"),
    ("Taiwan", ("Taiwanese",), "world"),
    ("India", ("Indian",), "world"),
    ("Brazil", ("Brazilian",), "world"),
    ("Mexico", ("Mexican",), "world"),
    ("Singapore", ("Singaporean",), "world"),
    ("United Arab Emirates", ("UAE", "Emirati"), "world"),
    ("Turkey", ("Turkish", "Türkiye"), "world"),
)

#: Words that say what kind of story an item is. The first category with a
#: hit wins, in this order (a ransomware attack that leaked data is ransomware).
CATEGORY_WORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("ransomware", ("ransomware", "ransom note", "leak site", "double extortion", "encrypted files", "extortion gang")),
    ("crypto", ("crypto exchange", "cryptocurrency", "defi", "drained", "wallet", "bitcoin", "ethereum", "stablecoin", "web3")),
    ("ddos", ("ddos", "denial-of-service", "denial of service")),
    ("actor", ("arrested", "charged", "indicted", "sentenced", "extradited", "pleaded guilty", "takedown", "seized",
               "sanctioned", "apt", "threat actor", "hacker group", "leaker")),
    ("breach", ("breach", "data leak", "leaked", "exposed", "stolen data", "records", "customer data", "compromised")),
    ("vulnerability", ("cve-", "vulnerability", "vulnerabilities", "zero-day", "0-day", "exploit", "patch", "flaw", "rce",
                       "remote code execution", "security update", "advisory")),
    ("malware", ("malware", "trojan", "backdoor", "botnet", "infostealer", "stealer", "loader", "rat ", "spyware", "wiper",
                 "phishing", "campaign")),
    ("policy", ("law", "regulation", "directive", "nis2", "gdpr", "fine", "fined", "lawsuit", "settlement", "bill ", "policy")),
    ("tool", ("tool", "framework", "open-source", "open source", "github", "released", "technique", "research", "paper",
              "proof-of-concept", "poc")),
)


#: Headlines of digests: many stories in one item. A digest never joins
#: incidents together and counts for less (relevance.py).
ROUNDUP = re.compile(
    r"\b(weekly recap|week in review|in other news|threatsday|this week in|veckobrev|newsletter|roundup|round-up|"
    r"risky bulletin|risky biz news|patch tuesday|top stories|news digest|security affairs newsletter|import ai \d+|"
    r"tl;dr sec|ainews|this week in security)\b",
    re.I,
)


def _pattern(words: list[str], ignore_case: bool) -> re.Pattern[str] | None:
    words = [w for w in words if w]
    if not words:
        return None
    alt = "|".join(re.escape(w) for w in sorted(words, key=len, reverse=True))
    return re.compile(rf"(?<![\w$]){alt}(?![\w$])", re.I if ignore_case else 0)


def _letters(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


class Matcher:
    """Finds the known names in a text. One compiled pattern per known
    thing: the lists are short and the texts a few hundred words."""

    def __init__(self, known: tuple[Known, ...] = ACTORS + COMPANIES + AGENCIES):
        self.entries: list[tuple[Known, list[re.Pattern[str]]]] = []
        for k in known:
            pats = []
            names = list(k.aliases) if k.aliases_only else [k.name, *k.aliases]
            exact = [n for n in names if k.exact_case and n == k.name]
            loose = [n for n in names if n not in exact]
            for words, ic in ((loose, True), (exact, False)):
                p = _pattern(words, ic)
                if p:
                    pats.append(p)
            self.entries.append((k, pats))
        self.by_norm = {k.name.lower(): k for k in known} | {
            a.lower(): k for k in known for a in k.aliases
        }
        # The same letters, whatever the dots and spaces: "J.P. Morgan Chase", "Lock Bit".
        self.by_letters = {_letters(n): k for n, k in self.by_norm.items() if len(_letters(n)) >= 6}

    def find(self, text: str) -> list[Known]:
        return [k for k, pats in self.entries if any(p.search(text) for p in pats)]

    def canonical(self, name: str) -> Known | None:
        """The known thing a name (from the model or a feed) is one of the
        names of, if any."""
        name = name.lower().strip()
        return self.by_norm.get(name) or self.by_letters.get(_letters(name))


_COUNTRY_PATTERNS = [
    (name, region, _pattern([name, *[w for w in words if len(w) > 3]], True), _pattern([w for w in words if len(w) <= 3], False))
    for name, words, region in COUNTRIES
]
REGION_OF = {name: region for name, _w, region in COUNTRIES}


def find_countries(text: str) -> list[str]:
    out = []
    for name, _region, loose, short in _COUNTRY_PATTERNS:
        if (loose and loose.search(text)) or (short and short.search(text)):
            out.append(name)
    return out


def _category_pattern(words: tuple[str, ...]) -> re.Pattern[str]:
    parts = []
    for w in words:
        w = w.strip()
        tail = "" if w.endswith("-") else "(?![a-z0-9])"
        parts.append(rf"(?<![a-z0-9]){re.escape(w)}{tail}")
    return re.compile("|".join(parts), re.I)


_CATEGORY_PATTERNS = [(c, _category_pattern(words)) for c, words in CATEGORY_WORDS]


def category_of(text: str) -> str:
    for category, pattern in _CATEGORY_PATTERNS:
        if pattern.search(text):
            return category
    return "other"


MATCHER = Matcher()


_PLACEHOLDER = re.compile(r"\*{2,}|^company\s*#?\s*\d+$|^victim\s*#?\d+$", re.I)
_NO_ONE = frozenset(("us", "usa", "uk", "eu", "un", "nato", "government", "the government", "military", "police"))


def placeholder(name: str) -> bool:
    """Not a name to show as a company: a leak site's masked or numbered
    victim ("T***Y", "Company #217"), a sector or a country read as one
    ("finance", "US"), or a bare lowercase word ("healthcare")."""
    n = name.strip()
    low = n.lower()
    return bool(_PLACEHOLDER.search(n)) or low in _NO_ONE or low in SECTORS or (n == low and n.isalpha())
