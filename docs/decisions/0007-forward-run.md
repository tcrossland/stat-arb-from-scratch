# 0007: The forward run: its strategy, first session and schedule

**Date:** 2026-11-17
**Status:** proposed

## Context

Phase 6 built the paper-trading package and the evidence for choosing what it trades, and started no forward run ([phase 6 review](../phases/phase-06/review.md)). Until a decision fills `[frozen]` and `[run]` in `config/paper.toml`, the daily job and the drift report refuse to run. The backlog item "Forward run" lists what this record must settle.

No path in any phase clears the deflated-Sharpe bar, so the forward run does not test a strategy expected to earn. It tests whether the pipeline, run one session at a time on data downloaded each day, behaves like its backtest. The choice is which pipeline to test. The phase 6 review gives two considerations, both measured on years phase 5 had already read:

- prefer a forecast whose lead survives the fill;
- prefer a rule that does not depend on the sign of the calibration slope. A negative trailing slope reverses every expected move, so the optimiser then bets on continuation.

The phase 5 holdout has been read. Results from the forward run are the only out-of-sample evidence the project can still produce.

## Decision

1. **The choice rule.** The frozen strategy is the choice path with the highest development net Sharpe among those that never bet on continuation: a floored or expanding slope, or the decile sort, which ignores the slope. The evidence is the development section of [`reports/phase-06/choice.md`](../../reports/phase-06/choice.md) and its log. The rule reads no holdout or forward data.
2. **The frozen strategy.** The rule picks:
   - forecast: the three-day lookback;
   - rule: the optimiser at κ = 1;
   - slope: floored;
   - book: $5m.

   This is the choice path with config id `b56df718a846aa4f` in `reports/phase-06/experiments.jsonl`. Its development metrics are in `choice.md`; it does not clear the bar. The forecast is a variant of `config/costs.toml`, so no model files are frozen. `[frozen]` in `config/paper.toml` holds these values, and `reports/phase-06/frozen-config.json`, written once by `statarb.paper.frozen --write`, pins them with the rest of the configuration by its hash.
3. **The first session is 2026-11-16.** The book starts flat, the first decision is made at the close of 2026-11-16, and its first fill is at the open of 2026-11-17. This record is written after the closes of 2026-11-16 and 2026-11-17. The project downloaded no data for either session before it, but a reader cannot check that the choice was blind to them. So every result the forward run reports is also given from 2026-11-18, the first session after this record, and the review says if the two differ. The first run processes these sessions together from one snapshot taken after them, so they do not test the daily data path the way later sessions do.
4. **The forward days are a fresh holdout,** from 2026-11-16 to the last session of the run. Only the daily job and the drift report read them.
   - The phase 2, 3 and 4 runners cut every table at the day before the first session, so on a snapshot taken during or after the run they never read a forward day.
   - The phase 5 runners and the choice already cut at the phase 5 holdout's last day, 2026-11-13. A test requires that day to come before the first session.
   - The data build and the phase 0 and 1 reports describe the data, not a strategy, and are not cut.

   This guard lands with this record, with its tests (`tests/test_forward_holdout.py`).
5. **The run and its schedule.**
   - **Run time:** `[run] run_time` stays 06:00 New York. A session is processed from 06:00 New York on the day after it.
   - **Daily job:** launchd starts `statarb.paper.daily` every day at 13:15 Central European time. That is 07:15 New York for most of the year, and 08:15 in the weeks when the two change their clocks on different dates, so it is after the run time all year, with room for a host that is sometimes in London.
   - **Drift report:** `statarb.paper.drift` runs on Sundays at 14:15, when the daily job has nothing to process.
   - **Where it runs:** from a clone of the repository used for nothing else, on main at the merge of this record. The clone is updated only by a deliberate pull followed by a run that passes the reproduction check.
   - **Keys:** the Alpaca keys are read from the host's keychain by the scheduler's wrapper, never from the repository or config.

   [Running the daily job](../daily-job.md) gives the setup.
6. **The backup.** After each run, the ledger is copied to a private git repository. Its address is a setting of the host that runs the job, read from `STATARB_BACKUP_REMOTE` like the raw store's `STATARB_RAW`, so it is not committed. The repository and the key that can push to it are created by hand. The ledger holds fill prices, so it is never published.
7. **What is committed.**
   - **Committed:** the daily notes in `reports/phase-06/daily/` and the weekly drift reports in `reports/phase-06/drift/`, once a week in one pull request. They hold statistics of the simulated book, no per-ticker values.
   - **Not committed:** the ledger, the run log in `data/paper/runs.jsonl` and the daily snapshots stay in `data/`.
8. **Length.** At least eight weeks of uninterrupted running, about 40 sessions, as the phase 6 brief's acceptance criteria require. Then the phase 6 review is amended with the run's results and its review questions.
9. **Backlog items this record triggers.**
   - **Measured effective spreads:** deferred, with the trigger moved to the forward run's review.
   - **Closes from the listing exchange's closing auctions:** deferred, with the trigger moved to the forward run's review.

   The run tests whether the live pipeline matches its backtest, which needs the closes and the spread assumption the backtest used. Changing either first would mean rebuilding phases 0 to 6, and is a change of its own.

## Consequences

- The daily job refuses to run if the configuration differs from the frozen record, if the code no longer reproduces the frozen path's logged metrics, or if the ledger fails its checks. Any change to the strategy is a new decision record, not an update.
- The run exercises the optimiser, its risk model, the solver fallback and the cost model each day. It does not exercise the model files or their hash check, since the frozen forecast is not a model.
- Backlog work during the run uses development data only, and the backtest runners enforce it.
- The first two sessions are reported both ways, so a reader can discount them.
- `docs/requirements.md` gains the daily job's and the drift report's time, memory and disk from the first run that downloads.
- The backlog item "Forward run" is deleted: this record and [running the daily job](../daily-job.md) carry out its action. The two deferred items keep their titles, with new triggers.
