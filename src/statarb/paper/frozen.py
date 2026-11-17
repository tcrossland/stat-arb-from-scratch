"""Phase 6 frozen record: everything that produces a decision in the forward run, pinned by a hash.

    uv run python -m statarb.paper.frozen            # check the config against the frozen record
    uv run python -m statarb.paper.frozen --write    # write the record once, when the forward run's decision sets [frozen]

The record has three parts:

- **strategy:** the configuration of the frozen path's phase 6 "choice path"
  log entry (`statarb.paper.choice`), built from config and `[frozen]` of
  `config/paper.toml` by the code that logged it, less its kind and dates,
  plus the price source;
- **files:** the parsed contents of every config file that shapes the data,
  residuals, signal, forecast, costs or portfolio, whole, except `data.toml`'s
  `[download]` and `[paths]` (how and where data is fetched, not what), its
  pinned `[source]` snapshot and digest (each day names its own), and
  `models.toml`'s `[runs]` and `[partial_adjustment]`, which train nothing;
- **models:** for a model forecast, every block's model file and SHA-256, from
  phase 5's last development walk-forward and its holdout read. The job loads
  each file only if it has this hash (`statarb.models.forecast.load_checked`).

The record is written once to `reports/phase-06/frozen-config.json` and its
hash, computed as `experiments.config_id` is, goes into `[frozen] config_hash`.
Before anything else the daily job and the drift report rebuild the record and
refuse to run if it differs, naming the keys that changed. Parsed contents, not
bytes, so a comment edit is not a change. With `[frozen]` unset, as until the
forward run's decision record, the job refuses before it downloads anything.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

import pandas as pd

from statarb.backtest import experiments
from statarb.backtest.cost_run import variants
from statarb.config import OVERLAY_ENV, load_config, overlay, repo_root, resolve_path
from statarb.models.backend import make_backend
from statarb.models.forecast import SavedBlock, load_checked
from statarb.models.holdout import HOLDOUT_PATH, HOLDOUT_WALK, PATH, WALK, latest_run
from statarb.models.run import Outcome, Settings, load_settings, path_record
from statarb.paper.config import Frozen, load_paper_config, model_horizon, parse_rule
from statarb.paper.day import Strategy, strategy_of

FILES = ("data", "universe", "factors", "sector_changes", "listing_starts", "alpaca", "backtest", "costs", "portfolio", "models")
EXCLUDED = {
    "data": (("download",), ("paths",), ("source", "snapshot"), ("source", "digest")),
    "models": (("runs",), ("partial_adjustment",)),
}
RECORD = Path("phase-06") / "frozen-config.json"    # under [paths] reports of config/data.toml
PHASE_5_LOG = Path("phase-05") / "experiments.jsonl"
DATES = ("kind", "first_date", "last_date")          # in a path's log entry, not in the record
NO_DATE = pd.Timestamp("1970-01-01")


class FrozenConfigError(RuntimeError):
    pass


def reports_dir(root: Path) -> Path:
    return resolve_path(load_config("data", root)["paths"]["reports"], root)


def plain(value: Any) -> Any:
    """Dates and tuples to JSON values, so the record hashes the same way it is written."""
    return json.loads(json.dumps(value, default=str))


def without(table: dict[str, Any], paths: tuple[tuple[str, ...], ...]) -> dict[str, Any]:
    """A copy of `table` with each key path removed; a path that is not there is ignored."""
    drop = {p[0] for p in paths if len(p) == 1}
    out = {}
    for key, value in table.items():
        if key in drop:
            continue
        deeper = tuple(p[1:] for p in paths if len(p) > 1 and p[0] == key)
        out[key] = without(value, deeper) if deeper and isinstance(value, dict) else value
    return out


def file_contents(root: Path) -> dict[str, Any]:
    return {name: plain(without(load_config(name, root), EXCLUDED.get(name, ()))) for name in FILES}


def walk_forward_ids(p5_log: list[dict]) -> dict[int, str]:
    """Each horizon's walk-forward config_id, from phase 5's last development run: a model path's `model.walk_forward`."""
    return {e["config"]["horizon"]: e["config_id"] for e in latest_run(p5_log, (WALK, PATH)) if e["config"]["kind"] == WALK}


def strategy_config(s: Settings, frozen: Frozen, p5_log: list[dict], price_source: str) -> dict[str, Any]:
    """The frozen path's choice-path configuration less its kind and dates, with the price source."""
    rule, kappa = parse_rule(frozen.rule)
    known = dict(variants(s.cfg, s.ccfg))
    o = Outcome(frozen.forecast, rule, kappa, float(frozen.book_size), pd.DataFrame(), {})
    rec = path_record(o, s.cfg, s.ccfg, s.pc, s.mc, known.get(frozen.forecast, known[s.pc.run.variant]), walk_forward_ids(p5_log), NO_DATE, NO_DATE)
    rec = {k: v for k, v in rec.items() if k not in DATES}
    return plain({**rec, "slope_rule": frozen.slope_rule, "price_source": price_source})


