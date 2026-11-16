# Roadmap

The plan, phase by phase. The strategy, and why it is run on free daily data, is described in [`README.md`](../README.md).

## Phases

| # | Phase | Main question | Key output |
|---|-------|---------------|------------|
| 0 | Data and universe | Can we build a clean, honest daily dataset? | Parquet price panel, universe file, data quality report |
| 1 | Factor model and residuals | What part of each stock's move is idiosyncratic? | Daily residual returns, factor exposure diagnostics |
| 2 | Baseline signal and backtest | Does simple residual reversal show any edge before and after costs? | Backtest engine, first P&L curve, metrics report |
| 3 | Cost realism | How much of the edge survives realistic trading and shorting costs? | Cost model, cost-sensitivity analysis |
| 4 | ML signal | Can a model learn when reversal works and when it does not? | Feature set, LightGBM model, walk-forward IC report |
| 5 | Portfolio construction | Does an optimiser with neutrality and turnover control beat decile sorts? | cvxpy optimiser, comparison report |
| 6 | Paper-trading simulation | Does the live, forward-running version behave like the backtest? | Daily scheduled run, simulated ledger, drift report |

## Principles

- Every phase ends with a written review before the next begins.
- The baseline from phase 2 is kept running in every later comparison. A more complex method has to beat it after costs to earn its place.
- Expect the edge to shrink at each phase. A result that improves dramatically is a reason to look for a bug, usually look-ahead.

## Out of scope for now

Intraday data, real order placement, options, futures, other asset classes. Revisit after phase 6 with a decision record.

Work after phase 6 continues the numbering, as phase 7 and on, with the same brief, review and tag.
