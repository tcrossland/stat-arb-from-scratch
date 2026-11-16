# Phase 2: Baseline signal and backtest

Drafted at setup, and revised at the start of the phase with what earlier phases found.

## Goal

Build a backtest engine and run the simplest version of the strategy through it. This baseline is the benchmark every later phase has to beat.

## Baseline strategy

- Signal on day *t*: minus the residual return over the last *n* days (start with *n* = 1, also try 3 and 5), optionally scaled by the stock's rolling residual volatility.
- Portfolio: rank the universe by signal, go long the top decile and short the bottom decile, equal weights, dollar neutral. Hold for one day and rebalance daily.
- Fills: at the close of day *t* for signals computed from data up to *t−1*'s close, or at the close of *t* with a slippage assumption if the signal uses *t*'s close. Record which.

## Engine requirements

- Inputs: a target-weights panel (date × ticker) and a price panel. Output: daily positions, trades, gross and net P&L, turnover.
- Costs as a pluggable function. In this phase use a flat cost per unit of turnover (start at 5 bps one-way and also report 0, 2, 10 and 20 bps).
- Shorting cost as a flat annual rate on short notional (start at 0.5%).
- No leverage assumptions hidden in the engine: report returns on gross exposure.

## Deliverables

1. `src/statarb/backtest/` with the engine, cost function interface and metrics.
2. `src/statarb/signals/reversal.py`.
3. `reports/phase-02/`:
   - cumulative P&L, gross and net, for each cost level
   - annualised return, volatility, Sharpe, maximum drawdown, daily turnover, hit rate
   - P&L by year and by sector
   - break-even cost: the one-way cost at which net Sharpe falls to zero
4. Tests: a hand-built three-stock, five-day example with known P&L; reproducibility test.

## Acceptance criteria

- The toy example matches hand calculations exactly.
- Results reproduce from config and seed.
- The report states the break-even cost and compares it with a realistic retail cost.

## Known pitfalls

- Using the close of *t* both to compute the signal and to fill the trade with no slippage. This is the classic look-ahead in reversal backtests and can create most of the apparent edge.
- Forgetting that turnover for a one-day reversal strategy is close to 100% of gross per day, so costs dominate.
- Survivorship bias from phase 0 flatters the long side.

## Review questions

- What is the gross Sharpe, and what is the break-even cost?
- How did the edge evolve over time? Expect decay.
- How much of the P&L comes from the long side versus the short side?
