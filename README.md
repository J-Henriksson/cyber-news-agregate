# cyber-news-agregate

Cybersecurity and AI news from about 60 free sources, read every few minutes, grouped into
incidents, scored for how much they matter to us, and shown as a daily brief, a feed and
graphs. The page updates by itself as news arrives.

## Run it

```bash
./run.sh            # builds the page if needed, then serves http://127.0.0.1:8740
```

Needs `uv` and Node (npm). The first start reads every source at once (a few minutes: GitHub
is the slow one); after that each source is read on its own clock.

To have it collect whenever you are logged in, with no terminal open:
`tools/install-service.sh` (a systemd service of your user; the script says how to undo it).
It only collects while it runs.

The model reads the news when `.env` holds a Gemini key (see `.env.example`). Without one,
the rules read it alone: known groups, companies, CVEs, amounts and countries, but not the
names the lists do not hold, nor summaries.

For work on the page: `cd frontend && npm run dev` serves it on :5740 with the API proxied
to :8740. Tests: `cd backend && uv run pytest`. A walk of the running page in a headless
browser: `uv run --with playwright==1.62.0 python tools/walk.py`.

## A copy on GitHub Pages

A read-only copy of the page can be kept on GitHub Pages, to read from anywhere. It is made
and pushed from this machine while the app runs: once when the sources have been read after
a start, then every hour when something changed (`RADAR_PAGES_EVERY_MIN`; 0 for only the
copy after a start). Turn it on in `.env`:

```bash
RADAR_PAGES=origin    # a remote of this repository, or an address
```

The copy is the one commit of the branch `gh-pages`, replaced each time. Once, in the
repository's settings on GitHub: Pages, deploy from the branch `gh-pages`, folder `/`. On
GitHub's free plan Pages needs a public repository. By hand:
`cd backend && uv run python -m radar.pages` (`--no-push` only makes it, in `data/pages`).
The Sources view says when the last copy went out, or why it did not.

The copy is the same page reading its data from files, as it stood when it was made: its
windows end there and "Today" is that day. It cannot star, dismiss, note, alert or read
now, has no Profile view, and its graph shows the top 120 incidents of relevance 10 or
more. It leaves out what is the reader's own (stars, notes), the model's calls and spend,
what was dismissed, and every incident that writes a word of `RADAR_PAGES_WITHHOLD`. It is
public: anyone with the address reads it, and the reason beside each score shows what the
profile holds.

## The page

