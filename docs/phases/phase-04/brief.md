# Phase 4: ML signal

Drafted at setup, and revised at the start of the phase with what earlier phases found.

## Goal

Train a model that predicts next-day residual returns from a set of features, and find out whether it adds anything over the simple reversal signal once costs are included.

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

## Deliverables

1. `src/statarb/models/` with feature builder, walk-forward splitter (with purge and embargo) and a LightGBM wrapper.
2. `reports/phase-04/`:
   - IC of the model versus the plain reversal signal
   - feature importance (gain and SHAP), with a short interpretation
   - backtest of the model signal through the phase 3 cost model, alongside the baseline
3. Tests: splitter produces no train-test overlap after purging; features at *t* do not change when data after *t* is perturbed.

## Acceptance criteria

- Out-of-sample IC reported with a t-statistic, by year.
- The model is compared with the baseline on net performance, not on IC alone.

## Known pitfalls

- Overfitting through repeated experimentation. Keep a log of every configuration tried in `reports/phase-04/experiments.csv` and hold back the most recent year as a final test set touched only once.
- Leakage through features that use the close of *t* when fills also happen at the close of *t*.
- An IC of 0.02 to 0.05 is a realistic good result. Anything far above 0.1 almost certainly means a bug.

## Review questions

- Does the model learn interpretable rules, such as weaker reversal after high-volume or earnings moves?
- Does the higher IC survive costs, given that a model signal may trade more?
- How much did the final holdout year differ from the walk-forward average?
