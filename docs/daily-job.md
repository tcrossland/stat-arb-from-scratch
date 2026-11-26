# Running the daily job

The forward run trades the strategy frozen by [decision record 0007](decisions/0007-forward-run.md) on a simulated book, one New York session at a time. This page sets up its two scheduled jobs:

- **The daily job,** `statarb.paper.daily`, downloads the day's snapshot and processes every due session into the ledger. It also writes a daily note and backs the ledger up.
- **The weekly drift report,** `statarb.paper.drift`, compares the run with its backtest.

A third job, the momentum forward run of [decision record 0010](decisions/0010-momentum-forward-run.md), steps two momentum strategies through the same sessions, each from the snapshot the daily job read for it (section 7). None places an order anywhere.

## What the host needs

- **A Unix-like system:** Linux or macOS. Windows is not supported, because the job's lock uses `fcntl`.
- **A clone of the repository used only by the job** (section 1), with `uv sync --locked` done and `git` and `ssh` installed. On macOS, LightGBM needs `libomp` (README, "Running it").
- **The pinned snapshot** in the raw store: the one named in `[source]` of `config/data.toml`. The reproduction check rebuilds the frozen path from it before every run.
- **Disk for a snapshot a day.** Each daily download is a full snapshot of the history since 2016, and every one is kept in the raw store, because the drift report compares each snapshot with the one before it. The first run's figures go in [`requirements.md`](requirements.md).
- **Network access** to Alpaca's market data API (`data.alpaca.markets`) for the daily download, and to the git host for the backup.
- **The keys of an Alpaca account** (section 3). The free plan of a paper-only account is enough ([decision record 0003](decisions/0003-data-sources-alpaca-and-wikipedia.md)).
- **To be on, or to wake,** some time after 06:00 New York on most days. A missed day is not lost: the next run processes every session since the last ledger day, in order.

## 1. A clone for the job

Run the job from a clone used for nothing else, on `main` at the merge of decision record 0007. A checkout used for development changes branch, and the job runs whatever is checked out. The frozen record catches a changed config. The reproduction check catches code that no longer gives the frozen path's logged metrics. Neither sees every other change.

```bash
git clone git@github.com:tcrossland/stat-arb-from-scratch.git stat-arb-forward
```

```bash
cd stat-arb-forward && uv sync --locked
```

Keep the clone outside Desktop, Documents and Downloads, where macOS limits background access. The run's own files live in the clone's `data/paper/`: the ledger, the run log, the daily tables and the backup clone. Never delete that folder.

Update the clone only deliberately, and check after each update that the frozen path still reproduces (section 6). A change that moves the frozen path's metrics or the frozen config makes the job refuse, and that is a new decision record, not an update.

## 2. The backup repository

The ledger in `data/paper/ledger/` is the only record of the run, and `data/` is git-ignored. After every run whose ledger passes its checks, the job copies the ledger into a clone of a private repository in `data/paper/backup/`, commits and pushes to `main` (`statarb.paper.backup`). Days are added or updated, never deleted.

Set it up once, by hand:

1. Create an empty **private** repository. It must be private: the ledger holds fill prices from Alpaca's data.
2. Make a key without a passphrase, since nobody is there to type one, and add `~/.ssh/statarb-ledger.pub` to the repository as a deploy key with write access:

   ```bash
   ssh-keygen -t ed25519 -N "" -C "stat-arb-from-scratch ledger backup" -f ~/.ssh/statarb-ledger
   ```

3. Add a host alias that uses only that key to `~/.ssh/config`, and accept GitHub's host key once, since the job's ssh never prompts:

   ```
   Host statarb-ledger
       HostName github.com
       User git
       IdentityFile ~/.ssh/statarb-ledger
       IdentitiesOnly yes
       IdentityAgent none
   ```

   `IdentityAgent none` matters on a host whose ssh agent holds a GitHub key: ssh offers the agent's keys first, and GitHub would accept the owner's key, which can push anywhere. The alias must come before any `Host *` block. `ssh -T git@statarb-ledger` should greet the repository by name, not the owner.

   ```bash
   ssh -T git@statarb-ledger
   ```

