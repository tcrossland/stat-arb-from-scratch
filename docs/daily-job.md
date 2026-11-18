# Running the daily job

The forward run trades the strategy frozen by [decision record 0007](decisions/0007-forward-run.md) on a simulated book, one New York session at a time. This page sets up its two scheduled jobs:

- **The daily job,** `statarb.paper.daily`, downloads the day's snapshot and processes every due session into the ledger. It also writes a daily note and backs the ledger up.
- **The weekly drift report,** `statarb.paper.drift`, compares the run with its backtest.

Neither places an order anywhere.

## What the host needs

- **A Unix-like system:** Linux or macOS. Windows is not supported, because the job's lock uses `fcntl`.
- **A clone of the repository used only by the job** (below), with `uv sync --locked` done and `git` and `ssh` installed. On macOS, LightGBM needs `libomp` (README, "Running it").
- **The pinned snapshot** in the raw store: the one named in `[source]` of `config/data.toml`. The reproduction check rebuilds the frozen path from it before every run.
- **Network access** to Alpaca's market data API (`data.alpaca.markets`) for the daily download, and to the git host for the backup.
- **The keys of an Alpaca account** in the job's environment, as `APCA_API_KEY_ID` and `APCA_API_SECRET_KEY` (section 4). The free plan of a paper-only account is enough ([decision record 0003](decisions/0003-data-sources-alpaca-and-wikipedia.md)).
- **To be on, or to wake,** some time after 06:00 New York on most days. A missed day is not lost: the next run processes every session since the last ledger day, in order.

## 1. A clone for the job

Run the job from a clone used for nothing else, on `main` at the merge of decision record 0007. A checkout used for development changes branch, and the job runs whatever is checked out. The frozen record catches a changed config. The reproduction check catches code that no longer gives the frozen path's logged metrics. Neither sees every other change.

```bash
git clone git@github.com:tcrossland/stat-arb-from-scratch.git stat-arb-forward
```

```bash
cd stat-arb-forward && uv sync --locked
```

Keep the clone outside Desktop, Documents and Downloads, where macOS limits background access. Point it at the raw store that holds the pinned snapshot with `STATARB_RAW`, an absolute path. The daily snapshots then accumulate there too. The run's own files, the ledger, the run log, the daily tables and the backup clone, live in the clone's `data/paper/`. Never delete it.

Update the clone only deliberately: pull, then run the job by hand and check that the reproduction check passes. A change that moves the frozen path's metrics or the frozen config makes the job refuse, and that is a new decision record, not an update.

## 2. The backup repository

`data/` is git-ignored, and the ledger in `data/paper/ledger/` is the only record of the run. After every run whose ledger passes its checks, the job does three things (`statarb.paper.backup`):

1. copies the ledger into `ledger/` of a clone of a private repository in `data/paper/backup/`;
2. commits what changed;
3. pushes to the repository's `main` branch.

It only adds and updates days, never deletes them. The job never creates the repository or a key; that is done once by hand.

