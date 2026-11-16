# Phase 0 review: Data and universe

Written on 2026-11-16 at the end of the phase. The numbers below are quoted from the generated report, [`reports/phase-00/data_quality.md`](../../../reports/phase-00/data_quality.md), built from the pinned snapshots: Alpaca bars and corporate actions downloaded on 2026-11-16, and Wikipedia revision 1384572480 read the same day.

## What was built

- **`src/statarb/data/`**: the `PriceSource` and `ConstituentSource` protocols, the Alpaca and Wikipedia adapters, raw snapshots with manifests and content digests, the canonical step, cleaning, total returns, the monthly universe, dated sectors, the quality report and the runner `statarb.data.build`. The modules and what each reads and writes are in [the architecture](../../architecture.md); the six tables are in [the data model](../../data-model.md).
- **`statarb.testing.lookahead`**, the look-ahead check later phases will reuse: perturb data after a cut-off and require every output up to it to be unchanged.
- **Decision record 0004**, the eleven rules for Alpaca's data, numbered in the order the build found them, and an amendment to record 0003 with the Wikimedia request policies.
- **Config with sources**: `config/alpaca.toml` (withholding, repeated dividends and corrections, each citing the issuer, its filings, the fund sponsor or the exchange), `config/listing_starts.toml` and `config/sector_changes.toml` (the three structural GICS changes since 2016).
- **Snapshots that cannot drift.** Each snapshot's manifest holds the SHA-256 of every file and a digest over them; config pins the snapshot by date and digest, and the build refuses one whose files changed. Raw snapshots are read-only, kept in one raw store shared by every worktree (`STATARB_RAW`), and backed up outside the repository; everything under `data/derived/` is rebuilt from them.
- **Tests**: the contract suite over every price and constituent adapter, unit tests for every transform that touches dates, the universe look-ahead test, return stability across a later snapshot, an end-to-end build on synthetic snapshots, and tests that check the architecture and data model pages against the code.

## Acceptance criteria

| Criterion | Result |
|---|---|
| A rebuild reproduces the parquet files byte for byte | Met: two rebuilds of the pinned snapshots gave identical SHA-256 for every table and the report; `tests/test_build.py` checks the same on synthetic snapshots. |
| Identical content after a dependency upgrade | Not yet testable: no upgrade has happened. Carried forward. |
| 95% coverage of each ticker's live window, or listed | Met: one ticker is below and listed in the report. |
| No split-day jump for AAPL 2020, NVDA 2021 and 2024 | Met: each split day's absolute return is below 25%, as is every other split day in the report. |
| Universe look-ahead test | Met: `tests/test_universe.py::test_membership_has_no_look_ahead`. |
| Return stability test | Met: `tests/test_build.py::test_a_later_snapshot_leaves_earlier_returns_unchanged` and the contract suite. |
| Both adapters pass the contract suite | Met: `tests/contract/`. |

## What the numbers showed

From [the report](../../../reports/phase-00/data_quality.md):

- **Coverage.** 515 tickers have prices: 503 candidates and 12 ETFs. No ticker has no data and none failed a rule. One ticker is below 95% of its live window, because it traded off-exchange for a period and its zero-volume bars are dropped (decision record 0004, rule 1).
- **Cleaning.** Only listing starts dropped rows: 5,834 rows across seven tickers whose source history began under another security that held the symbol, the SPAC that merged into the company, or stock cancelled in a reorganisation. No row was dropped for a missing or non-positive price, and no bar fell off the trading calendar.
- **Large moves.** 243 daily returns above 25% in absolute value across 120 tickers, 89 of them in 2020. One falls on a day with a split or cash. Of the 109 split days, none is above 25%.
- **Gaps.** 6 returns span more than one trading day, across four tickers.
- **Universe.** 128 monthly rebalances from 2016-03-31. On average 7.7 names of 300 enter at each rebalance (2.6%), at most 12. 451 of the 503 candidates are members at some point; 52 never are.
- **Survivorship.** 175 of the 503 candidates joined the S&P 500 after 2016-01-01.

**Corporate actions the rules do not apply** (rule 5). Counted in the snapshot over the window: one stock dividend, and 186 merger and unit-split records under the candidates' symbols, mostly with the candidate as acquirer. No return above 25% falls on the stock dividend's ex-date or in the three calendar days from any of those effective dates, so none needs a rule now.

**Withholding** (rule 4). Fifteen dividends on the withholding list were checked against the amount the issuer declares: Alpaca's amount was 75% of it on each net date and equal to it on each listed gross date, and after the rule the built amount matches the issuer's, to Alpaca's rounding, in all fifteen.

## How the rules were found

The Alpaca adapter landed with the six rules the API's documentation and record format settle: New York dates, an action query reaching 90 days past the bars' window, splits, cash dividends at face value, other kinds of action left unapplied, and failures reported rather than guessed. Every later rule was added in its own commit and applied to the same pinned snapshot, with the report's numbers before and after in the commit's `Results:` footer (`git log --grep '^Results:'` lists them):

