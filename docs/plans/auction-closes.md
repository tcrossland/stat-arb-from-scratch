# Closes from the listing exchange's auctions

Status: steps 1 to 4 built, 2026-11-27; step 5, the first download and report, is next. The measurement half of the backlog item "Closes from the listing exchange's closing auctions". Adopting auction prices waits for the forward run's review.

## Purpose

The build takes the consolidated daily bar's open and close. A market-on-close order fills at the listing exchange's closing auction and a market-on-open order at its opening auction, and neither price need be the bar's. How often they differ in this data has not been measured. This work measures it, by year, for stocks and the factor ETFs apart, without changing the build. It also answers a question the measurement depends on: whether Alpaca's condition codes pick out the listing exchange's official prices, and in which years.

## Constraints

- **The build does not change.** No file `FILES` in `statarb.paper.frozen` hashes changes, nor `config/momentum_forward.toml`. The new settings go in new files, `config/auctions.toml` and `config/listings.toml`, which no frozen record hashes. No table under `data/derived/processed/` is written.
- **No forward day.** The last date requested is 2026-11-13, the last session before the forward run's first (record 0007 item 4, as record 0010 item 8 amends it). The adapter refuses a last date on or after `first_session` in `config/paper.toml`, and drops and counts any record dated after its last date, should the endpoint return one.
- **Alpaca's terms.** The auctions endpoint is on the market data host Alpaca's bars already come from, under the terms of [decision record 0003](../decisions/0003-data-sources-alpaca-and-wikipedia.md). The raw snapshot stays out of the repository. The report holds statistics only: counts, shares, and sizes of differences in basis points, never a price, size or per-ticker value.
- **The scheduled jobs share the key.** They download at 13:15 and 13:45 CET under the same limit of 200 requests a minute. The download paces itself as the bar download does, and is run outside about 13:00 to 14:30 CET.
- **Real data is read once, by the owner.** Every runner here is built and tested on synthetic responses and fixtures. The first download and the first report run on real data are the owner's, from a clean tree.

## What the endpoint returns

From Alpaca's reference for `GET /v2/stocks/auctions` and its market data FAQ, read on 2026-11-27:

- Parameters: `symbols`, `start` and `end` (both inclusive, RFC-3339 or a date), `limit` (1 to 10,000 data points a page, across all symbols), `asof` (the date that fixes which entity a symbol names, so data under earlier names is returned), `feed` (only `sip`), `page_token`, `sort`.
- The response maps each symbol to a list of days. Each day has `d` (the date), `o` (opening auctions) and `c` (closing auctions). Each auction print has `p` (price), `s` (size, optional), `t` (timestamp), `x` (exchange code) and `c` (condition). Each price, exchange and condition triple appears once, with its earliest timestamp.
- The reference's example shows one Nasdaq-listed stock's close printed by both Nasdaq (`Q`) and NYSE Arca (`P`), each with condition `6` and condition `M`. So the condition alone does not identify the listing exchange's print, and the measurement keys on the exchange code as well.
- The stock condition codes that matter, from the FAQ's table: `6` Market Center Closing Trade and `O` Market Center Opening Trade, which update a daily bar's close and open; `M` Market Center Official Close and `Q` Market Center Official Open, which update nothing in a bar. So a bar's close can come from a later regular trade, or from another centre's closing trade, rather than the listing exchange's auction.
- Coverage: Alpaca states historical data "since 2016" for the free plan. The reference gives no start year for auctions, so the report counts by year how many symbol-days have any auction record, and the year coverage starts is read from that.
- The exchange and condition code tables are served by `/v2/stocks/meta/exchanges` and `/v2/stocks/meta/conditions/trade`. The download keeps both in the snapshot, so the codes the report uses are those Alpaca published at the time.

## Design

### The download

