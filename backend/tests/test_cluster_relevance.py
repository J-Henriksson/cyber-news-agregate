"""Items into incidents, incidents scored against the profile."""

import time

from radar.cluster import cluster, merged
from radar.extract import rules_of
from radar.profile import DEFAULT
from radar.relevance import Scorer

NOW = time.time()
DAY = 86400.0


def item(i, kind, title, text="", data=None, age_days=0.0, source=None, llm=None):
    it = {"id": f"it{i}", "source": source or kind, "kind": kind, "url": f"https://x/{i}", "title": title, "text": text,
          "published": NOW - age_days * DAY, "data": data or {}}
    it["rules"] = rules_of(it)
    it["llm"] = llm
    return it


def by_title(incidents):
    return {inc["title"]: inc for inc in incidents}


def test_the_press_and_the_leak_site_on_one_victim_are_one_incident():
    items = [
        item(1, "ransomware", "Akira claims Nordic Widgets AB", data={"group": "Akira", "victim": "Nordic Widgets AB"}, age_days=2),
        item(2, "news", "Nordic Widgets confirms cyberattack", source="The Record",
             llm={"category": "ransomware", "entities": [{"name": "Nordic Widgets", "type": "company", "role": "victim"}],
                  "money": [], "summary": "Nordic Widgets was hit."}),
        item(3, "news", "Unrelated: new phishing kit sold on Telegram", source="BleepingComputer"),
    ]
    incs = cluster(items)
    assert len(incs) == 2
    inc = by_title(incs)["Nordic Widgets confirms cyberattack"]
    assert inc["category"] == "ransomware"
    assert inc["sources"] == ["The Record", "ransomware"]
    assert inc["attackers"] == ["Akira"]


def test_a_shared_cve_joins_but_a_roundup_of_many_does_not():
    cves = " ".join(f"CVE-2026-{1000 + k}" for k in range(8))
    items = [
        item(1, "vuln", "CVE-2026-5555: Fortinet FortiOS: auth bypass", data={"cve": "CVE-2026-5555", "vendor": "Fortinet"}),
        item(2, "news", "Hackers exploit FortiOS flaw CVE-2026-5555 in the wild", source="SecurityWeek"),
        item(3, "news", f"Patch Tuesday fixes 8 flaws: {cves} and CVE-2026-5555", source="Help Net Security"),
    ]
    incs = cluster(items)
    assert len(incs) == 2
    joined = by_title(incs)["Hackers exploit FortiOS flaw CVE-2026-5555 in the wild"]
    assert set(joined["kinds"]) == {"vuln", "news"}
    assert joined["category"] == "vulnerability"


def test_alike_headlines_join_only_within_days_and_never_for_social_posts():
    items = [
        item(1, "news", "Asahi brewery production halted by ransomware attack", source="A", age_days=1),
        item(2, "news", "Ransomware attack halts Asahi brewery production lines", source="B", age_days=0.5),
        item(3, "news", "Asahi brewery production halted by ransomware attack", source="C", age_days=9),
        item(4, "social", "ransomware is everywhere today wow", age_days=0.2),
        item(5, "social", "wow ransomware everywhere today", age_days=0.1),
    ]
    incs = cluster(items)
    sizes = sorted(len(i["items"]) for i in incs)
    assert sizes == [1, 1, 1, 2]


def test_the_model_cannot_overrule_what_a_structured_source_says():
    it = item(1, "crypto", "BridgeX: $2,000,000 lost", data={"victim": "BridgeX", "amount_usd": 2_000_000},
              llm={"category": "other", "entities": [], "money": [], "summary": None})
    facts = merged(it)
    assert facts["category"] == "crypto"
    assert facts["money"][0]["amount"] == 2e6


