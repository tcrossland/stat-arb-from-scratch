# 0004: Rules for Alpaca's data

**Date:** 2026-11-16
**Status:** accepted

## Context

Decision record 0003 makes Alpaca the only price source and says the rules for using its data are found while building phase 0 and recorded in a record of their own. Alpaca returns daily bars and corporate-action records separately. Turning them into unadjusted bars with a `cash` and a `split_ratio` column on each ex-date, the form the canonical step and the return calculation expect, needs choices about which bars and records to trust and how to read them. A few of its records need information Alpaca does not give.

Every rule is applied by the build to the raw snapshot (`statarb.data.alpaca.apply_rules`, called from `statarb.data.snapshot`), never at download time, so a changed rule needs a rebuild, not a new download. The rules that need data, such as withholding periods, live in `config/alpaca.toml`.

## Decision

1. **Dates and empty bars.** Bars are requested with `adjustment=raw` from the consolidated feed (`feed=sip`) and dated by their New York date. A bar with zero volume is dropped: Alpaca returns one repeating the last close on a day with no trade on the consolidated tape (a whole-day halt, or trading off-exchange), and that close is not a price of the day.
2. **The action query.** `/v1/corporate-actions` filters `start` and `end` on the process date, which can fall weeks after the ex-date and occasionally before it. The query reaches 90 days either side of the bars' window, and records are kept by ex-date inside the window.
3. **Splits.** Forward and reverse splits give `split_ratio = new_rate / old_rate` on the ex-date. Two actions on one ex-date multiply.
4. **Cash dividends and withholding.** A dividend's `rate` is cash per share on its ex-date. Alpaca flags dividends of foreign issuers `foreign`, but from 2023 it reports some of them net of the issuer's home withholding tax and others gross, and the flag does not say which. The project's returns use the gross amount the issuer declares. `config/alpaca.toml` lists, per ticker, the ex-dates on which amounts are net and the rate withheld, and the tickers whose foreign-flagged amounts are gross throughout; a net amount is divided by one minus the rate. Each listing cites the issuer's declared amounts and the tax authority's rate. A foreign-flagged dividend for a ticker in neither list fails that ticker (rule 6), so a new case is checked by hand.
5. **Other kinds.** Stock dividends, mergers, redemptions, rights and the other kinds Alpaca returns are kept in the snapshot but not applied. A price move they cause shows as a large return in the quality report, which is where a missing rule would first be seen.
6. **Failures.** A ticker whose data breaks a rule (an action going ex on a day inside its window with no bar, a spin-off with no close, or an unlisted foreign dividend) is left out of the build and listed in the quality report with the reason, as a failed download is. The build never guesses.
7. **Histories and listing starts.** Some tickers carry bars from before their own listing: when-issued trading, a SPAC's shell, or another security that held the symbol. Those bars have real volume, so no rule on the bars finds them: `config/listing_starts.toml` gives each such ticker's first date with its source, and cleaning drops the bars before it.
8. **Spin-offs.** A spin-off is valued as cash to the parent's holders: the share ratio times the spun-off security's first close on or after the ex-date (or the payable date, when later), searched for ten days. On an ex-date that also has a split, the ratio counts shares held before the split, so the cash is divided by the split ratio.
9. **Symbols.** A ticker's actions follow its name changes back. Each symbol counts only for the dates the ticker held it, from the name change into it to the change away from it, because Alpaca reuses symbols across securities and a ticker can hold the same symbol twice.

## Consequences

- A rule or correction can be changed and tested without the network: the tests run the rules on synthetic responses, and a rebuild of a pinned snapshot shows the effect.
- `config/alpaca.toml` needs upkeep. A new foreign issuer in the universe can fail a ticker until it is listed, and the quality report says which.
- Withholding periods are inferred from where Alpaca's amounts fall short of the issuer's declared ones, so a period can be off by one dividend at its edges. An error there moves one day's return by the tax withheld, a fraction of the dividend yield.
- Other kinds of action (rule 5) are not modelled. The quality report counts the large returns that remain, by year and by whether they fall on an action day, and the phase review reports them.
- Valuing a spin-off at the spun-off security's first close is a convention, not a market fact: the true value is set in when-issued trading before it.
