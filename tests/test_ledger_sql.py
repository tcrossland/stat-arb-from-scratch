"""notebooks/ledger.sql, the ledger explorer for the DuckDB command line, gives what `statarb.paper.views` gives.

Two implementations of the same views, so each SQL view is held to the Python one on the synthetic ledger, as
the reversal run records it and as a momentum path does.
"""

from __future__ import annotations

import shutil

import pandas as pd
import pytest

from statarb.config import load_config, repo_root, resolve_path
from statarb.data.schema import DATE, TICKER
from statarb.paper import momentum, views
from synthetic_ledger import DATES, SECTORS, concat, frames, write

duckdb = pytest.importorskip("duckdb")

SQL = repo_root() / "notebooks" / "ledger.sql"
PATHS = tuple(spec.name for spec in momentum.load_momentum_config(repo_root()).runs)


@pytest.fixture(scope="module", params=[views.REVERSAL, PATHS[0]])
def name(request) -> str:
    return request.param


@pytest.fixture(scope="module")
def frame(name) -> pd.DataFrame:
    return concat(frames(momentum=name != views.REVERSAL))


@pytest.fixture(scope="module")
def sql(tmp_path_factory, name):
    """A connection with the views loaded, reading a synthetic ledger: the reversal run's, or a momentum path's."""
    paper = tmp_path_factory.mktemp("paper")
    write(paper, path=None if name == views.REVERSAL else name)
    con = duckdb.connect()
    con.execute("CREATE MACRO getenv(name) AS NULL")          # the command-line client's function; see the file's head
    con.execute("SET VARIABLE paper = ?", [str(paper)])
    con.execute("SET VARIABLE ledger_name = ?", [name])
    con.execute(SQL.read_text())
    yield con
    con.close()


@pytest.mark.parametrize("ledger", [views.REVERSAL, *PATHS])
def test_the_command_line_finds_each_ledger_where_the_config_puts_it(tmp_path, ledger) -> None:
    """From the environment alone, as the command-line client reads it, the SQL opens the ledger `views.load` opens:
    its folders are those of `[paths] paper` in config/data.toml and config/momentum_forward.toml."""
    (tmp_path / "config").mkdir()
    for config in ("data.toml", "momentum_forward.toml"):
        shutil.copy(repo_root() / "config" / config, tmp_path / "config" / config)
    write(resolve_path(load_config("data", tmp_path)["paths"]["paper"], tmp_path))
    for seed, path in enumerate(PATHS, start=1):
        write(momentum.paper_dir(tmp_path, momentum.load_momentum_config(tmp_path)), seed, path=path)
    env = {"STATARB_LEDGER_ROOT": str(tmp_path), "STATARB_LEDGER": "" if ledger == views.REVERSAL else ledger}
    con = duckdb.connect()
    con.execute("CREATE MACRO getenv(name) AS CASE " + " ".join(f"WHEN name = '{k}' THEN '{v}'" for k, v in env.items()) + " END")
    con.execute(SQL.read_text())
    loaded = views.load(tmp_path, ledger)
    _same(con.execute("FROM ledger").df(), concat([loaded.frame]), [DATE, TICKER])
    _same(con.execute("FROM sectors").df(), loaded.sectors, [TICKER, "valid_from"])
    con.close()


def _same(got: pd.DataFrame, want: pd.DataFrame, by: list[str]) -> None:
    """The same rows and columns, whatever the row order within ties and the dtypes' widths."""
    assert list(got.columns) == list(want.columns)
    got, want = (t.sort_values(by, kind="mergesort").reset_index(drop=True) for t in (got, want))
    for column in want.columns:
        if pd.api.types.is_datetime64_any_dtype(want[column]):
            got[column], want[column] = got[column].astype("datetime64[ns]"), want[column].astype("datetime64[ns]")
        elif not pd.api.types.is_numeric_dtype(want[column]) or pd.api.types.is_bool_dtype(want[column]):
            got[column], want[column] = got[column].astype(object), want[column].astype(object)
    pd.testing.assert_frame_equal(got, want, check_dtype=False, rtol=1e-9, atol=1e-12)


