# Phase 7 data quality report: MarketParquet

Statistics only: no price, volume or return of any symbol on any date.

## Snapshot

- Source: marketparquet, basis split_adjusted, snapshot 2026-11-20, digest dae4a405cb5b
- Bars read: 2016-01-01 to before 2026-11-16
- Before 2016-01-01: each file's schema and row count, from its footer alone
- From 2026-11-16 on: no file opened

## stock_daily

- Files: 6762, 2000-01-03 to 2026-11-19; not opened: 4
- Sessions of the calendar with no file: none
- Files on days that are not sessions: none
- In the sample: 18313329 bars of 14120 symbols over 2733 sessions

### Schemas

From the footers of every file opened.

| files | first | last | schema |
|---|---|---|---|
| 6597 | 2000-01-03 | 2026-03-26 | timestamp timestamp[us], symbol string, asset_type string, open double, high double, low double, close double, volume double |
| 161 | 2026-03-27 | 2026-11-13 | date date32[day], symbol string, asset_type string, open double, high double, low double, close double, volume double |

### Symbols per session, by year

From the footers' row counts.

| year | sessions | fewest | mean | most |
|---|---|---|---|---|
| 2000 | 252 | 1597 | 2704 | 2878 |
| 2001 | 248 | 2784 | 2868 | 3001 |
| 2002 | 252 | 2837 | 3053 | 3253 |
| 2003 | 252 | 3151 | 3302 | 3539 |
| 2004 | 252 | 3489 | 3660 | 3856 |
| 2005 | 252 | 3782 | 4002 | 4225 |
| 2006 | 251 | 4184 | 4335 | 4582 |
| 2007 | 251 | 4617 | 5015 | 5402 |
| 2008 | 253 | 5256 | 5394 | 5561 |
| 2009 | 252 | 5345 | 5458 | 5612 |
| 2010 | 252 | 5468 | 5617 | 5756 |
| 2011 | 252 | 5535 | 5748 | 5887 |
| 2012 | 250 | 5606 | 5814 | 5942 |
| 2013 | 252 | 5825 | 5979 | 6132 |
| 2014 | 252 | 6064 | 6186 | 6307 |
| 2015 | 252 | 6114 | 6257 | 6346 |
| 2016 | 252 | 6027 | 6187 | 6291 |
| 2017 | 251 | 5995 | 6124 | 6196 |
| 2018 | 251 | 6078 | 6186 | 6302 |
| 2019 | 252 | 6127 | 6235 | 6317 |
| 2020 | 253 | 6210 | 6431 | 6894 |
| 2021 | 252 | 6878 | 7385 | 7687 |
| 2022 | 251 | 7156 | 7539 | 7800 |
| 2023 | 250 | 6783 | 7142 | 7432 |
| 2024 | 252 | 6730 | 6876 | 7026 |
| 2025 | 250 | 6730 | 6873 | 7148 |
| 2026 | 219 | 6577 | 6741 | 6978 |

### Symbols with the delisted suffix

A symbol is counted in each year it has a bar. The suffix is the archive's knowledge at the download, so these shares are what a later reader knows, not what was known in the year.

| year | symbols | suffixed | symbol_days | suffixed_days | share_of_symbols | share_of_symbol_days |
|---|---|---|---|---|---|---|
| 2016 | 6820 | 3597 | 1559193 | 789029 | 0.5274 | 0.5060 |
| 2017 | 6791 | 3359 | 1537169 | 725821 | 0.4946 | 0.4722 |
| 2018 | 6832 | 3168 | 1552593 | 681643 | 0.4637 | 0.4390 |
| 2019 | 6919 | 2976 | 1571127 | 630570 | 0.4301 | 0.4013 |
| 2020 | 7421 | 3139 | 1627115 | 611705 | 0.4230 | 0.3759 |
| 2021 | 8761 | 3802 | 1860997 | 718579 | 0.4340 | 0.3861 |
| 2022 | 8548 | 3279 | 1892365 | 631137 | 0.3836 | 0.3335 |
| 2023 | 8255 | 2697 | 1785505 | 467662 | 0.3267 | 0.2619 |
| 2024 | 8046 | 1983 | 1732705 | 318338 | 0.2465 | 0.1837 |
| 2025 | 8128 | 1329 | 1718251 | 188098 | 0.1635 | 0.1095 |
| 2026 | 7806 | 566 | 1476309 | 47801 | 0.0725 | 0.0324 |

