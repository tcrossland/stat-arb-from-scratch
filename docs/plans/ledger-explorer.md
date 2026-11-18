# Ledger explorer

Status: proposed, 2026-11-18. Not started. Backlog item: [Ledger explorer](../backlog.md#ledger-explorer).

## Purpose

The daily note reports one ledger day: its P&L, costs, the book before and after the open. The drift report compares the run with its frozen path. Neither answers the questions that span days: what has the book traded this week, what does it hold by sector and side, which names made or lost money over a window, how long positions last, and whether the run has been healthy. The explorer answers them from the ledger, locally, without changing the run.

## Constraints

- **Local only.** Decision record 0003 forbids redistributing Alpaca's data, and the ledger holds per-ticker returns and dollar holdings derived from it. The explorer runs on the owner's machine and is never hosted: no Streamlit Cloud, no Pages site, no claude.ai Artifact. Nothing it shows is committed: no screenshots of the real ledger, no exported tables.
- **Read-only.** It never writes to `data/paper/`. It reads the ledger days and the sectors table of the processed snapshot in use, and nothing else.
- **Nothing it computes enters a result.** It reads forward days by design, so nothing it produces goes into an experiment log, a report or a decision. It is not a runner and does not call `load_tables`, so the forward holdout guard is not involved.
- **Additive.** No change to the frozen config files, the engine, the daily job or any logged result. If it needs a setting, the setting goes in a config file outside the frozen record's list (`FILES` in `statarb.paper.frozen`).
- **The job's clone stays clean.** The explorer is built in the development checkout and merged to `main` like any other change. The job's clone is pulled only deliberately, and a pull of committed code changes the ledger's `git_commit`, not its results. Any cache the app writes beside itself is git-ignored, since an untracked file in the job's clone would set `git_dirty` on the next ledger day.

## What the ledger can and cannot show

The frozen rule is the optimiser, so `target` is NaN on every row: the optimiser solves at the next open on `expected_move`, and the trades it makes appear only in the next day's `trade` and `holding`. The explorer can show the expected moves behind the next open, not the trades that will follow. Under the decile sort or the no-trade zone, `target` would show them.

Weights are per unit of capital; dollars are weight times `book_size`. Day-level columns (`missing_returns`, the three costs, `slope`, `status`, the run metadata) repeat on every row and are read once per day.

## Two layers

### 1. Ad hoc queries now, with nothing in the repository

The DuckDB command line (`brew install duckdb`, licence not yet read from its own LICENSE file) queries the ledger's parquet files directly, and `duckdb -ui` gives a local browser SQL notebook. Each file carries its own `date` column, so hive partitioning is turned off:

```sql
create view ledger as
  select * from read_parquet('data/paper/ledger/*.parquet', hive_partitioning = false);
```

This covers the first weeks, while the ledger is small and the questions are still forming. The queries that recur become the views below.

### 2. Views in `src/statarb/paper/`, and an app over them

**`statarb.paper.views`**: pure functions from ledger frames, with the sectors table where needed, to tables. Loading is the only function that touches files, and it uses `statarb.paper.ledger.dates` and `read_day`. Candidate views:

| View | Over | Shows |
|---|---|---|
| Book | one day | each name's `holding` long and short, gross and net exposure, name count, sector weights, largest positions, in weight and dollars |
| Trades | a window | each non-zero `trade` with `drifted` and `holding`, in dollars, and each day's spread, impact and commission costs |
| Next open | the latest day | `expected_move` for each name, against its `holding`: what the optimiser solves on at the next open |
| Attribution | a window | `pnl` and `borrow` by ticker, by sector and by side, and the day's costs |
| Ticker | one ticker | its `held`, `holding` and `expected_move` over time, entries and exits, holding periods and P&L contributed |
| Health | every day | `missing_returns`, `status`, `git_dirty`, `git_commit`, `snapshot`, and the result of `statarb.paper.ledger.check` |

Sector weights use the dated rule in `docs/data-model.md`: a ticker's sector on day *d* is the row with `valid_from <= d` and `valid_to` null or later than *d*. Hedge ETFs have no sector row and are shown as their own group.

**`notebooks/ledger.py`**: a [marimo](https://marimo.io) app over the views, run with `marimo run notebooks/ledger.py`. A day picker, a window picker and a ticker picker drive the views; charts use matplotlib as elsewhere. marimo is chosen over Jupyter and Streamlit because the file is plain Python with no stored outputs, which meets the rule in `notebooks/README.md` without a stripping step, and because one file serves as an app and as a notebook for digging. Streamlit would do as well as an app, with more dependencies for the licence test to cover.

The app takes the root of the checkout whose ledger it reads as an argument, defaulting to the current checkout, so it can read the job's clone from the development checkout. No path is committed.

## Dependencies

- **marimo**, in a non-default `uv` dependency group (`explore`), so the daily job's environment does not change. Its licence and those of its dependencies are read from their own package metadata in the change that adds it, and `tests/test_licences.py` covers them once installed.
- **DuckDB** as a command-line tool from Homebrew, outside `pyproject.toml`. Not needed by the views or the app.

## Testing

- A synthetic ledger builder in `tests/`: a few chained days over a handful of made-up tickers, written with `statarb.paper.ledger.write_day`, that passes `statarb.paper.ledger.check`. The existing helpers in `tests/test_paper_ledger.py` are the starting point.
- A unit test per view on that ledger, with hand-checked totals: the book's gross and net, trades equal to `holding` minus `drifted`, attribution summing to the day's `pnl`, sector assignment across a sector change.
- A test that loading reads no file outside the ledger and sectors paths it is given, and writes none.
- The app is not tested beyond importing it. Any screenshot used in the README or the docs is taken on the synthetic ledger and says so.

## Steps

One commit each, on a branch from `main`:

1. `feat(paper)`: `statarb.paper.views` with the synthetic ledger builder and tests.
2. `build`: the `explore` dependency group with marimo, its licence stated in the body; `.gitignore` for any cache the app writes.
3. `feat(paper)`: `notebooks/ledger.py`.
4. `docs`: `docs/architecture.md` (the module, the notebook and the library), `docs/daily-job.md` (how to open the explorer on the job's ledger) and `docs/README.md`. Remove the backlog item and mark this plan done.

## Open questions

- Whether the views belong in `statarb.paper` or a package of their own. They read only the ledger, so `statarb.paper` for now.
- Whether the daily note should link to the explorer, or stay self-contained. Self-contained for now: the note is committed and the explorer is local.
