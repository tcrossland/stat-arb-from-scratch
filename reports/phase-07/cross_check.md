# Phase 7 cross-check: MarketParquet against Alpaca

Statistics only: no price, volume or return of any symbol on any date.

## Snapshots

- Alpaca: snapshot 2026-11-16, digest a28ff7224e60, the phase 0 tables built from it
- MarketParquet: snapshot 2026-11-20, digest dae4a405cb5b, basis split_adjusted
- Days compared: from 2016-01-01 through 2026-11-15, the last day the backtest runners read

## Names and rows

- Tickers: 515 in Alpaca's tables, 515 of them in MarketParquet's files
- Symbol-days: 1346362 in both, 2876 in Alpaca alone, 6513 in MarketParquet alone

Tickers with at least 5 rows in one source alone (`first` is Alpaca, `second` MarketParquet). Alpaca's rows are after its cleaning, which drops a ticker's bars before its configured listing.

| ticker | held | rows | first | last |
|---|---|---|---|---|
| TKO | first | 1935 | 2016-01-04 | 2023-09-11 |
| COHR | first | 851 | 2016-01-04 | 2019-05-21 |
| AVGO | first | 20 | 2016-01-04 | 2016-02-01 |
| CEG | first | 20 | 2022-02-02 | 2022-03-02 |
| HONA | first | 9 | 2026-06-15 | 2026-06-26 |
| SNDK | first | 6 | 2025-02-13 | 2025-02-21 |
| SKYD | second | 2412 | 2016-01-04 | 2025-08-06 |
| HWM | second | 828 | 2016-11-01 | 2020-03-31 |
| FOX | second | 806 | 2016-01-04 | 2019-03-18 |
| EVRG | second | 609 | 2016-01-04 | 2018-06-04 |
| APTV | second | 474 | 2016-01-04 | 2017-11-16 |
| BKR | second | 378 | 2016-01-04 | 2017-07-03 |
| VRT | second | 364 | 2018-07-30 | 2020-02-07 |
| SMCI | second | 349 | 2018-08-23 | 2020-01-13 |
| JCI | second | 170 | 2016-01-04 | 2016-09-02 |
| VICI | second | 69 | 2017-10-18 | 2018-01-31 |
| FOXA | second | 14 | 2019-02-27 | 2019-03-18 |
| CARR | second | 10 | 2020-03-20 | 2020-04-02 |
| OTIS | second | 10 | 2020-03-20 | 2020-04-02 |
| DOW | second | 8 | 2019-03-21 | 2019-04-01 |

With fewer: 33 tickers in Alpaca alone, 8 in MarketParquet alone.

## Closes and volumes on one split basis

Alpaca's bars are divided by every later split, MarketParquet's are as served. A close agrees within 0.0001 of the other, a volume within 0.01, both relative. The volume ratio is MarketParquet's over Alpaca's.

| year | symbol_days | closes_agree | volumes_agree | median_volume_ratio |
|---|---|---|---|---|
| 2016 | 116991 | 93.152% | 1.318% | 0.9400 |
| 2017 | 118023 | 93.380% | 1.022% | 0.9282 |
| 2018 | 119309 | 93.388% | 1.133% | 0.9181 |
| 2019 | 121963 | 93.851% | 0.797% | 0.9079 |
| 2020 | 124375 | 94.004% | 1.187% | 0.9068 |
| 2021 | 125896 | 95.596% | 2.920% | 0.8950 |
| 2022 | 125971 | 97.168% | 12.456% | 0.8984 |
| 2023 | 125889 | 97.557% | 85.305% | 1.0000 |
| 2024 | 127961 | 98.457% | 57.447% | 0.9998 |
| 2025 | 127609 | 99.283% | 76.541% | 0.9998 |
| 2026 | 112375 | 99.729% | 98.420% | 0.9998 |

## Price returns, by what went ex

Each source's close over its previous close, where both have the same previous day; Alpaca's on its split-adjusted closes, so neither holds a dividend. They agree within 0.0001 and are apart beyond 0.01, both absolute. The kind is what Alpaca's actions say went ex that day.

| went_ex | returns | agree | apart |
|---|---|---|---|
| none | 1328996 | 99.153% | 374 |
| cash | 16729 | 98.763% | 39 |
| split | 108 | 97.222% | 2 |

## Where the split-adjusted series part

Returns apart by more than 0.01, by year and by what went ex in Alpaca's actions.

