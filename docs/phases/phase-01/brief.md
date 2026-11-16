# Phase 1: Factor model and residuals

Drafted at setup, and revised at the start of the phase with what earlier phases found.

## Goal

For each stock and day, split the return into a part explained by market and sector moves and an idiosyncratic residual. The residual is the raw material for every signal that follows.

## Approach

Start simple and keep it:

- **Model A (ETF regression).** For each stock, regress daily returns on SPY and its own sector ETF over a rolling 252-day window, using only data up to *t−1*. The residual on day *t* is the actual return minus the fitted return using the betas estimated before *t*.
  - Sector ETF returns are correlated with SPY. Either regress on SPY and the sector ETF's excess over SPY, or accept the collinearity and note it.
- **Model B (statistical factors, optional stretch).** PCA on the rolling cross-section of returns, top *m* components (try *m* = 5 to 15). Compare residual properties with Model A.

## Deliverables

1. `src/statarb/factors/` with a `FactorModel` interface and at least Model A.
2. `data/processed/residuals.parquet`: date, ticker, raw return, fitted return, residual, betas.
3. `reports/phase-01/`:
   - distribution of betas over time
   - average pairwise correlation of raw returns versus residuals (residuals should be far less correlated)
   - residual autocorrelation at lags 1 to 5, pooled and by sector. A negative lag-1 autocorrelation is the first hint that reversal exists.
4. Tests proving the betas used on day *t* do not depend on data from *t* or later.

## Acceptance criteria

- Mean cross-sectional correlation of residuals is well below that of raw returns (record the numbers).
- The look-ahead test passes: perturbing all data after a cut-off date leaves every residual before the cut-off unchanged.

## Known pitfalls

- Using the same day's data in the regression that produces that day's residual. This quietly makes residuals smaller and reversal look stronger.
- Short histories at the start of the window. Require a minimum number of observations before emitting a residual.
- Earnings days produce huge residuals that behave differently. Flag them now (even a crude flag from large volume spikes) so phase 4 can use it.

## Out of scope

Trading signals, portfolios, P&L.

## Review questions

- How negative is lag-1 residual autocorrelation, and how stable is it across years?
- Does Model B change the picture?
- What does the residual distribution look like in March 2020 compared with a calm year?
