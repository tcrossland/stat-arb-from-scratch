# 0009: Rules for MarketParquet's data

**Date:** 2026-11-21
**Status:** accepted

## Context

[Decision record 0008](0008-marketparquet-archive-as-a-paid-price-source.md) makes MarketParquet's archive the second price source and leaves five questions to a record of rules, each to be settled by measuring first: unadjusted prices, dividends, spin-offs, delisting and kinds of security. This is that record, as [decision record 0004](0004-rules-for-alpacas-data.md) is for Alpaca. It rests on the [quality report](../../reports/phase-07/data_quality.md) and the [cross-check](../../reports/phase-07/cross_check.md), which hold the numbers, and on measurements of the pinned snapshot made for this record, listed under "What was measured".

The source serves one file per trading day with every symbol's bar, adjusted for splits as of the download. It has no dividends, no table of splits, no kind of security and no permanent identifier. What the reports and the measurements showed:

- **Dividends are absent and spin-offs are folded in only sometimes.** On Alpaca's cash days the source's return is Alpaca's price return almost always. About half of the large distributions among the existing candidates are folded into its adjustment, so its return on those days is close to a total return; the rest are left as traded.
- **A bar means a file row, not always a trade.** Some bars have zero volume, and most of those do not repeat the previous close, so they are not the carried closes Alpaca serves. A few hundred bars have an open or a close outside the day's range, most by more than 1%.
- **A symbol with no trade on a day has no bar.** Over 40% of stock symbols miss at least one session between two bars.
- **The suffix marks a security, not a company.** A company that changed its name keeps one symbol through its history in most cases checked. In others its earlier life is also held under the old symbol, suffixed, as a second series that tracks the first closely without equalling it: several hundred suffixed symbols are near-copies of another symbol's returns, some of them share classes and some a renamed company held twice. Two of a pair can both rank among the 300 most liquid names, a handful of pairs at a time before 2022 and none from 2023.
- **Symbols say little about the kind of security.** Warrants, units and rights carry a fifth letter and preferred shares a series letter after a dot, but share classes of common stock use both forms too. Ranked by dollar volume, almost every one of the 300 most liquid symbols is a plain symbol of one to four letters and the rest are share classes: no warrant, unit, right or preferred share reaches the top 300 on any month end.
- **Alpaca holds the dead names too.** For a seeded sample of 60 suffixed symbols, Alpaca returned daily bars for every one, covering nearly all of the symbol's days for 56, and corporate-action records inside the symbol's life for about half: cash dividends and reverse splits. So unadjusted prices and dividends for delisted names are recoverable from Alpaca's records, at the cost of a second download keyed by this source's symbols and of decision record 0004's hand-checked corrections for thousands of names.

## Decision

