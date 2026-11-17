# Backlog

Deferred work, variants and open questions that do not belong in the current phase brief.

## Rules

- Every item names a trigger (the phase or event at which it should be revisited), why it matters, and the action to take then.
- Each phase review walks this list. An item is either moved into the next phase brief, turned into a decision record in `docs/decisions/` if it changes scope, data source or methodology, or deleted. The review says which.
- Work for the current phase goes in its brief, not here.
- An item's title is fixed once written: reviews and decision records refer to items by title.

## Items

### Documentation site

- **Trigger:** when the repository goes public.
- **Why:** GitHub renders the current markdown well. A site pays off once reports from several phases need cross-phase comparison and navigation. A Pages site from a private personal repository would be public.
- **Action:** write a decision record choosing the tool, its licence read first. The tool should render committed reports without executing code in CI, since `data/` is git-ignored. Until then, keep `reports/` as GitHub-friendly markdown with relative links.

### A second price source for cross-checking

- **Trigger:** the forward run's first weekly drift report, or sooner if a quality report, the residuals, a backtest or a drift report show unexplained large returns. Moved from the phase 6 review, since the drift report's revision check had not yet run.
- **Why:** the build has one price source, so an error Alpaca makes and no rule catches goes into every later phase. Comparing closes and actions with an independent source would find them. Decision record 0003 rules out sources whose terms forbid automated collection.
- **Action:** find a free source whose terms allow automated collection, read its licence and terms, and write a decision record. Cross-check closes and ex-date actions over the universe; do not mix its prices into the build.

### An independent short-term reversal series

- **Trigger:** when the repository goes public. Moved from the phase 6 review, since no phase needs it and it is the check a reader would ask for.
- **Why:** every check on the engine so far runs on this project's own data and code. A published short-term reversal factor, built by others from other data over the same years, would show whether the decile book's P&L moves with it by year, a check on the engine and the data together that no internal test gives.
- **Action:** find a published daily or monthly short-term reversal series, read its terms of use, and write a decision record before downloading it, since it is a new data source. Compare its returns by year with the raw-reversal decile book's gross P&L; do not use it in any signal.

### Measured effective spreads

- **Trigger:** the decision record that starts the forward run, whose simulated fills use the spread, or sooner if a conclusion turns on the spread assumption. Moved from the start of phase 6 by its brief, since phase 6 builds the job and runs no fills.
- **Why:** decision record 0005 charges an assumed spread because the daily-price estimators measure the strategy's own reversal. The assumption is the same for every stock and day, so it misprices the smaller names and stressed years.
- **Action:** find a public source of measured effective spreads per stock (for example the execution-quality reports US market centres publish under SEC Rule 605), read its terms, and write a decision record before using it. Compare it with the assumption and the bracket by size group and year.

### Forward run

- **Trigger:** the owner's decision to start it, after phase 6 is merged.
- **Why:** phase 6 builds and tests the paper-trading package but runs nothing forward, so nothing yet shows whether the live pipeline behaves like its backtest, the phase's goal. Its acceptance criteria, eight weeks of uninterrupted running and a drift report on turnover, signals, IC and P&L, can only be met by the run.
- **Action:** write the decision record that freezes the strategy from the phase 6 evidence by a rule stated before any forward day is seen: forecast, rule, slope rule, book size and, for a model, the files and their SHA-256. In the same record name the first session, the run time, the ledger's private backup repository and the scheduler, and say whether the forward days are a fresh holdout and from when; if they are, add the guard that makes the development and backtest runners refuse its dates. Fill `[frozen]`, `[run]` and `[backup]` in `config/paper.toml`, write the frozen record, check its first daily download end to end, then set up the scheduler, write `docs/daily-job.md` (the scheduler, the backup repository and its key, the daily and weekly commands, and what to do when a run is refused) and run the weekly drift report.

### Tolerance for a rebuild from another snapshot

- **Trigger:** a second snapshot is pinned at least a few weeks after the first.
- **Why:** the published results reproduce exactly only from the snapshot behind them, which is not redistributed. A reader who downloads their own gets Alpaca's later revisions to old data, so their numbers match closely, not exactly, and [reproducing the results](reproduce.md#checking-your-results) promises a tolerance it cannot yet state. The cache holds snapshots taken a day apart, too close to show what revisions do over weeks. Without a measured tolerance, a reader cannot tell a revision from an error in their rebuild.
- **Action:** pin the second snapshot and run every runner that accepts another snapshot on it with the same code (phase 0 to the phase 5 development run; the holdout and choice runners stop by design), then compare each logged metric with the first snapshot's by `config_id`. State the largest difference per metric in "Checking your results" in `docs/reproduce.md`, and remove its placeholder. Once the forward run's drift report has run, check its revision count against the same comparison.
