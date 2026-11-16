"""Wikipedia "List of S&P 500 companies" adapter (decision record 0003).

Fetches the rendered page through the MediaWiki Action API (`action=parse`),
pinned to a revision by `oldid` when one is configured, once per download and
never on a schedule. The raw HTML is kept in the snapshot, and parsing reads
the snapshot, so rebuilds never touch the network.

Requests follow the Wikimedia policies recorded in decision record 0003: one
request at a time, a User-Agent naming the client, its repository and a
contact, gzip, `maxlag` for a request no one waits on, and on a rate limit or
lag the wait the server asks for, never an immediate retry.
"""

from __future__ import annotations

import gzip
import json
import os
import platform
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping
from io import StringIO
from typing import Any

import pandas as pd

from statarb.data.sources import ConstituentSnapshot

API = "https://en.wikipedia.org/w/api.php"
PAGE = "List_of_S&P_500_companies"
CLIENT = "statarb-from-scratch/0.1"
REPOSITORY = "https://github.com/tcrossland/stat-arb-from-scratch"
# Whoever runs a download may add their own contact (an email address or a URL); see README.md.
CONTACT_ENV = "STATARB_CONTACT"
MAXLAG = 5                 # seconds of replication lag beyond which the server asks us to wait
RETRIES = 3
DEFAULT_WAIT = 5.0         # seconds, when the server asks for a wait without saying how long

_COLUMNS = {
    "Symbol": "ticker",
    "Security": "security",
    "GICS Sector": "sector",
    "GICS Sub-Industry": "sub_industry",
    "Date added": "date_added",
    "CIK": "cik",
}

ApiFetcher = Callable[[dict[str, str]], dict]


class WikipediaApiError(RuntimeError):
    pass


def user_agent(environ: Mapping[str, str] = os.environ) -> str:
    """`client/version (repository; contact) library/version`, as the User-Agent policy asks."""
    contact = environ.get(CONTACT_ENV, "").strip()
    detail = f"{REPOSITORY}; {contact}" if contact else REPOSITORY
    return f"{CLIENT} ({detail}) Python-urllib/{'.'.join(platform.python_version_tuple()[:2])}"


def request_url(params: Mapping[str, str]) -> str:
    return API + "?" + urllib.parse.urlencode(sorted({**params, "maxlag": str(MAXLAG)}.items()))


def _decode(body: bytes, encoding: str | None) -> dict[str, Any]:
    return json.loads(gzip.decompress(body) if encoding == "gzip" else body)


def _wait(headers: Mapping[str, str] | None) -> float:
    value = (headers or {}).get("Retry-After")
    try:
        return max(float(value), 1.0) if value is not None else DEFAULT_WAIT
    except ValueError:
        return DEFAULT_WAIT


def call_api(
    params: dict[str, str],
    opener: Callable[..., Any] = urllib.request.urlopen,
    sleep: Callable[[float], None] = time.sleep,
    environ: Mapping[str, str] = os.environ,
) -> dict[str, Any]:
    """One GET to the Action API, retried serially after the wait the server asks for."""
    request = urllib.request.Request(
        request_url(params), headers={"User-Agent": user_agent(environ), "Accept-Encoding": "gzip"}
    )
    for attempt in range(RETRIES + 1):
        try:
            with opener(request, timeout=60) as response:
                payload = _decode(response.read(), response.headers.get("Content-Encoding"))
                headers = response.headers
        except urllib.error.HTTPError as exc:
            if exc.code not in (429, 503) or attempt == RETRIES:
                raise
            sleep(_wait(exc.headers) * (attempt + 1))
            continue
        code = (payload.get("error") or {}).get("code")
        if code in ("maxlag", "ratelimited") and attempt < RETRIES:
            sleep(_wait(headers) * (attempt + 1))
            continue
        return payload
    raise AssertionError("unreachable")


class WikipediaConstituents:
    name = "wikipedia"

    def __init__(self, api: ApiFetcher = call_api, page: str = PAGE) -> None:
        self._api = api
        self._page = page

    def fetch(self, revision_id: int | None) -> ConstituentSnapshot:
        params = {"action": "parse", "prop": "text|revid", "format": "json", "formatversion": "2"}
        if revision_id:
            params["oldid"] = str(revision_id)
        else:
            params["page"] = self._page
        payload = self._api(params)
        if "error" in payload:
            raise WikipediaApiError(f"Wikipedia API error: {payload['error']}")
        parsed = payload["parse"]
        return ConstituentSnapshot(raw=parsed["text"].encode("utf-8"), revision_id=int(parsed["revid"]))

    def parse(self, raw: bytes) -> pd.DataFrame:
        tables = pd.read_html(StringIO(raw.decode("utf-8")), flavor="lxml")
        for table in tables:
            if {"Symbol", "GICS Sector"} <= set(table.columns):
                break
        else:
            raise ValueError("constituents table not found")
        out = table.rename(columns=_COLUMNS).loc[:, list(_COLUMNS.values())].copy()
        out["ticker"] = out["ticker"].astype("str").str.strip()
        out["date_added"] = pd.to_datetime(out["date_added"], errors="coerce").astype("datetime64[ns]")
        out["cik"] = pd.to_numeric(out["cik"], errors="coerce").astype("Int64")
        if out["ticker"].duplicated().any():
            raise ValueError("duplicate tickers in constituents table")
        return out.sort_values("ticker", kind="mergesort").reset_index(drop=True)
