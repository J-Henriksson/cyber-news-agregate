"""The API and the page. Run from backend/:

    uv run uvicorn radar.app:app --port 8740

The built page (frontend/dist) is served at /, the data under /api."""

from __future__ import annotations

import asyncio
import csv
import io
import json
import logging
import time
from contextlib import asynccontextmanager

from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from . import config
from .engine import Radar
from .extract import RULES_VERSION, rules_of
from .llm import LLM_VERSION
from .poller import Poller
from .store import Store

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
# One line a request filled the log with 17,000 lines in seven hours: the poller's own lines say what was read.
logging.getLogger("httpx").setLevel(logging.WARNING)

store = Store(config.DB_PATH)
store.reread_rules(rules_of, RULES_VERSION)
store.reread_llm(LLM_VERSION)
radar = Radar(store)
poller = Poller(store, radar)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    if config.polling_on():
        poller.start()
    yield
    poller.stop.set()
    poller.wake.set()


app = FastAPI(title="cyber-news-agregate", lifespan=lifespan)
# Only this machine's own page speaks to the API: a web page elsewhere that
# points a name at 127.0.0.1 (DNS rebinding) is turned away by its Host.
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "testserver"])


@app.get("/api/health")
def health():
    """For scripts: is it up, how fresh is it."""
    counts = store.count_items()
    return {"ok": True, "items": sum(counts.values()), "incidents": len(radar.incidents()), "built_at": radar.built_at,
            "polling": config.polling_on()}


@app.get("/api/feed")
def feed(days: float = 14, category: str | None = None, q: str | None = None, sort: str = "top",
         min_relevance: int = 0, limit: int = 300, kinds: str | None = None, desk: str | None = None,
         since: float | None = None, show: str | None = None):
    return radar.feed(days, category, q, sort, min_relevance, limit, kinds, desk, since, show)


