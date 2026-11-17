# Architecture

The packages, runners and config files, what each reads and writes, and the external libraries each enters through. `tests/test_architecture_doc.py` checks the module, runner and config tables against the code.

## Data flow

```mermaid
flowchart LR
    W["Wikipedia<br/>constituent page"] -->|--download| RW["raw store<br/>wikipedia/&lt;date&gt;/"]
    A["Alpaca<br/>bars and corporate actions"] -->|--download| RA["raw store<br/>alpaca/&lt;date&gt;/"]
    RW --> B["statarb.data.build"]
    RA --> B
    C["config/*.toml"] --> B
    B --> P["data/derived/processed/<br/>phase 0 tables"]
    B --> Q["reports/phase-00/data_quality.md"]
    P --> F["statarb.factors.build"]
    CF["config/factors.toml"] --> F
    F --> RS["data/derived/processed/<br/>residuals.parquet"]
    F --> FR["reports/phase-01/<br/>diagnostics.md and charts"]
    P --> BT["statarb.backtest.run"]
    RS --> BT
    CB["config/backtest.toml"] --> BT
    BT --> BR["reports/phase-02/<br/>backtest.md, charts and<br/>experiments.jsonl"]
    P --> CR["statarb.backtest.cost_run"]
    RS --> CR
    CB --> CR
    CC["config/costs.toml"] --> CR
    BR -->|trials| CR
    CR --> CRR["reports/phase-03/<br/>costs.md, charts and<br/>experiments.jsonl"]
    P --> FB["statarb.factors.build<br/>--model pca"]
    RS --> FB
    CF --> FB
    FB --> RB["data/derived/processed/<br/>residuals_pca.parquet"]
    FB --> FBR["reports/phase-04/<br/>model_b.md and chart"]
```

Only `--download` touches the network. A rebuild reads the pinned snapshots and the config, and writes the same bytes each time. Phases 2 and 3 store no table: every backtest, and every cost input (spread estimates, volatilities, volumes), is recomputed from the phase 0 and 1 tables, and only reports and experiment logs are written.

**Where data lives.** The raw store, `data/raw/` or the absolute path in `STATARB_RAW`, holds the raw snapshots: kept, read-only once complete and backed up outside the repository. Worktrees set `STATARB_RAW` to the main checkout's `data/raw/`, so there is one store. `data/derived/` holds everything rebuilt from it and can be deleted. Nothing under `data/` is committed or versioned: snapshots are versioned by convention instead, by date and content digest pinned in config.

**Config overlays.** An experiment that varies a setting never edits a file in `config/`. It sets `STATARB_CONFIG_OVERLAY` to a directory, relative to the repository root or absolute, and each `<name>.toml` in it is merged over `config/<name>.toml` by `statarb.config.load_config`: tables key by key, other values replaced, and a key the base file lacks refused. An overlay of `data.toml` can point `[paths]` at other tables and another reports directory, so an experiment on other data writes nothing over the committed results. Every experiment log entry records the overlay, if one was set, in its `run_state`.

## Modules

