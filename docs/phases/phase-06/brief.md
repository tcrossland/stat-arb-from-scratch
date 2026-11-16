# Phase 6: Paper-trading simulation

Drafted at setup, and revised at the start of the phase with what earlier phases found.

## Goal

Run the chosen strategy forward in time on new data each day, with no real orders, and check that the live pipeline behaves like the backtest.

## Design

- A daily job after the US close that:
  1. downloads the latest day's data and appends it to the store
  2. updates factor exposures, residuals and features
  3. produces forecasts and target weights from the frozen model
  4. simulates fills at the fill timing used for the backtest headline (open of *t+1* unless a phase review changed it), using the phase 3 cost model
  5. writes that day's trades, positions and P&L to the ledger and a short daily markdown note in `reports/phase-06/daily/`
- The model and all parameters are frozen at the start of the phase and recorded in `docs/decisions/`. Retraining is a new decision, not a silent update.
- The job must be idempotent: running it twice for the same date changes nothing.
- If the optimiser is infeasible or the solver fails, hold the previous day's book, record the failure in the ledger and the daily note, and continue the next day. The phase 4 backtest applies the same rule, so live and backtest behave the same on bad days. Never relax constraints automatically to get a solution.
- Scheduling with launchd or cron. Missed days are caught up in order.

## What eight weeks can and cannot show

Eight weeks is about 40 trading days, far too few to tell the backtest Sharpe apart from zero. Simulated fills also reuse the phase 3 cost model, so a forward run cannot reveal that the cost model is wrong. What it can show is whether the live pipeline matches the backtest: data arrives and is processed correctly, signals and turnover look the same, and the forecast keeps its predictive power.

## Deliverables

1. `src/statarb/paper/` with the daily loop and ledger.
2. A weekly drift report in `reports/phase-06/`:
   - data revisions by the source after the fact, missing days and pipeline failures
   - live turnover versus the backtest distribution
   - live signal and forecast distributions versus the backtest
   - realised daily IC versus the backtest distribution
   - live P&L against a wide band from the backtest, as a sanity check only
3. Tests: idempotency, catch-up after missed days, ledger integrity checks, and the hold-previous-book fallback on a forced solver failure.

## Acceptance criteria

- At least eight weeks of uninterrupted forward running.
- The drift report states whether turnover, signal distributions and IC sit within the backtest's ranges, and whether P&L sits within the wide band.

## Optional extension

Connect an Interactive Brokers **paper** account to compare simulated fills with IBKR's paper fills. This is the only way this phase can test the cost model. Requires a decision record first. No live account, ever, without a separate decision.

## Review questions

- Did live behaviour (turnover, signals, IC) match the backtest? If not, which assumption broke?
- Which data revisions did the source make after the fact, and would they have changed any decision?
- What operational problems appeared that a backtest never shows?
- What would it take to move to intraday data, and is it worth it?
