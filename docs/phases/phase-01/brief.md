# Phase 1: Factor model and residuals

Drafted at setup, and revised on 2026-11-16 at the start of the phase with what phase 0 found.

## Goal

For each stock and day, split the return into a part explained by market and sector moves and an idiosyncratic residual. The residual is the raw material for every signal that follows.

## Revised at the start of the phase

Phase 0 built the price, action, return, universe, candidate and dated-sector tables from the pinned snapshot, and its review says what carries forward. This revision makes the brief concrete where that reaches phase 1:

- **Inputs are phase 0's tables, nothing else.** The build reads `returns`, `sectors`, `prices` (for volume), `candidates` and `universe` from `data/derived/processed/`. No download: every number in this phase comes from the snapshot pinned in phase 0.
- **Returns, not prices.** The regression uses the daily total returns of `returns.parquet`, which already carry splits, dividends and spin-offs. Price levels never enter the model.
- **Betas up to *t − 1*, a date from config.** The window is the 252 trading days ending the day before *t*, and a residual needs at least 189 returns in it (75%). The first residual date follows from `[dates] start` in `config/data.toml` and the minimum in `config/factors.toml`: on the pinned snapshot it is 2016-10-04 for every stock with history from the start. No date is written in code.
- **The choices the drafted brief left open,** made now and recorded in `config/factors.toml`:
  - The sector factor is the sector ETF's return minus SPY's, so the two regressors overlap little and the market beta keeps its usual meaning.
  - A stock that changes sector keeps its window: each past day uses the ETF of the sector the stock was in on that day, read from the dated sectors. A restart would leave it without a residual for most of a year.
  - The intercept is estimated, so drift does not bias the betas, and not subtracted, so a year's drift is not mixed into a one-day residual.
  - Where the stock's sector has no ETF on *t*, or fewer than the minimum days in the window have one, the model uses SPY alone and flags the row `market_only`. On the pinned snapshot this covers T, VZ and TMUS in Telecommunication Services before 2018-09-24, and their first months in Communication Services after it.
- **A crude event flag.** Volume on *t* at least three times its median over the previous 20 trading days. Phase 0 keeps volumes as traded, so each is first put on one share basis with the split ratios, and a split does not register as a spike.
- **Size is dollar volume.** The free data has no shares outstanding, so size buckets use trailing 60-day median dollar volume, the measure the universe already ranks on.
- **Config that fails loudly.** `config/factors.toml` is read into frozen dataclasses that reject unknown or missing keys.
- **Reproducible output.** Two rebuilds give the same bytes for `residuals.parquet`, the report and its charts. Charts are drawn with matplotlib and saved with date and software metadata cleared. matplotlib enters `pyproject.toml` in this phase, its licence and its dependencies' read from their own metadata.
- **The look-ahead test uses phase 0's helper,** `statarb.testing.lookahead`: returns and volumes are perturbed after several cut-offs, and every residual up to each cut-off must be unchanged. A second test does the same for the rolling regression alone.
- **Window sensitivity.** Avellaneda and Lee estimate over 60 days, this project over 252. `statarb.factors.sensitivity` reruns Model A at 60, 126 and 252 days, with the minimum at the same share of each, and compares them on the member-days where all three have a residual. It feeds nothing later; it is there so the review can say what the window costs or buys.
- **Company-level GICS reclassifications** (from the phase 0 backlog walk), in their own step after Model A lands on phase 0's sectors, so the change they make is visible on its own. See the known pitfall below.

## Approach

Start simple and keep it:

- **Model A (ETF regression).** For each stock, regress daily returns on SPY and the ETF for the stock's sector on that date (from `sectors.parquet`) over a rolling 252-day window, using only data up to *t − 1*. The residual on day *t* is the actual return minus the fitted return using the betas estimated before *t*. The choices above settle collinearity, sector changes, the intercept and sectors without an ETF.
- **Model B** (statistical factors from PCA) is built in phase 4, where the optimiser needs a second risk model (decision record 0002).

Compute residuals for every candidate with enough history. Universe membership is applied at signal time, not here; the report describes universe members on the day a pair starts.

## Deliverables

1. `src/statarb/factors/` with a `FactorModel` interface, Model A, the rolling regression, the event flag, the runner `statarb.factors.build` and the window sensitivity runner `statarb.factors.sensitivity`.
2. `data/derived/processed/residuals.parquet`: date, ticker, raw return, fitted return, residual, intercept, betas, the sector ETF used, the number of returns in the window, the market-only flag, the volume ratio and the event flag.
3. `reports/phase-01/`:
   - `diagnostics.md`, statistics only: coverage, the distribution of betas over time, average pairwise correlation of raw returns versus residuals (residuals should be far less correlated), residual autocorrelation at lags 1 to 5, pooled, by year, by sector, by size bucket and on event days, with raw returns at lag 1 for comparison, and the residual distribution in March 2020 against a calm year. A negative lag-1 autocorrelation is the first hint that reversal exists.
   - its charts
   - `window_sensitivity.md`
4. Tests proving the betas used on day *t* do not depend on data from *t* or later, the look-ahead test on the residuals, the rolling regression against a direct least-squares fit on every window, recovery of known betas, the sector splice, the market-only fallback, split days in the event flag and strict config keys.
5. The reference docs in the same change as the code: architecture, data model, time discipline, glossary and requirements.

## Acceptance criteria

- Mean cross-sectional correlation of residuals is well below that of raw returns (record the numbers).
- The look-ahead test passes: perturbing all data after a cut-off date leaves every residual before the cut-off unchanged.
- A rebuild from phase 0's tables reproduces `residuals.parquet`, the report and the charts byte for byte.

## Known pitfalls

- Using the same day's data in the regression that produces that day's residual. This quietly makes residuals smaller and reversal look stronger.
- Short histories at the start of the window. Require a minimum number of observations before emitting a residual.
- Earnings days produce huge residuals that behave differently. Flag them now (even a crude flag from large volume spikes) so phase 5 can use it.
- **ETF self-inclusion.** Sector ETFs hold the stocks being regressed on them, and the largest names make up a large share of their ETF (XLK especially). Their residuals are mechanically understated. Report reversal by size bucket, and as a stretch compare with a sector factor built from universe members excluding the stock itself.
- **Returns that span missing bars.** Phase 0 drops zero-volume bars, so a few returns span more than one trading day (six on the pinned snapshot). They are regressed against the factor returns of their own date, which understates the factor part of a multi-day move. The review says whether they matter.
- **Company-level GICS reclassifications** (from the phase 0 backlog walk). `config/sector_changes.toml` covers the three structural GICS changes since 2016 for today's candidates, not companies moved between sectors in other years, so a stock can carry today's sector back to dates when it sat in another and be regressed on the wrong ETF. Find the universe members whose sector changed outside the structural changes by comparing the pinned Wikipedia revision with revisions at each year end since 2016, read by hand as a reader would, not by the adapter. Wikipedia only says which companies to check: confirm each move and its effective date from S&P Dow Jones Indices, MSCI or the issuer, as phase 0 did, and add it to `config/sector_changes.toml` with its source. A move whose date no primary source gives is listed in the review and left on today's sector. The step is its own commit, with a `Results:` footer saying how many universe stock-days change sector and how the report moves.

## Out of scope

Trading signals, portfolios, P&L.

## Review questions

- How negative is lag-1 residual autocorrelation, and how stable is it across years?
- What does the factor model add over raw returns?
- Does reversal look different for the largest names, given ETF self-inclusion?
- What does the residual distribution look like in March 2020 compared with a calm year?
