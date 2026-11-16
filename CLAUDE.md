# stat-arb-from-scratch

A research project: build a simplified, daily-frequency version of a cross-sectional residual mean-reversion strategy in equities, and run it as a simulation. The aim is to evaluate a mid-frequency stat-arb pipeline end to end, honestly, not to make money. `README.md` describes the strategy and the results so far; `docs/roadmap.md` has the phases.

## Hard constraints

- **Simulation only.** No code in this repo places, routes or submits real orders, and no broker credentials are stored here. If a later phase adds a broker connection it is paper-trading only and needs an explicit decision recorded in `docs/decisions/`.
- **No look-ahead.** Every value used to make a decision at time *t* must have been knowable at *t*. This is the single most important rule in the project. See "Time discipline" below.
- **Free data only** until a decision record says otherwise.
- **No data values.** No prices, volumes or per-ticker returns from any source in reports, docs, commit messages or test fixtures. Reports hold statistics derived from the data; fixtures are synthetic.

## Where things are

| Document | Holds | Update it when |
|---|---|---|
| `docs/phases/phase-NN/` | each phase's `brief.md` and `review.md` | a phase starts or ends |
| `docs/decisions/` | decision records (ADRs), indexed in its `README.md` | scope, data source or methodology changes |
| `docs/backlog.md` | deferred work, each item with a trigger, why and action | work belongs to a later phase |
| `docs/architecture.md` | packages, runners, config files, what each reads and writes, external libraries | a module, runner, config file or library is added or renamed |
| `docs/data-model.md` | stored tables, columns, keys and join rules | a stored table is added or changed |
| `docs/time-discipline.md` | what is known when, by phase | a timing assumption is added |
| `docs/glossary.md` | terms as this project uses them | a term is introduced |
| `docs/requirements.md` | time, memory and disk of each runner | a runner is added or its cost changes |

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
- Each phase starts by revising its brief with what earlier phases found, and ends with `docs/phases/phase-NN/review.md`: what was built, what the numbers showed, what surprised us, what carries forward. Confirm the reference docs are current. Then walk `docs/backlog.md`: move each item whose trigger has arrived into the next brief, turn it into a decision record, or delete it, and say which in the review. Tag the review's commit `phase-NN`.
- Anything another phase depends on lives in `src/statarb/` with tests, not in a notebook.

## Stack

- Python 3.14, managed with `uv`.
- Configuration in `config/*.toml`, never hard-coded paths or dates.

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
- Backtests must reproduce exactly from a fixed config and seed.

## Commits

- [Conventional Commits 1.0.0](https://www.conventionalcommits.org/en/v1.0.0/). The subject is `type(scope): summary`, in the imperative and short enough to read in `git log --oneline`; the body says why. Types: `feat`, `fix`, `docs`, `test`, `refactor`, `perf`, `build`, `ci` and `chore`. The scope is the package for code (`data`, `factors`, `backtest`, `portfolio`, `models`, `paper`) and the phase or the document for docs (`docs(phase-02): write the review`, `docs(decisions): record the data source`). The scope may be left out when a change spans several.
- **A `Results:` footer** on any commit that changes a logged result or a reported number, saying what moved and by how much, so `git log --grep '^Results:'` lists every change to the findings.
- One commit per coherent step. The history is meant to be read.
- Commits made with Claude Code keep its `Co-Authored-By` trailer.

## Writing style

British English. Plain prose in docs. No em-dashes.
