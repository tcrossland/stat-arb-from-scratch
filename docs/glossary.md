# Glossary

Terms as this project uses them. Where a term has a wider meaning in finance, the entry gives the project's definition. A phase that introduces a term, or fixes a definition in code or config, updates its entry in the same change.

Abbreviations: bps is basis points (1 bp = 0.01%).

## Notation

One symbol per quantity across the project. A phase that introduces a symbol adds it here.

| Symbol | Meaning | Phase |
|---|---|---|
| *t* | the trading day a decision is made on | all |
| *n* | lookback: the days of residuals summed into the signal | 2 |
| *k* | holding period: the days each decile portfolio is held | 2 |
| *b* | the AR(1) slope of the s-score's fit | 2 |
| *s* | the time of a fill on the engine's grid of opens and closes | 3 |
| *c* | impact coefficient of the square-root model | 3 |
| σ | a stock's daily volatility | 3 |
| *m* | number of PCA components in Model B | 4 |
| *v* | an eigenvector of the stocks' correlation matrix, one per eigenportfolio | 4 |
| λ | risk aversion: the weight on risk in the optimiser's objective | 4 |
| κ | cost multiplier: the weight on trading cost in the optimiser's objective | 4 |
| *τ* | turnover budget: the cap on a day's turnover, as a share of capital | 4 |
| *h* | the optimiser's horizon: the days of expected move and of risk it weighs | 4 |
| μ | the expected move over *h* days, in return units | 4 |
| Σ | the daily covariance of stock returns from a risk model | 4 |
| *w*, *w*₀ | the book's weights as fractions of capital: chosen, and as known at the decision | 4 |
| *w*\* | the aim portfolio: the book partial adjustment trades towards | 5 |
| θ | trade rate: the fraction of the gap to the aim portfolio traded each day | 5 |

## Data and universe

**Candidates.** Today's S&P 500 constituents, taken from Wikipedia (decision record 0003). The universe is chosen from them.

**Universe.** The stocks the strategy may hold on a given day: the 300 candidates with the highest median daily dollar volume over the trailing 60 trading days, ranked on the last trading day of each month with data up to that day, and used from the next trading day.

**Dollar volume.** Close times shares traded on a day.

**Survivorship bias.** A list of today's index members leaves out the companies that fell out of the index or stopped trading, which flatters any history built from it.

**Delisted suffix.** `-DELISTED`, which MarketParquet's archive appends to the symbol of a security that has since stopped trading, on every day of its history. It says what happened after each of those days, so it is part of a security's key and never an input (decision record 0008).

**Listed universe, survivors, candidates (phase 7).** Three universes of the same size ranked on the second source. `listed`: every stock symbol with a bar on the day. `survivors`: those without the delisted suffix, built with look-ahead on purpose to measure survivorship. `candidates`: today's S&P 500. `existing` names the universe phase 0 built on Alpaca's prices.

**Near-copy.** Two members of a universe whose returns over the ranking's window correlate above a stated level: two share classes of one company, or one company the archive holds under two symbols. Counted in the universe's report and left in (decision record 0009).

**Split, dividend, ex-date.** Corporate actions that change the price without changing the holder's wealth. The ex-date is the first day a stock trades on the new basis after a split, or without the right to a dividend.

**Adjusted prices.** Past prices rescaled so that a series runs smoothly across splits and dividends. Sources rescale the whole history after each new action, so adjusted levels are derived here, never stored as the source of truth.

**Unadjusted prices.** Prices as they traded on the day, with splits and dividends stored separately as corporate actions.

**Raw snapshot.** One download, kept in the raw store at `<source>/<download date>/` exactly as the source returned it, read-only and never modified. The daily job names its price snapshots for the run day instead, the download date except for a download before the run time. Builds read snapshots, never the network.

**Raw store, derived data.** The raw store (`data/raw/`, or the path in `STATARB_RAW`) holds raw snapshots, the only data that cannot be replaced; it is backed up privately and never committed. Derived data (`data/derived/`) is everything rebuilt from it, and can be deleted at any time.

**Snapshot digest.** The SHA-256 of a snapshot's `path hash` lines, one per file, sorted by path. It identifies a snapshot by content, where its date alone does not.