def test_money_is_in_dollars_and_the_headline_is_the_largest_damage():
    items = [item(1, "news", "Retailer hit", "Hackers stole $3 million and the company was fined €10 million. It raised $90 million last year.")]
    inc = cluster(items, per_eur={"EUR": 1.0, "USD": 1.1})[0]
    assert inc["headline_kind"] == "fine" and round(inc["headline_usd"]) == 11_000_000
    assert {m["kind"] for m in inc["money"]} == {"theft", "fine", "business"}


def score(items, profile=DEFAULT, **kw):
    inc = cluster(items, **kw)[0]
    return Scorer(profile).score(inc)


def test_naming_us_ranks_high_and_says_why():
    points, reasons = score([item(1, "news", "Example Org investigates a breach at a subcontractor", source="The Record")])
    assert points >= 60
    assert reasons[0]["why"].startswith("names us")


def test_an_exploited_flaw_in_software_we_run_ranks_above_one_we_do_not_run():
    ours = [item(1, "vuln", "CVE-2026-1: Fortinet FortiOS: bypass", data={"cve": "CVE-2026-1", "vendor": "Fortinet", "product": "FortiOS"})]
    theirs = [item(2, "vuln", "CVE-2026-2: Acme Widget: bypass", data={"cve": "CVE-2026-2", "vendor": "Acme", "product": "Widget"})]
    kev = {"CVE-2026-1": {"ransomware_use": "Known", "vendor": "Fortinet"}, "CVE-2026-2": {"vendor": "Acme"}}
    a, why_a = score(ours, kev=kev)
    b, _ = score(theirs, kev=kev)
    assert a > b
    assert any("software we run" in r["why"] for r in why_a) and any("exploited" in r["why"] for r in why_a)


def test_what_the_team_works_on_counts_and_names_the_project():
    points, reasons = score([item(1, "tool", "someone/agentic-pentest: an autonomous pentest agent built on an LLM")])
    assert any("ARTEX" in r["why"] for r in reasons)
    assert points >= 20


def test_a_claim_alone_counts_less_than_the_same_story_confirmed():
    claim, reasons = score([item(1, "ransomware", "Akira claims Example Org", data={"group": "Akira", "victim": "Example Org"})])
    confirmed, _ = score([item(1, "ransomware", "Akira claims Example Org", data={"group": "Akira", "victim": "Example Org"}),
                          item(2, "news", "Example Org confirms Akira attack", source="The Record")])
    assert claim < confirmed
    assert any("only claims" in r["why"] for r in reasons)


