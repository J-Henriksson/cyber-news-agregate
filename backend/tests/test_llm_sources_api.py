"""The model's answers checked against the text, the sources read from
canned answers, and the API end to end on a store of the test's own."""

import asyncio
import json
import time

import httpx
from fastapi.testclient import TestClient

from radar import llm, sources
from radar.store import Store

NOW = time.time()


def test_a_name_or_an_amount_the_text_does_not_hold_is_dropped():
    item = {"title": "Acme Corp hit by ransomware", "text": "The gang demanded $4.5 million from Acme Corp, which refused."}
    answer = {
        "category": "ransomware", "summary": "Acme was hit.",
        "entities": [{"name": "Acme Corp", "type": "company", "role": "victim", "sector": "retail"},
                     {"name": "Globex", "type": "company", "role": "victim"}],
        "money": [{"amount": 4500000, "currency": "USD", "kind": "ransom_demand", "quote": "demanded $4.5 million"},
                  {"amount": 9000000, "currency": "USD", "kind": "loss", "quote": "demanded $4.5 million"},
                  {"amount": 1000000, "currency": "USD", "kind": "loss", "quote": "lost $1 million"}],
        "records": "many", "via": ["CVE-2026-1"],
    }
    out, dropped = llm.check(answer, item)
    assert [e["name"] for e in out["entities"]] == ["Acme Corp"]
    assert [(m["amount"], m["kind"]) for m in out["money"]] == [(4.5e6, "ransom_demand")]
    assert out["records"] is None and out["via"] == []
    assert dropped == 3


def test_no_key_no_call():
    assert llm.run(Store(":memory:")) == {"skipped": "no GEMINI_API_KEY"}


def test_the_model_reads_a_batch_and_the_answers_land_on_their_items(monkeypatch):
    store = Store(":memory:")
    store.upsert_items([{"id": "a", "source": "S", "kind": "news", "title": "Acme Corp breached", "text": "Acme Corp lost data.",
                         "published": NOW, "data": {}}], lambda it: {})
    monkeypatch.setenv("GEMINI_API_KEY", "test")
    seen = {}

    def fake_call(prompt, key, **kw):
        seen["prompt"] = prompt
        return json.dumps({"items": [{"k": "a", "title_start": "Acme Corp breached", "category": "breach", "summary": "Acme Corp lost data.",
                                      "entities": [{"name": "Acme Corp", "type": "company", "role": "victim"}], "money": []}]}), \
            {"prompt": 100, "output": 20}

    monkeypatch.setattr(llm, "call", fake_call)
    done = llm.run(store, max_calls=2)
    assert done["calls"] == 1 and done["items"] == 1
    assert "Acme Corp breached" in seen["prompt"]
    stored = store.items_since(0)[0]
    assert stored["llm_state"] == "done" and stored["llm"]["entities"][0]["role"] == "victim"
    assert store.llm_since(0)["prompt_tokens"] == 100


def run_source(fetch, routes):
    def handler(request: httpx.Request) -> httpx.Response:
        for prefix, body in routes.items():
            if str(request.url).startswith(prefix):
                return httpx.Response(200, content=body if isinstance(body, bytes) else json.dumps(body).encode())
        return httpx.Response(404)

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await fetch(client)

    return asyncio.run(go())


def test_a_feed_keeps_its_recent_entries_with_their_text():
    when = time.strftime("%a, %d %b %Y %H:%M:%S GMT", time.gmtime(NOW - 3600))
    old = time.strftime("%a, %d %b %Y %H:%M:%S GMT", time.gmtime(NOW - 400 * 86400))
    rss = f"""<?xml version="1.0"?><rss version="2.0"><channel><title>T</title>
      <item><title>New &amp; bad</title><link>https://x/1</link><description>&lt;p&gt;Body text&lt;/p&gt;</description><pubDate>{when}</pubDate></item>
      <item><title>Old</title><link>https://x/2</link><pubDate>{old}</pubDate></item></channel></rss>""".encode()
    out = run_source(sources._feed("T", "https://feed/"), {"https://feed/": rss})
    assert [(i["title"], i["text"], i["url"]) for i in out] == [("New & bad", "Body text", "https://x/1")]


