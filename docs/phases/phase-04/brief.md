# Phase 4: Portfolio construction

Drafted at setup, and revised at the start of the phase with what earlier phases found.

## Goal

Replace decile sorts with an optimiser that turns forecasts into positions while controlling risk exposures and trading costs, and measure whether it improves net results for the baseline signal. This comes before the ML signal because trading costs are the binding constraint for short-term reversal (decision record 0002).

## Revised at the start of the phase

Phase 3 built the cost model, the calibration of a signal to return units and the engine's `Policy` seam; its review says what carries forward. Phase 3 found that no configuration keeps a net edge under the cost model, that commission's per-order minimum binds a retail book and impact a large one, and that the no-trade zone's best results come from trading less at the price of an unbalanced book. This revision makes the brief concrete where that reaches phase 4:

- **Inputs are the phase 0 and 1 tables, plus Model B's own residual table.** The runners read `returns`, `prices`, `residuals`, `universe` and `sectors` from `data/derived/processed/`, as phases 2 and 3 do. Model B writes `residuals_pca.parquet` beside Model A's `residuals.parquet` and leaves Model A's table unchanged. No download.
- **The signal is phase 3's baseline, unchanged:** residual reversal, *n* = 1, not volatility-scaled, *k* = 5, filled at the open of *t+1*, from `config/costs.toml`. The three-day lookback, phase 3's stated comparison, runs through the headline optimiser beside it, so each of phase 3's no-trade paths has an optimiser path on the same signal to compare with. The s-score rule does not enter: it is a threshold rule with its own hedges, not a forecast for every member.
- **The cost model is phase 3's headline,** with the spread as [decision record 0005](../../decisions/0005-spread-as-a-stated-assumption.md) states it. It prices every path, decile or optimiser, after the fill, exactly as in phase 3, and the optimiser's κ term is the same model written in convex form (below). Every cost input still comes from the day before the fill.
- **Book sizes $500k and $5m.** Phase 3's capacity curve peaks around $5m, so that is the book worth optimising; $500k is where commission still binds, and where the minimum trade size is tested.
- **Returns per dollar of capital,** as in phase 3, over the same period, signals from 2017-01-03 to the end of the data. Days before a path's expected move exists count, with an empty book, so every configuration has the same denominator.
- **Expected returns are phase 3's calibration over the holding period.** The draft regressed next-day residual returns on the signal. The optimiser holds positions for days and the baseline's holding period is *k* = 5, so the expected move over *h* = 5 days is what a trade earns, and `statarb.signals.calibration` already computes it with only outcomes known by the close of *t*. Model B's expected move is calibrated on Model B's residuals.
- **Gross exposure at most the capital, not fixed.** An equality on gross exposure is not convex. Phase 3 showed that a book should be sized to its capital rather than rescaled, so a day with weak forecasts deploys less, and the report shows the capital deployed beside every result.
- **Model B uses *m* = 15 factors, fixed, not a sweep from 5 to 15.** Avellaneda and Lee (2010, Table 8) found 15 fixed factors better than a variance target, and each further *m* would be a further trial on the same question. Model B's residuals start on 2017-01-04, the first day with a full 252-day window before it, one day after the first signal date; its expected move exists later still, and the days before count with an empty book as above.
- **Risk model and residuals are crossed.** The draft asks whether Model B changes the picture as a residual or as a risk model. The headline uses Model A for both; at the headline settings the optimiser also runs with Model A's signal and Model B's risk, Model B's signal and Model A's risk, and Model B for both. A decile sort on Model B's residuals gives the decile comparison and the size-bucket comparison phase 2 asked for.
- **The minimum trade size, and the re-solve.** The commission's per-order minimum is not convex, so the minimum trade size is how the optimiser sees it: $1,000 at the headline, where a $1 commission is 10 bps, with $0 and $5,000 beside it. Dropping trades after the solve breaks dollar and factor neutrality, the imbalance phase 3's zone left. The re-solve enters this phase: the names whose trades were dropped are held at their current weights and the problem is solved again over the rest, repeating until no further trade falls below the minimum, so the remaining names restore neutrality. Results are reported both ways, at $1,000 and $5,000. The headline is the filter alone, as drafted, set before any result.
- **The headline λ is set before any backtest return is seen,** from ex-ante properties of the book alone: over the first 60 days on which the expected move exists, with Model A risk and the headline cost, it is the largest λ in {1, 3, 10, 30, 100} at which the book deploys 70% or more of its capital on average at both book sizes. The sweep is that value and its neighbours in the list. Applied before any backtest, the rule gives λ = 30; 100 was added to the list then, so the sweep has a neighbour on each side, and deploys too little to change the choice. κ = 1 at the headline, which prices costs as the cost model measures them.
- **Trials.** A trial is a distinct position path, as before. An optimiser setting's positions depend on the book size, through the cost term, but like phase 3's no-trade path it is one rule tried once, so book sizes are not separate trials. Each optimiser setting, the three-day lookback through the optimiser and the decile sort on Model B's residuals is a new trial; the spread bracket re-costs paths without re-optimising them, so it adds none. The bar is phase 3's ("Judging the result"), against every position path in the repository's logs up to this phase.
- **The backlog items whose trigger is this phase's review:**
  - *Multi-period optimiser:* its action depends on whether costs still dominate after the turnover controls, which only this phase's results can show, so the review decides. The re-solve above is the part of it that does not need a forecast of future signals, and enters now.
  - *An independent short-term reversal series:* not this phase's work. It checks the engine and the data through the decile book's gross P&L, which this phase does not change, and it needs a new data source and a decision record. The review moves its trigger.
  - *Measured effective spreads:* the spread bracket below shows whether any verdict turns on the spread; the review decides from that.
