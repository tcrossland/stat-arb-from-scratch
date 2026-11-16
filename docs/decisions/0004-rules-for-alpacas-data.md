# 0004: Rules for Alpaca's data

**Date:** 2026-11-16
**Status:** accepted

## Context

Decision record 0003 makes Alpaca the only price source and says the rules for using its data are found while building phase 0 and recorded in a record of their own. Alpaca returns daily bars and corporate-action records separately. Turning them into unadjusted bars with a `cash` and a `split_ratio` column on each ex-date, the form the canonical step and the return calculation expect, needs choices about which bars and records to trust and how to read them.

Every rule is applied by the build to the raw snapshot (`statarb.data.alpaca.apply_rules`, called from `statarb.data.snapshot`), never at download time, so a changed rule needs a rebuild, not a new download.

## Decision

1. **Dates and empty bars.** Bars are requested with `adjustment=raw` from the consolidated feed (`feed=sip`) and dated by their New York date. A bar with zero volume is dropped: Alpaca returns one repeating the last close on a day with no trade on the consolidated tape (a whole-day halt, or trading off-exchange), and that close is not a price of the day.
2. **The action query.** `/v1/corporate-actions` filters `start` and `end` on the process date, which can fall weeks after the ex-date and occasionally before it. The query reaches 90 days either side of the bars' window, and records are kept by ex-date inside the window.
3. **Splits.** Forward and reverse splits give `split_ratio = new_rate / old_rate` on the ex-date. Two actions on one ex-date multiply.
4. **Cash dividends.** A dividend's `rate` is cash per share on its ex-date.
5. **Other kinds.** Stock dividends, spin-offs, mergers, redemptions, rights and the other kinds Alpaca returns are kept in the snapshot but not applied. A price move they cause shows as a large return in the quality report, which is where a missing rule would first be seen.
6. **Failures.** A ticker whose data breaks a rule (an action going ex on a day inside its window with no bar) is left out of the build and listed in the quality report with the reason, as a failed download is. The build never guesses.

## Consequences

- A rule can be changed and tested without the network: the tests run the rules on synthetic responses, and a rebuild of a pinned snapshot shows the effect.
- Other kinds of action (rule 5) are not modelled. The quality report counts the large returns that remain, by year and by whether they fall on an action day, and the phase review reports them.