| year | returns | none | cash | split | tickers |
|---|---|---|---|---|---|
| 2016 | 116524 | 4 | 2 | 1 | 5 |
| 2017 | 118013 | 1 | 1 | 0 | 2 |
| 2018 | 119300 | 6 | 2 | 0 | 4 |
| 2019 | 121952 | 16 | 2 | 0 | 10 |
| 2020 | 124362 | 342 | 10 | 0 | 135 |
| 2021 | 125891 | 3 | 5 | 0 | 7 |
| 2022 | 125969 | 0 | 4 | 0 | 4 |
| 2023 | 125887 | 0 | 3 | 0 | 3 |
| 2024 | 127957 | 0 | 5 | 0 | 5 |
| 2025 | 127606 | 0 | 4 | 0 | 4 |
| 2026 | 112372 | 2 | 1 | 1 | 3 |

The 10 days on which the most tickers part:

| date | tickers |
|---|---|
| 2020-03-13 | 68 |
| 2020-03-12 | 65 |
| 2020-03-18 | 38 |
| 2020-03-19 | 38 |
| 2020-03-10 | 36 |
| 2020-03-09 | 33 |
| 2020-03-17 | 27 |
| 2020-03-16 | 26 |
| 2019-08-13 | 6 |
| 2019-08-12 | 5 |

A ticker is on another basis where the centred 11-day median of the two closes' ratio is further than 0.001 from 1: MarketParquet's adjustment holds something Alpaca's splits do not, or lacks one of them.

| year | symbol_days | tickers |
|---|---|---|
| 2016 | 7385 | 31 |
| 2017 | 7039 | 29 |
| 2018 | 6803 | 28 |
| 2019 | 6245 | 26 |
| 2020 | 5891 | 26 |
| 2021 | 5139 | 23 |
| 2022 | 3453 | 17 |
| 2023 | 3061 | 13 |
| 2024 | 1943 | 11 |
| 2025 | 875 | 6 |
| 2026 | 223 | 2 |

34 tickers, with the days each is on another basis:

| ticker | days | first | last |
|---|---|---|---|
| HON | 2635 | 2016-01-04 | 2026-06-26 |
| FDX | 2616 | 2016-01-04 | 2026-05-29 |
| DD | 2472 | 2016-01-04 | 2025-10-31 |
| WDC | 2298 | 2016-01-04 | 2025-02-21 |
| LEN | 2275 | 2016-01-04 | 2025-01-17 |
| FTV | 2258 | 2016-07-06 | 2025-06-27 |
| J | 2199 | 2016-01-04 | 2024-09-27 |
| ILMN | 2132 | 2016-01-04 | 2024-06-24 |
| GE | 2074 | 2016-01-04 | 2024-04-01 |
| MMM | 2073 | 2016-01-04 | 2024-03-28 |
| FLEX | 2013 | 2016-01-04 | 2024-01-02 |
| DHR | 1949 | 2016-01-04 | 2023-09-29 |
| LH | 1886 | 2016-01-04 | 2023-06-30 |
| T | 1579 | 2016-01-04 | 2022-04-08 |
| BDX | 1573 | 2016-01-04 | 2022-03-31 |
| ZBH | 1550 | 2016-01-04 | 2022-02-28 |
| EXC | 1532 | 2016-01-04 | 2022-02-01 |
| O | 1478 | 2016-01-04 | 2021-11-12 |
| IBM | 1471 | 2016-01-04 | 2021-11-03 |
| IP | 1447 | 2016-01-04 | 2021-09-30 |
| DTE | 1383 | 2016-01-04 | 2021-06-30 |
| MRK | 1363 | 2016-01-04 | 2021-06-02 |
| PFE | 1228 | 2016-01-04 | 2020-11-16 |
| RTX | 1070 | 2016-01-04 | 2020-04-02 |
| ECHO | 928 | 2016-01-04 | 2019-09-10 |
| CBOE | 775 | 2016-01-04 | 2021-03-26 |
| EQT | 722 | 2016-01-04 | 2018-11-12 |
| PNR | 585 | 2016-01-04 | 2018-04-30 |
| DOC | 210 | 2016-01-04 | 2016-10-31 |
| YUM | 210 | 2016-01-04 | 2016-10-31 |
| OXY | 36 | 2016-01-04 | 2016-02-24 |
| IBKR | 24 | 2019-05-15 | 2019-07-09 |
| APTV | 11 | 2017-11-17 | 2017-12-04 |
| SPY | 2 | 2020-03-13 | 2020-03-16 |