- `statarb.data.auctions`: `AuctionSource` with the `Getter` and `pages` of `statarb.data.alpaca`, so the same `Client` signs, paces and retries every request, and every URL is built by `request_url` on `DATA_HOST`. One symbol a request, so each ticker's pages stay its own; the limit counts data points across symbols, so batching saves nothing.
- `asof` is the download date of the pinned bar snapshot (2026-11-16, from `config/data.toml`), so names map back as they did for the bars.
- `end` is sent as the end of the last date in New York time (an RFC-3339 timestamp), since a bare date may be read as its midnight.
- The raw snapshot is `data/raw/alpaca-auctions/<download date>/`, written by `cache.SnapshotWriter`, so it gets a manifest with every file's hash and its digest and is made read-only. It holds one parquet file per ticker in long form: one row per print, with the date, the session (`open` or `close`) and the print's fields as returned, so nothing is lost and a print split across two pages is still one day's. It also holds the two code tables as JSON. The manifest lists the tickers, the dates, `asof`, the tickers with no auction data, the failures, and any records dropped for falling after the last date.
- The tickers are those of the pinned bar snapshot's manifest: the candidates and the factor ETFs.
- `config/auctions.toml` holds the dates, `asof`, the pacing, the pinned snapshot and digest (empty until the first download), the comparison tolerance, and the map from listing exchange to Alpaca's exchange code. The runner checks that map against the snapshot's copy of the exchange table and refuses a mismatch.
- The runner is `uv run python -m statarb.data.auction_report --download`, which downloads, prints the setting that pins the snapshot, and stops.

### The listing exchange per ticker

