from __future__ import annotations

import datetime as dt
import socket
from pathlib import Path

import pytest

from statarb.config import load_config, repo_root, resolve_path


def test_repo_root_contains_pyproject() -> None:
    assert (repo_root() / "pyproject.toml").is_file()


def test_data_config_loads_with_expected_types() -> None:
    cfg = load_config("data")
    assert cfg["dates"]["start"] == dt.date(2016, 1, 1)
    assert isinstance(cfg["source"]["name"], str)
    assert cfg["universe"]["size"] == 300
    assert cfg["factors"]["market"] == "SPY"
    assert len(cfg["factors"]["sectors"]) == 11


def test_config_paths_resolve_inside_repo() -> None:
    cfg = load_config("data")
    for rel in cfg["paths"].values():
        path = resolve_path(rel)
        assert path.is_relative_to(repo_root())


def test_universe_and_sector_change_configs_parse() -> None:
    load_config("universe")
    load_config("sector_changes")


def test_load_config_from_explicit_root(tmp_path: Path) -> None:
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "x.toml").write_text("a = 1\n")
    assert load_config("x", root=tmp_path) == {"a": 1}


def test_network_is_blocked() -> None:
    with pytest.raises(RuntimeError, match="network"):
        socket.create_connection(("example.com", 80), timeout=1)