def test_structured_sources_state_victims_amounts_and_claims():
    day = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(NOW - 3600))
    rl = run_source(sources.fetch_ransomlook, {"https://www.ransomlook.io/api/recent": [
        {"post_title": "Acme Corp", "group_name": "akira", "discovered": day, "description": "Files: 50 GB"}]})
    assert rl[0]["data"] == {"group": "akira", "victim": "Acme Corp", "post": ""} and rl[0]["llm"] is False
    llama = run_source(sources.fetch_defillama, {"https://api.llama.fi/hacks": [
        {"date": NOW - 3600, "name": "BridgeX", "amount": 2_000_000, "technique": "Private key leak"},
        {"date": NOW - 500 * 86400, "name": "Old", "amount": 1}]})
    assert [(i["data"]["victim"], i["data"]["amount_usd"]) for i in llama] == [("BridgeX", 2_000_000)]


def test_social_posts_below_the_engagement_bar_are_left_out():
    post = lambda uri, likes: {"uri": f"at://did/app.bsky.feed.post/{uri}", "likeCount": likes, "repostCount": 0,  # noqa: E731
                               "author": {"handle": "h.bsky.social"}, "record": {"text": f"post {uri}", "createdAt": "2026-11-20T10:00:00Z"}}
    out = run_source(sources.fetch_bluesky, {"https://api.bsky.app/": {"posts": [post("a", 50), post("b", 2)]}})
    assert [i["url"] for i in out] == ["https://bsky.app/profile/h.bsky.social/post/a"]


def test_the_api_serves_every_view(monkeypatch):
    import radar.app as appmod

    store = Store(":memory:")
    from radar.engine import Radar
    from radar.extract import rules_of

    store.upsert_items([
        {"id": "1", "source": "RansomLook", "kind": "ransomware", "title": "akira claims Acme Corp", "text": "",
         "published": NOW - 3600, "data": {"group": "Akira", "victim": "Acme Corp"}},
        {"id": "2", "source": "The Record", "kind": "news", "title": "Acme Corp confirms Akira attack",
         "text": "Akira demanded $2 million from Acme Corp in Sweden.", "published": NOW - 1800, "data": {}},
        {"id": "3", "source": "CISA KEV", "kind": "vuln", "title": "CVE-2026-9: Fortinet FortiOS: bypass", "text": "",
         "published": NOW - 7200, "data": {"cve": "CVE-2026-9", "vendor": "Fortinet", "product": "FortiOS"}},
    ], rules_of)
    store.put("kev_catalog", [{"cve": "CVE-2026-9", "vendor": "Fortinet", "product": "FortiOS", "name": "bypass",
                               "added": time.strftime("%Y-%m-%d"), "ransomware_use": "Unknown"}])
    store.put("wd:acme", {"qid": "Q1", "label": "Acme Corp", "parent": ["Globex Industries"], "subsidiaries": [],
                          "industry": ["retail"], "url": "https://www.wikidata.org/wiki/Q1"})
    monkeypatch.setattr(appmod, "radar", Radar(store))
    client = TestClient(appmod.app)
    feed = client.get("/api/feed").json()
    assert feed["total"] == 2
    top = feed["incidents"][0]
    assert top["title"] == "CVE-2026-9: Fortinet FortiOS: bypass" or "Acme" in top["title"]
    acme = next(i for i in feed["incidents"] if "Acme" in i["title"])
    assert acme["headline_usd"] == 2e6 and acme["attackers"] == ["Akira"]
    detail = client.get(f"/api/incident/{acme['id']}").json()
    assert len(detail["items"]) == 2 and detail["companies"]["Acme Corp"]["parent"] == ["Globex Industries"]
    # Two incidents with nothing in common: the links lens draws neither (the feed has them).
    graph = client.get("/api/graph?lens=links").json()
    assert graph["nodes"] == [] and graph["alone"] == 2
    # The groups lens: who hit whom.
    groups = client.get("/api/graph?lens=groups").json()
    assert {(n["label"], n["kind"]) for n in groups["nodes"]} == {("Akira", "actor"), ("Acme Corp", "company")}
    assert groups["links"] == [{"source": "e:akira", "target": "e:acme", "kind": "hit", "weight": 1}]
    node = client.get("/api/node?id=e:acme").json()
    assert node["label"] == "Acme Corp" and node["roles"] == {"victim": 1} and node["incidents"][0]["id"] == acme["id"]
    assert node["wikidata"]["parent"] == ["Globex Industries"]
    assert client.get("/api/node?id=e:nobody").status_code == 404
    companies = client.get("/api/companies").json()["companies"]
    acme_row = next(c for c in companies if c["name"] == "Acme Corp")
    assert acme_row["as_victim"] == 1 and acme_row["related"][0] == {"name": "Globex Industries", "how": "parent", "in_news": False}
    money = client.get("/api/money").json()
    assert money["by_kind"] == {"ransom_demand": 2e6}
    assert client.get("/api/timeline").json()["actors"][0]["name"] == "Akira"
    # "Today" is a moment the page sends: what was told before it is left out.
    today = client.get(f"/api/feed?since={NOW - 2700}").json()
    assert [i["title"] for i in today["incidents"]] == ["Acme Corp confirms Akira attack"]
    hours = client.get(f"/api/timeline?since={NOW - 7200}").json()
    assert hours["bucket"] == 3600 and sum(sum(v for k, v in b.items() if k != "t") for b in hours["buckets"]) == 2
    exploited = client.get("/api/brief").json()["exploited"]
    assert exploited[0]["cve"] == "CVE-2026-9" and exploited[0]["ours"] is True
    assert client.get("/api/sources").json()["model"]["key"] is False
    assert client.get("/api/incident/nope").status_code == 404