- **What earlier phases leave to this phase:** survivorship flatters the long side (phase 0), unmeasured; phase 2's and phase 3's reports must still rebuild byte for byte after this phase's changes; this phase adds libraries without changing any existing pin, so the dependency-upgrade criterion stays untested.

## Model B

The statistical factor model, moved here from phase 1 (decision record 0002), after Avellaneda and Lee (2010), section 2.1. For each day *t*, over the 252 trading days ending *t−1*: standardise the returns of the stocks with a complete window, take the top *m* = 15 eigenvectors of their correlation matrix, form eigenportfolios with weights *v*/σ, and regress each stock with at least 189 returns in the window on an intercept and the eigenportfolio returns. The residual on *t* is the stock's return less its betas times the eigenportfolio returns on *t*; as in Model A the intercept is estimated but not subtracted. With about 300 stocks and 252 days the correlation matrix is singular; only the top eigenvectors are used, so this is acceptable. Eigenvectors are defined up to sign and their order can swap; the residuals, and the risk and neutrality built from the betas, do not depend on either.

It enters behind the `FactorModel` interface of phase 1, and the look-ahead test covers it as it covers Model A. Its residual properties are compared with Model A's on the phase 1 diagnostics.

From the phase 2 backlog walk: sector ETFs hold the stocks regressed on them, so the largest names' residuals are understated. Phase 1 found their lag-1 reversal weakest, but phase 2 found them earning most of the decile book's P&L. Model B's factors come from the universe itself and give a second view: compare reversal and decile P&L by size bucket under the two models.

## Optimisation problem (per day)

Weights *w* are fractions of capital, as in phase 3. The decision on day *t* is made at the close of *t* and filled at the open of *t+1*.

Maximise: μ′*w* − λ · *h* · *w*′Σ*w* − κ · cost(*w* − *w*₀)

- **Expected return μ:** the signal's expected residual move over the next *h* = 5 days, from `statarb.signals.calibration`. On day *t* only pairs whose outcome is known by the close of *t* qualify.
- **Risk:** Σ is the daily covariance from a factor model, chosen in config: factor covariance over a trailing 252-day window plus a diagonal specific-risk term from trailing 60-day residual variance, both from rows up to and including *t*. Model A's factors are the market and each sector ETF's return less the market's, with the betas from its residual table; Model B's are the eigenportfolios, whose covariance over their window is the diagonal of their eigenvalues. Σ is multiplied by *h* to match the horizon of μ.
- **Trading cost:** the half-spread and the commission's per-share rate times |*w* − *w*₀|, plus impact as a 3/2-power term (the square-root model times the trade, which is convex), all from the phase 3 cost inputs known before the fill. κ is the cost multiplier: 1 prices costs as the cost model does.
- ***w*₀** is the book as known at the decision: the holdings after the previous fill, drifted to the close of *t*.

Subject to:

- Dollar neutral.
- Each risk factor's exposure within 1% of capital: market beta and each sector under Model A, each eigenportfolio under Model B.
- Position limits: |*w*ᵢ| at most 2% of capital, and the position in dollars at most 1% of its 20-day average dollar volume.
- Gross exposure at most the capital.
- Only universe members on *t* can be held; names leaving the universe are sold.

Implement with cvxpy and Clarabel, pinned in `pyproject.toml`. Solve times for 300 names should be well under a second. Name the solver explicitly and put its tolerances in config: a different solver or version can return slightly different weights, which would break exact reproducibility.

If the problem is infeasible or the solver fails on a day, hold the previous day's book and log the day. Never relax constraints automatically. Report how many days this happened, apart from days with no eligible names; phase 6 uses the same rule.

## Turnover controls

Run two ways of limiting trading and compare them:

