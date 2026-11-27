# 0011: Listing exchanges from SEC EDGAR, and Alpaca's auction prices for measurement

**Date:** 2026-11-27
**Status:** accepted

## Context

The build takes the consolidated daily bar's open and close. A market-on-open order fills at the listing exchange's opening auction and a market-on-close order at its closing auction, and the backlog item "Closes from the listing exchange's closing auctions" asks how often those prices differ from the bar's in this data, before anything is changed. The [plan](../plans/auction-closes.md) measures it. It needs two inputs the project has not used:

- **Auction prices.** Alpaca's `GET /v2/stocks/auctions` returns each day's opening and closing auction prints of every market centre, with price, size, time, exchange code and condition code. It is the source [decision record 0003](0003-data-sources-alpaca-and-wikipedia.md) chose, on the same host and under the same terms. Alpaca's reference shows one stock's close printed by two exchanges, each with the official-close condition `M`, so a print is the listing exchange's only by its exchange code.
- **The listing exchange of each ticker on each day.** Two free sources were read for it, each on its own page on 2026-11-27:
  - Nasdaq Trader's symbol directory gives the listing exchange of every listed security, ETFs included. Its terms ("Copyright, Trademarks and Disclaimers") allow one unaltered copy for personal, non-commercial use and forbid distributing its content in whole or in part without Nasdaq's consent.
  - SEC EDGAR's `company_tickers_exchange.json` gives an exchange for each operating company's ticker. The SEC's website policy ("Website Dissemination") says information on sec.gov is public and may be copied or further distributed without permission, and asks for a citation. Its fair-access rules allow at most 10 requests a second. The file names "NYSE" for every NYSE-group exchange (it files SPY, listed on NYSE Arca, as "NYSE") and holds no sector ETFs. Issuers' filings and fund prospectuses on EDGAR fall under the same policy.

## Decision

1. **Auction prices come from Alpaca,** under decision record 0003's terms, into a raw snapshot of their own (`alpaca-auctions/<download date>/`) that is never committed. Reports hold statistics derived from them, never a price or size. The last date requested falls before the forward run's first session, so no forward day is read (decision record 0007, item 4).
2. **Listing exchanges come from SEC EDGAR,** written once into `config/listings.toml` with the date it was read: the stocks' current exchange from `company_tickers_exchange.json`, the ETFs' from each fund's prospectus, and each transfer since 2016 with its first session on the new exchange and the issuer's filing or press release as its source. A stock the SEC files as "NYSE" is entered as listed on the New York Stock Exchange.
3. **Nasdaq Trader's directory is not used.** A committed list taken from it would distribute its content.
4. **The data checks the list.** The report counts, for each ticker and year, the days on which the largest closing print is on another exchange than the list's. A ticker and year flagged there gets a sourced transfer or is left out of the counts, and the report says which. No condition code is assumed to mark the official price: the report measures how often the listing exchange and the others print `M` and `Q`, by year.
5. **Measurement only.** No build input, processed table or frozen record reads `config/auctions.toml` or `config/listings.toml`. Adopting auction prices waits for the forward run's review and is a build change after the fact, with an amendment to [decision record 0004](0004-rules-for-alpacas-data.md).
6. **Reruns on auction prices are not trials.** A rerun of a logged headline path on auction prices, under a config overlay, keeps the path's configuration, and nothing is chosen from it, as with the phase 7 rerun on the second source's prices. It is logged to `reports/phase-08/auction_overlay.jsonl`, which `repository_trials` in `statarb.backtest.trials` does not read, and reported beside the logged metric. If auction prices are adopted, every logged path is rerun into its `experiments.jsonl` in the ordinary way; each keeps its path id, so it replaces its statistic and adds no trial.

## Consequences

- The list is read after the sample ends, so a move between 2026-11-13 and the day it was read is a transfer in the file, dated after the sample. Reading a listing directory after the forward run began reads no price, volume or return of a forward session.
- The listing exchange is a fact about each ticker and is committed with its sources. A change to it needs no download, only a new report run.
- The NYSE-group exchanges are told apart by the listing check, not by the SEC file. A stock listed on NYSE American or NYSE Arca would be flagged in every year.
