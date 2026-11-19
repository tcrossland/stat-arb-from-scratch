# Roadmap

The plan, phase by phase. The strategy, and why it is run on free daily data, is described in [`README.md`](../README.md).

## Phases

| # | Phase | Main question | Key output |
|---|-------|---------------|------------|
| 0 | Data and universe | Can we build a clean, honest daily dataset? | Parquet price panel, universe file, data quality report |
| 1 | Factor model and residuals | What part of each stock's move is idiosyncratic? | Daily residual returns, factor exposure diagnostics |
| 2 | Baseline signal and backtest | Does simple residual reversal show any edge before and after costs? | Backtest engine, first P&L curve, metrics report |
| 3 | Cost realism | How much of the edge survives realistic trading and shorting costs? | Cost model, cost-sensitivity analysis |
| 4 | Portfolio construction | Does an optimiser with neutrality and turnover control beat decile sorts? | Model B, cvxpy optimiser, comparison report |
| 5 | ML signal | Can a model learn when reversal works, and does it add anything through the optimiser after costs? | Feature set, LightGBM model, walk-forward IC report |
| 6 | Paper-trading simulation | Does the live, forward-running pipeline behave like the backtest? | Daily scheduled run, simulated ledger, drift report |
| 7 | A second source and a universe with dead names | How much does survivorship flatter the results? | Second price source, cross-check report, universe from every listed stock, survivorship report |
| 8 | Momentum | Does a strategy that trades little fail for the same reason as one that trades a lot? | Momentum signals, reversal read once on the years before 2016, momentum report |

Portfolio construction comes before the ML signal because trading costs are the binding constraint for this strategy (decision record 0002).

Phases 7 and 8 are drafted, not started: each has a brief in [`phases/`](phases/), written during the forward run. Phase 7's source is paid, under decision record 0008. Phase 8 waits for the forward run's review and a decision record for its strategy.

## Principles

- Every phase ends with a written review before the next begins.
- The baseline from phase 2 is kept running in every later comparison. A more complex method has to beat it after costs to earn its place.
- Expect the edge to shrink at each phase. A result that improves dramatically is a reason to look for a bug, usually look-ahead.
- From phase 2 onwards, log every backtest configuration in `reports/phase-NN/experiments.jsonl`. Judge the best result against the number of configurations tried.
- Every signal goes through the same `Signal` interface and the same look-ahead test, so a new one reaches the cost model and the optimiser without changes to them.

## Out of scope for now

Intraday data, real order placement, options, futures, other asset classes. Revisit after phase 6 with a decision record.

Work after phase 6 continues the numbering, as phase 7 and on, with the same brief, review and tag.

## References

Grouped by the phase they inform. Magnitudes quoted here come from abstracts; check the full text before relying on a number.

### The strategy as a whole

