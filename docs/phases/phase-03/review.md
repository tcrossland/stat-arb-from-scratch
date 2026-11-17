# Phase 3 review: Cost realism

Written on 2026-11-16 at the end of the phase. The numbers below are quoted from the generated report, [`reports/phase-03/costs.md`](../../../reports/phase-03/costs.md), and its log, [`reports/phase-03/experiments.jsonl`](../../../reports/phase-03/experiments.jsonl), built from the phase 0 and 1 tables of the pinned snapshot with no new download. Every configuration is filled at the open of *t+1*, from 2017-01-03 to 2026-11-13, with returns per dollar of capital. Unless a line says otherwise, a number is under the headline cost model: a half-spread of 1.5 bps, square-root impact with *c* = 1, IBKR Pro Fixed commission and borrow at 0.5% a year, 5% for the most volatile stocks. Phase 6 opened with a fix to the raw reversal signal and the s-score, which moved some numbers quoted below by a little; [the phase 6 review](../phase-06/review.md#the-signal-fix) lists them, and the report holds the current values.

## What was built

- **`src/statarb/backtest/costs.py`**: `TradingCost`, a second implementation of the `CostModel` interface, charging a half-spread with a half-tick floor, square-root impact and a per-share commission with a per-order minimum and maximum; the cost inputs, each from the day before the fill; borrow rates with a hard-to-borrow bucket; and the no-trade zone. `FlatCost` and phase 2's report are unchanged.
- **`src/statarb/backtest/spreads.py`**: the EDGE, Abdi-Ranaldo and Corwin-Schultz estimators, written from their papers, with `statarb.testing.prices` to simulate prices with a known spread, reversal and a noisy open.
- **`src/statarb/signals/calibration.py`**: the signal in return units, from a trailing pooled regression on outcomes known by the decision date. Phase 4 reuses it.
- **The engine** takes an optional `Policy` at each fill, seeing the drifted holdings and the target; without one it is phase 2's engine.
- **The runner** `statarb.backtest.cost_run` and its report, from `config/costs.toml`, read into frozen dataclasses that reject unknown or missing keys. The modules are in [the architecture](../../architecture.md); the log's new fields are in [the data model](../../data-model.md#experiment-logs).
- **Tests**: each cost component by hand; the commission's minimum and maximum; inputs from the day before; each estimator on simulated prices, with reversal and a noisy open; the calibration; the no-trade zone case by case; look-ahead for the spread, volatility, expected move, holdings and daily costs; strict config keys; exact reproduction; a byte-identical report; the trial count up to each phase.

The choices the drafted brief left open are settled in [its revision](brief.md#revised-at-the-start-of-the-phase), and the spread in [decision record 0005](../../decisions/0005-spread-as-a-stated-assumption.md). No library was added.

## Acceptance criteria

| Criterion | Result |
|---|---|
| The baseline from phase 2 is re-run unchanged except for the cost model | Met: the signals, holding rules and s-score settings come from `config/backtest.toml` through phase 2's own functions, and `test_engine_without_a_policy_is_phase_2s` checks the engine without a policy against phase 2's. |
| The report states the book size at which net Sharpe falls below zero | Met: the list under "Net results by book size", for each configuration with and without the no-trade zone. |
| The report states, for each configuration and book size, whether it clears the bar | Met: "Judging the result". None of the 25 pairs clears it. |
| The report says which cost component binds a retail-sized book | Met: the `binding` column of "Cost per dollar traded". Commission, at $50k and $500k, for every configuration. |
| Phase 2's report rebuilds byte for byte after this phase's changes | Met: `statarb.backtest.run --no-log` on this phase's code rewrote `reports/phase-02/` with no change. |
| Every log entry records its `run_state`, and the committed log comes from a clean tree | Met: all 145 entries name commit `7d1f24c` with no uncommitted changes, no overlay, and the Alpaca snapshot of 2026-11-16. |

## What the numbers showed

- **No configuration keeps a net edge at any book size.** The baseline's gross return is 3.60% a year of capital and its net Sharpe is negative at every book size, from −9.08 at $50k to −0.11 at its best, $5m. The three-day lookback is positive only at $5m, 0.28 with a t-statistic of 0.86; the s-score rule is negative at every size.
- **Commission binds a retail book.** At $50k the baseline pays 54.49 bps of commission per dollar traded against 1.60 of spread and 0.16 of impact, and loses 46.14% a year. At $500k commission is still the largest component, 6.56 bps. The per-order minimum of $1 does this: a $50k decile book trades a few hundred dollars per name.
- **Impact binds an institutional book.** From $50m impact is the largest component for every configuration, 4.92 bps per dollar traded for the baseline at $50m and 15.55 at $500m. Spread is the largest only at $5m for the two decile books, where the total is lowest, 4.38 bps for the baseline. That is still above the baseline's phase 2 break-even of 3.66 bps.
- **The capacity curve peaks at $5m.** Net Sharpe of each decile book rises from $50k to $5m as commission per dollar falls, then falls as impact rises with the square root of the dollars traded.
- **The no-trade zone turns every decile book's net Sharpe positive up to $50m, and none is significant.** The three-day lookback with the zone reaches 0.54 at $5m, a t-statistic of 1.69 and a deflated Sharpe probability of 0.621 against a benchmark Sharpe of 0.44 from 149 trials. At $50k the baseline's zone deploys 0.01 of its capital and holds a median of no names; its positive Sharpe comes from almost not trading.
- **The zone gives up neutrality.** It keeps only the trades that pay, so long and short sides no longer match: the baseline's mean net dollar imbalance is 0.26 of gross at $500k and 0.72 at $50k, against none without the zone.
- **Spread sensitivity.** Moving the assumed half-spread from 1 to 5 bps moves the baseline's net Sharpe at $5m from −0.04 to −0.70 and the three-day lookback's from 0.33 to −0.12. No verdict changes across the bracket.
- **Commission schedule.** IBKR Pro Tiered, which leaves out exchange and clearing fees, lifts the $50k baseline from −9.08 to −2.99 and the s-score at $500k from −0.20 to −0.03, still negative.
- **Borrow is small.** 0.31% a year of capital for the baseline, 0.46% for the three-day lookback and 0.53% for the s-score, about half of it the hard-to-borrow extra in the decile books.
- **The s-score trades in larger orders.** With fewer, larger positions its commission per dollar at $500k is 1.78 bps against the baseline's 6.56, so it loses least of the three at retail sizes, and most at $500m, where its larger orders pay more impact.

## Comparison with De Groot, Huij and Zhou (2012)

Added on 2026-11-17, after phase 4. Figures are from the working paper presented at the 2011 EFMA annual meeting; the published version (*Journal of Banking and Finance* 36(2), 371 to 382) may differ.

| | De Groot et al. | This project |
|---|---|---|
| Sample | 1990 to 2009 | 2017-01 to 2026-11 |
| Universe | The 1,500, 500 and 100 largest US stocks in the Citigroup Broad Market Index | The 300 most-traded current S&P 500 members |
| Signal | Raw return over the past five days, one day skipped, rebalanced daily | Residual over one day (baseline) or three days, five daily slices, filled at the open of *t+1* |
| Portfolio | Top and bottom quintiles, equal weight, each leg measured against the universe's equal-weighted return | Top and bottom deciles, equal weight, dollar neutral |
| Costs | Nomura Securities estimates by dollar-volume decile, for $1 million per stock by 2009 and including a 3 bps commission in the 2000s; Keim and Madhavan (1997) as a second model | 1.5 bps half-spread ([decision record 0005](../../decisions/0005-spread-as-a-stated-assumption.md)), IBKR per-share commission with a minimum, square-root impact |
| Lower-turnover rule | Keep a loser (winner) until it ranks in the top (bottom) half, then replace it | The no-trade zone |

Their weekly long-short returns are per dollar long plus a dollar short, so half of one, times 52, is a yearly return per dollar of gross. Their weekly turnover in per cent, divided by 1,000, is turnover per dollar of gross per day as phase 2 measures it: their maximum is 400% a day, ours 2.0.

- **The cost levels agree.** For the 500 largest stocks, Nomura's single-trip cost averages 6 bps in the most liquid tenth and 25 bps in the least, and 4 to 5 bps in the most liquid tenth from 2007 to 2009 (their Table 2). Our headline model costs 4.3 to 8.8 bps per dollar traded between $500k and $50m.
- **Their gross edge was about twice ours.** The standard strategy on the 500 largest earned 71.9 bps a week gross over 1990 to 2009, about 19% a year per dollar of gross (Table 4). Over 2000 to 2009, their lower-turnover version earned 53.0 bps a week, about 14% (Table 8). The closest phase 2 configuration, raw *n* = 5, *k* = 1, earned 9.25% a year per dollar of gross over 2017 to 2026.
- **Their net edge for the 500 largest was already fading.** Net of Nomura costs, the lower-turnover strategy earned 30.5 bps a week over the full sample (Table 5) and 22.1 bps over 2000 to 2009, with a t-statistic of 1.7 (Table 8). The 100 largest held up: 53.1 bps over the full sample, 59.0 bps over 2000 to 2009 (t 4.1). They read this as stable profits; for the 500 largest it is a fall below significance. Our universe sits between the two, and over 2017 to 2026 no configuration has a net edge.
- **Trading less helps in both, and costs little gross return.** Their rule halves turnover on the 500 largest (from 0.69 to 0.33 of gross a day), loses a tenth of the gross return (71.9 to 65.0 bps a week) and turns net from −3.0 to 30.5 bps a week (Tables 4 and 5). Wider bands did better still: 35.3 bps a week when selling only past the 70th percentile (Table 9). For the three-day lookback at $5m, our no-trade zone cuts turnover per dollar of capital from 0.35 to 0.19 and raises gross Sharpe from 0.84 to 0.96. The reasoning is the same: replacing a position pays only if the gain in expected return covers the round trip. They work it through on their page 19: losers earn about 6 bps the next day against 1 bp for the next quintile, and stay losers for about three days, so a swap pays only below about 15 bps round trip.
- **Holding for five days lost gross return for them, and for raw reversal here.** On the 1,500 largest, rebalancing every fifth day cut gross from 61.7 to 41.2 bps a week (Tables 4 and 7). Here five-day slices cut raw *n* = 5 from 9.25% to 6.27% a year per dollar of gross, but raise the one-day residual signal from 3.42% to 5.40% (phase 2 report). Slices are a different construction: a fifth of the book is refreshed every day, where their rule refreshes all of it every fifth day.

Their result has no counterpart to our main cost finding. Their commission is a percentage of value with no minimum per order, while for our books below about $5m the per-order minimum is the largest cost. They also assume, as we do, no premium for providing liquidity, while noting that reversal trades lean against order flow and may cost less than their estimates.

## What surprised us

- **The spread estimators measure the strategy's own signal.** Each estimator reads negative serial covariance as bid-ask bounce, and reversal is negative serial covariance. On simulated prices with a true round-trip spread of 2 bps, every estimator reads 0.0 with no reversal and rises with it: at a reversal of 0.2, EDGE reads 10.4 bps, Abdi-Ranaldo 68.0 and Corwin-Schultz 17.8. A noisy open inflates EDGE alone, to 28.1 bps at 20 bps of noise. On the real data SPY, whose quoted spread is a fraction of a basis point, has an EDGE estimate between 14.3 and 103.2 bps by year, and 37% of EDGE's per-name, per-day estimates are negative. Charged as costs, the estimates would have made every book look worse in proportion to how much it reverses (the `edge estimate` and `ar estimate` rows of the sensitivity tables), pricing the signal as a cost. [Decision record 0005](../../decisions/0005-spread-as-a-stated-assumption.md) makes the spread a stated assumption, anchored on a published measurement of S&P 500 effective spreads, with a bracket.
- **Commission, not spread, binds a retail book.** The brief expected the per-order minimum to matter for small books. It dominates: at $50k commission is 34 times the spread per dollar traded, and switching to a schedule with a lower minimum moves net Sharpe more than any spread in the bracket. A retail decile book of a few hundred names is mostly paying the minimum. The fix is fewer, larger orders, which is what the s-score and the no-trade zone do and what phase 4's minimum trade size controls.
- **The best net result comes from trading less, not from a better signal.** The no-trade zone leaves each book's gross Sharpe close to the book's without it and cuts turnover to a fraction, but at the edges of the size range it does so by holding almost nothing, and everywhere by leaving the book unbalanced.

## Review questions

**Which cost component matters most for this strategy, and which binds a retail-sized book?** Commission binds a retail book, at $50k and $500k, for every configuration. Impact binds from $50m. Spread is the largest component only around $5m for the decile books, where costs are lowest and still above the break-even.

**What does the capacity curve say about why Quadrature returned outside capital?** The curve shows a mechanism, not any firm's reasons. A strategy whose gross edge is a few basis points per dollar traded has its best net Sharpe at a modest size: here $5m, with impact four times the phase 2 break-even by $500m. Past that point more capital lowers the return on all of it. Whether that is why Quadrature returned outside capital this phase cannot say.

**Is there any book size at which a retail trader keeps a positive net edge?** No. Without the zone every configuration loses at $50k and $500k. With the zone the decile books are positive, but none clears the bar, and at $50k the zone holds a median of no names.

**How much does the conclusion depend on the spread, and can the daily-price estimators be trusted to measure it?** Little within the bracket: no verdict changes from 1 to 5 bps, though the three-day lookback's net Sharpe at $5m changes sign at 5 bps. The estimators cannot be trusted on this strategy: they rise with the reversal it trades.

**How many configurations were tried, and does the three-day lookback count?** 149 position paths across the repository's logs up to this phase: phase 2's 147, and the two no-trade paths added here. The three-day lookback was adopted from phase 2's results after seeing them, as phase 2 warned; its path without the zone is one of phase 2's 147 and is not counted again, and its no-trade path is one of the two new trials. Book sizes and cost settings change P&L, not positions, so they are logged, 145 entries, and not counted.

## Lessons this phase built in

Four rows added to [`docs/lessons.md`](../../lessons.md). Two have their episodes above: a cost estimated from prices is checked against the strategy's own signal before it is charged, and commission is reported per dollar traded at each book size, since a per-order minimum, not the spread, binds a retail book. The others are rules built in with a test from the start: every cost input on a fill comes from the day before it, and a result is shown with the capital it deploys.

## Reference docs

Confirmed current in this change: [architecture](../../architecture.md) (the cost, spread and calibration modules, the `Policy` seam, the runner, `config/costs.toml`), [data model](../../data-model.md) (no stored table; the log's new fields and the trial definition), [time discipline](../../time-discipline.md) (phase 3 rows and notes), [glossary](../../glossary.md), [requirements](../../requirements.md) (the runner, measured on 2026-11-16), [reproducing the results](../../reproduce.md) (step 4), the [overview](../../overview.md) (the costs stage), the [roadmap](../../roadmap.md) (EDGE and the spread anchor) and the decision record index (0005).

## Backlog walk

- **An independent short-term reversal series:** trigger the phase 3 review, arrived. It needs a new data source, a terms check and a decision record before any download, and phase 3 adds no data source and leaves gross P&L unchanged. Kept, with the trigger moved to the phase 4 review.
- **Measured effective spreads:** added this phase with decision record 0005; trigger the phase 4 review.
- **Multi-period optimiser:** kept; trigger the phase 4 review. The no-trade zone's result, net Sharpe from trading less, is the case it addresses.
- **A second price source for cross-checking:** kept; trigger the phase 5 review.
- **Documentation site:** kept; trigger when the repository goes public.

## What carries forward

- **To phase 4:** the cost model for the optimiser's κ term, with the spread as assumed in decision record 0005; the calibration in `statarb.signals.calibration` for expected returns; the capacity peak around $5m, which sets the book size worth optimising for. The no-trade zone's imbalance is what phase 4's neutrality constraints are for, and the commission minimum is what its minimum trade size is for.
- **The open fill.** Daily volume overstates the opening auction's liquidity, so impact at the open is a lower bound and the capacity found an upper bound.
- **Survivorship** stays as stated in phase 0, unmeasured.
- **The dependency-upgrade criterion** from phase 0 is still untested: no upgrade has happened.
