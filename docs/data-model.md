# Data model

The stored tables, their columns and keys, and how they join. `tests/test_data_model_doc.py` checks the columns and types here against the tables the build writes.

All tables are long format in `data/derived/processed/`, written with rows sorted by their key: the phase 0 tables by `statarb.data.build`, `residuals` by `statarb.factors.build` from them. Phases 2 and 3 store no table: the backtest pivots these into dates by tickers panels in memory (`statarb.signals.tables`), phase 3 recomputes its cost inputs (spread estimates, volatilities, dollar volumes) from them on each run, and each writes only its report and experiment log, below. Dates are trading dates in New York, stored as `timestamp[ns]` with no time zone. Tickers are as Wikipedia lists them (`BRK.B`, not `BRK-B`).

## Raw snapshots

`<raw store>/<source>/<download date>/` holds one download as the source returned it, with `manifest.json` written last; the raw store is `data/raw/` or the path in `STATARB_RAW`. A snapshot without its manifest is incomplete and never read. Every manifest holds `files`, the SHA-256 of each file by its path in the snapshot, and `digest`, the SHA-256 of the lines `path hash` sorted by path; config pins a snapshot by date and digest, and the build refuses one that does not match. A complete snapshot is read-only. The price manifest records the source, basis, layout, the first date asked for, `end_exclusive` (the New York date of the download: bars before it only), the tickers asked for, those with no data and those that failed. Alpaca snapshots keep `bars/<ticker>.parquet` with Alpaca's bar fields and `actions/<ticker>.json` with its corporate-action records; the build applies `config/alpaca.toml` to them (decision record 0004). Wikipedia snapshots keep `page.html` and the revision id.

## candidates

Today's S&P 500 constituents from the pinned Wikipedia revision. Key: `ticker`.

| Column | Type | Meaning |
|---|---|---|
| `ticker` | string | ticker as listed |
| `security` | string | company name |
| `sector` | string | current GICS sector |
| `sub_industry` | string | current GICS sub-industry |
| `date_added` | timestamp[ns] | date added to the index, as the page states; null where it states none |
| `cik` | int64 | SEC Central Index Key |

## prices

Cleaned unadjusted daily bars, for candidates and the factor ETFs. Key: `date`, `ticker`.

| Column | Type | Meaning |
|---|---|---|
| `date` | timestamp[ns] | trading date |
| `ticker` | string | ticker |
| `open` | double | opening price as traded |
| `high` | double | high as traded |
| `low` | double | low as traded |
| `close` | double | closing price as traded |
| `volume` | int64 | shares traded, as traded |

## actions

Splits and cash on their ex-dates. Key: `date`, `ticker`. Joins to `prices` on both.

| Column | Type | Meaning |
|---|---|---|
| `date` | timestamp[ns] | ex-date |
| `ticker` | string | ticker |
| `split_ratio` | double | new shares per old share; 1 when none |
| `cash` | double | cash per share going ex, gross of withholding; spin-offs valued as cash (decision record 0004) |

## returns

Daily total returns. Key: `date`, `ticker`. A ticker's first bar has no return.

| Column | Type | Meaning |
|---|---|---|
| `date` | timestamp[ns] | the day the return is earned to |
| `ticker` | string | ticker |
| `ret` | double | `split_ratio * (close + cash) / prev_close - 1` |
| `prev_date` | timestamp[ns] | the ticker's previous bar; more than one trading day back where bars are missing |
| `split_ratio` | double | split going ex on `date` |
| `cash` | double | cash going ex on `date` |

## universe

Members by day. Key: `date`, `ticker`.

| Column | Type | Meaning |
|---|---|---|
| `date` | timestamp[ns] | trading date of membership |
| `ticker` | string | member |
| `rebalanced_on` | timestamp[ns] | the month end whose ranking chose it, the trading day before the first `date` it applies to |

## sectors

Dated GICS sectors. Key: `ticker`, `valid_from`. A ticker's sector on day *t* is the row with `valid_from <= t` and `valid_to` null or `t < valid_to`.

| Column | Type | Meaning |
|---|---|---|
| `ticker` | string | ticker |
| `sector` | string | GICS sector |
| `valid_from` | timestamp[ns] | first date the sector applies; the data start for the earliest |
| `valid_to` | timestamp[ns] | first date it no longer applies; null while current |

## residuals

Model A's residual returns (phase 1): each candidate's daily return less what SPY and its sector ETF explain, with betas estimated over the window ending the day before. Key: `date`, `ticker`. A row exists where the stock has a return on `date` and enough returns in the window; the factor ETFs have none. Universe membership is not applied here.

