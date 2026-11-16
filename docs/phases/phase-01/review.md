# Phase 1 review: Factor model and residuals

Written on 2026-11-16 at the end of the phase. The numbers below are quoted from the generated reports, [`reports/phase-01/diagnostics.md`](../../../reports/phase-01/diagnostics.md) and [`reports/phase-01/window_sensitivity.md`](../../../reports/phase-01/window_sensitivity.md), built from phase 0's tables of the pinned snapshot with no new download. The numbers before the company-level sector moves were added are given [below](#company-level-gics-reclassifications), where they live.

## What was built

- **`src/statarb/factors/`**: the `FactorModel` interface and Model A, the ETF regression; a rolling least-squares fit from lagged cumulative sums, checked against a direct fit on every window; the volume-spike event flag; the runner `statarb.factors.build`, which writes `residuals.parquet` and the diagnostics report with its charts; and `statarb.factors.sensitivity`, which reruns Model A at three windows. The modules and what each reads and writes are in [the architecture](../../architecture.md); the residual table is in [the data model](../../data-model.md#residuals).
- **`config/factors.toml`**, read into frozen dataclasses that reject unknown or missing keys: the 252-day window and its 189-day minimum, the excess sector factor, the sector ETFs, the event flag and the report's settings. No date is written in code; the first residual date, 2016-10-04, follows from the data's start and the minimum.
- **Eight company-level sector moves** in `config/sector_changes.toml`, each dated from MSCI's GICS change notice and citing it (see [below](#company-level-gics-reclassifications)).
- **matplotlib** for the charts, drawn through its object interface and saved with no date or software metadata.
- **Tests**: the rolling fit against least squares, betas on *t* unchanged by data from *t* onwards, the look-ahead test on the residuals with phase 0's helper at three cut-offs, recovery of known betas, the sector splice, the market-only fallback, a split that is not a volume spike, strict config keys, the report's date-alignment helpers, a byte-identical report, and the window comparison on common rows.

The choices the drafted brief left open are settled in [its revision](brief.md#revised-at-the-start-of-the-phase): the sector factor is the ETF's return less SPY's, a stock that changes sector keeps its window, the intercept is estimated and not subtracted, and a sector with no ETF falls back to SPY alone.

## Acceptance criteria

| Criterion | Result |
|---|---|
| Mean cross-sectional correlation of residuals well below raw returns | Met: the average pairwise correlation among members, mean over years, is 0.268 for raw returns and 0.004 for residuals, and no year's residual value is above 0.006. |
| Look-ahead test | Met: `tests/test_factors.py::test_residuals_have_no_look_ahead` perturbs returns and volumes after three cut-offs, one inside a sector change, and `test_coefficients_on_t_ignore_data_from_t_onwards` does the same for the rolling fit alone. |
| A rebuild reproduces `residuals.parquet`, the report and the charts byte for byte | Met: two rebuilds from the pinned tables gave the same SHA-256 for the residual table and identical report and chart files; `tests/test_factor_report.py` checks the same on synthetic data, with no date or software chunk in the PNGs. |

## What the numbers showed

From [the diagnostics report](../../../reports/phase-01/diagnostics.md):

- **Coverage.** 1,221,618 residual rows for 500 candidates from 2016-10-04 to 2026-11-13. 94.9% of universe member-days have a residual; the rest are members without a year of history. 0.3% of rows fall back to the market alone, all before July 2019: Telecommunication Services had no ETF, and the Communication Services ETF, launched in 2018, needed most of a year of history before it could enter a window. The event flag marks 1.5% of rows.
- **Betas.** The median member's market beta is 0.99 to 1.06 in every year and its sector beta 0.89 to 0.98. The excess sector factor keeps the market beta at its usual meaning.
- **Common moves removed.** Average pairwise correlation falls from 0.268 to 0.004, and in 2020 from 0.528 to 0.006: the model removes common moves in a crisis year as well as a calm one.
- **Reversal at lag 1.** The daily rank correlation of a residual with the next day's is −0.0174 (t −6.2). Lags 2 to 5 are small, the largest −0.0052 at lag 5 (t −2.0), so the effect is almost all one day.
- **By year.** Negative in every year but one: 2022, at +0.0032 (t 0.3). See [what surprised us](#what-surprised-us).
- **By sector.** Negative at lag 1 in every sector, strongest in Materials, Health Care and Consumer Staples and weakest in Utilities, Real Estate, Energy, Financials and Information Technology.
- **By size.** The largest fifth by dollar volume reverses least, −0.0123, against −0.0154 to −0.0215 for the other four.
- **Event days.** After a volume spike the mean is −0.0233, but on 10,532 rows its t-statistic is only −1.3: the flag marks too few days to tell event reversal from normal reversal.
- **March 2020.** The residual standard deviation is 0.0436, almost four times 2017's 0.0114, while excess kurtosis is 6.1 against 37.4: in 2017 most days are quiet and a few idiosyncratic jumps make the tails, while in March 2020 every day is wide.

From [the window sensitivity report](../../../reports/phase-01/window_sensitivity.md), on the 760,400 member-days where every window has a residual: the 60-day window reverses less at lag 1 than 252 days, by +0.0017 (t 1.9), and its market beta moves five times as much from day to day (median 0.0152 against 0.0028). 126 days sits between and is not distinguishable from 252 (+0.0004, t 0.8). Residual spread and pairwise correlation barely move with the window. The year-long window costs nothing here and gives steadier betas.

## Company-level GICS reclassifications

The phase 0 sector history covered the three structural GICS changes since 2016, so a candidate moved between sectors at another time carried today's sector back to its earlier dates. Comparing the pinned Wikipedia revision with one at each year end from 2016 to 2025, read by hand, named fourteen candidates whose sector differed. Wikipedia only said which to check. Each was checked against MSCI's GICS change notices and, for 2016 to 2018, the Select Sector SPDR Trust's quarterly holdings filings with the SEC, which list each holding under its sector fund.

| Candidate | Found | Effective | Universe member-days that change |
|---|---|---|---|
| Harris (now L3Harris) | Information Technology to Industrials | 2018-01-02 | 0: a member from 2018-12-03 |
| CVS | Consumer Staples to Health Care | 2018-05-01 | 524 |
| Leidos | Information Technology to Industrials | 2021-03-01 | 63 |
| Teledyne | Industrials to Information Technology | 2021-09-01 | 0: never a member |
| Roper | Industrials to Information Technology | 2022-05-02 | 1,069 |
| CoStar | Industrials to Real Estate, apart from the March 2023 changes | 2023-07-03 | 651 |
| AppLovin | Information Technology to Communication Services | 2026-08-03 | 586 |
| DuPont | Materials to Industrials | 2026-08-03 | 1,992 |
| Danaher | Industrials to Health Care in the third quarter of 2016 | no primary date found | not changed: see below |
| Amphenol | listed in Industrials at the end of 2016 only; no notice found | not confirmed | not changed: a member from 2018-01-02 |
| Corning, Equifax, Snap-on, Stanley Black & Decker | no move: held in the same sector fund in every filing from 2015 to 2018 | | not changed |

MSCI's notices give the GICS change "as of the close of" a day, so each move is effective the next trading day. No S&P Dow Jones Indices notice was found for any of the eight, so the index date is taken to be MSCI's; in the 2018 structural change the two differed by a week, so this is an assumption, stated in the config. DuPont's results for the second quarter of 2026 give the same date as MSCI.

Danaher moved after its spin-off of Fortive in July 2016: the filings place it in the Industrial fund at the end of June and the Health Care fund at the end of September. No primary source found gives the day, so it stays on Health Care throughout, as the brief requires. Between about 65 and 128 of its member-days in 2016 carry Health Care while it was still in Industrials. None of them has a residual, since residuals start on 2016-10-04, but its betas into 2017 are fitted partly on the wrong ETF.

In all, 4,885 universe member-days (0.61%) change sector, across six tickers, and 18,216 residual rows change. The report barely moves. Before the moves, lag-1 reversal was −0.0175 (t −6.2), 2022 +0.0033, the largest size bucket −0.0122, event days −0.0226, average pairwise correlation of residuals 0.004 and market-only rows 3,301; in the window sensitivity report, 60 days minus 252 was +0.0017 with t 2.0. Every other change is in the fourth decimal place. Sector labels matter for the stocks they move, not for the aggregate.

## Returns that span missing bars

Phase 0 left six returns spanning more than one trading day. Two fall on member-days with a residual, of 760,400, and each sits in its windows among at least 189 other returns. They do not matter at this scale. Phase 2 should still not form a multi-day signal across one without knowing it does.

## What surprised us

- **The factor model adds reliability more than size.** Pooled, raw returns reverse at lag 1 as strongly as residuals, −0.0174 for both, but with t −4.2 against −6.2. The difference is in the spread of the daily values: 0.2067 for raw returns and 0.1416 for residuals. On a day when one sector moves, raw returns rank stocks mostly by sector, and the next day's ranking says little about reversal within it; removing the market and sector part leaves a cross-section in which reversal shows more consistently. By year, residuals reverse more strongly than raw returns in 2016, 2020, 2023 and 2025, less in 2017, 2018 and 2021, and equally in 2019 and 2024. A reversal signal on residuals should not expect a larger mean than one on raw returns, but a steadier one, which is what matters once its daily P&L carries costs. Phase 2 runs raw reversal beside it as a control.
- **2022 was the year without reversal.** Every year from 2016 to 2025 reverses at lag 1 except 2022, at +0.0032 (t 0.3), and raw returns show no reversal that year either (−0.0001). It is not the year with the most common movement: 2020 had more, and residuals reversed through it. A reversal strategy's P&L should be expected to have a flat or losing year without warning, and phase 2 reports P&L by year to see whether the hole carries through to trading.
- **Wikipedia's sector history is not a source.** Of fourteen candidates whose sector differed between year-end revisions, four had never moved, and Teledyne's move of September 2021 was still missing at the end of that year. The year-end comparison was useful to find candidates; every date in the config comes from MSCI.
- **The calm year has the fatter tails.** 2017's excess kurtosis is six times March 2020's: idiosyncratic jumps on quiet days, rather than a crisis, make residuals heavy-tailed. Phase 2's volatility scaling and phase 5's event features both need to allow for it.

## Comparison with Avellaneda and Lee

From the backlog item "Benchmark against Avellaneda and Lee", for this phase. Avellaneda and Lee (2010), read in the working-paper version of 2009-06-15, trade residuals of US stocks with market capitalisation above $1 billion at each trade date, 1,417 stocks on 2007-05-01, from 1997 to 2007. They regress each stock on its sector ETF over 60 days, or on principal components, and report trading results rather than residual autocorrelation, so the residual properties here have nothing in their paper to compare with directly. What can be set side by side:

- **Results and decay.** Their ETF-based strategy has a Sharpe ratio of 1.1 over 1997 to 2007, degrading after 2002; with actual sector ETFs from 2002 its average over 2003 to 2007 is 0.6. Their PCA strategy has 1.44 over 1997 to 2007 and 0.9 over 2003 to 2007. Phase 1 starts in 2016, nine years after their sample ends, and finds a small lag-1 reversal, −0.0174, negative in eight of the nine full years from 2017 to 2025. Phase 2 measures whether it pays.
- **Universe.** Theirs is point-in-time by market capitalisation and avoids survivorship bias; this one is the 300 most liquid of today's S&P 500 and keeps it ([phase 0 review](../phase-00/review.md#review-questions)).
- **Window.** They estimate over 60 days, "roughly one earnings cycle". On this sample 60 days gives slightly weaker reversal and noisier betas than 252, so the longer window stays.
- **Factor.** They regress each stock on its one sector ETF, with no separate market factor; Model A uses SPY and the ETF less SPY. Model A contains theirs: with equal betas on the two factors it reduces to one regression on the ETF.

Their trading rule, entry and exit on thresholds of an s-score, moves into the phase 2 brief with this review (below), and phase 2's review compares P&L.

## Review questions

**How negative is lag-1 residual autocorrelation, and how stable is it across years?** −0.0174 as a daily rank correlation (t −6.2), negative in every year except 2022, and strongest in 2018, 2023 and 2024. Lags 2 to 5 add little. It is small: a rank correlation of −0.017 explains a tiny share of the next day's cross-section, and whether it survives costs is phase 2's question.

**What does the factor model add over raw returns?** Common moves fall from an average pairwise correlation of 0.268 to 0.004. Reversal is no larger on residuals than on raw returns, pooled, but its daily values vary about a third less, so its t-statistic rises from −4.2 to −6.2. See [what surprised us](#what-surprised-us).

**Does reversal look different for the largest names, given ETF self-inclusion?** Yes: the largest fifth reverses least, −0.0123 against −0.0154 to −0.0215. Self-inclusion is one explanation, since the largest names make up much of their ETF and their residuals are understated; the largest names being more efficiently priced is another. The comparison with a sector factor that excludes the stock was a stretch goal and is not done; it goes to the backlog with a trigger at the phase 2 review.

**What does the residual distribution look like in March 2020 compared with a calm year?** Almost four times as wide (standard deviation 0.0436 against 0.0114), with every reported quantile about four times as far from the median, and less fat-tailed (excess kurtosis 6.1 against 37.4).

## Lessons this phase built in

Six rows added to [`docs/lessons.md`](../../lessons.md). Three have their episodes above: compare residuals with raw returns on the same rows, report reversal by year, and date sector moves from primary sources. Betas only from data before *t*, volumes on one share basis and charts without metadata are rules the phase built in with a test from the start.

## Reference docs

Confirmed current in this change: [architecture](../../architecture.md) (the factors package, its runners, `config/factors.toml` and matplotlib), [data model](../../data-model.md) (the residual table, checked against what the build writes), [time discipline](../../time-discipline.md) (phase 1 rows and notes), [glossary](../../glossary.md), [requirements](../../requirements.md) (both runners, measured on 2026-11-16), [reproducing the results](../../reproduce.md) (step 2), the [overview](../../overview.md) (the residuals stage and dated sectors) and the decision record index, which this phase leaves unchanged.

## Backlog walk

- **s-score threshold trading rule:** trigger phase 2, arrived. Moved into the [phase 2 brief](../phase-02/brief.md#variant-s-score-thresholds) as a variant, with Avellaneda and Lee's settings read from their paper. Deleted from the backlog.
- **Benchmark against Avellaneda and Lee:** the phase 1 part is the section above. Kept, with its trigger now the phase 2 review alone.
- **Multi-period optimiser:** kept; trigger the phase 4 review.
- **Documentation site:** kept; trigger when the repository goes public.
- **A second price source for cross-checking:** trigger the phase 1 review, arrived. Nothing in this phase points to a price error: the residual tails are explained by quiet-day jumps and March 2020, and the six gapped returns are known. Kept, with the trigger moved to the phase 2 review, where the first P&L would show what a price error costs.
- **Company-level GICS reclassifications:** moved into this phase's brief by the phase 0 review, and done above.
- **Sector factor excluding the stock:** added this phase; trigger the phase 2 review.

## What carries forward

- **To phase 2:** `residuals.parquet`, with the residual for *t* known after the close of *t*; the event flag; the decay over lags 1 to 5, to set against the holding-period sweep; raw reversal as a control; and 2022, to look for in P&L by year.
- **Danaher and Amphenol** stay on today's sector. A primary date for either would be a change to `config/sector_changes.toml` with a `Results:` footer.
- **The largest names** reverse least. Phase 2 reports P&L by size before deciding whether a sector factor that excludes the stock is worth building.
- **The dependency-upgrade criterion** from phase 0 is still untested: no upgrade has happened.
- **Survivorship** stays as stated in phase 0, and flatters a reversal strategy's long side.
