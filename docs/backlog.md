# Backlog

Deferred work, variants and open questions that do not belong in the current phase brief.

## Rules

- Every item names a trigger (the phase or event at which it should be revisited), why it matters, and the action to take then.
- Each phase review walks this list. An item is either moved into the next phase brief, turned into a decision record in `docs/decisions/` if it changes scope, data source or methodology, or deleted. The review says which.
- Work for the current phase goes in its brief, not here.
- An item's title is fixed once written: reviews and decision records refer to items by title.

## Items

### Benchmark against Avellaneda and Lee

- **Trigger:** phase 2 review.
- **Why:** the closest published version of this strategy, with a sample ending in 2007. Comparing residual properties and reversal strength gives an external reference point.
- **Action:** add a section to each review explaining the gap, separating the later sample period, survivorship bias and method differences.

### Multi-period optimiser

- **Trigger:** phase 4 review.
- **Why:** the phase 4 optimiser solves one day at a time and ignores that today's trade changes tomorrow's starting book. Gârleanu and Pedersen (2013) show the multi-period answer: trade part of the way towards an aim portfolio that blends current and expected future forecasts, weighted by how fast each signal decays. A fast-decaying reversal signal is the case where this matters most.
- **Action:** if the phase 4 review shows costs still dominate after the turnover controls, implement the partial-adjustment rule as a variant behind the same portfolio interface and compare at matched turnover. Otherwise delete this item.

### Documentation site

- **Trigger:** when the repository goes public, and not before phase 3.
- **Why:** GitHub renders the current markdown well. A site pays off once reports from several phases need cross-phase comparison and navigation. A Pages site from a private personal repository would be public.
- **Action:** write a decision record choosing the tool, its licence read first. The tool should render committed reports without executing code in CI, since `data/` is git-ignored. Until then, keep `reports/` as GitHub-friendly markdown with relative links.

### A second price source for cross-checking

- **Trigger:** phase 2 review, or sooner if a quality report or the residuals show unexplained large returns.
- **Why:** the build has one price source, so an error Alpaca makes and no rule catches goes into every later phase. Comparing closes and actions with an independent source would find them. Decision record 0003 rules out sources whose terms forbid automated collection.
- **Action:** find a free source whose terms allow automated collection, read its licence and terms, and write a decision record. Cross-check closes and ex-date actions over the universe; do not mix its prices into the build.

### Sector factor excluding the stock

- **Trigger:** phase 2 review.
- **Why:** sector ETFs hold the stocks regressed on them, and the largest names are a large share of their ETF, so their residuals are understated. Phase 1 found weaker lag-1 reversal in the top size bucket, which this may explain in part.
- **Action:** if the phase 2 P&L by size shows the largest names behaving differently, build the sector factor from universe members' returns excluding the stock itself, as a second `FactorModel`, and compare reversal by size bucket. Otherwise move it to the phase 4 brief, where Model B gives a second answer to the same question.