| Column | Type | Meaning |
|---|---|---|
| `date` | timestamp[ns] | the day the residual is earned to |
| `ticker` | string | candidate |
| `ret` | double | the day's total return, as in `returns` |
| `fitted` | double | `beta_market * market + beta_sector * sector` on `date`, where sector is the sector ETF's return less SPY's |
| `residual` | double | `ret - fitted` |
| `alpha` | double | the intercept of the window's regression; estimated, not subtracted |
| `beta_market` | double | beta to SPY over the window ending the trading day before `date` |
| `beta_sector` | double | beta to the sector factor over the same window; null where `market_only` |
| `sector_etf` | string | the sector ETF on `date`; null where `market_only` |
| `n_obs` | int64 | returns in the window that the regression used |
| `market_only` | bool | SPY alone: the sector had no ETF on `date`, or too few days in the window had one |
| `volume_ratio` | double | volume on `date` over its median of the previous `lookback_days` trading days (`[events]` of `config/factors.toml`), both on one share basis; null without a full lookback |
| `event` | bool | `volume_ratio` at least `[events] volume_ratio`: a volume spike, the crude event flag |

## residuals_pca

Model B's residual returns (phase 4): each candidate's daily return less what the top `k` eigenportfolios explain, where `k` is `[pca] factors` of `config/factors.toml`. The eigenportfolios come from the correlation matrix of the stocks with a complete window ending the trading day before `date`, and each stock with at least `[pca] min_observations` returns in that window is regressed on them. Key: `date`, `ticker`. A row exists where the stock has a return on `date` and a regression; the factor ETFs have none, and universe membership is not applied. The columns `beta_k` and `eigenvalue_k` stand for one column each for `k` from 1 to `[pca] factors`, in that order.

| Column | Type | Meaning |
|---|---|---|
| `date` | timestamp[ns] | the day the residual is earned to |
| `ticker` | string | candidate |
| `ret` | double | the day's total return, as in `returns` |
| `fitted` | double | the stock's betas times the eigenportfolios' returns on `date`; a stock with no return on `date` counts as zero in those returns |
| `residual` | double | `ret - fitted`; the intercept is estimated, not subtracted, as in Model A |
| `n_obs` | int64 | returns in the window that the stock's regression used |
| `beta_k` | double | beta to eigenportfolio `k` over the window ending the trading day before `date` |
| `eigenvalue_k` | double | eigenvalue `k` of that window's correlation matrix: the variance of eigenportfolio `k`'s returns over the window, the same for every stock on `date` |

## Joins

- `prices`, `actions`, `returns`, `residuals` and `residuals_pca` join on `date` and `ticker`. Never rely on index alignment.
- `universe` restricts any of them to members: an inner join on `date` and `ticker`. For residuals this happens at signal time, on the day a position would be formed, never in the table.
- `sectors` joins on `ticker` with the date condition above, not on equality.

## Experiment logs

`reports/phase-NN/experiments.jsonl`, committed, append-only, one JSON object per line: one per backtest configuration and cost setting (in phase 3, also per book size) each time a runner logs. Its fields:

- `recorded_at`: the UTC time the entry was written, ISO 8601.
- `git_commit`, `git_dirty`: the commit the code ran at, and whether the working tree had changes. The committed log comes from a clean tree.
- `config_overlay`: the overlay directory (`STATARB_CONFIG_OVERLAY`) if one was set, else null.
- `price_source`, `price_snapshot`: `[source] name` and `snapshot` of `config/data.toml` as the run read them.
- `seed`: `[run] seed` of `config/backtest.toml`.
- `config`: the configuration that set the positions and costs. In phase 2: `signal`, `source`, `lookback_days`, `vol_scaled`, `holding_days`, `fill`, `cost_bps`, `slippage_bps`, `borrow_annual`, `decile`, `start`, and for the s-score `sscore`, its settings. In phase 3 the same position keys less the flat cost, plus `name` (the configuration's name in `config/costs.toml`), `book_size` (capital in US dollars), `spread` (a half-spread in bps, or an estimator's name), `half_tick_floor`, `impact_coefficient`, `commission` (the schedule's name, per-share rate, minimum and maximum), `borrow` (the general and hard-to-borrow rates and the proxy's quantile), `no_trade_zone`, and `no_trade` (the calibration window when the zone is on, else null).
- `config_id`: the first 16 hex digits of the SHA-256 of `config` as JSON with sorted keys. The fields above it stay out of `config`, so the same configuration has the same id whatever code state, overlay or snapshot it ran on.
- `metrics`: the headline metrics, annualised where the name says so; non-finite values are null. Phase 2's are per dollar of gross exposure. Phase 3's are per dollar of capital, with idle capital earning nothing, and add each cost component (`ann_cost_spread`, `ann_cost_impact`, `ann_cost_commission`, and the same per dollar traded as `*_bps_per_dollar`), `t_stat`, `mean_exposure` (capital deployed), `median_names`, `net_dollar_imbalance`, `hard_short_share`, `ann_borrow_hard_extra` and `gross_basis_sharpe` (the net Sharpe per dollar of gross, for comparison with phase 2).

Key: none, since reruns repeat a `config_id`. A trial is a distinct position path: `config` reduced to the keys that set positions (`statarb.backtest.trials.PATH_KEYS`), so cost settings, book sizes and names are not trials. Each phase counts the logs up to its own.
