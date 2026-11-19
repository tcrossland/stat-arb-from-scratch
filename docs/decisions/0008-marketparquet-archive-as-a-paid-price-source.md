# 0008: MarketParquet's archive as a paid price source

**Date:** 2026-11-19
**Status:** accepted

## Context

Decision record 0001 limits the project to free daily data and says that moving to paid data needs a new record. Decision record 0003 makes Alpaca the only price source, with history from 2016 and candidates from the current S&P 500. Two limits follow, and each phase review states them:

- **Survivorship.** The candidates are today's constituents, so no stock that was removed or delisted is in any backtest.
- **Sample length.** Ten years is too short to judge a strategy that trades monthly, and it holds neither 2000 to 2002 nor 2008.

No free source found so far removes either. The backlog's "Survivorship-free prices" has one unread candidate, and "A second price source for cross-checking" had none whose terms were clear.

**MarketParquet** sells an archive of US bars as parquet files, one file per trading day holding every symbol. Read from its own pages on 2026-11-19 (pricing, documentation, data quality and methodology, data licence, terms of service effective 2026-11-04, FAQ):

- **What the archive holds.** Daily bars from 2000-01-03 for stocks listed on NYSE, Nasdaq and NYSE American and for US-listed ETFs, with the stocks that have since been delisted, acquired or merged kept in each day's file as they traded. Also bars of 1, 5, 30 and 60 minutes from 2000, and continuous futures from 2007-12-31.
- **Price.** A single payment for the history up to the day of purchase. New sessions come from a monthly subscription, or from a free tier that serves the last year of daily bars.
- **Basis.** Prices are adjusted for splits as of the download and volumes with them. Cash dividends are not in the prices. The split factors also cover stock dividends and, case by case, a large spin-off; other spin-offs and mergers are left as traded.
- **Symbols.** A delisted security's symbol carries the suffix `-DELISTED` throughout its history, and an earlier company on a reused ticker is told apart by it.
- **Provenance.** Bars are licensed from an institutional vendor the site does not name.
- **Corrections.** The trailing 30 days are compared with the vendor each night and rewritten where they differ, and older history is rebuilt when an error is found. The changelog lists rewrites almost daily. Files carry no version or checksum.
- **Licence.** It allows backtesting and research, copies on the licensee's own machines, and publishing results derived from the data, such as statistics and charts that cannot be used to reconstruct the bars. It forbids redistributing the raw files or offering them or a trivially transformed copy to others. It is granted per account on payment for an archive, and is perpetual for files already downloaded.
- **Terms.** One account per person or organisation. The site forbids scraping it in place of buying and reaching for data not purchased. Its documentation describes bulk download through an authenticated API, with a rate limit per key.

What the archive does not hold: dividends, a table of splits, sectors, shares outstanding, the kind of security, delisting returns or reasons, index membership, quotes, or a permanent identifier.

## Decision

