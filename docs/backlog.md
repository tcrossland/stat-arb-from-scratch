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
  - **Candidate: MarketParquet's archive,** a paid source, taken up by [decision record 0008](decisions/0008-marketparquet-archive-as-a-paid-price-source.md), which amends the free-data rule of decision record 0001. The [phase 7 brief](phases/phase-07/brief.md) takes the cross-check up with it. What its pages say, read on 2026-11-19:
    - **What it can check.** Daily bars for every listed US stock from 2000, adjusted for splits and not for dividends, with no split or dividend records. So it checks closes, volumes and splits, by putting the build's unadjusted bars on the same split basis, and it cannot check cash dividends.
    - **Licence.** It allows backtesting and publishing derived statistics, forbids redistributing the files, and is granted per account on payment for the archive.
    - **Independence.** Its upstream vendor is not named and may be shared with Alpaca's. Agreement would then prove little; disagreement is still worth chasing.
    - **Revisions.** The site rewrites published days when values change, with no checksum or version. Each download is kept as a raw snapshot under its own source folder, never the daily job's, pinned by date and digest like Alpaca's.
    - **The comparison window** ends on the phase 5 holdout's last day, 2026-11-13, so it reads no forward day (decision record 0007).

### An independent short-term reversal series

- **Trigger:** when the repository goes public. Moved from the phase 6 review, since no phase needs it and it is the check a reader would ask for.
- **Why:** every check on the engine so far runs on this project's own data and code. A published short-term reversal factor, built by others from other data over the same years, would show whether the decile book's P&L moves with it by year, a check on the engine and the data together that no internal test gives.
- **Action:** find a published daily or monthly short-term reversal series, read its terms of use, and write a decision record before downloading it, since it is a new data source. Compare its returns by year with the raw-reversal decile book's gross P&L; do not use it in any signal.

### Measured effective spreads

- **Trigger:** the forward run's review, or sooner if a conclusion turns on the spread assumption. Moved from the forward run's decision record by [decision record 0007](decisions/0007-forward-run.md): the run tests whether the live pipeline matches its backtest, which needs the spread assumption the backtest used.
- **Why:** decision record 0005 charges an assumed spread because the daily-price estimators measure the strategy's own reversal. The assumption is the same for every stock and day, so it misprices the smaller names and stressed years.
- **Action:** find a public source of measured effective spreads per stock (for example the execution-quality reports US market centres publish under SEC Rule 605), read its terms, and write a decision record before using it. Compare it with the assumption and the bracket by size group and year.

### Tolerance for a rebuild from another snapshot

- **Trigger:** a second snapshot is pinned at least a few weeks after the first.
- **Why:** the published results reproduce exactly only from the snapshot behind them, which is not redistributed. A reader who downloads their own gets Alpaca's later revisions to old data, so their numbers match closely, not exactly, and [reproducing the results](reproduce.md#checking-your-results) says the tolerance is not yet measured. The cache holds snapshots taken a day apart, too close to show what revisions do over weeks. Without a measured tolerance, a reader cannot tell a revision from an error in their rebuild.
- **Action:** pin the second snapshot and run every runner that accepts another snapshot on it with the same code (phase 0 to the phase 5 development run; the holdout and choice runners stop by design), then compare each logged metric with the first snapshot's by `config_id`. State the largest difference per metric in "Checking your results" in `docs/reproduce.md`, in place of the note that it is not yet measured. Once the forward run's drift report has run, check its revision count against the same comparison.

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
  - **A second strategy is built in this repository, as phase 7 and on, not in one of its own.**
    - The trial count reads the experiment logs under one reports directory (`repository_trials` in `statarb.backtest.trials`), so every configuration of every strategy counts against the bar with no further work. A second repository would need its logs joined to these by hand.
    - "Combining strategies" builds one book through one optimiser, which needs both forecasts on the same tables and the same engine.
    - The alternatives are a copy of `statarb`, which then drifts, or a shared library extracted before a second strategy shows what it must hold: a seam with one implementation.
    - A repository of its own is right only for a strategy that needs a data source under other terms, another asset class, or dependency versions the frozen run cannot take.
  - **What carries over,** which sets the order of the candidates above:
    - *Any daily strategy, unchanged:* config and overlays, deterministic parquet, the look-ahead checks, the raw snapshots and their cache, the conversion to unadjusted bars, cleaning and returns, `build_universe`, the engine, the cost model and spread estimators, the metrics, the experiment log and trial count, the `Signal` protocol, registry and calibration, the walk-forward splitter, model backend and training, the optimiser and partial adjustment, and the forward run's sessions, ledger, step and backup.
    - *US equities ranked across stocks:* the Alpaca and Wikipedia sources, the dated sectors, both factor models, the risk models, the signal tables and the decile rule.
    - *Residual reversal only:* the reversal and s-score signals, the threshold rule, the fifteen features, the phase 2 sweep and phase 4 paths, every runner and report (each names its `phase-NN` directory), and the forward run's day, frozen record, choice, daily job and drift report.
  - **What a second strategy changes when it lands, not before:**
    - *A named universe.* One `[universe]` in `config/data.toml` gives one `universe.parquet` under one `[paths] processed`, and `Tables.members` is one membership panel. An overlay can point `[paths]` elsewhere, but that is a second copy of the pipeline, not two universes side by side. Another cut of the same candidates needs only a membership table per named universe, chosen in the strategy's config. The [phase 7 brief](phases/phase-07/brief.md) builds the first. Another market is "Other universes".
    - *Tables that do not assume residuals.* `Tables.stocks` is the stocks with residuals, and `residual`, `beta_market` and `hedges` are required. Momentum, low volatility and lead-lag fit as new signals. Pairs trading holds a position per pair, and time-series momentum trades the hedge instruments themselves, so each needs its own portfolio rule and a change to `Tables`.
    - *Config files of its own.* See the constraints.
    - *Forward-run paths by strategy,* only if it reaches a forward run: `data/paper/` and `reports/phase-06/frozen-config.json` name no strategy, and `[frozen]` of `config/paper.toml` holds one.
  - **The [phase 8 brief](phases/phase-08/brief.md) drafts the first:** momentum, on the universe phase 7 builds.
