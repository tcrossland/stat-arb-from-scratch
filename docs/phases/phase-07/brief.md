# Phase 7: A second source and a universe with dead names

Drafted on 2026-11-19, during the forward run, and started the same day. Revised at the start with what the first requests to the source showed, under "Found at the start".

## Goal

Add a second price source that holds the stocks that have since been delisted, check it against the first, build a universe from every stock listed on the day, and measure how much survivorship flatters the reversal results. No new strategy.

## Why this phase, and why now

Every review since phase 0 says the universe is drawn from today's S&P 500, so it has no stock that was removed or delisted, and that this flatters a strategy that buys recent losers. None could say by how much: no free source found holds the dead names' prices. A paid archive that does has been bought. This phase is phase 0 again for that source, and it ends with the measurement the earlier reviews could only describe.

It runs while the forward run of decision record 0007 lasts, which sets its limits:

- **No file in the frozen record changes.** `statarb.paper.frozen` hashes `data`, `universe`, `factors`, `sector_changes`, `listing_starts`, `alpaca`, `backtest`, `costs`, `portfolio` and `models`, and the daily job refuses to run on a change. Everything this phase configures goes in files of its own.
- **No pinned library moves.** `uv.lock` pins cvxpy, Clarabel, SciPy and LightGBM exactly for the frozen path's reproduction check. This phase needs no new library: pyarrow reads the source's files and the standard library fetches them.
- **Every logged result of phases 0 to 6 reproduces unchanged.** A change to shared code, such as the engine or the trial count, is off by default or leaves earlier entries' ids as they are, and a test requires it.
- **The job's clone is not pulled for this phase.** The work merges to `main`; the clone takes it only at a deliberate pull that passes the reproduction check.

## Before the phase starts

[Decision record 0008](../../decisions/0008-marketparquet-archive-as-a-paid-price-source.md) is the source's record, since decision record 0001 says paid data needs one. It says:

- which source, what was bought and when, and that it amends the free-data rule of decision record 0001 for this one source;
- the source's licence and terms as read from its own pages, with the date read;
- that Alpaca stays the source of everything already built, and that no table mixes the two sources' prices;
- that only daily stock and ETF bars are used: intraday bars and futures stay out of scope ([roadmap](../../roadmap.md));
- how snapshots are kept and pinned, where the key is read from, and that nothing of the data is published;
- that the years before 2016 are unread and stay so in this phase (see "The sample" below).

## Found at the start

From the source's documentation and a few day files read for their schema alone, on 2026-11-19:

- **The archive's last file is the session before the download's date** until the night's update, so the first snapshot, through 2026-11-19, is taken on 2026-11-20 or later. The download refuses to write a snapshot that stops short of the last session asked for.
- **A day file has no hash,** only a size in the file list. The download checks each file against its listed size, and the snapshot's own manifest holds the hashes.
- **The day is in a column that changed name.** Files dated before 2026-03-27 carry it as a midnight timestamp in `timestamp`, later ones as `date`. The reader accepts either and requires every row of a file to be of the file's day.
- **Stocks and ETFs are separate datasets,** `stock_daily` and `etf_daily`, each with its own file per day. The factor ETFs and SPY are in the second.
- **Reading by ticker would open every day file for each ticker,** some 2,700 files since 2016. The snapshot is read by day instead, a window at a time into one long table, and `statarb.data.snapshot.PriceSnapshot`, which reads by ticker, refuses it. See "Design points".
- **The file list's addresses are on a storage host, signed and valid for an hour.** The key goes to the API's host alone, and a test requires that.
- **A file takes about half a second to arrive,** one at a time, whether or not the connection is kept open, and the storage host does not offer HTTP/2, so requests cannot share a connection. The download fetches eight files at once, as the source's documentation suggests, through the standard library's thread pool, with every request still on one pace under the key's rate limit. At eight the pace is the limit.
- **The site's edge refuses Python's default client name.** The adapter names itself for what it is, a script reading the archive, in its `User-Agent`; the source's documentation gives scripted downloads as the intended use.

## The source

MarketParquet's archive, as its own pages describe it on 2026-11-19. Decision record 0008 holds the detail; what shapes this phase:

- **One parquet file per trading day holding every symbol,** from 2000-01-03, for stocks listed on NYSE, Nasdaq and NYSE American and for US-listed ETFs. A day's file is the cross-section as it traded that day, dead names included.
- **Prices are adjusted for splits as of the download,** and volumes with them. Cash dividends are not in the prices.
- **A delisted security's symbol carries the suffix `-DELISTED`** through its whole history.
- **It has no** dividends, table of splits, sectors, shares outstanding, kind of security, delisting return or reason, or permanent identifier.
- **The archive is corrected often and carries no version,** so a snapshot is the only way to reproduce a result.
- **The purchase covers sessions up to 2026-11-19.**

## The sample

