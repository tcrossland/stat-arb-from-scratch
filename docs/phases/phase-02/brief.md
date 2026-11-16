# Phase 2: Baseline signal and backtest

Drafted at setup, and revised at the start of the phase with what earlier phases found.

## Goal

Build a backtest engine and run the simplest version of the strategy through it. This baseline is the benchmark every later phase has to beat.

## Baseline strategy

- Signal on day *t*, from data up to the close of *t*: minus the residual return over the last *n* days (start with *n* = 1, also try 3 and 5), optionally scaled by the stock's rolling residual volatility.
- Portfolio: rank the universe members on day *t* by signal, go long the top decile and short the bottom decile, equal weights, dollar neutral.
- Holding period *k*, run as a sweep (*k* = 1, 2, 3, 5): each day's decile portfolio is held for *k* days as one of *k* overlapping slices, so 1/*k* of the book is replaced each day and the held book is the average of the last *k* daily portfolios. *k* = 1 is daily rebalancing. This is the dial between signal decay and trading cost. The phase 2 review picks the baseline *k* that later phases compare against, and records it.
- Fill timing, run as a sweep for every configuration:
  - close of *t* with a stated slippage assumption (optimistic)
  - open of *t+1* (headline result)
  - close of *t+1* (conservative)

  Opens are put on the same adjustment basis as closes. The sweep shows how much edge is lost per day of execution delay.

## The `Signal` interface

Every signal, from the first, is behind one interface (decision record 0002), a `typing.Protocol`:

- it declares the tables it reads (residuals, returns, universe and so on);
- it returns a score per stock and day computed from those tables cut at *t*;
- it is chosen by name in config, and its name and parameters are logged with each run, so a different signal is a different configuration.

How often a book trades stays with the portfolio rule, not the signal. The look-ahead test runs over every registered signal as a contract test, so a new signal is checked before it is used. Raw reversal (total returns instead of residuals) is a second signal from the start, as a control for what the factor model adds.

## Engine requirements

- Inputs: a target-weights panel (date × ticker) and a price panel. Output: daily positions, trades, gross and net P&L, turnover.
- Costs as a pluggable function. In this phase use a flat cost per unit of turnover (start at 5 bps one-way and also report 0, 2, 10 and 20 bps).
- Shorting cost as a flat annual rate on short notional (start at 0.5%).
- No leverage assumptions hidden in the engine: report returns on gross exposure.
- Every run appends its configuration, seed, git commit and headline metrics to `reports/phase-02/experiments.csv`. The best configuration is judged against the number tried, not in isolation.

## Deliverables

1. `src/statarb/backtest/` with the engine, cost function interface and metrics.
2. `src/statarb/signals/` with the `Signal` interface and the reversal signals.
3. `reports/phase-02/`:
   - cumulative P&L, gross and net, for each cost level
   - annualised return, volatility, Sharpe, maximum drawdown, daily turnover, hit rate
   - P&L by year and by sector
   - break-even cost: the one-way cost at which net Sharpe falls to zero
   - net Sharpe by fill timing
   - net Sharpe and turnover by holding period *k*, at each cost level
   - `experiments.csv`
4. Tests:
   - a hand-built three-stock, five-day example with known P&L
   - holding-period slices: with *k* = 2 on a toy panel, the held book each day equals the average of the two most recent daily portfolios
   - reproducibility from config and seed
   - placebo: shuffling the signal across stocks each day, over many seeds, gives mean gross P&L indistinguishable from zero
   - the look-ahead contract over every registered signal

## Acceptance criteria

- The toy example matches hand calculations exactly.
- The placebo test passes.
- Results reproduce exactly from config and seed.
- The report states the break-even cost and compares it with a realistic retail cost.

## Known pitfalls

- Using the close of *t* both to compute the signal and to fill the trade with no slippage. This is the classic look-ahead in reversal backtests and can create most of the apparent edge. The fill-timing sweep makes its size visible.
- Forgetting that turnover for a one-day reversal strategy (*k* = 1) is close to 100% of gross per day, so costs dominate.
- Survivorship bias from phase 0 flatters the long side.
- Picking the best of many configurations and reporting its Sharpe as if it were the only one tried.

## Review questions

- What is the gross Sharpe, and what is the break-even cost?
- How much of the edge is lost per day of execution delay?
- Which holding period maximises net Sharpe at a realistic cost, and how does it compare with the decay of residual autocorrelation over lags 1 to 5 from phase 1?
- How did the edge evolve over time? Expect decay.
- How much of the P&L comes from the long side versus the short side?
- How many configurations were tried, and does the best one still look meaningful after accounting for that?
