# 0006: Partial adjustment enters phase 5, before the holdout read

**Date:** 2026-11-17
**Status:** accepted

## Context

The phase 4 review moved the multi-period optimiser into the phase 5 brief, and the brief deferred it to the backlog for two reasons: its paths would add trials and so raise the deflated-Sharpe bar the model's forecast must clear, and a variant built on forecasts at several horizons would mix the forecast with the trading rule. The backlog item's action asks for the trade rate to be set by a rule on positions before any return is seen, and for the comparison with the one-period optimiser to be at matched turnover.

This decision is taken after the phase 5 development run, with its results in [`reports/phase-05/ml.md`](../../reports/phase-05/ml.md). That run left three things in view:

- Costs exceed the gross return in six of the eight paths through the one-period optimiser, so the open question from phase 4, whether trading less and more slowly would keep more of the gross, is still the one that decides the result.
- The model at *H* = 3 has a better 3-day and 5-day IC than at 1 day, so its forecast decays more slowly than the baseline's, which is the case partial adjustment is built for.
- The holdout has not been read. A rule added now is fixed before the holdout read and runs on it like every other rule.

Choosing to add a rule after seeing development results is a researcher's choice that the trial count must carry. It does: every new path is a trial, and the bar is recomputed with them.

## Decision

1. **The rule.** A policy behind the same portfolio interface as the decile sort and the optimiser, named "partial adjustment" in `[runs] rules` of `config/models.toml`. Each day it computes an aim portfolio *w*\* and trades a fixed fraction θ of the way to it from the book as known at the decision: *w* = *w*₀ + θ(*w*\* − *w*₀), then the phase 4 $1,000 minimum-trade filter. Names the optimiser may not hold, such as those leaving the universe, close at once, as the optimiser's forced exits do. A day with no aim, where the solve fails, holds the book.
2. **The aim portfolio** is the phase 4 headline optimiser's solution with no cost term (κ = 0): the same λ = 30, the same constraints, Model A risk and each forecast's own calibrated 5-day move μ. A convex combination of two books that meet the linear constraints meets them too, so the traded book stays within the neutrality constraints and the position, ADV and gross caps up to the drift of the book held and the minimum-trade filter, as the optimiser's does after its filter.
3. **One forecast per aim.** Gârleanu and Pedersen (2013) blend forecasts at several horizons into the aim, weighted by how fast each decays. Here each path has one forecast, and with one forecast their aim reduces to a scaled Markowitz portfolio, which the κ = 0 solution is. The blend is not built: the model at *H* = 1 and at *H* = 3 stay separate forecasts, as in the development run, so no path mixes forecasts.
4. **θ is set by a rule on positions, before any return is seen.** For each forecast and book size, θ is the value on the grid 0.01, 0.02, …, 1.00 (`[partial_adjustment]` of `config/models.toml`) whose mean capital traded per day over the development dates is closest to that of the same forecast through the one-period optimiser at the headline. The rule reads only the turnover of the two paths, never a return, cost or P&L column. The aim does not depend on the book held, since κ = 0, so it is solved once per forecast and book size and every θ on the grid reuses it. The chosen θ values are logged with the run; grid points are not trials, as with phase 4's λ rule. The holdout uses the development θ unchanged and reports its turnover beside the optimiser's.
5. **Every forecast runs through it,** the model at both horizons, the baseline and the three-day lookback, at both book sizes, over the same common dates as the other rules. A forecast's effect is read within each rule and the rule's effect within each forecast, which answers the brief's concern that a result would mix the two.
6. **Trials.** Each forecast through partial adjustment is a new position path: four new trials, book sizes not separate, added to the 173 of the development run. The bar is recomputed with them.

## Consequences

- The development run is repeated from a clean tree with the new rule, and its log replaces the one now committed. The walk-forward is unchanged, so every model file and its SHA-256 are the same; the hashes already reported stay valid, and the runner checks them.
- The holdout read waits for that run, and the holdout runner refuses a configuration unlike it, so partial adjustment is read on the holdout with everything else.
- The bar rises with four more trials. A forecast that clears the bar only through partial adjustment has paid for the extra rule.
- The multi-horizon blend stays in [`docs/backlog.md`](../backlog.md) as "Multi-period optimiser", narrowed to the blend, with the phase 5 review as its trigger.
- The glossary gains θ (trade rate) and *w*\* (aim portfolio).
