# Phase 8: Momentum

Drafted on 2026-11-19, during the forward run and before phase 7. To be revised at the start of the phase with what phase 7 and the forward run's review find. "What would change this brief" below says which findings would replace it.

## A momentum forward run, ahead of the phase

Added on 2026-11-25. [Decision record 0010](../../decisions/0010-momentum-forward-run.md) starts a momentum forward run beside the reversal run, on the same sessions (2026-11-16 to 2027-01-13) and the same Alpaca snapshots, before the rest of this phase. It runs the two signals of scope step 2 through the decile sort on the frozen universe, not on the `listed` universe, and its two development backtests are trials of this phase. The [plan](../../plans/momentum-forward-run.md) gives its stages. The sections below are amended where they meet it; the rest of the phase still waits for the forward run's review.

## What phase 7 found, for the revision

Added on 2026-11-22, after the [phase 7 review](../phase-07/review.md). The brief below is as drafted before phase 7 and is not yet revised: this lists what the revision has to take in. The numbers are in the review and its reports.

- **There is no rule for unadjusted prices.** Decision record 0009 derives none, so the phase 3 cost model cannot run on this universe, and step 3's net figures and the design point "The cost model on this universe" have nothing to rest on. A route exists and is not built: the backlog's "Splits and dividends for MarketParquet's symbols from Alpaca", whose trigger is this phase's cost model. The revision takes that item up first, or runs momentum gross and at a flat cost per dollar traded and says so. This is the first case under "What would change this brief".
- **The sources agree, with two disagreements open.** Closes and volumes differ before 2022 to 2023, most for the ETFs. That is short of the second case under "What would change this brief", but the one read of reversal on 2000 to 2015 is a one-day signal built on closes, in years where the disagreement is unmeasured, and it cannot be repeated. The backlog's "Why the two sources' closes and volumes differ before 2023" has its trigger at this phase's decision record.
- **Survivorship cut the other way for reversal, and the candidate list mattered more.** The universe with the dead names did slightly better than the one without, with the long leg helped and the short leg hurt by more. So the pitfall "Delisting cuts momentum the other way" compares momentum with a flattery of reversal's long leg that was not found, and step 5's "which way survivorship cuts for each leg, as phase 7 measured it" has a measured answer for reversal alone. The larger bias was the choice of today's S&P 500 as the candidate list, which this phase leaves behind by ranking every listed stock.
- **The form of reversal fixed for step 1** is what `statarb.backtest.survivorship` ran on the `listed` universe: on price returns and on Model B's residuals, with Model B fitted month by month on the members to date, the raw form scored from a symbol's first Model B residual, and the engine closing a held name after five sessions without a bar. The read of the unread years uses those settings unchanged.
- **Returns on this source are price returns.** Over momentum's twelve-month window the missing dividends are larger than over reversal's one day, which is what step 5's bound on the difference in yield between the legs is for. A spin-off is in the return only where the archive folded it in, and no rule tells the two apart.
- **A sensitivity on a price level is ruled out.** Step 5 proposes an assumed final return "for names whose last price is below a level". Prices here are adjusted for later splits, so a level on them looks ahead, and decision record 0009 lets nothing read one. Phase 7's sensitivity picks names by their fall over the last 21 bars instead, with its amounts in `config/marketparquet.toml`; this phase uses that form or states another that reads returns alone.
- **A company can be in a universe twice.** The archive holds some renamed companies under two symbols, and share classes rank separately. Phase 7 left these near-copies in and counted them; a momentum decile would hold both of a pair.
- **Model B at a one-day holding period is strong gross on today's S&P 500** and earns nothing net, the result of an eighth trial added after the review. It bears on the read of the unread years only as an expectation, stated here before that read: a high gross Sharpe ratio there on Model B's residuals would not be new.
- **What the footers showed of the years before 2016,** with no return computed: every session is present from 2000-01-03 on two schemas, the stock dataset has fewer than half as many symbols a session in 2000 as in 2015, and one session in 2000 has far fewer than its year's mean. The ETF dataset marks no symbol delisted in the years read, so it is not free of survivorship.

## Goal

Evaluate a second strategy, cross-sectional momentum, on its own: on the universe phase 7 builds, over the full history the second source holds, through the same portfolio rules, cost model and bar as reversal. And read the years before 2016 once, for reversal, before anything else has seen them.

## Why momentum

Six phases found that residual reversal earns a small gross return that trading costs more than remove. Momentum is the natural second strategy:

