"""The rules: amounts and their kinds, names, CVEs, countries, records."""

from radar.extract import records_in, rules_of
from radar.gazetteer import category_of, find_countries
from radar.money import find_amounts, parse_ecb, to_usd


def amounts(text):
    return [(m["amount"], m["currency"], m["kind"]) for m in find_amounts(text)]


def test_amounts_carry_their_currency_and_the_kind_the_words_around_them_say():
    assert amounts("LockBit demanded a $4.5 million ransom from the firm") == [(4.5e6, "USD", "ransom_demand")]
    assert amounts("The company paid a ransom of $1.1 million") == [(1.1e6, "USD", "ransom_paid")]
    assert amounts("attackers drained $30M from the bridge") == [(3e7, "USD", "theft")]
    assert amounts("fined €20 million by the regulator") == [(2e7, "EUR", "fine")]
    assert amounts("raised $50 million in Series B funding") == [(5e7, "USD", "business")]
    assert amounts("the attack cost the company 5 million kronor") == [(5e6, "SEK", "loss")]
    assert amounts("US$1.2 billion stolen") == [(1.2e9, "USD", "theft")]
    assert amounts("a reward of up to $10 million") == [(1e7, "USD", "reward")]


def test_a_bare_small_price_is_not_news():
    assert amounts("priced at $500 a month") == []
    assert amounts("version 4.5 million downloads") == []


def test_ecb_rates_convert_to_dollars():
    xml = """<gesmes:Envelope xmlns:gesmes="http://www.gesmes.org/xml/2002-08-01" xmlns="http://www.ecb.int/vocabulary/2002-08-01/eurofxref">
      <Cube><Cube time="2026-11-20"><Cube currency="USD" rate="1.10"/><Cube currency="SEK" rate="11.00"/></Cube></Cube>
    </gesmes:Envelope>"""
    fx = parse_ecb(xml)
    assert fx["day"] == "2026-11-20"
    assert to_usd(11e6, "SEK", fx["per_eur"]) == 1.1e6
    assert to_usd(1e6, "EUR", fx["per_eur"]) == 1.1e6
    assert to_usd(1e6, "XYZ", fx["per_eur"]) is None


def test_records_countries_and_categories():
    assert records_in("exposed 2.5 million customer records and 40,000 employees") == 2_500_000
    assert find_countries("Swedish municipalities and a Norwegian bank, says the US agency") == ["Sweden", "Norway", "United States"]
    assert "United States" not in find_countries("let us know")
    assert category_of("Akira ransomware gang hits a hospital") == "ransomware"
    assert category_of("Fortinet patches a critical flaw exploited as a zero-day") == "vulnerability"
    # "law" is a word, not the end of "flaw"; "apt" not the middle of "laptop".
    assert category_of("a flaw in the laptop firmware") == "vulnerability"
    assert category_of("Police arrested the GTA 6 leaker") == "actor"


def test_rules_find_known_groups_companies_cves_and_numbers():
    item = {"kind": "news", "title": "Scattered Spider hits Jaguar Land Rover via CVE-2025-31324",
            "text": "The attack on the UK carmaker exposed 1.2 million customers and cost £50 million.", "data": {}}
    r = rules_of(item)
    names = {e["name"]: e for e in r["entities"]}
    assert names["Scattered Spider"]["type"] == "actor" and names["Scattered Spider"]["role"] == "attacker"
    assert names["Jaguar Land Rover"]["sector"] == "automotive"
    assert r["cves"] == ["CVE-2025-31324"]
    assert r["records"] == 1_200_000
    assert r["money"][0]["currency"] == "GBP" and r["money"][0]["kind"] == "loss"
    assert "United Kingdom" in r["countries"]


def test_a_common_word_is_not_a_group_unless_its_alias_is_written():
    assert not [e for e in rules_of({"kind": "news", "title": "Play the game", "text": "", "data": {}})["entities"]]
    hit = rules_of({"kind": "news", "title": "Play ransomware claims a city", "text": "", "data": {}})["entities"]
    assert [e["name"] for e in hit] == ["Play"]


def test_a_structured_source_states_its_victim_and_amount():
    leak = rules_of({"kind": "ransomware", "title": "akira claims Acme Corp", "text": "", "data": {"group": "Akira", "victim": "Acme Corp"}})
    roles = {e["name"]: e["role"] for e in leak["entities"]}
    assert roles == {"Acme Corp": "victim", "Akira": "attacker"}
    assert leak["category"] == "ransomware"
    theft = rules_of({"kind": "crypto", "title": "X lost", "text": "", "data": {"victim": "BridgeX", "amount_usd": 2_000_000}})
    assert theft["money"][0] == {"amount": 2e6, "currency": "USD", "kind": "theft", "quote": theft["money"][0]["quote"],
                                 "stated_by_source": True}


def test_a_dollar_glued_to_letters_is_not_the_us_dollar():
    assert amounts("revenue of NT$135.1 billion last year") == [(135.1e9, "TWD", "business")]
    assert amounts("HK$2 million was stolen") == [(2e6, "HKD", "theft")]


def test_a_leak_site_post_has_no_damage_in_it_and_a_stated_amount_is_told_once():
    leak = rules_of({"kind": "ransomware", "title": "x claims Acme", "text": "Revenue $50 million.", "data": {"group": "x", "victim": "Acme"}})
    assert leak["money"] == []
    theft = rules_of({"kind": "crypto", "title": "BridgeX: $2,000,000 lost", "text": "", "data": {"victim": "BridgeX", "amount_usd": 2_000_000}})
    assert len(theft["money"]) == 1


def test_an_ai_source_story_is_ai_news_unless_it_is_security():
    from radar.gazetteer import is_ai
    news = rules_of({"kind": "news", "title": "OpenAI releases GPT-6 with longer context", "text": "", "data": {"topic": "ai"}})
    assert news["category"] == "ai" and news["ai"] is True
    flaw = rules_of({"kind": "news", "title": "Critical vulnerability in an LLM serving framework exploited", "text": "",
                     "data": {"topic": "ai"}})
    assert flaw["category"] == "vulnerability" and flaw["ai"] is True
    cyber = rules_of({"kind": "news", "title": "Hackers used an AI agent to breach a bank", "text": "", "data": {}})
    assert cyber["ai"] is True and cyber["category"] != "ai"
    assert is_ai("Prompt injection in Copilot") and is_ai("a new AI model")
    assert not is_ai("vi ska ai inte") and not is_ai("Ransomware hits a hospital")


def test_an_agency_has_one_name_however_it_is_written():
    r = rules_of({"kind": "news", "title": "The U.S. Cybersecurity and Infrastructure Security Agency warns of a flaw",
                  "text": "CISA and the Federal Bureau of Investigation said so.", "data": {}})
    assert sorted(e["name"] for e in r["entities"]) == ["CISA", "FBI"]
    assert all(e["type"] == "government" and e["role"] == "mentioned" for e in r["entities"])


def test_a_leading_the_is_not_part_of_a_name():
    from radar.text import norm_name
    assert norm_name("The Gentlemen") == norm_name("Gentlemen") == "gentlemen"
    assert norm_name("the BBC") == "bbc" and norm_name("Thea") == "thea" and norm_name("The X") == "the x"
