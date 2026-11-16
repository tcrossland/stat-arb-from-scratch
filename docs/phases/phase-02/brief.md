# Phase 2: Baseline signal and backtest

Drafted at setup, and revised on 2026-11-16 at the start of the phase with what phases 0 and 1 found.

## Goal

Build a backtest engine and run the simplest version of the strategy through it. This baseline is the benchmark every later phase has to beat.

## Revised at the start of the phase

Phase 0 built the price, return, universe and dated-sector tables from the pinned snapshot, and phase 1 the residual table; their reviews say what carries forward. This revision makes the brief concrete where that reaches phase 2:

- **Inputs are the phase 0 and 1 tables, nothing else.** The runner reads `returns`, `prices`, `residuals`, `universe` and `sectors` from `data/derived/processed/`. No download: every number comes from the snapshot pinned in phase 0. Phase 2 stores no table; every backtest is recomputed from these.
- **Signals start on 2017-01-03, set in config.** Residuals begin on 2016-10-04 (phase 1). The first signal date is `[period] start` of `config/backtest.toml`: the first trading day of 2017, the first full year with residuals, by which time a 60-day volatility for the scaled signals has the 45 observations it needs. No date is written in code. Books start flat on that date.
- **What phase 1 asks phase 2 to look for,** each with a place in the report:
  - *Raw reversal as a control.* Phase 1 found raw returns reverse at lag 1 as much as residuals, pooled, but less steadily. The raw-return signal runs beside the residual one through every configuration.
  - *2022.* The year without reversal in residuals or raw returns. P&L by year shows whether the hole carries through to trading.
  - *The largest names.* Their lag-1 reversal was weakest. P&L by size, on phase 1's buckets of trailing 60-day median dollar volume, decides the backlog item "Sector factor excluding the stock".
  - *Decay over lags 1 to 5.* Phase 1 found the effect almost all at lag 1. The holding-period sweep and the lookback sweep test that in P&L.
- **Open fills on the same basis as closes.** Phase 0 stores unadjusted opens and closes with splits and cash on their ex-dates. Open-to-open total returns are `split_ratio * (open + cash) / previous open - 1`: an action going ex on *d* takes effect at the open of *d*, so it belongs to the return ending at that open, as for close returns.
- **Missing bars.** A name with no bar at a fill time cannot trade and keeps its holding. A held name with no return that day is booked at zero, and the number of such name-days is logged. Phase 1 left six returns spanning more than one trading day: the signal needs all *n* days present, so an *n*-day signal never sums across a gap, and a one-day signal on the day after one uses the spanning return. The review says how many signals that touches.
- **Choices the drafted brief left open,** made now and recorded in `config/backtest.toml`:
  - Returns are per dollar of the gross exposure that earned the day's P&L. On a day that starts flat, the gross just traded into, so the first day's costs are kept.
  - Turnover is buys plus sells per dollar of gross, so replacing the whole book is 2.0. Costs are charged on every dollar traded.
  - Each leg of a decile book holds the floor of 10% of the members with a signal, at half the gross; ties are broken by column order so the book is deterministic.
  - The same-close fill pays 5 bps of slippage one-way on top of every cost level, standing in for trading a little before or after the close on a slightly stale signal.
  - A realistic retail cost is assumed to be 5 bps one-way, half the quoted spread of a large, liquid stock with a commission-free broker, until phase 3 builds a cost model.
  - The *k* slices are averaged into one target each day and the book rebalanced to it; the drift of each slice is not tracked separately.
  - The s-score regresses on SPY and the sector ETF less SPY, Model A's factor set (the paper uses the ETF alone), in-sample over the 60 days ending at *t*. A stock is eligible only with a sector ETF on every day of the window. Each open position is hedged with its sector ETF and SPY at the betas of the day it opened, with hedge targets reset daily; the stock position itself is held unchanged until it closes.
