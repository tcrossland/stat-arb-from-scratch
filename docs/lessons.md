# Lessons

The mistakes a pipeline like this invites, and what stops each one. Each row is one lesson: the phase it entered, the episode that taught it, and the test or check that enforces it now.

The episodes are told in the phase reviews and decision records: what happened, how it was found, what it would have cost. This page only indexes them. Each phase review adds a row for every lesson the phase built in. Rules adopted at setup have no episode.

| Lesson | Entered in | Episode | Enforced by |
|---|---|---|---|
| Tests never touch the network | setup | | [`tests/conftest.py`](../tests/conftest.py) |
| Every installed distribution's licence is checked, dependencies of dependencies included | setup | | [`tests/test_licences.py`](../tests/test_licences.py) |
| A source's price basis is declared and converted to unadjusted prices in one shared step; fully adjusted prices are refused | phase 0 | | [`tests/contract/test_price_sources.py`](../tests/contract/test_price_sources.py) |
| Universe membership on a day uses only data known by then | phase 0 | | [`tests/test_universe.py`](../tests/test_universe.py) |
| A download's cut-off is New York's date, never the machine's | phase 0 | | [`tests/test_exchange_time.py`](../tests/test_exchange_time.py) |
| A rebuild from a pinned snapshot is identical byte for byte | phase 0 | | [`tests/test_build.py`](../tests/test_build.py) |
| A source's foreign dividends may be net of withholding tax without saying so | phase 0 | [review](phases/phase-00/review.md#what-surprised-us), [record 0004](decisions/0004-rules-for-alpacas-data.md) rule 4 | [`tests/test_alpaca.py`](../tests/test_alpaca.py) |
| A bar with no volume is not a price | phase 0 | [review](phases/phase-00/review.md#what-surprised-us), [record 0004](decisions/0004-rules-for-alpacas-data.md) rule 1 | [`tests/test_alpaca.py`](../tests/test_alpaca.py) |
| A ticker's history can start before its own listing | phase 0 | [review](phases/phase-00/review.md#what-surprised-us), [record 0004](decisions/0004-rules-for-alpacas-data.md) rule 7 | [`tests/test_clean.py`](../tests/test_clean.py) |
| A source's action query may filter on a date other than the ex-date | phase 0 | [review](phases/phase-00/review.md#what-surprised-us), [record 0004](decisions/0004-rules-for-alpacas-data.md) rule 2 | [`tests/test_alpaca.py`](../tests/test_alpaca.py) |
| A correction to a source cites a primary source, never another price source | phase 0 | [record 0004](decisions/0004-rules-for-alpacas-data.md) rule 11 | [`tests/test_alpaca.py`](../tests/test_alpaca.py), [`tests/test_clean.py`](../tests/test_clean.py) |
| The architecture and data model pages are checked against the code | phase 0 | | [`tests/test_architecture_doc.py`](../tests/test_architecture_doc.py), [`tests/test_data_model_doc.py`](../tests/test_data_model_doc.py) |