| Module | Phase | Purpose |
|---|---|---|
| `statarb.config` | 0 | Loads `config/<name>.toml` with any config overlay merged over it (`STATARB_CONFIG_OVERLAY`, from phase 2), resolves configured paths against the repository root, and finds the raw store (`STATARB_RAW`). |
| `statarb.io` | 0 | Deterministic parquet: fixed compression, rows sorted by key, written to a temporary file and renamed. |
| `statarb.testing` | 0 | Helpers for tests that the package itself also provides. |
| `statarb.testing.lookahead` | 0 | The look-ahead check: perturb data after a cut-off, assert outputs up to it are unchanged. |
| `statarb.testing.prices` | 3 | Simulated daily prices with a known spread, reversal and opening noise, for the spread estimators' tests and the phase 3 report. |
| `statarb.data` | 0 | The data build. |
| `statarb.data.schema` | 0 | Column names, the bar schema, GICS sector names and the exchange's date (`exchange_today`). |
| `statarb.data.sources` | 0 | The `PriceSource` and `ConstituentSource` protocols and the price bases a source can declare. |
| `statarb.data.cache` | 0 | Raw snapshots: written once, complete when `manifest.json` with every file's hash and the digest is written last, then read-only; verified against the pinned digest. |
| `statarb.data.snapshot` | 0 | Reads a price snapshot as bars whatever its layout, applying a raw snapshot's rules. |
| `statarb.data.alpaca` | 0 | The Alpaca price source and the rules of decision record 0004. |
| `statarb.data.wikipedia` | 0 | The Wikipedia constituent source, with the request policies of decision record 0003. |
| `statarb.data.canonical` | 0 | Converts a source's declared basis to unadjusted bars. |
| `statarb.data.clean` | 0 | Cleaning rules, each dropped row logged with its reason. |
| `statarb.data.returns` | 0 | Daily total returns from unadjusted bars, splits and cash. |
| `statarb.data.universe` | 0 | Monthly universe from trailing median dollar volume. |
| `statarb.data.sectors` | 0 | Dated GICS sectors from current sectors and recorded changes. |
| `statarb.data.quality` | 0 | The data quality report: statistics only. |
| `statarb.data.build` | 0 | Runner: downloads snapshots on request, builds the tables and the report. |
| `statarb.factors` | 1 | Factor models and residual returns. |
| `statarb.factors.rolling` | 1 | Rolling least squares on a dates by stocks panel, each window ending the day before. |
| `statarb.factors.model` | 1 | The `FactorModel` protocol and Model A, the ETF regression. |
| `statarb.factors.pca` | 4 | Model B: residuals on the top principal components of standardised returns over the window ending *t−1* (Avellaneda and Lee, section 2.1), with each stock's betas and the eigenvalues. |
| `statarb.factors.compare` | 4 | Model B's diagnostics beside Model A's on the rows both have: residual size and overlap, pairwise correlation, reversal by lag, year and size. |
| `statarb.factors.events` | 1 | The crude event flag: volume over its trailing median, on one share basis. |
| `statarb.factors.report` | 1 | The diagnostics report and its charts: statistics only, computed apart from writing them. |
| `statarb.factors.build` | 1 | Runner: Model A's residuals with the event flag, from the phase 0 tables, and the diagnostics report; from phase 4, with `--model pca`, Model B's residuals and their comparison with Model A's. |
| `statarb.factors.sensitivity` | 1 | Runner: Model A at 60, 126 and 252 days compared on common rows; feeds nothing later. |
| `statarb.signals` | 2 | Signals behind the `Signal` interface. |
| `statarb.signals.tables` | 2 | The phase 0 and 1 tables as dates by tickers panels, the tables a signal may declare, and the s-score's factor inputs. |
| `statarb.signals.base` | 2 | The `Signal` protocol, and the scores and hedge ratios a signal returns. |
| `statarb.signals.reversal` | 2 | Cross-sectional reversal on residuals or on total returns, optionally scaled by volatility. |
| `statarb.signals.sscore` | 2 | Avellaneda and Lee's s-score from a 60-day in-sample regression and an AR(1) fit. |
| `statarb.signals.registry` | 2 | Every signal by the name config chooses it by; the look-ahead contract runs over it. |
| `statarb.signals.calibration` | 3 | A signal in return units: the expected move over the next *k* days, from a trailing pooled regression on pairs whose outcome is known. |
| `statarb.backtest` | 2 | The backtest engine, portfolio rules, metrics and the experiment log. |
| `statarb.backtest.config` | 2 | `config/backtest.toml` and, from phase 3, `config/costs.toml` as frozen dataclasses that reject unknown or missing keys. |
| `statarb.backtest.costs` | 2 | The `CostModel` protocol and the flat cost per dollar traded; from phase 3 the cost inputs, `TradingCost` (half-spread, square-root impact, commission), the borrow rates and the no-trade zone. |
| `statarb.backtest.spreads` | 3 | The EDGE, Abdi-Ranaldo and Corwin-Schultz spread estimators, rolling over a trailing window. |
| `statarb.backtest.engine` | 2 | Fill grids at the close and the open, the daily engine from target weights to holdings, trades and P&L with an optional `Policy` at each fill (phase 3), and daily returns on gross. |
| `statarb.backtest.rules` | 2 | The `PortfolioRule` protocol: decile books held in *k* slices, and the s-score thresholds with their hedges. |
| `statarb.backtest.metrics` | 2 | Sharpe, drawdown, break-even cost, hit rates, P&L by year and the deflated Sharpe ratio. |
| `statarb.backtest.experiments` | 2 | The experiment log: entries with `config_id`, `run_state` and metrics, appended as JSON Lines. |
| `statarb.backtest.trials` | 2 | Every distinct position path in the repository's experiment logs up to a phase, for the deflated Sharpe. |
| `statarb.backtest.sweep` | 2 | The phase 2 configurations: each variant's signal and rule, the fill grids, costs and the logged record. |
| `statarb.backtest.report` | 2 | The phase 2 report and its charts: statistics only. |
| `statarb.backtest.run` | 2 | Runner: the phase 2 sweep, the placebo, the experiment log and the report. |
| `statarb.backtest.cost_run` | 3 | Runner: the phase 3 configurations under the cost model at each book size and cost setting, the no-trade zone, the judgement against the bar and the experiment log. |
| `statarb.backtest.cost_report` | 3 | The phase 3 report and its charts: statistics only. |

