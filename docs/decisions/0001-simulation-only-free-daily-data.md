# 0001: Simulation only, free daily data

**Date:** 2026-11-16
**Status:** accepted. Its free-data rule is amended by [decision record 0008](0008-marketparquet-archive-as-a-paid-price-source.md), which allows one paid source.

## Context

The project exists to build and evaluate a mid-frequency statistical arbitrage pipeline end to end. Real mid-frequency strategies use intraday and order-book data and institutional execution, none of which is available or affordable for an individual.

## Decision

- No real orders. No broker credentials in the repository.
- Use free daily data for liquid US large caps.
- Run the strategy at daily frequency as a stand-in for the intraday version.

## Consequences

- The economics will look worse than the real thing, because daily data hides intraday opportunities and retail-level cost assumptions are harsh. That is acceptable: the question is whether the edge survives harsh but realistic costs, not how large it can be made to look.
- Survivorship bias in free constituent lists will flatter results. Each phase review must say how much this could matter.
- Moving to paid data, intraday frequency or any broker connection needs a new decision record.
