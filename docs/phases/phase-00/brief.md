# Phase 0: Data and universe

Drafted at setup, and revised on 2026-11-16 at the start of the phase with what setup settled.

## Goal

A clean, reproducible daily dataset for a point-in-time universe of liquid US large caps, plus the sector and market ETFs needed for the factor model in phase 1.

## Revised at the start of the phase

Setup fixed the stack, the storage formats, the data sources (decision record 0003) and the rule that no data values are published. This revision makes the brief concrete where those choices reach phase 0:

- **A pinned snapshot, by date and content.** `config/data.toml` and `config/universe.toml` name the snapshot each build reads by its download date and its digest, a hash over every file in it. The build refuses a pinned snapshot whose files no longer match, because a date alone does not identify a snapshot: two downloads on one day can differ, and Alpaca revises old data. A later download never changes a build by arriving.
- **Kept and disposable data, no data under version control.** `data/raw/` holds the raw snapshots, the only data that cannot be replaced: kept, read-only once complete, backed up privately and never committed. `data/derived/` holds everything rebuilt from them and can be deleted at any time. One raw store serves every worktree, through the `STATARB_RAW` setting. Version control for data (git-lfs, DVC) is not used: Alpaca's terms forbid putting its data on a hosted service, and a rebuild from pinned snapshots needs nothing more.
- **New York dates.** A download takes bars before the New York date at the time it runs, never the machine's local date, so a session still trading is never stored as complete. Instants in manifests are UTC.
- **Enough history to rank.** A candidate is ranked on a rebalance date only if it has bars on at least 54 of the 60 days in the window (90%); with fewer it is left out that month, so a new listing does not rank on a handful of days.
- **Rules where they can be read.** The rules for Alpaca's data are numbered in decision record 0004 as the build finds them, and any correction they need is listed in config with its primary source. Cleaning rules are stated in `statarb.data.clean`, and every row they drop is logged with its reason.
- **Statistics only.** The quality report and the review count large moves, gaps and dropped rows, by year and by cause, and never list a ticker's return, price or volume on a date. The split check below is reported the same way.
- **The Wikimedia policies,** read on their own pages before the first download, are recorded in decision record 0003 with what they change in the Wikipedia adapter.
- **Reference docs checked against the code.** From this phase a test checks `docs/architecture.md` against the modules and `docs/data-model.md` against the tables the build writes. `docs/requirements.md` gets the build's measured time, peak memory and disk.
- **The first dependencies.** Setup installs none at run time. Phase 0 adds the four it uses: pandas and NumPy for the tables, pyarrow for deterministic parquet and lxml for parsing the constituent list, each with its licence read from its own metadata. Later phases add theirs when they first use them.

## Downloads

Only `uv run python -m statarb.data.build --download` touches the network. It needs `APCA_API_KEY_ID` and `APCA_API_SECRET_KEY` in the environment, calls only `data.alpaca.markets`, and paces its requests under the free plan's 200 a minute: about two per ticker, bars and then corporate actions. Wikipedia is read once per download, in one request for the pinned revision. A source that throttles is waited on, never evaded. Tests run every adapter on synthetic responses with the network blocked.

## Scope

- **Candidate set:** current S&P 500 constituents. `config/universe.toml` pins the Wikipedia page revision ID and retrieval date; the extracted list is data, written to `data/derived/processed/candidates.parquet`, not config.
- **Universe:** on each rebalance date, the 300 candidates with the highest median dollar volume over the trailing 60 trading days, using only data up to and including that date. Rebalance monthly on the last trading day and apply membership from the next trading day, to limit churn at the boundary. Ranking on today's liquidity would select the companies that grew, which is look-ahead on top of survivorship.
- **Factor instruments:** SPY for the market and the eleven SPDR sector ETFs (XLB, XLC, XLE, XLF, XLI, XLK, XLP, XLRE, XLU, XLV, XLY). XLC starts in June 2018; before then there is no ETF for Communication Services.
- **Sector classification:** dated, not fixed. Start from each ticker's current GICS sector and apply known reclassifications recorded in `config/sector_changes.toml`. At minimum: Real Estate separated from Financials (2016), Communication Services created (2018, taking names from IT, Consumer Discretionary and Telecommunication Services), and the 2023 moves of payments companies such as Visa and Mastercard into Financials.
- **History:** 2016-01-01 to the latest close.
- **Prices and corporate actions:** store open, high, low, close and volume on the basis the source provides, and record what that basis is. Some free sources return prices adjusted for splits but not dividends; check, do not assume. Store split and dividend events separately. Derive total returns in our own code from prices and events. Adjusted price levels are derived, never the stored source of truth: sources rescale whole adjusted histories after each new split or dividend, which would make reproducibility depend on the download date and break the phase 6 daily append.
- **Source:** Alpaca's market data API for prices and the Wikipedia S&P 500 list for candidates and current sectors (decision record 0003), each behind an interface so it can be swapped later. See "Source interfaces" below.
- **Determinism:** pin the parquet writer version, sort rows by (date, ticker) before writing, and fix compression settings.

## Source interfaces

Sources differ in more than how data is fetched, so the interfaces fix what an adapter must return, not just how it is called. Each is a `typing.Protocol`, and the build looks the source up by the name in `config/data.toml`.

