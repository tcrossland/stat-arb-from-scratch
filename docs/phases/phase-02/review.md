# Phase 2 review: Baseline signal and backtest

Written on 2026-11-16 at the end of the phase. The numbers below are quoted from the generated report, [`reports/phase-02/backtest.md`](../../../reports/phase-02/backtest.md), and its log, [`reports/phase-02/experiments.jsonl`](../../../reports/phase-02/experiments.jsonl), built from the phase 0 and 1 tables of the pinned snapshot with no new download. Unless a line says otherwise, a number is for the headline configuration: residual reversal over one day (*n* = 1), held one day (*k* = 1), filled at the open of *t+1*, with returns per dollar of gross exposure from 2017-01-03 to 2026-11-13.

## What was built

- **`src/statarb/signals/`**: the `Signal` interface, its registry, and three signals behind it: residual reversal, raw reversal as the control, and Avellaneda and Lee's s-score with the betas it hedges at. Each declares the tables it reads.
- **`src/statarb/backtest/`**: the engine, which fills a target-weights panel at the close of *t*, the open of *t+1* or the close of *t+1* and books P&L, costs, borrow and turnover per dollar of gross; the `CostModel` interface with a flat cost; the `PortfolioRule` interface with the decile rule in *k* overlapping slices and the s-score's threshold rule, which carries hedged positions from day to day; metrics; the experiment log with its run state; the trial count and deflated Sharpe ratio; and the runner `statarb.backtest.run`, which sweeps every configuration, runs the placebo and writes the report. The modules and what each reads and writes are in [the architecture](../../architecture.md); the log's fields are in [the data model](../../data-model.md#experiment-logs).
- **The config overlay** in `statarb.config`, and **`config/backtest.toml`**, read into frozen dataclasses that reject unknown or missing keys. No date is written in code.
- **Tests**: the hand-built three-stock, five-day example; fill delay, untradable names and missing returns; open-to-open returns across a split and a dividend; holding slices; break-even cost; the s-score against a hand calculation, its centring and its trading rule with entry-day hedges; a placebo over 200 seeds; exact reproduction and a byte-identical report; the look-ahead contract over every registered signal, and the engine's targets and P&L at every fill; strict config keys, the overlay and the trial count.

The choices the drafted brief left open are settled in [its revision](brief.md#revised-at-the-start-of-the-phase). No library was added.

## Acceptance criteria

| Criterion | Result |
|---|---|
| The toy example matches hand calculations exactly | Met: `tests/test_backtest.py::test_hand_built_three_stock_five_day_example`. |
| The placebo test passes | Met on synthetic data over 200 seeds (`test_reversal_earns_and_a_shuffled_signal_does_not`), and on the real data over 100 seeds: mean 0.00% a year, standard error 0.14. |
| Results reproduce exactly from config and seed | Met: the logged run and an earlier `--no-log` run on the same tables wrote identical report and chart files, and `test_report_and_charts_are_identical_on_a_rerun` checks the same on synthetic data. |
| The report states the break-even cost against a realistic retail cost | Met: 0.74 bps one-way against an assumed 5 bps. |
| Every log entry records its `run_state`, and the log comes from a clean tree | Met: all 735 entries name commit `b48c6be` with no uncommitted changes, no overlay, and the Alpaca snapshot of 2026-11-16. |

## What the numbers showed

- **The edge is small and costs remove it.** Gross Sharpe 0.35, 3.42% a year. Break-even cost 0.74 bps one-way, so at the assumed retail cost of 5 bps the net Sharpe is −1.87. Turnover is 1.70 a day, close to replacing the whole book.
- **Execution delay.** Gross Sharpe is 0.31 filled at the close of *t*, 0.35 at the next open and 0.21 at the next close: a full day's delay costs about a third of the gross return (3.02% to 1.98% a year). The same-close fill pays 5 bps of slippage on top and is the worst net of the three at every cost level.
- **Holding period.** Holding longer helps at every cost level above zero. From *k* = 1 to 5, turnover falls from 1.70 to 0.56 and break-even rises from 0.74 to 3.66 bps; net Sharpe at 5 bps rises from −1.87 to −0.25, still negative.
- **Lookback.** A three-day lookback beats one day at every holding period: gross Sharpe 0.80 against 0.35 at *k* = 1. Volatility scaling lowers gross Sharpe in every configuration at the next-open fill but one, where the two tie.
- **By year.** Gross P&L is negative in four years of ten: 2019, 2021, 2022 and 2025. 2022 is the worst, −7.88%, with 2019 close behind at −6.07%. The best years are 2023 and 2018. There is no steady decay over the decade.
- **Long and short sides.** The long side earns 13.12% a year and the short side loses 9.70%, per dollar of gross. Each side alone is mostly the rise of the stocks it holds, large in a universe of today's survivors; the book is dollar neutral, with a mean net market beta of 0.008, and the edge is the difference.
- **Residual against raw.** Across all configurations the residual signal's median gross Sharpe is 0.63 against raw's 0.51 at the next-open fill, and it is higher at every lookback above one day. At *n* = 1 raw reversal earns more at three holding periods of four, 0.69 against 0.35 at *k* = 1.
- **Factor exposure.** At the close-of-*t+1* fill, where P&L splits into Model A's parts, the residual part earns 2.56% a year and the fitted market and sector part loses 0.58%.
- **By size.** The two most traded fifths earn most of the gross P&L, 1.86% and 1.47% a year of the total; the least traded fifth earns nothing.
- **By sector.** Health Care earns most and Information Technology loses most.
- **The s-score rule.** Gross Sharpe 0.49 at the next-open fill, turnover 0.25 a day, a median of 109 open positions, with hedges 28.7% of gross. Break-even is 2.47 bps, and net Sharpe at 5 bps is −0.43.
- **Missing data.** Two of the phase 0 returns that span more than one trading day reach a signal, both one-day signals in 2017. The headline book holds a name with no return that day on 2 name-days, booked at zero.

## What surprised us

- **The same-close fill is not the flattering one.** The brief warned that filling at the close used to compute the signal can create most of a reversal backtest's edge. Here it earns less gross than the next open, 0.31 against 0.35 at the headline and 0.53 against 0.63 at the median residual configuration. The close-of-*t* book holds the overnight move straight after the signal, the next-open book holds the overnight move a day later instead, so the first overnight move earns less than the second: the reversal shows after the next open more than over the first night. The pitfall still holds in principle; on this data the fill-timing sweep shows it is not where the edge comes from.
- **The largest names earn the most, though they reversed least.** Phase 1 found the weakest lag-1 reversal in the largest fifth by dollar volume. In P&L the top two fifths earn most of the gross return. One explanation, not tested here: a rank correlation weights every stock equally, while a decile book's P&L comes from the few names whose residuals moved most, so a weak correlation among large names need not mean a weak book among them. Either way, a statistic about returns is checked in P&L before it decides a design (below).
- **Holding longer and looking back further both help, though phase 1 found the effect almost all at lag 1.** Gross Sharpe rises from *k* = 1 to *k* = 5 and from *n* = 1 to *n* = 3. Phase 1's lags 2 to 5 were small but all negative, and averaging over formation days or summing over three days of residuals reduces the book's volatility more than it reduces its return. Lags too small to matter alone in a correlation can still add to a book.
- **2022 is not alone.** Phase 1 found 2022 the only year without lag-1 reversal. In P&L, 2019, 2021 and 2025 also lose. A daily correlation and a decile book weight days and names differently, so a year can reverse on average and still lose.

## Comparison with Avellaneda and Lee

From the backlog item "Benchmark against Avellaneda and Lee", for this phase. Their ETF-based strategy, as read for the [phase 1 review](../phase-01/review.md#comparison-with-avellaneda-and-lee), has a Sharpe ratio of 1.1 over 1997 to 2007 and 0.6 over 2003 to 2007, after 5 bps one-way. Their fill, at the close of the signal day with 5 bps of slippage, is this report's close-of-*t* row at 0 bps: net Sharpe −0.40, gross 0.51. The gap:

- **Sample.** Theirs ends in 2007 and already shows decay after 2002; this one starts nine years later. The s-score's gross Sharpe here, 0.49, is below their net figure for 2003 to 2007.
- **Universe.** Theirs is every US stock above $1 billion at each date, 1,417 on 2007-05-01, point in time. This one is the 300 most liquid of today's S&P 500. Survivorship flatters this one, so it does not explain the gap; the narrower, larger universe may, though the size split here does not show larger names earning less.
- **Residuals.** Their s-score runs on residuals from a 60-day regression on the ETF alone; here the s-score's own regression is 60 days on SPY and the ETF less SPY, as the brief chose.
- **Rule.** The thresholds, the 30-day limit on mean-reversion time and the centring are theirs. Their volume-adjusted variant is not run.

The s-score trades about a seventh as much as the headline decile book and has more than three times its break-even cost, which is the property the brief added it for. At 5 bps it still loses.

## Review questions

**What is the gross Sharpe, and what is the break-even cost?** 0.35 and 0.74 bps one-way. A realistic retail cost of 5 bps is almost seven times the break-even.

**How much of the edge is lost per day of execution delay?** About a third of the gross return from the close of *t* to the close of *t+1* at the headline. Across configurations a day's delay costs much less, since most hold longer than a day: the median residual configuration has gross Sharpe 0.53 at the close of *t* and 0.58 at the close of *t+1*. Within that day, the next open is the best fill.

**Which holding period maximises net Sharpe at a realistic cost, and how does it compare with the decay of residual autocorrelation?** *k* = 5, for every residual lookback without scaling, at 5 bps. Phase 1's autocorrelation is almost all at lag 1, which argued for short holding; the P&L says turnover dominates and the small lags still add. **The baseline holding period that later phases compare against is *k* = 5**, with the headline signal (residual, *n* = 1) and the next-open fill: net Sharpe −0.25 at 5 bps, break-even 3.66 bps. Phase 2's report keeps *k* = 1 as its headline, as its config says; phase 3 sets the baseline in its own config when it revises its brief.

**How did the edge evolve over time? Does 2022 show?** No steady decay: the best years are 2023 and 2018, and 2026 so far is positive. 2022 shows as the worst year, −7.88% gross, but 2019, 2021 and 2025 also lose.

**How much of the P&L comes from the long side versus the short side?** The long side 13.12% a year and the short side −9.70%, per dollar of gross, each mostly the rise of the stocks it holds. Survivorship flatters the long side, which buys recent losers from a list of stocks that are known to have survived; this phase cannot measure by how much.

**Does the residual signal earn more than the raw-return control, and do the largest names behave differently?** Yes at every lookback above one day, and by median across configurations; mostly not at one day, where raw reversal earns more, with more volatility. The largest names earn more than the rest, the opposite of what their weaker lag-1 reversal suggested.

**How many configurations were tried, and does the best one still look meaningful after accounting for that?** 147 position paths, the repository's first trials, each at five cost levels. The best gross Sharpe, 0.85 (residual, *n* = 3, *k* = 3, next open), against 0.43 expected from the best of 147 with no edge, has a deflated Sharpe probability of 0.915: suggestive of a gross edge, not conclusive at 95%. The best net Sharpe at 5 bps, 0.21 (*n* = 3, *k* = 5), has a t-statistic of 0.66 before any allowance for selection, which is no evidence of a net edge.

## Lessons this phase built in

Seven rows added to [`docs/lessons.md`](../../lessons.md). One has its episode above: a statistic about returns is checked in P&L before it decides a design. The others are rules the phase built in with a test from the start: the look-ahead contract over every signal, the engine's look-ahead test, the placebo, the config overlay, the run state in every log entry, and the trial count across every log.

## Reference docs

Confirmed current in this change: [architecture](../../architecture.md) (the signals and backtest packages, their seams, the runner, `config/backtest.toml` and the overlay), [data model](../../data-model.md) (no stored table; the experiment log's fields), [time discipline](../../time-discipline.md) (phase 2 rows and notes), [glossary](../../glossary.md), [requirements](../../requirements.md) (the runner, measured on 2026-11-16), [reproducing the results](../../reproduce.md) (step 3), the [overview](../../overview.md) (the signal and portfolio stages) and the decision record index, which this phase leaves unchanged.

## Backlog walk

- **Benchmark against Avellaneda and Lee:** trigger the phase 2 review, arrived. Done in the section above, the last review its trigger names. Deleted from the backlog.
- **Sector factor excluding the stock:** trigger the phase 2 review, arrived. The largest names do behave differently in P&L, but by earning more, so the understated residuals the item worried about do not show as a cost. Moved to the [phase 4 brief](../phase-04/brief.md#model-b), where Model B gives a second answer to the same question. Deleted from the backlog.
- **A second price source for cross-checking:** trigger the phase 2 review, arrived. Nothing in the P&L points to a price error: no year or sector stands out in a way a bad price would explain, the gapped returns reach two signals and a held name lacks a return on two name-days. A price error matters most once a strategy is run forward on new data. Kept, with the trigger moved to the phase 5 review.
- **Multi-period optimiser:** kept; trigger the phase 4 review.
- **Documentation site:** kept; trigger when the repository goes public.
- **An independent short-term reversal series:** added this phase; trigger the phase 3 review.

## What carries forward

- **To phase 3:** the baseline, residual reversal with *n* = 1, *k* = 5 and the next-open fill, whose break-even of 3.66 bps sits below the assumed retail cost of 5 bps; the cost model decides how far below. The s-score rule, with less turnover, runs beside it.
- **The three-day lookback** earns more than one day at every holding period, but was chosen from 147 trials after seeing them. A phase that adopts it says so and counts the trials.
- **The fill.** The next open is the best fill at the headline; the cost model prices fills at the open.
- **Survivorship** stays as stated in phase 0, and flatters the long side this phase reports.
- **The dependency-upgrade criterion** from phase 0 is still untested: no upgrade has happened.