- **Cost penalty** (the problem above): turnover is controlled indirectly through the trading cost term and κ.
- **Turnover budget:** the same objective with κ = 1, plus a hard constraint that daily turnover, the sum of |*w* − *w*₀| across names, is at most *τ* of capital, like the weights themselves. Forced exits of names that are no longer eligible sit outside the budget. If drift has taken *w*₀ further outside the other constraints than *τ* can repair, the day is infeasible and the previous book is held, as for any solver failure. Sweep *τ* at 10%, 25%, 50% and 100%. The constraint is convex, and *τ* reads directly as a dial.

Both apply the **minimum trade size** from config, in dollars: after solving, trades smaller than the minimum are dropped, and a target below the minimum is set to zero, so small positions close rather than linger. The resulting book is re-checked against the constraints, and any residual breach of dollar or factor neutrality is reported. The re-solve variant then holds the dropped names and solves again, as above. Do not cap the number of trades: that needs integer constraints and limits the wrong thing, since costs scale with traded value.

## Runs

At $500k and $5m, under the headline cost model:

- the decile sort, the phase 3 baseline, and the decile sort on Model B's residuals;
- the headline optimiser: Model A signal and risk, λ at the headline, κ = 1, no turnover budget, minimum trade $1,000, filter only;
- cost penalty: λ at its two neighbours, and κ at 0.5 and 2;
- turnover budget: κ = 1 and the headline λ, with *τ* at 10%, 25%, 50% and 100%;
- minimum trade size: $0 and $5,000, and the re-solve at $1,000 and $5,000;
- risk model and residuals: the three other pairings of Model A and Model B;
- the three-day lookback through the headline optimiser.

The decile sorts, the headline optimiser, Model B through the optimiser and the three-day lookback are also re-costed at each half-spread of the phase 3 bracket, without re-optimising: a trader does not know the true spread and would not re-optimise for it.

## Deliverables

1. `src/statarb/factors/` gains Model B behind `FactorModel`, with its own build writing `residuals_pca.parquet`; `src/statarb/portfolio/` holds the risk models, the optimiser and the decile sort behind one interface, with contract tests that run both through the same checks.
2. `reports/phase-04/`, with every run logged in `experiments.jsonl` through the config overlay and `run_state`:
   - Model B's residual diagnostics beside Model A's, with reversal by size bucket under each
   - net Sharpe, net return by year, turnover, capital deployed and realised factor exposures (net market beta, sector exposure, and the P&L and volatility of the fitted part of the book's returns): decile sort against optimiser, with each risk model
   - decile P&L by size bucket under Model A's and Model B's residuals
   - comparison with phase 3's no-trade zone on the same signal and book size, read from the phase 3 log
   - cost penalty against turnover budget at matched average turnover
   - sensitivity to λ, κ and *τ*
   - effect of the minimum trade size on net Sharpe and on neutrality, with and without the re-solve
   - the verdict at each half-spread in the phase 3 bracket
   - solver days: idle, failed and held, and solve times
   - each configuration judged against the bar
3. Tests:
   - Model B's residuals on day *t* do not change when data after *t* is perturbed, and its eigenvalues equal the eigenportfolios' variances over the window
   - the risk models on day *t* do not change when data after *t* is perturbed
   - constraints satisfied on random inputs
   - the turnover budget is never exceeded
   - after the minimum-trade filter, no trade is below the minimum; after the re-solve, the book is neutral within tolerance
   - a forced solver failure holds the previous day's book
   - with zero costs and no risk penalty the optimiser reproduces a sort-like portfolio
   - the expected-return calibration on day *t* does not change when data after *t* is perturbed
   - the optimiser's decisions up to day *t* do not change when data after *t* is perturbed
   - strict config keys and exact reproduction
4. Documentation in the same change as the code: architecture, data model (the Model B table and the log's new fields), time discipline (Model B, the risk models, the optimiser's decision and the hold-previous-book rule), glossary and requirements.

## Acceptance criteria

- Realised market and sector exposures are measurably closer to zero than with decile sorts.
- Turnover falls without a proportional loss of gross alpha.
- Each configuration is judged against the bar, with trials counted from every log up to this phase.
- Phase 2's and phase 3's reports rebuild byte for byte after this phase's changes.
- Every log entry records its `run_state`, and the committed log comes from a clean tree.

## Out of scope

New signals and ML forecasts (phase 5). The full multi-period optimiser, unless the review moves it into phase 5. New data sources.

## Review questions

- Does Model B change the picture, as a residual or as a risk model?
- Where does the improvement come from: lower turnover, better neutrality, or better use of forecast strength?
- How sensitive are results to the cost multiplier? An optimiser that only works with a precisely tuned cost parameter is fragile.
- At matched turnover, does the cost penalty or the turnover budget give better net results, and which is less sensitive to its parameter?
- What does the minimum trade size cost in neutrality, and does the re-solve buy it back?
- Does the optimiser beat the simple no-trade zone by enough to justify its complexity?
- Does any configuration's verdict against the bar change inside the phase 3 spread bracket?