The top bar picks the **desk** (All, Cyber, AI) and the **window**: Today (since midnight on
this computer's clock) or the last 3 to 90 days. Every view follows both, and the address
holds them, so a link or a reload opens the same place.

| View | Shows |
|---|---|
| Brief | The day on one page: what matters most to us, flaws being exploited in our stack, what is named more than usual, the money reported, what you starred, new tools for the team's work, AI news |
| Feed | Every incident with the reasons for its score. Order by Top (relevance fading with age), Relevance, Newest or Money; show All, Starred, Updated or Dismissed; download as CSV or JSON |
| Graph | Four lenses, each for one question. **Us**: why does it matter to us (our organisation in the middle, the parts of the profile that matched around it, each incident on the part that gave it most). **Links**: what is connected (incidents and only what two or more of them share). **Companies**: which companies are tied together (hit together, hit through another's product, owned by one another; those tied to no other stand in rows underneath). **Groups**: who hits whom. Shape says what a mark is, the blue ramp how much it matters to us, a green ring that the profile names it. Click a mark for what stands behind it; every lens has a table of the same data |
| Companies | The companies hit (or whose software was), by sector, as a map or a table; their parents, subsidiaries and the companies hit alongside them |
| Money | Every amount a source stated, in dollars, by kind (stolen, ransom asked or paid, loss, fine, settlement), with the words it was stated in |
| Timeline | Incidents by day (by hour for Today) and kind, and each group's incidents on its own lane |
| Sources | What each source last answered, what is not read and why, the model's calls and spend |
| Profile | Who "us" is: the profile relevance is scored against |

**An incident** (click one anywhere) shows its sources, who did what to whom, the money, the
flaws, related incidents, and the companies around the victims. There you can:

- **Star** it: it stays in the Brief, and is marked "updated" when it is told again.
- **Dismiss** it: not for us; it leaves every view (Feed, Dismissed brings it back).
- **Note** it, and **Copy** it as Markdown for a chat, a ticket or a mail.

**Keys:** `/` search, `j` `k` move through the feed, `Enter` open, `s` star, `x` dismiss,
`Esc` close.

**Alerts** (top bar, off until you turn them on): a desktop notification for each new
incident of relevance 50 or more.

The page follows the system's light or dark theme. Charts are drawn at their real size and
each has a table of the same data. In the graph: hover lights up a mark and what it is tied
to, click opens what stands behind it, drag moves a mark, the wheel zooms, Fit brings all of
it back into view, and the search box lights up what it names.

## Sources

All free and keyless.

- **Security press:** BleepingComputer, The Record, KrebsOnSecurity, SecurityWeek, The Hacker News, Dark Reading, DataBreaches.net, CyberScoop, Help Net Security, The Register, TechCrunch, Ars Technica, 404 Media, Risky Bulletin, Schneier on Security.
- **Research teams:** Cisco Talos, Unit 42, Google Project Zero, Securelist, SentinelLabs, watchTowr Labs, GreyNoise, Wiz Research, SANS ISC, Microsoft Security, Embrace The Red.
- **Advisories:** CERT-SE, CERT-EU, NCSC-FI, NCSC UK, CISA.
- **Exploited flaws:** CISA KEV, with FIRST's EPSS scores.
- **Leak sites:** RansomLook (a gang's own claim, marked as a claim).
- **Breaches:** Have I Been Pwned. **Crypto thefts:** DefiLlama. **Filings:** SEC form 8-K item 1.05.
- **The scene:** Bluesky (popular posts on breach and exploit searches), Mastodon (security writers on infosec.exchange), Hacker News.
- **Tools and methods:** new GitHub security repositories with stars, arXiv cs.CR.
- **The AI desk:** OpenAI, Google DeepMind, Google AI, Mistral, NVIDIA and Hugging Face announcements; The Verge, TechCrunch, Ars Technica, MIT Technology Review and The Decoder on AI; Simon Willison, Import AI, Latent Space, AI Snake Oil; the AI Incident Database; Hacker News on AI; new AI repositories on GitHub; trending new models on Hugging Face.
- **Around the companies:** Wikidata (parents, subsidiaries, industry, staff). **Exchange rates:** the ECB.

Not read: X (its API is paid and scraping breaks its terms), Reddit and VentureBeat (refuse
this client), Anthropic (no feed), Telegram and leak forums (their claims arrive through
RansomLook and the press). Some linked articles are behind a paywall (The Verge, MIT
Technology Review, 404 Media, the WSJ and others): the page says so on the link, and only
their headline and teaser were read.

## How it works

1. **Read** (`radar/sources.py`, `radar/poller.py`): each source on its own clock (news every
   15 to 30 minutes, the slow lists every 6 to 12 hours), with conditional requests so an
   unchanged feed costs a few bytes, into one SQLite file (`data/radar.sqlite3`). Items are
   kept 90 days, social posts 14.
2. **Find** (`radar/extract.py`, `radar/llm.py`): rules find the known names, CVEs, amounts,
   records and countries; Gemini reads the news in batches of 20 for every company, group and
   person with their part (victim, vendor, attacker), the amounts and their kind, and one
   sentence. **Nothing the model says is kept unless the item's own text holds it**: a name
   must be written in the item, an amount quoted from it, and an answer must carry its item's
   key and first words.
3. **Group** (`radar/cluster.py`): items about one thing become one incident: the same victim;
   one flaw's CVE; and, from different sources within days, a near-identical headline, two
   uncommon words one of which is a name, or a flaw of the same seldom-named maker. A digest
   of many stories joins nothing. An incident keeps its id as reports join it, so a star, a
   note or a link holds.
4. **Score** (`radar/relevance.py`) against `profile.json`. The points are written in the
   file's header and shown with every incident: names us +60, a tool we build on +40, a
   supplier hit +40, software we run in a security story +25 (exploited +20), an advisory
   from an authority of ours (CERT-SE +20), a peer hit +15, our sector +12, a country of ours
   by its weight, a group we watch +15, what the team works on by its points, a major
   company hit, reported money and records, more sources; a roundup counts 60% and a claim
   nothing confirms 70%.
5. **Tell the page** (`/api/events`, server-sent events): when anything it shows has changed,
   the backend says so with the incidents that are new, at most once every 3 seconds. The
   page reloads the open view, marks what is new, and keeps the graph's nodes where they
   stood. Nothing polls.

The first profile is an example to start from: a made-up organisation ("Example Org") in
defence and aerospace, the Nordic and Baltic countries, a typical enterprise stack, CERT-SE
as our authority, and the team's projects (ARTEX, mara, ai-course-thingy). Correct it in the
Profile view.

## Cost

Every source is free. The one cost is the model: Gemini bills per token. A call (20 items)
costs about $0.007 at list price (measured 2026-11-20). The sources bring a few hundred
items a day for it to read, so 10 to 20 calls: **about $0.10 a day, $3 a month**. The cap is
60 calls a day ($0.41 at most), set by `RADAR_LLM_DAILY_CALLS`; the Sources view shows the
day's calls and spend. Without a key it runs on the rules alone for nothing.

## Limits

- **Money is what was reported**, not what was lost. Most incidents state no amount, asked
  ransoms are not paid ones, and a total adds up claims of very different weight.
- **History starts at the first run.** Feeds give a few days to a few weeks back; the
  timeline is thin before the day the radar first ran.
- **Grouping is by rules.** Two stories about one breach that share no victim name, CVE,
  name or wording stay apart; two different stories that share them can join.
- **A leak-site post is a claim.** It is marked as one and scores less until something
  confirms it.
- **The page is for this machine.** The API answers only to 127.0.0.1 and has no logins. The copy on GitHub
  Pages is the one thing meant for elsewhere, and it only reads.
