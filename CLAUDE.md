# stat-arb-from-scratch

A research project: build a simplified, daily-frequency version of a cross-sectional residual mean-reversion strategy in equities, and run it as a simulation. The aim is to evaluate a mid-frequency stat-arb pipeline end to end, honestly, not to make money. `README.md` describes the strategy and the results so far; `docs/roadmap.md` has the phases.

## Hard constraints

- **Simulation only.** No code in this repo places, routes or submits real orders, and no broker credentials are stored here. If a later phase adds a broker connection it is paper-trading only and needs an explicit decision recorded in `docs/decisions/`.
- **No look-ahead.** Every value used to make a decision at time *t* must have been knowable at *t*. This is the single most important rule in the project. See "Time discipline" below.
- **Free data only,** with one exception: MarketParquet's archive, a paid source, under decision record 0008. Any other paid source needs a decision record first.
- **No keys in the repository.** API keys are read from the environment, never from a file in the repository, a config file or a scheduler file.
- **No data values.** No prices, volumes or per-ticker returns from any source in reports, docs, commit messages or test fixtures. Reports hold statistics derived from the data; fixtures are synthetic.

## Where things are

| Document | Holds | Update it when |
|---|---|---|
| `docs/phases/phase-NN/` | each phase's `brief.md` and `review.md` | a phase starts or ends |
| `docs/decisions/` | decision records (ADRs), indexed in its `README.md` | scope, data source or methodology changes |
| `docs/backlog.md` | deferred work, each item with a trigger, why and action | work belongs to a later phase |
| `docs/plans/` | a plan for each piece of work large enough to need one, with a status line: purpose, constraints, design, steps | work needs a plan before it is built, or planned work is built or dropped |
| `docs/architecture.md` | packages, runners, config files, what each reads and writes, external libraries | a module, runner, config file or library is added or renamed |
| `docs/data-model.md` | stored tables, columns, keys and join rules | a stored table is added or changed |
| `docs/time-discipline.md` | what is known when, by phase | a timing assumption is added |
| `docs/glossary.md` | terms as this project uses them | a term is introduced |
| `docs/requirements.md` | time, memory and disk of each runner | a runner is added or its cost changes |
| `docs/README.md` | the documentation index, by what the reader wants to do | a page is added, renamed or removed |
| `docs/overview.md` | the pipeline on one page, a paragraph per stage with links to its brief and package | a phase review lands or a stage changes |
| `docs/lessons.md` | one row per lesson: the phase it enters, its episode, the check that enforces it | a lesson enters, or a review or decision record tells its episode |
| `docs/reproduce.md` | the reader's guide to rebuilding the results | a runner, a snapshot pin or the published tolerance changes |

The architecture and data model documents are empty until the first module lands. From then on a test checks each against the code.

## Numbering

- **Phases** are numbered from 0, written "phase 2" in prose and keyed `phase-02` everywhere else: `docs/phases/phase-02/`, `reports/phase-02/`, the tag `phase-02` and the commit scope `docs(phase-02)`. Work after phase 6 continues as phase 7 and on.
- **Decision records** are numbered from 0001 in the order they land, whatever phase they belong to, and listed in `docs/decisions/README.md`. A record that replaces another names it, and the replaced record's status names its successor.
- **Dates** are ISO 8601 (2026-11-16) everywhere, record headers included.
- **Symbols** follow the notation table in `docs/glossary.md`: one symbol per quantity.

## How we work

- File-first. Read the current phase brief before writing code, and do not start work that belongs to a later phase: record it in `docs/backlog.md` with a trigger instead.
- Decisions that change scope, data source or methodology go in `docs/decisions/NNNN-title.md` (short ADR: context, decision, consequences), with a line in the index.
- Keep the reference docs in the table above current in the same change as the code.
- Each number lives in one place: the phase review, or the generated report the review quotes. The README, the overview and every other page link to it rather than copy it, so a rerun that moves a number changes one file.
- Each phase starts by revising its brief with what earlier phases found, and ends with `docs/phases/phase-NN/review.md`: what was built, what the numbers showed, what surprised us, what carries forward. Confirm the reference docs are current. Then walk `docs/backlog.md`: move each item whose trigger has arrived into the next brief, turn it into a decision record, or delete it, and say which in the review.
- A phase's pull request is merged with a merge commit, never squashed or rebased, so its commits keep the hashes the experiment logs record. Once it is merged, tag the merge commit `phase-NN`, annotated `phase-NN: <phase title>`, so the tag is on `main`'s own line, includes any change made in review, and gives the project as `main` held it when the phase ended, whatever else was merged while the phase ran. Never tag before the merge. The tags `phase-00` to `phase-07` are on each pull request's last commit, the rule until phase 8, and stay there.
- Anything another phase depends on lives in `src/statarb/` with tests, not in a notebook.

## Stack

