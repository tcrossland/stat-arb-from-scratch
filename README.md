# Residual mean reversion in US equities: an end-to-end statistical arbitrage pipeline

A daily statistical arbitrage pipeline for US equities, from raw market data to a forward-running paper trade, built to answer one question: does cross-sectional residual mean reversion survive realistic trading costs and an honest count of everything tried? Simulation only.

## Results

Each phase review adds its findings here, whichever way they go.

- **Phase 0, data and universe.** A daily build of S&P 500 candidates and factor ETFs from free data, reproducible byte for byte from pinned snapshots, with the source's quirks fixed under the numbered rules of decision record 0004. The universe uses today's constituents, so it carries survivorship bias. [Review](docs/phases/phase-00/review.md), [quality report](reports/phase-00/data_quality.md).
- **Phase 1, factor model and residuals.** Regressing each stock on the market and its sector ETF removes almost all common movement. Residuals reverse slightly from one day to the next, no more than raw returns do but more steadily, and in every year but 2022. [Review](docs/phases/phase-01/review.md), [diagnostics](reports/phase-01/diagnostics.md).
- **Phase 2, reversal signal and backtest.** Residual reversal earns a small gross return that a retail-sized trading cost more than removes, at every holding period, fill and lookback tried. Holding longer and looking back further help; the best of all the configurations tried is suggestive gross and not significant net. [Review](docs/phases/phase-02/review.md), [backtest report](reports/phase-02/backtest.md).
- **Phase 3, cost realism.** Under spread, impact, commission and borrow, no configuration keeps a net edge at any book size tried. Commission's per-order minimum binds a retail book, and impact a large one. A filter that trades only when the expected move pays the cost turns the decile books' net Sharpe positive, by trading little, and none clears the bar for a net edge. The daily-price spread estimators read the strategy's own reversal as spread, so the spread is a stated assumption. [Review](docs/phases/phase-03/review.md), [cost report](reports/phase-03/costs.md).

## Architecture

```mermaid
flowchart LR
    S["raw snapshots<br/>Alpaca, Wikipedia"] --> D["data build<br/>universe, returns"] --> F["factor model<br/>Model A: ETFs<br/>Model B: PCA"] --> G["signal"] --> P["portfolio rule<br/>decile sort, no-trade zone,<br/>optimiser"] --> B["backtest and<br/>paper trade"]
    R["risk model"] --> P
    C["cost model"] --> P
    C --> B
```

Each stage is a function of the tables before it, cut at the decision date, which is what lets a test check it for look-ahead. Each seam (the price and constituent sources, the factor model, the signal, the cost model, the portfolio rule and the risk model) is a typed interface whose implementations all pass the same contract tests, chosen by name in config and recorded with every result.

## Invariants

Each phase holds to these:

- **No look-ahead.** Every value used on a day must have been knowable that day. Every transform and every signal passes a test that perturbs later data and requires nothing earlier to change ([time discipline](docs/time-discipline.md)).
- **Reproducible.** Every result reproduces exactly from a pinned data snapshot, its config and seed, in the environment fixed by `uv.lock`. Raw snapshots are never modified.
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

| Phase | Adds | Status |
|-------|------|--------|
| 0 | Prices, returns and a liquidity-ranked universe | done |
| 1 | Factor model and residuals | done |
| 2 | Reversal signal and backtest engine | done |
| 3 | Cost model | done |
| 4 | Portfolio optimiser and a statistical factor model | not started |
| 5 | ML signal | not started |
| 6 | Daily paper-trading simulation | not started |

## Running it

Needs Python 3.14 and [uv](https://docs.astral.sh/uv/). No GPU is needed.

### Run the tests

The tests run on small synthetic fixtures committed under `tests/`. They need no download, no keys and no network.

```
uv sync
uv run ruff check
uv run pytest
```

### Build the data

The phase 0 build turns pinned raw snapshots (in `data/raw/`, or the shared store named by `STATARB_RAW`) into the tables of [the data model](docs/data-model.md) and a quality report. The first build in a fresh clone downloads the snapshot; downloading needs the keys of a free, paper-only [Alpaca](https://alpaca.markets/) account in `APCA_API_KEY_ID` and `APCA_API_SECRET_KEY`, and only Alpaca's market data host is called (decision record 0003). Nothing else needs them.

```
uv run python -m statarb.data.build --download
uv run python -m statarb.data.build
```

### Build the residuals

The phase 1 build reads the phase 0 tables, needs no network, and writes the residual table and the diagnostics report:

```
uv run python -m statarb.factors.build
```

[Reproducing the results](docs/reproduce.md) covers pinning the snapshot and what each step reads and writes.

## Disclaimer

This is a personal research project, not investment advice. Nothing here is a recommendation to buy or sell any security or to follow any strategy. Backtest and simulated results are hypothetical, rest on simplifying assumptions (including survivorship bias in the universe) and do not predict future returns.

Market data is downloaded from third-party sources at run time and is not redistributed in this repository: no prices, volumes or other data values are committed, and reports hold only statistics derived from them.

Issues and questions are welcome.

## Licence

MIT. See [`LICENSE`](LICENSE).
