"""Phase 6 weekly drift report: does the forward run behave like its backtest?

    uv run python -m statarb.paper.drift
    uv run python -m statarb.paper.drift --now 2027-01-22T07:15-05:00

Writes `reports/phase-06/drift/<last ledger day>.md` and a chart beside it,
covering the run from its first session to the last ledger day. A rerun with
no new ledger day rewrites the same report.

- **Reference.** The frozen path over development, rebuilt on the reference
  tables as the reproduction check rebuilds it
  (`statarb.paper.reproduce.frozen_panels`).
- **Within range.** Each live measure is a statistic over the run's *N* days
  so far: a mean, or for P&L a sum. It is compared with the same statistic
  over every *N*-day window of the reference. Within range is between the 5th
  and 95th percentiles of those windows; the P&L band is the 1st to 99th. The
  live book starts flat, as no reference window does, so turnover and gross
  exposure leave out the run's first `holding_days` sessions.
- **Live measures.** Turnover, gross exposure and net return from the ledger,
  the record. Signal, expected move, slope and IC from the frozen strategy's
  panels rebuilt on the latest daily snapshot's tables, the same code the
  reference uses; the decision check below shows where those panels differ
  from what the ledger recorded.
- **Revisions.** Every daily snapshot's bars against the snapshot before it,
  over the dates both hold, both read with today's rules so that only the
  source's revisions show; and every ledger day's decision rebuilt from the
  latest snapshot against the decision the ledger recorded. A difference in
  the second is a decision the source's revisions would have changed.
- **Operations.** Runs by status from `data/paper/runs.jsonl`, the runs that
  failed, refused or stopped short, failed backups, sessions due and not yet
  in the ledger, held names without a return, and tickers the source failed to
  return.

The report reads the ledger, never writes it, and takes the daily job's lock so
it never reads tables the job is rebuilding. Like the job, it refuses first if
the config is not the frozen one (`statarb.paper.frozen`), or a config overlay
is set: it rebuilds the strategy from config, so another config would compare
the run with a different strategy.
"""

from __future__ import annotations

import argparse
import datetime as dt
import itertools
import json
import sys
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from statarb.backtest import experiments
from statarb.config import load_config, raw_store, repo_root, resolve_path
from statarb.data import cache
from statarb.data.alpaca import RuleError, Rules
from statarb.data.build import price_rules
from statarb.data.schema import DATE, PRICE_COLUMNS, TICKER
from statarb.data.snapshot import PriceSnapshot
from statarb.models.ic import daily_rank_ic
from statarb.models.run import rule_variant
from statarb.paper import daily, frozen, ledger, reproduce
from statarb.paper import sessions as sessions_
from statarb.paper.config import load_paper_config
from statarb.paper.day import Panels, backtest_path, strategy_panels

WINDOW = (5.0, 95.0)                      # percentiles of the reference windows: within range
BAND = (1.0, 99.0)                        # the wide band for P&L
BAR_FIELDS = (*PRICE_COLUMNS, "volume", "cash", "split_ratio")
SHOWN = 20                                # rows listed in the report's longer tables


# Daily measures ------------------------------------------------------------------------------------


def book_measures(frame: pd.DataFrame) -> pd.DataFrame:
    """Turnover, gross exposure and net return per day, per dollar of capital, from ledger rows.

    As the backtest measures them (`statarb.backtest.cost_run.per_capital`):
    gross exposure is what was held into the day, or what was traded into on a
    day that starts flat.
    """
    g = frame.groupby(DATE, sort=True)
    held = g["held"].apply(lambda x: float(np.abs(x).sum()))
    after = g["holding"].apply(lambda x: float(np.abs(x).sum()))
    first = g.first()
    costs = first["cost_spread"] + first["cost_impact"] + first["cost_commission"]
    return pd.DataFrame(
        {
            "turnover": g["trade"].apply(lambda x: float(np.abs(x).sum())),
            "exposure": held.where(held > 0, after),
            "net": g["pnl"].sum() - g["borrow"].sum() - costs,
        }
    )


