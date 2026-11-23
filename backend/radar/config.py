"""Where things live, which model reads the news, and how much it may spend."""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]  # cyber-news-agregate/


def load_dotenv(path: Path = ROOT / ".env") -> None:
    """KEY=value lines of the project's .env into the environment (what the
    environment already holds wins)."""
    if os.environ.get("RADAR_NO_DOTENV") == "1" or not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


load_dotenv()

DATA = Path(os.environ.get("RADAR_DATA", ROOT / "data"))
DB_PATH = DATA / "radar.sqlite3"
PROFILE_PATH = Path(os.environ.get("RADAR_PROFILE", ROOT / "profile.json"))
FRONTEND_DIST = ROOT / "frontend" / "dist"

#: Items older than this are dropped from the store.
KEEP_DAYS = 90
#: Sent with every request. Generic on purpose: no name or address of the user.
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) cyber-news-agregate/0.1"

LLM_MODEL = os.environ.get("RADAR_LLM_MODEL", "gemini-3.5-flash-lite")
#: Model calls a day (UTC). One call reads a batch of items.
LLM_DAILY_CALLS = int(os.environ.get("RADAR_LLM_DAILY_CALLS", "60"))
LLM_BATCH = int(os.environ.get("RADAR_LLM_BATCH", "20"))
#: USD per million tokens (input, output), list price, for the spend shown.
LLM_PRICE = (0.30, 2.50)


def gemini_key() -> str:
    """Read at call time, so a test or a shell can blank it."""
    return os.environ.get("GEMINI_API_KEY", "").strip()


def polling_on() -> bool:
    return os.environ.get("RADAR_POLL", "1") != "0"
