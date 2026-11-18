"""notebooks/ledger.py, the ledger explorer, runs every cell without error on the synthetic ledger."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys

import pytest

from statarb.config import repo_root
from synthetic_ledger import write


@pytest.fixture
def root(tmp_path):
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "data.toml").write_text('[paths]\npaper = "data/paper"\n')
    write(tmp_path / "data" / "paper")
    return tmp_path


@pytest.mark.slow
def test_the_app_runs_on_the_synthetic_ledger(root, tmp_path_factory) -> None:
    """Every cell of notebooks/ledger.py runs without error. The copy runs outside the repository, since marimo
    writes a session cache, with the cells' outputs, beside the notebook."""
    pytest.importorskip("marimo")
    work = tmp_path_factory.mktemp("app")
    notebook = shutil.copy(repo_root() / "notebooks" / "ledger.py", work / "ledger.py")
    shutil.copy(repo_root() / "notebooks" / "ledger.css", work / "ledger.css")
    run = subprocess.run(
        [sys.executable, "-m", "marimo", "export", "html", str(notebook), "-o", str(work / "out.html"), "--", "--root", str(root)],
        capture_output=True, text=True, timeout=120, check=False,
    )
    assert run.returncode == 0, run.stderr
    session = json.loads((work / "__marimo__" / "session" / "ledger.py.json").read_text())
    errors = [o for cell in session["cells"] for o in cell.get("outputs", []) if o.get("type") == "error"]
    assert not errors and len(session["cells"]) > 10