def test_an_answer_numbered_for_another_item_is_dropped_whole(monkeypatch):
    store = Store(":memory:")
    store.upsert_items([
        {"id": "a", "source": "HN", "kind": "community", "title": "FBI says Artex tool used in breaches", "text": "", "published": NOW, "data": {}},
        {"id": "b", "source": "HN", "kind": "community", "title": "Show HN: Onlook, a design tool", "text": "", "published": NOW - 1, "data": {}},
    ], lambda it: {})
    monkeypatch.setenv("GEMINI_API_KEY", "test")
    # The model answers item 0 with item 1's reading.
    monkeypatch.setattr(llm, "call", lambda prompt, key, **kw: (json.dumps({"items": [
        {"k": "a", "title_start": "Show HN: Onlook", "category": "tool", "summary": "A launch of Onlook."},
        {"k": "b", "title_start": "Show HN: Onlook", "category": "tool", "summary": "A launch of Onlook."}]}), {"prompt": 1, "output": 1}))
    done = llm.run(store, max_calls=1)
    by_id = {it["id"]: it for it in store.items_since(0)}
    assert by_id["a"]["llm_state"] == "failed" and by_id["a"]["llm"] is None
    assert by_id["b"]["llm"]["summary"] == "A launch of Onlook."
    assert done["misplaced"] == 1


def test_a_trailing_comma_is_forgiven_and_worse_raises():
    assert llm._parse('{"items": [{"k": "a", "summary": "x",},]}') == {"items": [{"k": "a", "summary": "x"}]}
    try:
        llm._parse('{"items": [{"k": "a" "summary"}]}')
    except ValueError:
        pass
    else:
        raise AssertionError("broken JSON must raise")


def test_new_means_a_new_item_not_a_regrouped_incident():
    from radar.engine import Radar
    from radar.extract import rules_of

    store = Store(":memory:")
    radar = Radar(store)
    store.upsert_items([{"id": "1", "source": "S", "kind": "news", "title": "Acme Corp breached", "text": "",
                         "published": NOW - 60, "data": {}}], rules_of)
    known, fresh = radar.news_since(None)
    assert known == {"1"} and fresh == []
    v = radar.version()
    store.upsert_items([{"id": "2", "source": "T", "kind": "news", "title": "Globex hit by ransomware", "text": "",
                         "published": NOW, "data": {}}], rules_of)
    assert radar.version() != v
    known, fresh = radar.news_since(known)
    assert [i["title"] for i in fresh] == ["Globex hit by ransomware"]
    _, fresh = radar.news_since(known)
    assert fresh == []


def test_trending_models_need_to_be_new_and_liked():
    made = time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(NOW - 3 * 86400))
    old = time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(NOW - 90 * 86400))
    out = run_source(sources.fetch_hf_models, {"https://huggingface.co/api/models": [
        {"id": "lab/new-model", "likes": 900, "downloads": 5000, "pipeline_tag": "text-generation", "createdAt": made,
         "tags": ["transformers", "region:us"]},
        {"id": "lab/old-model", "likes": 9000, "createdAt": old},
        {"id": "lab/unliked", "likes": 3, "createdAt": made}]})
    assert [i["data"]["pipeline"] for i in out] == ["text-generation"]
    assert out[0]["data"]["topic"] == "ai" and "region:us" not in out[0]["text"]


