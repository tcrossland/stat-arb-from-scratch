# Phase 5: ML signal

Drafted at setup, and revised at the start of the phase with what earlier phases found.

## Goal

Train a model that predicts next-day residual returns from a set of features, and find out whether it adds anything over the baseline signal once both are run through the phase 4 optimiser and the phase 3 cost model.

## Revised at the start of the phase

Phase 4 built the optimiser, its risk models and the `Policy` paths; its review says what carries forward. Phase 4 found that the optimiser cuts risk, not losses: it holds a neutral book and raises gross Sharpe, then spends the gain on turnover, and no path clears the deflated-Sharpe bar. Its best result is the three-day lookback, and that is a 2020 result. This revision makes the brief concrete where that reaches phase 5. The values live in `config/models.toml`, set before any model is trained, so no result can move them.

### Carried from phase 4

- **One pipeline for every forecast.** The model's forecast and the baseline go through the optimiser at its phase 4 headline: λ = 30, κ = 1, no turnover budget, a $1,000 minimum trade, no re-solve, Model A for residuals and risk, filled at the open of *t+1* under phase 3's headline cost model, at $500k and $5m. Beside it, every forecast also runs through phase 3's *k* = 5 decile sort, which shows its gross edge without the calibration, and phase 3's no-trade zone, which beat the optimiser in every phase 4 comparison. The rules are listed in config.
- **The benchmark to beat** is the three-day lookback through the optimiser, phase 4's best path, beside the baseline (*n* = 1). Both are phase 3 variants from `config/costs.toml`, unchanged. Every comparison is read by year before the pooled figure, since phase 4's best result was one year.
- **κ stays at 1.** Phase 4 found net Sharpe rising with κ up to the edge of its sweep, but that was seen after the returns. A different κ is a new trial, and if one is tried it is chosen inside each walk-forward training window. Choosing it there would need an optimiser path over every training window for each candidate, about 100 s each, so this phase does not tune κ; every optimiser path here is at κ = 1.
- **The calibration.** Every forecast, the model's and the baseline's, is converted to an expected 5-day residual move by phase 3's trailing calibration (252 signal dates, at least 126), the optimiser's *h*, so its risk scaling and headline settings stay exactly as in phase 4 and the comparison isolates the forecast. Phase 4 found that κ = 1 under-prices trading, which suggests the pooled 5-day calibration overstates what a trade earns. The model's forecast inherits that question, and the review reports the calibration slope beside the results.
- **Cost of a run.** An optimiser path takes about 100 s on the full history. With four forecasts and two book sizes the runner has 8 optimiser paths, about a quarter of an hour beside the 48 model fits, run in the background and clear of 13:15 local time.

### Dates

- **Holdout:** 2025-11-14 to 2026-11-13, the snapshot's last 12 months. **Development end:** 2025-11-13. Both are in `config/models.toml`.
- **The first walk-forward test block starts on 2020-01-02.** Residuals start on 2016-10-04, so the first model trains on a little over three years.
- **Runners stop at the development end and refuse holdout dates.** The development runner cuts every table it loads at the development end before anything is computed, and refuses a config whose development end is on or after the holdout start. IC and backtests read only rows whose target is known by the close of 2025-11-13, so the last decision dates of the last block, whose targets fall in the holdout, are left out.
- **The holdout is read once, at the end of this phase,** by its own runner, after the final configuration is fixed and logged. It refuses a dirty tree, a configuration that differs from the last development run's, and a second read. The holdout's walk-forward restarts its blocks on 2025-11-14, so every development block, and every development model, is the same whether or not the holdout is loaded; the runner retrains the development models and checks each against its logged hash. Nothing is chosen from the holdout, so it adds no trials, and the review says it was read once.
- **The holdout is clean for the model only.** Phases 2 to 4 ran through 2026-11-13 and chose the baseline, the three-day lookback, the zone and the optimiser headline with that year in the sample. Their runners are unchanged and their reports still rebuild byte for byte; the review states the caveat.
- **Trials and the holdout count only what is done in this repository.** The prior set is every position path in this repository's logs up to phase 4.