def signal_measures(dates: pd.DatetimeIndex, signal: np.ndarray, move: np.ndarray, slopes: np.ndarray, residual: np.ndarray, members: np.ndarray) -> pd.DataFrame:
    """Per date: the cross-sectional spread of the signal and the expected move over members, the slope, and the IC.

    The IC on *d* is the rank correlation across members of the signal on *d*
    with the residual on *d*+1, so the last date has none.
    """
    sig = np.where(members & np.isfinite(signal), signal, np.nan)
    mv = np.where(members & np.isfinite(move), move, np.nan)
    with warnings.catch_warnings():                    # an all-NaN row has no spread: NaN is the answer
        warnings.simplefilter("ignore", RuntimeWarning)
        signal_sd = np.nanstd(sig, axis=1, ddof=1)
        move_sd = np.nanstd(mv, axis=1, ddof=1)
    T, N = signal.shape
    ic = pd.Series(np.nan, index=range(T))
    if T > 1:
        day = np.repeat(np.arange(T - 1), N)
        found = daily_rank_ic(day, sig[:-1].ravel(), residual[1:].ravel())
        ic.loc[found.index] = found.to_numpy()
    return pd.DataFrame({"signal_sd": signal_sd, "forecast_sd": move_sd, "slope": slopes, "ic": ic.to_numpy()}, index=dates)


def panel_measures(p: Panels) -> pd.DataFrame:
    """`signal_measures` on every date of a strategy's panels."""
    t = p.plab.lab.tables
    return signal_measures(t.dates, p.signal, p.move[:, : len(t.stocks)], p.slopes, t.residual.to_numpy(), t.members)


# Comparison with the reference ---------------------------------------------------------------------


@dataclass(frozen=True)
class Measure:
    key: str
    label: str
    source: str                   # "book" (ledger) or "signal" (panels)
    stat: str                     # "mean" or "sum" over the days
    band: tuple[float, float]
    ramp_up: bool                 # leave out the run's first holding_days sessions
    group: str                    # what the acceptance criterion it answers to calls it


MEASURES = (
    Measure("turnover", "turnover, fraction of capital a day", "book", "mean", WINDOW, True, "turnover"),
    Measure("exposure", "gross exposure, fraction of capital", "book", "mean", WINDOW, True, "book"),
    Measure("signal_sd", "signal, cross-sectional standard deviation", "signal", "mean", WINDOW, False, "signal"),
    Measure("forecast_sd", "expected move, cross-sectional standard deviation", "signal", "mean", WINDOW, False, "signal"),
    Measure("ic", "IC, signal on d against the residual on d+1", "signal", "mean", WINDOW, False, "IC"),
    Measure("slope", "calibration slope", "signal", "mean", WINDOW, False, "slope"),
    Measure("negative", "share of days with a negative slope", "signal", "mean", WINDOW, False, "slope"),
    Measure("net", "net return on capital, summed", "book", "sum", BAND, False, "P&L"),
)


@dataclass(frozen=True)
class Comparison:
    measure: Measure
    live: float
    days: int
    low: float
    high: float
    percentile: float             # share of reference windows below the live value, in per cent
    windows: int

    @property
    def verdict(self) -> str:
        if self.days == 0 or not np.isfinite(self.live) or self.windows == 0:
            return "no data"
        if self.live < self.low:
            return "below"
        if self.live > self.high:
            return "above"
        return "within"


def windows(reference: pd.Series, n: int, stat: str) -> np.ndarray:
    """The statistic over every n-day window of the reference's days that have a value."""
    values = reference.dropna()
    if n <= 0 or len(values) < n:
        return np.array([])
    rolled = values.rolling(n)
    return (rolled.sum() if stat == "sum" else rolled.mean()).dropna().to_numpy()


def compare(measure: Measure, live: pd.Series, reference: pd.Series) -> Comparison:
    values = live.dropna()
    n = len(values)
    live_stat = float(values.sum() if measure.stat == "sum" else values.mean()) if n else float("nan")
    w = windows(reference, n, measure.stat)
    if len(w) == 0:
        return Comparison(measure, live_stat, n, float("nan"), float("nan"), float("nan"), 0)
    low, high = np.percentile(w, measure.band)
    return Comparison(measure, live_stat, n, float(low), float(high), float((w < live_stat).mean() * 100), len(w))


