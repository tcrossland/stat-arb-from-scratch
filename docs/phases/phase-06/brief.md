# Phase 6: Paper-trading simulation

Drafted at setup, and revised at the start of the phase with what earlier phases found.

## Goal

Run the chosen strategy forward in time on new data each day, with no real orders, and compare what happens with what the backtest predicted.

## Design

- A daily job after the US close that:
  1. downloads the latest day's data and appends it to the store
  2. updates factor exposures, residuals and features
  3. produces forecasts and target weights from the frozen model
  4. simulates fills at the next close using the phase 3 cost model
  5. writes trades, positions and P&L to an append-only ledger (`data/paper/ledger.parquet`) and a short daily markdown note
- The model and all parameters are frozen at the start of the phase and recorded in `docs/decisions/`. Retraining is a new decision, not a silent update.
- The job must be idempotent: running it twice for the same date changes nothing.
- Scheduling with launchd or cron. Missed days are caught up in order.

## Deliverables

1. `src/statarb/paper/` with the daily loop and ledger.
2. A weekly drift report in `reports/phase-06/`: live P&L versus the backtest's expected distribution, live turnover and costs versus modelled, data issues encountered.
3. Tests: idempotency, catch-up after missed days, ledger integrity checks.

## Acceptance criteria

- At least eight weeks of uninterrupted forward running.
- The drift report states whether live results sit within the backtest's expected range.

## Optional extension

Connect an Interactive Brokers **paper** account to compare simulated fills with IBKR's paper fills. Requires a decision record first. No live account, ever, without a separate decision.

## Review questions

- Did live performance fall inside the backtest's expected range? If not, which assumption broke?
- What operational problems appeared that a backtest never shows?
- What would it take to move to intraday data, and is it worth it?
