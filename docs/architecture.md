# Architecture

The packages, runners and config files, what each reads and writes, and the external libraries each enters through. `tests/test_architecture_doc.py` checks the module, runner and config tables against the code.

**Where data lives.** The raw store, `data/raw/` or the absolute path in `STATARB_RAW`, holds the raw snapshots: kept, read-only once complete and backed up outside the repository. Worktrees set `STATARB_RAW` to the main checkout's `data/raw/`, so there is one store. `data/derived/` holds everything rebuilt from it and can be deleted. Nothing under `data/` is committed or versioned: snapshots are versioned by convention instead, by date and content digest pinned in config.

## Modules

| Module | Phase | Purpose |
|---|---|---|
| `statarb.config` | 0 | Loads `config/<name>.toml`, resolves configured paths against the repository root, and finds the raw store (`STATARB_RAW`). |
| `statarb.io` | 0 | Deterministic parquet: fixed compression, rows sorted by key, written to a temporary file and renamed. |
| `statarb.testing` | 0 | Helpers for tests that the package itself also provides. |
| `statarb.testing.lookahead` | 0 | The look-ahead check: perturb data after a cut-off, assert outputs up to it are unchanged. |
| `statarb.data` | 0 | The data build. |
| `statarb.data.schema` | 0 | Column names and the bar schema. |
| `statarb.data.sources` | 0 | The `PriceSource` protocol and the price bases a source can declare. |
| `statarb.data.cache` | 0 | Raw snapshots: written once, complete when `manifest.json` with every file's hash and the digest is written last, then read-only; verified against the pinned digest. |
| `statarb.data.canonical` | 0 | Converts a source's declared basis to unadjusted bars. |
| `statarb.data.returns` | 0 | Daily total returns from unadjusted bars, splits and cash. |

## Seams

| Protocol | Implementations | Chosen by |
|---|---|---|
| `PriceSource` | synthetic sources in `tests/helpers.py` | the test |

`tests/contract/` runs every implementation of each protocol through the same checks.

## Runners

| Runner | Phase | Reads | Writes |
|---|---|---|---|

## Config files

| File | Read by | Holds |
|---|---|---|
| `data.toml` | the phase 0 build, not yet written | Start date, price source, universe, factor ETFs, quality thresholds, paths. |
| `universe.toml` | the phase 0 build, not yet written | The Wikipedia revision to pin. |
| `sector_changes.toml` | the phase 0 build, not yet written | GICS sector changes, to be filled in during phase 0. |

## External libraries

| Library | Licence | Enters through | Used for |
|---|---|---|---|
| pandas | BSD-3-Clause | every `statarb.data` module | long-format tables |
| NumPy | BSD-3-Clause, with bundled 0BSD, MIT, Zlib and CC0-1.0 parts | `canonical`, `testing.lookahead` | array arithmetic and seeded noise |
| pyarrow | Apache-2.0 | `statarb.io` | parquet |

The HTTP clients use the standard library (`urllib`), so no client library is pinned. Each later phase adds its libraries to `pyproject.toml` and to this table when it first uses them.
