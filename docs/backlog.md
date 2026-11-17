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

### Other strategies on free daily data

- **Trigger:** the forward run's review, when the next chapter is chosen. Each strategy taken up needs a decision record before its first run, since it changes scope.
- **Why:** every phase has studied one strategy, and its edge is small next to costs. Strategies that trade less, or that use the opens and closes already held, test whether the pipeline (universe, factor model, cost model, optimiser, walk-forward, deflated bar) carries over to another idea, and whether that idea survives the same costs.
- **Action:** candidates, roughly in order of how much existing code they reuse:
  - **Overnight and intraday reversal** (Lou, Polk and Skouras, 2019): split each residual into its overnight and intraday parts and build a signal from each. The phase 6 review found most of the baseline's one-day lead in the overnight move, which a book filled at the open never holds; this asks whether the intraday part alone reverses into the next day.
  - **Pairs trading** (Gatev, Goetzmann and Rouwenhorst, 2006): distance-method pairs within a sector, then cointegrated pairs with a rolling hedge ratio, compared with the factor residual at matched turnover.
  - **Lead-lag** (Lo and MacKinlay, 1990; Hou, 2007): stocks that have not yet followed their sector ETF's move, using the same residuals with the sector return as the signal.
  - **Cross-sectional and industry momentum** (Jegadeesh and Titman, 1993; Moskowitz and Grinblatt, 1999): twelve-month return skipping the last month, rebalanced monthly. Its turnover is a fraction of reversal's, so it tests the cost lesson from the other side.
  - **Low volatility and betting against beta** (Frazzini and Pedersen, 2014): long low-beta, short high-beta, scaled to be beta-neutral, monthly.
  - **Time-series momentum** (Moskowitz, Ooi and Pedersen, 2012) on the sector ETFs and SPY already in the data.
  - **A regime filter for reversal:** switch the baseline off in states where it has failed, building on the phase 6 slope evidence.
  - Before choosing, read Chen and Zimmermann's Open Source Asset Pricing replications as the list of what has been tried (licence not yet read).
- **Constraints:** the phase 5 holdout is spent, so a strategy is chosen on development data and confirmed only on data that arrives after its configuration is fixed. Every configuration counts as a trial against the bar. Survivorship (phase 0 review) cuts differently by strategy: it flatters a long leg in recent losers and momentum's long leg in past winners, and hides the failures a short leg would have profited from; each review says which way it cuts. Earnings drift is left out: it needs a point-in-time earnings calendar the free sources do not give.

### Combining strategies

- **Trigger:** a second strategy from the item above has been evaluated on its own on development data, under its own decision record.
- **Why:** for *N* strategies with equal Sharpe ratio *S* and pairwise correlation ρ, an equal-risk combination has a Sharpe ratio of *S* × √(*N* / (1 + (*N* − 1)ρ)), a likelier route to the bar than improving reversal alone. A slow signal combined with fast reversal also nets trades: when the two disagree, one book trades less than two, which matters for a strategy whose edge is small next to costs.
- **Action:** blend the strategies' calibrated expected moves into one forecast with fixed equal-risk weights and build one book through the phase 4 optimiser, rather than separate books with a capital split. Compare the blend with each strategy alone at matched turnover, report how much of the cost saving comes from netting, and report the strategies' correlation by year, since it tends to rise in a crisis (Khandani and Lo, 2007).
- **Constraints:** fitted blend weights are more trials and count against the bar; fixed equal-risk weights avoid most of that. Chosen on development data and confirmed only on data that arrives after.

### Intraday data

