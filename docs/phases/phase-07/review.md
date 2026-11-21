# Phase 7 review: A second source and a universe with dead names

Written on 2026-11-21 at the end of the phase, during the forward run. The numbers below are quoted from the generated reports: the [quality report](../../../reports/phase-07/data_quality.md), the [cross-check](../../../reports/phase-07/cross_check.md), the [universe report](../../../reports/phase-07/universe.md) and the [survivorship report](../../../reports/phase-07/survivorship.md), with its log, [`reports/phase-07/experiments.jsonl`](../../../reports/phase-07/experiments.jsonl). They rest on the MarketParquet snapshot of 2026-11-20 and, where Alpaca is named, the Alpaca snapshot of 2026-11-16. "This source" is MarketParquet's archive. Returns on it are price returns: they hold no dividends ([decision record 0009](../../decisions/0009-rules-for-marketparquets-data.md)).

## What was built

- **The adapter and the first snapshot.** `statarb.data.marketparquet` lists and downloads the archive's daily stock and ETF files, eight at once on one pace under the key's rate limit, and keeps them as served in a snapshot of day files, a third layout beside `raw` and `bars`. Each file is checked against its listed size and, where the storage host's `ETag` is an MD5, against that. The manifest keeps each file's `ETag` and `Last-Modified` and lists the files modified after the download began. `statarb.data.marketparquet_build` downloads a snapshot and checks the pinned one. The first holds 13,524 files, both datasets from 2000-01-03 to 2026-11-19; every file's MD5 matched and none was modified during the download.
- **The quality report,** `statarb.data.marketparquet_quality`: sessions against the exchange calendar, schemas and symbols per session from the files' footers, suffixed symbols, bars that cannot be right, moves the size of a split and symbols that vanish and reappear.
- **The cross-check,** `statarb.data.cross_check` and its runner `statarb.backtest.source_check`: the two sources' bars for the 515 existing tickers with Alpaca's put on the split basis of its download, and the phase 2 headline run on each source's prices for the same universe.
- **The rules for this source's data,** decision record 0009.
- **This source's tables and its universe,** `statarb.data.marketparquet_tables`: `prices`, `returns` and `universe_listed` under `data/derived/marketparquet/`, apart from Alpaca's tables, and the universe's report.
- **The engine's option for names whose bars stop,** `close_after` on `statarb.backtest.engine.run`, off unless asked for, and two keys in the trial id, `universe` and `close_after`, left out when null.
- **The survivorship measurement,** `statarb.backtest.survivorship`: seven logged paths on three universes of this source, beside the existing universe's two.
- **Config:** everything is in `config/marketparquet.toml`, which the forward run's frozen record does not hold. No library was added and no pin moved.
- **Tests:** the adapter on synthetic day files with the network blocked, the addresses it builds and where the key goes; each report's checks; a read outside the sample failing on purpose-built files; the suffix test for the universe and for every path's target book; look-ahead tests for the universe and for Model B fitted on the members to date; the engine's option on and off; every logged path of phases 2 to 6 keeping its id.

The brief's revision, ["Found at the start"](brief.md#found-at-the-start), holds what the first requests to the source showed.

## Acceptance criteria

