"""Load TOML configuration from the repository's config/ directory.

A config overlay lets an experiment change settings without editing a config
file, so the committed config always describes the committed results. When the
environment variable named by `OVERLAY_ENV` holds a directory, each
`<name>.toml` in it is merged over `config/<name>.toml`: tables merge key by
key and any other value replaces the base one. An overlay may only set keys the
base file has, so a misspelt key fails instead of being ignored. The experiment
log records the overlay with every entry (`statarb.backtest.experiments`).
"""

from __future__ import annotations

import os
import tomllib
from collections.abc import Mapping
from pathlib import Path
from typing import Any

OVERLAY_ENV = "STATARB_CONFIG_OVERLAY"


def repo_root(start: Path | None = None) -> Path:
    """Return the nearest ancestor directory containing pyproject.toml."""
    here = (start or Path(__file__)).resolve()
    for candidate in (here, *here.parents):
        if (candidate / "pyproject.toml").is_file():
            return candidate
    raise FileNotFoundError("pyproject.toml not found above " + str(here))


def _read(path: Path) -> dict[str, Any]:
    with path.open("rb") as fh:
        return tomllib.load(fh)


def overlay(environ: Mapping[str, str] = os.environ) -> str | None:
    """The overlay directory named in the environment, as given, or None."""
    return environ.get(OVERLAY_ENV) or None


def merged(base: dict[str, Any], over: dict[str, Any], where: str) -> dict[str, Any]:
    """`base` with `over` merged in: tables key by key, other values replaced. Every key must be in `base`."""
    out = dict(base)
    for key, value in over.items():
        path = f"{where}.{key}"
        if key not in base:
            raise KeyError(f"config overlay sets {path}, which the base config does not have")
        if isinstance(value, dict) != isinstance(base[key], dict):
            kind = "table" if isinstance(value, dict) else "value"
            raise TypeError(f"config overlay sets {path} as a {kind}, unlike the base config")
        out[key] = merged(base[key], value, path) if isinstance(value, dict) else value
    return out


def load_config(name: str, root: Path | None = None) -> dict[str, Any]:
    """Load config/<name>.toml, with the overlay's <name>.toml merged over it when one is set."""
    root = root or repo_root()
    base = _read(root / "config" / f"{name}.toml")
    named = overlay()
    if named is None:
        return base
    directory = resolve_path(named, root)
    if not directory.is_dir():
        raise FileNotFoundError(f"config overlay {named} ({OVERLAY_ENV}) is not a directory under {root}")
    path = directory / f"{name}.toml"
    return merged(base, _read(path), name) if path.is_file() else base


def resolve_path(relative: str, root: Path | None = None) -> Path:
    """Resolve a path from config relative to the repository root."""
    return (root or repo_root()) / relative


RAW_ENV = "STATARB_RAW"


def raw_store(configured: str, root: Path | None = None, environ: Mapping[str, str] = os.environ) -> Path:
    """Where raw snapshots live: the absolute path in STATARB_RAW when set, else `configured` under the repository.

    Worktrees set STATARB_RAW to the main checkout's data/raw, so every worktree
    reads one store of raw snapshots and none keeps a copy.
    """
    override = environ.get(RAW_ENV, "")
    if override:
        path = Path(override)
        if not path.is_absolute():
            raise ValueError(f"{RAW_ENV} must be an absolute path: {override}")
        return path
    return resolve_path(configured, root)