### Settled before any code

- **Features: fifteen,** as listed below: residual sums over 1, 3, 5 and 20 days; residual volatility over 20 and 60 days (at least 75% of the window present); volume over its median of the previous 20 days, on one share basis across splits (phase 1's event ratio); the day's high-low range over the close; the distance of the total-return index from its high and low over 20 and 60 days; SPY's 20-day volatility; the cross-sectional dispersion of members' total returns on the day; and sector. Phase 1's event flag is the volume ratio at 3 or more, a split the tree can make itself, so it is not a separate feature. Highs and lows for the distances are of the close-to-close total-return index, so splits and dividends do not register as moves. Values stay on their natural scale, not ranked per day, so the regime features let a tree condition on the level. Features are recomputed from the processed tables in each run, not stored.
- **A cross-sectional feature counts only stocks known on *t*.** The tables' stock axis is every stock with a residual anywhere in the loaded tables, so a cross-section over that axis depends on whether a stock has a residual later. Dispersion on *t* counts the members with a residual on or before *t*, which is what a live run can compute.
- **Target:** the residual return over the next *H* days, ranked across members each day and scaled to [−0.5, 0.5]; *H* = 1 is the headline and *H* = 3 the variant. Squared-error loss on the ranked target.
- **Walk-forward:** test blocks of 63 trading days and an expanding window. The model for a block is trained at the close of the block's first day on every member-day whose target is known by then, which for an *H*-day target means rows up to *H* days before the block starts: that is the purge. In a walk-forward that only trains on the past, an embargo after a test block removes nothing, because no training set follows the block it predicts; the splitter implements a 5-day embargo anyway, for the inner validation split and any later scheme that is not purely forward, and a test checks both.
- **Hyperparameters,** chosen inside each training window only: a grid of `num_leaves` 15 and 63 by `min_data_in_leaf` 500 and 2,000, chosen on the last 252 signal dates of the training window with the purge between the inner training and validation sets, and the number of trees by early stopping (50 rounds, at most 1,000) on the same validation set. Grid points are compared on mean daily rank IC over the validation days; early stopping uses squared error, the loss. The chosen point is refitted on the whole window with that number of trees. Learning rate 0.05, feature and row fractions 0.8, bagging every round, all fixed. Every grid point is logged; the walk-forward picks one per block, so grid points are not position paths.
- **Determinism:** LightGBM with `deterministic`, `force_row_wise`, a fixed seed and a fixed thread count, so a model rebuilt from the same data and config is byte-identical, and a test checks it.
- **Common dates.** Every path starts flat on the first date every forecast has a calibrated move and ends on 2025-11-13, so the baseline and the three-day lookback are compared with the model over the same days.
- **Trials.** Each position path (forecast and rule) is a trial, added to the phase 2 to 4 set; book sizes are not separate trials, as in phase 4. The baseline's and the three-day lookback's paths repeat prior paths over fewer dates and add none. The bar is phase 3's.

### Lessons this phase builds in

Each has its own row in [`docs/lessons.md`](../../lessons.md).

- **The look-ahead test also catches a feature that depends on whether a later row exists:** a cross-section over stocks whose rows start later, a feature computed from the next row's presence, or a forward-filled gap. The perturbation test cannot see these, since it changes values after a cut-off and leaves which rows exist alone. The contract in `tests/contract/test_signals.py` therefore also builds every registered signal, and the features, from tables cut at a date and from the whole tables, with a stock whose rows start after the cut and rows removed after it, and requires identical values up to the cut. A test keeps a dispersion over the whole stock axis as a known defect and checks that the contract fails it. The development runner measures what that defect would have cost: on the development data, the days on which the defective dispersion differs from the correct one, and the median and largest difference. That is a statistic of a feature, not of a return, so it adds no trial; no model is trained or backtested on the defective definition.
- **The model library sits behind a small interface, selected in config:** fit with early stopping, predict, feature contributions, gain, and save returning the file's SHA-256. LightGBM is the one implementation; a second library would be a config change whose models are checked byte for byte, and comparing one is a set of new trials for a later phase.
- **Runners stop at the development end and refuse holdout dates,** as above, with a test for each refusal.

### The multi-period variant is deferred

The phase 4 backlog walk moved the multi-period optimiser into this brief: costs exceeded the gross return in all but three of phase 4's 34 optimiser pairs, and every step towards trading less helped. It is not built in this phase, for two reasons:

- **Its trials would count against the bar the model must clear.** Every partial-adjustment path is a new position path, and the deflated-Sharpe bar rises with the number of trials. Built here, it would raise the bar the model's forecast is judged against, in the phase whose question is whether that forecast adds anything.
- **A result would mix the forecast with the trading rule.** The aim portfolio blends forecasts at several horizons, weighted by how fast each decays, so the variant needs the model's forecasts at several horizons and their decay rates, which are what this phase builds and measures. Run together, a gain or a loss could not be put down to the forecast or to the rule. Comparing the forecast and the baseline through the same one-period optimiser keeps the rule fixed.

It goes back to [`docs/backlog.md`](../../backlog.md) as "Multi-period optimiser", triggered by this phase's review, which carries it to a later chapter or deletes it.

### Backlog items whose trigger is the phase 5 review

- **A second price source for cross-checking** and **an independent short-term reversal series.** Both need a new data source and a decision record, and neither is phase 5's work. The review walks each one.
- **Multi-period optimiser**, back in the backlog from this brief, as above. The review carries it to a later chapter or deletes it, with the forecasts' measured decay in hand.

### What earlier phases leave to this phase

Survivorship flatters the long side (phase 0), unmeasured; the open fill is a lower bound on impact; phases 2 to 4's reports must still rebuild byte for byte after this phase's changes; and the dependency-upgrade criterion stays untested, since LightGBM enters without moving an existing pin.

## Target

Next-day residual return, cross-sectionally ranked or z-scored per day. Ranking makes the target robust to market-wide volatility shifts. Also try a 3-day horizon.

## Features (all computed with data up to *t*)

- Residual returns over 1, 3, 5 and 20 days.
- Residual volatility over 20 and 60 days.
- Volume relative to its 20-day average on the day of the move. Low-volume moves should reverse more.
- High-low range relative to close.
- Earnings or event flag from phase 1.
- Distance from 20-day and 60-day high and low.
- Market regime: SPY 20-day volatility, cross-sectional dispersion of returns.
- Sector, as a categorical.

Start with ten to fifteen features. Add more only when the validation process is trustworthy.

## Validation

- Walk-forward: train on an expanding or rolling window, predict the next block (for example three months), roll forward.
- **Purge** observations whose target windows overlap the test block, and add an **embargo** of a few days after each test block. See López de Prado, *Advances in Financial Machine Learning*, chapter 7.
- Metrics: daily rank information coefficient (IC) between prediction and realised target, its mean, standard deviation and t-statistic; IC by year; IC decay at horizons 1 to 5 days.
- Hyperparameters chosen inside the training window only.

## Using the forecast in the optimiser

- **A signal like any other.** The walk-forward forecast enters through the `Signal` interface of phase 2, so it passes the same look-ahead contract and reaches the cost model and the optimiser by the same route as the baseline.
- **Calibration to return units.** The model predicts a ranked or z-scored target, so its output has no units. Before it enters the phase 4 optimiser, convert it to expected residual return with the same trailing calibration used for the baseline signal. Without this, the trade-off against risk and cost in the objective is arbitrary.
- **Multi-period trading, from the phase 4 backlog walk.** The phase 4 optimiser solves one day at a time and ignores that today's trade changes tomorrow's starting book, and its costs still exceed its gross return after the turnover controls ([phase 4 review](../phase-04/review.md#backlog-walk)). Gârleanu and Pedersen (2013) trade part of the way towards an aim portfolio that blends current and expected future forecasts, weighted by how fast each signal decays. Implement the partial-adjustment rule as a variant behind the same portfolio interface and compare it with the one-period optimiser at matched turnover. Deferred to the backlog; [the revision](#the-multi-period-variant-is-deferred) says why.
- **Optimiser parameters.** The phase 4 headline: λ = 30, κ = 1, no turnover budget, a $1,000 minimum trade. Any retuning for the model forecast happens inside each walk-forward training window, is logged in the experiment log like any other configuration, and never touches the holdout year; this phase does none ([the revision](#carried-from-phase-4)).

## Deliverables

1. `src/statarb/models/` with feature builder, walk-forward splitter (with purge and embargo) and a LightGBM wrapper behind the model interface. Trained models are saved in LightGBM's native text format, never pickle, under `data/derived/models/` (git-ignored, rebuilt by retraining), named by horizon and training window, with a SHA-256 hash of each file logged alongside its run in `experiments.jsonl`. SHAP values come from LightGBM's own TreeSHAP (`pred_contrib`), exact for trees; no `shap` package.
2. The walk-forward forecast registered as a `Signal`, so it passes the look-ahead contract, including the test where a later row is removed rather than perturbed, and reaches the calibration, the cost model and every portfolio rule by the baseline's route.
3. `statarb.models.run`, the development runner, from `config/models.toml` (strict keys), writing `reports/phase-05/experiments.jsonl` and `reports/phase-05/ml.md`; and `statarb.models.holdout`, the holdout runner, writing `reports/phase-05/holdout.md` and its log entries.
4. `reports/phase-05/ml.md`:
   - IC of each model against the baseline and the three-day lookback, with t-statistics, by year and by decay day 1 to 5
   - feature importance (gain and out-of-sample SHAP), with a short interpretation, and reversal after event moves
   - how far a dispersion over the whole stock axis would have been from the correct one: days that differ, median and largest difference
   - every forecast through the decile sort, the no-trade zone and the optimiser at both book sizes, with net return by year, against the bar
5. Tests: splitter produces no train-test overlap after purging; both sides of the purge and the embargo; features at *t* do not change when data after *t* is perturbed or when later rows are removed; the forecast calibration on day *t* does not change when data after *t* is perturbed; byte-identical models; each runner's refusals; both runners end to end on the fixture.
6. LightGBM 4.7.0 in `pyproject.toml`, its licence read from its own metadata and stated in the commit. On macOS its wheel needs the OpenMP runtime (`brew install libomp`), for the tests too: the system-runtime exception in `CLAUDE.md`, recorded in its Stack section and the install step in `README.md` in the same commit.
7. Reference docs: the features (recomputed, not stored) and the model files in `docs/data-model.md`; a walk-forward diagram (training, purge, test and embargo blocks along a time axis) and the phase 5 rows in `docs/time-discipline.md`; the new modules, runners, config and library in `docs/architecture.md`; both runners in `docs/requirements.md`; step 6 of `docs/reproduce.md`.

## Acceptance criteria

- Out-of-sample IC reported with a t-statistic, by year.
- The model is compared with the baseline on net performance through the same optimiser and cost model, not on IC alone.

## Known pitfalls

- Overfitting through repeated experimentation. Keep a log of every configuration tried in `reports/phase-05/experiments.jsonl` and hold back the most recent year as a final test set touched only once.
- Leakage through features that use the close of *t* when fills also happen at the close of *t*.
- An IC of 0.02 to 0.05 is a realistic good result. Anything far above 0.1 almost certainly means a bug.

## Review questions

- Does the model learn interpretable rules, such as weaker reversal after high-volume or earnings moves?
- Does the higher IC survive costs once the optimiser controls turnover?
- How much did the final holdout year differ from the walk-forward average?
- Does the model beat the three-day lookback through the optimiser in more years than it loses?
