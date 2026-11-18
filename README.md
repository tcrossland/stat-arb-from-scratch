# Residual mean reversion in US equities: an end-to-end statistical arbitrage pipeline

A daily statistical arbitrage pipeline for US equities, from raw market data to a forward-running paper trade, built to answer one question: does cross-sectional residual mean reversion survive realistic trading costs and an honest count of everything tried? Simulation only.

The short answer so far is no: the signal earns a small return before trading costs, but once realistic costs are paid and every configuration tried is counted, none keeps a return that can be told apart from luck. The forward paper trade now tests whether the pipeline, run one day at a time on data downloaded each day, behaves like its backtest, not whether it earns.

## Results

The findings of each phase, whichever way they go.

- **Phase 0, data and universe.** A daily build of S&P 500 candidates and factor ETFs from free data, reproducible byte for byte from pinned snapshots, with the source's quirks fixed under the numbered rules of decision record 0004. The universe uses today's constituents, so it carries survivorship bias. [Review](docs/phases/phase-00/review.md), [quality report](reports/phase-00/data_quality.md).
- **Phase 1, factor model and residuals.** Regressing each stock on the market and its sector ETF removes almost all common movement. Residuals reverse slightly from one day to the next, no more than raw returns do but more steadily, and in every year but 2022. [Review](docs/phases/phase-01/review.md), [diagnostics](reports/phase-01/diagnostics.md).
- **Phase 2, reversal signal and backtest.** Residual reversal earns a small gross return that a retail-sized trading cost more than removes, at every holding period, fill and lookback tried. Holding longer and looking back further help; the best of all the configurations tried is suggestive gross and not significant net. [Review](docs/phases/phase-02/review.md), [backtest report](reports/phase-02/backtest.md).
- **Phase 3, cost realism.** Under spread, impact, commission and borrow, no configuration keeps a net edge at any book size tried. Commission's per-order minimum binds a retail book, and impact a large one. A filter that trades only when the expected move pays the cost turns the decile books' net Sharpe positive, by trading little, and none clears the bar for a net edge. The daily-price spread estimators read the strategy's own reversal as spread, so the spread is a stated assumption. [Review](docs/phases/phase-03/review.md), [cost report](reports/phase-03/costs.md).
- **Phase 4, portfolio construction.** An optimiser that weighs the expected move against risk and trading cost holds a book with market and sector exposures near zero, and raises gross Sharpe over the decile sort, but trades more and loses more net. It does better the less it trades, and its best result comes from one year. A statistical factor model changes no verdict, as residual or as risk model, and the simpler no-trade zone does better net at the price of an unbalanced book. No configuration clears the bar. [Review](docs/phases/phase-04/review.md), [portfolio report](reports/phase-04/portfolio.md).
- **Phase 5, ML signal.** A gradient-boosted model forecasts residual reversal out of sample about as well as the baseline signal, but earns less gross than the simple variants through every portfolio rule: the forecast with the best rank correlation is not the one that pays for its trades. Trading part of the way to the optimiser's book each day keeps less than the optimiser at the same turnover. No configuration clears the bar, and in the held-out last year, read once, no forecast's correlation with later returns is distinguishable from zero. [Review](docs/phases/phase-05/review.md), [development report](reports/phase-05/ml.md), [holdout report](reports/phase-05/holdout.md).
- **Phase 6, paper trading, built; the forward run starts from 2026-11-16.** A daily job that runs a frozen strategy forward one New York session at a time with the backtest's own step, and refuses to run if its config, its model files or its backtest no longer match what was frozen. No forecast or calibration rule tried for the choice clears the bar, and most of the baseline's one-day lead is in the overnight move, which a book filled at the next open never holds. So the run tests whether the live pipeline behaves like its backtest, not whether it earns: decision record 0007 freezes the three-day lookback through the optimiser, by a rule that reads no forward data, and keeps the forward days as a fresh holdout. [Review](docs/phases/phase-06/review.md), [evidence for the choice](reports/phase-06/choice.md), [decision record 0007](docs/decisions/0007-forward-run.md).

## Architecture

```mermaid
flowchart LR
    S["raw snapshots<br/>Alpaca, Wikipedia"] --> D["data build<br/>universe, returns"] --> F["factor model<br/>Model A: ETFs<br/>Model B: PCA"] --> G["signal"] --> P["portfolio<br/>decile sort, no-trade zone,<br/>optimiser"] --> B["backtest and<br/>paper trade"]
    R["risk model"] --> P
    C["cost model"] --> P
    C --> B
```