### Bars that cannot be right

A bar may be counted in several columns.

| year | bars | price_missing | price_not_positive | high_below_low | open_outside_range | close_outside_range | volume_zero | volume_missing_or_negative |
|---|---|---|---|---|---|---|---|---|
| 2016 | 1559193 | 0 | 0 | 0 | 0 | 0 | 435 | 0 |
| 2017 | 1537169 | 0 | 0 | 0 | 0 | 0 | 620 | 0 |
| 2018 | 1552593 | 0 | 0 | 0 | 0 | 0 | 385 | 0 |
| 2019 | 1571127 | 0 | 0 | 0 | 0 | 0 | 438 | 0 |
| 2020 | 1627115 | 0 | 0 | 0 | 0 | 0 | 644 | 0 |
| 2021 | 1860997 | 0 | 0 | 0 | 5 | 0 | 719 | 0 |
| 2022 | 1892365 | 0 | 0 | 0 | 0 | 0 | 588 | 0 |
| 2023 | 1785505 | 0 | 0 | 0 | 65 | 2 | 714 | 0 |
| 2024 | 1732705 | 0 | 0 | 0 | 85 | 2 | 349 | 0 |
| 2025 | 1718251 | 0 | 0 | 0 | 0 | 0 | 151 | 0 |
| 2026 | 1476309 | 0 | 0 | 0 | 0 | 0 | 155 | 0 |

### Moves the size of a split

The move from a symbol's close to its next bar's open, where both are positive. It counts as the size of a split when within 3% of a ratio or its inverse. Prices here are already adjusted for splits, so these are candidates for a split that was not applied, or was applied twice, among moves that happened to be that size.

5936 of 18299209 moves, in 1686 symbols.

| ratio | falls | rises |
|---|---|---|
| 2 | 1965 | 1978 |
| 3 | 437 | 391 |
| 4 | 252 | 179 |
| 5 | 208 | 146 |
| 10 | 162 | 119 |
| 20 | 51 | 48 |

| year | moves | falls | rises | symbols |
|---|---|---|---|---|
| 2016 | 1552373 | 99 | 120 | 70 |
| 2017 | 1536710 | 54 | 71 | 63 |
| 2018 | 1552068 | 111 | 80 | 81 |
| 2019 | 1570613 | 125 | 129 | 126 |
| 2020 | 1626176 | 135 | 195 | 196 |
| 2021 | 1859244 | 65 | 78 | 104 |
| 2022 | 1891742 | 449 | 292 | 346 |
| 2023 | 1785024 | 382 | 425 | 422 |
| 2024 | 1732099 | 561 | 541 | 453 |
| 2025 | 1717370 | 569 | 493 | 391 |
| 2026 | 1475790 | 525 | 437 | 327 |

### Symbols that vanish and reappear

A stretch of sessions with no bar between two bars of one symbol, the suffix being part of the symbol. By year, an absence is counted in the year of the last bar before it.

331895 absences in 6039 of 14120 symbols.

| sessions_absent | absences | symbols |
|---|---|---|
| 1 | 193465 | 5831 |
| 2 to 5 | 113816 | 4375 |
| 6 to 20 | 21791 | 2525 |
| 21 to 250 | 2709 | 935 |
| over 250 | 114 | 111 |