def with_negative(frame: pd.DataFrame) -> pd.DataFrame:
    """Add the negative-slope indicator, NaN where the slope is."""
    return frame.assign(negative=(frame["slope"] < 0).astype("float64").where(frame["slope"].notna()))


def comparisons(live_book: pd.DataFrame, live_signal: pd.DataFrame, ref_book: pd.DataFrame, ref_signal: pd.DataFrame, ramp_up: int) -> list[Comparison]:
    live_signal, ref_signal = with_negative(live_signal), with_negative(ref_signal)
    out = []
    for m in MEASURES:
        live = (live_book if m.source == "book" else live_signal)[m.key]
        ref = (ref_book if m.source == "book" else ref_signal)[m.key]
        out.append(compare(m, live.iloc[ramp_up:] if m.ramp_up else live, ref))
    return out


def band_by_day(reference: pd.Series, days: int, band: tuple[float, float]) -> pd.DataFrame:
    """For k = 1 to `days`: the band's percentiles of the reference's k-day sums, for the P&L chart."""
    rows = []
    for k in range(1, days + 1):
        w = windows(reference, k, "sum")
        rows.append(np.percentile(w, band) if len(w) else [np.nan, np.nan])
    return pd.DataFrame(rows, columns=["low", "high"], index=range(1, days + 1))


# Revisions -----------------------------------------------------------------------------------------

CHANGE_COLUMNS = [TICKER, "rows", "fields", "first", "last", "max_price_change", "split"]


def bar_changes(old: Path, new: Path, rules: Rules | None = None) -> pd.DataFrame:
    """Each ticker whose bars in `new` differ from `old` on the dates both hold.

    Raw snapshots are both read with today's rules, so a difference is the
    source's revision, not a change of rule. A ticker that fails a rule in
    either is left out; `source_failures` lists it. `split` marks a ticker with
    a new split in `new` after `old` ends: a split-adjusted snapshot's new split
    changes every earlier price.
    """
    a_snap, b_snap = PriceSnapshot.open(old), PriceSnapshot.open(new)
    end = pd.Timestamp(a_snap.manifest.get("end_exclusive"))
    rows = []
    for ticker in sorted(set(a_snap.tickers()) & set(b_snap.tickers())):
        try:
            a, b = a_snap.bars(ticker, rules), b_snap.bars(ticker, rules)
        except RuleError:
            continue
        both = a.merge(b, on=DATE, suffixes=("_old", "_new"))
        changed = np.zeros(len(both), dtype=bool)
        fields = []
        for f in BAR_FIELDS:
            x, y = both[f"{f}_old"].to_numpy(), both[f"{f}_new"].to_numpy()
            diff = ~((x == y) | (np.isnan(x) & np.isnan(y)))
            if diff.any():
                fields.append(f)
                changed |= diff
        if not changed.any():
            continue
        x = both.loc[changed, [f"{f}_old" for f in PRICE_COLUMNS]].to_numpy()
        y = both.loc[changed, [f"{f}_new" for f in PRICE_COLUMNS]].to_numpy()
        with np.errstate(divide="ignore", invalid="ignore"):
            rel = np.abs(y - x) / np.abs(x)
        later = b.loc[b[DATE] >= end, "split_ratio"]
        rows.append(
            {
                TICKER: ticker,
                "rows": int(changed.sum()),
                "fields": ", ".join(fields),
                "first": both.loc[changed, DATE].min(),
                "last": both.loc[changed, DATE].max(),
                "max_price_change": float(np.nanmax(rel)) if np.isfinite(rel).any() else float("nan"),
                "split": bool(((later != 1) & later.notna()).any()),
            }
        )
    return pd.DataFrame(rows, columns=CHANGE_COLUMNS)


def snapshot_pairs(raw_root: Path, source: str, base: str) -> list[tuple[Path, Path]]:
    """Each complete price snapshot of `source` from `base` on, paired with the complete snapshot before it."""
    snaps = [p for p in cache.complete_snapshots(raw_root, source) if p.name >= base]
    return list(itertools.pairwise(snaps))


