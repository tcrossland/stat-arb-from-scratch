# Documentation

Organised by what you want to do. Read the sections in order for the full picture, or jump to the one you need.

## Get oriented

- [`README.md`](../README.md): what the project asks, the results so far, the architecture and the rules it holds to.
- [`CLAUDE.md`](../CLAUDE.md): the working rules the project is built under with Claude Code, from time discipline to commit messages.

## Follow the story

Each phase in order: its brief, then its build commits, then its review. The tags `phase-00` to `phase-06` mark where each phase ends, so `git log phase-01..phase-02` lists phase 2's commits, and checking out a tag gives the project as that phase left it.

- [`roadmap.md`](roadmap.md): the phases, the question each one asks, and the references.
- [`phases/`](phases/): one folder per phase, with its `brief.md` and, once it ends, its `review.md`.
- [`decisions/`](decisions/README.md): the decision records, each a change of scope, data source or methodology with its reasons.

## Understand the method

- [`overview.md`](overview.md): the whole pipeline on one page, stage by stage.
- [`time-discipline.md`](time-discipline.md): what is known when, and how the project avoids look-ahead.
- [`glossary.md`](glossary.md): terms as the project uses them, and the notation, one symbol per quantity.

## Learn from the mistakes

- [`lessons.md`](lessons.md): each lesson, the phase it enters, the episode that taught it and the check that enforces it now.

## Run it

- [`reproduce.md`](reproduce.md): rebuild every published result from your own snapshot.
- [`daily-job.md`](daily-job.md): set up and run the forward paper trade, and [explore its ledger](daily-job.md#exploring-the-ledger).

## Look something up

- [`architecture.md`](architecture.md): packages, runners and config files, what each reads and writes, and the external libraries.
- [`data-model.md`](data-model.md): the stored tables, their columns, keys and join rules.
- [`requirements.md`](requirements.md): the time, memory and disk each runner needs.
- [`../config/`](../config/): the configuration, commented, one TOML file per area.
- [`backlog.md`](backlog.md): deferred work, each item with the trigger that brings it back.
- [`plans/`](plans/): plans for work large enough to need one, such as the [ledger explorer](plans/ledger-explorer.md).
