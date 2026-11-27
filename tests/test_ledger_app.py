"""notebooks/ledger.py, the ledger explorer, runs every cell without error on each synthetic ledger."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys

import pytest

from statarb.config import repo_root
from statarb.paper import momentum, views
from synthetic_ledger import write

PATHS = tuple(spec.name for spec in momentum.load_momentum_config(repo_root()).runs)


@pytest.fixture
def root(tmp_path):
    """The reversal ledger and, as the momentum job lays them out, a ledger for each momentum path."""
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "data.toml").write_text('[paths]\npaper = "data/paper"\n')
    shutil.copy(repo_root() / "config" / "momentum_forward.toml", tmp_path / "config" / "momentum_forward.toml")
    write(tmp_path / "data" / "paper")
    for seed, name in enumerate(PATHS, start=1):
        write(momentum.paper_dir(tmp_path, momentum.load_momentum_config(tmp_path)), seed, path=name)
    return tmp_path


@pytest.mark.slow
@pytest.mark.parametrize("ledger", [views.REVERSAL, *PATHS])
def test_the_app_runs_on_each_synthetic_ledger(root, ledger, tmp_path_factory) -> None:
    """Every cell of notebooks/ledger.py runs without error, opened on the ledger by `--ledger`. The copy runs
    outside the repository, since marimo writes a session cache, with the cells' outputs, beside the notebook."""
    pytest.importorskip("marimo")
    work = tmp_path_factory.mktemp("app")
    notebook = shutil.copy(repo_root() / "notebooks" / "ledger.py", work / "ledger.py")
    shutil.copy(repo_root() / "notebooks" / "ledger.css", work / "ledger.css")
    run = subprocess.run(
        [sys.executable, "-m", "marimo", "export", "html", str(notebook), "-o", str(work / "out.html"), "--", "--root", str(root), "--ledger", ledger],
        capture_output=True, text=True, timeout=120, check=False,
    )
    assert run.returncode == 0, run.stderr
    session = json.loads((work / "__marimo__" / "session" / "ledger.py.json").read_text())
    errors = [o for cell in session["cells"] for o in cell.get("outputs", []) if o.get("type") == "error"]
    assert not errors and len(session["cells"]) > 10