def decision_changes(frame: pd.DataFrame, panels: Panels) -> pd.DataFrame:
    """Per ledger day: names whose rebuilt decision (target or expected move) differs from the recorded one."""
    tickers = panels.plab.lab.tables.tickers
    pos = pd.Series(np.arange(len(panels.dates)), index=panels.dates)
    rows = []
    for date, day in frame.groupby(DATE, sort=True):
        s = int(pos[date])
        rebuilt = pd.DataFrame({TICKER: tickers, "target_now": panels.targets[s], "move_now": panels.move[s]})
        both = day[[TICKER, "target", "expected_move"]].merge(rebuilt, on=TICKER, how="left")
        out = {"date": date}
        for rec, now, name in (("target", "target_now", "target"), ("expected_move", "move_now", "move")):
            x, y = both[rec].to_numpy(), both[now].to_numpy()
            diff = ~((x == y) | (np.isnan(x) & np.isnan(y)))
            out[f"{name}_names"] = int(diff.sum())
            gap = np.abs(np.nan_to_num(x) - np.nan_to_num(y))
            out[f"{name}_max"] = float(gap[diff].max()) if diff.any() else 0.0
        rows.append(out)
    return pd.DataFrame(rows, columns=["date", "target_names", "target_max", "move_names", "move_max"])


# Operations ----------------------------------------------------------------------------------------


def run_summary(runs: list[dict[str, Any]]) -> dict[str, Any]:
    by_status: dict[str, int] = {}
    for r in runs:
        by_status[r["status"]] = by_status.get(r["status"], 0) + 1
    trouble = [r for r in runs if r["status"] not in ("done", "nothing due")]
    backups = [r for r in runs if (r.get("backup") or "").startswith("failed")]
    return {"runs": len(runs), "by_status": by_status, "trouble": trouble, "backup_failures": backups}


def source_failures(snapshots: list[str], raw_root: Path, source: str, rules: Rules | None = None) -> dict[str, list[str]]:
    """Tickers each snapshot used by the ledger gave no bars for: failed downloads, and failed rules under today's rules."""
    out = {}
    for name in snapshots:
        path = raw_root / source / name
        if cache.is_complete(path):
            snap = PriceSnapshot.open(path)
            _, failed_rules = snap.read_all(rules)
            failed = sorted(set(snap.manifest.get("failed", {})) | set(failed_rules))
            if failed:
                out[name] = failed
    return out


# The report ----------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Drift:
    last: pd.Timestamp
    first: pd.Timestamp
    entry: str                                  # config id of the reference path's log entry
    reference_span: tuple[pd.Timestamp, pd.Timestamp]
    comparisons: list[Comparison]
    live_book: pd.DataFrame
    live_signal: pd.DataFrame
    ref_book: pd.DataFrame
    ref_signal: pd.DataFrame
    pnl_band: pd.DataFrame
    slope_band: tuple[float, float]
    bars: list[tuple[str, str, pd.DataFrame]]   # (old, new, changes)
    decisions: pd.DataFrame
    runs: dict[str, Any]
    lagging: list[pd.Timestamp]
    missing_returns: pd.Series
    source_failed: dict[str, list[str]]
    config_hashes: list[str]
    dirty_days: list[pd.Timestamp]
    snapshot: str                               # the daily snapshot the live panels were rebuilt on
    ramp_up: int


def read_ledger(root: Path) -> pd.DataFrame:
    days = ledger.dates(root)
    return pd.concat([ledger.read_day(root, d) for d in days], ignore_index=True) if days else pd.DataFrame()


def latest_tables(paper: Path) -> tuple[str, dict[str, pd.DataFrame]]:
    """The daily job's tables for the snapshot in use: the latest complete one in `data/paper/processed/`."""
    processed = paper / daily.PROCESSED
    done = sorted(p for p in processed.iterdir() if (p / daily.COMPLETE).exists()) if processed.exists() else []
    if not done:
        raise FileNotFoundError(f"no complete tables in {processed}: run the daily job first")
    return done[-1].name, daily.read_tables(done[-1])


