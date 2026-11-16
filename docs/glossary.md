# Glossary

Terms as this project uses them. Where a term has a wider meaning in finance, the entry gives the project's definition. A phase that introduces a term, or fixes a definition in code or config, updates its entry in the same change.

Abbreviations: bps is basis points (1 bp = 0.01%).

## Notation

One symbol per quantity across the project. A phase that introduces a symbol adds it here.

| Symbol | Meaning | Phase |
|---|---|---|
| *t* | the trading day a decision is made on | all |
| *m* | number of PCA components in Model B | 1 |
| *n* | lookback: the days of residuals summed into the signal | 2 |
| *c* | impact coefficient of the square-root model | 3 |
| σ | a stock's daily volatility | 3 |
| λ | risk aversion: the weight on risk in the optimiser's objective | 5 |
| κ | cost multiplier: the weight on trading cost in the optimiser's objective | 5 |

## Data and universe

**Universe.** The stocks the strategy may hold on a given day, chosen from a candidate list by liquidity.

**Dollar volume.** Close times shares traded on a day.

**Survivorship bias.** A list of today's index members leaves out the companies that fell out of the index or stopped trading, which flatters any history built from it.

**Split, dividend, ex-date.** Corporate actions that change the price without changing the holder's wealth. The ex-date is the first day a stock trades on the new basis after a split, or without the right to a dividend.

**Adjusted prices.** Past prices rescaled so that a series runs smoothly across splits and dividends. Sources rescale the whole history after each new action.

**Total return.** The day's return including any dividend going ex that day.

**Sector ETF.** An exchange-traded fund holding the stocks of one sector; the eleven SPDR sector funds stand for the sectors, and SPY for the market.

## Factor model and residuals

**Factor model.** A regression that explains each stock's daily return by a few common factors, here the market and the stock's sector.

**Beta.** A stock's sensitivity to a factor: how much it tends to move per unit move of the factor.

**Residual.** The part of a stock's return that the factor model does not explain: the return minus betas times factor returns.

**Fitted return.** The part the factor model does explain.

**PCA factors.** Statistical factors taken from the principal components of the stocks' returns, rather than from ETFs.

## Signals and portfolios

**Signal.** A number per stock per day that ranks expected moves.

**Cross-sectional.** Across stocks on the same day, as opposed to along one stock's history.

**Reversal (mean reversion).** The tendency of a large move to be partly undone over the following days.

**Lookback (*n*).** The number of days of residuals summed into the signal.

**Decile portfolio.** Long the 10% of universe members with the highest signal and short the 10% with the lowest, equally weighted.

**Baseline.** The simplest version of the strategy, built in phase 2, which every later method must beat after costs.

**Book.** The strategy's portfolio: every long and short position it holds at a given time.

**Gross exposure.** The sum of the absolute values of all positions: longs plus shorts.

**Dollar neutral.** Long and short positions of equal dollar value, so the book's net exposure is zero.

**Turnover.** Dollars traded (buys plus sells) per dollar of gross exposure, per day.

## Backtest mechanics

**Backtest.** A simulation of the strategy over past data, with every decision made from what was known at the time.

**Fill timing.** When a decision made at the close of *t* is executed: at that close with a stated slippage, at the open of *t+1*, or at the close of *t+1*.

**Slippage.** Any difference between the price assumed and the price obtained.

**Gross and net return.** Gross is before trading and borrow costs; net is after them.

## Performance measures

**Sharpe ratio.** Mean daily return divided by its standard deviation, times √252 to annualise.

**Maximum drawdown.** The largest fall in cumulative returns from a previous peak.

**Hit rate.** The share of days, or of positions, with positive P&L.

**Break-even cost.** The flat one-way cost per dollar traded at which the net Sharpe ratio falls to zero.

## Costs

**One-way cost.** Cost per dollar traded on a single buy or sell. A round trip pays it twice.

**Bid-ask spread, half-spread.** The gap between the best price to sell and the best price to buy. A trade that crosses from the midpoint pays half of it.

**Spread estimators.** Formulas that infer the spread from daily prices when quotes are not available.

**Market impact.** The price moving against a trade because of the trade itself, growing with the trade's size relative to daily volume.

**Commission.** The broker's fee.

**Borrow cost.** The fee for borrowing shares to sell short, charged on short notional.

**Book size, capacity.** Book size is the money the strategy runs, in US dollars. Capacity is the book size beyond which costs, mainly impact, outgrow the edge.

**No-trade zone.** A rule that trades a name only when its expected move pays for the trade.

## Portfolio construction

**Optimiser.** Chooses each day's book by maximising expected return minus a risk penalty minus a cost penalty, under constraints.

**Risk aversion (λ).** The weight on risk in the optimiser's objective.

**Cost multiplier (κ).** The weight on trading cost in the optimiser's objective.

## ML signal

**Feature.** An input to the model, computed per stock per day from data up to the close of that day.

**Ranked target.** The residual move to be predicted, ranked across stocks each day.

**Information coefficient (IC).** The daily rank correlation between a forecast and the realised outcome across stocks.

**Walk-forward, purge, embargo.** Validation that trains on the past and tests on the next block of time, dropping training rows whose outcomes overlap the test block (purge) and a gap after it (embargo).

**Holdout.** The most recent data, kept out of every model choice and read once at the end.

## Paper trading

**Ledger.** The record of the forward run: trades, positions and P&L by day.

**Drift report.** The weekly check that the forward run behaves like its backtest.

## Process

**Look-ahead.** Using at time *t* any value not knowable at *t*. Tests perturb data after a cut-off and check that nothing before it changes.

**Decision record (ADR).** A short note in `docs/decisions/` for a change of scope, data source or methodology: context, decision, consequences.

**Phase brief, review.** The brief sets a phase's scope (`docs/phases/`); the review records what was built and what the numbers showed.