The libraries and the modules each enters through are in `docs/architecture.md`; setup is in `README.md`.

- Python 3.14, managed with `uv`, dependencies in `pyproject.toml` and pinned in `uv.lock`. A library enters `pyproject.toml` in the phase whose code first imports it, never earlier. The whole stack must install from prebuilt wheels on the pinned version; check before moving to a newer Python. A library that needs a system runtime is the one exception: the phase that adds it records the runtime here and the install step in `README.md`. So far: LightGBM (phase 5), whose macOS wheel needs the OpenMP runtime, `libomp`, from Homebrew.
- pandas 3 in long format with explicit `date` and `ticker` columns. Sort before any grouped `shift` or rolling operation, and never rely on index alignment between frames.
- Storage: TOML for hand-written config, parquet for data, JSON Lines for experiment logs, LightGBM's native text format for models. No pickle.
- Configuration in `config/*.toml`, never hard-coded paths or dates.
- Charts with matplotlib, saved with date and software metadata cleared so regenerated charts are identical.
- Functional style: pure functions of explicit inputs, frozen dataclasses changed with `dataclasses.replace`, values returned rather than appended to shared state. Runners read and write at the edges. Sequential state (the engine stepping through days) stays in a local loop inside a function that is pure at its boundary. A function whose output depends only on its arguments is one the look-ahead test can check.
- Seams only where there are two implementations or the backlog names a second: a `typing.Protocol` with plain functions or small classes behind it, chosen by name in config and logged with each run. Contract tests run every implementation of a seam through the same checks.
- Licences. The repository is MIT-licensed. Before adding a dependency, model weights or a data source, read its licence from the package's own metadata or LICENSE file, not from a mirror or aggregator, and state it in the change that adds it. Permissive licences (MIT, BSD, Apache-2.0, ISC, PSF) are fine, and so is weak file-level copyleft such as MPL-2.0 used unmodified. Copyleft (GPL, AGPL, LGPL), non-commercial or unstated terms need a decision record first. Never copy code from a copyleft project: reimplement from the paper. Data's terms of use bind as well as code licences. Data and model weights are never committed, and test fixtures are synthetic. `tests/test_licences.py` checks every installed distribution, including dependencies of dependencies, against this rule; a package whose metadata states no licence goes in its `EXCEPTIONS` with what its licence file says.

## Time discipline

The rules. What each phase may use when is in `docs/time-discipline.md`.

- Index all data by the timestamp at which it became available, not the period it describes.
- A signal computed from the close on day *t* can trade no earlier than the close of *t* (with a stated slippage assumption) or the open of *t+1*. Pick one per backtest and record it.
- Rolling estimates (betas, volatilities, z-scores) use only data up to and including *t*.
- Model training uses walk-forward splits with a purge gap and embargo. Never random k-fold on time series.
- Universe membership at *t* uses only information available at *t*. Where the free data makes this impossible (survivorship), say so in the phase review.

## Testing

- Unit tests for every transform that touches dates or alignment.
- A dedicated look-ahead test: shift future data by random noise and confirm historical signals do not change.
- Backtests must reproduce exactly from a fixed config and seed in the environment fixed by `uv.lock`. After a dependency upgrade, results must match in content even if file bytes differ.
- Tests never touch the network. They run on small synthetic fixtures committed under `tests/`; only the data build reads the cache or downloads. `tests/conftest.py` enforces this.
- `uv run ruff check` and `uv run pytest -m "not slow"` must pass before every commit, and the full `uv run pytest` before every push and every logged run. Tests that take seconds each, such as a runner end to end, are marked `slow`; a look-ahead check stays unmarked unless another unmarked test covers the same code. A commit that touches only docs needs only the tests that check docs against the code, and only when it changes a page they read. CI runs both on push to `main` and on pull requests, with the full suite, and checks each pull request's commit messages with `scripts/check_commits.py`. Ruff uses its default rules; `[tool.ruff]` in `pyproject.toml` records any exceptions. pytest runs in strict mode.

## Commits

- [Conventional Commits 1.0.0](https://www.conventionalcommits.org/en/v1.0.0/). The subject is `type(scope): summary`, in the imperative and short enough to read in `git log --oneline`; the body says why. Types: `feat`, `fix`, `docs`, `test`, `refactor`, `perf`, `build`, `ci` and `chore`. The scope is the package for code (`data`, `factors`, `backtest`, `portfolio`, `models`, `paper`) and the phase or the document for docs (`docs(phase-02): write the review`, `docs(decisions): record the data source`). The scope may be left out when a change spans several.
- **A `Results:` footer** on any commit that changes a logged result or a reported number, saying what moved and by how much, so `git log --grep '^Results:'` lists every change to the findings.
- One commit per coherent step. The history is meant to be read.
- Commits made with Claude Code keep its `Co-Authored-By` trailer.

## Writing style

British English. Plain prose in docs. No em-dashes.
