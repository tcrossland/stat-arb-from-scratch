"""Load TOML configuration from the repository's config/ directory."""

from __future__ import annotations

import tomllib
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