| year | absences | symbols |
|---|---|---|
| 2016 | 22904 | 1283 |
| 2017 | 20739 | 1207 |
| 2018 | 21276 | 1241 |
| 2019 | 22623 | 1250 |
| 2020 | 18539 | 1256 |
| 2021 | 23632 | 1629 |
| 2022 | 50581 | 2092 |
| 2023 | 45307 | 2025 |
| 2024 | 39519 | 1974 |
| 2025 | 34139 | 1899 |
| 2026 | 32636 | 1734 |

## etf_daily

- Files: 6762, 2000-01-03 to 2026-11-19; not opened: 4
- Sessions of the calendar with no file: none
- Files on days that are not sessions: none
- In the sample: 7765635 bars of 7617 symbols over 2733 sessions

### Schemas

From the footers of every file opened.

| files | first | last | schema |
|---|---|---|---|
| 6597 | 2000-01-03 | 2026-03-26 | timestamp timestamp[us], symbol string, asset_type string, open double, high double, low double, close double, volume double |
| 161 | 2026-03-27 | 2026-11-13 | date date32[day], symbol string, asset_type string, open double, high double, low double, close double, volume double |

### Symbols per session, by year

From the footers' row counts.

| year | sessions | fewest | mean | most |
|---|---|---|---|---|
| 2000 | 252 | 46 | 67 | 95 |
| 2001 | 248 | 91 | 102 | 119 |
| 2002 | 252 | 110 | 121 | 129 |
| 2003 | 252 | 114 | 127 | 134 |
| 2004 | 252 | 124 | 144 | 157 |
| 2005 | 252 | 157 | 179 | 208 |
| 2006 | 251 | 205 | 258 | 323 |
| 2007 | 251 | 321 | 417 | 499 |
| 2008 | 253 | 493 | 554 | 614 |
| 2009 | 252 | 605 | 653 | 714 |
| 2010 | 252 | 712 | 777 | 850 |
| 2011 | 252 | 838 | 904 | 965 |
| 2012 | 250 | 942 | 1008 | 1080 |
| 2013 | 252 | 1050 | 1114 | 1194 |
| 2014 | 252 | 1169 | 1243 | 1337 |
| 2015 | 252 | 1313 | 1382 | 1491 |
| 2016 | 252 | 1434 | 1563 | 1707 |
| 2017 | 251 | 1632 | 1744 | 1858 |
| 2018 | 251 | 1825 | 1906 | 2139 |
| 2019 | 252 | 2125 | 2188 | 2265 |
| 2020 | 253 | 2222 | 2276 | 2336 |
| 2021 | 252 | 2346 | 2531 | 2748 |
| 2022 | 251 | 2749 | 2920 | 3066 |
| 2023 | 250 | 3062 | 3178 | 3366 |
| 2024 | 252 | 3366 | 3600 | 3923 |
| 2025 | 250 | 3937 | 4355 | 4871 |
| 2026 | 219 | 4877 | 5329 | 5807 |

### Symbols with the delisted suffix

A symbol is counted in each year it has a bar. The suffix is the archive's knowledge at the download, so these shares are what a later reader knows, not what was known in the year.

| year | symbols | suffixed | symbol_days | suffixed_days | share_of_symbols | share_of_symbol_days |
|---|---|---|---|---|---|---|
| 2016 | 1879 | 0 | 393861 | 0 | 0.0000 | 0.0000 |
| 2017 | 2130 | 0 | 437782 | 0 | 0.0000 | 0.0000 |
| 2018 | 2285 | 0 | 478318 | 0 | 0.0000 | 0.0000 |
| 2019 | 2404 | 0 | 551394 | 0 | 0.0000 | 0.0000 |
| 2020 | 2603 | 0 | 575744 | 0 | 0.0000 | 0.0000 |
| 2021 | 2838 | 0 | 637878 | 0 | 0.0000 | 0.0000 |
| 2022 | 3199 | 0 | 732972 | 0 | 0.0000 | 0.0000 |
| 2023 | 3610 | 0 | 794438 | 0 | 0.0000 | 0.0000 |
| 2024 | 4108 | 0 | 907326 | 0 | 0.0000 | 0.0000 |
| 2025 | 5094 | 0 | 1088860 | 0 | 0.0000 | 0.0000 |
| 2026 | 6126 | 0 | 1167062 | 0 | 0.0000 | 0.0000 |

