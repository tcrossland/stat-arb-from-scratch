"""Wikipedia adapter: the pinned revision, the parse, and the Wikimedia request policies (decision record 0003)."""

from __future__ import annotations

import gzip
import io
import json
import urllib.error
import urllib.parse
from email.message import Message

import pytest

from helpers import constituents_html, fake_wikipedia_api
from statarb.data import wikipedia
from statarb.data.wikipedia import WikipediaConstituents


def test_pins_revision_when_given() -> None:
    api = fake_wikipedia_api(constituents_html(), revid=999)
    source = WikipediaConstituents(api=api)
    assert source.fetch(999).revision_id == 999
    assert api.calls[-1]["oldid"] == "999" and "page" not in api.calls[-1]
    source.fetch(None)
    assert "oldid" not in api.calls[-1] and api.calls[-1]["page"] == "List_of_S&P_500_companies"


def test_parse_keeps_dotted_tickers() -> None:
    table = WikipediaConstituents(api=fake_wikipedia_api(constituents_html())).parse(constituents_html().encode())
    assert "BRK.B" in set(table["ticker"])
    assert len(table) == 5


def test_an_api_error_is_raised() -> None:
    source = WikipediaConstituents(api=lambda params: {"error": {"code": "nosuchrevid"}})
    with pytest.raises(wikipedia.WikipediaApiError, match="nosuchrevid"):
        source.fetch(1)


def test_user_agent_names_the_client_repository_and_an_optional_contact() -> None:
    plain = wikipedia.user_agent({})
    assert plain.startswith(f"{wikipedia.CLIENT} ({wikipedia.REPOSITORY}) Python-urllib/")
    assert "@" not in plain
    with_contact = wikipedia.user_agent({wikipedia.CONTACT_ENV: "someone@example.org"})
    assert f"({wikipedia.REPOSITORY}; someone@example.org)" in with_contact


class Response(io.BytesIO):
    def __init__(self, payload: dict, gzipped: bool = True, headers: dict[str, str] | None = None) -> None:
        body = json.dumps(payload).encode()
        super().__init__(gzip.compress(body) if gzipped else body)
        self.headers = Message()
        if gzipped:
            self.headers["Content-Encoding"] = "gzip"
        for key, value in (headers or {}).items():
            self.headers[key] = value

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_requests_ask_for_gzip_set_maxlag_and_go_to_the_api_only() -> None:
    seen = []

    def opener(request, timeout):
        seen.append(request)
        return Response({"parse": {"revid": 7, "text": "x"}})

    payload = wikipedia.call_api({"action": "parse", "oldid": "7"}, opener=opener, sleep=lambda s: None, environ={})
    assert payload["parse"]["revid"] == 7
    (request,) = seen
    assert request.full_url.startswith(wikipedia.API + "?")
    query = urllib.parse.parse_qs(urllib.parse.urlsplit(request.full_url).query)
    assert query["maxlag"] == [str(wikipedia.MAXLAG)] and query["oldid"] == ["7"]
    assert request.get_header("Accept-encoding") == "gzip"
    assert request.get_header("User-agent") == wikipedia.user_agent({})


def test_rate_limits_and_lag_wait_as_asked_then_retry_serially() -> None:
    sleeps: list[float] = []
    replies = iter(["429", "lag", "ok"])

    def opener(request, timeout):
        reply = next(replies)
        if reply == "429":
            headers = Message()
            headers["Retry-After"] = "7"
            raise urllib.error.HTTPError(request.full_url, 429, "Too Many Requests", headers, io.BytesIO(b""))
        if reply == "lag":
            return Response({"error": {"code": "maxlag"}}, headers={"Retry-After": "3"})
        return Response({"parse": {"revid": 1, "text": "x"}}, gzipped=False)

    payload = wikipedia.call_api({"action": "parse"}, opener=opener, sleep=sleeps.append, environ={})
    assert payload["parse"]["revid"] == 1
    assert sleeps == [7.0, 6.0]       # Retry-After times the attempt number


def test_other_http_errors_are_not_retried() -> None:
    def opener(request, timeout):
        raise urllib.error.HTTPError(request.full_url, 403, "Forbidden", Message(), io.BytesIO(b""))

    with pytest.raises(urllib.error.HTTPError):
        wikipedia.call_api({"action": "parse"}, opener=opener, sleep=lambda s: None, environ={})