1. **Bars are read as served, and a security is its symbol with the suffix.** No symbol is renamed, merged with another or linked to a later one. The suffix stays in the key and out of every decision (decision record 0008, point 8).
2. **A bar with zero volume is dropped,** as rule 1 of decision record 0004 drops Alpaca's: whatever its close is, it is not a traded price of the day.
3. **A bar that contradicts itself is dropped:** an open or a close outside the day's low and high, a high below the low, or a price that is missing or not positive. The symbol has no bar that day.
4. **A day with no bar is a day the symbol did not trade.** Its next return runs from its previous bar and records that bar's date, as the returns table does for Alpaca. Nothing is filled forward.
5. **Returns are price returns:** the close over the symbol's previous close, less one. They hold no dividends. A spin-off is in the return where the source folded it into its adjustment and absent where it did not, and no rule tells the two apart. Every result on this source says so.
6. **No unadjusted price is derived.** Nothing that reads a price level is computed from this source: the per-share commission, the half-tick floor of the spread, and any price floor in a universe rule. Dollar volume, which split adjustment leaves unchanged, is the only level used.
7. **Alpaca's records are not joined to this source's prices in this phase.** The probe shows they could supply splits on their ex-dates and dividends for many delisted names. Doing so is a second source of records per symbol, with its own failures, and the survivorship measurement does not need it: its three universes on this source share one return basis, so the missing cash is in all of them. It goes to the backlog, with the cost model on this universe as its trigger.
8. **The kind of security is not inferred from the symbol.** The stock dataset is the candidate list and the ETF dataset supplies the factor ETFs. Ranking by dollar volume keeps warrants, units, rights and preferred shares out of a universe of 300 without a rule, and a rule on symbol shapes could not tell a preferred series from a share class. What stays in and is not a common share of a US company, such as an American depositary receipt, a real-estate trust or a closed-end fund, is stated in the universe's report and not removed.
9. **Near-copies are left in and counted.** A suffixed symbol whose returns track another symbol's is a share class or a company held twice. Telling them apart needs the whole history and the suffix, both look-ahead. The universe's report counts, for each month end, the members whose trailing returns correlate above a stated level with another member's, so the reader sees how many slots are doubled.
10. **A security's last bar is its last trade.** No final return is assumed in any headline number. The survivorship report states one sensitivity, fixed before any path runs: every name whose bars stop before the sample's end, and whose close fell over its last 21 bars by more than a stated amount, takes a further stated loss on its last bar. The two amounts are set in `config/marketparquet.toml` with the source they come from.
11. **The source does not go behind `PriceSource`.** That protocol's contract requires an adapter to report each split on its ex-date, so that the canonical step can return unadjusted prices, and this source cannot (rule 6). Bars with `split_ratio` 1 on every day would declare a basis they do not meet. The source is read by day through `statarb.data.marketparquet`, and its tables are built by a runner of its own. This amends point 1 of decision record 0008, which put it behind the interface. As first accepted on 2026-11-21 this rule said the opposite; it was corrected the same day, before any code rested on it, when the contract tests were read.

## Consequences

- **Rules 2 and 3 are applied by the build,** never at download time, so a changed rule needs a rebuild and not a new snapshot. The quality report counts the bars each drops.
- **Returns on this source understate total returns** by the dividends, and by each spin-off the source did not fold in. An unfolded spin-off shows as a one-day fall in the parent, which a reversal signal reads as a loser. The cross-check sizes both for the existing candidates; for the wider universe they are unmeasured.
- **Phase 3's cost model cannot run on this source** until rule 7's backlog item is taken up. Results are gross, or net at flat cost levels per dollar traded.
- **The universe is "every listed stock symbol", not "every common share".** Its report says how many members are share classes, near-copies and foreign or fund-like names, as far as the symbol shows it.
- **The survivorship measurement inherits rule 9.** A renamed company held twice counts as one delisted name and one survivor, which makes universe 4 differ from universe 3 by names that never failed. The count in the universe's report bounds it.
- **The delisting sensitivity is a bound, not an estimate.** The source gives no delisting reason, so the rule cannot tell a failure from a merger except by the price path into the last bar.
- **The Alpaca probe is not a snapshot.** It was 60 symbols, seeded, read once on 2026-11-21, and is not reproducible from the raw store. It informs rule 7's backlog item and no result.

## What was measured

On the pinned snapshot, bars from 2016-01-01 to 2026-11-13, for this record. The counts are not yet in a generated report: the universe's report in step 5 of [phase 7](../phases/phase-07/brief.md) carries those that bear on the universe.

- Zero-volume bars, and whether each repeats the previous close.
- Bars with an open or close outside the range, by how far.
- Symbols by shape, with each shape's share of dollar volume and of the 300 most liquid symbols on month ends.
- The share of those 300 slots held by suffixed symbols, by year.
- Known name changes among the existing candidates, by whether the old symbol also appears suffixed.
- Suffixed symbols whose returns correlate above 0.98 with another symbol's over 60 or more common days, and how many such pairs rank in the top 300 together.
- The price path into a suffixed symbol's last bar.
- For 60 suffixed symbols, whether Alpaca's market data API returns bars and corporate actions.