| Rule | What pointed to it |
|---|---|
| 1, zero-volume bars | the report's 928 zero-volume days across seven tickers |
| 4, foreign dividends fail until checked | not a count: the `foreign` flag on Alpaca's records, which does not say whether an amount is net; 32 tickers then failed |
| 4, withholding lists | the 32 failures, each checked against the issuer's declared amounts |
| 7, listing starts | two tickers below 95% coverage once zero-volume bars were dropped, and 20 of the 28 gapped returns on a third |
| 8, spin-offs | one of the two split-day jumps, on a day that was also a spin-off's ex-date |
| 9, name changes | not a count: name-change records in the snapshot linking symbols the build did not read |
| 10, duplicates | not a count: records filed twice double the cash on a day that already has some |
| 11, corrections | not a count, except the last split-day jump (a distribution filed as a reverse split): records checked against issuers' announcements |

The commits give each step's counts and its sources; the episodes worth keeping are below.

## What surprised us

- **Alpaca nets some foreign dividends without saying so.** From 2023 the amounts for some Irish- and Dutch-domiciled issuers are net of withholding tax and others are gross, with the same `foreign` flag on both. The difference is a quarter of each affected dividend, small on one day but systematic across a sector. Rule 4 and the withholding list fix it, and an unlisted foreign dividend fails its ticker rather than passing silently.
- **A zero-volume bar is not a price.** On a day with no trade on the consolidated tape Alpaca returns a bar repeating the last close. Taken as a price, it makes a flat day followed by a jump; rule 1 drops it, which is why one ticker shows low coverage rather than false returns.
- **Histories start before the listing.** A ticker's history can begin under a shell company, a predecessor or when-issued trading with real volume, so no rule on the bars finds it. Each case needs its listing date from the issuer, in `config/listing_starts.toml` (rule 7).
- **The action query filters on the process date, not the ex-date.** An action handled weeks after its ex-date falls outside a query on the bars' window; the query reaches 90 days either side (rule 2).
- **Wikipedia's robots.txt disallows the Action API to generic crawlers**, while API:Etiquette recommends the API with `oldid` for a specific revision. Record 0003 keeps one manual request for the pinned revision and says why.

## Review questions

**How many tickers did we lose and why?** None of the 503 candidates lacks data or fails a rule. Seven lose the history before their listing, and one has a stretch with no bars while it traded off-exchange. 52 candidates never enter the universe: they are real members of the index whose dollar volume never reaches the top 300.

**How much does the universe change month to month?** Little: 7.7 names of 300 enter at an average rebalance, slightly more in 2020 and 2025 to 2026 than in quieter years. Turnover from membership alone will be small next to the signal's own turnover in phase 2.

**How bad is the survivorship problem likely to be, and how would we fix it with paid data?** The universe is drawn only from companies in today's index. 175 of 503 candidates were added after the start of the data, often after strong growth, and every company that left the index, failed or was acquired is missing. For a reversal strategy the bias is not only in average returns: the losers that kept falling, failed or left the index are absent, which flatters buying recent losers. The fix needs point-in-time index membership and prices for delisted securities, which are paid (CRSP is the standard academic source). A decision record would be needed to use one.

**What would change in Europe or a broader universe?** In Europe: several exchanges and currencies, so a currency choice for returns and costs, different settlement and ex-date conventions, and dividend withholding on most issuers rather than a few, which makes rule 4 the main rule rather than an exception. Free data with corporate actions is scarcer. A broader US universe brings in smaller stocks, where zero-volume days, gaps and listing histories are common and the cleaning rules carry more weight, and costs grow.

## Lessons this phase built in

Ten rows added to [`docs/lessons.md`](../../lessons.md). Four have their episode in [What surprised us](#what-surprised-us) and decision record 0004: net foreign dividends, zero-volume bars, histories before listing and the action query's dates. The others are rules the phase built in with a test from the start: one canonical basis, point-in-time membership, New York dates, byte-identical rebuilds, primary sources for corrections and reference docs checked against the code.

## Reference docs

Confirmed current in this change: [architecture](../../architecture.md), [data model](../../data-model.md), [time discipline](../../time-discipline.md) (phase 0 rows), [glossary](../../glossary.md), [requirements](../../requirements.md) (the rebuild and the download, both measured on 2026-11-16), [reproducing the results](../../reproduce.md) (the phase 0 runner, pinning and backing up the snapshot), and the decision record index.

## Backlog walk

- **s-score threshold trading rule:** kept; trigger phase 2.
- **Benchmark against Avellaneda and Lee:** kept; trigger the phase 1 and phase 2 reviews.
- **Multi-period optimiser:** kept; trigger the phase 4 review.
- **Documentation site:** kept; trigger when the repository goes public.
- **A second price source for cross-checking:** added this phase; trigger the phase 1 review.
- **Company-level GICS reclassifications:** raised this phase with trigger phase 1, so moved into the phase 1 brief's known pitfalls.
- **Corporate actions other than splits, dividends and spin-offs:** raised this phase and resolved in it: the count above found no large return on their dates, so no rule is added, and rule 5 of record 0004 stands. Deleted.

## What carries forward

- **To phase 1:** the six tables, the dated sectors with the company-level check now in its brief, and the look-ahead helper. Residuals must use returns, not price levels, and betas only up to *t − 1*.
- **The dependency-upgrade criterion** is checked at the first upgrade: rebuild and compare table contents.
- **The pinned snapshot** is the one behind every number above. Keep its backup; a later download is a different snapshot, and moving the pin is a change with its own `Results:` footer.
- **Survivorship** stays as stated above in every later review.
