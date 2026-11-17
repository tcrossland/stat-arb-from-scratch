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

# Commits whose message breaks a rule but cannot be reworded, by full hash: the
# problems each may have, matched as fragments of `problems`' text. A commit an
# experiment log names in its `git_commit` keeps its hash, since rewording it
# would change that hash and every later one the logs record.
EXCEPTIONS = {
    # Phase 5's first development run, 26 entries in reports/phase-05/experiments.jsonl.
    "447f85eee3df29c120843868f496a37b4d6f1579": ("subject is 73 characters",),
}


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


def reported(sha: str, message: str) -> list[str]:
    """`problems`, less those `EXCEPTIONS` allows for this commit."""
    allowed = EXCEPTIONS.get(sha, ())
    return [p for p in problems(message) if not any(a in p for a in allowed)]


def messages(revisions: str) -> list[tuple[str, str]]:
    """(full hash, message) for each commit in a revision range, oldest first."""
    out = subprocess.run(
        ["git", "log", "--reverse", "--format=%H%x00%B%x1e", revisions],
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
        for problem in reported(sha, message):
            print(f"{sha[:7]}: {problem}")
            failed += 1
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
