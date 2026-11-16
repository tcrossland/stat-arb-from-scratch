# Data model

The stored tables, their columns and keys, and how they join. `tests/test_data_model_doc.py` checks the columns and types here against the tables the build writes.

All tables are long format in `data/derived/processed/`, written by `statarb.data.build` with rows sorted by their key. Dates are trading dates in New York, stored as `timestamp[ns]` with no time zone. Tickers are as Wikipedia lists them (`BRK.B`, not `BRK-B`).

## Raw snapshots

`<raw store>/<source>/<download date>/` holds one download as the source returned it, with `manifest.json` written last; the raw store is `data/raw/` or the path in `STATARB_RAW`. A snapshot without its manifest is incomplete and never read. Every manifest holds `files`, the SHA-256 of each file by its path in the snapshot, and `digest`, the SHA-256 of the lines `path hash` sorted by path; config pins a snapshot by date and digest, and the build refuses one that does not match. A complete snapshot is read-only. The price manifest records the source, basis, layout, the first date asked for, `end_exclusive` (the New York date of the download: bars before it only), the tickers asked for, those with no data and those that failed. Alpaca snapshots keep `bars/<ticker>.parquet` with Alpaca's bar fields and `actions/<ticker>.json` with its corporate-action records; the build applies the rules of decision record 0004 to them. Wikipedia snapshots keep `page.html` and the revision id.

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
| `cash` | double | cash per share going ex (decision record 0004) |

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

## Joins

- `prices`, `actions` and `returns` join on `date` and `ticker`. Never rely on index alignment.
- `universe` restricts any of them to members: an inner join on `date` and `ticker`.
- `sectors` joins on `ticker` with the date condition above, not on equality.