- **Constraints:** the phase 5 holdout is spent, so a strategy is chosen on development data and confirmed only on data that arrives after its configuration is fixed. Every configuration counts as a trial against the bar. Survivorship (phase 0 review) cuts differently by strategy: it flatters a long leg in recent losers and momentum's long leg in past winners, and hides the failures a short leg would have profited from; each review says which way it cuts. Earnings drift is left out: it needs a point-in-time earnings calendar the free sources do not give.
  - **While the forward run lasts,** the frozen record hashes `data`, `universe`, `factors`, `sector_changes`, `listing_starts`, `alpaca`, `backtest`, `costs`, `portfolio` and `models` (`FILES` in `statarb.paper.frozen`), and the daily job refuses to run on a change. A new strategy's settings go in new config files and none of these is edited. `uv.lock` pins cvxpy, Clarabel, SciPy and LightGBM exactly for the frozen path's reproduction check, so a strategy that needs another version of any of them waits for the run's review, or reaches the job's clone only with a run that passes that check.

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

- **Trigger:** the forward run's review, or sooner if a drift report shows a close that is not the listing exchange's closing auction price. Moved from the forward run's decision record by [decision record 0007](decisions/0007-forward-run.md): the run tests whether the live pipeline matches its backtest, which needs the closes the backtest used.
- **Why:** the build takes the consolidated daily bar's close, which can differ from the official close set by the listing exchange's closing auction. How often it differs in this data has not been measured. The same question applies to the open: a market-on-open order fills at the opening auction, and the bar's open need not be that price.
- **Action:** measure first, without changing the build: fetch each ticker's auctions from Alpaca into a raw snapshot of its own, find the listing exchange per ticker from a sourced list with its transfers since 2016, and count by year how often the auction close and open differ from the bar's. Rerun the headline paths with auction prices under an overlay and report the change. Adopting it is a build change after the fact, reported against the current numbers, with an amendment to decision record 0004.

### Survivorship-free prices

- **Trigger:** a later phase returns to the data.
- **Why:** the universe is drawn from today's S&P 500 and has no delisted stocks ([phase 0 review](phases/phase-00/review.md)), which flatters buying recent losers. A free survivorship-aware panel would let the effect be measured rather than stated.
- **Action:** look for a free S&P 500 panel that holds delisted members' prices with their delisting returns, on a basis the build can use (unadjusted with actions, not fully adjusted), with terms that allow this use. One candidate to read first is FINSABER-V2-Data on Hugging Face (`finsaber-team/FINSABER-V2-Data`; its basis, delisting returns and licence not yet checked). If one qualifies, write a decision record under decision record 0001 to add it behind the price and constituent interfaces, and measure how much the phase 2 to 5 results change with the missing names restored. If none does, delete this item.