4. Set `STATARB_BACKUP_REMOTE` in the run script (section 3) to the repository's address with the alias as its host: `git@statarb-ledger:<owner>/<repository>.git`. The address stays out of the repository, the run log and the notes.

**A failed backup** never stops the run. It is recorded in the run log and the next daily note, and the next run retries. Without `STATARB_BACKUP_REMOTE` the backup is recorded as not configured. After changing the address, delete `data/paper/backup/`: the job will not push from a clone of another remote.

**To restore the ledger,** copy `ledger/*.parquet` from the backup repository into `data/paper/ledger/`. The next run checks the chain.

## 3. The run script

Both jobs run through one script outside the repository, which sets their working directory, `PATH`, settings and keys. The scheduler and every run by hand call it, so each setting lives in one place.

### The Alpaca keys

The download reads the keys from `APCA_API_KEY_ID` and `APCA_API_SECRET_KEY` and fails without them. They never go in the repository, a config file, the script or the scheduler's file. Keep them where the host keeps secrets, and have the script read them at run time:

- **macOS:** in the login keychain, added once with `security`:

  ```bash
  security add-generic-password -a "$USER" -s alpaca-paper-key-id -w
  ```

  ```bash
  security add-generic-password -a "$USER" -s alpaca-paper-secret -w
  ```

  Each prompts for the value, so it stays out of the shell history.
- **Linux:** in a file only the user can read, outside the clone, such as `~/.config/stat-arb/alpaca.env` with mode 600, holding the two `NAME=value` lines.

The drift report downloads nothing and needs no keys.

### The script

`~/bin/stat-arb-job`, made executable with `chmod 700`. Replace `/path/to/stat-arb-forward` with the job's clone, `/path/to/raw` with the raw store that holds the pinned snapshot, `<owner>/<repository>` with the backup repository and `/path/to/uv` with the output of `command -v uv`. Check that the `PATH` given includes the directories of `git` and `ssh`.

```sh
#!/bin/sh
# The forward run's jobs: stat-arb-job daily|drift|momentum [options]
set -eu
case "${1:-}" in
    daily|drift|momentum) job=$1; shift ;;
    *) echo "usage: stat-arb-job daily|drift|momentum [options]" >&2; exit 2 ;;
esac
cd /path/to/stat-arb-forward
export PATH="/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin"
export STATARB_RAW="/path/to/raw"
export STATARB_BACKUP_REMOTE="git@statarb-ledger:<owner>/<repository>.git"
export STATARB_MOMENTUM_BACKUP_REMOTE="git@statarb-momentum-ledger:<owner>/<momentum repository>.git"
if [ "$job" = daily ]; then
    # macOS. On Linux, replace these three lines with: set -a; . ~/.config/stat-arb/alpaca.env; set +a
    APCA_API_KEY_ID=$(security find-generic-password -s alpaca-paper-key-id -w)
    APCA_API_SECRET_KEY=$(security find-generic-password -s alpaca-paper-secret -w)
    export APCA_API_KEY_ID APCA_API_SECRET_KEY
fi
if [ "$job" = momentum ]; then
    exec /path/to/uv run python -m statarb.paper.momentum daily "$@"
fi
exec /path/to/uv run python -m "statarb.paper.$job" "$@"
```

The momentum job downloads nothing, so it needs no Alpaca keys; `STATARB_MOMENTUM_BACKUP_REMOTE` is its backup's address (section 7).

If a key cannot be read, for instance from a login keychain locked after sleep, the script stops before the job starts. The run log then has no line for that run; the scheduler's log has the error, and the next run retries.

### Check it

A run as of a time before the first session is due finds nothing to process and only backs up. On an empty ledger it clones the backup repository and reports `"backup": "up to date: the ledger is empty"`:

```bash
~/bin/stat-arb-job daily --no-download --now 2026-11-16T12:00-05:00
```

## 4. When it runs

`[run] run_time` in `config/paper.toml` is 06:00 New York time. A session is processed by the first run on a later New York date at or after the run time; a run before 06:00 New York treats the previous day as today, and takes or reuses only a snapshot named for that day. Why it waits until then is in [`time-discipline.md`](time-discipline.md). So the scheduler does not need the exact time, and can fire more than once:

