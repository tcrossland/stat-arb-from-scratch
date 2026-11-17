# Reproducing the results

How to rebuild every published result on your own machine. Parts marked *(phase N)* wait for the phase that builds them; until then they say what will be there.

## What you need

- Python 3.14 and [uv](https://docs.astral.sh/uv/). The [README](../README.md#running-it) has the setup.
- A free Alpaca account. It is paper-only, and the project calls only the market data host, `data.alpaca.markets`, never the trading API. Create a paper API key in Alpaca's dashboard and set it in the environment as `APCA_API_KEY_ID` and `APCA_API_SECRET_KEY`. Never put it in a file in the repository or in config ([decision record 0003](decisions/0003-data-sources-alpaca-and-wikipedia.md)).
- Memory for the largest runner: the phase 4 portfolio runner needs about 8 GB across its six worker processes; fewer workers (`--workers`) need less and take longer. [`docs/requirements.md`](requirements.md) has the time, memory and disk of every runner, the one place those figures are kept.

The tests need neither the key nor the network:

```bash
uv sync --locked
uv run pytest
```

## Your snapshot

Each reader downloads their own data: Alpaca's terms do not allow the project to redistribute it. The download is a raw snapshot, pinned in `config/data.toml` by its date and its digest, and the candidate list comes from the Wikipedia revision pinned in `config/universe.toml` with the date and digest of its snapshot. The build refuses a pinned snapshot whose files no longer match its digest. A snapshot you download has its own digest, so you pin yours after downloading (step 1).

**Where to keep it.** Raw snapshots live in `data/raw/`, or in the absolute path set in `STATARB_RAW`. With several worktrees, set `STATARB_RAW` to the main checkout's `data/raw/` in each, so they share one store and none holds a copy. Everything the build writes goes to `data/derived/`, which can be deleted at any time: step 1's rebuild, step 2 and the first command of step 5 rebuild its tables from the snapshots in under two minutes.

**Back it up.** Raw snapshots are the only part of the data that cannot be replaced: Alpaca revises old data, so a later download is not the same snapshot. Back up the raw store privately, outside the repository, and never commit it; `data/` is git-ignored. A snapshot is read-only once complete.

## The runners, in order

Each step gives the command, what it reads and what it writes. Each needs the steps before it: the tables of steps 1 and 2, and from step 4 the experiment logs of the steps before it.

From step 3, every runner behaves the same way in four respects:

- **It logs.** It appends its entries to `reports/phase-NN/experiments.jsonl`, each with the run state beside it: the commit, whether the tree had changes, the config overlay and the price snapshot. The committed log comes from one run on a clean tree. Running it again appends entries with the same `config_id`s and leaves the trial count unchanged.
- **`--no-log`** rebuilds the report without adding entries.
- **A config overlay** changes a setting without editing a config file ([architecture](architecture.md#data-flow)):

  ```bash
  STATARB_CONFIG_OVERLAY=path/to/overlay uv run python -m statarb.backtest.run
  ```
- **The same inputs give the same report.** From the same snapshot, config and code, it writes the same report and charts, byte for byte.

1. Download the snapshot and build the data and the universe:

   ```bash
   uv run python -m statarb.data.build --download
   ```

   It reads the pinned Wikipedia revision once and then Alpaca's bars and corporate actions for every candidate and factor ETF, paced under the free plan's limit, into new snapshots in the raw store dated by New York's date. Wikimedia asks scripts for a contact. Setting `STATARB_CONTACT` to an email or URL of your own adds it to the User-Agent; it is optional, and without it the User-Agent names the project's repository ([decision record 0003](decisions/0003-data-sources-alpaca-and-wikipedia.md)).

   The download prints the date and digest of each snapshot. Pin them, in `[source]` of `config/data.toml` and in `config/universe.toml`, so later builds read those snapshots and check them. A rebuild then needs no network and writes the same bytes each time:

   ```bash
   uv run python -m statarb.data.build
   ```

   It writes the tables of the [data model](data-model.md) to `data/derived/processed/` and the quality report to `reports/phase-00/data_quality.md`.
2. Compute Model A's residuals and the diagnostics report from the phase 0 tables:

   ```bash
   uv run python -m statarb.factors.build
   ```

   It reads `returns`, `sectors`, `prices`, `candidates` and `universe` from `data/derived/processed/` with `config/factors.toml`, needs no network, and writes `residuals.parquet` beside them and `reports/phase-01/diagnostics.md` with its charts. Building it again writes the same bytes. The window sensitivity check, which feeds nothing later, fits Model A at three windows and writes `reports/phase-01/window_sensitivity.md`:

   ```bash
   uv run python -m statarb.factors.sensitivity
   ```
3. Run the phase 2 backtests from the phase 0 and 1 tables:

   ```bash
   uv run python -m statarb.backtest.run
   ```

   It reads `returns`, `prices`, `residuals`, `universe` and `sectors` from `data/derived/processed/` with `config/backtest.toml`, needs no network and stores no table. It runs every configuration of the sweep at each fill timing, logs one entry per configuration and cost level, and writes `reports/phase-02/backtest.md` and its charts. The [phase 2 review](phases/phase-02/review.md) quotes the report's numbers.
4. Run the phase 3 cost model from the same tables:

   ```bash
   uv run python -m statarb.backtest.cost_run
   ```

   It reads the tables phase 2 reads, with `config/backtest.toml` for the signals and holding rules and `config/costs.toml` for the configurations, book sizes and cost model, needs no network and stores no table. It runs each configuration, with and without the no-trade zone, at every book size under the headline cost model and its sensitivities, logs one entry per run, and writes `reports/phase-03/costs.md` and its charts. It reads the phase 2 log for the trial count and phase 2's break-even. The [phase 3 review](phases/phase-03/review.md) quotes the report's numbers.
5. Compute Model B's residuals, then run the phase 4 portfolio paths.

   Model B needs only step 1's tables:

   ```bash
   uv run python -m statarb.factors.build --model pca
   ```

   It reads the phase 0 tables with `config/factors.toml`, writes `data/derived/processed/residuals_pca.parquet` beside Model A's table, which it leaves unchanged, and writes `reports/phase-04/model_b.md` and its chart. Building it again writes the same bytes.

   The portfolio paths need Model B's table and the logs of steps 3 and 4:

   ```bash
   uv run python -m statarb.portfolio.run
   ```

   It reads the tables phase 3 reads and `residuals_pca`, with `config/costs.toml` for the signals and cost model and `config/portfolio.toml` for the optimiser, risk models and paths, needs no network and stores no table. It runs every path at both book sizes in worker processes (`--workers`, six by default), logs one entry per path, book size and re-costed spread, and writes `reports/phase-04/portfolio.md` and its charts. It reads the earlier logs for the trial count and phase 3's no-trade zone. `--choose-risk-aversion` prints the table of the rule that set the headline λ and runs nothing else. The solver and its version are pinned in `uv.lock`, since another can return slightly different weights. Solve times vary from run to run, so the runner prints them with its progress and keeps them out of the report and log. The [phase 4 review](phases/phase-04/review.md) quotes the reports' numbers.
6. Train the phase 5 walk-forward models and run every forecast through the portfolio rules. The development run needs the tables of steps 1 and 2 and the logs of steps 3 to 5:

   ```bash
   uv run python -m statarb.models.run
   ```

   It reads the tables phase 3 reads and cuts every one at the development end in `config/models.toml` before computing anything, so it never reads the holdout. With `config/costs.toml` and `config/portfolio.toml` unchanged, it trains one LightGBM model per walk-forward block at each target horizon, writes each to `data/derived/models/` in LightGBM's text format, runs the model's forecasts and the phase 3 variants through the decile sort, the no-trade zone, the headline optimiser and partial adjustment at both book sizes (the optimiser paths in worker processes, `--workers`, four by default, then the partial-adjustment paths, each with the trade rate whose turnover matches its optimiser path's), logs one walk-forward entry per horizon, with each model file's SHA-256, and one entry per path and book size, and writes `reports/phase-05/ml.md` and its charts. It reads the earlier logs for the trial count. LightGBM trains deterministically with a fixed thread count, so a rebuilt model has the bytes of the logged one; compare a model file's SHA-256 with its block in the log. The holdout runner reads the last year, which the development run never reads, once:

   ```bash
   uv run python -m statarb.models.holdout
   ```

   It refuses a tree with changes, a configuration, overlay or snapshot that differs from the last logged development run's, and a log that already holds a read. It retrains every development model and stops unless each has its logged SHA-256, then runs every path over the holdout, partial adjustment at the development run's trade rates, logs the read and writes `reports/phase-05/holdout.md` and its chart. The committed log already holds the read, so to rebuild the report pass `--repeat`: it reads the holdout again, requires every result to equal the logged one, and appends nothing.
7. *(phase 6)* Run the daily job; its guide is `docs/daily-job.md`.

## Checking your results

Every backtest result from phase 2 is logged with its configuration and `config_id` in `reports/phase-NN/experiments.jsonl`, and each phase review links to the report that holds its numbers. What you can expect to match depends on your snapshot:

- **Whatever your snapshot,** your logs have the same `config_id`s as the committed ones, and each report counts the same trials: both come from the configuration alone, not the data.
- **On the snapshot behind the published results,** every report and chart rebuilds byte for byte. Only someone who has that snapshot can check this, since it is not redistributed.
- **On a snapshot you downloaded,** Alpaca's revisions to old data move the numbers, so they match the published ones closely, not exactly. Compare entries by `config_id`. *(Before publication)* The tolerance is measured by rebuilding the reports from two snapshots taken weeks apart and stated here; the phase 6 drift report's revision check measures the same thing.