- **Development, 2016-01-01 to 2025-11-13:** the years every earlier phase used, cut where `config/models.toml` cuts them. The survivorship measurement runs here.
- **The cross-check may read to 2026-11-13,** the phase 5 holdout's last day. That year is spent, and the cross-check compares sources, not strategies.
- **No day from 2026-11-16 on is read.** Those are the forward run's days, a fresh holdout under decision record 0007. The snapshot holds a few of them; every table is cut before them.
- **The years before 2016 are unread.** No configuration in the repository has seen them, so whatever reads them first spends them. This phase checks those files' hashes, schema and row counts and computes no return from them. Phase 8's decision record says what they are for.

## Scope

In order. Each step is a commit or a short series.

1. **The adapter and the first snapshot.** `statarb.data.marketparquet` and its runner `statarb.data.marketparquet_build`, settings in `config/marketparquet.toml`, the key from `MARKETPARQUET_API_KEY` in the environment. A download asks for each year's files with one manifest request, stays under the key's rate limit, and writes a snapshot under `marketparquet/<download date>/` in the raw store, complete when its manifest of file hashes is written, pinned by date and digest. The first snapshot runs through 2026-11-19.
2. **The source's quality report,** `reports/phase-07/data_quality.md`, statistics only: symbols per day by year, the share of suffixed symbols, missing sessions, jumps the size of a split, bars whose open or close lies outside the day's range, and symbols that appear, vanish and reappear.
3. **The cross-check against Alpaca,** `reports/phase-07/cross_check.md`, on the existing candidates over 2016-01-01 to 2026-11-13:
   - closes and volumes, with Alpaca's put on the same split basis, and the share of symbol-days that agree to a stated tolerance, by year;
   - splits, where the two split-adjusted series part company;
   - price returns on days with no ex-date, and the size of the dividends this source lacks, as a share of return variance;
   - whether the two closes are the same close, counted by year where they differ;
   - the existing headline rebuilt on this source's prices for the same names, with every difference from the logged metrics stated. It repeats a logged path and adds no trial.
4. **Rules for this source's data,** in a decision record of their own as decision record 0004 is for Alpaca. Each is settled by measuring first:
   - **Splits and unadjusted prices.** Whether Alpaca's corporate actions cover delisted names decides how much is recoverable. Without a split on its ex-date the canonical step cannot return unadjusted prices.
   - **Dividends.** From Alpaca's records where they exist, or price returns, stated.
   - **Spin-offs.** Those the source folds into its split factor, and those left as traded.
   - **Kinds of security.** Which symbols are common shares.
   - **Delisting.** The last bar is the last trade; any assumed final return is a sensitivity.
5. **A named universe.** The phase 0 liquidity ranking over every stock in the day's file, written beside the existing universe and chosen by name. `build_universe` already takes bars, tickers and a size, and dollar volume is unchanged by split adjustment.
6. **A rule for names whose prices stop.** See "Names whose prices stop" below.
7. **The survivorship measurement,** `reports/phase-07/survivorship.md`. See below.

## The survivorship measurement

The reversal headline of phase 2, with its lookback, holding period, decile and fill unchanged and no sweep, on four universes of 300 names over development:

| Universe | Source | Names ranked | It isolates |
|---|---|---|---|
| 1 | Alpaca | today's S&P 500 | nothing: the logged result |
| 2 | MarketParquet | today's S&P 500 | the source, and the missing dividends |
| 3 | MarketParquet | every listed stock that still trades today | the change of candidates |
| 4 | MarketParquet | every listed stock of the day | survivorship |

- **Universes 2 to 4 share one source and one return basis,** so the differences among them are the universe's. The gap between 1 and 2 is sized by the cross-check.
- **Universe 3 is built with look-ahead on purpose.** It keeps the names with no suffix, which is the bias being measured. One function builds it, takes the suffix as an explicit argument, and is called by this measurement alone.
- **Two forms of the signal:** reversal on total returns (`raw`), which needs no factor model, and on Model B's residuals, which need no sectors. Model A runs on universes 1 and 2 only, since sectors exist only for today's S&P 500.
- **Gross, and net at phase 2's flat cost levels,** which are charged per dollar traded and read no price level. The phase 3 cost model is not run on this source until a rule gives it unadjusted prices.
- **Its paths are trials.** Six on universes 2 to 4 with the two forms, and Model A on universe 2: seven, fixed here and logged in `reports/phase-07/experiments.jsonl`.
- **What it reports:** the Sharpe ratio, return and turnover of each path, the long and short legs apart, by year, and the names in each leg that later delisted, counted. Statistics only.

## Design points

