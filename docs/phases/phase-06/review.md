# Phase 6 review: Paper-trading simulation

Written on 2026-11-17 at the end of the build. The phase was built and not run, as its [revised brief](brief.md#built-now-run-later) sets out: no forward day has been processed, nothing was downloaded and no scheduler was set up. The numbers below are quoted from the generated report, [`reports/phase-06/choice.md`](../../../reports/phase-06/choice.md), and its log, [`reports/phase-06/experiments.jsonl`](../../../reports/phase-06/experiments.jsonl), built from the phase 0 and 1 tables of the pinned snapshot. Choice paths run from 2020-07-09, phase 5's first calibrated date, to 2025-11-13, the development end; the diagnostic paths and the slope tables run on through the holdout to 2026-11-13. Every path is filled at the open of *t+1*, with returns per dollar of capital and phase 3's headline cost model. "The optimiser" is phase 4's headline at κ = 1, and "the four forecasts" are phase 5's: the baseline, the three-day lookback, and the model at *H* = 1 and *H* = 3.

## What was built

- **The signal fix** (`7cecc3d`), in a commit of its own before anything else, as the [brief](brief.md#from-the-phase-5-backlog-walk) asks: the raw reversal signal and the s-score score, fit and centre only the stocks known on *t*. Every registered signal now passes the row-removal look-ahead test, and its two strict expected failures are gone. Phases 2 and 3 were logged again ([below](#the-signal-fix)).
- **`src/statarb/models/`** loads a saved model file only if it has its recorded SHA-256, and forecasts each day from the model of the latest walk-forward block that starts on or before it (`65c4d55`).
- **`src/statarb/backtest/trials.py`** counts a path's slope rule in its trial id unless it is trailing, so phase 5's paths keep their ids; diagnostic paths, and paths identical to their trailing version, add no trial (`d4414ed`).
- **`src/statarb/paper/`** (`91e0114`):
  - the evidence for the choice (`choice`, `report`), on development data;
  - the due sessions from the New York Stock Exchange calendar and New York's date and run time (`sessions`);
  - one engine step per session on tables cut at it, filling the decision recorded the day before, into one immutable parquet file per day with a hash chain (`day`, `loop`, `ledger`);
  - the frozen record, the reproduction check, the job's lock, refusals and run log, and the ledger's backup (`frozen`, `reproduce`, `daily`, `backup`);
  - the weekly drift report against the frozen path over development (`drift`).
- **Library:** exchange-calendars 4.13.3, Apache-2.0, with korean-lunar-calendar (MIT), pyluach (MIT) and toolz (BSD-3-Clause), each read from the package's own metadata. No existing pin moved.
- **One logged choice run** of 72 entries at `91e0114` on a clean tree, with no overlay and the snapshot of 2026-11-16: 56 choice paths and 16 diagnostic paths. Every phase 5 model was retrained and matched its logged SHA-256, and every trailing path gave phase 5's metrics exactly. A wording fix to the report (`154ef5c`) was rebuilt with `--no-log`, and its charts and log were byte-identical to the logged run's.
- **Tests:** 107 in eight `tests/test_paper_*.py` files, covering what the brief lists: a run of sessions gives the backtest's holdings, trades and P&L exactly for every rule, every slope rule and a model forecast from saved files; idempotency, catch-up and the weeks when US and European clock changes differ; ledger integrity and no partial day after a simulated crash; refusal on a model hash mismatch, a changed frozen config and a failed reproduction check, including a code change the frozen record cannot see; and the held book on a forced solver failure. The full suite has 521 tests.

## Acceptance criteria

The brief accepts the build, and leaves the forward run's criteria to the run.

| Criterion | Result |
|---|---|
| Every test the brief lists passes | Met: the tests above, in a suite of 521 that passes. |
| The evidence for the choice is logged | Met: 72 entries in `reports/phase-06/experiments.jsonl`, and `choice.md` built from them. |
| At least eight weeks of uninterrupted forward running | Not started: [decision record 0007](../../decisions/0007-forward-run.md) starts it from 2026-11-16. |
| The drift report states whether turnover, signals, IC and P&L sit within the backtest's ranges | Built and tested on synthetic sessions; it has nothing to report until the forward run starts. |

## What the numbers showed

- **The phase 5 reading of the model's gross holds for the *H* = 1 model, not for *H* = 3.** Phase 5 guessed that the model orders the middle of the cross-section, while a decile book earns in the tails. Over 2020-07-09 to 2025-11-13, the gap in mean realised 5-day residual move between the top and bottom deciles is 0.309% for the three-day lookback, 0.211% for the *H* = 3 model, 0.207% for the baseline and 0.123% for the *H* = 1 model ("Realised move by forecast decile"). The *H* = 1 model's bottom two deciles move up, not down (0.003% and 0.027%). The *H* = 3 model's gap is the baseline's, yet its decile sort earned less gross in phase 5, so the tails do not explain that one. Only the three-day lookback has its largest moves in its outer deciles at both ends.
- **Most of the baseline's one-day lead is overnight, where the book is not.** Its mean daily IC against total returns from the close of *t* to the open of *t+1* is 0.0177 (t 4.6); from the open of *t+1* to the open of *t+2*, where a book filled at the open holds it, 0.0043 (t 1.2). The models' one-day IC from the fill is 0.0006 (*H* = 1) and 0.0021 (*H* = 3). Over five days from the fill the three-day lookback leads, 0.0117 (t 3.2), then the baseline, 0.0097 (t 2.8); the models are 0.0045 and 0.0068, neither above t 1.7 ("IC by fill timing"). These are total-return ICs, comparable with each other and not with phase 5's residual ICs, and the t-statistics for five-day windows are overstated.
- **The slope rules change no verdict.** Flooring the slope at zero moves net Sharpe by at most 0.35 (the *H* = 1 model through the optimiser at $5m, −0.60 to −0.25) and lowers the three-day lookback's optimiser paths (0.37 to 0.31 at $5m). The expanding slope raises the zone's net Sharpe at six of eight forecast and book pairs, by up to 0.31, and lowers the phase 3 variants' optimiser paths at both books, since the optimiser trades more on it (the baseline's turnover at $500k, 0.859 to 1.199). Two floored paths, the *H* = 3 model's zone at both books, equal their trailing version and add no trial.
- **Nothing clears the bar.** With 15 new trials at each book size, 192 in all, the best path is still phase 5's three-day lookback through the optimiser at $5m with the trailing slope: net Sharpe 0.37, t 0.86, deflated Sharpe probability 0.20, against phase 5's 0.285 from 177 trials.
- **A negative slope is common in the holdout.** The share of days with a negative trailing slope is 0% to 41% in each development year for each forecast, and in the holdout 30% (baseline), 44% (three-day lookback), 78% (*H* = 1) and 51% (*H* = 3). Phase 5 did not measure the holdout's slope; this is the measurement, from the diagnostic paths, and nothing is chosen from it.

## The signal fix

Counting only the stocks known on the day moved phase 2's raw control and s-score paths and phase 3's s-score paths, and nothing in phases 4 or 5 at two decimals. The reruns' commits carry `Results:` footers (`ce738c9`, `61a81b2`); the reports hold the new values. The numbers the phase 2 and phase 3 reviews quote that moved:

| Review | Number | Before | After |
|---|---|---|---|
| [Phase 2](../phase-02/review.md) | s-score break-even, bps one-way | 2.47 | 2.52 |
| Phase 2 | s-score net Sharpe at 5 bps | −0.43 | −0.42 |
| Phase 2 | s-score median open positions | 109 | 108 |
| Phase 2 | median gross Sharpe of the raw decile configurations | 0.51 | 0.53 |
| Phase 2 | raw, *n* = 5, *k* = 5, gross Sharpe | 0.50 | 0.51 |
| Phase 2 | best raw configuration's gross Sharpe | 0.78 | 0.77 |
| Phase 2 | deflated Sharpe probability of the best path | 0.915 | 0.914 |
| [Phase 3](../phase-03/review.md) | three-day lookback with the zone at $5m, deflated Sharpe probability | 0.621 | 0.620 |
| Phase 3 | s-score net Sharpe at $500k | −0.20 | −0.19 |
| Phase 3 | s-score at $500k on IBKR Pro Tiered | −0.03 | −0.02 |
| Phase 3 | s-score borrow, % of capital a year | 0.53 | 0.52 |

No verdict in either review changes. The best path in phase 2 (residual, *n* = 3, *k* = 3) and its gross Sharpe, 0.85, are unchanged, as is phase 3's benchmark Sharpe, 0.44.

## What surprised us

- **The decile book earned most on the days the trailing slope said reversal had stopped.** The decile sort ignores the slope, so its gross return can be split by the sign of the slope on the decision day. In development it earned more on negative-slope days for all four forecasts: 5.77% a year against 2.69% for the baseline, 10.37% against 3.62% for the three-day lookback, 6.83% against −0.46% for the *H* = 1 model, and 2.98% against 2.01% for *H* = 3, over only 10 negative days. In the holdout the same holds for every forecast but *H* = 3. The no-trade zone stops opening positions on those days, deploying 0.00 to 0.08 of capital against 0.14 to 0.92 on positive days, so it sits out the days the decile book did best. A likely reason, which this phase did not test: the trailing slope is fitted on signals at least five days old, so it turns negative after reversal has failed, and by then reversal has often come back. These returns are annualised from 10 to 241 negative days per forecast and period, with no test of significance; they say the trailing calibration is late, not that another calibration would pay, and the expanding slope, which is rarely negative, kept no net edge either.
- **The lead sits in the move the book cannot hold.** Phase 5 measured IC from the close of *t*, and the baseline's one-day IC there was its best feature. The fill-timing table puts most of it in the overnight move from the close of *t* to the open of *t+1*, which a book filled at the open never holds, and the three-day lookback, whose one-day IC from the close was the lowest of the four, has the largest five-day lead from the fill. The five-day lead from the fill orders the three-day lookback, the baseline and the *H* = 3 model as phase 5 found their decile sorts' gross returns ordered, which phase 5's IC did not. It extends phase 5's lesson: a forecast's IC is measured from the fill before it is compared.

## Review questions

The brief's questions are the forward run's. Three wait for it; the fourth can be answered in part from the evidence.

**Did live behaviour (turnover, signals, IC) match the backtest? If not, which assumption broke?** Not yet answerable: no forward session has run. The tests show that a run of synthetic sessions, each on tables cut at it, gives the backtest's holdings, trades and P&L exactly, so a mismatch in the forward run will come from the data, the clock or the operation, not from a second implementation of the strategy.

**Which data revisions did the source make after the fact, and would they have changed any decision?** Not yet answerable. The drift report compares each pair of daily snapshots bar by bar and rebuilds each recorded decision on the later snapshot, so the forward run will answer it.

**What operational problems appeared that a backtest never shows?** None yet, since nothing ran. The run log records every refused and failed run for the drift report, so the forward run will answer it.

**What would it take to move to intraday data, and is it worth it?** The fill-timing table says where the daily lead is: most of the baseline's one-day IC is in the overnight move, which only a fill at the close of *t* would hold, with a signal computed from prices before the close. That needs intraday bars to compute the signal in the last minutes before the close and a model of the closing-auction fill, neither of which this project has. It is not worth it on this evidence alone; the [roadmap](../../roadmap.md) leaves it to a decision record after the forward run.

## Lessons this phase built in

Four rows in [`docs/lessons.md`](../../lessons.md). Three are the rules the brief named, each built in with a test from the start: the live step is the backtest's step; the job does not trust the clock; and a frozen config cannot see a code change, so the frozen path is rebuilt before every run. The fourth has its episode [above](#what-surprised-us): a forecast's lead is measured from the fill, since most of the baseline's one-day IC is in a move a book filled at the next open never holds.

## Reference docs

Confirmed current in this change: [architecture](../../architecture.md) (the paper package, its runners, `config/paper.toml`, exchange-calendars), [data model](../../data-model.md) (the ledger, the run log and the log's choice and diagnostic paths), [time discipline](../../time-discipline.md) (the phase 6 notes), [glossary](../../glossary.md), [requirements](../../requirements.md) (the choice runner, measured on 2026-11-17; the forward-run runners are measured with the first download), [reproducing the results](../../reproduce.md) (step 7), the [overview](../../overview.md) (the paper-trading stage) and the [lessons](../../lessons.md). The phase 2 and phase 3 reviews point to [the signal fix](#the-signal-fix) for the numbers it moved. No decision record: the one that freezes the strategy starts the forward run.

## Backlog walk

- **A second price source for cross-checking:** trigger the phase 6 review, arrived. Nothing in this phase showed unexplained large returns, and the drift report's revision check, which would show the source's errors after the fact, has not yet run. Kept, with the trigger moved to the forward run's first drift report.
- **An independent short-term reversal series:** trigger the phase 6 review, arrived. It checks the engine and the data against others' work, and nothing in this phase needs it, but it is the one external check on the whole pipeline. Kept, with the trigger moved to the documentation site's, when the repository goes public.
- **Measured effective spreads** (trigger the forward run's decision record), **forward run** (the owner's decision, after this phase is merged) and **documentation site** (when the repository goes public): not yet due.

## What carries forward

- **To the forward run's decision record:** the evidence in `choice.md`, and a rule for choosing from it stated before any forward day is seen. Nothing clears the bar, so the choice is which pipeline to test. The fill-timing and negative-slope findings are reasons to prefer a forecast whose lead survives the fill and a rule that does not depend on the slope's sign, but they were measured on years phase 5 has read for the slope, and on development years for everything else.
- **The holdout is spent.** Whether the forward days are a fresh holdout is the decision record's to say, with the guard that makes the development runners refuse them if they are.
- **The calibration** is late by construction ([above](#what-surprised-us)); whether a calibration that is not would pay is open, and is a new trial if tested.
- **The open fill** remains a lower bound on impact, and **survivorship** stays as stated in phase 0, unmeasured.
- **The dependency-upgrade criterion** from phase 0 is still untested: exchange-calendars entered without moving an existing pin.
