"""Walk the running page in a headless browser: every view, and the things
a reader does (move with the keys, star, dismiss, note, copy, a link kept
across a reload, the graph's switches, the table of companies, a narrow
screen). Whatever it stars, dismisses or notes it puts back.

    uv run --with playwright==1.62.0 python tools/walk.py [out_dir] [base_url]

Screenshots land in out_dir (default: /tmp/radar-walk). Exits 1 on a failure."""

import json
import sys
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/radar-walk")
BASE = (sys.argv[2] if len(sys.argv) > 2 else "http://127.0.0.1:8740").rstrip("/") + "/"
OUT.mkdir(parents=True, exist_ok=True)
failures: list[str] = []


def api(path: str, body: dict | None = None):
    req = urllib.request.Request(BASE + "api/" + path, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json"}, method="POST" if body is not None else "GET")
    return json.load(urllib.request.urlopen(req))


def check(ok: bool, what: str) -> None:
    print(("ok    " if ok else "FAIL  ") + what)
    if not ok:
        failures.append(what)


with sync_playwright() as p:
    browser = p.chromium.launch(args=["--disable-dev-shm-usage"])
    context = browser.new_context(viewport={"width": 1600, "height": 1000})
    context.grant_permissions(["clipboard-read", "clipboard-write"], origin=BASE.rstrip("/"))
    page = context.new_page()
    errors: list[str] = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" and "favicon" not in m.text else None)
    nav = lambda name: page.locator(".nav button", has_text=name).click()  # noqa: E731

    # Brief: the landing view.
    page.goto(BASE)
    page.wait_for_selector(".brief .tiles")
    check(page.locator(".brief-cols section").count() >= 6, "brief shows its sections")
    page.wait_for_timeout(800)
    page.screenshot(path=OUT / "brief.png")

    # Feed: keys, star, dismiss.
    nav("Feed")
    page.wait_for_selector(".row")
    check(page.locator(".row").count() > 5, "feed lists incidents")
    page.keyboard.press("j")
    page.keyboard.press("j")
    cur = page.locator(".row.cur")
    check(cur.count() == 1, "j moves a cursor through the feed")
    inc_id = cur.get_attribute("data-id")
    page.keyboard.press("s")
    page.wait_for_timeout(700)
    check(api(f"incident/{inc_id}")["state"]["starred"] is True, "s stars the incident under the cursor")
    page.keyboard.press("s")
    page.wait_for_timeout(700)
    check(api(f"incident/{inc_id}")["state"]["starred"] is False, "s again removes the star")
    before = page.locator(".row").count()
    page.keyboard.press("x")
    page.wait_for_timeout(900)
    check(page.locator(f'.row[data-id="{inc_id}"]').count() == 0, "x dismisses: the incident leaves the feed")
    page.locator(".toolbar .seg button", has_text="Dismissed").click()
    page.wait_for_timeout(900)
    check(page.locator(f'.row[data-id="{inc_id}"]').count() == 1, "it is kept under Dismissed")
    api(f"incident/{inc_id}/state", {"dismissed": False})
    page.locator(".toolbar .seg button", has_text="All").click()
    page.wait_for_timeout(900)
    check(page.locator(".row").count() == before, "brought back, the feed is as before")
    page.screenshot(path=OUT / "feed.png")

    # An incident: panel, note, copy, and the link holding across a reload.
    page.locator(".row").first.click()
    page.wait_for_selector(".panel h1")
    opened = page.url.split("i=")[-1].split("&")[0]
    check("i=" in page.url, "an open incident is in the address")
    page.locator("textarea.note-box").fill("walk.py was here")
    page.locator(".panel h1").click()
    page.wait_for_timeout(700)
    check(api(f"incident/{opened}")["state"]["note"] == "walk.py was here", "a note is kept")
    page.locator(".panel-acts button", has_text="Copy").click()
    page.wait_for_timeout(300)
    copied = page.evaluate("navigator.clipboard.readText()")
    check(copied.startswith("## ") and "walk.py was here" in copied, "Copy gives the incident as Markdown, note included")
    page.screenshot(path=OUT / "incident.png")
    page.reload()
    page.wait_for_selector(".panel h1")
    check(page.locator(".panel h1").count() == 1, "after a reload the same incident is open")
    page.locator("textarea.note-box").fill("")
    page.locator(".panel h1").click()
    page.wait_for_timeout(700)
    check(api(f"incident/{opened}")["state"]["note"] is None, "the note is cleared again")
    page.keyboard.press("Escape")
    page.wait_for_timeout(300)
    check(page.locator(".panel").count() == 0, "Esc closes the panel")

    # Graph: draws, and the legend switches a kind of node off.
    nav("Graph")
    hits = ".graph-stage svg > g > g:last-child circle"
    lens = lambda name: page.locator(".graph-bar .seg", has=page.locator("button", has_text="Links")).locator("button", has_text=name).click()  # noqa: E731
    counts = {}
    for name in ("Us", "Links", "Companies", "Groups"):
        lens(name)
        page.wait_for_timeout(1500)
        counts[name] = page.locator(hits).count()
        check(counts[name] > 3, f"graph, lens {name}: draws ({counts[name]} marks)")
    # No name the reader looks for first is left out for want of room (incident titles and CVE ids may be).
    lens("Links")
    page.wait_for_timeout(1500)
    hidden = page.evaluate("""() => [...document.querySelectorAll('.graph-stage svg > g > g:nth-child(5) text')]
        .filter(t => t.getAttribute('display') === 'none').map(t => t.textContent)""")
    unnamed = [h for h in hidden if len(h) <= 30 and not h.startswith("CVE-")]
    check(len(unnamed) <= 2, f"links lens: the names of what ties incidents together are drawn ({unnamed[:5]} left out)")
    toggles = page.locator(".legend-btn")
    if toggles.count():
        nodes = page.locator(hits).count()
        toggles.first.click()
        page.wait_for_timeout(1200)
        check(page.locator(hits).count() != nodes, "a legend switch hides its kind of node")
        toggles.first.click()
        page.wait_for_timeout(800)
    # A part of the profile opens what stands behind it; one of its incidents opens the panel.
    lens("Us")
    page.wait_for_timeout(1500)
    page.locator(hits).nth(1).click(force=True)
    page.wait_for_selector(".inspector h4")
    check(page.locator(".inspector .items li").count() >= 1, "a mark opens its inspector with its incidents")
    page.locator(".inspector .items a").first.click()
    page.wait_for_selector(".panel h1")
    check(page.locator(".panel h1").count() == 1, "an incident in the inspector opens the incident panel")
    page.keyboard.press("Escape")
    page.locator(".graph-bar .seg button", has_text="Table").click()
    page.wait_for_selector(".graph-table tbody tr")
    check(page.locator(".graph-table tbody tr").count() >= 3, "the graph has a table of the same data")
    page.locator(".graph-bar .seg button", has_text="Graph").last.click()
    page.wait_for_timeout(600)
    page.reload()
    page.wait_for_selector(".graph-bar")
    check(page.locator(".graph-bar .seg button.on", has_text="Us").count() == 1, "the lens is remembered over a reload")

    nav("Companies")
    page.wait_for_selector(".treemap-wrap svg rect")
    page.wait_for_timeout(800)
    page.screenshot(path=OUT / "companies.png")
    page.locator(".toolbar .seg button", has_text="Table").click()
    page.wait_for_selector("table.grid tbody tr")
    check(page.locator("table.grid tbody tr").count() > 3, "companies as a table")

    for view in ("Money", "Timeline", "Exposure", "Sources", "Profile"):
        nav(view)
        page.wait_for_timeout(1800)
        page.screenshot(path=OUT / f"{view.lower()}.png")
        check(page.locator(".view").count() == 1, f"{view} renders")

    # A narrow screen: nothing spills sideways.
    page.set_viewport_size({"width": 420, "height": 840})
    nav("Brief")
    page.wait_for_selector(".brief .tiles")
    page.wait_for_timeout(600)
    spill = page.evaluate("document.scrollingElement.scrollWidth - window.innerWidth")
    check(spill <= 1, f"narrow screen: no sideways scroll (spill {spill}px)")
    page.screenshot(path=OUT / "narrow.png")

    check(not errors, f"no page errors ({errors[:3]})")
    browser.close()

print(f"\n{len(failures)} failure(s). Screenshots in {OUT}")
sys.exit(1 if failures else 0)
