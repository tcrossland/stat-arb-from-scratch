# Backlog

Deferred work, variants and open questions that do not belong in the current phase brief.

## Rules

- Every item names a trigger (the phase or event at which it should be revisited), why it matters, and the action to take then.
- Each phase review walks this list. An item is either moved into the next phase brief, turned into a decision record in `docs/decisions/` if it changes scope, data source or methodology, or deleted. The review says which.
- Work for the current phase goes in its brief, not here.
- An item's title is fixed once written: reviews and decision records refer to items by title.

## Items

### Multi-period optimiser

- **Trigger:** phase 4 review.
- **Why:** the phase 4 optimiser solves one day at a time and ignores that today's trade changes tomorrow's starting book. Gârleanu and Pedersen (2013) show the multi-period answer: trade part of the way towards an aim portfolio that blends current and expected future forecasts, weighted by how fast each signal decays. A fast-decaying reversal signal is the case where this matters most.
- **Action:** if the phase 4 review shows costs still dominate after the turnover controls, implement the partial-adjustment rule as a variant behind the same portfolio interface and compare at matched turnover. Otherwise delete this item.

### Documentation site

- **Trigger:** when the repository goes public, and not before phase 3.
- **Why:** GitHub renders the current markdown well. A site pays off once reports from several phases need cross-phase comparison and navigation. A Pages site from a private personal repository would be public.
- **Action:** write a decision record choosing the tool, its licence read first. The tool should render committed reports without executing code in CI, since `data/` is git-ignored. Until then, keep `reports/` as GitHub-friendly markdown with relative links.

### A second price source for cross-checking

- **Trigger:** phase 5 review, or sooner if a quality report, the residuals or a backtest show unexplained large returns.
- **Why:** the build has one price source, so an error Alpaca makes and no rule catches goes into every later phase. Comparing closes and actions with an independent source would find them. Decision record 0003 rules out sources whose terms forbid automated collection.
- **Action:** find a free source whose terms allow automated collection, read its licence and terms, and write a decision record. Cross-check closes and ex-date actions over the universe; do not mix its prices into the build.

### An independent short-term reversal series

- **Trigger:** phase 3 review.
- **Why:** every check on the engine so far runs on this project's own data and code. A published short-term reversal factor, built by others from other data over the same years, would show whether the decile book's P&L moves with it by year, a check on the engine and the data together that no internal test gives.
- **Action:** find a published daily or monthly short-term reversal series, read its terms of use, and write a decision record before downloading it, since it is a new data source. Compare its returns by year with the raw-reversal decile book's gross P&L; do not use it in any signal.
