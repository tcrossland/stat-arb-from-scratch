# Phase 0 data quality report

Statistics only: no price, volume or return of any ticker on any date.

## Snapshots

- Constituent source: wikipedia, revision 1384572480, retrieved 2026-11-16, digest 4da8e311e61e
- Price source: alpaca, basis unadjusted, snapshot 2026-11-16, digest a28ff7224e60, bars before 2026-11-16
- Trading days: 2733 (2016-01-04 to 2026-11-13)
- Candidates: 503; tickers with prices: 515
- Price rows: 1349238; returns: 1348723; split days: 108; days with cash: 16369

## Tickers with no data

None.

## Tickers that failed

Failed downloads, and for a raw snapshot, tickers whose data fails a source rule.

None.

## Coverage below 95% of the live window

| ticker | first | last | bars | expected | coverage |
|---|---|---|---|---|---|
| SMCI | 2016-01-04 | 2026-11-13 | 2384 | 2733 | 0.8723 |

## Rows dropped by cleaning

| reason | rows |
|---|---|
| before listing (configured) | 5834 |

### By ticker

| ticker | reason | rows | first | last |
|---|---|---|---|---|
| DOW | before listing (configured) | 420 | 2016-01-04 | 2017-08-31 |
| EXE | before listing (configured) | 1129 | 2016-01-04 | 2020-06-26 |
| FOX | before listing (configured) | 806 | 2016-01-04 | 2019-03-18 |
| FOXA | before listing (configured) | 806 | 2016-01-04 | 2019-03-18 |
| JCI | before listing (configured) | 170 | 2016-01-04 | 2016-09-02 |
| SW | before listing (configured) | 2140 | 2016-01-04 | 2024-07-05 |
| VRT | before listing (configured) | 363 | 2018-07-30 | 2020-02-07 |

## Daily total returns with absolute value above 25%

256 returns across 130 tickers, counted by year: on a day with a split or cash, and while the ticker was in the universe.

| year | returns | tickers | on_action_days | while_member |
|---|---|---|---|---|
| 2016 | 7 | 5 | 0 | 2 |
| 2017 | 6 | 5 | 0 | 1 |
| 2018 | 12 | 11 | 1 | 6 |
| 2019 | 16 | 11 | 0 | 9 |
| 2020 | 91 | 58 | 1 | 58 |
| 2021 | 5 | 4 | 0 | 2 |
| 2022 | 22 | 16 | 0 | 17 |
| 2023 | 18 | 12 | 0 | 9 |
| 2024 | 25 | 19 | 0 | 20 |
| 2025 | 27 | 25 | 0 | 14 |
| 2026 | 27 | 23 | 1 | 22 |

## Split days

Split days: 108; with an absolute return above 25%: 2 (EQT, HON).

## Returns spanning missing trading days

6 returns span more than one trading day.

| ticker | gapped_returns |
|---|---|
| BIIB | 2 |
| XLRE | 2 |
| DXCM | 1 |
| SMCI | 1 |

## Zero-volume days

None.

## Universe

- Effective from 2016-04-01 to 2026-11-13
- Rebalances: 128
- Names entering per rebalance: mean 7.7, max 12
- Candidates that were ever members: 451

### Candidates never in the universe

AIZ, ALLE, AOS, ATO, AVY, BF.B, BR, CINF, CPT, CRL, ERIE, FDS, FDXF, FOX, FRT, GL, GRMN, IEX, IRM, J, JKHY, L, LII, LNT, MAA, NDSN, NI, NVR, NWS, NWSA, PFG, PNR, PNW, PTC, Q, REG, RJF, ROL, RVTY, SKYD, SOLV, STE, TDY, TECH, TKO, TPL, TRMB, TXT, TYL, UDR, VYLR, WRB

## Survivorship indicator

175 of 503 candidates were added to the S&P 500 after 2016-01-01. Their earlier history is included only because they survived into today's index.