- **It tests the cost lesson from the other side.** It trades a fraction as often as reversal, so if it misses the bar it misses on its gross return, which is a different finding.
- **It needs prices only,** which is all the second source has: no sectors, fundamentals or shares outstanding.
- **It needs what the second source adds.** The stocks that later delisted are its short leg, so a universe of survivors biases it more than it biases reversal. And a monthly strategy cannot be judged on ten years: with a true annual Sharpe ratio *S* over *Y* years the t-statistic is about *S*√*Y*, so ten years cannot tell a modest Sharpe ratio from zero, and twenty-six can.
- **It is the second signal "Combining strategies" waits for.** A slow signal beside fast reversal, in one book, is the backlog's likelier route to the bar.

The expectation, stated before any run: momentum probably does not clear the bar on its own. Published momentum has been weak in large stocks since about 2000, and the sample holds its 2009 crash (Daniel and Moskowitz, 2016).

## Before the phase starts

- **The forward run's review is written.** The backlog's "Other strategies on free daily data" puts the choice of the next strategy there, and a run that did not match its backtest comes first. The momentum forward run of record 0010 is the exception: it starts before the review.
- **Phase 7's review says the new universe can carry a strategy:** the sources agree, and the cost model has unadjusted prices or a stated substitute.
- **A check that costs nothing:** read published returns of US large-cap momentum since 2000 from a source whose terms allow it, such as Jensen, Kelly and Pedersen (2023), terms not yet read. If the gross return there is near zero, see "What would change this brief".
- **A decision record for the strategy,** before its first run, as the backlog requires. It fixes:
  - the configuration below, taken from the papers and not tuned;
  - how these paths count beside the repository's existing trials, and how the bar treats Sharpe ratios measured over different periods;
  - what the years before 2016 are for, as "The sample" below proposes;
  - what, if anything, later data is expected to confirm.

## The sample

- **Reversal's unread years, 2000 to 2015.** Every reversal configuration was chosen on 2016 to 2025 and none has seen these years. They are read once, as the phase 5 holdout was.
- **Momentum, 2000 to 2026-11-13.** No year is unseen for momentum, since its record over this period is published. Its protection is a configuration fixed in advance and a small number of paths, not a holdout.
- **No day from 2026-11-16 on,** as in phase 7, unless the forward run has ended and its review has released them. The one exception is the momentum forward run's job (record 0010), which reads them as the reversal run's daily job does.
- **Warm-up.** The first signal date follows from the longest window, so momentum's first book is about a year after the first bar.

## Scope

1. **Reversal, read once on the unread years.**
   - The form is the one phase 7 ran on the universe with dead names and fixed there: on total returns and on Model B's residuals, at the headline's lookback, holding period, decile and fill. The frozen strategy itself cannot be read on these years: it uses Model A's residuals, which need sectors the dead names lack and sector ETFs that do not all exist then (XLC starts in June 2018).
   - A runner like `statarb.models.holdout`: it refuses a dirty tree, a configuration unlike the one phase 7 logged, and a second read, and its entries are not trials.
   - It reports the same statistics as phase 7's survivorship report, beside the 2016 to 2025 figures.
2. **The momentum signals,** behind the `Signal` interface, each passing the look-ahead contract with later values perturbed and with later rows removed:
   - **Total-return momentum** (Jegadeesh and Titman, 1993): the return over the 252 trading days ending 21 days before the decision.
   - **Residual momentum** (Blitz, Huij and Martens, 2011): the sum of Model B's residuals over the same window, divided by their standard deviation over it.
3. **Momentum alone,** each signal through:
   - the decile sort held 21 days in overlapping slices, which `DecileRule` already does;
   - the phase 4 optimiser, with the signal calibrated to an expected move by phase 3's calibration at a 21-day horizon;
   - gross and net under the phase 3 cost model at each book size, borrow included, since momentum's short leg is the stocks hardest to borrow.
   That is four position paths, fixed here. Any further path is a trial and needs a reason in the review.
4. **The report,** `reports/phase-08/momentum.md`, statistics only: each path's Sharpe ratio, return, turnover and drawdown, the legs apart, by year, 2009 on its own, the judgement against the bar, and momentum beside reversal at matched gross.
5. **The data's gaps as stated sensitivities:**
   - an assumed final return for names whose last price is below a level, at a few values, with the long and short legs apart;
   - a bound on the difference in dividend yield between the legs, if returns are price returns;
   - which way survivorship cuts for each leg, as phase 7 measured it.
6. **Momentum's correlation with reversal,** daily and by year, for the paths of step 3 against the reversal headline. Reported and not acted on: it is the input "Combining strategies" needs.
7. **The momentum forward run** of record 0010, started ahead of the other steps: its results from 2026-11-16 and from its first session processed on time, its late sessions, and its daily correlation with the reversal run over the same sessions.

## Design points

