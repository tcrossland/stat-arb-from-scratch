"""Phase 6 ledger backup against a local bare repository: no network, the same git commands as a real remote."""

from __future__ import annotations

import shutil
import subprocess

import pandas as pd
import pytest

from statarb.paper import backup, ledger

DAYS = pd.bdate_range("2027-01-04", "2027-01-08")


def _git(cwd, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()


@pytest.fixture
def remote(tmp_path):
    """An empty bare repository whose default branch is not `main`, as an old git or a hosted default may give."""
    path = tmp_path / "remote.git"
    _git(tmp_path, "init", "--quiet", "--bare", "-b", "master", str(path))
    return path


def _write(root, *days: pd.Timestamp, content: bytes = b"day") -> None:
    root.mkdir(parents=True, exist_ok=True)
    for d in days:
        ledger.path_for(root, d).write_bytes(content + f" {d:%Y-%m-%d}".encode())


def _remote_files(remote) -> dict[str, str]:
    names = _git(remote, "ls-tree", "-r", "--name-only", backup.BRANCH).splitlines()
    return {n: _git(remote, "show", f"{backup.BRANCH}:{n}") for n in names}


def _commits(remote) -> int:
    return int(_git(remote, "rev-list", "--count", backup.BRANCH))


def test_an_empty_remote_is_not_configured(tmp_path) -> None:
    result = backup.sync(tmp_path / "ledger", tmp_path / "clone", "")
    assert result.status == "not configured" and not (tmp_path / "clone").exists()
    assert backup.REMOTE_ENV in result.message


def test_the_remote_comes_from_the_environment() -> None:
    assert backup.remote({backup.REMOTE_ENV: " git@host:owner/ledger.git\n"}) == "git@host:owner/ledger.git"
    assert backup.remote({}) == ""


def test_the_first_sync_pushes_every_day_and_a_second_does_nothing(tmp_path, remote) -> None:
    root, clone = tmp_path / "ledger", tmp_path / "clone"
    _write(root, *DAYS[:3])
    first = backup.sync(root, clone, str(remote))
    assert first.status == "pushed", first.text()
    assert str(remote) not in first.text()                  # the result goes into a published note
    assert _remote_files(remote) == {f"ledger/{ledger.path_for(root, d).name}": f"day {d:%Y-%m-%d}" for d in DAYS[:3]}
    assert _git(remote, "log", "-1", "--format=%s %an", backup.BRANCH) == "Ledger through 2027-01-06 statarb daily job"
    second = backup.sync(root, clone, str(remote))
    assert second.status == "up to date" and _commits(remote) == 1


def test_new_and_changed_days_are_pushed_and_none_deleted(tmp_path, remote) -> None:
    root, clone = tmp_path / "ledger", tmp_path / "clone"
    _write(root, *DAYS[:2])
    backup.sync(root, clone, str(remote))
    _write(root, DAYS[1], content=b"rewritten")
    _write(root, DAYS[2])
    ledger.path_for(root, DAYS[0]).unlink()
    assert backup.sync(root, clone, str(remote)).status == "pushed"
    files = _remote_files(remote)
    assert len(files) == 3 and files[f"ledger/{ledger.path_for(root, DAYS[1]).name}"] == "rewritten 2027-01-05"
    assert _commits(remote) == 2


def test_a_failed_push_is_reported_and_the_next_sync_retries_it(tmp_path, remote) -> None:
    root, clone = tmp_path / "ledger", tmp_path / "clone"
    _write(root, DAYS[0])
    backup.sync(root, clone, str(remote))
    away = remote.rename(tmp_path / "away.git")                  # the remote cannot be reached
    _write(root, DAYS[1])
    failed = backup.sync(root, clone, str(remote))
    assert failed.status == "failed" and failed.message.startswith("git push:"), failed.text()
    away.rename(remote)
    retried = backup.sync(root, clone, str(remote))              # nothing new to commit, but the clone is ahead
    assert retried.status == "pushed" and _commits(remote) == 2
    assert backup.sync(root, clone, str(remote)).status == "up to date"


def test_a_lost_clone_is_cloned_again_and_continues_the_history(tmp_path, remote) -> None:
    root, clone = tmp_path / "ledger", tmp_path / "clone"
    _write(root, DAYS[0])
    backup.sync(root, clone, str(remote))
    shutil.rmtree(clone)
    _write(root, DAYS[1])
    assert backup.sync(root, clone, str(remote)).status == "pushed"
    assert _commits(remote) == 2 and len(_remote_files(remote)) == 2


def test_a_clone_of_another_remote_is_refused(tmp_path, remote) -> None:
    root, clone = tmp_path / "ledger", tmp_path / "clone"
    _write(root, DAYS[0])
    backup.sync(root, clone, str(remote))
    other = tmp_path / "other.git"
    _git(tmp_path, "init", "--quiet", "--bare", "-b", "main", str(other))
    result = backup.sync(root, clone, str(other))
    assert result.status == "failed" and backup.REMOTE_ENV in result.message
    assert str(other) not in result.message and str(clone) not in result.message


def test_two_ledgers_share_one_clone_in_folders_of_their_own(tmp_path, remote) -> None:
    """The momentum run's two paths (decision record 0010) back up to one repository."""
    clone = tmp_path / "clone"
    _write(tmp_path / "a", *DAYS[:2])
    _write(tmp_path / "b", DAYS[0], content=b"other")
    assert backup.sync(tmp_path / "a", clone, str(remote), "total-return", "X_REMOTE").status == "pushed"
    assert backup.sync(tmp_path / "b", clone, str(remote), "residual", "X_REMOTE").status == "pushed"
    files = _remote_files(remote)
    assert {n.split("/")[0] for n in files} == {"total-return", "residual"} and len(files) == 3
    assert files[f"residual/{ledger.path_for(tmp_path / 'b', DAYS[0]).name}"] == "other 2027-01-04"
    assert backup.sync(tmp_path / "a", clone, str(remote), "total-return", "X_REMOTE").status == "up to date"
    assert "X_REMOTE" in backup.sync(tmp_path / "a", clone, "", "total-return", "X_REMOTE").message
