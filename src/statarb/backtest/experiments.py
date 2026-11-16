"""Experiment log: one JSON object per backtest configuration and cost level, appended to a JSON Lines file.

Each entry has the configuration, the seed, the state it ran in (`run_state`:
the code, the config overlay and the price snapshot) and headline metrics. The
log is append-only, so it keeps every configuration ever tried, reruns included;
`config_id` identifies repeats of the same configuration.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
import subprocess
from pathlib import Path
from typing import Any

from statarb.config import load_config, overlay


def git_state(root: Path) -> dict[str, Any]:
    """The commit and whether the working tree has changes; None for both outside a git checkout."""

    def git(*args: str) -> str:
        return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, check=True).stdout.strip()

    try:
        return {"git_commit": git("rev-parse", "HEAD"), "git_dirty": bool(git("status", "--porcelain"))}
    except (OSError, subprocess.CalledProcessError):
        return {"git_commit": None, "git_dirty": None}


def run_state(root: Path) -> dict[str, Any]:
    """What an entry records beside its config: the code (`git_state`), the config overlay if one is set,
    and the price source and snapshot named in `[source]` of config/data.toml.

    Kept out of `config`, so `config_id` still identifies a configuration across sources and overlays.
    """
    source = load_config("data", root)["source"]
    return {**git_state(root), "config_overlay": overlay(), "price_source": source["name"], "price_snapshot": source.get("snapshot", "")}


def _clean(value: Any) -> Any:
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {k: _clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean(v) for v in value]
    return value


def config_id(config: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(_clean(config), sort_keys=True).encode()).hexdigest()[:16]


def entry(config: dict[str, Any], metrics: dict[str, Any], seed: int, state: dict[str, Any], now: dt.datetime) -> dict[str, Any]:
    return _clean(
        {
            "recorded_at": now.astimezone(dt.UTC).isoformat(timespec="seconds"),
            **state,
            "seed": seed,
            "config_id": config_id(config),
            "config": config,
            "metrics": metrics,
        }
    )


def append(path: Path, entries: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as fh:
        for e in entries:
            fh.write(json.dumps(e, sort_keys=True) + "\n")


def read(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
