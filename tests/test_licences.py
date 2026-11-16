"""Every installed distribution must carry a licence the CLAUDE.md rule allows.

The rule: permissive licences, and file-level copyleft (MPL-2.0) used
unmodified. Copyleft, non-commercial or unstated terms need a decision record
and an entry in EXCEPTIONS naming it. Reads installed metadata only, so it
covers dependencies of dependencies and never touches the network.
"""

from __future__ import annotations

import re
from importlib.metadata import Distribution, distributions

import pytest

# SPDX identifiers, lower-case.
ALLOWED_SPDX = frozenset(
    {
        "0bsd", "apache-2.0", "bsd-2-clause", "bsd-3-clause", "cc0-1.0", "isc", "mit", "mit-0", "mit-cmu",
        "mpl-2.0", "psf-2.0", "python-2.0", "unlicense", "zlib",
    }
)
# Trove classifiers ("License :: ... :: <name>") and free-text License fields, matched case-insensitively.
ALLOWED_TEXT = re.compile(
    r"^(mit( license)?|mit-cmu|bsd( license)?|(new |simplified )?bsd|[23]-clause bsd( license)?|bsd-[23]-clause"
    r"|apache( software license| license,? version 2\.0| 2\.0|-2\.0)|isc( license)?( \(iscl\))?"
    r"|python software foundation license|psf(-2\.0)?|mozilla public license 2\.0 \(mpl 2\.0\)"
    r"|the unlicense \(unlicense\)|zlib/libpng license)$",
    re.IGNORECASE,
)
DENIED = re.compile(r"\b(a?gpl|lgpl|gnu|copyleft|non-?commercial|cc[- ]by-nc)", re.IGNORECASE)

# Distributions whose metadata states no licence, with what their bundled licence file says.
# A copyleft or non-commercial entry here also needs a decision record, named in the comment.
EXCEPTIONS: dict[str, str] = {}


def spdx_allowed(expression: str) -> bool:
    """An SPDX expression is allowed if every AND term is, where an OR term needs one allowed side."""
    expr = expression.replace("(", " ").replace(")", " ")
    for conjunct in re.split(r"\s+AND\s+", expr, flags=re.IGNORECASE):
        options = [o.strip().lower() for o in re.split(r"\s+OR\s+", conjunct, flags=re.IGNORECASE)]
        if not any(o in ALLOWED_SPDX for o in options):
            return False
    return True


def text_allowed(text: str) -> bool:
    return not DENIED.search(text) and bool(ALLOWED_TEXT.match(text.strip()))


def licence_of(dist: Distribution) -> tuple[str, bool] | None:
    """The licence a distribution declares and whether it is allowed, or None if it declares none.

    Order: the SPDX License-Expression, then licence classifiers, then a short
    License field (long ones are the licence text itself and are not parsed).
    """
    meta = dist.metadata
    name = meta["Name"].lower()
    if name in EXCEPTIONS:
        return EXCEPTIONS[name], spdx_allowed(EXCEPTIONS[name])
    if expression := meta.get("License-Expression"):
        return expression, spdx_allowed(expression)
    classifiers = [c.split("::")[-1].strip() for c in meta.get_all("Classifier") or [] if c.startswith("License ::")]
    classifiers = [c for c in classifiers if c != "OSI Approved"]
    if classifiers:
        return "; ".join(classifiers), all(text_allowed(c) for c in classifiers)
    field = (meta.get("License") or "").strip()
    if field and len(field) <= 80:
        return field, text_allowed(field)
    return None


@pytest.mark.parametrize(
    ("expression", "allowed"),
    [
        ("MIT", True),
        ("BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0", True),
        ("Apache-2.0 OR BSD-2-Clause", True),
        ("GPL-3.0-or-later OR MIT", True),          # dual-licensed: we take the MIT side
        ("MIT AND GPL-3.0-only", False),
        ("LGPL-2.1-or-later", False),
        ("(Apache-2.0 OR MIT) AND LicenseRef-Proprietary", False),
    ],
)
def test_spdx_expressions(expression: str, allowed: bool) -> None:
    assert spdx_allowed(expression) is allowed


@pytest.mark.parametrize(
    ("text", "allowed"),
    [
        ("MIT License", True),
        ("BSD License", True),
        ("3-Clause BSD License", True),
        ("Apache Software License", True),
        ("Mozilla Public License 2.0 (MPL 2.0)", True),
        ("GNU General Public License v3 (GPLv3)", False),
        ("GNU Lesser General Public License v2 or later (LGPLv2+)", False),
        ("CC BY-NC 4.0", False),
        ("Other/Proprietary License", False),
    ],
)
def test_classifier_and_field_text(text: str, allowed: bool) -> None:
    assert text_allowed(text) is allowed


def test_every_installed_distribution_has_an_allowed_licence() -> None:
    unstated, refused = [], []
    for dist in distributions():
        name = dist.metadata["Name"]
        found = licence_of(dist)
        if found is None:
            unstated.append(name)
        elif not found[1]:
            refused.append(f"{name}: {found[0]}")
    assert not unstated, f"no licence in metadata (read the LICENSE file and add to EXCEPTIONS): {sorted(unstated)}"
    assert not refused, f"licence not allowed by the CLAUDE.md rule (needs a decision record): {sorted(refused)}"


def _dist(tmp_path, metadata: str) -> Distribution:
    from importlib.metadata import PathDistribution

    info = tmp_path / "example-1.0.dist-info"
    info.mkdir()
    (info / "METADATA").write_text("Metadata-Version: 2.4\nName: example\nVersion: 1.0\n" + metadata)
    return PathDistribution(info)


@pytest.mark.parametrize(
    ("metadata", "expected"),
    [
        ("License-Expression: GPL-3.0-only\nClassifier: License :: OSI Approved :: MIT License\n", ("GPL-3.0-only", False)),
        ("Classifier: License :: OSI Approved :: GNU General Public License v3 (GPLv3)\n", ("GNU General Public License v3 (GPLv3)", False)),
        ("Classifier: License :: OSI Approved :: BSD License\n", ("BSD License", True)),
        ("License: Apache 2.0\n", ("Apache 2.0", True)),
        ("", None),
    ],
)
def test_licence_of_reads_expression_then_classifiers_then_field(tmp_path, metadata: str, expected) -> None:
    assert licence_of(_dist(tmp_path, metadata)) == expected