def test_incidents_keep_their_ids_as_reports_join_and_stars_follow_the_story():
    from radar.engine import Radar
    from radar.extract import rules_of

    store = Store(":memory:")
    radar = Radar(store)
    add = lambda *rows: store.upsert_items(list(rows), rules_of)  # noqa: E731
    add({"id": "1", "source": "RansomLook", "kind": "ransomware", "title": "akira claims Acme Corp", "text": "",
         "published": NOW - 7200, "data": {"group": "Akira", "victim": "Acme Corp"}})
    first = radar.feed()["incidents"][0]
    store.set_state(first["id"], starred=True)
    add({"id": "2", "source": "The Record", "kind": "news", "title": "Acme Corp confirms Akira attack", "text": "",
         "published": NOW - 600, "data": {}})
    again = radar.feed()["incidents"]
    assert len(again) == 1 and again[0]["id"] == first["id"] and again[0]["items"] == 2
    assert again[0]["state"]["starred"] is True
    # Opened, then told again: it shows as updated.
    store.set_state(first["id"], seen=NOW - 1800)
    assert radar.feed(show="updated")["total"] == 1 and radar.feed(show="starred")["total"] == 1
    # Dismissed: gone from every view, kept under its own filter.
    store.set_state(first["id"], dismissed=True)
    assert radar.feed()["total"] == 0 and radar.graph(lens="groups")["nodes"] == [] and radar.feed(show="dismissed")["total"] == 1


def test_the_brief_trending_related_and_export(monkeypatch):
    import radar.app as appmod
    from radar.engine import Radar
    from radar.extract import rules_of

    store = Store(":memory:")
    rows = [{"id": f"r{k}", "source": "RansomLook", "kind": "ransomware", "title": f"akira claims Victim{k} Works", "text": "",
             "published": NOW - 3600 * k, "data": {"group": "Akira", "victim": f"Victim{k} Works"}} for k in range(1, 4)]
    rows.append({"id": "n1", "source": "The Record", "kind": "news", "title": "Example Org confirms an Akira ransomware attack", "text": "",
                 "published": NOW - 900, "data": {}})
    store.upsert_items(rows, rules_of)
    monkeypatch.setattr(appmod, "radar", Radar(store))
    monkeypatch.setattr(appmod, "store", store)
    client = TestClient(appmod.app)
    brief = client.get("/api/brief").json()
    assert brief["top"][0]["title"] == "Example Org confirms an Akira ransomware attack" and brief["counts"]["incidents"] == 4
    assert [t["name"] for t in brief["trending"]] == ["Akira"] and brief["trending"][0]["today"] == 4
    ours = brief["top"][0]
    detail = client.get(f"/api/incident/{ours['id']}").json()
    assert len(detail["related"]) == 3 and detail["related"][0]["shares"] == ["akira"]
    assert client.post(f"/api/incident/{ours['id']}/state", json={"starred": True, "seen": True}).json()["starred"] is True
    assert client.get("/api/brief").json()["starred"][0]["id"] == ours["id"]
    csv_text = client.get("/api/export?format=csv").text.splitlines()
    assert csv_text[0].startswith("relevance,category,title") and len(csv_text) == 5
    assert len(client.get("/api/export?format=json").json()) == 4
    # Top: the same relevance, the newer first.
    top = client.get("/api/feed?sort=top").json()["incidents"]
    assert top[0]["id"] == ours["id"] and [i["title"][-7:] for i in top[1:]] == ["1 Works", "2 Works", "3 Works"]


def test_an_unchanged_feed_is_not_parsed_again():
    import pytest
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers.get("if-none-match"))
        if request.headers.get("if-none-match") == '"v1"':
            return httpx.Response(304)
        when = time.strftime("%a, %d %b %Y %H:%M:%S GMT", time.gmtime(NOW - 60))
        body = f'<rss version="2.0"><channel><item><title>One</title><link>https://x/1</link><pubDate>{when}</pubDate></item></channel></rss>'
        return httpx.Response(200, content=body.encode(), headers={"ETag": '"v1"'})

    fetch = sources._feed("E", "https://etag-feed/")

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            first = await fetch(client)
            with pytest.raises(sources.Unchanged):
                await fetch(client)
            return first

    assert len(asyncio.run(go())) == 1 and seen == [None, '"v1"']


def test_the_api_answers_this_machine_only():
    import radar.app as appmod
    client = TestClient(appmod.app)
    assert client.get("/api/health").json()["ok"] is True
    assert client.get("/api/health", headers={"Host": "evil.example"}).status_code == 400


