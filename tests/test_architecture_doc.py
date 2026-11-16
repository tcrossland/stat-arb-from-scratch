"""docs/architecture.md names every module, runner and config file there is, and nothing that is not."""

from __future__ import annotations

import re

from statarb.config import repo_root

ROOT = repo_root()
DOC = (ROOT / "docs" / "architecture.md").read_text()


def _section(title: str) -> str:
    return DOC.split(f"## {title}\n", 1)[1].split("\n## ", 1)[0]


def _first_cells(title: str) -> set[str]:
    return set(re.findall(r"^\| `([^`]+)` \|", _section(title), flags=re.MULTILINE))


def _modules() -> dict[str, str]:
    """Module name -> source text, for every module but the top-level package."""
    src = ROOT / "src"
    out = {}
    for path in (src / "statarb").rglob("*.py"):
        parts = path.relative_to(src).with_suffix("").parts
        if parts == ("statarb", "__init__"):
            continue
        out[".".join(parts[:-1] if parts[-1] == "__init__" else parts)] = path.read_text()
    return out


def test_module_table_matches_the_package() -> None:
    assert _first_cells("Modules") == set(_modules())


def test_runner_table_lists_the_modules_with_a_main() -> None:
    runners = {name for name, text in _modules().items() if "def main(" in text}
    assert _first_cells("Runners") == runners


def test_config_table_lists_every_config_file() -> None:
    assert _first_cells("Config files") == {p.name for p in (ROOT / "config").glob("*.toml")}


def test_no_em_dashes() -> None:
    assert "—" not in DOC
