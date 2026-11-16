# Phase 3: Cost realism

Drafted at setup, and revised at the start of the phase with what earlier phases found.

## Goal

Replace the flat cost assumption with a model that reflects how costs actually vary by stock, size and market conditions, then see how much of the baseline edge survives.

## Cost model components

- **Spread.** Free daily data has no quotes. Estimate the effective spread from daily high, low and close (for example the Corwin-Schultz or Abdi-Ranaldo estimators). Pay half the spread per trade.
- **Market impact.** Square-root model: impact ≈ *c* · σ · √(trade size / daily volume), with σ the daily volatility and *c* around 0.5 to 1 as a starting point. Run a notional book size sweep (for example $50k, $500k, $5m, $50m) to see where capacity runs out.
- **Commission.** Use a published retail broker schedule (for example Interactive Brokers tiered pricing) as a config entry.
- **Borrow.** Flat general-collateral rate for most names plus a higher rate for a "hard to borrow" bucket. Free data will not tell us which names are hard to borrow, so use a proxy (high short-term volatility, small size) and state it.

## Deliverables

1. `src/statarb/backtest/costs.py` implementing the components behind the existing cost interface.
2. `reports/phase-03/`:
   - baseline net P&L under the new model at each book size
   - cost breakdown by component
   - a no-trade-zone variant: only trade when the expected move exceeds the estimated cost, compared with the baseline
3. Tests for each cost component on hand-checkable inputs.

## Acceptance criteria

- The baseline from phase 2 is re-run unchanged except for the cost model, so differences are attributable.
- The report states the book size at which net Sharpe falls below zero.

## Out of scope

New signals. Optimisation beyond the simple no-trade zone.

## Review questions

- Which cost component matters most for this strategy?
- What does the capacity curve say about why Quadrature returned outside capital?
- Is there any book size at which a retail trader keeps a positive net edge?
