# Phase 0: Data and universe

Drafted at setup, and revised at the start of the phase with what earlier phases found.

## Goal

A clean, reproducible daily dataset for a universe of liquid US large caps, plus the sector and market ETFs needed for the factor model in phase 1.

## Scope

- **Universe:** roughly the 300 most liquid US stocks. Start from current S&P 500 constituents, rank by median 60-day dollar volume, keep the top 300. Record the list in `config/universe.toml` with the date it was built.
- **Factor instruments:** SPY for the market and the eleven SPDR sector ETFs (XLB, XLC, XLE, XLF, XLI, XLK, XLP, XLRE, XLU, XLV, XLY).
- **History:** 2016-01-01 to the latest close, as far back as the free sources under consideration give consolidated daily bars. XLC starts later; handle the gap explicitly.
- **Fields:** open, high, low, close, adjusted close, volume. Sector classification per stock (GICS sector is enough).
- **Source:** a free source with an API meant for programs, chosen in a decision record before phase 0. Wrap it behind a small interface (`PriceSource`) so it can be swapped later. Cache raw downloads in `data/raw/` so reruns do not hit the network.

## Deliverables

1. `src/statarb/data/` with download, cache and cleaning code.
2. `data/processed/prices.parquet`: long format (date, ticker, fields) with total-return-adjusted prices.
3. `data/processed/sectors.parquet`: ticker to sector mapping.
4. `reports/phase-00/data_quality.md`: missing days per ticker, suspicious jumps (absolute daily return above 25%), zero-volume days, tickers dropped and why.
5. Tests for date alignment, adjustment handling and the cleaning rules.

## Acceptance criteria

- Running `uv run python -m statarb.data.build` from a clean checkout with a warm cache reproduces the parquet files byte for byte.
- Every ticker in the universe has at least 95% of trading days in its live window, or is listed as an exception in the quality report.
- Adjusted returns for a handful of names with known splits (for example AAPL 2020, NVDA 2021 and 2024) show no split-day jump.

## Known pitfalls

- **Survivorship bias.** Using today's S&P 500 list over the past ten years includes only the companies that survived and grew. This inflates historical returns, especially for a reversal strategy that buys losers. Free point-in-time constituent data is hard to find. Accept the bias for now, measure the dates each ticker joined if you can, and write it up clearly in the phase review.
- **Adjusted close versus open.** Free sources often adjust only the close. If you later use open prices for fills, adjust them with the same factor.
- **APIs change** without notice. Cache aggressively and pin the client's version.

## Out of scope

Factor models, signals, anything that computes returns beyond simple daily returns for quality checks.

## Review questions

- How many tickers did we lose and why?
- How bad is the survivorship problem likely to be, and how would we fix it with paid data?
- What would change if we moved to Europe or a broader universe?