- `config/listings.toml` names its source of current listings, its URL, the date it was read and its terms. It then gives every ticker's current listing exchange, and each transfer since 2016 as a dated entry with the exchange it left, the one it joined and its primary source: the company's filing or press release, or the exchange's notice. A transfer's date is the first session on the new exchange.
- `statarb.data.listings` turns it into dated intervals per ticker, from the current listing back through the transfers, and refuses a transfer whose `to` does not match the next interval's exchange, or a ticker with two current listings.
- **The source of current listings** is SEC EDGAR, for every value in the file: `company_tickers_exchange.json` for the stocks, each ETF's prospectus for the twelve ETFs, and the issuers' filings for the transfers. The SEC's website policy, read on its own page ("Website Dissemination", 2026-11-27), says information on sec.gov is public and may be copied or further distributed without permission, and asks for a citation, which the file gives. Its fair-access rules allow at most 10 requests a second and no unclassified bots. Nothing here downloads from it on a schedule: the file is read once to write the config, and the date it was read is recorded.
  - The SEC file names "NYSE" for every NYSE-group exchange: it files SPY, listed on NYSE Arca, as "NYSE", and has no NYSE Arca or NYSE American entries. So a stock it files as "NYSE" is entered as NYSE, and the listing check below confirms or flags it from the auction data, which does tell the exchanges apart.
  - The Nasdaq Trader symbol directory gives the listing exchange exactly, ETFs included, but its terms (the site's "Copyright, Trademarks and Disclaimers" page, read 2026-11-27) allow one unaltered copy for personal, non-commercial use and forbid distributing its content in whole or in part without consent. A config file derived from it could not be committed, so it is not used.
- **Transfers** are found two ways: the issuers' filings and the exchanges' announcements of switches for the current constituents, and, once the auctions are downloaded, a listing check in the report (below), which flags every ticker and year whose largest closing print comes from another exchange than the config's. Each flagged case gets a primary source and an entry, or the ticker is left out of the counts and listed.
- **A decision record** (0011) records the listing source and its terms before it is used, as decision record 0003 did for Alpaca and Wikipedia, with the auctions endpoint as a new use of Alpaca under the same terms, and the rule for the reruns below.

### The counts

- `statarb.data.auction_counts`, pure functions of explicit frames: the auctions in long form, the bars, the listing intervals, the set of ETFs and the tolerance.
- For each symbol-day with a bar, the listing exchange's prints are found by exchange code and date. Four prices are compared with the bar: the closing cross (condition `6`) and the official close (`M`) with the bar's close, and the opening cross (`O`) and the official open (`Q`) with the bar's open. A price differs when it is more than the tolerance away, half the smallest sub-dollar tick ($0.00005), so rounding never counts.
- **Report tables**, by year and by stocks and ETFs apart:
  - coverage: symbol-days with a bar, with any auction record, and with a print from the listing exchange;
  - the condition check: the share of symbol-days on which the listing exchange prints `M` (and `Q`), on which another exchange prints them too, on which its `M` and `6` prices differ, and on which its print is the largest closing print by size where sizes are given. This says whether, and from which year, `M` from the listing exchange identifies the official close;
  - the counts: for each of the four prices, the symbol-days compared, the number and share that differ, and the median and 95th percentile of the absolute difference in basis points among those that differ;
  - the listing check: by year, the tickers whose largest closing print is on another exchange than the config's, and the tickers left out.
- **The runner** `uv run python -m statarb.data.auction_report` reads the pinned auction snapshot and the pinned bar snapshot of `config/data.toml`, both verified by digest, and the raw bars as Alpaca returned them, unadjusted like the auction prices. It cuts both at the last date and writes `reports/phase-08/auction_closes.md` with the snapshots' digests, the commit and whether the tree was clean. It reads no processed table and calls no loader the forward holdout guard covers.

### The reruns of the headline paths (proposed rule, nothing run)

The backlog's next half reruns the headline paths on auction prices under a config overlay: `data.toml`'s `[paths]` pointed at tables with the listing exchange's auction open and close in place of the bar's where they differ. The rule proposed for how they are logged:

1. **They are not trials.** Each repeats a logged path with its configuration unchanged, on prices that differ only where the auction differs from the bar. Nothing is chosen from them and no setting follows them, the case `statarb.backtest.source_check` set in phase 7 for the same path on another source's prices. Counting them would raise the deflated bar for a choice nobody made.
2. **They are logged where the count cannot read them.** `repository_trials` reads every `reports/phase-*/experiments.jsonl`. The reruns write `reports/phase-08/auction_overlay.jsonl` instead, in the same entry format with the overlay in each entry's `run_state`, so they are on record with their configurations, seeds and commits, and the trial count is unchanged. A test checks that `logs` in `statarb.backtest.trials` does not read that file, and that the repository's trial count is the same before and after it is written.
3. **They are reported against the logged numbers.** A generated section of `reports/phase-08/auction_closes.md` gives each headline path's config id, its logged metric and the rerun's, side by side.
4. **Adoption is separate.** If the forward run's review adopts auction prices, that is a build change after the fact with an amendment to decision record 0004. Every logged path is then rerun in the ordinary way into `experiments.jsonl` with a `Results:` footer. Each keeps its path id, so it replaces its statistic and adds no trial.

## Steps

1. **The plan** (this file), agreed before any code.
2. **The download:** `statarb.data.auctions`, `config/auctions.toml` and the `--download` path of the runner. Tests on synthetic responses: the request parameters, pagination with a day split across pages, a record after the last date dropped and counted, a last date on or after `first_session` refused, the snapshot's layout and manifest, and every request going to `data.alpaca.markets` alone. Done when the tests pass and nothing touched the network.
3. **The listings:** decision record 0011 and its line in the index; `config/listings.toml` with every pinned bar snapshot ticker's current exchange and each transfer since 2016 with its primary source; `statarb.data.listings` with tests of the intervals and the refusals.
4. **The counts:** `statarb.data.auction_counts` and the report runner, with tests on synthetic fixtures: each of the four comparisons, the tolerance, stocks and ETFs apart, a ticker with a transfer, the condition check, the listing check, and a report with no price in it. Then the reference docs: architecture, data model (the raw snapshot), time discipline (an auction price is known at its auction), glossary, requirements and the documentation index. Done when ruff, `uv run pytest -m "not slow"` and the full suite pass, committed on the branch.
   - Built 2026-11-27. The runner is `statarb.data.auction_report`; the snapshot keeps the prints under `prints/` and Alpaca's code tables under `meta/`. A ticker the data contradicts and no source settles goes under `[[left_out]]` in `config/listings.toml` with its reason.
5. **The owner's runs:** the download, outside 13:00 to 14:30 CET; the snapshot pinned in `config/auctions.toml` and committed; then the report from a clean tree. Any ticker the listing check flags gets a sourced transfer or is left out before the report is committed.

The overlay reruns, and the backlog's "Why the two sources' closes and volumes differ before 2023", come after step 5 and are not part of this plan.

## Out of scope

- Any change to the build, the processed tables, the frozen records or either forward run.
- Intraday data or a model of the closing-auction fill (the backlog's near-close item).
- MarketParquet's closes: the cross-check item uses these auction prices once they exist.
