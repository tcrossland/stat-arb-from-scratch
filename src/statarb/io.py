"""Deterministic parquet output.

Within one locked environment the same frame always produces the same bytes:
rows are sorted, the index is dropped, and writer settings are fixed. Files are
written to a temporary path and renamed into place, so a reader never sees half
a file.
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

_WRITE_OPTIONS = {
    "compression": "zstd",
    "compression_level": 3,
    "use_dictionary": True,
    "write_statistics": True,
    "row_group_size": 1_000_000,
    "data_page_size": 1 << 20,
}


def write_parquet(frame: pd.DataFrame, path: Path, sort_by: Sequence[str]) -> None:
    ordered = frame.sort_values(list(sort_by), kind="mergesort").reset_index(drop=True)
    table = pa.Table.from_pandas(ordered, preserve_index=False)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    pq.write_table(table, tmp, **_WRITE_OPTIONS)
    os.replace(tmp, path)


def read_parquet(path: Path) -> pd.DataFrame:
    return pq.read_table(path).to_pandas()
