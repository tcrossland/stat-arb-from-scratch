"""Check commit messages against the rules in CLAUDE.md, "Commits".

Usage: python scripts/check_commits.py <revision range>, for example
`main..HEAD`. CI runs it on every pull request over the commits the pull
request adds. Standard library only, so it needs no dependency.
"""

from __future__ import annotations

import re
import subprocess
import sys

TYPES = ("feat", "fix", "docs", "test", "refactor", "perf", "build", "ci", "chore")
SUBJECT = re.compile(rf"^(?:{'|'.join(TYPES)})(?:\([a-z0-9][a-z0-9-]*\))?!?: \S")
MAX_SUBJECT = 72


def problems(message: str) -> list[str]:
    """What is wrong with one commit message, or an empty list."""
    lines = message.rstrip("\n").split("\n")
    subject = lines[0]
    found = []
    if subject.startswith("Merge "):
        return found
    if not SUBJECT.match(subject):
        found.append(f"subject is not `type(scope): summary` with a type from {', '.join(TYPES)}: {subject!r}")
    if len(subject) > MAX_SUBJECT:
        found.append(f"subject is {len(subject)} characters, more than {MAX_SUBJECT}")
    if subject.endswith("."):
        found.append("subject ends with a full stop")
    if len(lines) > 1 and lines[1].strip():
        found.append("no blank line between the subject and the body")
    for line in lines[1:]:
        if line.startswith("Results:") and not line.removeprefix("Results:").strip():
            found.append("`Results:` footer says nothing about what moved")
    return found


def messages(revisions: str) -> list[tuple[str, str]]:
    """(short hash, message) for each commit in a revision range, oldest first."""
    out = subprocess.run(
        ["git", "log", "--reverse", "--format=%h%x00%B%x1e", revisions],
        check=True, capture_output=True, text=True,
    ).stdout
    entries = [e.strip("\n") for e in out.split("\x1e") if e.strip()]
    return [tuple(e.split("\x00", 1)) for e in entries]


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    failed = 0
    for sha, message in messages(argv[1]):
        for problem in problems(message):
            print(f"{sha}: {problem}")
            failed += 1
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
