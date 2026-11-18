# Notebooks

For exploration only. Nothing another phase depends on lives here: it moves to `src/statarb/` with tests. Notebooks are committed without outputs, since outputs can hold data values.

- [`ledger.py`](ledger.py): the ledger explorer, a [marimo](https://marimo.io) app over `statarb.paper.views`, with its theme in [`ledger.css`](ledger.css). How to run it is in [the daily-job guide](../docs/daily-job.md#exploring-the-ledger).
- [`ledger.sql`](ledger.sql): the same views for the [DuckDB](https://duckdb.org) command line, `duckdb -init notebooks/ledger.sql`, checked against the Python views by `tests/test_ledger_sql.py`.

marimo writes a session cache with the cells' outputs to `__marimo__/` beside the notebook, which is git-ignored.