- **Fire every day, weekends included.** A run with nothing due takes a few seconds and changes nothing but the run log.
- **Pick a local time at or after 06:00 New York on every day of the year,** with a few minutes of margin for a slow clock. In Central Europe, 13:15, the time decision record 0007 sets, is 07:15 New York for most of the year and 08:15 in the weeks when the two change their clocks on different dates. It stays after 06:00 New York if the host moves to London.
- **Overlapping runs are safe:** the second finds the lock held and exits with an error, changing nothing.

The job exits:
- **0** when it processed every due session or found none;
- **1** when it refused or stopped short. The reason is printed and recorded in `data/paper/runs.jsonl`;
- **with a traceback** on an unexpected error, which is also recorded as `failed`.

A failed backup does not change the exit code.

## 5. The scheduler

Schedule two jobs:

- **The daily job** every day at 13:15.
- **The drift report** on Sundays at 14:15. No session is due on a Sunday, so the daily job finishes in seconds and the two do not hold the lock at once. On Saturdays the daily job processes Friday's session, download included.

If the two do overlap, as when a host that slept through both wakes and starts them together, the drift report exits with an error and changes nothing. Nothing is lost: each report covers the run from its first session, so next week's covers this week too, and `~/bin/stat-arb-job drift` writes it at once. Like the daily job, the drift report refuses and writes nothing if the config differs from the frozen record or a config overlay is set.

### launchd (macOS)

`~/Library/LaunchAgents/local.stat-arb-forward.daily.plist`. launchd does not expand `~`, so write the script's full path, with your home folder in place of `/Users/you`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>local.stat-arb-forward.daily</string>
    <key>ProgramArguments</key>
    <array>
        <string>/Users/you/bin/stat-arb-job</string>
        <string>daily</string>
    </array>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key>
        <integer>13</integer>
        <key>Minute</key>
        <integer>15</integer>
    </dict>
    <key>StandardOutPath</key>
    <string>/path/to/stat-arb-forward/data/paper/daily.log</string>
    <key>StandardErrorPath</key>
    <string>/path/to/stat-arb-forward/data/paper/daily.log</string>
</dict>
</plist>
```

`local.stat-arb-forward.drift.plist` is the same with `drift` in place of `daily` in the label, the arguments and the log's name, and Sundays at 14:15 (`Weekday` 0 is Sunday):

```xml
    <key>StartCalendarInterval</key>
    <dict>
        <key>Weekday</key>
        <integer>0</integer>
        <key>Hour</key>
        <integer>14</integer>
        <key>Minute</key>
        <integer>15</integer>
    </dict>
