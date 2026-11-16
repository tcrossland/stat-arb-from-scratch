# 0003: Data sources: Alpaca for prices, Wikipedia for the candidate list

**Date:** 2026-11-16
**Status:** accepted

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

For the candidate list, the Wikipedia page "List of S&P 500 companies" has the current constituents in one table with symbol, GICS sector and sub-industry, date added and CIK. Its text is published under CC BY-SA 4.0 according to Wikipedia's terms of use (not yet read from its own pages; to be confirmed there before phase 0 keeps anything from the page). The list of symbols and sectors is factual; the page itself is kept as a raw snapshot and never committed.

## Decision

- **Alpaca is the only price source**, behind the `PriceSource` interface. Bars are requested unadjusted, and splits and dividends are stored as events. One price source per build.
- **History from 2016-01-01**, the start of Alpaca's free daily bars.
- **Raw snapshots are never modified.** Every download is kept exactly as Alpaca returned it, as a dated snapshot under `data/raw/alpaca/`. The build applies the project's rules and any listed corrections to the snapshot, so a changed rule or correction needs a rebuild, not a new download. Rebuilds read the cache, never the network. Alpaca revises old data, so a snapshot is also the only way to reproduce a result exactly.
- **Rules for Alpaca's data** (which bars and actions to use, and how) are found while building phase 0, and recorded in a decision record of their own as they are found. A correction to Alpaca's records is listed in config with its primary source: the issuer's announcement, filing or tax form, never another price source.
- **Keys** are read from the environment (`APCA_API_KEY_ID`, `APCA_API_SECRET_KEY`), never from the repository, a config file or a scheduler file. The adapter calls only the market data host, `data.alpaca.markets`, never the trading API, and a test checks the URLs it builds. Tests never call the API: they run the adapter on synthetic responses.
- **Wikipedia for the candidates** and their current GICS sectors, behind the `ConstituentSource` interface. The raw page is saved in `data/raw/`, and its retrieval date and revision ID are pinned in `config/universe.toml`.
- **GICS reclassifications** are maintained by hand in `config/sector_changes.toml`, each checked against an S&P or MSCI announcement.

## Consequences

- A reader needs a free Alpaca account to download; the tests need neither keys nor network.
- A reader's own snapshot, taken later, will differ slightly from the one behind the published results, because Alpaca revises old data. How closely results match is measured and stated before publication.
- No delisted names, so survivorship bias remains as decision record 0001 and the phase 0 brief describe.
- Wikipedia is editable by anyone. Pinning the revision ID makes the candidate list reproducible.
- A second price source for cross-checking would need terms that allow automated collection, so it cannot be Yahoo, and a decision record of its own.
