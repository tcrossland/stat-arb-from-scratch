# Reproducing the results

How to rebuild every published result on your own machine. Parts marked *(phase N)* wait for the phase that builds them; until then they say what will be there.

## What you need

- Python 3.14 and [uv](https://docs.astral.sh/uv/). The [README](../README.md#running-it) has the setup.
- A free Alpaca account. It is paper-only, and the project calls only the market data host, `data.alpaca.markets`, never the trading API. Create a paper API key in Alpaca's dashboard and set it in the environment as `APCA_API_KEY_ID` and `APCA_API_SECRET_KEY`. Never put it in a file in the repository or in config ([decision record 0003](decisions/0003-data-sources-alpaca-and-wikipedia.md)).

The tests need neither the key nor the network:

```bash
uv sync --locked
uv run pytest
```

## Your snapshot

Each reader downloads their own data: Alpaca's terms do not allow the project to redistribute it. The download is a raw snapshot, pinned in `config/data.toml` by its date and its digest, and the candidate list comes from the Wikipedia revision pinned in `config/universe.toml` with the date and digest of its snapshot. The build refuses a pinned snapshot whose files no longer match its digest. A snapshot downloaded by a reader has its own digest, so pin yours after downloading; the download prints both settings.

**Where to keep it.** Raw snapshots live in `data/raw/`, or in the absolute path set in `STATARB_RAW`. With several worktrees, set `STATARB_RAW` to the main checkout's `data/raw/` in each, so they share one store and none holds a copy. Everything the build writes goes to `data/derived/`, which can be deleted at any time and rebuilt in seconds.

**Back it up.** Raw snapshots are the only part of the data that cannot be replaced: Alpaca revises old data, so a later download is not the same snapshot. Back up the raw store privately, outside the repository, and never commit it; `data/` is git-ignored. A snapshot is read-only once complete. The one change ever made to one is adding file hashes to a manifest that lacks them:

```bash
uv run python -m statarb.data.build --add-hashes <raw store>/<source>/<date>
```

It prints the digest to pin and touches nothing but the manifest.

Alpaca revises old data, so a snapshot taken later is not byte for byte the one behind the published results. Your numbers will match the published ones closely, not exactly. *(Before publication)* The tolerance is measured by rebuilding the reports from two snapshots taken weeks apart and stated here; the phase 6 drift report's revision check measures the same thing.

## The runners, in order

*(Phase 0 onwards)* Each phase adds its runners here as it lands: the command, what it reads and what it writes. The time, memory and disk each one needs are in [`docs/requirements.md`](requirements.md), the one place those figures are kept.

1. Download the snapshot and build the data and the universe:

   ```bash
   uv run python -m statarb.data.build --download
   ```

   It reads the pinned Wikipedia revision once and then Alpaca's bars and corporate actions for every candidate and factor ETF, paced under the free plan's limit, into new snapshots in the raw store dated by New York's date. Wikimedia asks scripts for a contact: set `STATARB_CONTACT` to an email or URL of your own to add it to the User-Agent ([decision record 0003](decisions/0003-data-sources-alpaca-and-wikipedia.md)). It then prints the date and digest to pin for each snapshot: set them in `[source]` of `config/data.toml` and in `config/universe.toml`, so later builds read those snapshots and check them. A rebuild needs no network and writes the same bytes each time:

   ```bash
   uv run python -m statarb.data.build
   ```

   It writes the tables of the [data model](data-model.md) to `data/derived/processed/` and the quality report to `reports/phase-00/data_quality.md`.
2. Compute Model A's residuals and the diagnostics report from the phase 0 tables:

   ```bash
   uv run python -m statarb.factors.build
   ```

   It reads `returns`, `sectors`, `prices`, `candidates` and `universe` from `data/derived/processed/` with `config/factors.toml`, needs no network, and writes `residuals.parquet` beside them and `reports/phase-01/diagnostics.md` with its charts. A rebuild writes the same bytes. The window sensitivity check, which feeds nothing later, reruns Model A at three windows and writes `reports/phase-01/window_sensitivity.md`:

   ```bash
   uv run python -m statarb.factors.sensitivity
   ```
3. Run the phase 2 backtests from the phase 0 and 1 tables:

   ```bash
   uv run python -m statarb.backtest.run
   ```

   It reads `returns`, `prices`, `residuals`, `universe` and `sectors` from `data/derived/processed/` with `config/backtest.toml`, needs no network and stores no table. It runs every configuration of the sweep at each fill timing, appends one entry per configuration and cost level to `reports/phase-02/experiments.jsonl` with the run state beside it, and writes `reports/phase-02/backtest.md` and its charts. A rerun writes the same report and charts. The committed log comes from one run on a clean tree; another run appends entries with the same `config_id`s and leaves the trial count unchanged. Add `--no-log` to rebuild the report without adding entries; compare your entries with the committed ones by `config_id`. The [phase 2 review](phases/phase-02/review.md) quotes the report's numbers. To try another setting, put it in a config overlay rather than editing `config/backtest.toml` ([architecture](architecture.md#data-flow)):

   ```bash
   STATARB_CONFIG_OVERLAY=path/to/overlay uv run python -m statarb.backtest.run
   ```
4. *(phase 3)* Run the cost model and its sweeps.
5. *(phase 4)* Run the optimiser and Model B.
6. *(phase 5)* Train the walk-forward models.
7. *(phase 6)* Run the daily job; its guide is `docs/daily-job.md`.

## Checking your results

From phase 2, every backtest result is logged with its configuration and `config_id` in `reports/phase-NN/experiments.jsonl`, and each phase review links to the report that holds its numbers. Compare your reports with those, within the tolerance above.