def test_one_vendors_advisories_of_a_day_are_one_batch():
    noon = (NOW - (NOW // DAY * DAY - DAY / 2)) / DAY
    items = [item(k, "advisory", f"Siemens SIMATIC part {k}", source="CISA advisories", age_days=noon + 0.02 * k) for k in range(1, 4)]
    items.append(item(9, "advisory", "Schneider Electric EcoStruxure", source="CISA advisories", age_days=noon))
    incs = by_title(cluster(items))
    assert "Siemens: 3 advisories from CISA advisories" in incs
    assert len(incs) == 2


def test_one_story_worded_apart_joins_on_its_uncommon_words():
    items = [item(1, "news", "China-linked hackers exploit critical VMware vCenter zero-day to gain admin access", source="A"),
             item(2, "news", "VMware patches vCenter zero-day exploited in attacks since September", source="B"),
             item(3, "news", "Microsoft patches Exchange zero-day exploited in attacks", source="C")]
    sizes = sorted(len(i["items"]) for i in cluster(items))
    assert sizes == [1, 2]


def test_a_tool_we_build_on_counts_when_named_but_not_inside_another_word():
    named, reasons = score([item(1, "news", "FBI says Artex AI open-source hacking tool used to breach networks", source="HN")])
    assert any(r["why"] == "names a tool we build on (ARTEX)" for r in reasons)
    _, reasons = score([item(2, "news", "Strapi stores passwords in cleartext", source="X")])
    assert not any("ARTEX" in r["why"] for r in reasons)


def test_a_vendor_we_use_in_a_story_that_is_not_about_security_scores_nothing_for_it():
    _, reasons = score([item(1, "news", "Microsoft now installs Windows 11 26H2 on unmanaged devices", source="BleepingComputer",
                             llm={"category": "policy", "entities": [{"name": "Microsoft", "type": "company", "role": "vendor"}],
                                  "money": [], "summary": None})])
    assert not any("software we run" in r["why"] for r in reasons)


def test_incidents_carry_their_desks_and_the_views_filter_by_desk():
    from radar.engine import Radar
    from radar.store import Store

    items = [item(1, "news", "Anthropic launches a new Claude model", data={"topic": "ai"}, source="The Decoder"),
             item(2, "news", "Hackers abuse an LLM agent to steal cloud keys", source="BleepingComputer"),
             item(3, "news", "Akira ransomware hits a Swedish municipality", source="The Record")]
    topics = {inc["title"]: inc["topics"] for inc in cluster(items)}
    assert topics == {"Anthropic launches a new Claude model": ["ai"],
                      "Hackers abuse an LLM agent to steal cloud keys": ["ai", "cyber"],
                      "Akira ransomware hits a Swedish municipality": ["cyber"]}
    store = Store(":memory:")
    store.upsert_items([{k: v for k, v in it.items() if k not in ("rules", "llm")} for it in items], rules_of)
    radar = Radar(store)
    titles = lambda desk: sorted(i["title"] for i in radar.feed(desk=desk)["incidents"])  # noqa: E731
    assert titles("ai") == ["Anthropic launches a new Claude model", "Hackers abuse an LLM agent to steal cloud keys"]
    assert titles("cyber") == ["Akira ransomware hits a Swedish municipality", "Hackers abuse an LLM agent to steal cloud keys"]
    assert len(titles(None)) == 3


def vendor(name):
    return {"category": "vulnerability", "entities": [{"name": name, "type": "company", "role": "vendor"}], "money": [],
            "summary": None, "v": 2}


def test_a_sources_own_series_headline_does_not_chain_its_issues():
    items = [item(k, "advisory", "CISA Adds One Known Exploited Vulnerability to Catalog", source="CISA advisories",
                  age_days=k) for k in range(1, 4)]
    items += [item(9, "advisory", "CISA Adds Two Known Exploited Vulnerabilities to Catalog", source="CISA advisories", age_days=1.1)]
    assert len(cluster(items)) == 4


def test_common_words_in_common_are_not_one_story_but_a_shared_name_is():
    apart = [item(1, "news", "North Smithfield man accused of creating AI-generated child sexual abuse material", source="A"),
             item(2, "news", "Reports of AI-related child sexual abuse material rise sharply, data shows", source="B")]
    assert len(cluster(apart)) == 2
    together = [item(1, "news", "Optimizely scripts hijacked to serve a card skimmer to CNN readers", source="A"),
                item(2, "news", "Card skimmer served through Optimizely reached BBC and CNN, researchers say", source="B")]
    assert len(cluster(together)) == 1


def test_a_flaw_of_a_seldom_named_maker_is_one_story_however_worded():
    items = [item(1, "news", "Drupal Patches Critical Installer Flaw That Could Give Unauthenticated Attackers Control", source="A",
                  llm=vendor("Drupal")),
             item(2, "news", "Drupal patches critical RCE flaw, warns exploits may surface quickly", source="B", llm=vendor("Drupal"))]
    assert len(cluster(items)) == 1
    # A maker in the news every day is not a reason to join.
    products = ["Outlook preview pane", "Hyper-V guest escape", "SharePoint deserialization", "Teams link handling",
                "Windows kernel driver", "Edge sandbox", "Azure identity tokens", "Defender scanning engine", "Excel macro loading"]
    many = [item(k, "news", f"Microsoft fixes {what}", source=f"S{k}", llm=vendor("Microsoft")) for k, what in enumerate(products, 1)]
    assert len(cluster(many)) == 9


def test_a_digest_of_many_stories_glues_none_of_them():
    victim = lambda name: {"category": "breach", "entities": [{"name": name, "type": "company", "role": "victim"}],  # noqa: E731
                           "money": [], "summary": None, "v": 2}
    both = {"category": "breach", "entities": [{"name": "Acme Corp", "type": "company", "role": "victim"},
                                               {"name": "Globex Ltd", "type": "company", "role": "victim"}],
            "money": [], "summary": None, "v": 2}
    items = [item(1, "news", "Acme Corp confirms a breach of its billing system", source="A", llm=victim("Acme Corp")),
             item(2, "news", "Globex Ltd says attackers stole its design files", source="B", llm=victim("Globex Ltd")),
             item(3, "news", "Weekly Recap: Acme Corp breach, Globex Ltd theft and more", source="C", llm=both)]
    incs = cluster(items)
    assert len(incs) == 3
    assert next(i for i in incs if i["title"].startswith("Weekly Recap"))["roundup"] is True


def test_an_authoritys_advisory_and_a_product_in_the_headline_count():
    items = [item(1, "advisory", "Allvarlig sårbarhet i Oracle Java", source="CERT-SE",
                  data={}, text="CVE-2026-114938"),
             item(2, "news", "Java4Shell Flaw (CVE-2026-114938) Enables Pre-Auth RCE in Jira, Jenkins and Keycloak", source="The Hacker News")]
    points, reasons = score(items)
    why = [r["why"] for r in reasons]
    assert "CERT-SE advises on it" in why
    assert any(w.startswith("software we run: Atlassian") for w in why)
    assert points >= 45


def test_a_roundup_counts_for_less_and_phrases_are_whole_words():
    from radar.relevance import Phrases
    one, _ = score([item(1, "news", "Example Org confirms a breach", source="A")])
    recap, reasons = score([item(1, "news", "Weekly Recap: Example Org breach and nine other stories", source="A")])
    assert recap < one and any("roundup" in r["why"] for r in reasons)
    p = Phrases(["ARTEX", "prompt injection"])
    assert p.find("the Artex tool", "the artex tool") == "Artex"
    assert p.find("stored in cleartext", "stored in cleartext") is None
    assert p.find("a Prompt Injection.", "a prompt injection.") == "Prompt Injection"


def test_a_vendors_batch_of_advisories_is_not_pulled_into_one_flaws_story():
    # Yesterday noon (UTC), so the batch's day does not split when the test runs near midnight.
    noon = (NOW - (NOW // DAY * DAY - DAY / 2)) / DAY
    items = [item(k, "advisory", f"Siemens Product{k}", text="CVE-2026-111497" if k == 1 else f"CVE-2026-9000{k}",
                  source="CISA advisories", age_days=noon + 0.01 * k) for k in range(1, 5)]
    items += [item(8, "vuln", "CVE-2026-111497: Google Brotli: unchecked return value", data={"cve": "CVE-2026-111497", "vendor": "Google"},
                   age_days=noon),
              item(9, "news", "Broccoli2shell: the critical Brotli decoder flaw CVE-2026-111497", source="Wiz Research", age_days=noon)]
    incs = by_title(cluster(items))
    assert "Siemens: 4 advisories from CISA advisories" in incs
    brotli = incs["Broccoli2shell: the critical Brotli decoder flaw CVE-2026-111497"]
    assert set(brotli["kinds"]) == {"news", "vuln"} and len(incs) == 2


def test_a_topic_word_only_in_the_body_is_a_mention_in_passing():
    points = lambda reasons: next(r["points"] for r in reasons if r["facet"] == "interest")  # noqa: E731
    _, headline = score([item(1, "news", "A new agentic framework for red teams", source="HN")])
    _, body = score([item(2, "news", "Chip maker sweeps the training records", "The firm also spoke of agentic systems.", source="HN")])
    _, twice = score([item(3, "news", "Lab notes from the week", "An agentic harness found a prompt injection.", source="HN")])
    assert points(headline) == 20 and points(twice) == 20
    assert points(body) == 7 and any(r["why"].endswith(", in passing") for r in body)
