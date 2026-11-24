# cyber-news-agregate

Reads cybersecurity and AI news from about 60 free feeds, groups the stories that are about
the same incident, and ranks them by how much they matter to you. There is a daily brief, a
searchable feed and some graphs.

Read-only demo: https://j-henriksson.github.io/cyber-news-agregate/

## Run it

```bash
./run.sh
```

Then open http://127.0.0.1:8740. You need `uv` and Node. The first start takes a few minutes
because every feed is read once.

Go to Profile first and fill in your sector, countries, the software you run and the groups
you care about. Scores are worked out against that.

Keys: `/` search, `j` `k` move, `Enter` open, `s` star, `x` dismiss.

`tools/install-service.sh` keeps it running in the background.

## How it works

Feeds are polled into a SQLite file in `data/`. Rules pull out names, CVEs and amounts,
similar items are merged into one incident, and each incident is scored against your profile.

With a Gemini key in `.env` (copy `.env.example`) it also picks out company names, amounts
and a one-line summary per story. Without a key it still works, with less detail. This is the
only part that costs money: about a cent per call, capped at 60 calls a day.

Owners and subsidiaries of the companies come from Wikidata, which refuses scripts that give
no contact. Set `RADAR_CONTACT` in `.env` to a URL or an e-mail address to get them.

## Sources

Security press, research blogs, CERT advisories, CISA's exploited-vulnerability list,
leak-site, breach and crypto-theft trackers, SEC filings, Bluesky, Mastodon, Hacker News and
the main AI news feeds. All free, no API keys. The list is in `backend/radar/sources.py`.
X, Reddit and Telegram are not read.

## GitHub Pages

Set `RADAR_PAGES=origin` in `.env` and the app pushes a read-only snapshot to the `gh-pages`
branch when it starts, then hourly if something changed. Stars, notes and the profile editor
stay on your machine. The snapshot is public.

## Development

```bash
cd backend && uv run pytest
cd frontend && npm run dev      # page on :5740, API proxied to :8740
uv run --with playwright==1.62.0 python tools/walk.py    # clicks through the running page
```

## Good to know

- Money figures are what a source reported, not verified losses.
- Grouping is rule-based, so it sometimes merges two stories or splits one.
- There is no login. The app only listens on 127.0.0.1.
