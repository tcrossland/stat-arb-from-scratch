# 0002: Plan revisions before phase 0

**Date:** 2026-11-16
**Status:** accepted

## Context

A review of the phase briefs before any code was written found problems in phase 0 that would carry into every later phase, an ordering question between the ML and portfolio construction phases, gaps in how backtest results and the paper-trading run would be judged, and two places where later phases would need a seam the first drafts did not plan for.

## Decision

- **Point-in-time universe.** Membership on each date comes from trailing 60-day dollar volume among the candidates, using only data up to that date, rebalanced monthly. The candidates remain today's S&P 500 list, so survivorship in membership remains and is reported.
- **Prices plus corporate actions.** Prices are stored on the basis the source provides, with split and dividend events stored separately, and total returns are derived in our own code. Adjusted price levels are never the stored source of truth, because sources rescale adjusted history after each new corporate action.
- **Dated sector mapping.** Sectors carry validity dates, built from current GICS plus known reclassifications. Where a stock's sector has no ETF on a date, the factor model uses SPY alone.
- **Portfolio construction before ML.** Portfolio construction becomes phase 4 and the ML signal phase 5. Trading costs are the binding constraint for short-term reversal, so turnover control is the more likely source of net edge. A model forecast is used through the optimiser in the end, so evaluating it once in that pipeline avoids a second round of comparisons, and the step most prone to overfitting moves later.
- **Model B with the optimiser.** The statistical factor model (PCA) moves from a stretch goal in phase 1 to phase 4, where its covariance gives the optimiser a second risk model and its residuals a second input. Phase 1 builds Model A only.
- **One interface for signals.** From phase 2, every signal implements a `Signal` interface: it declares the tables it reads, returns a score per stock and day from the tables cut at *t*, is chosen by name in config and is logged with each run. The look-ahead test runs over every registered signal. The ML forecasts of phase 5 enter as signals, so the baseline and the model share one route through the cost model and the optimiser.
- **Testing discipline from phase 2.** Every backtest configuration is logged, a shuffled-signal placebo test guards the engine, and fill timing is run as a sweep with the open of *t+1* as the headline.
- **Phase 6 judges implementation, not P&L.** Eight weeks of forward running cannot distinguish the backtest Sharpe from zero, and simulated fills reuse the phase 3 cost model. The drift report centres on data revisions, turnover, signal distributions and IC, with P&L as a wide-band sanity check.

## Consequences

- Phase 0 is larger: more tables and two extra tests (universe look-ahead and return stability).
- Reclassifications must be maintained by hand in `config/sector_changes.toml`.
- A signal needs a calibration step to return units before the optimiser can use it.
- Phase 6 cannot test the cost model without a broker paper account, which would need its own decision record.