### Point-in-time index membership

- **Trigger:** phase 7's review, if a result still turns on which stocks were in the index, or a source of constituent history is found.
- **Why:** the candidates are the S&P 500 of one pinned Wikipedia revision. Phase 7 measures survivorship on a universe ranked from every listed stock, which answers the question for a universe defined by rule, not for the index: a stock that left the index and still trades is in neither measurement. Tickers are the only key, so a reused ticker or a renamed company can make a false entry or exit.
- **Action:** find a constituent history with announcement and effective dates, keyed by an identifier that survives a ticker change, and read its terms; a paid one needs a decision record under decision record 0001. Behind the `ConstituentSource` interface, with membership on a day taken as known that day. Measure how the phase 2 to 5 results change with the removed members restored.

### Cash-out for names whose prices stop

- **Trigger:** the forward run's review, or sooner if a held name loses its prices during the run.
- **Why:** the engine keeps a name with no bar at its holding and books a held name with no return at zero (`statarb.backtest.engine`). After an acquisition or a delisting the position therefore stays in the book at its last weight, earns nothing, takes gross exposure and is never cashed out. The daily note and the drift report count such names. On today's survivors the case is rare; the [phase 7 brief](phases/phase-07/brief.md) builds a rule for it as an engine option, off by default, because a universe with dead names meets it constantly.
- **Action:** decide whether the rule becomes the default for the existing universe: close the position at the last price after a set number of sessions without a bar, in the engine so the backtest and the paper run agree. It moves logged results and the frozen strategy's behaviour, so it is a change after the fact, reported against the current numbers, never made during the run. The review lists any name held at zero during the run, for how long, and the gross it took.

### Other universes

- **Trigger:** the forward run's review, when the next chapter is chosen. Another market is out of scope ([roadmap](roadmap.md)) until a decision record says otherwise.
- **Why:** the engine, signals, calibration, optimiser and models work on any table of dates and stocks, so a second market tests whether the pipeline generalises. Against it: several European markets tax share purchases, which for a strategy whose edge is small next to costs may decide the result before any modelling; a large enough universe means combining national index lists, with the same survivorship problem; and a new market needs a new price source.
- **Action:** first, without building anything, compare short-term reversal in Europe with the US from published factor data, for example Jensen, Kelly and Pedersen (2023) (terms of use not yet read). If reversal is not stronger there by more than the transaction taxes, stop. Otherwise, a decision record for the universe source, the sector ETFs, transaction taxes and a percentage-of-value commission in the cost model, and the exchange time zone from config rather than `statarb.data.schema.EXCHANGE_TZ`.

### Model diagnostic charts

- **Trigger:** a later phase returns to the ML model, or the cross-phase summary below, whichever comes first.
- **Why:** phase 5's report shows the IC by year and the features' importance, but not how the IC moves through time, how the forecast depends on its strongest feature, or how the walk-forward tuning behaved. The tuning is visible only in the log, which hides whether the chosen grid point flips between blocks on small differences in validation IC, and whether the number of trees collapses in blocks where validation IC is near zero, when the model is close to a constant forecast. Day-level features (`market_vol` and `dispersion`, the same for every stock on a day) cannot reorder stocks on their own, since the target is ranked within each day, so the gain they take is either interaction or fitting each day's mean, which changes no position.
- **Action:** chart the rolling 252-day IC at 1 and 5 days across development and the holdout with the boundary marked; the SHAP dependence of the forecast on the one-day residual sum coloured by the volume ratio; and the walk-forward blocks for each horizon, one column per block, with every grid point's validation IC, the chosen one marked, and the trees chosen on a log scale. Every block's grid is in `reports/phase-05/experiments.jsonl`, so the charts need no retraining. Separately, measure how much of the day-level features' gain is interaction, by comparing validation IC with and without them over every block, on development data only; that comparison adds trials.

### Cross-phase summary

- **Trigger:** the forward run's review, or the documentation site, whichever comes first.
- **Why:** each review reports its own phase, and a reader has no single view of how the headline moved from phase to phase, how much each step lost to costs and how many trials the bar has absorbed.
- **Action:** store each phase's headline path's daily returns in one table, written by the runners that already produce them, so no earlier phase is rerun. From it, one report with the shrinkage of the headline Sharpe from gross to net by phase, drawdown curves, the trial histogram against the deflated bar, and the sample and holdout timeline. Statistics and charts only, no prices.
