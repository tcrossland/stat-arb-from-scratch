# Lessons

The mistakes a pipeline like this invites, and what stops each one. Each row is one lesson: the phase it entered, the episode that taught it, and the test or check that enforces it now.

The episodes are told in the phase reviews and decision records: what happened, how it was found, what it would have cost. This page only indexes them, with a row for every lesson a phase built in. Rules adopted at setup have no episode.

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
| The betas used on day *t* come only from returns before *t* | phase 1 | | [`tests/test_factors.py`](../tests/test_factors.py) |
| Volumes are put on one share basis before they are compared across a split | phase 1 | | [`tests/test_factors.py`](../tests/test_factors.py) |
| A sector move is dated from MSCI, S&P Dow Jones Indices or the issuer; Wikipedia only says which companies to check | phase 1 | [review](phases/phase-01/review.md#company-level-gics-reclassifications) | [`tests/test_sectors.py`](../tests/test_sectors.py) |
| Residuals are compared with raw returns on the same rows: what a factor model adds may be reliability rather than size | phase 1 | [review](phases/phase-01/review.md#what-surprised-us) | [`tests/test_factor_report.py`](../tests/test_factor_report.py) |
| Reversal is reported by year as well as pooled: one year can have none | phase 1 | [review](phases/phase-01/review.md#what-surprised-us) | [`tests/test_factor_report.py`](../tests/test_factor_report.py) |
| Charts are saved with no date or software metadata, so a rebuild writes the same bytes | phase 1 | | [`tests/test_factor_report.py`](../tests/test_factor_report.py) |
| Every registered signal passes the look-ahead contract before it is used | phase 2 | | [`tests/contract/test_signals.py`](../tests/contract/test_signals.py) |
| The engine's targets and P&L up to a day do not change with data after it, at every fill | phase 2 | | [`tests/test_backtest.py`](../tests/test_backtest.py) |
| A signal shuffled across stocks each day earns nothing on the same engine | phase 2 | | [`tests/test_backtest.py`](../tests/test_backtest.py) |
| An experiment changes a setting through a config overlay, never by editing a config file | phase 2 | | [`tests/test_config_overlay.py`](../tests/test_config_overlay.py) |
| Every log entry records the commit, uncommitted changes, the overlay and the price snapshot | phase 2 | | [`tests/test_config_overlay.py`](../tests/test_config_overlay.py) |
| Trials are counted across every experiment log in the repository, and the best is judged with the deflated Sharpe ratio | phase 2 | | [`tests/test_backtest.py`](../tests/test_backtest.py) |
| A statistic about returns is checked in P&L before it decides a design: the largest names reversed least and earned most | phase 2 | [review](phases/phase-02/review.md#what-surprised-us) | [`tests/test_backtest.py`](../tests/test_backtest.py) (the report's P&L by year, sector and size) |
| A cost estimated from prices is checked against the strategy's own signal before it is charged: the daily-price spread estimators read reversal as spread | phase 3 | [review](phases/phase-03/review.md#what-surprised-us), [record 0005](decisions/0005-spread-as-a-stated-assumption.md) | [`tests/test_spreads.py`](../tests/test_spreads.py) |
| Commission is reported per dollar traded at each book size: a per-order minimum, not the spread, binds a retail book | phase 3 | [review](phases/phase-03/review.md#what-surprised-us) | [`tests/test_costs.py`](../tests/test_costs.py) (impact against commission by book size; the report's `binding` column) |
| Every cost input on a fill comes from the day before it | phase 3 | | [`tests/test_costs.py`](../tests/test_costs.py) |
| A result is shown beside the capital it deploys: a filter can look safe by holding nothing | phase 3 | | [`tests/test_costs.py`](../tests/test_costs.py) (the report's capital columns) |
| An improvement is read by year before it is believed: the optimiser's best result is one year | phase 4 | [review](phases/phase-04/review.md#what-surprised-us) | [`tests/test_optimiser.py`](../tests/test_optimiser.py) (the report's net return by year) |
| Neutrality is judged by the P&L of what it removes as well as the exposure: it removed risk, not losses | phase 4 | [review](phases/phase-04/review.md#what-surprised-us) | [`tests/test_optimiser.py`](../tests/test_optimiser.py) (the report's fitted P&L and volatility beside each path's exposures) |
| A failed solve holds the previous book; a constraint is never relaxed | phase 4 | | [`tests/test_optimiser.py`](../tests/test_optimiser.py) |
| A tuning parameter's headline value is set by a rule on ex-ante properties, before any return is seen | phase 4 | | [`src/statarb/portfolio/config.py`](../src/statarb/portfolio/config.py) (the headline λ must be one of the rule's candidates), `statarb.portfolio.run --choose-risk-aversion` |
| Model B's residuals up to a day do not change with data after it | phase 4 | | [`tests/test_pca.py`](../tests/test_pca.py) |
| Every portfolio construction passes the same contract tests | phase 4 | | [`tests/contract/test_portfolio.py`](../tests/contract/test_portfolio.py) |
| The look-ahead test also removes the rows after a cut-off: perturbing values cannot see a value that depends on whether a later row exists | phase 5 | | [`tests/test_features.py`](../tests/test_features.py), [`tests/contract/test_signals.py`](../tests/contract/test_signals.py) |
| The model library sits behind a small interface, selected in config, and every library passes the same checks, a byte-identical rebuild among them | phase 5 | | [`tests/contract/test_models.py`](../tests/contract/test_models.py) |
| Runners stop at the development end and refuse holdout dates: the development runner cuts every table there before computing anything, and refuses tables that reach past it and a development end inside the holdout | phase 5 | | [`tests/test_models_run.py`](../tests/test_models_run.py) |
