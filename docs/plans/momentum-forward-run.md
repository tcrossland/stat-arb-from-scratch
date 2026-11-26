# Momentum forward run

Status: in progress, 2026-11-25. Stages 1 and 2 merged (pull requests 31 and 32); stage 3, the job, built, and its backtest logged and frozen on 2026-11-26; stage 4 next.

## Purpose

A second forward run, cross-sectional momentum, beside the reversal run of [decision record 0007](../decisions/0007-forward-run.md), on the same sessions and the same data: first session 2026-11-16, last 2027-01-13. It tests whether the momentum pipeline, run one session at a time, matches its backtest, and gives the two strategies' daily returns on identical sessions, the input the backlog's "Combining strategies" needs. It says little about momentum's return: about two holding cycles fit in 40 sessions. [Decision record 0010](../decisions/0010-momentum-forward-run.md) fixes it.

## Constraints

- **Reversal's run is untouched.** No change to the files its frozen record hashes (`FILES` in `statarb.paper.frozen`), to `config/paper.toml`, or to anything that moves log entry `b56df718a846aa4f`. The job's clone is pulled only deliberately, with the reproduction check.
- **Configuration before computation.** Record 0010 lands before any momentum value is computed on real data, and no setting changes after its development backtest is seen.
- **Same bars as reversal.** The momentum job never downloads. Each session is processed from the snapshot named for its run day, the one the reversal job took.
- **Alpaca's data.** MarketParquet's archive ends at 2026-11-19 for this account (its API refused 2026-11-20 on, checked 2026-11-25), so the run is on the frozen universe, not phase 7's `listed` universe.

## Design

- **Signals** in `statarb.signals.momentum`, behind `Signal`: total-return momentum and residual momentum on Model A's residuals, 252 days ending 21 days before the decision.
- **Rule:** the decile sort at 10% a leg, held 21 days in overlapping slices (`holding_slices` in `statarb.backtest.rules`), $5m, filled at the next open, under the phase 3 cost model with borrow. Two paths, two ledgers.
- **Config:** `config/momentum_forward.toml`, outside the frozen record's files, one entry per path with its paper directory, notes directory and backup variable.
- **Paper package:** `Strategy` learns a forecast that is a registered signal with its own holding period and decile; reversal's branches stay as they are. A frozen record and a reproduction check per path, against its own entry in `reports/phase-08/experiments.jsonl`.
- **Job:** an entry point that runs after reversal's job, at 13:45 CET, reads the run day's snapshot, processes nothing when there is none, and has its own lock, ledger, run log, notes (`reports/phase-08/forward/daily/`) and backup repository.

## Steps

1. **The record and the brief** (docs only, first). Record 0010, its line in the index, and the phase 8 brief revised: the run moves into scope ahead of the rest of the phase, and its job is excepted from "No day from 2026-11-16 on". Done when merged, before any momentum value on real data.
2. **The signals** on synthetic data, with the look-ahead contract in both forms and a test of the skipped 21 days. Done when `uv run pytest` passes and no real data was read.
   - Built 2026-11-25 (pull request 32). Registered as `momentum` and `residual_momentum`, and not in `DECILE_SIGNALS`, since the phase 2 sweep passes `lookback_days`. A −100% return scores −1; a return below −100% counts as missing. A score needs every day of its window, as reversal's does, so a missing bar removes a stock for 252 sessions.
   - Beyond the step: phase 7's delisted-suffix test on both signals, and their rows and notes in `docs/time-discipline.md`.
3. **The second strategy** in the paper package, the backtest runner cut at 2026-11-15 and its two logged paths, the frozen records, the job, and `tests/test_forward_holdout.py` extended. Reference docs current in the same change. Done when reversal's frozen check still gives `254f4de9d1902403`, its reproduction still gives `b56df718a846aa4f`, and the job's tests on synthetic fixtures cover catch-up, a missing snapshot and a refused config.
   - Load the job's and the backtest's tables from the same first date: rolling sums carry rounding of about 1e-16 from rows that have left the window, and the reproduction check is exact.
4. **The start.** The owner creates the backup repository and its key; the clone is pulled the deliberate way and checked; each past run day is processed in order with `--now` from its snapshot; the owner loads the 13:45 agent. Done when both ledgers hold the same sessions, each momentum day's snapshot matches reversal's, and reversal's next daily check passes.

## Out of scope

- Momentum on the `listed` universe, reversal's unread years, the optimiser paths and the sensitivities: phase 8 proper.
- MarketParquet's subscription for new sessions, and any forward run on its data: a decision of its own under record 0008.
- A drift report for momentum: deferred, with its trigger at the first weekly pull request that carries momentum's notes.
- Combining the two strategies.
