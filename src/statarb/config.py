"""Load TOML configuration from the repository's config/ directory."""

from __future__ import annotations

import os
import tomllib
from collections.abc import Mapping
from pathlib import Path
from typing import Any


def repo_root(start: Path | None = None) -> Path:
    """Return the nearest ancestor directory containing pyproject.toml."""
    here = (start or Path(__file__)).resolve()
    for candidate in (here, *here.parents):
        if (candidate / "pyproject.toml").is_file():
            return candidate
    raise FileNotFoundError("pyproject.toml not found above " + str(here))


def load_config(name: str, root: Path | None = None) -> dict[str, Any]:
    """Load config/<name>.toml."""
    path = (root or repo_root()) / "config" / f"{name}.toml"
    with path.open("rb") as fh:
        return tomllib.load(fh)


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