- Avellaneda, M. and Lee, J.-H. (2010). Statistical arbitrage in the U.S. equities market. *Quantitative Finance* 10(7), 761 to 782. [Draft PDF](https://math.nyu.edu/~avellane/AvellanedaLeeStatArb071008.pdf). The closest published version of this project: residuals against sector ETFs or PCA factors, traded with an Ornstein-Uhlenbeck s-score. Sample ends in 2007. The published Sharpe ratios differ from the 2008 draft, so cite the published version. This is the external benchmark for phases 1 and 2.
- Khandani, A. and Lo, A. (2007). What happened to the quants in August 2007? Uses a simple contrarian strategy as a proxy for equity stat arb and documents its crash. Useful context for any phase review that covers a drawdown.

### Phases 1 and 2: residuals and reversal

- Lehmann, B. (1990). Fads, martingales, and market efficiency. *Quarterly Journal of Economics* 105(1). Original weekly reversal evidence.
- Lo, A. and MacKinlay, A. C. (1990). When are contrarian profits due to stock market overreaction? *Review of Financial Studies* 3(2). The contrarian portfolio construction that later papers reuse.
- Blitz, D., Huij, J., Lansdorp, S. and Verbeek, M. (2013). Short-term residual reversal. *Journal of Financial Markets* 16(3), 477 to 504. [IDEAS](https://ideas.repec.org/a/eee/finmar/v16y2013i3p477-504.html). Residual reversal earns roughly twice the risk-adjusted return of plain reversal and survives costs in large caps after 1990. The academic version of the phase 2 baseline.
- Collin-Dufresne, P. and Daniel, K. (preliminary). [Working paper](https://business.columbia.edu/sites/default/files-efs/pubfiles/11568/str1.pdf). Estimates a reversal half-life of about 2.5 days. Marked "do not quote", so treat as background for choosing *n* = 1 to 5.
- Bailey, D. and López de Prado, M. (2014). The deflated Sharpe ratio: correcting for selection bias, backtest overfitting and non-normality. *Journal of Portfolio Management* 40(5). How to judge the best of many backtest configurations.

### Phase 3: costs and capacity

- Corwin, S. and Schultz, P. (2012). A simple way to estimate bid-ask spreads from daily high and low prices. *Journal of Finance* 67(2).
- Abdi, F. and Ranaldo, A. (2017). A simple estimation of bid-ask spreads from daily close, high, and low prices. *Review of Financial Studies* 30(12).
- Ardia, D., Guidotti, E. and Kroencke, T. A. (2024). Efficient estimation of bid-ask spreads from open, high, low, and close prices. *Journal of Financial Economics* 161. The EDGE estimator.
- Hagströmer, B. Bias in the effective bid-ask spread. [Working paper](https://www.hec.edu/sites/default/files/documents/overestEspr-v12.pdf), version of 25 September 2019. Effective spreads of S&P 500 constituents measured from trades and quotes; the anchor for the assumed spread in decision record 0005.
- De Groot, W., Huij, J. and Zhou, W. (2012). Another look at trading costs and short-term reversal profits. *Journal of Banking and Finance* 36(2). Costs fall sharply with a large-cap universe and lower-turnover construction.
- Frazzini, A., Israel, R. and Moskowitz, T. Trading costs of asset pricing anomalies. Ranks short-term reversal as the anomaly most constrained by trading costs.
- Nagel, S. (2012). Evaporating liquidity. *Review of Financial Studies* 25(7). Reversal returns as compensation for providing liquidity. A useful lens on capacity.

### Phase 4: portfolio construction

- Avellaneda and Lee (2010), above. Its PCA factors and eigenportfolios are Model B.
- Gârleanu, N. and Pedersen, L. H. (2013). Dynamic trading with predictable returns and transaction costs. *Journal of Finance* 68(6). Multi-period trading towards an aim portfolio, weighted by signal decay. Basis for the multi-period trading item in the [phase 5 brief](phases/phase-05/brief.md).

### Phase 5: ML signal and validation

- López de Prado, M. (2018). *Advances in Financial Machine Learning*. Wiley. Chapter 7 on purged and embargoed cross-validation.
- Krauss, C., Do, X. A. and Huck, N. (2017). Deep neural networks, gradient-boosted trees, random forests: statistical arbitrage on the S&P 500. *European Journal of Operational Research* 259(2). Daily S&P 500 stat arb with tree models, close to the phase 5 set-up.
- Guijarro-Ordonez, J., Pelger, M. and Zanotti, G. (2022). Deep learning statistical arbitrage. [arXiv:2106.04028](https://arxiv.org/abs/2106.04028).

### Phases 7 and 8: survivorship and momentum

Cited from memory when the briefs were drafted; check each against its full text before relying on it.

- Shumway, T. (1997). The delisting bias in CRSP data. *Journal of Finance* 52(1). What a failed stock loses after its last trade, and what leaving it out does to a backtest.
- Jegadeesh, N. and Titman, S. (1993). Returns to buying winners and selling losers: implications for stock market efficiency. *Journal of Finance* 48(1). The original momentum evidence, with portfolios held in overlapping slices.
- Blitz, D., Huij, J. and Martens, M. (2011). Residual momentum. *Journal of Empirical Finance* 18(3). Momentum on residual returns, the slow counterpart of the phase 2 baseline.
- Daniel, K. and Moskowitz, T. (2016). Momentum crashes. *Journal of Financial Economics* 122(2). Why momentum's losses come in the short leg after a market fall.

### Code

For reading only. None of these has been reviewed for look-ahead or cost handling, their licences have not been checked, and no code is copied from them: a method used here is implemented from its paper.

- [gregzanotti/dlsa-public](https://github.com/gregzanotti/dlsa-public): official code for Guijarro-Ordonez, Pelger and Zanotti. Input data is not released, so results cannot be reproduced on free data. Worth reading for residual construction.
- [kingwongf/statsArb](https://github.com/kingwongf/statsArb): an Avellaneda and Lee style implementation with ETF or PCA factors and OU entry rules.
- [Hudson & Thames arbitragelab, PCA approach](https://hudson-and-thames-arbitragelab.readthedocs-hosted.com/en/latest/technical/api/arbitragelab/other_approaches/pca_approach/index.html): documentation of a commercial s-score implementation. Reference for the maths only.
