# 0003: Data sources: Alpaca for prices, Wikipedia for the candidate list

**Date:** 2026-11-16
**Status:** accepted, with an amendment of 2026-11-26 on the rebuild tolerance

## Context

Phase 0 needs daily open, high, low, close and volume from 2016 for about 500 US stocks and 12 ETFs, split and dividend events stored separately from prices (decision record 0002), and the current S&P 500 list with GICS sectors. Decision record 0001 limits the project to free data. A reader must be able to download the same data, so a source is acceptable only if its terms allow a program to collect it.

Three price sources were considered.

**Alpaca's market data API**, on the free (Basic) plan of a paper-only account:

- Consolidated (SIP) daily bars from 2016, through an API meant for programs. Bars are unadjusted on request, the prices actually traded on each day.
- Corporate actions (splits, cash dividends, spin-offs, name changes) through `/v1/corporate-actions`, as their own records rather than as price factors.
- The free plan allows 200 requests a minute. The keys come from a free account; the account is paper-only, and only the market data host is called.
- Its terms allow personal, non-commercial use and forbid copying or republishing the data for publication or distribution without consent. Statistics and charts derived from the data are published here; its prices, volumes and other values never are.

**Yahoo Finance, through the `yfinance` library:** rejected.

- Yahoo's terms (section 2, "Member conduct", item 9) forbid collecting its data by automated means without prior permission, which is what a download for every reader would do.
- Its prices without adjustment (`auto_adjust=False`) are not unadjusted: they are adjusted for splits, though not for dividends, so the whole history changes after each later split.
- `yfinance` is unofficial and not affiliated with Yahoo.

**Stooq:** rejected. Its CSV endpoint now answers with a JavaScript proof-of-work browser check instead of data, and an API key is reported to need a CAPTCHA. Automated use would mean defeating bot detection, which this project will not do.

For the candidate list, the Wikipedia page "List of S&P 500 companies" has the current constituents in one table with symbol, GICS sector and sub-industry, date added and CIK. The Wikimedia Foundation's terms of use (read on its own page, revision 598588, on 2026-11-16) set the conditions:

- Section 7: contributed text is licensed under both CC BY-SA 4.0 and the GFDL, and a reuser may comply with either, except for text imported under CC BY-SA alone. Reusing the text needs attribution and a licence notice, and modified versions carry the same licence.
- Section 7 also waives contributors' database rights covered by CC BY-SA 4.0, so the facts on the page (symbols, sectors, dates added, CIKs) may be reused freely without attribution.
- Section 4 forbids automated use that is abusive or disruptive, breaks the applicable usage policies or has not been approved by the Wikimedia community, and anything that puts an undue burden on an API.
- Section 12 binds API users to the User-Agent policy, the Robot policy and the API etiquette page, which are not yet read.

## Decision

- **Alpaca is the only price source**, behind the `PriceSource` interface. Bars are requested unadjusted, and splits and dividends are stored as events. One price source per build.
- **History from 2016-01-01**, the start of Alpaca's free daily bars.
- **Raw snapshots are never modified.** Every download is kept exactly as Alpaca returned it, as a dated snapshot under `data/raw/alpaca/`. The build applies the project's rules and any listed corrections to the snapshot, so a changed rule or correction needs a rebuild, not a new download. Rebuilds read the cache, never the network. Alpaca revises old data, so a snapshot is also the only way to reproduce a result exactly.
- **Rules for Alpaca's data** (which bars and actions to use, and how) are found while building phase 0, and recorded in a decision record of their own as they are found. A correction to Alpaca's records is listed in config with its primary source: the issuer's announcement, filing or tax form, never another price source.
- **Keys** are read from the environment (`APCA_API_KEY_ID`, `APCA_API_SECRET_KEY`), never from the repository, a config file or a scheduler file. The adapter calls only the market data host, `data.alpaca.markets`, never the trading API, and a test checks the URLs it builds. Tests never call the API: they run the adapter on synthetic responses.
- **Wikipedia for the candidates** and their current GICS sectors, behind the `ConstituentSource` interface. The raw page is saved in `data/raw/`, and its retrieval date and revision ID are pinned in `config/universe.toml`. Only the facts are kept: the page's text is never committed or redistributed, so no CC BY-SA text enters the repository. The adapter fetches the pinned revision once per download through the MediaWiki API, never on a schedule, and follows the policies section 12 of the terms names.
- **GICS reclassifications** are maintained by hand in `config/sector_changes.toml`, each checked against an S&P or MSCI announcement.

