"""Raw download snapshots: data/raw/<source>/<download date>/.

A snapshot is complete only once manifest.json exists; it is written last,
with the SHA-256 of every file and the snapshot's digest: the SHA-256 of its
sorted `path hash` lines. Config pins a snapshot by date and digest, and a
pinned snapshot whose files no longer match is refused. Complete snapshots are
made read-only and never modified; the one exception is `add_hashes`, which
writes the hashes into a manifest that lacks them and touches nothing else.
Incomplete snapshots are never read and are cleared before a new download into
the same directory.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import shutil
import stat
from pathlib import Path
from typing import Any

import pandas as pd

from statarb.io import read_parquet, write_parquet

MANIFEST = "manifest.json"


class SnapshotExistsError(FileExistsError):
    pass


class SnapshotDigestError(ValueError):
    """A pinned snapshot whose files, manifest hashes or digest do not match the pin."""


def file_hashes(path: Path) -> dict[str, str]:
    """SHA-256 of every file in a snapshot but its manifest, by path relative to the snapshot."""
    return {
        p.relative_to(path).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(path.rglob("*"))
        if p.is_file() and p.name not in (MANIFEST, MANIFEST + ".tmp")
    }


def digest(hashes: dict[str, str]) -> str:
    """The snapshot's digest: SHA-256 of its `path hash` lines, sorted by path."""
    lines = "".join(f"{name} {h}\n" for name, h in sorted(hashes.items()))
    return hashlib.sha256(lines.encode()).hexdigest()


def make_read_only(path: Path) -> None:
    """Clear the write bits of a snapshot's files and folders, so nothing changes it by accident."""
    for p in sorted(path.rglob("*"), reverse=True):
        p.chmod(p.stat().st_mode & ~(stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH))
    path.chmod(path.stat().st_mode & ~(stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH))


def _write_manifest(path: Path, manifest: dict[str, Any]) -> None:
    tmp = path / (MANIFEST + ".tmp")
    tmp.write_text(json.dumps(manifest, indent=2, sort_keys=True, default=str) + "\n")
    os.replace(tmp, path / MANIFEST)


def snapshot_dir(raw_root: Path, source: str, day: dt.date) -> Path:
    return raw_root / source / day.isoformat()


def is_complete(path: Path) -> bool:
    return (path / MANIFEST).is_file()


class SnapshotWriter:
    """Writes one snapshot; `commit` writes the manifest last, which completes it."""

    def __init__(self, raw_root: Path, source: str, day: dt.date) -> None:
        self.path = snapshot_dir(raw_root, source, day)
        if is_complete(self.path):
            raise SnapshotExistsError(f"complete snapshot already exists: {self.path}")
        if self.path.exists():
            shutil.rmtree(self.path)
        self.path.mkdir(parents=True)

    def write_frame(self, name: str, frame: pd.DataFrame, sort_by: list[str]) -> None:
        write_parquet(frame, self.path / f"{name}.parquet", sort_by)

    def write_bytes(self, name: str, data: bytes) -> None:
        (self.path / name).parent.mkdir(parents=True, exist_ok=True)
        (self.path / name).write_bytes(data)

    def commit(self, manifest: dict[str, Any]) -> Path:
        """Write the manifest with the files' hashes and digest, which completes the snapshot, then make it read-only."""
        hashes = file_hashes(self.path)
        _write_manifest(self.path, {**manifest, "files": hashes, "digest": digest(hashes)})
        make_read_only(self.path)
        return self.path


def complete_snapshots(raw_root: Path, source: str) -> list[Path]:
    base = raw_root / source
    if not base.is_dir():
        return []
    return sorted(p for p in base.iterdir() if p.is_dir() and is_complete(p))


def verify(path: Path, pinned_digest: str) -> None:
    """Raise SnapshotDigestError unless the files on disk match the manifest's hashes and the pinned digest."""
    manifest = read_manifest(path)
    if "files" not in manifest:
        raise SnapshotDigestError(f"{path}: the manifest has no file hashes; add them with --add-hashes")
    on_disk = file_hashes(path)
    if on_disk != manifest["files"] or digest(on_disk) != manifest["digest"]:
        changed = sorted(set(on_disk.items()) ^ set(manifest["files"].items()))
        raise SnapshotDigestError(f"{path}: files differ from the manifest: {[name for name, _ in changed][:5]}")
    if manifest["digest"] != pinned_digest:
        raise SnapshotDigestError(f"{path}: digest {manifest['digest']} is not the pinned {pinned_digest!r}")


def select_snapshot(raw_root: Path, source: str, pinned: str = "", pinned_digest: str = "") -> Path:
    """The pinned snapshot (download date and digest) if set, verified, else the latest complete one."""
    if pinned:
        path = raw_root / source / pinned
        if not is_complete(path):
            raise FileNotFoundError(f"pinned snapshot is missing or incomplete: {path}")
        if not pinned_digest:
            raise SnapshotDigestError(f"{path}: pinned by date only; pin its digest too")
        verify(path, pinned_digest)
        return path
    found = complete_snapshots(raw_root, source)
    if not found:
        raise FileNotFoundError(f"no complete {source} snapshot under {raw_root}; run with --download")
    return found[-1]


def read_manifest(path: Path) -> dict[str, Any]:
    return json.loads((path / MANIFEST).read_text())


def read_frame(path: Path, name: str) -> pd.DataFrame:
    return read_parquet(path / f"{name}.parquet")


def add_hashes(path: Path) -> str:
    """Write the file hashes and digest into a complete snapshot's manifest that lacks them; return the digest.

    The only change ever made to a complete snapshot, and to its manifest
    alone. A manifest that has them is checked, not rewritten.
    """
    manifest = read_manifest(path)
    if "files" in manifest:
        verify(path, manifest["digest"])
        return manifest["digest"]
    hashes = file_hashes(path)
    mode = path.stat().st_mode
    path.chmod(mode | stat.S_IWUSR)
    try:
        if (path / MANIFEST).exists():
            (path / MANIFEST).chmod((path / MANIFEST).stat().st_mode | stat.S_IWUSR)
        _write_manifest(path, {**manifest, "files": hashes, "digest": digest(hashes)})
    finally:
        path.chmod(mode)
    make_read_only(path)
    return digest(hashes)
