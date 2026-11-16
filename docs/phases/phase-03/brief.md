# Phase 3: Cost realism

Drafted at setup, and revised at the start of the phase with what earlier phases found.

## Goal

Replace the flat cost assumption with a model that reflects how costs actually vary by stock, size and market conditions, then see how much of the baseline edge survives.

## Revised at the start of the phase

Phase 2 built the engine, the `CostModel` interface with a flat cost, the experiment log with its run state and the trial count; its review says what carries forward. This revision makes the brief concrete where that reaches phase 3:

- **Inputs are the phase 0 and 1 tables, nothing else.** The runner reads `returns`, `prices`, `residuals`, `universe` and `sectors` from `data/derived/processed/`, as phase 2 does. No download. Phase 3 stores no table: spread estimates, volatilities and volumes are recomputed from these on each run.
- **The configurations,** re-run unchanged except for the cost model, so differences are attributable. Signals, holding rules and the s-score settings come from `config/backtest.toml`; the configurations run and the cost model come from a new `config/costs.toml`.
  - *The baseline,* as the phase 2 review sets it: residual reversal, *n* = 1, not volatility-scaled, *k* = 5, filled at the open of *t+1*. Break-even 3.66 bps one-way under the flat cost.
  - *The three-day lookback,* the same with *n* = 3, adopted here as a comparison and said so: phase 2 found it earns more than one day at every holding period, but it was picked from 147 trials after seeing them. Its path without the zone is one of phase 2's 147 trials and is not counted again; its no-trade path is a new trial.
  - *The s-score rule,* beside them, unchanged.
  - All at the open of *t+1*, the best fill in phase 2.
- **Returns per dollar of capital.** Phase 2 reported returns per dollar of gross exposure, so the size of the book did not matter. Here costs depend on dollars, so each book has a capital in US dollars and weights are fractions of it; returns are per dollar of capital, with idle capital earning nothing. A decile book deploys its capital less where its *k* slices offset each other; a book under the no-trade zone deploys only what passes the rule and is not scaled up; the s-score book deploys whatever its open positions and hedges add up to. The report shows the capital deployed beside every result.
- **Book sizes** $50k, $500k, $5m, $50m and $500m. Capacity is where net return turns down as size grows.
- **Every cost input from the day before the fill.** The cost of a fill at grid time *s* uses spread, volatility and volume known by the close before *s*, so the same estimate could have decided the trade. The fill price itself is used only to count shares for the commission. A look-ahead test perturbs data after a day and requires the costs up to it to stay the same.
- **Trials.** A trial is still a distinct position path. The cost model and the book size change P&L, not positions, so neither is a separate trial; every setting is still logged and reported. A no-trade path is one trial per decile configuration: its positions depend on the book size, but it is one rule tried once. Each phase's report counts the logs up to its own phase, so a later phase's trials do not change an earlier report on a rerun.
- **What phase 2 leaves to this phase:** survivorship flatters the long side (phase 0), unmeasured here; the dependency-upgrade criterion is still untested.

## Cost model components

- **Spread.** Free daily data has no quotes. Estimate the effective spread from daily prices with the published estimators: Ardia, Guidotti and Kroencke (2024, "EDGE", from open, high, low and close), Abdi and Ranaldo (2017, from close, high and low) and Corwin and Schultz (2012, from high and low). Pay half the spread per dollar traded, and never less than half a cent over the previous close, since no stock trades inside its one-cent tick.

  **Check before trusting them.** Each estimator reads negative serial covariance of prices as bid-ask bounce, and daily reversal, the effect this strategy trades, is negative serial covariance. Before any estimate is charged, test on simulated prices with a known spread whether the estimate moves with reversal or with a noisy open that the spread does not explain, and check the real estimates against a name whose spread is known to be a fraction of a basis point, SPY. If what they measure depends on the strategy's own signal, they cannot price it: the spread then becomes a stated assumption with a bracket run beside it, recorded in a decision record, and the estimators are reported as diagnostics and run once each as a sensitivity.
