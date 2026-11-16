# 0005: The spread is a stated assumption, not an estimate

**Date:** 2026-11-16
**Status:** accepted

## Context

The phase 3 brief prices the bid-ask spread with estimators that need only daily prices, since free daily data has no quotes: EDGE (Ardia, Guidotti and Kroencke 2024), Abdi and Ranaldo (2017) and Corwin and Schultz (2012). It also asks for a check before any estimate is charged. Each estimator reads negative serial covariance of prices as bid-ask bounce, and daily reversal, the effect this strategy trades, is negative serial covariance too. If the estimators cannot tell the two apart, a cost model built on them charges the strategy for its own signal.

The check has three parts, all in `reports/phase-03/costs.md` (section "Spread") and the tests in `tests/test_spreads.py`:

- **Simulated prices with a known spread.** Each estimator recovers a large known spread on prices with no other structure. Adding reversal to the same prices, with the spread unchanged, raises every estimator's estimate, and the more reversal the higher the estimate; Abdi-Ranaldo moves most. Adding noise to the opening print raises EDGE, the only one of the three that reads the open.
- **A name whose spread is known.** SPY's quoted spread is a fraction of a basis point. Its own trailing-year estimates are tens of basis points from EDGE and Abdi-Ranaldo in most years, several times the published effective spread of the average S&P 500 stock, and Corwin-Schultz's yearly median for it is negative in most years.
- **Sign.** A large share of per-name, per-day estimates are negative, which a spread cannot be.

So what the estimators measure depends on the strategy's own signal and on noise in the open, and on these prices they cannot price the strategy's trades.

## Decision

1. **The headline half-spread is a stated assumption:** 1.5 bps one-way per dollar traded, for every stock and day, never less than half a cent over the previous close (`config/costs.toml`, `[spread]`). Its anchor is Hagströmer's measurement of the effective spread of S&P 500 constituents from trade and quote data ("Bias in the Effective Bid-Ask Spread", version of 25 September 2019, [HEC Paris](https://www.hec.edu/sites/default/files/documents/overestEspr-v12.pdf)): a dollar-volume-weighted average round-trip effective spread of about 2.7 bps measured against the micro-price and about 3.2 bps against the midpoint, so 1.4 to 1.6 bps one-way. The sample is one week of December 2015, and the universe here is the 300 most-traded stocks rather than the whole index, so the number is a reference point, not a measurement of this book.
2. **A bracket is run beside it:** 1.0, 2.5 and 5.0 bps one-way, each reported as a sensitivity at every book size.
3. **The estimators stay as diagnostics.** The report shows them by year and size group, SPY's own estimates and the share that are negative, and runs each once as a sensitivity, pooled by size group. None is charged in a headline result.
4. **The tests keep the evidence:** each estimator on simulated prices with a known spread, with reversal and with a noisy open, in `tests/test_spreads.py`.

## Consequences

- The conclusion's dependence on the spread is read from the sensitivity table, not hidden in an estimate. A result that holds at 1.0 bps and fails at 2.5 bps is reported as depending on the assumption.
- The headline spread does not vary by name, size or year, so it understates costs in the smaller names of the universe and in stressed markets such as 2020, and overstates them in the largest names. The half-tick floor is the only part that varies by stock.
- Phase 6 reuses this cost model for simulated fills, so the assumption carries into the paper-trading run.
- A measured effective spread per stock would replace the assumption. Free trade and quote data is not available, so the backlog item "Measured effective spreads" names the route: a public source of measured spreads, with its terms read and a decision record before it is used.
