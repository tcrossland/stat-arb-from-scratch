"""Phase 6 reproduction check: the frozen path must still give its logged metrics.

    uv run python -m statarb.paper.reproduce

The frozen record cannot see a code change that alters behaviour, and the
code will change while the forward run goes on. So before it processes any
session the daily job rebuilds the frozen path over development and requires
the metrics of its "choice path" entry in `reports/phase-06/experiments.jsonl`
exactly: every metric equal after the JSON round trip the log went through.
The entry is the one whose configuration is the frozen strategy, logged from
the same price source.

The path is rebuilt the way the job builds each day (`statarb.paper.day`: a
model forecast from the saved model files, not retrained), from the entry's
first date to its last, on tables built from the snapshot pinned in
`[source]` of `config/data.toml` into `data/paper/reference/<snapshot>/`, so
revisions the source makes to old prices in the daily snapshots cannot fail
it. The tables are rebuilt for every check with the code as it is, so a
change to the data or residual build is checked too.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pandas as pd

from statarb.backtest import experiments
from statarb.config import load_config, repo_root, resolve_path
from statarb.models.run import Outcome, build_period_lab
from statarb.paper.choice import CHOICE
from statarb.paper.day import Panels, Strategy, backtest_path, panels_on

LOG = Path("phase-06") / "experiments.jsonl"          # under [paths] reports
REFERENCE = "reference"                                # under [paths] paper
DATES = ("kind", "first_date", "last_date")            # in a path's log entry, not in the frozen record
IGNORED = ("identical_to", "solver_seconds_mean")      # a fact about the run's other paths; wall-clock


def logged_entry(log: list[dict[str, Any]], strategy: Mapping[str, Any]) -> dict[str, Any]:
    """The choice-path entry of the frozen strategy (`statarb.paper.frozen.strategy_config`). Repeats of it must agree."""
    config = {k: v for k, v in strategy.items() if k != "price_source"}
    hits = [
        e for e in log
        if e["config"].get("kind") == CHOICE and e.get("price_source") == strategy["price_source"]
        and {k: v for k, v in e["config"].items() if k not in DATES} == config
    ]
    if not hits:
        raise ValueError(f"no {CHOICE} in {LOG} has the frozen strategy")
    if any((e["config_id"], e["metrics"]) != (hits[0]["config_id"], hits[0]["metrics"]) for e in hits[1:]):
        raise ValueError(f"the {CHOICE} entries of the frozen strategy in {LOG} disagree")
    return hits[0]


def frozen_entry(root: Path) -> dict[str, Any]:
    """The choice-path entry of the strategy in the frozen record: call `statarb.paper.frozen.require` first."""
    from statarb.paper.frozen import RECORD, reports_dir

    reports = reports_dir(root)
    stored = json.loads((reports / RECORD).read_text())
    return logged_entry(experiments.read(reports / LOG), stored["strategy"])


def comparable(metrics: Mapping[str, Any]) -> dict[str, Any]:
    """Metrics as the experiment log stores them, without the fields that are not about this path's result."""
    stored = json.loads(json.dumps(experiments._clean(dict(metrics))))
    return {k: v for k, v in stored.items() if k not in IGNORED}


def mismatches(logged: Mapping[str, Any], rebuilt: Mapping[str, Any]) -> list[str]:
    """Each metric that differs, with both values; nothing if every one is equal."""
    old, new = comparable(logged), comparable(rebuilt)
    return [f"{key}: {old.get(key)!r} logged, {new.get(key)!r} now" for key in sorted(set(old) | set(new)) if old.get(key) != new.get(key)]


def frozen_panels(long: Mapping[str, pd.DataFrame], strategy: Strategy, entry: Mapping[str, Any]) -> Panels:
    """The strategy's panels on `long` cut at the entry's last date, starting flat on its first."""
    config = entry["config"]
    first, last = pd.Timestamp(config["first_date"]), pd.Timestamp(config["last_date"])
    plab = build_period_lab(long, strategy.settings, last)
    dates = plab.lab.tables.dates
    start = int(dates.searchsorted(first))
    if start >= len(dates) or dates[start] != first or dates[-1] != last:
        raise ValueError(f"the reference tables do not run from {first.date()} to {last.date()}, the frozen path's dates")
    return panels_on(plab, start, strategy)


def frozen_path(long: Mapping[str, pd.DataFrame], strategy: Strategy, entry: Mapping[str, Any]) -> Outcome:
    return backtest_path(frozen_panels(long, strategy, entry), strategy)


def check(long: Mapping[str, pd.DataFrame], strategy: Strategy, entry: Mapping[str, Any]) -> list[str]:
    """How the frozen path rebuilt on `long` differs from its log entry: nothing if it reproduces."""
    return mismatches(entry["metrics"], frozen_path(long, strategy, entry).metrics)


def reference(root: Path) -> tuple[Path, str]:
    """Where the reference tables are built, named by the pinned snapshot, and the snapshot's pinned digest."""
    source = load_config("data", root)["source"]
    if not source["snapshot"] or not source.get("digest"):
        raise ValueError("pin [source] snapshot and digest in config/data.toml: the reference tables are built from one fixed snapshot")
    return resolve_path(load_config("data", root)["paths"]["paper"], root) / REFERENCE / source["snapshot"], source["digest"]


def main(argv: list[str] | None = None) -> int:
    """The daily job's check, on reference tables rebuilt as it rebuilds them."""
    from statarb.paper.daily import reproduction  # the job owns the table build

    root = repo_root()
    result = reproduction(root)
    print("\n".join(result.problems) if result.problems else f"the frozen path reproduces log entry {result.entry}")
    return 1 if result.problems else 0


if __name__ == "__main__":
    sys.exit(main())