**Manifest.** `manifest.json` in a snapshot: the source, basis, dates and tickers of the download, which tickers had no data or failed, and the SHA-256 of every file with the snapshot's digest. It is written last, so a snapshot without one is incomplete and never read.

**Pinned snapshot, pinned revision.** The price snapshot named by date and digest in `[source]` of `config/data.toml`, and the Wikipedia revision id with its snapshot's date and digest in `config/universe.toml`, that a build reads. Pinning them makes a rebuild exact, and the digest makes it refuse a snapshot that changed.

**Price basis.** What a source's prices are adjusted for: unadjusted, split-adjusted or fully adjusted (for splits and dividends). The canonical step turns the first two into unadjusted prices; fully adjusted prices cannot be turned back and are refused.

**Corporate action.** An event that changes what a share is or pays: a split, cash dividend, spin-off or name change. Alpaca reports each as a record with an ex-date and a **process date**, the day it handled the event, usually near the payable date.

**Split ratio.** New shares per old share on a split's ex-date: 4 for a four-for-one split, 0.5 for a one-for-two reverse split, 1 on other days.

**Cash.** Cash per share going ex on a day: dividends gross of withholding tax, plus any spin-off valued as cash.

**Gross and net dividend.** The amount the issuer declares, and that amount less the tax its home country withholds. Returns use the gross amount (decision record 0004).

**Spin-off.** A company distributing shares of a subsidiary to its own holders. The parent's price drops by the value distributed, which the return counts as cash.

**Listing start.** The first date of a ticker's own trading, where the source's history begins earlier under another security or a pre-merger shell. Listed with sources in `config/listing_starts.toml`.

**New York date.** The calendar date in New York, where the exchanges are. Trading dates and a download's cut-off use it, whatever the machine's time zone.

**Dated sector.** A stock's GICS sector with the dates it applied, so a reclassification changes the sector from its effective date only.

**Total return.** The day's return including any dividend going ex that day.

**Sector ETF.** An exchange-traded fund holding the stocks of one sector; the eleven SPDR sector funds stand for the sectors, and SPY for the market.

## Factor model and residuals

**Factor model.** A model that explains each stock's daily return by a few common factors. **Model A** regresses it on the market (SPY) and the ETF of the stock's sector; **Model B** uses statistical factors from PCA.

**Beta.** A stock's sensitivity to a factor: how much it tends to move per unit move of the factor.

**Estimation window.** The trading days whose returns a stock's betas on day *t* are estimated from: the 252 ending the day before *t*, at least 189 of them with a return (`[model]` of `config/factors.toml`). With fewer, the stock has no residual that day.

**Sector factor.** In Model A, the return of the stock's sector ETF less SPY's return on the same day, so the market and sector regressors overlap little. Each day in the window uses the ETF of the sector the stock was in that day.

**Intercept (alpha).** The constant in the window's regression. It is estimated, so drift does not bias the betas, but not subtracted from the residual.

**Market-only row.** A residual from SPY alone, because the stock's sector had no ETF on the day (Telecommunication Services before 2018) or too few days in the window had one. Flagged `market_only` in the residual table.

**Volume ratio, event flag.** The volume ratio is a day's volume over its median over the previous 20 trading days, both put on one share basis with the split ratios. A day with a ratio of at least 3 is flagged as an event: a crude stand-in for earnings and other news (`[events]` of `config/factors.toml`).

**Residual.** The part of a stock's return that the factor model does not explain: the return on *t* minus the betas estimated before *t* times the factor returns on *t*.

**Fitted return.** The part the factor model does explain.

**Daily rank correlation.** The Spearman correlation of two values across stocks on one day, such as a residual and the same stock's residual a day later, averaged over days. Its t-statistic treats days as independent. It is the cross-sectional quantity a reversal signal trades.

**Average pairwise correlation.** The correlation of two stocks' daily values over a year, averaged over every pair of stocks. Residuals that remove the common factors have one near zero.

**Size bucket.** A stock's quintile of trailing 60-day median dollar volume among universe members on a day, 1 the smallest. The free data has no shares outstanding, so size here means trading size, not market value.

**ETF self-inclusion.** A sector ETF holds the stocks regressed on it, so a large stock's own move is partly in its sector factor and its residual is understated.