Each stage is a function of the tables before it, cut at the decision date, which is what lets a test check it for look-ahead. Each seam (the price and constituent sources, the factor model, the signal, the cost model, the portfolio rule, the engine's policy and the risk model) is a typed interface whose implementations all pass the same contract tests, chosen by name in config and recorded with every result.

## Invariants

Each phase holds to these:

- **No look-ahead.** Every value used on a day must have been knowable that day. Every transform and every signal passes a test that perturbs later data and requires nothing earlier to change ([time discipline](docs/time-discipline.md)).
- **Reproducible.** Every result reproduces exactly from the pinned data snapshot behind it, its config and seed, in the environment fixed by `uv.lock`. That snapshot is not redistributed: a rebuild from your own download matches closely, within a tolerance to be stated in [reproducing the results](docs/reproduce.md#checking-your-results). Raw snapshots are never modified.
- **Every trial counted.** Every configuration run is logged, and the best is judged against all of them with a deflated Sharpe ratio, never shown alone.
- **No data committed.** No prices, volumes or per-ticker returns are committed, and reports hold statistics only; tests run on synthetic fixtures with the network blocked.
- **Licences checked.** A test reads the licence of every installed distribution, dependencies included.

## Reading path

The [documentation index](docs/README.md) lists every page by what you want to do, in the recommended reading order.

## The strategy

Each day a factor model removes the part of every stock's return that the market and its sector explain. What remains, the residual, is specific to the stock. The stocks whose residuals fell most over the last few days are bought and those that rose most are sold short, in equal dollar amounts, on the bet that part of those moves reverses. It is cross-sectional because stocks are ranked against each other on the same day, so the book gains when recent losers beat recent winners, whichever way the market moves.

Firms that trade this for a living run it intraday, with order-book data and institutional costs. This project runs it on free daily data, which keeps the mechanics and makes the economics much harsher.

## How the work is organised

Each phase adds one stage. It starts from a brief in [`docs/phases/`](docs/phases/) and ends with a written review and a tag, `phase-00` to `phase-06`, so checking out a tag gives the project as it stood at the end of that phase. Decisions that change scope, data or method are recorded in [`docs/decisions/`](docs/decisions/).

The project is built with Claude Code under the working rules in [CLAUDE.md](CLAUDE.md), and its commits carry Claude Code's co-author trailer. Each phase is a brief, then the commits that build it, then a review and a tag. Each lesson the work has taught is a row in [docs/lessons.md](docs/lessons.md), with the episode that taught it where there was one, and the test or check that enforces it now.

| Phase | Adds | Status |
|-------|------|--------|
| 0 | Prices, returns and a liquidity-ranked universe | done |
| 1 | Factor model and residuals | done |
| 2 | Reversal signal and backtest engine | done |
| 3 | Cost model | done |
| 4 | Portfolio optimiser and a statistical factor model | done |
| 5 | ML signal | done |
| 6 | Daily paper-trading simulation | built; forward run not started |

## Running it

Needs Python 3.14 and [uv](https://docs.astral.sh/uv/). No GPU is needed. On macOS, LightGBM needs the OpenMP runtime, for the tests too: install it once with [Homebrew](https://brew.sh/) (`brew install libomp`). On Linux the wheel uses GCC's OpenMP runtime, `libgomp`, which most distributions install with GCC. The tests run on small synthetic fixtures committed under `tests/` and need no download, no keys and no network:

```bash
uv sync --locked
uv run ruff check
uv run pytest
```

[Reproducing the results](docs/reproduce.md) rebuilds every published result: downloading and pinning a data snapshot, which needs a free, paper-only Alpaca account, then each phase's runner in order, with what each reads and writes.

## Reuse it

Most of the code is built around this pipeline's tables, but a few parts work on their own:

- [Look-ahead checks](src/statarb/testing/lookahead.py): perturb a table's values after a cut-off, or drop its rows after it, and assert that nothing dated on or before the cut-off changed. They work on any long pandas table with a date column.
- [Deflated Sharpe ratio](src/statarb/backtest/metrics.py): the probability that a strategy's Sharpe ratio beats the best expected from as many trials of noise, after Bailey and López de Prado (2014), from a daily return series and the Sharpe ratios of every trial.
- [Trading cost model](src/statarb/backtest/costs.py): `TradingCost` charges half-spread, square-root market impact and a per-order commission with a minimum and a maximum on a panel of trades by day and name, held as numpy arrays. Building its inputs from prices (`build_cost_inputs`) assumes this project's tables.

The [contract tests](tests/contract/) are tied to the pipeline rather than reusable: they are where a new signal, price source, portfolio rule or model library starts, since every registered implementation runs through the same checks.

Help is welcome on one open question in particular: is there a published short-term reversal series, built by others and with terms that allow automated use, to compare with this project's decile book year by year? It would be the one check on the engine and the data together that does not rest on this project's own code ([backlog](docs/backlog.md#an-independent-short-term-reversal-series)). Issues and questions are welcome.

## Disclaimer

This is a personal research project, not investment advice. Nothing here is a recommendation to buy or sell any security or to follow any strategy. Backtest and simulated results are hypothetical, rest on simplifying assumptions (including survivorship bias in the universe) and do not predict future returns.

Market data is downloaded from third-party sources at run time and is not redistributed in this repository: no prices, volumes or other data values are committed, and reports hold only statistics derived from them.

## Licence

MIT. See [`LICENSE`](LICENSE).