- **`PriceSource`.** An adapter returns daily OHLCV bars, a declaration of the price basis those bars are on (unadjusted, split-adjusted as of the download date, or fully adjusted), and split and dividend events by ex-date with their own declared basis. A source that cannot supply split and dividend events is not eligible, because returns could not then be checked for stability.
- **Canonical form.** One shared step, outside the adapters, converts any declared basis to unadjusted prices, volumes and dividends: the prices actually traded on each day. Unadjusted history never changes when a later split or dividend occurs, so it suits both byte-for-byte rebuilds and the phase 6 daily append. Total returns are derived only from the canonical form, once, by shared code; adapters never compute returns.
- **Symbols and dates.** Each adapter maps project tickers to its own format and assigns every bar and event to its exchange trading date.
- **`ConstituentSource`.** A separate interface for the candidate list with current GICS sectors, so the price source and candidate list can change independently. It returns the list, the retrieval date and a revision identifier. Before the Wikipedia adapter first downloads, read the Wikimedia API policies that decision record 0003 lists and follow them.
- **Raw snapshots.** Each download is a snapshot in `data/raw/<source>/<download date>/`, so snapshots from different sources or dates are never confused. A price snapshot holds one parquet file per ticker with what the source returned before any rule is applied (bars and action records); a constituent snapshot holds the raw page. Each snapshot ends with a `manifest.json`, written last, recording the client version, request parameters, tickers, timestamps, the SHA-256 of every file and the snapshot's digest. A snapshot without a manifest is incomplete and is never read. Snapshots are never modified once complete. The build applies the rules for the source's data and the corrections listed in config to them, so a changed rule needs a rebuild, not a download.
- **Rules and corrections.** The rules for Alpaca's data are recorded in a decision record as the build finds them. A correction to a source's record is listed in config with its primary source, never taken from another price source.
- **One price source per build.** Bases are never mixed between tickers. A second source is used only for cross-checking, which needs its own decision record.
- **Contract tests.** One test suite, parameterised over adapters, runs on small synthetic fixtures committed under `tests/fixtures/`: basis declaration, event series, symbol mapping, date assignment, and the round trip through the canonical step to stable returns. The Alpaca adapter runs on synthetic API responses and never calls the API. An adapter counts as pluggable only once it passes.

## Deliverables

1. `src/statarb/data/` with the `PriceSource` and `ConstituentSource` interfaces, the Alpaca and Wikipedia adapters, the shared canonical conversion step, cache, cleaning, return derivation and universe code.
2. `data/derived/processed/prices.parquet`: long format (date, ticker, open, high, low, close, volume) on the recorded basis.
3. `data/derived/processed/actions.parquet`: splits and dividends by ex-date.
4. `data/derived/processed/returns.parquet`: daily total returns derived from 2 and 3, with the adjustment factors needed to put opens on the same basis as closes.
5. `data/derived/processed/universe.parquet`: membership by date.
6. `data/derived/processed/sectors.parquet`: ticker, sector, valid from, valid to.
7. `data/derived/processed/candidates.parquet`: the candidate list from the pinned Wikipedia revision, with current GICS sector and date added.
8. `reports/phase-00/data_quality.md`: statistics only, never a price, volume or return for a ticker on a date: missing days, suspicious jumps (absolute daily return above 25%) and zero-volume days, counted; tickers dropped and why; monthly universe churn; candidates that never enter the universe.
9. Tests for date alignment, adjustment handling, the cleaning rules, universe look-ahead and return stability (see acceptance criteria), plus the adapter contract suite.

## Acceptance criteria

- Running `uv run python -m statarb.data.build` from a clean checkout with a warm cache, in the environment fixed by `uv.lock`, reproduces the parquet files byte for byte.
- After a dependency upgrade, the rebuilt tables are identical in content (equal after reading back), even though file bytes may differ because parquet embeds the writer version.
- Every ticker has at least 95% of trading days in its live window, or is listed as an exception in the quality report.
- Returns for a handful of names with known splits (for example AAPL 2020, NVDA 2021 and 2024) show no split-day jump: each split day's absolute return is below the 25% threshold of the quality report, reported as that bound rather than as the return.
- Universe look-ahead test: perturbing prices and volumes after a cut-off date leaves membership before the cut-off unchanged.
- Return stability test: appending a later split or dividend leaves every earlier return unchanged.
- The Alpaca and Wikipedia adapters pass the contract suite.

## Known pitfalls

- **Survivorship bias.** The candidate set is still today's S&P 500 list. Point-in-time ranking removes the bias from choosing on current liquidity, but not the bias from only including companies that survived and stayed in the index. Public reconstructions of historical membership exist, but free sources rarely carry prices for delisted names, which is the binding constraint. Write it up clearly in the phase review.
- **Adjusted close versus open.** If fills later use open prices, put them on the same basis with the same factors.
- **Sources revise old data and change without notice.** Rebuild from the raw snapshot, never from a new download, and record which snapshot each result used.

## Out of scope

Factor models, signals, anything that computes returns beyond the daily total returns above and simple quality checks.

## Review questions

- How many tickers did we lose and why?
- How much does the universe change month to month?
- How bad is the survivorship problem likely to be, and how would we fix it with paid data?
- What would change if we moved to Europe or a broader universe?