**PCA factors.** Statistical factors taken from the principal components of the stocks' returns, rather than from ETFs (Model B).

**Eigenportfolio.** In Model B, a portfolio with weights *v*/σ, where *v* is one of the top eigenvectors of the stocks' correlation matrix over the window and σ each stock's volatility over it (Avellaneda and Lee, 2010). Its returns are the factor's returns; its variance over the window is the eigenvalue. Model B uses the top *m* = 15 (`[pca]` of `config/factors.toml`).

**Complete window.** A stock with a return on every day of the window. Only these shape Model B's eigenportfolios; a stock with at least 189 returns gets betas and a residual without shaping them.

## Signals and portfolios

**Signal.** A number per stock per day that ranks expected moves. Every signal implements the `Signal` interface: it declares the tables it reads, scores each stock from those tables cut at *t*, and is chosen by name in config (decision record 0002).

**Cross-sectional.** Across stocks on the same day, as opposed to along one stock's history.

**Reversal (mean reversion).** The tendency of a large move to be partly undone over the following days.

**Lookback (*n*).** The number of days of residuals summed into the signal.

**Decile portfolio (decile sort).** Long the 10% of universe members with the highest signal and short the 10% with the lowest, equally weighted, half the gross on each side. Each leg holds the floor of 10% of the members with a signal.

**Holding period (*k*) and slices.** Each day's decile portfolio is held for *k* days. The book is the average of the last *k* daily portfolios, so 1/*k* of it is replaced each day.

**Raw-return control.** The same portfolio built from total returns instead of residuals, to show what the factor model adds.

**s-score.** How far a stock's cumulated residual is from its equilibrium, in units of its equilibrium standard deviation, from an Ornstein-Uhlenbeck process fitted over a trailing window (Avellaneda and Lee, 2010). A threshold rule opens a position when it is far from zero and closes it near zero, so a position is held until the residual reverts. A phase 2 variant.

**Portfolio rule.** What turns signals and universe membership into the book to hold: the decile sort with *k* slices, or the s-score's thresholds. It decides how often the book trades; the signal does not. A second seam beside the signal (`PortfolioRule`).

**Policy.** What the engine applies at each fill time *s* to the targets due then: it sees the holdings of the last fill, the same moved with prices to *s*, and the targets, and returns the targets to trade to with a note for the day. The no-trade zone (phase 3), the optimiser and decile sort (phase 4) and partial adjustment (phase 5) are policies. Another seam (`Policy`).

**Threshold rule.** The s-score's portfolio rule: a position opens when the s-score crosses an opening threshold and is held unchanged until it crosses a closing one, the stock leaves the universe or its fit stops qualifying. Each position is hedged with its sector ETF and SPY at the betas of the day it opened.

**Mean-reversion time.** In the s-score's fit, the trading days the cumulated residual takes to close 1 − 1/*e*, about 63%, of its distance to equilibrium, −1 / ln *b* for the AR(1) slope *b*. A stock trades only if it is under 30 days.

**Baseline.** The simplest version of the strategy, built in phase 2, which every later method must beat after costs.

**Book.** The strategy's portfolio: every long and short position it holds at a given time.

**Gross exposure.** The sum of the absolute values of all positions: longs plus shorts.

**Dollar neutral.** Long and short positions of equal dollar value, so the book's net exposure is zero.

**Turnover.** Dollars traded (buys plus sells) per day: per dollar of gross exposure in phase 2, and per dollar of capital from phase 3.

## Backtest mechanics

**Backtest.** A simulation of the strategy over past data, with every decision made from what was known at the time.

**Fill timing.** When a decision made at the close of *t* is executed: at that close with a stated slippage, at the open of *t+1*, or at the close of *t+1*.

**Slippage.** Any difference between the price assumed and the price obtained.

**Placebo.** The signal shuffled among universe members each day. A correct engine earns nothing from it on average.

