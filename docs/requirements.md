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
| `statarb.models.run` | the phase 5 development run: 24 walk-forward blocks at each of two horizons (four grid points and a refit per block), then four forecasts through the decile sort and the no-trade zone in the main process, the headline optimiser in four worker processes and partial adjustment in four more, each at two book sizes, then the report | 9 min, of which 3 min training, 2 min optimiser paths and 4 min partial-adjustment paths | 2.4 GB in the largest process, 8.5 GB across all of them | 4 MB of models in `data/derived/models/`, 0.2 MB report and charts, 0.2 MB appended to the experiment log per run | 2026-11-17 |
| `statarb.models.holdout` | the phase 5 holdout read: the walk-forward retrained through the holdout at each of two horizons, its 48 development models checked against their hashes, then every forecast through every rule over the holdout year, the optimiser and partial adjustment in four worker processes, each at two book sizes, then the report | 5 min, of which 3.5 min training and 1.5 min paths | 2.6 GB in the largest process, 6.8 GB across all of them | 0.2 MB report and chart, 0.1 MB appended to the experiment log, once | 2026-11-17 |
| `statarb.paper.choice` | the phase 6 evidence for the choice: the walk-forward retrained through the holdout at each of two horizons and its 104 models checked against their hashes, the diagnostic paths through the holdout, then every forecast through the no-trade zone and the optimiser under three slope rules and the decile sort, each at two book sizes, the optimiser paths in four worker processes, then the report | 11.5 min, of which 3.5 min training | 2.9 GB in the largest process | 0.5 MB report and charts, 0.2 MB appended to the experiment log per run | 2026-11-17 |

The optimiser's solve times are wall-clock, so they stay out of the phase 4 report and log; the runner prints each path's mean with its progress line. On the run above an optimal day took 0.040 to 0.061 seconds to decide, and 0.127 to 0.175 with the re-solve, which solves again up to five times. An optimiser path took 92 to 145 seconds on the full history, and 308 to 422 with the re-solve; the decile sorts about a second each.

The phase 5 optimiser paths took 43 to 47 seconds each with four running at once, and a walk-forward block 2 to 5 seconds to tune and refit. A partial-adjustment path took 95 to 99 seconds with four at once: its aim, one solve a day, takes about as long as an optimiser path, and the rest is the hundred engine runs of the trade-rate grid, about half a second each. Over the holdout year an optimiser path took 8 to 9 seconds and a partial-adjustment path 6 to 8, with its development trade rate and no grid.

Phase 6's forward-run runners (`statarb.paper.daily`, `statarb.paper.drift`, `statarb.paper.reproduce` and `statarb.paper.frozen`) have not run on real data: they are measured on the first daily download, as [decision record 0007](decisions/0007-forward-run.md) requires.

The download made 515 tickers' requests at the adapter's pace of 190 a minute, with a pause between tickers; nearly all its time is waiting on that pace, not computing.