## Cash days

Alpaca's days with cash going ex and no split, by the size of the cash as a share of the price (its total return less its price return). MarketParquet's return is Alpaca's price return within 0.0001, so the cash is not in it, or else it is nearer Alpaca's total return, so the cash is folded into its adjustment, or nearer the price return. Alpaca's cash includes spin-offs valued as cash (decision record 0004).

| cash_over_price | days | price_return | nearer_total | nearer_price |
|---|---|---|---|---|
| up to 2% | 16569 | 16395 | 21 | 153 |
| 2% to 5% | 113 | 104 | 7 | 2 |
| over 5% | 47 | 23 | 22 | 2 |

## What the returns lack

Pooled over symbol-days by year, as a share of Alpaca's squared total returns: what Alpaca's own price return lacks, which is its dividends and other cash, and what MarketParquet's return lacks, which is that less what it folds in, plus every other difference between the sources.

| year | first_price_return_lacks | second_return_lacks | correlation |
|---|---|---|---|
| 2016 | 0.936% | 0.726% | 0.9964 |
| 2017 | 0.463% | 0.329% | 0.9984 |
| 2018 | 2.890% | 2.016% | 0.9901 |
| 2019 | 0.357% | 2.668% | 0.9869 |
| 2020 | 0.343% | 0.943% | 0.9953 |
| 2021 | 0.219% | 0.145% | 0.9993 |
| 2022 | 0.307% | 0.105% | 0.9995 |
| 2023 | 0.413% | 0.207% | 0.9990 |
| 2024 | 0.552% | 0.172% | 0.9991 |
| 2025 | 0.840% | 0.134% | 0.9993 |
| 2026 | 0.623% | 0.277% | 0.9986 |

## Whether the two closes are the same close

The share of closes further from the ticker's basis than each band, relative, so a different basis does not count and a different print does.

Stocks:

| year | symbol_days | over_1e-06 | over_0.0001 | over_0.001 | over_0.01 |
|---|---|---|---|---|---|
| 2016 | 114221 | 3.660% | 0.488% | 0.024% | 0.002% |
| 2017 | 115262 | 2.912% | 0.416% | 0.021% | 0.000% |
| 2018 | 116413 | 2.604% | 0.553% | 0.070% | 0.003% |
| 2019 | 118939 | 2.732% | 0.798% | 0.304% | 0.008% |
| 2020 | 121339 | 2.647% | 0.982% | 0.330% | 0.133% |
| 2021 | 122872 | 1.030% | 0.190% | 0.039% | 0.001% |
| 2022 | 122959 | 0.511% | 0.080% | 0.018% | 0.000% |
| 2023 | 122889 | 0.373% | 0.013% | 0.000% | 0.000% |
| 2024 | 124937 | 0.143% | 0.026% | 0.016% | 0.000% |
| 2025 | 124609 | 0.113% | 0.032% | 0.002% | 0.000% |
| 2026 | 109747 | 0.109% | 0.073% | 0.005% | 0.001% |

ETFs:

| year | symbol_days | over_1e-06 | over_0.0001 | over_0.001 | over_0.01 |
|---|---|---|---|---|---|
| 2016 | 2770 | 9.783% | 8.448% | 0.903% | 0.000% |
| 2017 | 2761 | 21.297% | 16.878% | 0.398% | 0.000% |
| 2018 | 2896 | 24.827% | 22.030% | 0.656% | 0.000% |
| 2019 | 3024 | 17.030% | 14.153% | 0.992% | 0.000% |
| 2020 | 3036 | 18.347% | 15.415% | 2.372% | 0.494% |
| 2021 | 3024 | 7.077% | 5.688% | 0.331% | 0.000% |
| 2022 | 3012 | 0.930% | 0.664% | 0.000% | 0.000% |
| 2023 | 3000 | 0.000% | 0.000% | 0.000% | 0.000% |
| 2024 | 3024 | 0.000% | 0.000% | 0.000% | 0.000% |
| 2025 | 3000 | 0.000% | 0.000% | 0.000% | 0.000% |
| 2026 | 2628 | 0.000% | 0.000% | 0.000% | 0.000% |

## The headline on this source

The phase 2 headline (residual n=1, k=1, fill open_t1) on the same universe and sectors, with MarketParquet's prices, its price returns in place of total returns, and Model A refitted on them. It repeats a logged path to size the sources' difference: it is not logged and adds no trial.

