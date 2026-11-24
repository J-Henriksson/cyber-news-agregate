"""The read-only copy for GitHub Pages: what it holds, what it leaves out,
and that it is pushed as one commit that replaces the last. The only
remote here is a bare repository of the test's own."""

import json
import shutil
import subprocess
import time

import pytest

from radar import config, pages
from radar.engine import Radar
from radar.extract import rules_of
from radar.store import Store

NOW = time.time()


def _radar() -> Radar:
    store = Store(":memory:")
    store.upsert_items([
        {"id": "1", "source": "RansomLook", "kind": "ransomware", "title": "akira claims Acme Corp", "text": "",
         "published": NOW - 3600, "data": {"group": "Akira", "victim": "Acme Corp"}},
        {"id": "2", "source": "The Record", "kind": "news", "title": "Acme Corp confirms Akira attack",
         "text": "Akira demanded $2 million from Acme Corp in Sweden.", "published": NOW - 1800, "data": {}},
        {"id": "3", "source": "The Record", "kind": "news", "title": "Globex Industries says intruders copied its payroll",
         "text": "", "published": NOW - 900, "data": {}},
        {"id": "4", "source": "BleepingComputer", "kind": "news", "title": "Initech ships a firmware fix for its routers",
         "text": "", "published": NOW - 600, "data": {}},
    ], rules_of)
    store.put("wd:acme", {"qid": "Q1", "label": "Acme Corp", "parent": ["Globex Industries"], "subsidiaries": [],
                          "industry": ["retail"], "url": "https://www.wikidata.org/wiki/Q1"})
    return Radar(store)


def _titled(radar: Radar, word: str) -> dict:
    return next(i for i in radar.incidents() if word in i["title"])


@pytest.fixture
def dist(tmp_path):
    """A built page: an index and one asset."""
    d = tmp_path / "dist"
    (d / "assets").mkdir(parents=True)
    (d / "index.html").write_text("<!doctype html><html><head><title>t</title></head><body></body></html>")
    (d / "assets" / "app.js").write_text("console.log('the page')")
    return d


def _texts(out) -> str:
    return "\n".join(p.read_text() for p in out.rglob("*") if p.is_file() and p.suffix in pages.TEXT)


def test_a_copy_holds_every_view_and_nothing_of_the_reader(tmp_path, dist):
    radar = _radar()
    acme, globex, initech = (_titled(radar, w) for w in ("Acme", "Globex", "Initech"))
    radar.store.set_state(acme["id"], starred=True, note="ours to handle, ask Kim")
    radar.store.set_state(initech["id"], dismissed=True)
    out = tmp_path / "site"
    made = pages.snapshot(radar, out, dist=dist, words=[])

    index = (out / "index.html").read_text()
    assert 'name="radar-snapshot"' in index and "data-midnight=" in index and index.index("radar-snapshot") < index.index("</head>")
    assert (out / ".nojekyll").is_file() and (out / "assets" / "app.js").is_file()
    read = lambda name: json.loads((out / "data" / f"{name}.json").read_text())  # noqa: E731

    rows = read("feed")["rows"]
    assert {r["id"] for r in rows} == {acme["id"], globex["id"]}, "what was dismissed is left out, the rest is there"
    assert all("akira" in r["hay"] or "globex" in r["hay"] for r in rows), "every row carries what the search reads"
    assert all(r["state"] == {"starred": False, "dismissed": False, "seen": None, "note": None, "updated": False} for r in rows)
    assert "ask Kim" not in _texts(out) and read("brief-72-all")["starred"] == []
    assert made["incidents"] == 2 and made["files"] == len([p for p in out.rglob("*") if p.is_file()]) - 1  # the asset

    # Every view the page asks for, at every window and desk.
    for desk in ("all", "cyber", "ai"):
        assert read(f"brief-today-{desk}")["counts"]["incidents"] <= 2
        for win in ("today", "3", "7", "14", "30", "90"):
            for view in ("graph-us", "graph-links", "graph-companies", "graph-groups", "nodes", "companies", "money", "timeline"):
                assert (out / "data" / f"{view}-{win}-{desk}.json").is_file(), f"{view} at {win}, {desk}"
    # A mark of the graph has what stands behind it, and an incident its own file.
    groups = read("graph-groups-14-all")
    assert {n["label"] for n in groups["nodes"]} == {"Akira", "Acme Corp"}
    assert read("nodes-14-all")["e:acme"]["incidents"][0]["id"] == acme["id"]
    detail = read(f"incident/{acme['id']}")
    assert len(detail["items"]) == 2 and detail["state"]["note"] is None and detail["companies"]["Acme Corp"]["qid"] == "Q1"
    assert not (out / "data" / "incident" / f"{initech['id']}.json").exists()
    # The model's calls and spend stay here.
    model = read("sources")["model"]
    assert model["today"]["calls"] == 0 and model["cost_today_usd"] == 0 and model["states"] == {}

    # The next copy replaces this one, file for file.
    radar.store.set_state(globex["id"], dismissed=True)
    pages.snapshot(radar, out, dist=dist, words=[])
    assert [r["id"] for r in read("feed")["rows"]] == [acme["id"]]
    assert not (out / "data" / "incident" / f"{globex['id']}.json").exists()