- **Market impact.** Square-root model: impact ≈ *c* · σ · √(dollars traded / average daily dollar volume), with σ the trailing 60-day volatility of daily returns and dollar volume averaged over 20 days. *c* = 1, the conservative end of the usual range, with 0.5 as a sensitivity. Daily volume overstates the liquidity in the opening auction, so the capacity found is an upper bound for open fills.
- **Commission.** Interactive Brokers' published US stock schedule, read from its own page and stored in `config/costs.toml` with the date it was read: IBKR Pro Fixed as the headline, since its per-share rate includes exchange and clearing fees, and IBKR Pro Tiered as a lower bound, since it leaves them out. One order per name per day. The per-order minimum matters for small books: a $50k decile book trades a few hundred dollars per name, so a $1 minimum is tens of basis points. Report commission per dollar traded at each book size.
- **Borrow.** A flat general-collateral rate (0.5% a year, as phase 2) plus a higher rate for a hard-to-borrow bucket. Free data does not say which names are hard to borrow, and size cannot be the proxy in a universe of the 300 most-traded stocks, so the proxy is high trailing volatility: the top 5% of stocks each day, at 5% a year. Both rates are assumptions and the report says so.

## No-trade zone

A variant of each decile configuration that trades a name only when its expected move pays for the trade:

- **Expected move.** Calibrate the signal to return units: regress the move over the next *k* days on the signal, pooled over members and a trailing window of signal dates, both demeaned across members each day, using only pairs whose outcome is known by the close of *t*. Phase 4 needs the same calibration for its expected returns, so it lives in `statarb.signals.calibration`, behind no interface of its own until phase 4 is the second user.
- **Rule.** Each day, start from the baseline's target book. A new position opens only if its expected move exceeds the estimated round-trip cost. An existing position is resized only if the expected move exceeds the one-way cost of that trade. Exits and changes of side always trade, so the holding rule and the long-short split stay close to the baseline's. Costs are estimated at the previous close, since the fill price is not known when the order is sent.
- **Where it sits.** An optional policy the engine applies at each fill, seeing the drifted holdings and the target; without one the engine behaves exactly as in phase 2.
- Report the turnover, the capital deployed, the net dollar imbalance it leaves and net Sharpe, against the baseline at each book size.

## Judging the result

A configuration earns a net edge at a book size only if both hold:

- the mean net return has a t-statistic of at least 2; and
- its deflated Sharpe probability is at least 0.95, against every position path in the repository's experiment logs up to this phase, with the benchmark from the variance of the paths' gross Sharpes, as in phase 2.

Anything short of this is reported as "not distinguishable from zero", whatever its sign.

## Deliverables

1. `src/statarb/backtest/costs.py`: the components behind the existing `CostModel` interface, which already sees the gross exposure; `FlatCost` and phase 2's report unchanged. The spread estimators in their own module, and the calibration in `statarb.signals.calibration`.
2. A runner, `statarb.backtest.cost_run`, and `config/costs.toml`, read into frozen dataclasses that reject unknown or missing keys.
3. `reports/phase-03/`, with every run logged in `experiments.jsonl` through the config overlay and `run_state`:
   - net P&L of each configuration under the new model at each book size, with the book size at which net Sharpe changes sign
   - cost breakdown by component, and cost per dollar traded by component and book size
   - the spread estimators by year and size group, how often a stock's own estimate is negative, and what the independence check found
   - the no-trade-zone variant against the baseline
   - sensitivity of the conclusion to the spread, the impact coefficient and the commission schedule
   - each configuration and book size judged against the bar above
4. Tests: each cost component on hand-checkable inputs; each spread estimator on simulated prices with a known spread, and its response to reversal and to a noisy open; the calibration using only known outcomes; the no-trade rule case by case; look-ahead for the cost inputs and the no-trade zone; strict config keys; exact reproduction.
5. Documentation: architecture, data model (no stored table; the log's new fields), time discipline (the cost inputs, the commission's share count, the expected move and the no-trade decision), glossary and requirements, in the same change as the code.

## Acceptance criteria

- The baseline from phase 2 is re-run unchanged except for the cost model, so differences are attributable.
- The report states the book size at which net Sharpe falls below zero.
- The report states, for each configuration and book size, whether it clears the bar in "Judging the result".
- The report says which cost component binds a retail-sized book.
- Phase 2's report rebuilds byte for byte after this phase's changes.
- Every log entry records its `run_state`, and the committed log comes from a clean tree.

## Out of scope

New signals. Optimisation beyond the simple no-trade zone. A new data source for spreads or borrow, which needs a decision record of its own.

## Review questions

- Which cost component matters most for this strategy, and which binds a retail-sized book?
- What does the capacity curve say about why Quadrature returned outside capital?
- Is there any book size at which a retail trader keeps a positive net edge?
- How much does the conclusion depend on the spread, and can the daily-price estimators be trusted to measure it?