Alpaca's rerun gives the logged metrics exactly at every cost level: yes.

- Stocks with residuals: 500 on Alpaca, 500 on MarketParquet
- Member-days from the first signal date: 744247; with a residual: 741883 on Alpaca, 742234 on MarketParquet
- Stock-days with a residual on one source alone: 2867 on Alpaca, 6701 on MarketParquet

At 0 bps one way:

| metric | logged | alpaca_rerun | marketparquet | difference |
|---|---|---|---|---|
| days | 2480 | 2480 | 2480 | 0 |
| sharpe | 0.3221 | 0.3221 | 0.3083 | -0.0139 |
| gross_sharpe | 0.3476 | 0.3476 | 0.3340 | -0.0136 |
| ann_return | 0.0317 | 0.0317 | 0.0299 | -0.0017 |
| ann_gross_return | 0.0342 | 0.0342 | 0.0324 | -0.0017 |
| ann_vol | 0.0983 | 0.0983 | 0.0971 | -0.0012 |
| max_drawdown | -0.2837 | -0.2837 | -0.2791 | 0.0047 |
| turnover | 1.7028 | 1.7028 | 1.7039 | 0.0011 |
| break_even_bps | 0.7380 | 0.7380 | 0.6971 | -0.0409 |
| ann_long_pnl | 0.1312 | 0.1312 | 0.1215 | -0.0096 |
| ann_short_pnl | -0.0970 | -0.0970 | -0.0891 | 0.0079 |
| position_hit_rate | 0.5034 | 0.5034 | 0.5028 | -0.0007 |
| day_hit_rate | 0.5137 | 0.5137 | 0.5117 | -0.0020 |
| missing_returns | 2 | 2 | 2 | 0 |

At 5 bps one way:

| metric | logged | alpaca_rerun | marketparquet | difference |
|---|---|---|---|---|
| days | 2480 | 2480 | 2480 | 0 |
| sharpe | -1.8696 | -1.8696 | -1.9122 | -0.0426 |
| gross_sharpe | 0.3476 | 0.3476 | 0.3340 | -0.0136 |
| ann_return | -0.1829 | -0.1829 | -0.1848 | -0.0019 |
| ann_gross_return | 0.0342 | 0.0342 | 0.0324 | -0.0017 |
| ann_vol | 0.0978 | 0.0978 | 0.0966 | -0.0012 |
| max_drawdown | -1.8143 | -1.8143 | -1.8337 | -0.0193 |
| turnover | 1.7028 | 1.7028 | 1.7039 | 0.0011 |
| break_even_bps | 0.7380 | 0.7380 | 0.6971 | -0.0409 |
| ann_long_pnl | 0.1312 | 0.1312 | 0.1215 | -0.0096 |
| ann_short_pnl | -0.0970 | -0.0970 | -0.0891 | 0.0079 |
| position_hit_rate | 0.5034 | 0.5034 | 0.5028 | -0.0007 |
| day_hit_rate | 0.4262 | 0.4262 | 0.4242 | -0.0020 |
| missing_returns | 2 | 2 | 2 | 0 |

Daily returns of the two runs at 5 bps over 2480 days: correlation 0.9910 net, 0.9910 gross.

| leg | days | mean_share_in_common |
|---|---|---|
| long | 2481 | 0.9648 |
| short | 2481 | 0.9729 |

By year at 5 bps:

| year | alpaca_net_return | marketparquet_net_return | alpaca_net_sharpe | marketparquet_net_sharpe |
|---|---|---|---|---|
| 2017 | -0.1530 | -0.1837 | -3.5530 | -4.2581 |
| 2018 | -0.0838 | -0.0773 | -1.4650 | -1.3673 |
| 2019 | -0.2778 | -0.2702 | -5.1090 | -5.0883 |
| 2020 | -0.1167 | -0.1329 | -0.7348 | -0.8649 |
| 2021 | -0.2342 | -0.2474 | -2.8840 | -3.0483 |
| 2022 | -0.2931 | -0.2780 | -2.6647 | -2.5179 |
| 2023 | -0.0681 | -0.0590 | -0.9534 | -0.8228 |
| 2024 | -0.2053 | -0.2095 | -2.7874 | -2.8329 |
| 2025 | -0.2661 | -0.2627 | -2.7425 | -2.8023 |
| 2026 | -0.1016 | -0.0976 | -0.7311 | -0.7021 |