def test_an_answer_is_matched_over_the_words_it_wrote_back():
    item = {"title": "AI claimed a solution to the 167-year-old Riemann Hypothesis"}
    assert llm.matches_item({"title_start": "AI claimed a"}, item)
    assert llm.matches_item({"title_start": "“AI claimed a solution”"}, item)
    assert not llm.matches_item({"title_start": "AI"}, item)
    assert not llm.matches_item({"title_start": "Mathematicians are having"}, item)
    assert llm.matches_item({"title_start": "@x: hi"}, {"title": "@x: hi"})


def test_what_is_not_a_company_name_is_not_shown_as_one():
    from radar.engine import placeholder
    assert all(placeholder(n) for n in ("T***Y", "Company #217", "finance", "healthcare", "US", "rai"))
    assert not any(placeholder(n) for n in ("eni.it", "Volvo", "BBC", "wakao.co.jp", "N-able", "23andMe"))


def lens_store():
    """A small world for the graph's lenses: a flaw in software we run told twice, two groups, shared victims."""
    from radar.engine import Radar
    from radar.extract import rules_of

    store = Store(":memory:")
    v = lambda *names: {"category": "breach", "summary": None, "money": [], "v": 2,  # noqa: E731
                        "entities": [{"name": n, "type": "company", "role": "victim"} for n in names]}
    store.upsert_items([
        {"id": "k1", "source": "CISA KEV", "kind": "vuln", "title": "CVE-2026-9001: Fortinet FortiOS: bypass", "text": "",
         "published": NOW - 7200, "data": {"cve": "CVE-2026-9001", "vendor": "Fortinet", "product": "FortiOS"}},
        {"id": "n1", "source": "The Record", "kind": "news", "title": "Hospital breached through FortiOS flaw CVE-2026-9001 and CVE-2026-9002",
         "text": "", "published": NOW - 3600, "data": {}},
        {"id": "r1", "source": "RansomLook", "kind": "ransomware", "title": "akira claims Acme Corp", "text": "",
         "published": NOW - 5000, "data": {"group": "Akira", "victim": "Acme Corp"}},
        {"id": "r2", "source": "RansomLook", "kind": "ransomware", "title": "akira claims Initech Works", "text": "",
         "published": NOW - 4000, "data": {"group": "Akira", "victim": "Initech Works"}},
        {"id": "r3", "source": "RansomLook", "kind": "ransomware", "title": "qilin claims Acme Corp", "text": "",
         "published": NOW - 90000, "data": {"group": "Qilin", "victim": "Acme Corp"}},
        {"id": "n2", "source": "BleepingComputer", "kind": "news", "title": "Vendor breach exposes Globex and Hooli customer data",
         "text": "", "published": NOW - 2000, "data": {}},
    ], rules_of)
    store.set_llm({"n2": v("Globex", "Hooli")})
    store.put("kev_catalog", [{"cve": "CVE-2026-9001", "vendor": "Fortinet", "product": "FortiOS", "name": "bypass",
                               "added": time.strftime("%Y-%m-%d"), "ransomware_use": "Unknown"}])
    return Radar(store)


def test_the_us_lens_hangs_each_incident_on_the_part_of_the_profile_it_touched():
    g = lens_store().graph(lens="us")
    by = {n["id"]: n for n in g["nodes"]}
    assert by["us"]["label"] == "Example Org" and g["nodes"][0]["id"] == "us"
    fortinet = by["f:stack:fortinet"]
    assert fortinet["kind"] == "facet" and fortinet["sub"] == "software we run" and fortinet["points"] >= 45
    assert {"source": "us", "target": "f:stack:fortinet", "kind": "ours", "weight": fortinet["points"]} in g["links"]
    hung = [link for link in g["links"] if link["source"] == "f:stack:fortinet" and link["kind"] == "why"]
    # The exploited-list entry and the news story about the same product: both hang on Fortinet.
    assert len(hung) == 2 and all(by[link["target"]]["kind"] == "incident" for link in hung)
    # What touches nothing of ours is not in this lens at all.
    assert not any("akira" in n["label"].lower() for n in g["nodes"])
    assert [f["id"] for f in g["facets"]] == ["stack"]


