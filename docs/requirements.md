# Requirements

The time, peak memory and disk each runner needs, measured on the author's machine, so a reader knows what a rebuild costs before starting it. Each phase review updates the table, and a runner that grows past its budget is a regression to fix.

Machine: Apple M2, 24 GB of memory, macOS. Times are wall-clock; peak memory is the maximum resident set size reported by `/usr/bin/time -l`.

| Runner | Step | Time | Peak memory | Disk written | Measured |
|---|---|---|---|---|---|
| `statarb.data.build` | rebuild from the pinned snapshots | 11 s | 1.2 GB | 29 MB in `data/derived/processed/`, 4 KB report | 2026-11-16 |
| `statarb.data.build --download` | download, then rebuild | 12 min | 1.2 GB | 58 MB Alpaca snapshot, 0.3 MB Wikipedia snapshot, in the raw store | 2026-11-16 |
| `statarb.factors.build` | Model A's residuals from the phase 0 tables, then the diagnostics report | 14 s | 2.1 GB | 68 MB in `data/derived/processed/`, 0.1 MB report and charts | 2026-11-16 |
| `statarb.factors.build --model pca` | Model B's residuals from the phase 0 tables, then its report beside Model A | 47 s | 1.8 GB | 174 MB in `data/derived/processed/`, 24 KB report and chart | 2026-11-16 |
| `statarb.factors.sensitivity` | Model A at three windows, compared | 22 s | 2.4 GB | 2 KB report | 2026-11-16 |
| `statarb.backtest.run` | the phase 2 sweep, 49 signal and holding variants at three fills (147 configurations) and five cost levels, then 100 placebo runs and the report | 33 s | 1.8 GB | 0.2 MB report and charts, 0.8 MB appended to the experiment log per run | 2026-11-16 |
| `statarb.backtest.cost_run` | the phase 3 cost model: three configurations, with and without the no-trade zone, at five book sizes under the headline cost model and its sensitivities (145 runs), then the report | 47 s | 1.8 GB | 0.1 MB report and charts, 0.3 MB appended to the experiment log per run | 2026-11-16 |
| `statarb.portfolio.run` | the phase 4 paths: three decile sorts and 17 optimiser settings, each at two book sizes, in six worker processes, the bracket's re-costing, then the report | 15 min | 2.5 GB in the largest process, 8.1 GB across all of them | 0.2 MB report and charts, 0.2 MB appended to the experiment log per run | 2026-11-17 |

The optimiser's solve times are wall-clock, so they stay out of the phase 4 report and log; the runner prints each path's mean with its progress line. On the run above an optimal day took 0.040 to 0.061 seconds to decide, and 0.127 to 0.175 with the re-solve, which solves again up to five times. An optimiser path took 92 to 145 seconds on the full history, and 308 to 422 with the re-solve; the decile sorts about a second each.

The download made 515 tickers' requests at the adapter's pace of 190 a minute, with a pause between tickers; nearly all its time is waiting on that pace, not computing.