- **The signals reuse what exists.** Residual momentum is a rolling sum of residuals scaled by volatility, as `ReversalSignal` is, with the sign reversed and the last 21 days left out. Whether it is a second configuration of one signal or a signal of its own is decided by which makes the look-ahead contract and the log entry clearer.
- **`Tables` on the new universe.** `Tables.stocks` is the stocks with residuals and its hedges are the sector ETFs. On Model B's residuals with no sectors, the hedge columns are the market alone.
- **The decile book is rebalanced daily, in slices.** `holding_slices` averages the last 21 daily books, so a slice is reset to equal weights each day and trades a little. The report states that turnover beside a book rebalanced once a month, without running the second as a path.
- **The config is new files.** Momentum's settings go in a config file of their own, as phase 7's do, so the frozen record's hash never moves while the run lasts.
- **The cost model on this universe** uses phase 7's rule for unadjusted prices. Under a stated substitute, such as a commission as a fraction of value, every net figure says so.

## Backlog items this phase takes up

- **"Other strategies on free daily data":** momentum, from its list. The item stays for the other candidates.
- **"Splits and dividends for MarketParquet's symbols from Alpaca":** its trigger is this phase's cost model, which has no unadjusted prices on this universe without it. The revision takes it up first, or runs momentum gross and at a flat cost per dollar traded and says so (see "What phase 7 found").
- **"Why the two sources' closes and volumes differ before 2023":** its trigger is this phase's decision record, since the one read of the years before 2016 rests on closes from years where the disagreement is unexplained.
- **"Combining strategies":** its trigger, a second strategy evaluated alone, arrives at this phase's review. It is the natural phase 9 and is not started here.

## Deliverables

1. The strategy's decision record, and record 0010 for the forward run.
2. The momentum signals in `statarb.signals`, registered by name, with their tests.
3. The runner that reads reversal's unread years once, and the momentum runner, each logging to `reports/phase-08/experiments.jsonl`.
4. `reports/phase-08/`: the report on reversal's unread years, the momentum report and their charts.
5. Reference docs current: architecture, data model, time discipline, glossary (momentum, skip month, residual momentum), requirements and the reproduction guide.

## Acceptance criteria

- The read of the unread years is logged once, reproduces with the runner's repeat option, and a second read is refused.
- Every momentum path reproduces exactly from its config, seed and pinned snapshot.
- Both signals pass the look-ahead contract in both forms, and the suffix test of phase 7.
- Every logged result of phases 0 to 7 reproduces unchanged.
- The report judges each path against the bar with the trial count the decision record sets, and shows the result with and without 2009.
- Each sensitivity is reported for both legs.

## Known pitfalls

- **A strong result is a reason to look for a bug.** The roadmap's principle holds here more than anywhere: a large-cap momentum Sharpe ratio well above the published record most likely means look-ahead through the suffix, the split basis or the universe.
- **The skip month is not optional.** The last month's return is reversal, which this project has measured. Leaving it in mixes the two signals.
- **Momentum's crashes are in the short leg.** The losers rebound together after a market fall, so a book that is dollar-neutral is not beta-neutral then. Report the book's market beta through time.
- **Delisting cuts momentum the other way.** Leaving out what a failed name loses after its last trade understates the short leg, where reversal's long leg was flattered.
- **Twenty-six years is one sample.** Reading reversal's unread years and running momentum on them are different uses of the same days. The first is a holdout; the second is not, and the report must not present it as one.
- **A monthly strategy cannot be confirmed by a short forward run.** Eight weeks is two rebalances.

## Out of scope

The combination with reversal. Low volatility and betting against beta. Any ML forecast of momentum. Industry momentum, which needs sectors. Intraday bars and futures. A forward run of momentum on the `listed` universe, which would need MarketParquet's subscription for new sessions and a record under 0008.

## What would change this brief

- **Phase 7 finds no route to unadjusted prices.** Net results then rest on a stated substitute for the commission and the spread's floor, or the phase stays gross and says less.
- **The cross-check finds the sources disagree materially.** The next phase is then about the data, not a strategy.
- **Published large-cap momentum since 2000 is near zero.** Either low volatility takes momentum's place, or momentum is kept only as the second leg and the combination follows sooner.
- **The forward run's review finds the pipeline does not match its backtest.** That comes first.
- **The second source fails on the first two counts.** The fallback is overnight and intraday reversal on Alpaca's data, the first candidate in the backlog's list, which needs none of it.

## Review questions

- Did reversal on the unread years look like reversal on 2016 to 2025, and what does that say about the earlier phases' choices?
- Does momentum earn a gross return on this universe, and what do costs and borrow leave of it?
- How much of the result is 2009, and how much is the short leg?
- Does the residual form do what its paper reports: less volatility and a smaller crash?
- How correlated are momentum and reversal, by year, and is a combination worth a phase?
