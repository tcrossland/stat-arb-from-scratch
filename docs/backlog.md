# Backlog

Deferred work, variants and open questions that do not belong in the current phase brief.

## Rules

- Every item names a trigger (the phase or event at which it should be revisited), why it matters, and the action to take then.
- Each phase review walks this list. An item is either moved into the next phase brief, turned into a decision record in `docs/decisions/` if it changes scope, data source or methodology, or deleted. The review says which.
- Work for the current phase goes in its brief, not here.
- An item's title is fixed once written: reviews and decision records refer to items by title.

## Items

### s-score threshold trading rule

- **Trigger:** phase 2.
- **Why:** Avellaneda and Lee (2010) enter and exit on thresholds of an Ornstein-Uhlenbeck s-score rather than sorting into daily deciles. It trades much less than a daily decile rebalance, which matters once costs bite.
- **Action:** run as a variant alongside the decile baseline through the same engine and cost settings.

### Benchmark against Avellaneda and Lee

- **Trigger:** phase 1 and phase 2 reviews.
- **Why:** the closest published version of this strategy, with a sample ending in 2007. Comparing residual properties and reversal strength gives an external reference point.
- **Action:** add a section to each review explaining the gap, separating the later sample period, survivorship bias and method differences.

### Documentation site

- **Trigger:** when the repository goes public, and not before phase 3.
- **Why:** GitHub renders the current markdown well. A site pays off once reports from several phases need cross-phase comparison and navigation. A Pages site from a private personal repository would be public.
- **Action:** write a decision record choosing the tool, its licence read first. The tool should render committed reports without executing code in CI, since `data/` is git-ignored. Until then, keep `reports/` as GitHub-friendly markdown with relative links.