def test_the_links_lens_keeps_only_what_joins_two_incidents():
    g = lens_store().graph(lens="links")
    by = {n["label"]: n for n in g["nodes"]}
    # Akira joins two incidents (both gangs' claims on Acme are one), and the flaw joins its
    # exploited-list entry to the news story. Acme, Qilin, Initech, Globex each sit in one incident: left out.
    assert by["Akira"]["kind"] == "actor" and by["Akira"]["incidents"] == 2
    assert by["CVE-2026-9001"]["kind"] == "cve" and by["CVE-2026-9001"]["kev"] is True and by["CVE-2026-9001"]["incidents"] == 2
    assert not {"Acme Corp", "Qilin", "Initech Works", "Globex", "Hooli"} & set(by)
    assert sum(1 for n in g["nodes"] if n["kind"] == "incident") == 4 and g["alone"] == 1
    # Two separate parts, numbered so the page can set them side by side.
    assert {n["group"] for n in g["nodes"]} == {0, 1}


def test_the_companies_lens_ties_companies_hit_together_and_the_groups_lens_who_hit_whom():
    radar = lens_store()
    c = radar.graph(lens="companies")
    assert {"source": "e:globex", "target": "e:hooli", "kind": "together", "weight": 1} in c["links"]
    assert {n["label"] for n in c["nodes"]} >= {"Globex", "Hooli"} and all(n["kind"] == "company" for n in c["nodes"])
    g = radar.graph(lens="groups")
    hit = {(link["source"], link["target"]) for link in g["links"]}
    assert hit == {("e:akira", "e:acme"), ("e:akira", "e:initech works"), ("e:qilin", "e:acme")}
    acme = next(n for n in g["nodes"] if n["label"] == "Acme Corp")
    assert acme["incidents"] == 1 and acme["role"] == "victim"
    detail = radar.node("e:akira")
    assert detail["kind"] == "actor" and detail["total"] == 2 and detail["roles"] == {"attacker": 2}
    assert radar.node("f:stack:fortinet")["total"] == 2 and radar.node("c:CVE-2026-9001")["sub"].endswith("exploited (CISA KEV)")


def test_many_companies_hit_in_one_incident_hang_on_the_incident_not_on_every_pair():
    from radar.engine import Radar
    from radar.extract import rules_of

    store = Store(":memory:")
    hit = lambda *names, vendor=None: {  # noqa: E731
        "category": "breach", "summary": None, "money": [], "v": 2,
        "entities": [{"name": n, "type": "company", "role": "victim"} for n in names]
        + ([{"name": vendor, "type": "company", "role": "vendor"}] if vendor else [])}
    store.upsert_items([
        {"id": "m1", "source": "The Record", "kind": "news", "title": "Script hijack hits five sites", "text": "", "published": NOW - 3000, "data": {}},
        {"id": "m2", "source": "BleepingComputer", "kind": "news", "title": "Later count: four of them confirm the hijack", "text": "",
         "published": NOW - 2000, "data": {}},
        {"id": "m3", "source": "SecurityWeek", "kind": "news", "title": "Flaw in a file transfer product used against three firms", "text": "",
         "published": NOW - 1000, "data": {}},
    ], rules_of)
    store.set_llm({"m1": hit("Alphaco", "Betaco", "Gammaco", "Deltaco", "Epsilonco"),
                   "m2": hit("Alphaco", "Betaco", "Gammaco", "Deltaco"),
                   "m3": hit("Zetaco", "Etaco", "Thetaco", vendor="Movers Inc")})
    g = Radar(store).graph(lens="companies")
    by = {n["label"]: n for n in g["nodes"]}
    hubs = [n for n in g["nodes"] if n["kind"] == "incident"]
    # Five hit at once: one incident between them and five lines, not ten; the same event told again adds nothing.
    assert [h["label"] for h in hubs] == ["Script hijack hits five sites"]
    together = [link for link in g["links"] if link["kind"] == "together"]
    assert len(together) == 5 and {link["source"] for link in together} == {hubs[0]["id"]}
    # Hit through a product: its maker ties them, and they are not tied to each other besides.
    through = [link for link in g["links"] if link["kind"] == "through"]
    assert len(through) == 3 and {link["source"] for link in through} == {by["Movers Inc"]["id"]}
    assert by["Alphaco"]["group"] == by["Epsilonco"]["group"] != by["Zetaco"]["group"]


def test_a_name_is_known_whatever_its_dots_and_spaces():
    from radar.gazetteer import MATCHER

    assert MATCHER.canonical("J.P. Morgan Chase").name == "JPMorgan Chase"
    assert MATCHER.canonical("Lock Bit").name == "LockBit"
    assert MATCHER.canonical("Some Unknown Firm") is None