| Criterion | Result |
|---|---|
| A rebuild from the pinned snapshot reproduces this phase's tables byte for byte and every logged metric exactly | Met: a second run of `statarb.data.marketparquet_tables` wrote the three tables and the universe's report with the same hashes, every report of the phase rebuilt unchanged, and a rerun of the seven paths gave all 35 logged entries' metrics exactly. |
| Every logged result of phases 0 to 6 reproduces unchanged, and `statarb.paper.frozen` finds the frozen record unchanged | Met as far as it was run. The frozen record matches. `statarb.backtest.run --no-log` and `statarb.backtest.cost_run --no-log` rewrote `reports/phase-02/` and `reports/phase-03/` with no change, and the cross-check's rerun of the phase 2 headline on Alpaca's tables gives the logged metrics exactly at every cost level. The runners of phases 4 to 6 were not rerun; the suite's exact-reproduction tests for them pass. |
| The cross-check states, by year, how often the two sources agree and where they do not, and explains each kind of disagreement or lists it as open | Met: the report gives the counts, and ["What the numbers showed"](#what-the-numbers-showed) explains three kinds and lists two as open. |
| The suffix test passes for the universe, the signals and the positions | Met: `tests/test_marketparquet_tables.py` for the universe and `tests/test_survivorship.py` for every path's target book on the two universes the rule covers, both unmarked. |
| No return before 2016 and no day from 2026-11-16 on is read by any runner, and a test checks the cut | Met. Every runner reads by `[sample]` of the config: bars from 2016-01-01, footers alone before it, no file opened from 2026-11-16. A test runs the quality report on files that fail if read outside the cuts, and another requires the config's cuts to be those. The measurement reads nothing after the development end, 2025-11-13. The quality report, the cross-check and the tables do read the phase 5 holdout year, as the brief allows. |
| The survivorship report gives the difference between universes 3 and 4 for each form of the signal, with the legs apart, and says which way the missing delisting returns would move it | Met: "What each step adds" and "After the last bar". |

## What the numbers showed

Over development, from the first signal on 2017-01-03 to 2025-11-13, at the phase 2 headline's settings. `existing` is today's S&P 500 on Alpaca's total returns, rerun over development and not logged again. On this source, `candidates` is today's S&P 500, `survivors` every listed symbol still trading at the download, and `listed` every listed symbol of the day.

| Gross Sharpe | Returns | Model B's residuals | Model A's residuals |
|---|---|---|---|
| existing | 0.688 | | 0.339 |
| candidates | 0.577 | 0.955 | 0.274 |
| survivors | 0.325 | 0.275 | |
| listed | 0.391 | 0.369 | |

- **Survivorship does not flatter the reversal on these universes.** `survivors` less `listed` is −0.066 of gross Sharpe on returns and −0.094 on Model B's residuals: leaving out the names that later delisted makes the result slightly worse. The gross return falls by 1.09% and 0.89% a year.
- **It cuts by leg, as the brief expected, but the short leg is the larger.** Leaving the dead names out adds 0.21% and 1.83% a year to the long leg and takes 1.30% and 2.72% from the short leg. Names that later delisted are about 8% of name-days in each leg of `listed`, 8.20% long and 7.80% short on returns, so the book is not long the failures more than it is short them.
- **The candidate list is the larger effect.** `survivors` less `candidates` is −0.252 on returns and −0.680 on Model B's residuals. The two universes share a source, a return basis and the rule that only names alive today are ranked. They differ in who is ranked: every surviving listed symbol, or the 503 that are in the S&P 500 today.
- **The source costs 0.07 to 0.11.** `candidates` less `existing` is −0.111 on returns and −0.065 on Model A's residuals. On the same universe and the same names, with only the prices changed, the cross-check puts the difference at 0.014: the headline's gross Sharpe is 0.334 on this source against the logged 0.348, the two runs' daily returns correlate 0.991, and their legs hold 96.5% and 97.3% of the same names. The rest of the gap here comes from ranking the universe on this source's dollar volume and, for the raw form, from the missing dividends.
- **No path earns anything net.** At 5 bps one way every path's net Sharpe is between −0.95 and −2.44, as phase 2 found for the existing universe.
- **The wider universes part from the S&P 500 after 2021.** By year, Model B's residuals on `candidates` and on `listed` have gross Sharpe ratios within 0.4 of each other from 2017 to 2021, except in 2019. In 2022 they are −0.493 and −1.771, and `listed` is lower in each year after.
- **After the last bar.** The engine closed 9 and 11 holdings on `listed` because their bars had stopped. Two of each meet the sensitivity's test, a fall of more than 10% over the last 21 bars, and a further loss of 55% on those moves each leg by about 0.1% a year, in opposite directions. The test picks 1,551 symbols in the whole source; the book held two of them when they stopped.

What the source holds:

- **Sessions.** No session of the exchange calendar is missing from either dataset and no file falls on another day.
- **Dead names.** 52.7% of the stock symbols with a bar in 2016 carry the delisted suffix, 7.3% of those in 2026. Ranked by dollar volume they matter less: suffixed symbols are 17.36% of the listed universe's member-days in 2016 and 0.73% in 2026.
- **The ETF dataset has no suffixed symbol** in any year from 2016, so it is not a set of ETFs free of survivorship. The factor ETFs and SPY are alive, so nothing here turns on it.
- **Bars.** No price is missing or not positive and no high is below its low. 155 stock bars have an open outside the day's range and 4 a close, all in 2021, 2023 and 2024. The rules drop 5,265 bars in 319 symbols, almost all for zero volume, of 18.3 million.
- **Absences.** 6,039 of 14,120 stock symbols miss at least one session between two of their bars, most often one session. Among the listed universe's members the case is rare, which is why the engine's option matters little.
- **The universe.** 300 symbols a month, 820 ever members over the sample, about 14 entering at each ranking. About 99% of member-days are symbols of one to four letters. Only 70% to 84% of the existing universe's member-days, by year, are members here.

How the two sources agree, for the 515 existing tickers:

- **Dividends are absent, as the source documents.** On 98.8% of Alpaca's cash days this source's return is Alpaca's price return.
- **Spin-offs are folded into the adjustment, and only some.** Of 47 cash days where the cash is over 5% of the price, this source's return is nearer Alpaca's total return on 22. 34 tickers sit on another basis than Alpaca's splits give for a stretch that ends on a date. Explained: the source says it folds a large spin-off into its split factor case by case.
- **The days of March 2020.** Eight of the ten days on which the most tickers part are 2020-03-09 to 2020-03-19. Likely explained by different closing prints on days with market-wide halts; not verified against a third source.
- **Open: the closes are not always the same close before 2022.** For stocks, 0.4% to 1.0% of closes are more than 1 bp from the ticker's basis in each year to 2020, and under 0.1% from 2022. For the ETFs it is 5.7% to 22.0% through 2021 and none from 2023.
- **Open: volumes are lower here before 2023.** The median of this source's volume over Alpaca's is 0.89 to 0.94 in each year to 2022 and 1.00 from 2023.

## What surprised us

- **The sign.** Every review since phase 0 said that a universe without dead names flatters a strategy that buys recent losers. Measured, it does not: the universe with the dead names does slightly better. The argument held for the long leg, where the failures are bought, and missed the short leg, where a name that later delisted and was rising into an acquisition or a squeeze was just as often sold. What the earlier results carry is a different bias, in the next point.
- **Today's S&P 500 is the stronger filter.** A list of today's index members is not only a list of survivors: it is a list of companies that grew large enough to be in the index. Reversal on those names, including in the years before they joined, does better than on every surviving listed stock by several times the survivorship effect. The phase 0 review named survivorship; the bias that matters is the choice of today's index as the candidate list, and "survivors less listed" does not measure it.
- **Model B on today's S&P 500 at 0.955.** Its gross return, 6.16% a year, is like the raw form's 7.55%, at half the volatility, 6.45% against 13.10%. Phase 4 found Model B's residuals gave a steadier book with less gross return than Model A's on the existing universe, where its decile sort's gross Sharpe was 0.66 against 0.71. That path held for two days, was costed per dollar of capital and used a fit on all 500 candidates; this one holds for one day and is fitted month by month on the members to date. No logged path was like for like when this review was written, so the difference was left unexplained; an eighth trial, [added after the review](#added-after-the-review-an-eighth-trial), explains it.
- **A symbol is not a company through time, in either source.** Alpaca gives a renamed company's history under today's ticker. This source carries a plain rename under the new symbol too, but holds some companies twice, the earlier years also under the old symbol with the suffix, as a series that tracks the other closely without equalling it. At a month end in 2016 about 7 pairs of the listed universe's 300 members correlate above 0.98, and about 1 from 2023; some are share classes. A company held twice is one delisting and one survivor in this measurement.
- **Alpaca holds the dead names.** A probe of 60 suffixed symbols found Alpaca's bars for all of them and corporate actions for about half. The premise of the purchase was that no free source holds dead names' prices. What this source adds is the list of who traded on each day, which Alpaca does not give; the prices could have come from either. The probe is not a snapshot and supports no result.
- **The archive moves during the day, and a symbol's marker can be look-ahead twice.** Files for October and November were modified at three times on one day, so a snapshot is not taken at one instant; the manifest now records what the host says of each file. And a fifth letter Q, the exchange's bankruptcy marker, is on some symbols' whole history, as the suffix is. No rule reads either.
- **A rule accepted before its contract was read.** Decision record 0009 first put the source behind `PriceSource` with a split ratio of 1 on every day. The protocol's contract tests require each split on its ex-date and a round trip to unadjusted prices, which the archive cannot give. The rule was corrected the day it was accepted, before any code rested on it.

## Added after the review: an eighth trial

Stated on 2026-11-22, before the path ran. The brief fixed seven trials. This adds one, on the owner's decision, to explain the result above that the review left unexplained: Model B's residuals on today's S&P 500 at a gross Sharpe ratio of 0.955.

- **The path:** the phase 2 headline's settings (lookback 1, holding 1, decile 0.1, fill at the open of *t+1*) on the existing universe and Alpaca's total returns, over development, with Model B's residuals in place of Model A's. The residuals are phase 4's stored table, fitted on every candidate throughout, put into the tables as phase 4 puts them. Nothing else differs from the logged phase 2 headline.
- **What it separates.** The 0.955 differs from phase 4's Model B decile sort, 0.66, in three ways at once: a one-day holding period against two, a fit month by month on the members to date against one on every candidate, and this source against Alpaca. This path has the one-day holding period with phase 4's fit and Alpaca's prices. If it is near 0.955, the holding period explains the gap. If it is near phase 4's figure or Model A's, the fit and the source do.
- **How it counts.** It is a new position path, so a trial: logged in this phase's log with Alpaca as its source and no universe key, since its universe is phase 0's. Nothing is chosen from it, and no setting is changed after it is seen.
**The result,** from the logged run at `c73fd78` on 2026-11-22, a clean tree, quoted from the [survivorship report](../../../reports/phase-07/survivorship.md):

- **The holding period explains it.** On the existing universe, reversal on Model B's residuals held for one day has a gross Sharpe ratio of 1.154 over development: a gross return of 7.62% a year at a volatility of 6.61%. That is above the 0.955 on this source, not below it. So Model B at a one-day holding period is strong on today's S&P 500 whatever the fit and the source, and phase 4's 0.66 was the same residuals held for two days.
- **The fit and the source cost about 0.2.** `candidates` less `existing` on Model B's residuals is −0.198 of gross Sharpe and −1.46% a year of gross return, beside −0.111 on returns and −0.065 on Model A's residuals. The two Model B paths differ in the source and in the fit, and this does not separate those.
- **It is the highest gross Sharpe of the ten paths and earns nothing net.** At 5 bps one way its net Sharpe is −2.160: it turns over 1.711 of gross a day, like every other path here, and its break-even cost is 1.71 bps.
- **By year it is the first four years.** Its gross Sharpe is 2.290, 3.110, 0.374 and 2.953 in 2017 to 2020, and between −0.574 and 1.805 in each year after, negative in 2021 and 2022.
- **What it changes.** Nothing about survivorship, and no verdict: no path keeps a net edge. It replaces "unexplained" above with a finding about Model B: its residuals reverse more cleanly than Model A's over one day and lose that by the second. The rerun reproduced the 35 earlier entries' metrics exactly, and the repository's logs now hold 200 trials.

## Review questions

**How closely do the two sources agree, and what explains where they do not?** Closely on returns and from 2023 almost exactly: 99.2% of price returns on days with nothing going ex agree within 0.0001, and closes on one split basis agree on 93.2% of symbol-days in 2016 and 99.7% in 2026. Dividends, folded spin-offs and the halts of March 2020 explain three kinds of disagreement. Differing closes and lower volumes before 2022 to 2023 are open. The near-exact agreement of recent years fits a shared upstream, so it proves less than it seems.

**How much of each earlier result was survivorship, by leg and by year?** Of survivorship as the brief defines it, none that flattered: −0.066 and −0.094 of gross Sharpe, with the long leg helped and the short leg hurt by more. By year the sign varies and no year stands out. Of the candidate list, a good deal: 0.25 to 0.68 of gross Sharpe, on Model B's residuals much of it in 2019 and from 2022 on. This measures the phase 2 headline's settings alone, gross and at flat costs; the results of phases 3 to 6 were not rerun on these universes.

**Which of the source's gaps could be closed by a rule, and which stay as stated assumptions?** Closed by a rule: bars with zero volume and bars that contradict themselves are dropped, and a held name whose bars stop is closed. Closable from Alpaca's records, and deferred: splits on their ex-dates and dividends for many delisted names. Stated assumptions: which spin-offs are folded, the kind of security, a company held under two symbols, and everything after a last bar.

**Is the new universe fit to carry a strategy with costs, or does the lack of unadjusted prices rule that out?** Not under phase 3's cost model, which reads price levels for the commission and the spread's floor. It carries a strategy gross, or net at a flat cost per dollar traded. Unadjusted prices would come from joining Alpaca's actions, which is now a backlog item.

**What did the first read of the day files show about the years before 2016 that phase 8 should know, without any return being computed?** From footers alone: both datasets hold every session from 2000-01-03, on two schemas that differ only in the name and type of the day's column. The stock dataset grows from a mean of 2,704 symbols a session in 2000 to 6,257 in 2015, and one session in 2000 has 1,597, about 60% of that year's mean. The ETF dataset has a mean of 67 symbols a session in 2000 and 1,382 in 2015. Whether the dead names' share before 2016 is like the share after it is unread.

## Lessons this phase built in

Seven rows added to [`docs/lessons.md`](../../lessons.md). Four have their episodes above: a marker a source applies at the download is a key and never an input; the list of candidates is itself a filter, measured apart from survivorship; a seam's contract tests are read before a record promises the seam; and a snapshot of an archive that moves records what the host said of each file. The others are rules built in with a test from the start: a statistical factor model is fitted on the names known by the day; a path on another universe has another trial id, and every earlier path keeps its own; and a test of a failure bounds what was asked for, never how fast a thread noticed, after a test that counted fetches failed under load.

## Reference docs

Confirmed current in this change: [architecture](../../architecture.md) (the adapter, the five runners, the comparison module, `config/marketparquet.toml`, the seam the source stays outside), [data model](../../data-model.md) (the snapshot of day files, this source's tables, the log's new keys), [time discipline](../../time-discipline.md) (the notes for phase 7), [glossary](../../glossary.md), [requirements](../../requirements.md) (each runner, measured on 2026-11-20 and 2026-11-21), [reproducing the results](../../reproduce.md) (steps 8 to 12), the [overview](../../overview.md) (the data and universe stages), the [lessons](../../lessons.md) and the README's invariants. Two decision records: [0008](../../decisions/0008-marketparquet-archive-as-a-paid-price-source.md), written before the phase, and [0009](../../decisions/0009-rules-for-marketparquets-data.md), with 0008's point on the interface amended by it.

## Backlog walk

Two items left the backlog when the phase started, as the brief says: **"A second price source for cross-checking"**, which is the cross-check, and **"Survivorship-free prices"**, which the survivorship measurement takes up on an own universe from a paid source without delisting returns.

- **Point-in-time index membership:** trigger this review, if a result still turns on which stocks were in the index. It does: the choice of today's index as the candidate list is the largest effect measured here. No source of constituent history was found. Kept, with what this phase found added and the trigger moved to the decision record that takes up the next strategy.
- **Cash-out for names whose prices stop:** not yet due. The rule is built as an engine option and its case measured as rare; whether it becomes the default for the existing universe is still the forward run's review's to decide. Kept, with the measurement added.
- **Closes from the listing exchange's closing auctions:** not yet due. The cross-check found that the two sources' closes differ before 2022, most for the ETFs, which bears on it. Kept, with that added.
- **Tolerance for a rebuild from another snapshot:** not yet due. It now applies to this source too, whose archive is corrected more often. Kept, with that added.
- **Splits and dividends for MarketParquet's symbols from Alpaca:** new, from rule 7 of decision record 0009.
- **Documentation site, An independent short-term reversal series, Measured effective spreads, Other strategies on free daily data, Combining strategies, Intraday data, Other universes, Model diagnostic charts** and **Cross-phase summary:** not yet due.

## What carries forward

- **To phase 8:** the tables and the listed universe on this source, the rules of decision record 0009, and the engine's option at five sessions. The years before 2016 are unread, and the record that takes up the strategy says what they are for. A strategy there runs gross or at flat costs until unadjusted prices exist.
- **The candidate list is a bias to state with every earlier result.** Phases 2 to 6 ran on today's S&P 500. This phase measured the headline's settings on wider universes and found them worse by more than survivorship explains. Whether that holds for the cost-aware paths of phases 3 to 5 is unmeasured.
- **The two open disagreements** between the sources, closes and volumes before 2022 to 2023, are unexplained. The ETFs' closes are Model A's regressors, so a result that leans on Model A on this source before 2022 should be read with that in mind.
- **The measurement leaves out delisting returns.** Its one sensitivity moved nothing, because the book held almost no name when it stopped; a strategy that holds failing names for longer would not be so lucky.
- **The snapshot cannot be downloaded again as it was.** The archive is rewritten daily and carries no version, so every result here rests on the pinned snapshot in the raw store, which has to be backed up outside the repository as Alpaca's are.
- **The tolerance for a rebuild from another snapshot** is unmeasured for both sources.
- **The dependency-upgrade criterion** from phase 0 is still untested: this phase added no library and moved no pin.