- **The `Signal` interface and a portfolio-rule interface**, both `typing.Protocol`s (below). A signal returns scores; it is calibrated to an expected move in phase 3, where the no-trade zone first needs return units.
- **A config overlay.** Setting `STATARB_CONFIG_OVERLAY` to a directory merges each `<name>.toml` in it over `config/<name>.toml`, key by key, and refuses a key the base file does not have. An experiment that varies a setting puts it in an overlay and never edits a config file, so the committed config always describes the committed results.
- **The experiment log records the data and the code beside the config.** From its first entry, each entry holds the git commit and whether the tree had changes, the overlay if one was set, and the price source and snapshot from `config/data.toml` (`run_state`). These stay out of the hashed configuration, so `config_id` identifies a configuration whatever data or overlay it ran on. The committed log comes from a run on a clean tree.
- **Trials are counted across the repository.** A trial is a distinct position path: a configuration less its cost level, since costs do not change positions. The count is every distinct path in every `reports/phase-NN/experiments.jsonl` of this repository, and the deflated Sharpe ratio (Bailey and López de Prado, 2014) judges the best gross Sharpe against it. Gross, because across configurations the spread of net Sharpe is mostly the spread of costs, not selection noise.
- **Reproducible output.** Two runs give the same bytes for the report and its charts.

## Baseline strategy

- Signal on day *t*, from data up to the close of *t*: minus the residual return over the last *n* days (start with *n* = 1, also try 3 and 5), optionally divided by the stock's rolling 60-day residual volatility times √*n*.
- Portfolio: rank the universe members on day *t* by signal, go long the top decile and short the bottom decile, equal weights, dollar neutral.
- Holding period *k*, run as a sweep (*k* = 1, 2, 3, 5): each day's decile portfolio is held for *k* days as one of *k* overlapping slices, so 1/*k* of the book is replaced each day and the held book is the average of the last *k* daily portfolios. *k* = 1 is daily rebalancing. This is the dial between signal decay and trading cost. The phase 2 review picks the baseline *k* that later phases compare against, and records it.
- Fill timing, run as a sweep for every configuration:
  - close of *t* with a stated slippage assumption (optimistic)
  - open of *t+1* (headline result)
  - close of *t+1* (conservative)

  Opens are put on the same adjustment basis as closes. The sweep shows how much edge is lost per day of execution delay.

## Variant: s-score thresholds

From the phase 1 backlog walk. Avellaneda and Lee (2010) enter and exit on thresholds rather than sorting into daily deciles, so a position is held until its residual has reverted. It trades much less than a daily decile rebalance, which matters once costs bite. Run it alongside the decile baseline through the same engine, costs and fill-timing sweep, with their settings as the starting point:

- Fit an Ornstein-Uhlenbeck process to each stock's cumulated residual over the last 60 trading days up to *t*, as an AR(1) on the cumulated residuals.
- Keep a stock only if its mean reversion is fast against the window: a mean-reversion time under 30 trading days, half the window.
- The s-score is the distance of the cumulated residual from its equilibrium in units of the equilibrium standard deviation, with the equilibrium means centred across stocks each day, as they found works better.
- Open long below −1.25 and short above +1.25; close a long once the s-score rises above −0.50 and a short once it falls below +0.75.

Their residuals come from a 60-day regression, this project's from 252 days (phase 1's window sensitivity report compares the two). The s-score's own 60-day window is separate from the factor model's, so the variant needs no new residuals. The signal is the s-score; the thresholds and the holding they imply are a portfolio rule, so the variant needs a portfolio rule that carries state from day to day, behind the same interface as the decile rule.

## The `Signal` interface

Every signal, from the first, is behind one interface (decision record 0002), a `typing.Protocol`:

- it declares the tables it reads (residuals, returns, universe and so on);
- it returns a score per stock and day computed from those tables cut at *t*;
- it is chosen by name in config, and its name and parameters are logged with each run, so a different signal is a different configuration.

How often a book trades stays with the portfolio rule, not the signal. The look-ahead test runs over every registered signal as a contract test, so a new signal is checked before it is used. Raw reversal (total returns instead of residuals) is a second signal from the start, as a control for what the factor model adds.

The portfolio rule is the second seam, with two implementations from the start: the decile sort with *k* slices, and the s-score thresholds, which carry positions from day to day. Both turn scores and membership into a target-weights panel, and the engine takes either.

## Engine requirements

