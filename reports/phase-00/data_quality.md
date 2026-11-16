# Phase 0 data quality report

Statistics only: no price, volume or return of any ticker on any date.

## Snapshots

- Constituent source: wikipedia, revision 1384572480, retrieved 2026-11-16, digest 4da8e311e61e
- Price source: alpaca, basis unadjusted, snapshot 2026-11-16, digest a28ff7224e60, bars before 2026-11-16
- Trading days: 2733 (2016-01-04 to 2026-11-13)
- Candidates: 503; tickers with prices: 483
- Price rows: 1270970; returns: 1270487; split days: 105; days with cash: 15304

## Tickers with no data

None.

## Tickers that failed

Failed downloads, and for a raw snapshot, tickers whose data fails a source rule.

- ACGL: WithholdingError: ACGL: dividend going ex 2024-11-18 is flagged foreign; check whether it is net of withholding tax
- ACN: WithholdingError: ACN: dividend going ex 2020-04-15 is flagged foreign; check whether it is net of withholding tax
- ALLE: WithholdingError: ALLE: dividend going ex 2020-03-16 is flagged foreign; check whether it is net of withholding tax
- AMCR: WithholdingError: AMCR: dividend going ex 2020-03-03 is flagged foreign; check whether it is net of withholding tax
- AON: WithholdingError: AON: dividend going ex 2020-04-30 is flagged foreign; check whether it is net of withholding tax
- APTV: WithholdingError: APTV: dividend going ex 2020-02-04 is flagged foreign; check whether it is net of withholding tax
- BG: WithholdingError: BG: dividend going ex 2020-02-13 is flagged foreign; check whether it is net of withholding tax
- CB: WithholdingError: CB: dividend going ex 2020-03-19 is flagged foreign; check whether it is net of withholding tax
- CCL: WithholdingError: CCL: dividend going ex 2020-02-20 is flagged foreign; check whether it is net of withholding tax
- CRH: WithholdingError: CRH: dividend going ex 2020-03-12 is flagged foreign; check whether it is net of withholding tax
- EG: WithholdingError: EG: dividend going ex 2023-03-15 is flagged foreign; check whether it is net of withholding tax
- ETN: WithholdingError: ETN: dividend going ex 2020-05-13 is flagged foreign; check whether it is net of withholding tax
- FERG: WithholdingError: FERG: dividend going ex 2021-03-25 is flagged foreign; check whether it is net of withholding tax
- GRMN: WithholdingError: GRMN: dividend going ex 2020-06-12 is flagged foreign; check whether it is net of withholding tax
- IVZ: WithholdingError: IVZ: dividend going ex 2020-02-12 is flagged foreign; check whether it is net of withholding tax
- JBL: WithholdingError: JBL: dividend going ex 2023-08-14 is flagged foreign; check whether it is net of withholding tax
- JCI: WithholdingError: JCI: dividend going ex 2020-03-13 is flagged foreign; check whether it is net of withholding tax
- LIN: WithholdingError: LIN: dividend going ex 2020-06-02 is flagged foreign; check whether it is net of withholding tax
- LYB: WithholdingError: LYB: dividend going ex 2020-06-05 is flagged foreign; check whether it is net of withholding tax
- MDT: WithholdingError: MDT: dividend going ex 2020-03-26 is flagged foreign; check whether it is net of withholding tax
- MRVL: WithholdingError: MRVL: dividend going ex 2020-04-02 is flagged foreign; check whether it is net of withholding tax
- NXPI: WithholdingError: NXPI: dividend going ex 2020-03-13 is flagged foreign; check whether it is net of withholding tax
- PFE: WithholdingError: PFE: dividend going ex 2023-07-27 is flagged foreign; check whether it is net of withholding tax
- PNR: WithholdingError: PNR: dividend going ex 2020-04-16 is flagged foreign; check whether it is net of withholding tax
- RCL: WithholdingError: RCL: dividend going ex 2020-03-05 is flagged foreign; check whether it is net of withholding tax
- SLB: WithholdingError: SLB: dividend going ex 2020-02-11 is flagged foreign; check whether it is net of withholding tax
- STE: WithholdingError: STE: dividend going ex 2020-06-11 is flagged foreign; check whether it is net of withholding tax
- STX: WithholdingError: STX: dividend going ex 2020-03-24 is flagged foreign; check whether it is net of withholding tax
- SW: WithholdingError: SW: dividend going ex 2024-08-15 is flagged foreign; check whether it is net of withholding tax
- TEL: WithholdingError: TEL: dividend going ex 2020-05-21 is flagged foreign; check whether it is net of withholding tax
- TT: WithholdingError: TT: dividend going ex 2020-03-12 is flagged foreign; check whether it is net of withholding tax
- WTW: WithholdingError: WTW: dividend going ex 2021-12-30 is flagged foreign; check whether it is net of withholding tax

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

262 returns across 123 tickers, counted by year: on a day with a split or cash, and while the ticker was in the universe.

| year | returns | tickers | on_action_days | while_member |
|---|---|---|---|---|
| 2016 | 10 | 6 | 0 | 3 |
| 2017 | 6 | 5 | 0 | 1 |
| 2018 | 12 | 11 | 1 | 6 |
| 2019 | 17 | 12 | 0 | 9 |
| 2020 | 95 | 54 | 1 | 55 |
| 2021 | 6 | 5 | 0 | 2 |
| 2022 | 22 | 16 | 0 | 17 |
| 2023 | 17 | 11 | 0 | 8 |
| 2024 | 25 | 19 | 0 | 20 |
| 2025 | 27 | 25 | 0 | 16 |
| 2026 | 25 | 21 | 1 | 20 |

## Split days

Split days: 105; with an absolute return above 25%: 2 (EQT, HON).

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
- Names entering per rebalance: mean 7.1, max 12
- Candidates that were ever members: 432

### Candidates never in the universe

AIZ, AOS, ATO, AVY, BF.B, BR, CINF, CPT, ERIE, FDS, FDXF, FRT, IEX, IRM, J, JKHY, L, LNT, MAA, NDSN, NWS, NWSA, PNW, PTC, Q, REG, RJF, ROL, SKYD, SOLV, TDY, TECH, TKO, TPL, TRMB, TYL, UDR, VYLR, WRB

## Survivorship indicator

175 of 503 candidates were added to the S&P 500 after 2016-01-01. Their earlier history is included only because they survived into today's index.