**Experiment log.** `reports/phase-NN/experiments.jsonl`: one JSON object per backtest configuration and cost level run, with its configuration and `config_id`, seed, run state and headline metrics ([data model](data-model.md#experiment-logs)).

**Run state.** What an experiment log entry records beside the configuration: the git commit, whether the tree had changes, the config overlay and the price source and snapshot. It is kept out of the hashed configuration, so a configuration has one id whatever it ran on.

**Config overlay.** A directory named in `STATARB_CONFIG_OVERLAY` whose TOML files are merged over those in `config/`, so an experiment changes a setting without editing a config file. It may set only keys the base file has.

**Fill grid.** The fill times a backtest steps through, one per trading day: every close or every open. A book decided at the close of *t* is filled on the grid at *t* (same close), *t + 1* (next open or next close).

**Gross and net return.** Gross is before trading and borrow costs; net is after them.

## Performance measures

**Sharpe ratio.** Mean daily return divided by its standard deviation, times √252 to annualise.

**Maximum drawdown.** The largest fall in cumulative returns from a previous peak.

**Hit rate.** The share of days with positive net P&L (day hit rate), or of held position-days with positive gross P&L (position hit rate).

**Break-even cost.** The flat one-way cost per dollar traded at which the net Sharpe ratio falls to zero.

**Trial.** One distinct position path run through the backtest: the part of a configuration that sets positions, since costs, book size and names change the P&L but not the positions. A no-trade path, or an optimiser setting, is one trial whatever the book size. Counted across the repository's experiment logs up to the phase in question; the best result is judged against how many there are.

**Net edge.** From phase 3: a mean net return with a t-statistic of at least 2 and a deflated Sharpe probability of at least 0.95. Anything short of both is "not distinguishable from zero", whatever its sign.

**Deflated Sharpe ratio.** Bailey and López de Prado (2014): the probability that a strategy's true Sharpe ratio is above the best one expected by chance from that many trials with no edge, allowing for the non-normality of returns.

**Benchmark Sharpe.** That best Sharpe ratio expected by chance, annualised: the bar the deflated Sharpe ratio measures a result against. It treats trials as independent, so it is somewhat too high when they are close variants.

## Costs

**One-way cost.** Cost per dollar traded on a single buy or sell. A round trip pays it twice.

**Bid-ask spread, half-spread.** The gap between the best price to sell and the best price to buy. A trade that crosses from the midpoint pays half of it.

**Spread estimators.** Formulas that infer the spread from daily prices when quotes are not available: EDGE (Ardia, Guidotti and Kroencke, from open, high, low and close), Abdi and Ranaldo's (close, high and low) and Corwin and Schultz's (high and low). Each reads negative serial covariance of prices as bid-ask bounce, so daily reversal raises it (decision record 0005).

**Assumed spread, spread bracket.** The daily-price estimators cannot price this strategy's spread, so the headline half-spread is a stated assumption anchored on published effective spreads of S&P 500 stocks, and the bracket repeats each result at other half-spreads to show which conclusions depend on it (decision record 0005; `[spread]` of `config/costs.toml`).

**Half-tick floor.** No stock trades inside its one-cent tick, so a half-spread is never less than half a cent over the previous close.

**Market impact.** The price moving against a trade because of the trade itself, growing with the trade's size relative to daily volume.

**Commission.** The broker's fee. Here a per-share rate with a minimum and a maximum per order, from Interactive Brokers' published US schedule; one order per name per day. The minimum makes small orders cost far more per dollar than large ones.

**Borrow cost.** The fee for borrowing shares to sell short, charged on short notional.

**Hard to borrow.** A stock whose borrow fee is well above the general rate. Free data does not say which, so phase 3 flags the stocks in the top 5% of trailing volatility each day, a proxy.

**Book size, capacity.** Book size is the money the strategy runs, in US dollars. Capacity is the book size beyond which costs, mainly impact, outgrow the edge.

**Capital, capital deployed.** From phase 3, weights are fractions of the book's capital and returns are per dollar of capital, with idle capital earning nothing. Capital deployed is the gross exposure as a share of the capital: below 1 where a decile book's slices offset each other, the no-trade zone leaves names untraded, or the optimiser holds less than its gross cap.

**Net dollar imbalance.** The mean of |longs − shorts| / gross: how far a book is from dollar neutral.

**No-trade zone.** A rule that trades a name only when its expected move pays for the trade.

**Expected move, calibration.** A signal converted to return units, by regressing the realised residual move on the signal over a trailing window of pairs whose outcome was already known at *t*.

## Portfolio construction

**Optimiser.** Chooses each day's book by maximising expected return minus a risk penalty minus a cost penalty, under constraints.

**Risk aversion (λ).** The weight on risk in the optimiser's objective.

**Cost multiplier (κ).** The weight on trading cost in the optimiser's objective.

**Partial adjustment.** A rule that trades a fixed fraction θ of the way each day from the book held to an aim portfolio *w*\*, after Gârleanu and Pedersen (2013). In phase 5 the aim is the optimiser's solution with no cost term, and θ is set for each forecast and book size so the path's turnover matches the optimiser's (decision record 0006).

**Aim portfolio (*w*\*).** The book partial adjustment trades towards: what the optimiser would hold if trading were free.

**Trade rate (θ).** The fraction of the gap to the aim portfolio partial adjustment trades each day.

**Turnover budget (*τ*).** A hard cap on the sum of absolute weight changes in a day, as a share of capital. Forced exits of names leaving the universe sit outside it.

**Horizon (*h*).** The days over which the optimiser weighs the expected move and the risk: the baseline's holding period, 5. The daily covariance is multiplied by it.

**Risk model.** The daily covariance of stock returns as factor loadings times a factor covariance times their transpose, plus a diagonal of specific variances. Model A risk takes the market and sector factors and Model A's betas; Model B risk the eigenportfolios, whose covariance is the diagonal of their eigenvalues, and Model B's betas. Specific variance is each stock's residual variance over the trailing 60 days, from at least 40 of them; a stock with fewer takes the day's median across stocks.

**Position limits.** Each position is at most 2% of capital and at most 1% of the stock's 20-day average dollar volume (`[optimiser]` of `config/portfolio.toml`).

**Factor exposure.** The book's weights times its loadings on a factor, per dollar of capital. The optimiser keeps each within 1% of capital; the report measures it against Model A's factors for every path.

**Ex-ante volatility.** The book's annualised volatility as its risk model predicts it on the day of the decision.

**Minimum trade size.** After solving, trades smaller than this many dollars are dropped, a target below it is set to zero so small positions close, and closes always go through. It stands in for the commission's per-order minimum, which is not convex.

**Re-solve.** After the minimum trade filter, the names it changed are fixed where it left them and the problem is solved again over the rest, so the others restore neutrality; up to five rounds, keeping the last filtered book if a re-solve fails.

**Idle day.** A decision day with nothing to optimise: no expected move or risk model yet, or fewer than two eligible names. Counted apart from failed days.

**Risk aversion rule.** How the headline λ was set before any backtest return was seen: the largest candidate at which the book deploys at least 70% of its capital on average over the first 60 days with an expected move, at both book sizes.

**Hold the previous book.** If the solver returns anything but an optimal solution on a day, the previous fill's holdings are kept, nothing trades, and the day is logged as failed. Constraints are never relaxed automatically.

## ML signal

**Feature.** An input to the model, computed per stock per day from data up to the close of that day.

**Ranked target.** The residual move to be predicted, ranked across stocks each day.

**Row-removal test.** The look-ahead check that builds a value from tables cut at a date and from the whole tables, and requires the two to agree up to the cut. It catches a value that depends on whether a later row exists, which perturbing later values cannot.

**Stock axis.** The columns of the signal tables: every stock with a residual anywhere in the loaded tables. A value across stocks counts only those known on the day.

**Information coefficient (IC).** The daily rank correlation between a forecast and the realised outcome across stocks.

**Walk-forward, purge, embargo.** Validation that trains on the past and tests on the next block of time, dropping training rows whose outcomes overlap the test block (purge) and a gap after it (embargo).

**SHAP contribution.** A feature's share of one forecast, from LightGBM's TreeSHAP (`pred_contrib`), exact for trees: a row's contributions and the expected value add up to the forecast. Reported out of sample, on each block's test rows.

**Gain.** The total reduction in training loss from a feature's splits, summed over a model's trees.

**Holdout.** The most recent data, kept out of every model choice and read once at the end. In phase 5 the read is logged as entries that are not trials, and `--repeat` can only reproduce it.

**Fresh holdout.** The forward run's days, from its first session on (decision record 0007): read only by the daily job and the drift report, since the phase 5 holdout has been read. The phase 2 to 4 runners cut every table at the day before the first session.

**Development end.** The last date the development runner reads: every table is cut there before anything is computed, and the holdout starts the next trading day.

**Common dates.** The dates every forecast's path is compared over in phase 5: from the first date every forecast has a calibrated move to the development end.

## Paper trading

**Forward run.** The frozen strategy run on each new trading day as it happens, with simulated fills and no orders. It starts flat on its first session.

**Calibration slope.** The coefficient of the expected-move calibration: how many units of realised residual move one unit of signal has meant. Phase 3's is trailing, fitted over the last calibration window of pairs whose outcome is known.

**Slope rule.** How the calibration slope behind an expected move is set in phase 6: `trailing`, phase 3's slope as it is; `floored`, the trailing slope never below zero, so a forecast that has stopped working moves nothing rather than its own reverse; `expanding`, fitted over every pair known since the first signal date, the backtestable form of a slope fixed from development.

**Choice path.** A development path of phase 6's evidence for the choice: a forecast through a rule at a book size under one slope rule. A choice path whose daily results equal its trailing version's adds no trial.

**Diagnostic path.** A path run through the holdout only to chart a forecast's slope beside its P&L. Nothing is chosen from it, so it is not a trial.

**Frozen record.** Everything that produces a decision in the forward run, written once when its decision record sets the strategy: the strategy's configuration, every config file that shapes a decision, and each saved model's SHA-256. Its hash is on every ledger day, and the daily job refuses to run if the config no longer gives it.

**Reproduction check.** Before each day's run, the frozen path is rebuilt over development on tables from the pinned snapshot, and every metric must equal its logged entry. It catches a code change that alters behaviour, which the frozen record cannot see.

**Session, due session.** A day the exchange is open, from its calendar. A session is due once New York's date has passed it and its clock has reached the run time, 06:00, so a run processes the same sessions however early, late or often the scheduler fires it.

**Run day.** New York's date at a run of the daily job, or the day before until its clock reaches the run time. Sessions before the run day are due, and the job's price snapshot is named for the run day and holds bars before it, so a run before 06:00 never takes or reuses a snapshot whose last session may not have settled.

**Early snapshot.** A price snapshot taken before the run time on the date it is named for, whose last session may not have settled. The daily job takes none; the run log flags any it used (`snapshot_early`).

**Late session.** A forward-run session not processed by the first run after it falls due, from a snapshot taken on that New York day after the run time: one caught up after a missed day, or processed from an early snapshot. It still counts toward the run, and the run's review reports results with and without the late sessions (decision record 0007, amendment of 2026-11-18).

**Catch-up.** A run after missed days processes every due session after the last ledger day, in order, each on tables cut at it.

**Ledger, ledger day.** The record of the forward run: one immutable file per session, holding the engine step at that day's open and the decision made at its close. The next day fills the decision recorded, never a recomputed one.

**Holding spell.** A run of ledger days on which a name is held on one side. It starts at the open that fills it and ends at the open that closes or flips it; adding to or reducing it on the same side keeps the spell. The ledger explorer lists them with what each earned.

**Ledger explorer.** A local app over the ledger (`notebooks/ledger.py`, on `statarb.paper.views`): the book, trades, P&L, attribution, holding spells and run health. It reads forward days, so nothing it shows enters a result, and it is never hosted, since the ledger derives from data that may not be redistributed.

**Drift report.** The weekly check that the forward run behaves like its backtest: each live measure over the run's days against the same measure over every window of as many days in the frozen path over development, with the source's revisions and the run's failures.

## Process

**Look-ahead.** Using at time *t* any value not knowable at *t*. Tests perturb data after a cut-off and check that nothing before it changes.

**Decision record (ADR).** A short note in `docs/decisions/` for a change of scope, data source or methodology: context, decision, consequences.

**Phase brief, review, backlog.** The brief sets a phase's scope (`docs/phases/`); the review records what was built and what the numbers showed; the backlog (`docs/backlog.md`) holds work deferred to a later phase, each item with the trigger that brings it back.

