"""The company lookups on Wikidata: what the reader says it is, and that a
refusal stops it instead of being asked again every round."""

import time

import httpx

from radar import companies
from radar.store import Store


def _refusal(code: int = 403, headers: dict | None = None) -> httpx.HTTPStatusError:
    request = httpx.Request("GET", companies.API)
    return httpx.HTTPStatusError("refused", request=request, response=httpx.Response(code, headers=headers, request=request))


def test_the_reader_names_itself_and_never_a_browser(monkeypatch):
    monkeypatch.delenv("RADAR_CONTACT", raising=False)
    plain = companies.user_agent()
    assert plain.startswith("cyber-news-agregate/") and "python-httpx/" in plain and "Mozilla" not in plain and "(" not in plain
    monkeypatch.setenv("RADAR_CONTACT", "https://example.org/radar")
    assert companies.user_agent().startswith("cyber-news-agregate/0.1 (https://example.org/radar) python-httpx/")


def test_a_refusal_stops_the_round_and_nothing_is_asked_until_the_wait_is_over(monkeypatch):
    store, asked = Store(":memory:"), []
    monkeypatch.setattr(companies.time, "sleep", lambda _s: None)

    def refuse(_client, name):
        asked.append(name)
        raise _refusal()

    monkeypatch.setattr(companies, "lookup", refuse)
    names = ["Acme Corp", "Globex Industries", "Initech"]
    assert companies.enrich(store, names) == 0
    assert asked == ["Acme Corp"], "the first refusal ends the round: the other names are not tried"
    assert companies.enrich(store, names) == 0 and companies.enrich(store, names) == 0
    assert asked == ["Acme Corp"], "and the next rounds ask nothing"
    st = companies.status(store)
    assert st["error"] == "HTTP 403" and 3000 < st["until"] - time.time() <= companies.REFUSED_S and st["asked"] == 0

    # The wait over, it asks again; answered, the names are kept and the refusal forgotten.
    store.put(companies.WAIT_KEY, {"until": time.time() - 1, "error": "HTTP 403"})
    monkeypatch.setattr(companies, "lookup", lambda _c, name: {"qid": "Q1", "label": name} if name != "Initech" else None)
    assert companies.enrich(store, names) == 3
    assert store.get("wd:acme")["label"] == "Acme Corp" and store.get("wd:initech") == {"unknown": True}
    assert companies.status(store) | {"contact": False} == {"known": 2, "asked": 3, "error": None, "until": None, "contact": False}
    assert companies.enrich(store, names) == 0, "known names are not asked again"


def test_the_wait_follows_what_went_wrong(monkeypatch):
    assert companies._refused(_refusal(429, {"retry-after": "7200"})) == ("HTTP 429", 7200.0)
    assert companies._refused(_refusal(429, {"retry-after": "5"})) == ("HTTP 429", companies.REFUSED_S)
    assert companies._refused(_refusal(403, {"retry-after": "Wed, 21 Oct 2026 07:28:00 GMT"})) == ("HTTP 403", companies.REFUSED_S)
    why, wait = companies._refused(httpx.ConnectError("no route to host"))
    assert why == "no route to host" and wait == companies.FAILED_S
    assert companies._refused(ValueError("Expecting value"))[1] == companies.FAILED_S


def test_a_refusal_is_raised_as_one_not_parsed_as_an_answer():
    def answer(request: httpx.Request) -> httpx.Response:
        assert "Mozilla" not in request.headers["user-agent"] and request.url.params["format"] == "json"
        return httpx.Response(403, text="Please respect our robot policy")

    with httpx.Client(transport=httpx.MockTransport(answer), headers={"User-Agent": companies.user_agent()}) as client:
        try:
            companies.lookup(client, "Acme Corp")
        except httpx.HTTPStatusError as err:
            assert err.response.status_code == 403
        else:
            raise AssertionError("a 403 was taken for an answer")
