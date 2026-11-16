# Phase 5: Portfolio construction

Drafted at setup, and revised at the start of the phase with what earlier phases found.

## Goal

Replace decile sorts with an optimiser that turns forecasts into positions while controlling risk exposures and trading costs, and measure whether it improves net results.

## Optimisation problem (per day)

Maximise: expected return − λ · risk − κ · trading cost, with λ the risk aversion and κ the cost multiplier

- Expected return: model forecast (phase 4) or baseline signal, scaled to return units.
- Risk: factor covariance from the phase 1 model plus a diagonal specific-risk term.
- Trading cost: linear half-spread plus a convex impact term (use a 3/2-power approximation of the square-root model so the problem stays convex).

Subject to:

- Dollar neutral.
- Zero (or tightly bounded) exposure to market beta and each sector.
- Position limits, for example ±2% of gross per name, and a cap relative to average daily volume.
- Fixed gross exposure.

Implement with cvxpy. Solve times for 300 names should be well under a second.

## Deliverables

1. `src/statarb/portfolio/optimiser.py` and a decile-sort implementation behind the same interface.
2. `reports/phase-05/`:
   - net Sharpe, turnover and realised factor exposures: decile sort versus optimiser, for both baseline and ML signals
   - sensitivity to λ and to κ
3. Tests: constraints satisfied on random inputs; with zero costs and no risk penalty the optimiser reproduces a sort-like portfolio.

## Acceptance criteria

- Realised market and sector exposures are measurably closer to zero than with decile sorts.
- Turnover falls without a proportional loss of gross alpha.

## Review questions

- Where does the improvement come from: lower turnover, better neutrality, or better use of forecast strength?
- How sensitive are results to the cost multiplier? An optimiser that only works with a precisely tuned cost parameter is fragile.