1. **MarketParquet's archive is a second price source,** behind the `PriceSource` interface. It was bought on 2026-11-19 with a single payment. This amends decision record 0001: the project may use this one paid source. Any other paid source, and the subscription for new sessions, needs a record of its own. Decision record 0001's other rules stand.
2. **Daily stock and ETF bars only.** The intraday bars and the futures are in the archive but stay out of scope ([roadmap](../roadmap.md)) until a record says otherwise.
3. **Alpaca stays the source of everything already built.** Phases 0 to 6, their logged results and the forward run read Alpaca's snapshots, as decision records 0003 and 0007 say. One price source per build still holds: no table mixes the two sources' prices.
4. **No file in the frozen record changes.** The source's settings go in a config file of its own, never in `config/data.toml` or any other file `statarb.paper.frozen` hashes, so the daily job runs on unchanged.
5. **Raw snapshots are never modified.** Each download is kept as the files MarketParquet served, as a dated snapshot in a folder of its own in the raw store, complete when its manifest of file hashes is written, and pinned by date and digest. Because the archive is rewritten and carries no version, a snapshot is the only way to reproduce a result. The first snapshot is taken through 2026-11-19, the last session the purchase covers.
6. **The key** is read from the environment (`MARKETPARQUET_API_KEY`), never from the repository, a config file or a scheduler file. The adapter calls only the documented API on `marketparquet.com` and the download addresses it returns, asks for a year's files with one manifest request, stays under the key's rate limit, and a test checks the addresses it builds. Tests never call the API: they run the adapter on synthetic files.
7. **Nothing of the data is published.** No price, volume or per-symbol return from this source appears in a report, a document, a commit message or a fixture, as for Alpaca. Reports hold statistics that cannot be used to reconstruct a bar. Raw and derived tables stay out of the repository.
8. **The suffix is never an input.** `-DELISTED` on a bar from an earlier year says what happened later, so it is look-ahead. It is part of a security's key and nothing else: no universe rule, signal, cost or position may depend on it. A look-ahead test replaces the suffixes with ones that carry no meaning and requires every output to be unchanged. The one exception is a universe of survivors built on purpose to measure the bias, by a function that takes the suffix as an explicit argument.
9. **Rules for MarketParquet's data** are found while building on it and recorded in a record of their own, as decision record 0004 does for Alpaca. Known before the first download, and to be settled there:
   - **Unadjusted prices.** The build's canonical step needs each split on its ex-date, and the cost model counts shares at the unadjusted fill price. The archive has no split table. Until a rule supplies one, nothing that depends on a price level is computed from this source: the per-share commission, the half-tick floor and any price floor in a universe rule. Dollar volume is unchanged by split adjustment, so the liquidity ranking is unaffected.
   - **Dividends.** Returns from this source are price returns unless a rule adds the cash from another record of the issuer's dividends.
   - **Spin-offs.** Those folded into the split factor and those left as traded need telling apart.
   - **Delisting.** A security's last bar is its last trade. Any assumed final return is a stated sensitivity, never a silent fill.
   - **Kinds of security.** A rule for which symbols are common shares, since the archive does not say.
10. **Its first use is the cross-check** of the backlog's "A second price source for cross-checking", in [phase 7](../phases/phase-07/brief.md): closes and split-adjusted returns of the existing candidates against Alpaca's, over a window that ends on the phase 5 holdout's last day, 2026-11-13. It reads no day of the forward run and adds no trial. It also measures whether this source's daily close is the close the backtests used.
11. **The years before 2016 are unread.** No configuration in the repository has seen them. No return is computed from them, in the cross-check or anywhere else, until the record that takes up the next strategy says what they are for, how its trials count against the bar and what serves as its holdout. Checking those files' hashes, schema and row counts is not a read.
12. **The strategy is not chosen here.** Each strategy taken up needs its own record before its first run, as the backlog says.

## Consequences

- **A reader must buy the archive to rebuild any result on this source.** Results on Alpaca's data are rebuilt as before, with a free account. From phase 7 each report says which source it rests on, and the reproducibility invariant in `README.md` and `docs/reproduce.md` say the same.
- **A reader's download will differ from the pinned snapshot,** by more than Alpaca's does, since the archive is corrected often. How closely results match is measured when a second snapshot exists, as for Alpaca.
- **The purchase covers sessions up to 2026-11-19.** A forward run on this source would need the subscription or the free tier's rolling year, and a record first.
- **The source's independence is unknown.** Its vendor is unnamed and may share an upstream with Alpaca. Agreement in the cross-check then proves less than it seems; disagreement is still worth chasing.
- **Survivorship can be measured, not only stated,** once the rules above exist: the same configuration on today's constituents and on a universe ranked from every listed stock of the day. Without delisting returns the measurement has a known gap, and each review says which way it cuts.
- **Model A does not extend to this universe.** Sectors exist only for the current S&P 500 list, so residuals for other names come from Model B or a market-only regression.
- **The cost model needs a decision before any net result** on this source under phase 3's model, since the commission and the spread's floor read unadjusted prices.
- **The licence is the account holder's.** It covers the holder's own machines. A contributor would need their own purchase, and no snapshot is shared.
- **The snapshot holds days of the forward run** for the frozen strategy's names. The frozen strategy cannot change, and every table built from this source is cut before them, so the fresh holdout of decision record 0007 is not read.
