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

- **Trigger:** phase 5 review, or sooner if a quality report, the residuals or a backtest show unexplained large returns.
- **Why:** the build has one price source, so an error Alpaca makes and no rule catches goes into every later phase. Comparing closes and actions with an independent source would find them. Decision record 0003 rules out sources whose terms forbid automated collection.
- **Action:** find a free source whose terms allow automated collection, read its licence and terms, and write a decision record. Cross-check closes and ex-date actions over the universe; do not mix its prices into the build.

### An independent short-term reversal series

- **Trigger:** phase 5 review.
- **Why:** every check on the engine so far runs on this project's own data and code. A published short-term reversal factor, built by others from other data over the same years, would show whether the decile book's P&L moves with it by year, a check on the engine and the data together that no internal test gives.
- **Action:** find a published daily or monthly short-term reversal series, read its terms of use, and write a decision record before downloading it, since it is a new data source. Compare its returns by year with the raw-reversal decile book's gross P&L; do not use it in any signal.

### Multi-period optimiser

- **Trigger:** phase 5 review.
- **Why:** the phase 4 optimiser solves one day at a time and ignores that today's trade changes tomorrow's starting book, and in all but three of its 34 pairs of path and book size costs exceeded the gross return. Gârleanu and Pedersen (2013) trade part of the way towards an aim portfolio that blends current and expected future forecasts, weighted by how fast each decays. The phase 4 review moved it into the phase 5 brief, which deferred it: its trials would count against the deflated-Sharpe bar the model's forecast must clear, and it needs forecasts at several horizons, so a result in the same phase would mix the forecast with the trading rule.
- **Action:** at the phase 5 review, with the forecasts' decay by horizon measured, carry it to a later chapter, with the trade rate set by a rule on positions before any return is seen and the comparison with the one-period optimiser at matched turnover, or delete it if the decay leaves nothing to weight.

### Signals that count members before their first residual

- **Trigger:** phase 5 review.
- **Why:** the stock axis of the signal tables is every stock with a residual anywhere in the loaded tables. The raw reversal signal scores a member from its total returns before its first residual, and the s-score fits such members and centres across them, but only when the stock has a residual later; a live run on that day would not see it. Phase 5's row-removal test found this. On the pinned snapshot it touches 2,362 member-days from 2017-01-03, of 25 stocks, on 1,349 days. It reaches phase 2's and phase 3's raw control and s-score paths, not the residual signal or the model. `tests/contract/test_signals.py` marks both signals as strict expected failures until it is fixed.
- **Action:** count only stocks known on the day in both signals, rerun phases 2 and 3 in a commit of its own with a `Results:` footer and both sets of numbers, and remove the two expected failures.

### Measured effective spreads

- **Trigger:** the start of phase 6, whose simulated fills use the spread, or sooner if a conclusion turns on the spread assumption.
- **Why:** decision record 0005 charges an assumed spread because the daily-price estimators measure the strategy's own reversal. The assumption is the same for every stock and day, so it misprices the smaller names and stressed years.
- **Action:** find a public source of measured effective spreads per stock (for example the execution-quality reports US market centres publish under SEC Rule 605), read its terms, and write a decision record before using it. Compare it with the assumption and the bracket by size group and year.