def model_files(p5_log: list[dict], horizon: int | None) -> list[dict[str, str]]:
    """A model forecast's block files by first test date, from phase 5's last development walk-forward and its holdout read."""
    if horizon is None:
        return []
    out: dict[str, dict[str, str]] = {}
    for kinds, kind in (((WALK, PATH), WALK), ((HOLDOUT_WALK, HOLDOUT_PATH), HOLDOUT_WALK)):
        for e in latest_run(p5_log, kinds):
            if e["config"]["kind"] == kind and e["config"]["horizon"] == horizon:
                out.update({b["test_first"]: {"test_first": b["test_first"], "file": b["model_file"], "sha256": b["model_sha256"]} for b in e["metrics"]["blocks"]})
    if not out:
        raise FrozenConfigError(f"phase 5's log has no walk-forward for H = {horizon}")
    return [out[k] for k in sorted(out)]


def build_record(s: Settings, frozen: Frozen, files: dict[str, Any], p5_log: list[dict]) -> dict[str, Any]:
    return {
        "strategy": strategy_config(s, frozen, p5_log, files["data"]["source"]["name"]),
        "files": files,
        "models": model_files(p5_log, model_horizon(frozen.forecast)),
    }


def record(root: Path, frozen: Frozen) -> dict[str, Any]:
    return build_record(load_settings(root), frozen, file_contents(root), experiments.read(reports_dir(root) / PHASE_5_LOG))


def differences(old: Any, new: Any, prefix: str = "") -> list[str]:
    """Dotted key paths at which two JSON values differ; lists are compared whole."""
    if isinstance(old, dict) and isinstance(new, dict):
        out = []
        for key in sorted(set(old) | set(new)):
            path = f"{prefix}.{key}" if prefix else key
            if key not in old:
                out.append(f"{path} (added)")
            elif key not in new:
                out.append(f"{path} (removed)")
            else:
                out += differences(old[key], new[key], path)
        return out
    return [] if old == new else [prefix or "(whole record)"]


def compare(stored: dict[str, Any] | None, config_hash: str, rebuilt: dict[str, Any]) -> list[str]:
    """Why the rebuilt record does not match the stored one and its hash, or nothing if it does."""
    if not config_hash:
        return ["[frozen] config_hash is not set in config/paper.toml"]
    if stored is None:
        return [f"no frozen record at {RECORD}"]
    problems = []
    if experiments.config_id(stored) != config_hash:
        problems.append(f"{RECORD} hashes to {experiments.config_id(stored)}, not the config_hash {config_hash} in config/paper.toml")
    return problems + [f"changed since the freeze: {key}" for key in differences(stored, rebuilt)]


def check(root: Path) -> list[str]:
    """Why the config does not match the frozen record, or nothing if it does."""
    if (named := overlay()) is not None:
        return [f"config overlay {named} is set ({OVERLAY_ENV}); the frozen record is checked against the base config only"]
    frozen = load_paper_config(root).frozen
    if not frozen.is_set:
        return ["[frozen] in config/paper.toml is not set: the forward run waits for the decision record that freezes its strategy"]
    path = reports_dir(root) / RECORD
    stored = json.loads(path.read_text()) if path.exists() else None
    return compare(stored, frozen.config_hash, record(root, frozen))


def require(root: Path) -> str:
    """The frozen hash, or FrozenConfigError naming every difference."""
    problems = check(root)
    if problems:
        raise FrozenConfigError("the config differs from the frozen record:\n  " + "\n  ".join(problems))
    return load_paper_config(root).frozen.config_hash


def write(root: Path) -> str:
    """Write the record for the config as it is and return its hash; refuses to replace a different frozen record."""
    if (named := overlay()) is not None:
        raise FrozenConfigError(f"config overlay {named} is set ({OVERLAY_ENV}); the frozen record is written from the base config only")
    frozen = load_paper_config(root).frozen
    if not frozen.is_set:
        raise FrozenConfigError("[frozen] in config/paper.toml is not set: the decision record that freezes the strategy sets it first")
    built = record(root, frozen)
    digest = experiments.config_id(built)
    if frozen.config_hash and frozen.config_hash != digest:
        raise FrozenConfigError(f"config_hash is already {frozen.config_hash}; changing the frozen config is a new decision record")
    path = reports_dir(root) / RECORD
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(built, sort_keys=True, indent=2) + "\n")
    os.replace(tmp, path)
    return digest


def strategy_from(s: Settings, frozen: Frozen, models: list[dict[str, str]], model_dir: Path) -> Strategy:
    """The frozen strategy, with each model file loaded only if it has the record's SHA-256."""
    backend = make_backend(s.mc.model.library, s.mc.lightgbm)
    blocks = [SavedBlock(pd.Timestamp(m["test_first"]), m["file"], m["sha256"]) for m in models]
    loaded = [(b.test_first, load_checked(backend, model_dir, b)) for b in blocks]
    return strategy_of(s, frozen.forecast, frozen.rule, frozen.slope_rule, frozen.book_size, loaded)


def load_strategy(root: Path) -> Strategy:
    """The frozen strategy as the record pins it: call `require` first."""
    stored = json.loads((reports_dir(root) / RECORD).read_text())
    model_dir = resolve_path(load_config("data", root)["paths"]["models"], root)
    return strategy_from(load_settings(root), load_paper_config(root).frozen, stored["models"], model_dir)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--write", action="store_true", help="write the frozen record and print its hash for config/paper.toml")
    args = parser.parse_args(argv)
    root = repo_root()
    if args.write:
        print(write(root))
        return 0
    problems = check(root)
    print("\n".join(problems) if problems else f"matches the frozen record {load_paper_config(root).frozen.config_hash}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
