"""Who "us" is: the organisation, its sector and countries, the software it
runs, its suppliers and peers, the groups it watches, and what the team
works on. Kept in profile.json at the project root and edited in the
page's Profile view; relevance.py scores every incident against it.

The default is an example to start from (a made-up organisation in defence
and aerospace; the team's ARTEX, mara and ai-course-thingy projects):
change it in the page."""

from __future__ import annotations

import json
from pathlib import Path

from .config import PROFILE_PATH

DEFAULT: dict = {
    "organization": "Example Org",
    "aliases": ["Example Org"],
    "sectors": ["defense", "aerospace", "government"],
    "countries": {"Sweden": 15, "Norway": 8, "Finland": 8, "Denmark": 8, "Estonia": 6, "Latvia": 6, "Lithuania": 6,
                  "Poland": 4, "Germany": 3, "United Kingdom": 3},
    "stack": ["Microsoft", "Cisco", "Fortinet", "Palo Alto Networks", "Ivanti", "Citrix", "Broadcom", "Atlassian",
              "SAP", "Siemens", "GitHub", "GitLab", "Okta", "CrowdStrike", "Linux", "Windows", "Exchange", "SharePoint"],
    #: Sources whose advisories we answer to: an advisory of theirs on an incident scores the points.
    "authorities": {"CERT-SE": 20, "CERT-EU": 10, "NCSC-FI": 8, "NCSC UK": 6, "CISA advisories": 6},
    "suppliers": [],
    "own_tools": ["ARTEX"],
    "peers": ["BAE Systems", "Lockheed Martin", "Airbus", "Thales", "Leonardo", "Rheinmetall", "Kongsberg", "Patria",
              "Nammo", "Boeing", "Northrop Grumman", "RTX", "General Dynamics", "L3Harris", "MBDA", "Elbit Systems",
              "Dassault Aviation", "Naval Group"],
    "actors": ["APT28", "APT29", "Sandworm", "Turla", "Star Blizzard", "NoName057(16)", "Lapsus$", "Scattered Spider",
               "ShinyHunters", "Scattered LAPSUS$ Hunters", "Lazarus Group", "Kimsuky", "Volt Typhoon", "Salt Typhoon",
               "APT41", "Charming Kitten", "Arion Kurtaj"],
    "interests": [
        {"name": "AI pentesting agents", "project": "ARTEX", "points": 20,
         "keywords": ["autonomous pentest", "AI pentest", "AI-powered pentest", "pentest agent", "penetration testing agent",
                      "LLM agent", "agentic", "offensive AI", "AI red team", "AI hacking", "AI-driven attack", "MCP server",
                      "prompt injection", "jailbreak", "XBOW", "CAI framework", "PentAGI"]},
        {"name": "File and malware triage", "project": "mara", "points": 15,
         "keywords": ["malware analysis", "static analysis", "YARA", "reverse engineering", "Ghidra", "IDA Pro",
                      "disassembler", "malicious document", "LNK file", "shortcut file", "macro", "infostealer", "loader",
                      "sandbox evasion", "obfuscation"]},
        {"name": "AI in defence", "project": "", "points": 15,
         "keywords": ["military AI", "defense AI", "defence AI", "AI in defense", "AI in defence", "autonomous weapons",
                      "lethal autonomous", "AI targeting", "drone swarm", "Pentagon AI", "NATO AI", "battlefield AI"]},
        {"name": "Frontier models", "project": "ARTEX", "points": 8,
         "keywords": ["frontier model", "new model", "model release", "open-weight", "open weights", "GPT-5", "GPT-6",
                      "Claude", "Gemini", "Llama", "DeepSeek", "Qwen", "Mistral", "reasoning model", "benchmark"]},
        {"name": "AI regulation", "project": "", "points": 6,
         "keywords": ["AI Act", "AI regulation", "AI law", "AI safety institute", "AI executive order", "AI governance"]},
        {"name": "ML malware detection", "project": "ai-course-thingy", "points": 15,
         "keywords": ["machine learning malware", "malware detection", "malware classifier", "EMBER", "adversarial malware",
                      "detection model", "ML-based detection", "AI-generated malware", "LLM-generated malware"]},
    ],
}


def load(path: Path = PROFILE_PATH) -> dict:
    if not path.exists():
        save(DEFAULT, path)
        return json.loads(json.dumps(DEFAULT))
    profile = json.loads(path.read_text())
    return {**DEFAULT, **profile}


def save(profile: dict, path: Path = PROFILE_PATH) -> None:
    path.write_text(json.dumps(profile, indent=2, ensure_ascii=False) + "\n")