1. Create an empty, **private** repository and put its SSH address in `[backup] remote` in `config/paper.toml`. It must be private: the ledger holds fill prices from Alpaca's data.
2. Make a key that can push to that repository and nothing else, without a passphrase, since nobody is there to type one:

   ```bash
   ssh-keygen -t ed25519 -N "" -C "stat-arb-from-scratch ledger backup" -f ~/.ssh/stat-arb-ledger
   ```

   Add `~/.ssh/stat-arb-ledger.pub` to the repository as a deploy key with write access (on GitHub, in the repository's settings under Deploy keys).
3. Give the key a host alias in `~/.ssh/config`, so that only this repository uses it:

   ```
   Host github-stat-arb-ledger
       HostName github.com
       User git
       IdentityFile ~/.ssh/stat-arb-ledger
       IdentitiesOnly yes
   ```

   Use the alias in place of the host name in `[backup] remote`, for example `git@github-stat-arb-ledger:<owner>/<repository>.git`.
4. Accept the host's key once by hand. The job runs ssh with `BatchMode=yes`, so it fails rather than asks:

   ```bash
   ssh -T git@github-stat-arb-ledger
   ```

5. Check it from the job. A run as of a time before the first session is due finds nothing to process and does only the backup, so on an empty ledger it clones the repository and reports `"backup": "up to date: the ledger is empty"`:

   ```bash
   uv run python -m statarb.paper.daily --no-download --now 2026-11-16T12:00-05:00
   ```

   The run log records the run with the time given.

A failed backup never stops the run. It is recorded in the run's line of `data/paper/runs.jsonl`, printed with the run's result, and shown in the next daily note; the next run retries the push. The job refuses to push from a backup clone whose remote is not `[backup] remote`: delete `data/paper/backup/`, and the next run clones the new remote.

To restore the ledger on a new clone, clone the backup repository and copy `ledger/*.parquet` into `data/paper/ledger/`; the job's integrity check verifies the chain on its next run.

## 3. When it runs

`[run] run_time` in `config/paper.toml` is 06:00 New York time. A session is processed by the first run on a later New York date at or after the run time; a run before 06:00 New York treats the previous day as today. Why it waits until then is in [`time-discipline.md`](time-discipline.md). So the scheduler does not need the exact time, and can fire more than once:

- **Fire every day, weekends included.** A run with nothing due takes a few seconds and changes nothing but the run log.
- **Pick a local time at or after 06:00 New York all year,** with a few minutes of margin for a slow clock.
  - 11:15 UTC is 06:15 in New York in winter and 07:15 in summer. So 11:15 UTC, converted to the host's summer time (its largest offset from UTC), is late enough on every day.
  - On a host in Central Europe that is 13:15, the time decision record 0007 sets. It is 07:15 New York for most of the year, and 08:15 in the weeks when Europe and the US change their clocks on different dates.
  - A host that moves between Central Europe and London keeps 13:15, which is later still in London.
- **Overlapping runs are safe:** the second finds the lock held and exits with an error, changing nothing.

The job exits:
- **0** when it processed every due session or found none;
- **1** when it refused or stopped short. The reason is printed and recorded in `data/paper/runs.jsonl`;
- **with a traceback** on an unexpected error, which is also recorded as `failed`.

A failed backup does not change the exit code.

## 4. The scheduler

Schedulers start jobs with a short `PATH` and in another directory. In each example, replace `/path/to/stat-arb-forward` with the job's clone, `/path/to/raw` with the raw store and `/path/to/uv` with the output of `command -v uv`, and check that the `PATH` given includes the directories of `git` and `ssh`.

### The Alpaca keys

The download reads the keys from `APCA_API_KEY_ID` and `APCA_API_SECRET_KEY` and fails without them. They never go in the repository, a config file or the scheduler's own file, which is plain text. Keep them where the host keeps secrets, and have the scheduler's command read them at run time:

- **macOS:** in the login keychain, added once with `security`:

  ```bash
  security add-generic-password -a "$USER" -s alpaca-paper-key-id -w
  ```

  ```bash
  security add-generic-password -a "$USER" -s alpaca-paper-secret -w
  ```

  Each prompts for the value, so it stays out of the shell history. A login keychain set to lock after sleep or inactivity makes the read fail; that run fails and the next one retries.
- **Linux:** in a file only the user can read, outside the clone, such as `~/.config/stat-arb/alpaca.env` with mode 600, holding the two `NAME=value` lines.

The weekly drift report downloads nothing and needs no keys.

### launchd (macOS)

`~/Library/LaunchAgents/local.stat-arb-forward.daily.plist`, at 13:15 local time:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>local.stat-arb-forward.daily</string>
    <key>ProgramArguments</key>
    <array>
        <string>/bin/sh</string>
        <string>-c</string>
        <string>APCA_API_KEY_ID="$(security find-generic-password -s alpaca-paper-key-id -w)" APCA_API_SECRET_KEY="$(security find-generic-password -s alpaca-paper-secret -w)" exec /path/to/uv run python -m statarb.paper.daily</string>
    </array>
    <key>WorkingDirectory</key>
    <string>/path/to/stat-arb-forward</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin</string>
        <key>STATARB_RAW</key>
        <string>/path/to/raw</string>
    </dict>
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

```bash
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/local.stat-arb-forward.daily.plist
```

launchd runs a job missed while the host was asleep when it wakes, once however many were missed. An agent in `~/Library/LaunchAgents` runs in its user's login session.

### cron or systemd (Linux)

With cron, on a host on UTC:

```
PATH=/usr/local/bin:/usr/bin:/bin
15 11 * * * cd /path/to/stat-arb-forward && set -a && . ~/.config/stat-arb/alpaca.env && STATARB_RAW=/path/to/raw && set +a && /path/to/uv run python -m statarb.paper.daily >> data/paper/daily.log 2>&1
```

cron skips a time at which the host was off; the next day's run catches up. A systemd user timer can take New York time directly (`OnCalendar=*-*-* 06:15:00 America/New_York`, with `Persistent=true` so a missed time runs at the next start), with the same command in its service and the keys in `EnvironmentFile`.

### The weekly drift report

`statarb.paper.drift` writes the week's report to `reports/phase-06/drift/`. Schedule it once a week after the daily job's last run of the week, on Saturdays at the daily job's time, in the same way with `statarb.paper.drift` in place of `statarb.paper.daily`. It needs no keys. It takes the job's lock, so if the two overlap it exits with an error and changes nothing. Like the job, it refuses and writes nothing if the config differs from the frozen record or a config overlay is set.

## 5. After it starts

- **Each run** appends a line to `data/paper/runs.jsonl` with its status, the sessions due and processed, the reproduction check and the backup.
- **Each processed session** writes a note to `reports/phase-06/daily/`.
- **The weekly drift report** reads both.

Check the first run that downloads by hand, end to end: the download, the tables built into `data/paper/processed/`, the reproduction check, the ledger day, the note and the backup. Then record its time, memory and disk in [`requirements.md`](requirements.md).

**Committing:** once a week, after the drift report, commit the week's daily notes and the report from the job's clone on a branch of their own, and open one pull request. The job ignores those two folders when it records whether the tree is clean, so uncommitted notes do not mark later runs as dirty.

**When a run refuses,** its line in the run log says why:

- **the config differs from the frozen record:** restore the config. A deliberate change is a new decision record;
- **the reproduction check fails:** the code or the pinned snapshot no longer gives the frozen path's logged metrics. Find out why before the next run; never edit the frozen record to fit;
- **the ledger fails its integrity check, or a session is missing from it:** restore the ledger from the backup repository;
- **a session the snapshot lacks** stops the run there, and the next run retries it.

A solver failure is not a refusal: the book is held, as in the backtest, and the ledger and the note record it.