- **The price source seam.** `PriceSource.fetch` takes one ticker and a date range and returns bars with `cash` and `split_ratio`. This source serves one file per day and has neither column. The adapter downloads by day and reads by day (`read_days`), since reading by ticker would open every file for each ticker. Decision record 0008 puts the source behind `PriceSource`: that waits for step 4, whose rules say what `cash` and `split_ratio` are for this source, and is then a class over the table `read_days` returns, so the protocol gains no second shape. If the rules cannot supply those columns, the record is amended before the seam is.
- **The snapshot's layout** is a third one, `days`, beside `raw` and `bars`: the day files as served, `<dataset>/<year>/<date>.parquet`, with the source's rules applied by the build.
- **Derived tables of their own.** This source's tables go under a directory named in `config/marketparquet.toml`, never into `data/derived/processed/`, which holds Alpaca's.
- **The trial id needs the universe.** `PATH_KEYS` in `statarb.backtest.trials` holds the signal, lookback, fill and the rest, but neither the universe nor the source, so a logged run on another universe would take the existing path's id and replace its statistic. A `universe` key enters, null for the existing universe so every earlier id holds, and a test requires that.
- **The run state names the source it read.** `run_state` takes the source and snapshot from `[source]` of `config/data.toml`. A run on this source records its own.
- **The suffix is a key and nothing else.** A test replaces every suffix with a label that carries no meaning and requires the universe, the scores and the positions of universes 2 and 4 to be unchanged. It runs unmarked.
- **Keys.** With no permanent identifier, a security is its symbol as the snapshot has it, suffix included. A symbol the source renames between two snapshots is a difference the rebuild tolerance must absorb.

## Names whose prices stop

The engine's rule is that a name with no bar cannot trade and keeps its holding, and a held name with no return is booked at zero. On today's survivors that case is rare. On a universe with dead names it is routine, and it compounds: a delisted name drops out of the ranking within a month, the rule's target for it becomes zero, and the engine can never trade it there, so the position stays in the book for good at a zero return, taking gross.

- A rule closes a held name at its last price after a set number of sessions without a bar, books nothing further, and counts it.
- It is an option of the engine, off by default, so every logged result and the frozen strategy are unchanged, and a test requires the existing paths to reproduce exactly with it off.
- The number of sessions is set once, before any path runs, in `config/marketparquet.toml`.
- Whether to make it the default for the existing universe is the backlog's "Cash-out for names whose prices stop", after the forward run's review.

## Backlog items this phase takes up

These left the backlog when the phase started, and the review says so:

- **"A second price source for cross-checking"**: step 3.
- **"Survivorship-free prices"**: step 7. It asks for a free S&P 500 panel with delisting returns. This phase measures survivorship on an own universe from a paid source without delisting returns, and says what that leaves unmeasured. What it leaves is the backlog's "Point-in-time index membership".

## Deliverables

1. The record of rules for the source's data, beside decision record 0008.
2. `src/statarb/data/marketparquet.py`, its config file, and the snapshot's layout in `statarb.data.snapshot`.
3. The named universe, the engine's option for names whose prices stop, and the `universe` key of the trial id.
4. `reports/phase-07/`: the quality report, the cross-check, the survivorship report with its charts, and `experiments.jsonl`.
5. Tests: the adapter on synthetic day files with the network blocked, the addresses it builds, the suffix test, the universe's look-ahead test on the new universe, the engine's option on and off, earlier path ids unchanged, and the contract suites over whatever joins a seam.
6. The reference docs: the source, runner, config file and tables in `docs/architecture.md` and `docs/data-model.md`, the suffix rule in `docs/time-discipline.md`, time, memory and disk in `docs/requirements.md`, and the second source in `docs/reproduce.md` and the README's invariants.

## Acceptance criteria

- A rebuild from the pinned snapshot reproduces this phase's tables byte for byte and every logged metric exactly.
- Every logged result of phases 0 to 6 reproduces unchanged, and `statarb.paper.frozen` finds the frozen record unchanged.
- The cross-check states, by year, how often the two sources agree and where they do not, and either explains each kind of disagreement or lists it as open.
- The suffix test passes for the universe, the signals and the positions.
- No return before 2016 and no day from 2026-11-16 on is read by any runner, and a test checks the cut.
- The survivorship report gives the difference between universes 3 and 4 for each form of the signal, with the legs apart, and says which way the missing delisting returns would move it.

## Known pitfalls

- **The suffix says what happened later.** Any filter, join or sort that reads it is look-ahead.
- **A price floor on adjusted prices is look-ahead too.** A later reverse split raises every earlier adjusted price, so a floor would keep names because of what happened afterwards. Rank on dollar volume only until unadjusted prices exist.
- **The missing delisting return cuts by leg.** A name that fails loses more after its last trade than its last bar shows. Leaving that out flatters a long leg in recent losers and understates a short leg in them.
- **The source may share an upstream with Alpaca.** Agreement then proves less than it seems.
- **The archive changes under a pinned digest.** A second download will differ. That is the source's revision, not an error in the rebuild, and the tolerance is measured only when a second snapshot exists.
- **Not every symbol is a common share.** A ranking by dollar volume takes whatever trades most.
- **A reused ticker is two securities.** The source tells them apart by the suffix, which is why the suffix must stay in the key while staying out of every decision.

## Out of scope

Any new signal or strategy. Any return before 2016. The phase 3 cost model, the optimiser and the ML forecast on the new universe. Intraday bars and futures. A forward run on this source. Any change to a file in the frozen record.

## Review questions

- How closely do the two sources agree, and what explains where they do not?
- How much of each earlier result was survivorship, by leg and by year?
- Which of the source's gaps could be closed by a rule, and which stay as stated assumptions?
- Is the new universe fit to carry a strategy with costs, or does the lack of unadjusted prices rule that out?
- What did the first read of the day files show about the years before 2016 that phase 8 should know, without any return being computed?