- Inputs: a target-weights panel (date × ticker) and a price panel. Output: daily positions, trades, gross and net P&L, turnover.
- Costs as a pluggable function. In this phase use a flat cost per unit of turnover (start at 5 bps one-way and also report 0, 2, 10 and 20 bps).
- Shorting cost as a flat annual rate on short notional (start at 0.5%).
- No leverage assumptions hidden in the engine: report returns on gross exposure.
- Backtest configurations are TOML files in `config/`, loaded into frozen dataclasses that reject unknown or missing keys, so a misspelt parameter fails loudly instead of falling back to a default.
- Every run appends one JSON object per configuration and cost level (configuration, seed, `run_state` and headline metrics) to `reports/phase-02/experiments.jsonl`. JSON Lines keeps working as later phases add parameters, where a CSV's columns would drift. The best configuration is judged against the number tried, not in isolation.

## Deliverables

1. `src/statarb/backtest/` with the engine, the cost function interface, the portfolio rules, metrics, the experiment log with `run_state`, the trial count and the deflated Sharpe, and the runner `statarb.backtest.run`.
2. `src/statarb/signals/` with the `Signal` interface, its registry, and the residual reversal, raw reversal and s-score signals.
3. The config overlay in `statarb.config`, and `config/backtest.toml`.
4. `reports/phase-02/`:
   - cumulative P&L, gross and net, for each cost level
   - annualised return, volatility, Sharpe, maximum drawdown, daily turnover, hit rate
   - P&L by year, by sector and by size
   - the long and short sides, and the book's market exposure: the P&L split into Model A's residual and fitted parts, and its net market beta
   - break-even cost: the one-way cost at which net Sharpe falls to zero
   - net Sharpe by fill timing
   - net Sharpe and turnover by holding period *k*, at each cost level
   - the s-score variant beside the decile baseline: net Sharpe, turnover and positions held, at each cost level
   - the placebo on the real data, and the trial count with the deflated Sharpe
   - `experiments.jsonl`
5. Tests:
   - a hand-built three-stock, five-day example with known P&L
   - holding-period slices: with *k* = 2 on a toy panel, the held book each day equals the average of the two most recent daily portfolios
   - fill delay, untradable names, and open-to-open returns across a split and a dividend
   - the s-score against a hand calculation, its centring and its trading rule
   - reproducibility from config and seed
   - placebo: shuffling the signal across stocks each day, over many seeds, gives mean gross P&L indistinguishable from zero
   - the look-ahead contract over every registered signal, and the engine's targets and P&L up to a cut-off unchanged by data after it
   - strict config keys, the overlay's merge and refusals, the experiment log and the trial count
6. The reference docs in the same change as the code: architecture, data model, time discipline, glossary and requirements.

## Acceptance criteria

- The toy example matches hand calculations exactly.
- The placebo test passes.
- Results reproduce exactly from config and seed in the environment fixed by `uv.lock`: two runs give the same report and charts byte for byte.
- The report states the break-even cost and compares it with a realistic retail cost.
- Every entry of the committed experiment log records its `run_state`, and the log comes from a clean tree.

## Known pitfalls

- Using the close of *t* both to compute the signal and to fill the trade with no slippage. This is the classic look-ahead in reversal backtests and can create most of the apparent edge. The fill-timing sweep makes its size visible.
- Forgetting that turnover for a one-day reversal strategy (*k* = 1) is close to 100% of gross per day, so costs dominate.
- Survivorship bias from phase 0 flatters the long side.
- Picking the best of many configurations and reporting its Sharpe as if it were the only one tried.
- Editing a config file to try a setting, so the committed config no longer describes the committed results. Use an overlay.

## Review questions

- What is the gross Sharpe, and what is the break-even cost?
- How much of the edge is lost per day of execution delay?
- Which holding period maximises net Sharpe at a realistic cost, and how does it compare with the decay of residual autocorrelation over lags 1 to 5 from phase 1?
- How did the edge evolve over time? Expect decay. Does 2022 show?
- How much of the P&L comes from the long side versus the short side?
- Does the residual signal earn more than the raw-return control, and do the largest names behave differently?
- How many configurations were tried, and does the best one still look meaningful after accounting for that?

The review also answers the backlog items triggered at it: "Benchmark against Avellaneda and Lee" (the s-score against their results), "Sector factor excluding the stock" (from P&L by size) and "A second price source for cross-checking" (from what the first P&L shows).
