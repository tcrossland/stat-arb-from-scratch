# Phase 0 data quality report

Statistics only: no price, volume or return of any ticker on any date.

## Snapshots

- Constituent source: wikipedia, revision 1384572480, retrieved 2026-11-16, digest 4da8e311e61e
- Price source: alpaca, basis unadjusted, snapshot 2026-11-16, digest a28ff7224e60, bars before 2026-11-16
- Trading days: 2733 (2016-01-04 to 2026-11-13)
- Candidates: 503; tickers with prices: 515
- Price rows: 1355072; returns: 1354557; split days: 109; days with cash: 16391

## Tickers with no data

None.

## Tickers that failed

Failed downloads, and for a raw snapshot, tickers whose data fails a source rule.

None.

## Coverage below 95% of the live window

| ticker | first | last | bars | expected | coverage |
|---|---|---|---|---|---|
| DOW | 2016-01-04 | 2026-11-13 | 2337 | 2733 | 0.8551 |
| SMCI | 2016-01-04 | 2026-11-13 | 2384 | 2733 | 0.8723 |
| EXE | 2016-01-04 | 2026-11-13 | 2577 | 2733 | 0.9429 |

## Rows dropped by cleaning

None.

### By ticker

None.

## Daily total returns with absolute value above 25%

275 returns across 131 tickers, counted by year: on a day with a split or cash, and while the ticker was in the universe.

| year | returns | tickers | on_action_days | while_member |
|---|---|---|---|---|
| 2016 | 10 | 6 | 0 | 3 |
| 2017 | 6 | 5 | 0 | 1 |
| 2018 | 13 | 12 | 1 | 6 |
| 2019 | 17 | 12 | 0 | 9 |
| 2020 | 104 | 59 | 1 | 58 |
| 2021 | 6 | 5 | 0 | 2 |
| 2022 | 22 | 16 | 0 | 17 |
| 2023 | 18 | 12 | 0 | 9 |
| 2024 | 25 | 19 | 0 | 20 |
| 2025 | 27 | 25 | 0 | 14 |
| 2026 | 27 | 23 | 1 | 22 |

## Split days

Split days: 109; with an absolute return above 25%: 2 (EQT, HON).

## Returns spanning missing trading days

28 returns span more than one trading day.

| ticker | gapped_returns |
|---|---|
| VRT | 20 |
| BIIB | 2 |
| XLRE | 2 |
| DOW | 1 |
| DXCM | 1 |
| EXE | 1 |
| SMCI | 1 |

## Zero-volume days

None.

## Universe

- Effective from 2016-04-01 to 2026-11-13
- Rebalances: 128
- Names entering per rebalance: mean 7.8, max 12
- Candidates that were ever members: 451

### Candidates never in the universe

AIZ, ALLE, AOS, ATO, AVY, BF.B, BR, CINF, CPT, CRL, ERIE, FDS, FDXF, FRT, GL, GRMN, IEX, IRM, J, JBHT, JKHY, L, LII, LNT, MAA, NDSN, NI, NVR, NWS, NWSA, PFG, PNR, PNW, PTC, Q, REG, RJF, ROL, RVTY, SKYD, SOLV, STE, TDY, TECH, TKO, TPL, TRMB, TXT, TYL, UDR, VYLR, WRB

## Survivorship indicator

175 of 503 candidates were added to the S&P 500 after 2016-01-01. Their earlier history is included only because they survived into today's index.
