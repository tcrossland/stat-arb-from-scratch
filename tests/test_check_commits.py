from __future__ import annotations

import pytest

from check_commits import problems


@pytest.mark.parametrize(
    "message",
    [
        "docs: add the project brief, roadmap and phase plans\n\nWhy it was done.\n",
        "feat(data): build the universe\n\nBody.\n\nCo-Authored-By: Someone <someone@example.com>\n",
        "fix(backtest): fill at the open\n\nBody.\n\nResults: phase 2 net Sharpe of the headline moves by 0.01.\n",
        "docs(phase-02): write the review",
        "refactor!: rename the runners",
        "Merge pull request #1 from somewhere",
    ],
)
def test_conventional_messages_pass(message: str) -> None:
    assert problems(message) == []


@pytest.mark.parametrize(
    ("message", "fragment"),
    [
        ("Add the backlog", "subject is not"),
        ("feature: add the backlog", "subject is not"),
        ("docs(Phase 2): write the review", "subject is not"),
        ("docs:add the backlog", "subject is not"),
        ("docs: " + "x" * 70, "more than 72"),
        ("docs: add the backlog.", "full stop"),
        ("docs: add the backlog\nno blank line", "no blank line"),
        ("fix(data): correct a dividend\n\nBody.\n\nResults:\n", "says nothing"),
    ],
)
def test_bad_messages_are_caught(message: str, fragment: str) -> None:
    assert any(fragment in p for p in problems(message))
