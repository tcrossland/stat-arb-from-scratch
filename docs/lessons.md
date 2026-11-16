# Lessons

The mistakes a pipeline like this invites, and what stops each one. Each row is one lesson: the phase it entered, the episode that taught it, and the test or check that enforces it now.

The episodes are told in the phase reviews and decision records: what happened, how it was found, what it would have cost. This page only indexes them. Each phase review adds a row for every lesson the phase built in. Rules adopted at setup have no episode.

| Lesson | Entered in | Episode | Enforced by |
|---|---|---|---|
| Tests never touch the network | setup | | [`tests/conftest.py`](../tests/conftest.py) |
| Every installed distribution's licence is checked, dependencies of dependencies included | setup | | [`tests/test_licences.py`](../tests/test_licences.py) |
