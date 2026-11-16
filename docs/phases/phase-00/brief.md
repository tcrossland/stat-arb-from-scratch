# Phase 0: Data and universe

Drafted at setup, and revised at the start of the phase with what earlier phases found.

## Goal

A clean, reproducible daily dataset for a point-in-time universe of liquid US large caps, plus the sector and market ETFs needed for the factor model in phase 1.

## Scope

- **Candidate set:** current S&P 500 constituents. Record the list in `config/universe.toml` with the date it was taken.
- **Universe:** on each rebalance date, the 300 candidates with the highest median dollar volume over the trailing 60 trading days, using only data up to and including that date. Rebalance monthly on the last trading day and apply membership from the next trading day, to limit churn at the boundary. Ranking on today's liquidity would select the companies that grew, which is look-ahead on top of survivorship.
- **Factor instruments:** SPY for the market and the eleven SPDR sector ETFs (XLB, XLC, XLE, XLF, XLI, XLK, XLP, XLRE, XLU, XLV, XLY). XLC starts in June 2018; before then there is no ETF for Communication Services.
- **Sector classification:** dated, not fixed. Start from each ticker's current GICS sector and apply known reclassifications recorded in `config/sector_changes.toml`. At minimum: Real Estate separated from Financials (2016), Communication Services created (2018, taking names from IT, Consumer Discretionary and Telecommunication Services), and the 2023 moves of payments companies such as Visa and Mastercard into Financials.
- **History:** 2016-01-01 to the latest close.
- **Prices and corporate actions:** store open, high, low, close and volume on the basis the source provides, and record what that basis is. Some free sources return prices adjusted for splits but not dividends; check, do not assume. Store split and dividend events separately. Derive total returns in our own code from prices and events. Adjusted price levels are derived, never the stored source of truth: sources rescale whole adjusted histories after each new split or dividend, which would make reproducibility depend on the download date and break the phase 6 daily append.
- **Source:** a free source with an API meant for programs, chosen in a decision record before phase 0, wrapped behind a small interface (`PriceSource`) so it can be swapped later. Cache raw downloads in `data/raw/` as dated snapshots so reruns do not hit the network.
- **Determinism:** pin the parquet writer version, sort rows by (date, ticker) before writing, and fix compression settings.

## Deliverables

1. `src/statarb/data/` with download, cache, cleaning, return derivation and universe code.
2. `data/processed/prices.parquet`: long format (date, ticker, open, high, low, close, volume) on the recorded basis.
3. `data/processed/actions.parquet`: splits and dividends by ex-date.
4. `data/processed/returns.parquet`: daily total returns derived from 2 and 3, with the adjustment factors needed to put opens on the same basis as closes.
5. `data/processed/universe.parquet`: membership by date.
6. `data/processed/sectors.parquet`: ticker, sector, valid from, valid to.
7. `reports/phase-00/data_quality.md`: statistics only, never a price, volume or return for a ticker on a date: missing days, suspicious jumps (absolute daily return above 25%) and zero-volume days, counted; tickers dropped and why; monthly universe churn; candidates that never enter the universe.
8. Tests for date alignment, adjustment handling, the cleaning rules, universe look-ahead and return stability (see acceptance criteria).

## Acceptance criteria

- Running `uv run python -m statarb.data.build` from a clean checkout with a warm cache reproduces the parquet files byte for byte.
- Every ticker has at least 95% of trading days in its live window, or is listed as an exception in the quality report.
- Returns for a handful of names with known splits (for example AAPL 2020, NVDA 2021 and 2024) show no split-day jump.
- Universe look-ahead test: perturbing prices and volumes after a cut-off date leaves membership before the cut-off unchanged.
- Return stability test: appending a later split or dividend leaves every earlier return unchanged.

## Known pitfalls

- **Survivorship bias.** The candidate set is still today's S&P 500 list. Point-in-time ranking removes the bias from choosing on current liquidity, but not the bias from only including companies that survived and stayed in the index. Public reconstructions of historical membership exist, but free sources rarely carry prices for delisted names, which is the binding constraint. Write it up clearly in the phase review.
- **Adjusted close versus open.** If fills later use open prices, put them on the same basis with the same factors.
- **APIs change** without notice. Cache aggressively and pin the client's version.

## Out of scope

Factor models, signals, anything that computes returns beyond the daily total returns above and simple quality checks.

## Review questions

- How many tickers did we lose and why?
- How much does the universe change month to month?
- How bad is the survivorship problem likely to be, and how would we fix it with paid data?
- What would change if we moved to Europe or a broader universe?