def reference_tables(root: Path) -> dict[str, pd.DataFrame]:
    """The reproduction check's reference tables, built if no daily run has left them."""
    path, digest = reproduce.reference(root)
    if not (path / daily.COMPLETE).exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        daily.build_tables(root, path.name, digest, path)
    return daily.read_tables(path)


def drift(root: Path, now: dt.datetime) -> Drift | None:
    """Everything the report shows, or None if the ledger has no day yet."""
    cfg = load_config("data", root)
    paper = resolve_path(cfg["paths"]["paper"], root)
    raw_root = raw_store(cfg["paths"]["raw"], root)
    frame = read_ledger(paper / daily.LEDGER)
    if frame.empty:
        return None
    source = cfg["source"]["name"]
    rules = price_rules(source, root)
    pc = load_paper_config(root)
    first = pc.run.first
    days = sorted(frame[DATE].unique())
    last = pd.Timestamp(days[-1])
    strategy = frozen.load_strategy(root)

    # Reference: the frozen path over development on the reference tables.
    entry = reproduce.frozen_entry(root)
    ref = reproduce.frozen_panels(reference_tables(root), strategy, entry)
    ref_signal = panel_measures(ref).iloc[ref.start :]
    ref_book = backtest_path(ref, strategy).daily[["turnover", "exposure", "net"]]

    # Live: the ledger, and the panels rebuilt on the latest daily snapshot.
    snapshot, tables = latest_tables(paper)
    panels = strategy_panels(tables, last, first, strategy)
    live_signal = panel_measures(panels).loc[days]
    live_book = book_measures(frame)
    ramp_up = rule_variant(panels.plab, strategy.forecast).holding_days

    sessions = sessions_.market_sessions(pc.run.calendar, first, pd.Timestamp(sessions_.run_day(now, pc.run.run_time)))
    lagging = list(sessions_.due(sessions, now, first, last, pc.run.run_time))
    per_day = frame.groupby(DATE).first()
    dates = ref.dates
    return Drift(
        last=last,
        first=first,
        entry=entry["config_id"],
        reference_span=(dates[ref.start], dates[-1]),
        comparisons=comparisons(live_book, live_signal, ref_book, ref_signal, ramp_up),
        live_book=live_book,
        live_signal=live_signal,
        ref_book=ref_book,
        ref_signal=ref_signal,
        pnl_band=band_by_day(ref_book["net"], len(days), BAND),
        slope_band=tuple(float(x) for x in np.nanpercentile(ref_signal["slope"], WINDOW)),
        bars=[(a.name, b.name, bar_changes(a, b, rules)) for a, b in snapshot_pairs(raw_root, source, cfg["source"]["snapshot"])],
        decisions=decision_changes(frame, panels),
        runs=run_summary(experiments.read(paper / daily.RUNS)),
        lagging=lagging,
        missing_returns=per_day["missing_returns"].loc[lambda s: s > 0],
        source_failed=source_failures(sorted(per_day["snapshot"].unique()), raw_root, source, rules),
        config_hashes=sorted(per_day["config_hash"].unique()),
        dirty_days=list(per_day.index[per_day["git_dirty"].astype(bool)]),
        snapshot=snapshot,
        ramp_up=ramp_up,
    )


def main(argv: list[str] | None = None) -> int:
    from statarb.paper.report import write_drift_report

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--now", help="report as of this time (ISO 8601 with an offset), for the sessions still due")
    args = parser.parse_args(argv)
    now = dt.datetime.fromisoformat(args.now) if args.now else dt.datetime.now(dt.UTC)
    root = repo_root()
    frozen.require(root)                  # before anything is read or written, as the daily job does
    cfg = load_config("data", root)
    paper = resolve_path(cfg["paths"]["paper"], root)
    with daily.locked(paper / daily.LOCK):
        result = drift(root, now)
    if result is None:
        print(json.dumps({"status": "nothing to report", "message": "the ledger has no day yet"}))
        return 0
    out = resolve_path(cfg["paths"]["reports"], root) / daily.DRIFT
    path = write_drift_report(result, out)
    outside = [c.measure.key for c in result.comparisons if c.verdict in ("below", "above")]
    print(json.dumps({"status": "written", "report": str(path.relative_to(root)), "outside": outside}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
