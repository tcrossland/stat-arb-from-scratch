# 0010: A momentum forward run beside the reversal run

**Date:** 2026-11-25
**Status:** accepted

## Context

The forward run of [decision record 0007](0007-forward-run.md) trades the frozen reversal strategy from 2026-11-16 to 2027-01-13. The [phase 8 brief](../phases/phase-08/brief.md) evaluates momentum as a second strategy and, as drafted, left a forward run of momentum out of scope and read no day from 2026-11-16 on.

A momentum forward run on the same sessions and the same data gives two things a later backtest cannot:

- whether the momentum pipeline, run one session at a time, matches its backtest, with its ledger written and backed up day by day;
- both strategies' daily returns on identical sessions and identical bars, the input the backlog's "Combining strategies" needs.

It cannot say much about momentum's return. A book held 21 days turns over about twice in 40 sessions, as the brief's pitfalls already say.

Three facts constrain it:

- **MarketParquet's archive ends at 2026-11-19 for this account.** On 2026-11-25 its API listed daily stock files for 2026-11-17 to 2026-11-19 and refused 2026-11-20 to 2026-11-25 as outside the plan's access window. New sessions need a subscription, which [record 0008](0008-marketparquet-archive-as-a-paid-price-source.md) says needs a record of its own. So the run uses Alpaca's data and the frozen universe, the reversal run's data path, and not phase 7's `listed` universe.
- **Every daily snapshot of the reversal run is kept** in the raw store, and each ledger day records the snapshot it was built from. A session already past can be processed from the bars the reversal job read for it.
- **This record comes after the first sessions.** The two signals were defined in the phase 8 brief, committed on 2026-11-19 (`90b6987`), after the sessions of 2026-11-16 to 2026-11-18. Everything else below is fixed here, on 2026-11-25, after the reversal job processed the session of 2026-11-24. No momentum value has been computed on any data before this record.

## Decision

1. **A second forward run, separate from the first.** Momentum runs on the frozen universe (the pinned S&P 500 candidate list, the market and the sector ETFs), from the same daily snapshots as the reversal run. It has its own config file, `config/momentum_forward.toml`, outside the files the reversal run's frozen record holds, and its own frozen records, ledgers, run log, notes and backup. Reversal's configuration, frozen record, job, schedule and end are unchanged.
2. **Two paths.** Each is a ledger of its own:
   - **total-return momentum** (Jegadeesh and Titman, 1993): the return over the 252 trading days ending 21 trading days before the decision;
   - **residual momentum** (Blitz, Huij and Martens, 2011): the sum of Model A's residuals over the same window, divided by their standard deviation over it.

   Both go through the decile sort, 10% of ranked members in each leg, held 21 days in overlapping slices, with a book of $5m, filled at the next open as the reversal run is, and costed by the phase 3 cost model with borrow, as the reversal run is costed. Nothing here is tuned: the window and skip are the papers', the decile and book are the reversal run's. The optimiser paths of the brief are left out: they need a calibration at a 21-day horizon and a slope rule that do not exist, and choosing them now would be choosing after forward days were seen.
3. **The first session is 2026-11-16 and the last 2027-01-13,** the reversal run's, by [record 0007's amendment](0007-forward-run.md#amendment-2026-11-18-the-runs-end-and-late-sessions). Each book starts flat, with its first decision at the close of 2026-11-16.
4. **Sessions already past are late.** Every session before the momentum job's first scheduled run is processed afterwards, in order, from the snapshot named for its run day, which is the snapshot the reversal ledger records for that session. Each is a late session under point 3 of record 0007's amendment.
5. **Results are reported two ways:** from 2026-11-16, and from the first session the momentum job processes on time. The first shares the reversal run's sessions; the second is free of the doubt that the choices in item 2 saw the earlier days.
6. **The same bars as the reversal run.** The momentum job never downloads. It reads the complete snapshot named for the run day that the reversal job took. If there is none, it processes nothing and the next run retries. It runs daily at 13:45 Central European time, after the reversal job's 13:15.
7. **Backtest first, then no change.** Each path is backtested once on the pinned development snapshot of 2026-11-16, cut at 2026-11-15 as the phase 2 to 4 runners are, and logged in `reports/phase-08/experiments.jsonl`. These are two trials, counted against phase 8's bar. The job refuses to run unless the code reproduces them. The run starts whatever they show, and no setting in item 2 changes after they are seen.
8. **Record 0007 item 4 is amended.** The forward days are read by the reversal run's daily job, its drift report and the momentum job, and by nothing else.
9. **What is committed** follows record 0007 item 7: the momentum daily notes go in `reports/phase-08/forward/daily/`, in the weekly pull request with the reversal run's notes. The ledgers, run log and backup address are not committed. The backup goes to a private repository of its own, whose address is a setting of the host.

## Consequences

- The phase 8 brief takes this run into its scope, ahead of the rest of the phase, which still waits for the forward run's review. Its sample section excepts the momentum job from "no day from 2026-11-16 on".
- The paper package gains a second kind of strategy. The change is additive: the reversal run's frozen check and reproduction check, run in the job's clone before it takes the new code, show that its path is unchanged.
- The run tests the momentum pipeline on today's S&P 500, with the survivorship that list carries in the years before. It is not a forward test of the `listed` universe's paths, which phase 8 runs on MarketParquet's history.
- This record does not replace the strategy's decision record that the brief asks for before phase 8's runs. That record counts the two trials of item 7.
- The phase 8 review reports the run's results both ways, lists its late sessions, and gives the daily correlation with the reversal run.
- A drift report for momentum is deferred. Its trigger is the first weekly pull request that carries momentum's notes.
- MarketParquet's subscription for new sessions, and a forward run on that source, stay a separate decision under record 0008.
