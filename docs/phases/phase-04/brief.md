# Phase 4: Portfolio construction

Drafted at setup, and revised at the start of the phase with what earlier phases found.

## Goal

Replace decile sorts with an optimiser that turns forecasts into positions while controlling risk exposures and trading costs, and measure whether it improves net results for the baseline signal. This comes before the ML signal because trading costs are the binding constraint for short-term reversal (decision record 0002).

## Model B

The statistical factor model, moved here from phase 1 (decision record 0002): PCA on the rolling cross-section of standardised returns, using only data up to *t−1*, with the top *m* components as factors (try *m* = 5 to 15). It gives a residual table beside Model A's and a second risk model for the optimiser. It enters behind the `FactorModel` interface of phase 1, and the look-ahead test covers it as it covers Model A. Compare its residual properties with Model A's on the phase 1 diagnostics.

## Optimisation problem (per day)

Maximise: expected return − λ · risk − κ · trading cost, with λ the risk aversion and κ the cost multiplier

- Expected return: the baseline signal converted to return units by regressing next-day residual return on the signal over a trailing window, using only data up to *t*. The conversion works on any `Signal` (phase 2), so phase 5's forecast reaches the optimiser unchanged.
- Risk: factor covariance from Model A or Model B plus a diagonal specific-risk term, chosen in config.
- Trading cost: linear half-spread plus a convex impact term (use a 3/2-power approximation of the square-root model so the problem stays convex).

Subject to:

- Dollar neutral.
- Zero (or tightly bounded) exposure to market beta and each sector.
- Position limits, for example ±2% of gross per name, and a cap relative to average daily volume.
- Fixed gross exposure.

Implement with cvxpy. Solve times for 300 names should be well under a second. Name the solver explicitly and pin its version alongside cvxpy's, with tolerances in config: a different solver or version can return slightly different weights, which would break exact reproducibility.

If the problem is infeasible or the solver fails on a day, hold the previous day's book and log the day. Never relax constraints automatically. Report how many days this happened; phase 6 uses the same rule.

## Turnover controls

Run two ways of limiting trading and compare them:

- **Cost penalty** (the problem above): turnover is controlled indirectly through the trading cost term and κ.
- **Turnover budget:** the same objective with κ = 1, plus a hard constraint that daily turnover, the sum of |*w*(*t*) − *w*(*t−1*)| across names, is at most *τ* of gross. Sweep *τ* (for example 10%, 25%, 50% and 100%). The constraint is convex, and *τ* reads directly as a dial.

Both variants apply a **minimum trade size** from config, in dollars: after solving, trades smaller than the minimum are dropped, and the resulting book is re-checked against the constraints. Report any residual breach of dollar or factor neutrality this causes. Do not cap the number of trades: that needs integer constraints and limits the wrong thing, since costs scale with traded value.

## Deliverables

1. `src/statarb/factors/` gains Model B; `src/statarb/portfolio/optimiser.py` and a decile-sort implementation behind the same interface.
2. `reports/phase-04/`:
   - Model B's residual diagnostics beside Model A's
   - net Sharpe, turnover and realised factor exposures for the baseline signal: decile sort (at the holding period chosen in phase 2) versus optimiser, under the phase 3 cost model, with each risk model
   - comparison with the phase 3 no-trade-zone variant
   - cost penalty versus turnover budget at matched average turnover
   - sensitivity to λ, κ and *τ*
   - effect of the minimum trade size on net Sharpe and on neutrality
3. Tests:
   - Model B's residuals on day *t* do not change when data after *t* is perturbed
   - constraints satisfied on random inputs
   - the turnover budget is never exceeded
   - after the minimum-trade filter, no trade is below the minimum
   - a forced solver failure holds the previous day's book
   - with zero costs and no risk penalty the optimiser reproduces a sort-like portfolio
   - the expected-return calibration on day *t* does not change when data after *t* is perturbed

## Acceptance criteria

- Realised market and sector exposures are measurably closer to zero than with decile sorts.
- Turnover falls without a proportional loss of gross alpha.

## Out of scope

New signals and ML forecasts (phase 5).

## Review questions

- Does Model B change the picture, as a residual or as a risk model?
- Where does the improvement come from: lower turnover, better neutrality, or better use of forecast strength?
- How sensitive are results to the cost multiplier? An optimiser that only works with a precisely tuned cost parameter is fragile.
- At matched turnover, does the cost penalty or the turnover budget give better net results, and which is less sensitive to its parameter?
- Does the optimiser beat the simple no-trade zone by enough to justify its complexity?
