# Phase 6: Paper-trading simulation

Drafted at setup, and revised at the start of the phase with what earlier phases found.

## Goal

Run the chosen strategy forward in time on new data each day, with no real orders, and check that the live pipeline behaves like the backtest.

## Revised at the start of the phase

Phases 0 to 5 built the data, the residuals, the signals, the cost model, the optimiser and the walk-forward model. None found a net edge: no path in any phase clears the deflated-Sharpe bar, and the phase 5 holdout has been read. What this phase can still test is whether a pipeline run one day at a time behaves like its backtest. This revision makes the brief concrete where earlier phases reach it.

### Built now, run later

This phase builds and tests the paper-trading package and the evidence for choosing what it trades. It starts no forward run. The run waits for a later decision record, which freezes the strategy, its book size and any model files, names the first session, the ledger's backup and the scheduler, and says whether the forward days are a fresh holdout. Until then `[frozen]` and `[run]` in `config/paper.toml` hold no values and the daily job refuses to run. The backlog item "Forward run" lists what the decision needs.

Everything the run will need is built and tested here. Tests run on synthetic data and a fixed calendar, offline; nothing in this phase downloads.

### Evidence for the choice

Nothing earned the role on returns ([phase 5 review](../phase-05/review.md#what-carries-forward)). On development data the three-day lookback through the optimiser at $5m is the best path; in the holdout the *H* = 3 model through the optimiser loses least; neither clears the bar. The forward run tests the pipeline, which any of them can do, so the choice is which pipeline to test, by a rule stated in the decision record before any forward day is seen. This phase builds the evidence the record cites, on development data only, in `statarb.paper.choice`:

- **Realised move by forecast decile.** The mean realised 5-day residual move by decile of each phase 5 forecast. Phase 5's untested reading of why the forecast with the best IC earned less is that it orders the middle of the cross-section, while a decile book or a calibrated forecast earns in the tails; the chart confirms or refutes it.
- **IC by fill timing.** Each forecast's IC against total returns from the close of *t*, where phase 5 measures it, and from the open of *t+1*, where the book fills. A lead that sits in the overnight move is one the book never holds.
- **What a negative calibration slope does.** A negative trailing slope reverses every expected move: the zone stops opening positions and the optimiser bets on continuation. Phase 5 found the trailing slope positive on 82% to 99% of development path days and did not measure it in the holdout. Each forecast runs through every rule that uses the expected move, at both book sizes, with the slope as phase 3 has it (trailing), floored at zero, and estimated over every pair since the start (expanding). The trailing paths repeat phase 5's and must reproduce its log exactly. A path identical to its trailing version adds no trial; the others are trials. A chart shows each forecast's trailing slope from its first calibrated date to the end of the snapshot, negative stretches shaded and the holdout marked, above the cumulative gross P&L of its decile sort and zone.

The runner retrains the phase 5 models and requires each to match its logged SHA-256. It logs to `reports/phase-06/experiments.jsonl`, and the forward run's reproduction check (below) reads the frozen path's entry there.

### The daily job

- **Which sessions are due** comes from the New York Stock Exchange calendar of `exchange_calendars`, never from the machine's clock or from whether data has arrived. A session is due once New York's date has passed it and New York's clock has reached the run time in config, so the scheduler may fire early, late or twice. Missed sessions are caught up in order from the last ledger day. The library enters with its licence read from its own metadata.
- **Data each day** is a complete price snapshot, built into `data/paper/processed/<snapshot>/` and never into the development tables. By phase 0's rule a snapshot taken on New York date *D* holds bars before *D* only, so a session's bars arrive in the next day's snapshot. A session the tables lack stops the run there, and the next run retries it.
- **One engine step per session.** Ledger day *d* is grid time *d* on the open grid: the return from the open of *d−1* to the open of *d* on the holdings carried in, the fill at the open of *d* of the decision recorded at the close of *d−1*, then the decision at the close of *d*. The next day fills the recorded decision rather than recomputing it, so a revision the source makes overnight cannot change an order after the fact. Each decision is built from the tables cut at *d* with the backtest's own code, so a session's step is the backtest's step on that grid time, and a test checks it.
- **What the job can run:** a phase 3 variant or a phase 5 model forecast, through the decile sort, the no-trade zone or the optimiser at a cost multiplier, with a slope rule, at a book size. Partial adjustment is left out, since it kept less than the optimiser for every forecast; the job refuses a frozen rule it cannot run.
- **A model forecast** comes from the phase 5 walk-forward's saved model files: each day's forecast is from the model of the block it falls in, and after the last block that model continues, untrained. Every file's SHA-256 is in the frozen record, and the job refuses to run if any file differs.
- **On a solver failure** the optimiser holds the book, as in the phase 4 backtest; the status goes in the ledger and the daily note, and the next day continues.
- **The frozen record** pins everything that produces a decision: the strategy as its log entry describes it, the parsed contents of every config file that shapes the data, residuals, signal or costs, and the model files' SHA-256. Its hash goes in config. The job and the drift report rebuild the record before anything else and refuse to run if it differs, naming the keys that changed.
- **The reproduction check.** This phase changes code, which the frozen record cannot see. Before processing any session the job rebuilds the frozen path over development, on tables built from the pinned snapshot, and requires every metric of its log entry exactly.
- **The ledger** carries the frozen record's hash, the commit, whether the tree had changes and the snapshot on every row, and an integrity check refuses a ledger whose chain does not hold bit for bit.
- **The backup** copies the ledger into a clone of a private git repository after each run and pushes it. A failure is recorded and retried by the next run; it never stops the job.
- **A run log**, `data/paper/runs.jsonl`, records every run, refused and failed runs included, for the drift report.

### Lessons this phase builds in

Each has its own row in [`docs/lessons.md`](../../lessons.md).

- **The live step is the backtest's step.** The daily job calls the engine's step function and the backtest's builders on the tables cut at each session, and a test requires a run of sessions to give the backtest's holdings exactly.
- **The job does not trust the clock.** Whether a session is due depends on New York's date and time, whatever the machine's zone, and a test covers the weeks when US and European clock changes differ.
- **A frozen config cannot see a code change.** The reproduction check rebuilds the frozen path and compares every metric, and a test changes the code's behaviour and requires the refusal.

### Backlog items whose trigger is the start of this phase

- **Measured effective spreads.** Simulated fills run only in the forward run, so the item moves to the forward run's decision record, the trigger for any conclusion that turns on the spread.

### What earlier phases leave to this phase

The open fill is a lower bound on impact; survivorship flatters the long side, unmeasured; whether the pooled 5-day calibration overstates what a trade earns is still open; and the dependency-upgrade criterion stays untested, since `exchange_calendars` enters without moving an existing pin.

## From the phase 5 backlog walk

- **Signals that count members before their first residual.** The raw reversal signal scores a member from its total returns before its first residual, and the s-score fits such members and centres across them, but only when the stock has a residual later, which a live run on that day would not know. Phase 5's row-removal test found it; the [phase 5 review](../phase-05/review.md#the-look-ahead-perturbation-cannot-see) says how far it reaches. Before the daily job is built, in a commit of its own: count only stocks known on the day in both signals, rebuild phases 2 and 3 with a `Results:` footer giving both sets of numbers, and remove the two strict expected failures in `tests/contract/test_signals.py`. A daily job appends one day at a time, so a signal that depends on later rows would differ from its backtest there first.

## Design

- A daily job after the US close that:
  1. downloads the latest day's data and appends it to the store
  2. updates factor exposures, residuals and features
  3. produces forecasts and target weights from the frozen model
  4. simulates fills at the fill timing used for the backtest headline (open of *t+1* unless a phase review changed it), using the phase 3 cost model
  5. writes that day's trades, positions and P&L to the ledger and a short daily markdown note in `reports/phase-06/daily/`
- **Ledger:** one immutable parquet file per trading day, `data/paper/ledger/date=YYYY-MM-DD.parquet`, written to a temporary file and renamed into place so a crash can never leave a half-written day. Parquet files cannot be appended to, so a single growing file would mean rewriting the whole record every day.
- **Backup:** `data/` is git-ignored, and the ledger is the only record of the forward run. The daily notes are committed, and the ledger is copied to a private backup named in the forward run's decision record. The ledger holds fill prices, so it is never published.
- The strategy and all parameters are frozen before the forward run and recorded in `docs/decisions/`, including the SHA-256 hash of every model file it uses. The job refuses to run if a model file's hash does not match. Retraining is a new decision, not a silent update.
- The job must be idempotent: running it twice for the same date changes nothing. Rerunning a date overwrites only that day's ledger file.
- If the optimiser is infeasible or the solver fails, hold the previous day's book, record the failure in the ledger and the daily note, and continue the next day. The phase 4 backtest applies the same rule, so live and backtest behave the same on bad days. Never relax constraints automatically to get a solution.
- Scheduling with the host's scheduler, set up with the forward run. Missed days are caught up in order.

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
3. Tests: idempotency, catch-up after missed days, a run before the session is due does nothing whatever the machine's time zone, ledger integrity checks, no partial ledger file after a simulated crash mid-write, refusal to run on a model hash mismatch, a changed frozen config or a failed reproduction check, and the hold-previous-book fallback on a forced solver failure.

## Acceptance criteria

The criteria below are the forward run's. This phase's build is accepted when every test above passes and the evidence for the choice is logged.

- At least eight weeks of uninterrupted forward running.
- The drift report states whether turnover, signal distributions and IC sit within the backtest's ranges, and whether P&L sits within the wide band.

## Optional extension

Connect an Interactive Brokers **paper** account to compare simulated fills with IBKR's paper fills. This is the only way this phase can test the cost model. Requires a decision record first. No live account, ever, without a separate decision.

## Review questions

- Did live behaviour (turnover, signals, IC) match the backtest? If not, which assumption broke?
- Which data revisions did the source make after the fact, and would they have changed any decision?
- What operational problems appeared that a backtest never shows?
- What would it take to move to intraday data, and is it worth it?