## Seams

| Protocol | Implementations | Chosen by |
|---|---|---|
| `PriceSource` | `AlpacaSource`; synthetic sources in `tests/helpers.py` | `[source] name` in `config/data.toml` |
| `ConstituentSource` | `WikipediaConstituents` | fixed in phase 0 |
| `FactorModel` | `EtfFactorModel` (Model A), `PcaFactorModel` (Model B) | `--model` of `statarb.factors.build`; each writes its own table |
| `Signal` | `ReversalSignal` on residuals (`residual`) and on total returns (`raw`), `SScoreSignal` (`sscore`) | name, in `[[signals]]`, `[headline]` and `[sscore]` of `config/backtest.toml`, through `statarb.signals.registry` |
| `PortfolioRule` | `DecileRule`, `ThresholdRule` | the variant: decile signals take the decile rule, the s-score its thresholds |
| `CostModel` | `FlatCost`, `TradingCost` | phase 2: the cost levels in `[costs]` of `config/backtest.toml`; phase 3: `[spread]`, `[impact]` and `[commission]` of `config/costs.toml` |
| `Policy` (engine) | none, the default; `NoTradeZone`; phase 4's optimiser is the next | phase 3: each decile configuration runs with and without the zone |

`tests/contract/` runs every implementation of each protocol through the same checks: `test_signals.py` runs every registered signal through the look-ahead test and checks it reads only the tables it declares. `FactorModel` has one implementation until phase 4, so its checks are in `tests/test_factors.py` until then; the portfolio rules and the flat cost are checked in `tests/test_backtest.py`, and `TradingCost` and the no-trade zone in `tests/test_costs.py`.

## Runners

| Runner | Phase | Reads | Writes |
|---|---|---|---|
| `statarb.data.build` | 0 | the raw store, `config/data.toml`, `config/universe.toml`, `config/sector_changes.toml`, `config/listing_starts.toml`, `config/alpaca.toml`; with `--download` also Wikipedia and Alpaca | the phase 0 tables in `data/derived/processed/`, `reports/phase-00/data_quality.md`; with `--download` a new snapshot in the raw store; with `--add-hashes` the hashes in a manifest that lacks them, and nothing else |
| `statarb.factors.build` | 1 | `returns`, `sectors`, `prices`, `candidates` and `universe` in `data/derived/processed/`, `config/data.toml`, `config/factors.toml`; with `--model pca` also `residuals` | `data/derived/processed/residuals.parquet`, `reports/phase-01/diagnostics.md` and its charts; with `--model pca` instead `data/derived/processed/residuals_pca.parquet` and `reports/phase-04/model_b.md` with its chart |
| `statarb.factors.sensitivity` | 1 | the same tables and config as `statarb.factors.build` | `reports/phase-01/window_sensitivity.md` |
| `statarb.backtest.run` | 2 | `returns`, `prices`, `residuals`, `universe` and `sectors` in `data/derived/processed/`, `config/data.toml`, `config/factors.toml`, `config/backtest.toml`, and the experiment logs up to phase 2 for the trial count | `reports/phase-02/backtest.md` and its charts; appends to `reports/phase-02/experiments.jsonl` unless `--no-log` |
| `statarb.backtest.cost_run` | 3 | the same tables as `statarb.backtest.run`, `config/data.toml`, `config/factors.toml`, `config/backtest.toml`, `config/costs.toml`, and the experiment logs before phase 3 for the trial count and phase 2's break-even | `reports/phase-03/costs.md` and its charts; appends to `reports/phase-03/experiments.jsonl` unless `--no-log` |

## Config files