```

Load both:

```bash
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/local.stat-arb-forward.daily.plist
```

```bash
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/local.stat-arb-forward.drift.plist
```

launchd runs a job missed while the host was asleep when it wakes, once however many were missed. An agent in `~/Library/LaunchAgents` runs in its user's login session.

### cron or systemd (Linux)

With cron, on a host on UTC:

```
15 11 * * * $HOME/bin/stat-arb-job daily >> /path/to/stat-arb-forward/data/paper/daily.log 2>&1
15 12 * * 0 $HOME/bin/stat-arb-job drift >> /path/to/stat-arb-forward/data/paper/drift.log 2>&1
```

cron skips a time at which the host was off; the next day's run catches up. A systemd user timer can take New York time directly (`OnCalendar=*-*-* 06:15:00 America/New_York`, with `Persistent=true` so a missed time runs at the next start), with the script as its service's `ExecStart`, and a second timer for the drift report on Sundays an hour later.

## 6. After it starts

- **Each run** appends a line to `data/paper/runs.jsonl` with its status, the sessions due and processed, the reproduction check, the backup, its duration and its peak memory.
- **Each stage** writes a line to stderr, and so to `daily.log`, with the UTC time as it starts and its duration as it ends: the frozen check, the price snapshot, its tables, the reproduction check, each session and the backup. A stage with a start line and no end line is the one still running, or the one a crash stopped.
- **Each processed session** writes a note to `reports/phase-06/daily/`.
- **The weekly drift report** reads the run log and the ledger, and writes to `reports/phase-06/drift/`.

**The first run.** Start the first run that downloads by hand, `~/bin/stat-arb-job daily`, and check it end to end: the download, the tables built into `data/paper/processed/`, the reproduction check, the ledger day, the note and the backup. Then record its time, memory and disk in [`requirements.md`](requirements.md); its line in the run log has the time and memory.

### Each week

After the drift report, commit the week's daily notes and the report in one pull request. Make the branch in a separate worktree, so the job's clone stays on `main`. The job ignores the two folders when it records whether the tree is clean, so the notes it has not committed do not mark later runs as dirty. Each command changes into the job's clone first, so it can run from any folder; from a development checkout, the same steps would branch from it and copy its notes instead.

```bash
cd /path/to/stat-arb-forward && git fetch && git worktree add ../stat-arb-week -b docs/week-2026-11-23 origin/main
```

```bash
cd /path/to/stat-arb-forward && cp -R reports/phase-06/daily reports/phase-06/drift ../stat-arb-week/reports/phase-06/
```

```bash
cd /path/to/stat-arb-forward && git -C ../stat-arb-week add reports/phase-06/daily reports/phase-06/drift && git -C ../stat-arb-week commit -m "docs(phase-06): add the week of 2026-11-23" && git -C ../stat-arb-week push -u origin HEAD
```

Open the pull request, then remove the worktree with `cd /path/to/stat-arb-forward && git worktree remove ../stat-arb-week`.

**Pulling `main` into the job's clone.** Once weekly pull requests are merged, `main` holds notes that the clone has as untracked files, and git refuses a pull that would overwrite them. With neither job running, move the two folders aside, pull, and put back the notes `main` does not have yet. It is one command, so it can run from any folder: it changes into the clone first, and stops at the first step that fails. Run from a development checkout, the same steps would move that checkout's tracked notes instead. `mkdir` fails if `../stat-arb-aside` is left from an earlier pull; delete it first, once its notes match the clone's.

```bash
cd /path/to/stat-arb-forward && mkdir ../stat-arb-aside && mv reports/phase-06/daily reports/phase-06/drift ../stat-arb-aside/ && git pull --ff-only && rsync -a --ignore-existing ../stat-arb-aside/ reports/phase-06/
```

Then check that the config still matches the frozen record and that the frozen path still reproduces. A run by hand with no session due skips the reproduction check, so run both checks on their own, offline and without keys, with the raw store that holds the pinned snapshot:

```bash
cd /path/to/stat-arb-forward && uv run --offline --locked python -m statarb.paper.frozen && STATARB_RAW=/path/to/raw uv run --offline --locked python -m statarb.paper.reproduce
```

Once both pass, delete `../stat-arb-aside`: the clone now holds every note in it.

### Exploring the ledger

The ledger explorer reads the job's ledger from a development checkout, so the job's clone needs nothing installed and no change. In the development checkout, install the `explore` group once, then open the app on the job's clone, here beside it:

```bash
uv sync --locked --group explore
```

```bash
uv run --group explore marimo run notebooks/ledger.py -- --root ../stat-arb-forward
```

It serves on 127.0.0.1 and opens a browser tab: the book after any day's open, the trades and P&L over a window, attribution by ticker, sector or side, holding spells, one ticker's history, the expected moves behind the next open, and each day's health. Its header says whether the ledger is up to date or how many sessions the daily job would process if it ran now, by the job's own rule. It only reads. It runs in marimo's dark theme, set by `[tool.marimo.display] theme` in `pyproject.toml`; change it to `"light"` there and restart the app, and the charts follow. Keep what it shows on the machine: no screenshots or exported tables in the repository or anywhere public ([decision record 0003](decisions/0003-data-sources-alpaca-and-wikipedia.md)). `marimo edit` on the same file also checks marimo.io for a newer version once a day; set `MARIMO_SKIP_UPDATE_CHECK=1` to stop it. `marimo run` does not check.

**From the command line.** The same views are in SQL for the [DuckDB](https://duckdb.org) command-line client (`brew install duckdb`). From the development checkout:

```bash
STATARB_LEDGER_ROOT=../stat-arb-forward duckdb -init notebooks/ledger.sql
```

It lists its views on start (`FROM guide;` shows them again) and writes nothing: the database is in memory. If it waits five seconds on start and reports a timeout reading the terminal's background colour, the terminal does not answer DuckDB's query for it: add `-dark-mode` or `-light-mode` to the command. Some queries to start from:

```sql
FROM book_on();                                    -- the book after the latest open
FROM trades WHERE date >= current_date - 7;        -- the last week's trades
SELECT sector, sum(net_usd) AS net FROM earned GROUP BY ALL ORDER BY abs(net) DESC;
FROM history('SPY');                               -- one name, day by day
```

`tests/test_ledger_sql.py` holds each SQL view to the Python view of the same name, so the two cannot drift apart.

### When a run refuses

Its line in the run log says why:

- **the config differs from the frozen record:** restore the config. A deliberate change is a new decision record;
- **the reproduction check fails:** the code or the pinned snapshot no longer gives the frozen path's logged metrics. Find out why before the next run; never edit the frozen record to fit;
- **the ledger fails its integrity check, or a session is missing from it:** restore the ledger from the backup repository;
- **a session the snapshot lacks** stops the run there, and the next run retries it.

A solver failure is not a refusal: the book is held, as in the backtest, and the ledger and the note record it.

## 7. The momentum forward run

[Decision record 0010](decisions/0010-momentum-forward-run.md) runs two momentum strategies, total-return and residual momentum through the decile sort, over the same sessions as the reversal run, from 2026-11-16. `statarb.paper.momentum daily` steps each with the daily job's own code, from the same clone, with its own lock, so it never blocks the reversal job or is blocked by it. Its settings are in `config/momentum_forward.toml`, and its files under `data/paper-momentum/`: a ledger and run log per path in `data/paper-momentum/<path>/`, its tables and its backup clone. Its notes go to `reports/phase-08/forward/daily/<path>/`. The reversal job's dirty flag ignores them, and its own ignores the reversal job's.

**It never downloads, and follows the reversal ledger.** Each ledger day of the reversal run names the snapshot it was built from. The momentum job reads each due session from that snapshot in the raw store, so the two runs read the same bars for every session, late ones included. A session the reversal run has not yet recorded is waited for once, for up to an hour, checking every 30 seconds, in case the daily job is still running. After that the run stops there as `incomplete`, exits 1, and the next run retries. So does a session whose snapshot is missing from the raw store or incomplete. It refuses to start if `[paths] paper` of `config/momentum_forward.toml` overlaps the reversal run's folder, or if `STATARB_MOMENTUM_BACKUP_REMOTE` is the reversal run's backup address.

**Before any session** it checks each path's frozen record (`reports/phase-08/forward/frozen-<path>.json`) and rebuilds each path's backtest on reference tables from the pinned snapshot, requiring the metrics of its logged entry exactly. To run those checks by hand in the clone:

```bash
cd /path/to/stat-arb-forward && uv run --offline --locked python -m statarb.paper.momentum frozen && uv run --offline --locked python -m statarb.paper.momentum reproduce
```

**The backup** goes to a second private repository, with each path's ledger in a folder of the path's name. Set it up as in section 2 with its own key, since GitHub takes a deploy key for one repository only: `~/.ssh/statarb-momentum-ledger`, the host alias `statarb-momentum-ledger`, and the address in `STATARB_MOMENTUM_BACKUP_REMOTE`. Its clone is `data/paper-momentum/backup/`.

**Schedule it after the daily job,** so the session is in the reversal ledger when it looks: every day at 13:45, as for the daily job in section 5. For launchd, `local.stat-arb-forward.momentum.plist` is the daily job's with `momentum` in place of `daily` in the label, the arguments and the log's path under `data/paper-momentum/`, and `Minute` 45. With cron, `45 11 * * *`.

**Catching up past sessions** needs one run. It processes every session the reversal ledger holds, in order, each from its recorded snapshot, building the tables of each snapshot in turn; the raw store keeps every snapshot. Run it by hand after that day's daily job has finished, so the reversal ledger holds yesterday's session, and before loading the schedule, so the first scheduled run finds only the latest session due. Started earlier, it processes every recorded session, waits up to an hour for yesterday's, and then exits 1 as `incomplete`.

```bash
~/bin/stat-arb-job momentum
```

Both paths' ledger days then name the same snapshot as the reversal ledger's day, which `snapshot` in each ledger shows. A path's `duration_seconds` in its run log counts from the start of the run, so the second path's includes the first's.
