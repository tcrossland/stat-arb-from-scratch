"""Phase 6 ledger backup: a clone of a private git repository that each run copies the ledger into and pushes.

`data/` is git-ignored and the ledger is the only record of the forward run,
so after each run the job copies every ledger day into `ledger/` of a clone of
the repository in `STATARB_BACKUP_REMOTE` under `data/paper/backup/`, commits
what changed and pushes to its `main` branch. The remote is a setting of the
host that runs the job, like the raw store, so it is read from the
environment and never written to the repository, the run log or a note.

- **Never stops the run.** A git or network failure is returned as a result,
  recorded in the run log and shown in the next daily note; the local ledger
  stays the record, and the next run retries.
- **Idempotent.** Files are copied only when their bytes differ, a commit is
  made only when something changed, and a push only when the clone is ahead of
  what it last pushed, so a run with nothing new does not touch the network.
- **Add only.** A day is never deleted from the backup. A damaged ledger is
  refused before the backup is reached.
- **Unattended.** Commits carry the job's own identity with signing off, and
  git is told never to prompt, so a scheduled run fails rather than waits.

The repository and the key that can push to it are the owner's to create; the
job never creates either.
"""

from __future__ import annotations

import filecmp
import os
import shutil
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from statarb.paper import ledger

BRANCH = "main"
FOLDER = "ledger"                      # inside the clone
IDENTITY = (
    "-c", "user.name=statarb daily job",
    "-c", "user.email=daily-job@statarb.invalid",
    "-c", "commit.gpgsign=false",
)
TIMEOUT = 120                          # seconds for any one git command
REMOTE_ENV = "STATARB_BACKUP_REMOTE"


@dataclass(frozen=True)
class BackupResult:
    status: str                        # "pushed", "up to date", "not configured" or "failed"
    message: str

    def text(self) -> str:
        return f"{self.status}: {self.message}"


def remote(environ: Mapping[str, str] = os.environ, name: str = REMOTE_ENV) -> str:
    """The backup repository's git remote, from the variable `name` (`REMOTE_ENV` by default); empty means not configured."""
    return environ.get(name, "").strip()


def _env() -> dict[str, str]:
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    env.setdefault("GIT_SSH_COMMAND", "ssh -o BatchMode=yes")
    return env


def git(cwd: Path, *args: str) -> str:
    done = subprocess.run(["git", *IDENTITY, *args], cwd=cwd, env=_env(), capture_output=True, text=True, timeout=TIMEOUT, check=True)
    return done.stdout.strip()


def _ref(clone: Path, ref: str) -> str | None:
    try:
        return git(clone, "rev-parse", "--verify", "--quiet", ref)
    except subprocess.CalledProcessError:
        return None


def _clone(remote: str, clone: Path, variable: str = REMOTE_ENV) -> None:
    """Clone the remote if there is no clone yet, on `BRANCH` whatever the remote's default branch is."""
    if not (clone / ".git").exists():
        clone.parent.mkdir(parents=True, exist_ok=True)
        git(clone.parent, "clone", "--quiet", remote, clone.name)
        if _ref(clone, f"refs/remotes/origin/{BRANCH}"):
            git(clone, "checkout", "--quiet", "-B", BRANCH, f"origin/{BRANCH}")
        else:                                          # an empty repository: the first commit starts the branch
            git(clone, "symbolic-ref", "HEAD", f"refs/heads/{BRANCH}")
    origin = git(clone, "remote", "get-url", "origin")
    if origin != remote:
        raise ValueError(f"the backup clone pushes to another remote than {variable}: delete it to clone the new one")


def _copy(ledger_root: Path, clone: Path, folder: str = FOLDER) -> list[str]:
    """Copy every ledger day whose bytes differ into `folder` of the clone; the names copied."""
    target = clone / folder
    target.mkdir(exist_ok=True)
    copied = []
    for day in ledger.dates(ledger_root):
        source = ledger.path_for(ledger_root, day)
        dest = target / source.name
        if not dest.exists() or not filecmp.cmp(source, dest, shallow=False):
            shutil.copyfile(source, dest)
            copied.append(source.name)
    return copied


def sync(ledger_root: Path, clone: Path, remote: str, folder: str = FOLDER, variable: str = REMOTE_ENV) -> BackupResult:
    """Copy, commit and push the ledger into `folder` of the clone. Failures are returned, not raised.

    Two ledgers can share one repository and one clone in folders of their own,
    as the momentum run's two paths do (`statarb.paper.momentum`); `variable`
    names the setting the remote came from, for the messages.
    """
    if not remote:
        return BackupResult("not configured", f"{variable} is not set")
    try:
        _clone(remote, clone, variable)
        copied = _copy(ledger_root, clone, folder)
        if copied:
            git(clone, "add", "--", folder)
            last = ledger.dates(ledger_root)[-1]
            subject = f"Ledger through {last:%Y-%m-%d}" if folder == FOLDER else f"{folder}: ledger through {last:%Y-%m-%d}"
            git(clone, "commit", "--quiet", "-m", subject, "-m", f"{len(copied)} file(s) added or changed.")
        head = _ref(clone, "HEAD")
        if head is None or head == _ref(clone, f"refs/remotes/origin/{BRANCH}"):
            return BackupResult("up to date", "nothing new to push" if head else "the ledger is empty")
        git(clone, "push", "--quiet", "origin", f"HEAD:refs/heads/{BRANCH}")
        return BackupResult("pushed", head[:7])
    except subprocess.CalledProcessError as err:
        detail = (err.stderr or err.stdout or "").strip().splitlines()
        return BackupResult("failed", f"git {err.cmd[len(IDENTITY) + 1]}: {detail[-1] if detail else f'exit {err.returncode}'}")
    except (OSError, ValueError, subprocess.TimeoutExpired) as err:
        return BackupResult("failed", f"{type(err).__name__}: {err}")
