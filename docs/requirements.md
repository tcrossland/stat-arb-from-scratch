# Requirements

The time, peak memory and disk each runner needs, measured on the author's machine, so a reader knows what a rebuild costs before starting it. Each phase review updates the table, and a runner that grows past its budget is a regression to fix.

Machine: Apple M2, 24 GB of memory, macOS. Times are wall-clock; peak memory is the maximum resident set size reported by `/usr/bin/time -l`.

| Runner | Step | Time | Peak memory | Disk written | Measured |
|---|---|---|---|---|---|
| `statarb.data.build` | rebuild from the pinned snapshots | 11 s | 1.2 GB | 29 MB in `data/derived/processed/`, 4 KB report | 2026-11-16 |
| `statarb.data.build --download` | download, then rebuild | 12 min | 1.2 GB | 58 MB Alpaca snapshot, 0.3 MB Wikipedia snapshot, in the raw store | 2026-11-16 |
| `statarb.factors.build` | Model A's residuals from the phase 0 tables | 7 s | 1.8 GB | 68 MB in `data/derived/processed/` | 2026-11-16 |

The download made 515 tickers' requests at the adapter's pace of 190 a minute, with a pause between tickers; nearly all its time is waiting on that pace, not computing.