## Consequences

- A reader needs a free Alpaca account to download; the tests need neither keys nor network.
- A reader's own snapshot, taken later, will differ slightly from the one behind the published results, because Alpaca revises old data. How closely results match is measured and stated before publication. Amended on 2026-11-26: see the amendment below.
- No delisted names, so survivorship bias remains as decision record 0001 and the phase 0 brief describe.
- Wikipedia is editable by anyone. Pinning the revision ID makes the candidate list reproducible.
- Before the Wikipedia adapter's first download, phase 0 reads the User-Agent policy, the Robot policy and the API etiquette page from their own pages, and records anything that changes the adapter here. Done on 2026-11-16: see the amendment below.
- A second price source for cross-checking would need terms that allow automated collection, so it cannot be Yahoo, and a decision record of its own.

## Amendment, 2026-11-16: the Wikimedia request policies

Read from their own pages on 2026-11-16, before the adapter's first download:

- the Wikimedia Foundation User-Agent Policy, https://foundation.wikimedia.org/wiki/Policy:Wikimedia_Foundation_User-Agent_Policy, revision 564705;
- the Robot policy, https://wikitech.wikimedia.org/wiki/Robot_policy, revision 2391151;
- API:Etiquette, https://www.mediawiki.org/wiki/API:Etiquette, revision 8373208;
- https://en.wikipedia.org/robots.txt, as served that day.

What they ask of a client, and what `statarb.data.wikipedia` does:

- **User-Agent.** A script must send an informative User-Agent of the form `client/version (contact) library/version`, and may be blocked without one. The adapter sends `statarb-from-scratch/0.1 (https://github.com/tcrossland/stat-arb-from-scratch) Python-urllib/<version>`. A reader who downloads can add an email or other contact by setting `STATARB_CONTACT`, which goes after the repository URL. No personal detail is in the code.
- **Rate and concurrency.** Unauthenticated clients make one request at a time and stay well below five a second. The adapter makes one request per download, never on a schedule, and retries serially.
- **Compression.** Requests ask for gzip (`Accept-Encoding: gzip`), and the adapter decodes it.
- **Lag and limits.** Requests carry `maxlag=5`. On HTTP 429 or 503, or an API error `maxlag` or `ratelimited`, the adapter waits as `Retry-After` says (longer on each attempt), up to three retries, and then fails. Other errors are not retried.
- **Authentication.** Not required for reads; none is used.

**The pinned revision.** The Robot policy prefers cached interfaces to the Action API for page HTML and discourages fetching old revisions by id, and robots.txt disallows `/w/` (which includes `/w/api.php`) to generic crawlers, with an exception only for `action=mobileview`. API:Etiquette, on the other hand, names `oldid` as the way to fetch a specific revision. The adapter keeps one `action=parse&oldid=` request per download, because:

- the pinned revision is what makes the candidate list reproducible, and only the revision id gives it;
- the adapter is not a crawler: it reads one page when a person runs a download by hand, follows no links and makes no other request;
- it meets every rule above for API clients.

If Wikimedia asks for a different route, or a cached interface comes to serve a pinned revision, the adapter changes and this record is amended.

## Amendment, 2026-11-26: the rebuild tolerance after publication

The repository has been public since it was created on 2026-11-16, so the tolerance the consequences ask for could not be measured before publication: it needs a snapshot taken weeks after the pinned one, and the cache then held snapshots a day apart.

- **Until it is measured,** the README and [reproducing the results](../reproduce.md#checking-your-results) say that a rebuild from a reader's own snapshot matches closely, not exactly, and that how closely is not yet measured.
- **It is measured** from a daily-job snapshot at least four weeks past the pinned one, from about 2026-12-14, as the backlog's "Tolerance for a rebuild from another snapshot" sets out, and the result is stated in the reproduction guide in place of that note.
