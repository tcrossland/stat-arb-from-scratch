---
name: daily-check
description: Check whether the forward run's scheduled jobs on this host have run, what each did, and what changed since the run before. Covers the reversal daily job, the momentum job that follows it, and the Sunday drift report. Use when asked whether the daily job has run, finished or failed, what the latest ledger day made, or what changed in the run.
---

# Check the scheduled jobs

Read-only. Never start, stop or reload a job, never pull or change the job's clone, and never edit its files. `docs/daily-job.md` says how the jobs are set up and what each file holds; this skill only reads them.

Quote a figure or a decision only from a command run in this check, never from memory or an earlier answer. When explaining a trade, name the day its forecast was recorded, the open it was filled at and the ledger day it earned on.

## 1. Find the clone and the schedule

The jobs run from a clone used for nothing else. On macOS its path is in the daily job's launchd agent, as the folder holding `data/paper/daily.log`:

```bash
plutil -extract StandardOutPath raw ~/Library/LaunchAgents/local.stat-arb-forward.daily.plist
```

The clone is that path less `/data/paper/daily.log`. Call it `$CLONE` below. If there is no agent, look for cron lines with `crontab -l`, and if there are none, ask where the jobs run.

Each job's time is in its agent's `StartCalendarInterval`, in the host's local time:

```bash
for j in daily momentum drift; do f=~/Library/LaunchAgents/local.stat-arb-forward.$j.plist; [ -f "$f" ] && echo "$j: $(plutil -extract StartCalendarInterval json -o - "$f")"; done
```

The drift report has a `Weekday` (0 is Sunday) and runs once a week. A job whose time today has not come yet has not missed its run: say when it is due.

## 2. Is a job running?

```bash
for j in daily momentum drift; do echo "$j: $(launchctl print gui/$(id -u)/local.stat-arb-forward.$j 2>&1 | grep -E '^\s*(state|runs|pid|last exit code) =' | tr -s ' \t' ' ' | tr '\n' ';')"; done
```

`state = running` with a `pid` means it is running now. The daily job then names its current stage in its log: each stage writes a start line and a `done in` line with the UTC time, and the stage with a start line and no end line is the one running. The download also prints `prices: N/515` as it goes.

```bash
grep -v '^prices: [0-9]*/' "$CLONE/data/paper/daily.log" | tail -n 15; tail -n 1 "$CLONE/data/paper/daily.log"
```

For the time a run takes, read `duration_seconds` from the run log's earlier lines rather than guessing; the download is most of it.

## 3. What each run did

Each run appends one line to its run log. List the latest runs with DuckDB, which shows `as_of` and `recorded_at` in the host's time zone (the file holds UTC):

```bash
duckdb -no-agent -markdown -c "SELECT as_of, recorded_at, status, message, due, processed, problems, reproduced, left(git_commit, 7) AS git_commit, git_dirty, snapshot, backup, duration_seconds, peak_memory_mb FROM read_json_auto('$CLONE/data/paper/runs.jsonl', union_by_name = true) ORDER BY as_of DESC LIMIT 4"
```

Columns a run log lacks, as older lines do, come back empty with `union_by_name`. Read today's line against the last run that processed a session:

- **status:** `done` or `nothing due` is a clean run. `refused`, `failed` or `incomplete` gives its reason in `message`, and "When a run refuses" in `docs/daily-job.md` says what each means.
- **problems** should be empty, `reproduced` should match the frozen path's id in every run that processed a session, and `git_dirty` should be false.
- **git_commit** changing between runs means the clone was updated. Name both commits and list what came in with `git -C "$CLONE" log --oneline <old>..<new>`.
- **backup** says whether the ledger was pushed. A failed backup does not fail the run, so report it even when the status is `done`.
- **No line for today** after the scheduled time, with the agent not running: the run script stopped before the job started, often on a locked keychain. The scheduler's log (`daily.log`) holds the error.

**The momentum job** keeps a run log per path in `$CLONE/data/paper-momentum/<path>/runs.jsonl`, one folder per path beside `processed`, `reference` and `backup`, and its log in `$CLONE/data/paper-momentum/momentum.log`. Run the same query on each path's run log. It reads the sessions the reversal ledger recorded, so it can only be as far on as the daily job. `incomplete` means the session it waited for was not in the reversal ledger within the hour; the next run retries.

**The drift report** writes `$CLONE/reports/phase-06/drift/<last session>.md`. On a Sunday after its time, check that a new report is there and read its Verdict section.

## 4. What the new ledger day made

Run the ledger views of `notebooks/ledger.sql` from this checkout. The guide table they print on loading can be ignored. For the reversal run:

```bash
STATARB_LEDGER_ROOT="$CLONE" duckdb -no-agent -markdown -init notebooks/ledger.sql -c "FROM pnl ORDER BY date DESC LIMIT 3"
```

For a momentum path, the views need its ledger and the momentum run's tables side by side, so point them at a folder in the scratchpad that links to both:

```bash
M=<scratchpad>/momentum-<path> && mkdir -p "$M" && ln -sfn "$CLONE/data/paper-momentum/<path>/ledger" "$M/ledger" && ln -sfn "$CLONE/data/paper-momentum/processed" "$M/processed" && duckdb -no-agent -markdown -cmd "SET VARIABLE paper = '$M'" -cmd ".read notebooks/ledger.sql" -c "FROM pnl ORDER BY date DESC LIMIT 3"
```

For the latest ledger day, report the net P&L and its costs and borrow from `pnl`, the long and short totals from `earned` grouped by `side`, the largest names and sectors from `earned`, and the book after the open from `exposure`. `health` shows each day's optimiser status, missing returns and commit. A ledger day earns from the previous ledger day's open to its own open, on the book filled at that previous open, which was decided on the `expected_move` recorded at the close of the ledger day before it.

Each processed session also writes a note: `$CLONE/reports/phase-06/daily/<session>.md` for the reversal run, and `$CLONE/reports/phase-08/forward/daily/<path>/<session>.md` for each momentum path. Check it is there. Notes the job has written and the weekly pull request has not yet taken show in `git -C "$CLONE" status --short`.

## 5. Report

Lead with the answer for each job: run or not, and its status. Then, in a short list, what changed since the run before: the sessions processed, the commit, the snapshot, the backup, the duration and peak memory against earlier runs, and the new ledger day's figures. Say what was not checked.

The ledger's figures derive from licensed market data (decision record 0003). Give them in the chat only, never in a commit, a pull request or anywhere public.