def test_the_guide_lists_every_view_and_macro(sql) -> None:
    listed = {name.split("(")[0] for (name,) in sql.execute("SELECT name FROM guide").fetchall()}
    made = {name for (name,) in sql.execute("SELECT view_name FROM duckdb_views() WHERE NOT internal").fetchall()}
    made |= {name for (name,) in sql.execute("SELECT function_name FROM duckdb_functions() WHERE NOT internal AND function_type = 'table_macro'").fetchall()}
    assert listed == made - {"guide"}
    widest = sql.execute("SELECT max(length(name)), max(length(shows)) FROM guide").fetchone()
    assert sum(widest) <= 80 - 7, "the guide wraps in an 80-column terminal"


def test_the_ledger_and_sectors_are_read_whole(sql, frame) -> None:
    _same(sql.execute("FROM ledger").df(), frame, [DATE, TICKER])
    _same(sql.execute("FROM sectors").df(), SECTORS, [TICKER, "valid_from"])
    _same(sql.execute("FROM named").df(), views.with_sector(frame, SECTORS), [DATE, TICKER])


@pytest.mark.parametrize("day", [DATES[1], DATES[3], DATES[5]])
def test_book_and_its_sectors(sql, frame, day) -> None:
    want = views.book(frame, SECTORS, day)
    _same(sql.execute("FROM book_on(?)", [day.date()]).df(), want, [TICKER])
    got = sql.execute("SELECT * EXCLUDE (date) FROM sector_exposure WHERE date = ?", [day.date()]).df()
    _same(got, views.sector_exposure(want).reset_index(), ["sector"])


def test_book_on_defaults_to_the_latest_day(sql, frame) -> None:
    _same(sql.execute("FROM book_on()").df(), views.book(frame, SECTORS, DATES[-1]), [TICKER])


def test_the_book_is_largest_first(sql) -> None:
    held = sql.execute("FROM book_on()").df()["holding"].abs()
    assert list(held) == sorted(held, reverse=True)


def test_exposure_trades_pnl_and_health(sql, frame) -> None:
    _same(sql.execute("FROM exposure").df(), views.exposure(frame).reset_index(), [DATE])
    _same(sql.execute("FROM trades").df(), views.trades(frame), [DATE, TICKER])
    _same(sql.execute("FROM pnl").df(), views.pnl(frame).reset_index(), [DATE])
    _same(sql.execute("FROM health").df(), views.health(frame).reset_index(), [DATE])


@pytest.mark.parametrize("by", ["ticker", "sector", "side"])
def test_earned_groups_to_the_attribution(sql, frame, by) -> None:
    got = sql.execute(
        f"SELECT {by}, sum(pnl_usd) AS pnl_usd, sum(borrow_usd) AS borrow_usd, sum(net_usd) AS net_usd, count(DISTINCT date) AS days "
        "FROM earned GROUP BY ALL"
    ).df()
    _same(got, views.attribution(frame, SECTORS, by).reset_index(), [by])


def test_history_next_open_and_spells(sql, frame) -> None:
    _same(sql.execute("FROM history('BB')").df(), views.history(frame, "BB"), [DATE])
    _same(sql.execute("FROM next_open").df(), views.next_open(frame), [TICKER])
    _same(sql.execute("FROM spells").df(), views.spells(frame), [TICKER, "entry"])
    assert sql.execute("SELECT count(*) FROM spells WHERE exit IS NULL").fetchone() == (4,)


def test_next_open_is_in_the_python_views_order(sql, frame) -> None:
    """By expected move where the ledger has one, else by target, largest first."""
    assert list(sql.execute("SELECT ticker FROM next_open").df()[TICKER]) == list(views.next_open(frame)[TICKER])
