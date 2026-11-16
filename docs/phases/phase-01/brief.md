# Phase 1: Factor model and residuals

Drafted at setup, and revised at the start of the phase with what earlier phases found.

## Goal

For each stock and day, split the return into a part explained by market and sector moves and an idiosyncratic residual. The residual is the raw material for every signal that follows.

## Approach

Start simple and keep it:

- **Model A (ETF regression).** For each stock, regress daily returns on SPY and the ETF for the stock's sector on that date (from `sectors.parquet`) over a rolling 252-day window, using only data up to *t−1*. The residual on day *t* is the actual return minus the fitted return using the betas estimated before *t*.
  - Sector ETF returns are correlated with SPY. Either regress on SPY and the sector ETF's excess over SPY, or accept the collinearity and note it.
  - Where the stock's sector has no ETF on a date (Communication Services before XLC in June 2018), regress on SPY alone and flag those rows.
  - When a stock changes sector, the regression window should use the ETF that applied on each day, or restart. Pick one and record it.
- **Model B** (statistical factors from PCA) is built in phase 4, where the optimiser needs a second risk model (decision record 0002).

Compute residuals for every candidate with enough history. Universe membership is applied at signal time, not here.

## Deliverables

1. `src/statarb/factors/` with a `FactorModel` interface and Model A.
2. `data/derived/processed/residuals.parquet`: date, ticker, raw return, fitted return, residual, betas, factor set used.
3. `reports/phase-01/`:
   - distribution of betas over time
   - average pairwise correlation of raw returns versus residuals (residuals should be far less correlated)
   - residual autocorrelation at lags 1 to 5, pooled, by sector and by size bucket. A negative lag-1 autocorrelation is the first hint that reversal exists.
4. Tests proving the betas used on day *t* do not depend on data from *t* or later.

## Acceptance criteria

- Mean cross-sectional correlation of residuals is well below that of raw returns (record the numbers).
- The look-ahead test passes: perturbing all data after a cut-off date leaves every residual before the cut-off unchanged.

## Known pitfalls

- Using the same day's data in the regression that produces that day's residual. This quietly makes residuals smaller and reversal look stronger.
- Short histories at the start of the window. Require a minimum number of observations before emitting a residual.
- Earnings days produce huge residuals that behave differently. Flag them now (even a crude flag from large volume spikes) so phase 5 can use it.
- **ETF self-inclusion.** Sector ETFs hold the stocks being regressed on them, and the largest names make up a large share of their ETF (XLK especially). Their residuals are mechanically understated. Report reversal by size bucket, and as a stretch compare with a sector factor built from universe members excluding the stock itself.

## Out of scope

Trading signals, portfolios, P&L.

## Review questions

- How negative is lag-1 residual autocorrelation, and how stable is it across years?
- Does reversal look different for the largest names, given ETF self-inclusion?
- What does the residual distribution look like in March 2020 compared with a calm year?
