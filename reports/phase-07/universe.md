# Phase 7 universe report: `listed`

Statistics only: no price, volume or return of any symbol on any date.

## Snapshot and rules

- MarketParquet snapshot 2026-11-20, digest dae4a405cb5b; bars read from 2016-01-01 to before 2026-11-16
- Trading days: 2733 (2016-01-04 to 2026-11-13)
- Bars kept: 18340240 of 14132 symbols; returns: 18326108
- Bars dropped: 5265 in 319 symbols

Bars dropped by the rules of decision record 0009, by year. A bar with zero volume is counted there whatever else is wrong with it.

| year | not_a_trading_day | zero_volume | contradicts_itself |
|---|---|---|---|
| 2016 | 0 | 435 | 0 |
| 2017 | 0 | 620 | 0 |
| 2018 | 0 | 385 | 0 |
| 2019 | 0 | 438 | 0 |
| 2020 | 0 | 644 | 0 |
| 2021 | 0 | 719 | 5 |
| 2022 | 0 | 588 | 0 |
| 2023 | 0 | 714 | 16 |
| 2024 | 0 | 349 | 46 |
| 2025 | 0 | 151 | 0 |
| 2026 | 0 | 155 | 0 |

## Universe

The 300 symbols of the stock dataset with the highest median dollar volume over the 60 sessions to each month end, of those with bars on at least 54 of them, held from the next session. Dollar volume is unchanged by split adjustment. No price floor is applied: on adjusted prices it would look ahead.

- Effective from 2016-04-01 to 2026-11-13
- Rebalances: 128
- Symbols entering per rebalance: mean 13.9, most 21
- Symbols that were ever members: 820

## What the ranking let in

Member-days by the form of the symbol and by whether it carries the delisted suffix. The form shows little of the kind of security: share classes of common stock take every form. The suffix is what the archive knew at the download, counted here and read by no rule.

| year | member_days | symbols | one_to_four_letters | five_letters | a_letter_after_a_dot | other | suffixed |
|---|---|---|---|---|---|---|---|
| 2016 | 57300 | 374 | 98.77% | 0.78% | 0.45% | 0.00% | 17.36% |
| 2017 | 75300 | 397 | 99.00% | 0.67% | 0.33% | 0.00% | 13.90% |
| 2018 | 75300 | 399 | 99.00% | 0.67% | 0.33% | 0.00% | 10.60% |
| 2019 | 75600 | 399 | 99.00% | 0.67% | 0.33% | 0.00% | 8.44% |
| 2020 | 75900 | 392 | 98.95% | 0.67% | 0.39% | 0.00% | 5.76% |
| 2021 | 75600 | 410 | 98.55% | 0.86% | 0.59% | 0.00% | 4.44% |
| 2022 | 75300 | 385 | 98.67% | 0.67% | 0.67% | 0.00% | 3.75% |
| 2023 | 75000 | 378 | 98.67% | 0.67% | 0.67% | 0.00% | 3.25% |
| 2024 | 75600 | 376 | 98.67% | 0.67% | 0.67% | 0.00% | 1.82% |
| 2025 | 75000 | 399 | 98.81% | 0.67% | 0.53% | 0.00% | 1.09% |
| 2026 | 65700 | 397 | 99.00% | 0.67% | 0.33% | 0.00% | 0.73% |

## Near-copies

At each month end, pairs of members whose returns over the ranking's window correlate above 0.98: two share classes of one company, or one company the archive holds under two symbols. Only returns up to the month end are read. They are left in (decision record 0009, rule 9).

| year | rebalances | mean_pairs | most_pairs | mean_members |
|---|---|---|---|---|
| 2016 | 10 | 6.80 | 8 | 13.60 |
| 2017 | 12 | 6.25 | 9 | 12.50 |
| 2018 | 12 | 4.83 | 6 | 9.67 |
| 2019 | 12 | 3.92 | 5 | 7.83 |
| 2020 | 12 | 2.75 | 5 | 5.50 |
| 2021 | 12 | 2.58 | 5 | 5.17 |
| 2022 | 12 | 2.17 | 3 | 4.33 |
| 2023 | 12 | 1.25 | 2 | 2.50 |
| 2024 | 12 | 1.50 | 3 | 3.00 |
| 2025 | 12 | 1.50 | 2 | 3.00 |
| 2026 | 10 | 1.10 | 2 | 2.20 |

## Against the existing universe

Of the member-days of the universe built from today's S&P 500 on Alpaca's prices, the share whose ticker is a member here on the same day.

| year | member_days | also_here |
|---|---|---|
| 2016 | 57300 | 70.59% |
| 2017 | 75300 | 74.64% |
| 2018 | 75300 | 78.18% |
| 2019 | 75600 | 80.87% |
| 2020 | 75900 | 79.13% |
| 2021 | 75600 | 70.46% |
| 2022 | 75300 | 76.75% |
| 2023 | 75000 | 81.80% |
| 2024 | 75600 | 83.76% |
| 2025 | 75000 | 79.94% |
| 2026 | 65700 | 79.00% |