def test_an_incident_that_writes_a_withheld_word_is_left_out(tmp_path, dist):
    radar = _radar()
    out = tmp_path / "site"
    pages.snapshot(radar, out, dist=dist, words=["Globex"])
    text = _texts(out).lower()
    assert "globex" not in text, "neither its incident nor what Wikidata says of another company's owner"
    rows = json.loads((out / "data" / "feed.json").read_text())["rows"]
    assert [r["title"] for r in rows if "Acme" in r["title"]] and len(rows) == 2
    assert json.loads((out / "data" / "companies-14-all.json").read_text())["companies"][0]["wikidata"] is None


def test_a_copy_that_still_holds_the_word_is_refused(tmp_path, dist):
    (dist / "assets" / "app.js").write_text("console.log('made at Globex')")
    with pytest.raises(pages.Withheld):
        pages.snapshot(_radar(), tmp_path / "site", dist=dist, words=["globex"])


def test_a_folder_of_something_else_is_not_emptied(tmp_path, dist):
    out = tmp_path / "documents"
    out.mkdir()
    (out / "thesis.txt").write_text("years of work")
    with pytest.raises(ValueError):
        pages.snapshot(_radar(), out, dist=dist, words=[])
    assert (out / "thesis.txt").read_text() == "years of work"


@pytest.mark.skipif(shutil.which("git") is None, reason="needs git")
def test_a_copy_is_pushed_as_the_one_commit_of_its_branch(tmp_path, dist):
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", "--quiet", str(remote)], check=True)
    git = lambda *a: subprocess.run(["git", "--git-dir", str(remote), *a], check=True, capture_output=True, text=True).stdout  # noqa: E731
    radar, out = _radar(), tmp_path / "site"

    pages.snapshot(radar, out, dist=dist, words=[])
    pages.publish(out, str(remote), "gh-pages")
    first = git("rev-parse", "gh-pages").strip()
    assert git("rev-list", "--count", "gh-pages").strip() == "1"
    assert "radar-snapshot" in git("show", "gh-pages:index.html") and git("show", "gh-pages:.nojekyll") == ""
    assert git("log", "-1", "--format=%s", "gh-pages").startswith("The page as of ")

    radar.store.set_state(_titled(radar, "Globex")["id"], dismissed=True)
    pages.snapshot(radar, out, dist=dist, words=[])
    pages.publish(out, str(remote), "gh-pages")
    assert git("rev-parse", "gh-pages").strip() != first and git("rev-list", "--count", "gh-pages").strip() == "1"
    titles = [r["title"] for r in json.loads(git("show", "gh-pages:data/feed.json"))["rows"]]
    assert len(titles) == 2 and not any("Globex" in t for t in titles), "the branch holds the new copy only"


def test_a_copy_is_due_after_a_start_then_only_when_something_changed(monkeypatch):
    radar = _radar()
    radar.incidents()
    pub = pages.Publisher(radar)
    monkeypatch.delenv("RADAR_PAGES", raising=False)
    assert pub.due(NOW) is False, "nowhere to push: no copy is made"
    monkeypatch.setenv("RADAR_PAGES", "origin")
    monkeypatch.setattr(config, "PAGES_EVERY_MIN", 60.0)
    assert pub.due(NOW) is True, "the first round after a start"
    pub.last_try = NOW
    assert pub.due(NOW + 60) is False and pub.due(NOW + pages.RETRY_S) is True, "a push that failed is tried again, not at once"
    pub.seen = radar.version()
    assert pub.due(NOW + 7200) is False, "nothing changed: nothing to push"
    radar.store.version += 1
    assert pub.due(NOW + 600) is False and pub.due(NOW + 3600) is True, "changed, and the hour is up"
    monkeypatch.setattr(config, "PAGES_EVERY_MIN", 0.0)
    assert pub.due(NOW + 7200) is False, "0: only the copy after a start"
    assert pub.status() == {"on": True, "last": None}