@app.get("/api/export")
def export(format: str = "csv", days: float = 14, category: str | None = None, q: str | None = None, sort: str = "top",
           min_relevance: int = 0, desk: str | None = None, since: float | None = None, show: str | None = None):
    """The feed as a file: what the same filters show on the page, as CSV or JSON."""
    rows = radar.feed(days, category, q, sort, min_relevance, 5000, None, desk, since, show)["incidents"]
    if format == "json":
        return JSONResponse(rows, headers={"Content-Disposition": 'attachment; filename="cyber-news-agregate.json"'})
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["relevance", "category", "title", "first_seen", "last_seen", "sources", "victims", "attackers", "vendors",
                "cves", "reported_usd", "money_kind", "records", "countries", "url", "id"])
    day = lambda t: time.strftime("%Y-%m-%d %H:%M", time.gmtime(t))  # noqa: E731
    for r in rows:
        w.writerow([r["relevance"], r["category"], r["title"], day(r["first_seen"]), day(r["last_seen"]), len(r["sources"]),
                    "; ".join(r["victims"]), "; ".join(r["attackers"]), "; ".join(r["vendors"]), " ".join(r["cves"]),
                    round(r["headline_usd"]) if r["headline_usd"] else "", r["headline_kind"] or "", r["records"] or "",
                    "; ".join(r["countries"]), r["url"] or "", r["id"]])
    return Response(out.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": 'attachment; filename="cyber-news-agregate.csv"'})


@app.get("/api/brief")
def brief(hours: float = 24, desk: str | None = None, since: float | None = None):
    return radar.brief(hours, desk, since)


@app.get("/api/trending")
def trending(desk: str | None = None):
    return {"trending": radar.trending(desk)}


@app.post("/api/incident/{incident_id}/state")
def set_state(incident_id: str, body: dict = Body(...)):
    """Star, dismiss, note or mark an incident seen: {"starred": true}, {"dismissed": true},
    {"note": "..."}, {"seen": true}."""
    inc = radar.incident(incident_id)
    if inc is None:
        raise HTTPException(404, "no such incident")
    fields = {k: body[k] for k in ("starred", "dismissed", "note") if k in body}
    if body.get("seen"):
        fields["seen"] = time.time()
    return store.set_state(inc["id"], **fields)


@app.get("/api/incident/{incident_id}")
def incident(incident_id: str):
    out = radar.incident(incident_id)
    if out is None:
        raise HTTPException(404, "no such incident (the incidents are rebuilt as news arrives: reload the list)")
    return out


@app.get("/api/graph")
def graph(days: float = 14, min_relevance: int = 0, limit: int = 120, desk: str | None = None, since: float | None = None,
          lens: str = "links"):
    return radar.graph(days, min_relevance, min(limit, 400), desk, since, lens)


@app.get("/api/node")
def node(id: str, days: float = 14, desk: str | None = None, since: float | None = None):
    out = radar.node(id, days, desk, since)
    if out is None:
        raise HTTPException(404, "nothing in this window stands behind that node")
    return out


@app.get("/api/companies")
def companies(days: float = 30, desk: str | None = None, since: float | None = None):
    return radar.companies(days, desk, since)


@app.get("/api/money")
def money(days: float = 90, desk: str | None = None, since: float | None = None):
    return radar.money(days, desk, since)


@app.get("/api/timeline")
def timeline(days: float = 30, desk: str | None = None, since: float | None = None):
    return radar.timeline(days, desk, since)


@app.get("/api/sources")
def sources():
    return radar.sources() | {"busy": sorted(poller.busy), "last_round": poller.last_round,
                              "polling": config.polling_on(), "pages": poller.pages.status()}


@app.get("/api/profile")
def get_profile():
    return radar.profile


@app.put("/api/profile")
def put_profile(profile: dict = Body(...)):
    if not isinstance(profile.get("organization"), str):
        raise HTTPException(400, "the profile needs an organization")
    radar.set_profile(profile)
    return radar.profile


#: At most one change event this often: a poll round changes the store many times.
EVENT_GAP_S = 3.0
HEARTBEAT_S = 15.0


@app.get("/api/events")
async def events(request: Request):
    """Server-sent events: ``hello`` on connect, ``change`` when what the
    views show has changed (with the incidents that are new since the last
    event), ``status`` when sources start or finish reading. The page
    reloads on ``change`` instead of polling."""

    async def stream():
        known: set[str] | None = None
        seen_built = None
        seen_state = store.state_version
        busy = None
        beat = time.monotonic()
        while not poller.stop.is_set():
            if await request.is_disconnected():
                break
            now_busy = sorted(poller.busy)
            if radar.stale():
                # Rebuild off the event loop; readers get the last list meanwhile.
                await asyncio.to_thread(radar.incidents)
            if radar.built != seen_built:
                seen_built = radar.built
                items, fresh = await asyncio.to_thread(radar.news_since, known)
                first = known is None
                known = items
                fresh.sort(key=lambda i: -i["relevance"])
                payload = {"built": seen_built, "items": len(items), "busy": now_busy, "new_count": len(fresh),
                           "new": [{"id": i["id"], "title": i["title"], "relevance": i["relevance"], "category": i["category"]}
                                   for i in fresh[:30]]}
                yield f"event: {'hello' if first else 'change'}\ndata: {json.dumps(payload)}\n\n"
                busy, beat = now_busy, time.monotonic()
                seen_state = store.state_version
                await asyncio.sleep(EVENT_GAP_S)
                continue
            if store.state_version != seen_state:
                # Starred or dismissed in another tab: the lists change, nothing is new.
                seen_state = store.state_version
                yield "event: state\ndata: {}\n\n"
                beat = time.monotonic()
            if now_busy != busy:
                busy = now_busy
                yield f"event: status\ndata: {json.dumps({'busy': now_busy})}\n\n"
                beat = time.monotonic()
            elif time.monotonic() - beat > HEARTBEAT_S:
                yield ": beat\n\n"
                beat = time.monotonic()
            await asyncio.sleep(1.0)

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.post("/api/refresh")
def refresh():
    poller.refresh()
    return {"ok": True}


if config.FRONTEND_DIST.exists():
    app.mount("/assets", StaticFiles(directory=config.FRONTEND_DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def page(path: str):
        target = config.FRONTEND_DIST / path
        if path and target.is_file():
            return FileResponse(target)
        return FileResponse(config.FRONTEND_DIST / "index.html")