### Bars that cannot be right

A bar may be counted in several columns.

| year | bars | price_missing | price_not_positive | high_below_low | open_outside_range | close_outside_range | volume_zero | volume_missing_or_negative |
|---|---|---|---|---|---|---|---|---|
| 2016 | 393861 | 0 | 0 | 0 | 0 | 0 | 4679 | 0 |
| 2017 | 437782 | 0 | 0 | 0 | 0 | 0 | 8980 | 0 |
| 2018 | 478318 | 0 | 0 | 0 | 0 | 0 | 9102 | 0 |
| 2019 | 551394 | 0 | 0 | 0 | 0 | 0 | 24625 | 0 |
| 2020 | 575744 | 0 | 0 | 0 | 0 | 0 | 13887 | 0 |
| 2021 | 637878 | 0 | 0 | 0 | 0 | 0 | 10606 | 0 |
| 2022 | 732972 | 0 | 0 | 0 | 1 | 0 | 21517 | 0 |
| 2023 | 794438 | 0 | 0 | 0 | 1 | 0 | 26291 | 0 |
| 2024 | 907326 | 0 | 0 | 0 | 0 | 0 | 20468 | 0 |
| 2025 | 1088860 | 0 | 0 | 0 | 0 | 0 | 20124 | 0 |
| 2026 | 1167062 | 0 | 0 | 0 | 0 | 0 | 3535 | 0 |

### Moves the size of a split

The move from a symbol's close to its next bar's open, where both are positive. It counts as the size of a split when within 3% of a ratio or its inverse. Prices here are already adjusted for splits, so these are candidates for a split that was not applied, or was applied twice, among moves that happened to be that size.

38 of 7758018 moves, in 19 symbols.

| ratio | falls | rises |
|---|---|---|
| 2 | 15 | 10 |
| 3 | 5 | 0 |
| 4 | 5 | 2 |
| 5 | 0 | 1 |
| 10 | 0 | 0 |
| 20 | 0 | 0 |

| year | moves | falls | rises | symbols |
|---|---|---|---|---|
| 2016 | 391982 | 4 | 1 | 5 |
| 2017 | 437513 | 1 | 0 | 1 |
| 2018 | 478033 | 1 | 0 | 1 |
| 2019 | 551140 | 0 | 0 | 0 |
| 2020 | 575426 | 2 | 0 | 1 |
| 2021 | 637404 | 0 | 1 | 1 |
| 2022 | 732540 | 1 | 0 | 1 |
| 2023 | 793894 | 1 | 2 | 2 |
| 2024 | 906584 | 3 | 2 | 3 |
| 2025 | 1087692 | 4 | 3 | 3 |
| 2026 | 1165810 | 8 | 4 | 11 |

### Symbols that vanish and reappear

A stretch of sessions with no bar between two bars of one symbol, the suffix being part of the symbol. By year, an absence is counted in the year of the last bar before it.

65009 absences in 2045 of 7617 symbols.

| sessions_absent | absences | symbols |
|---|---|---|
| 1 | 37749 | 1936 |
| 2 to 5 | 22377 | 1374 |
| 6 to 20 | 4324 | 670 |
| 21 to 250 | 556 | 212 |
| over 250 | 3 | 3 |

| year | absences | symbols |
|---|---|---|
| 2016 | 18268 | 768 |
| 2017 | 16833 | 835 |
| 2018 | 16206 | 874 |
| 2019 | 2650 | 183 |
| 2020 | 3441 | 205 |
| 2021 | 2858 | 182 |
| 2022 | 1208 | 274 |
| 2023 | 220 | 30 |
| 2024 | 193 | 46 |
| 2025 | 92 | 30 |
| 2026 | 3040 | 500 |