| File | Read by | Holds |
|---|---|---|
| `data.toml` | `statarb.data.build`, `statarb.factors.build`, `statarb.factors.sensitivity`, `statarb.backtest.run`, `statarb.backtest.cost_run` | Start date, price source and the pinned snapshot's date and digest, download pacing, universe, factor ETFs, quality thresholds, paths. |
| `universe.toml` | `statarb.data.build` | The pinned Wikipedia revision, and the date and digest of the snapshot of it the build reads. |
| `sector_changes.toml` | `statarb.data.sectors` | GICS sector changes since 2016 with effective dates. |
| `listing_starts.toml` | `statarb.data.clean` | First trading dates for tickers whose source history starts before their listing, with sources. |
| `alpaca.toml` | `statarb.data.alpaca` | Withholding, repeated dividends and corrections to Alpaca's corporate actions, each with a primary source. |
| `factors.toml` | `statarb.factors.build`, `statarb.factors.sensitivity`, `statarb.backtest.run`, `statarb.backtest.cost_run` | Model A's window, minimum history and sector factor, the ETF of each GICS sector, the event flag's settings and the report's buckets, lags and calm year. |
| `backtest.toml` | `statarb.backtest.config` | The first signal date, the placebo's seed and runs, the decile and volatility window, cost levels and borrow, fill timings and slippage, holding periods, the headline, the decile signals and the s-score's settings. Phase 3 reads its signals, portfolio and s-score settings unchanged. |
| `costs.toml` | `statarb.backtest.config` | The phase 3 fill, book sizes and configurations; the assumed half-spread, its bracket and floor, and the estimators' window and size groups; the impact coefficients and windows; the commission schedules with the date and page they were read from; the borrow rates and hard-to-borrow proxy; the no-trade zone's calibration window. |

## External libraries

| Library | Licence | Enters through | Used for |
|---|---|---|---|
| pandas | BSD-3-Clause | every `statarb.data` and `statarb.factors` module; `signals.tables` and `backtest.engine` | long-format tables, and the wide panels the backtest pivots them into |
| NumPy | BSD-3-Clause, with bundled 0BSD, MIT, Zlib and CC0-1.0 parts | `canonical`, `testing.lookahead`, `factors.rolling`, `factors.model`; `backtest.engine`, `backtest.rules`, `signals.sscore`; `backtest.costs`, `backtest.spreads`, `signals.calibration`, `testing.prices` | array arithmetic, seeded noise, the rolling regression, and the engine and s-score on dates by tickers arrays |
| pyarrow | Apache-2.0 | `statarb.io` | parquet |
| lxml | BSD-3-Clause | `statarb.data.wikipedia`, through `pandas.read_html` | parsing the constituent table |
| matplotlib | Matplotlib License, based on the PSF licence | `statarb.factors.report`; `statarb.backtest.report`, `statarb.backtest.cost_report`; `statarb.factors.compare`, `statarb.portfolio.report` | charts, saved with no date or software metadata |
| SciPy 1.18.1 | BSD-3-Clause; its wheels bundle OpenBLAS (BSD-3-Clause), LAPACK (BSD-3-Clause-Open-MPI) and the GCC runtime library (GPL-3.0-or-later with the GCC Runtime Library Exception 3.1) | `statarb.factors.pca`; through cvxpy, the solver's sparse matrices | the top eigenvectors of the correlation matrix (`scipy.linalg.eigh`) |
| cvxpy 1.9.3 | Apache-2.0 | `statarb.portfolio.optimiser` | stating the day's convex problem and handing it to the solver |
| Clarabel 0.11.1 | Apache-2.0 | `statarb.portfolio.optimiser`, through cvxpy, named in `[optimiser] solver` | the interior-point solver for the second-order cone problem |

cvxpy brings its own dependencies, none imported by the project: OSQP (Apache-2.0), SCS (MIT), HiGHS through `highspy` (MIT), QDLDL (Apache-2.0), cffi (MIT-0), pycparser (BSD-3-Clause), Jinja2 (BSD-3-Clause), MarkupSafe (BSD-3-Clause), joblib (BSD-3-Clause), cloudpickle (BSD-3-Clause), setuptools (MIT) and SparseDiffPy (Apache-2.0). Each licence is read from the distribution's own metadata; `tests/test_licences.py` checks every installed distribution. cvxpy, Clarabel and SciPy are pinned exactly: another solver or version can return slightly different weights.

The HTTP clients use the standard library (`urllib`), so no client library is pinned, and the deflated Sharpe's normal distribution is the standard library's `statistics.NormalDist`. Phases 2 and 3 add no library; phase 4 adds SciPy, cvxpy and Clarabel. Each later phase adds its libraries to `pyproject.toml` and to this table when it first uses them.