- **Trigger:** the forward run's review. Intraday data is out of scope ([roadmap](roadmap.md)) and needs a decision record under decision record 0001.
- **Why:** the phase 6 review found most of the baseline's one-day lead in the overnight move, which a book filled at the open never holds; holding it needs a signal computed before the close and a fill at the closing auction. The spread is an assumption (decision record 0005) that quotes would measure.
- **Action:** in order, each step only if the one before justifies it: split the residual into overnight and intraday parts on the daily opens and closes already held (see "Other strategies on free daily data"); then a near-close fill, with intraday bars for the signal and a model of the closing-auction fill, only if the overnight reversal holds in recent years; then a measurement of the spread from quotes. Not an intraday book. Each source's terms are read before a decision record.

### Closes from the listing exchange's closing auctions

- **Trigger:** the forward run's decision record, since the frozen path's fills and marks use the close, or sooner if a drift report shows a close that is not the listing exchange's closing auction price.
- **Why:** the build takes the consolidated daily bar's close, which can differ from the official close set by the listing exchange's closing auction. How often it differs in this data has not been measured. The same question applies to the open: a market-on-open order fills at the opening auction, and the bar's open need not be that price.
- **Action:** measure first, without changing the build: fetch each ticker's auctions from Alpaca into a raw snapshot of its own, find the listing exchange per ticker from a sourced list with its transfers since 2016, and count by year how often the auction close and open differ from the bar's. Rerun the headline paths with auction prices under an overlay and report the change. Adopting it is a build change after the fact, reported against the current numbers, with an amendment to decision record 0004.

### Survivorship-free prices

- **Trigger:** a later phase returns to the data.
- **Why:** the universe is drawn from today's S&P 500 and has no delisted stocks ([phase 0 review](phases/phase-00/review.md)), which flatters buying recent losers. A free survivorship-aware panel would let the effect be measured rather than stated.
- **Action:** look for a free S&P 500 panel that holds delisted members' prices with their delisting returns, on a basis the build can use (unadjusted with actions, not fully adjusted), with terms that allow this use. One candidate to read first is FINSABER-V2-Data on Hugging Face (`finsaber-team/FINSABER-V2-Data`; its basis, delisting returns and licence not yet checked). If one qualifies, write a decision record under decision record 0001 to add it behind the price and constituent interfaces, and measure how much the phase 2 to 5 results change with the missing names restored. If none does, delete this item.

### Model diagnostic charts

- **Trigger:** a later phase returns to the ML model, or the cross-phase summary below, whichever comes first.
- **Why:** phase 5's report shows the IC by year and the features' importance, but not how the IC moves through time, how the forecast depends on its strongest feature, or how the walk-forward tuning behaved. The tuning is visible only in the log, which hides whether the chosen grid point flips between blocks on small differences in validation IC, and whether the number of trees collapses in blocks where validation IC is near zero, when the model is close to a constant forecast. Day-level features (`market_vol` and `dispersion`, the same for every stock on a day) cannot reorder stocks on their own, since the target is ranked within each day, so the gain they take is either interaction or fitting each day's mean, which changes no position.
- **Action:** chart the rolling 252-day IC at 1 and 5 days across development and the holdout with the boundary marked; the SHAP dependence of the forecast on the one-day residual sum coloured by the volume ratio; and the walk-forward blocks for each horizon, one column per block, with every grid point's validation IC, the chosen one marked, and the trees chosen on a log scale. Every block's grid is in `reports/phase-05/experiments.jsonl`, so the charts need no retraining. Separately, measure how much of the day-level features' gain is interaction, by comparing validation IC with and without them over every block, on development data only; that comparison adds trials.

### Cross-phase summary

- **Trigger:** the forward run's review, or the documentation site, whichever comes first.
- **Why:** each review reports its own phase, and a reader has no single view of how the headline moved from phase to phase, how much each step lost to costs and how many trials the bar has absorbed.
- **Action:** store each phase's headline path's daily returns in one table, written by the runners that already produce them, so no earlier phase is rerun. From it, one report with the shrinkage of the headline Sharpe from gross to net by phase, drawdown curves, the trial histogram against the deflated bar, and the sample and holdout timeline. Statistics and charts only, no prices.
