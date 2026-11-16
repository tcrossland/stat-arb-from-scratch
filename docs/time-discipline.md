# Time discipline

What is known when. This page is the shared reference for the rule in `CLAUDE.md` that every value used to make a decision at time *t* must have been knowable at *t*. Every phase that adds a timing assumption updates this page in the same change.

## The rules

- Index all data by the timestamp at which it became available, not the period it describes.
- A signal computed from the close on day *t* can trade no earlier than the close of *t* (with a stated slippage assumption) or the open of *t+1*. Each backtest picks one and records it.
- Rolling estimates (betas, volatilities, z-scores) use only data up to and including *t*.
- Model training uses walk-forward splits with a purge gap and embargo, never random k-fold.
- Universe membership at *t* uses only information available at *t*. Where the free data makes this impossible (survivorship), the phase review says so.

## One trading day

```mermaid
flowchart LR
    subgraph prev["day t−1"]
        C0["close t−1<br/>last data for the betas used on day t"]
    end
    subgraph today["day t"]
        O1["open t"]
        C1["close t<br/>residual and signal for t become known"]
        F1["fill at the close of t<br/>only with a stated slippage"]
    end
    subgraph next["day t+1"]
        F2["fill at the open of t+1"]
        F3["fill at the close of t+1"]
    end
    C0 --> O1 --> C1 --> F1 --> F2 --> F3
```

## Rules by phase

Each phase adds a row for every value it computes: what the value uses, and when it is first usable.

| Phase | Value | Uses data up to | First usable |
|---|---|---|---|
| 0 | Candidate list | today's index members (survivorship: not knowable in the past) | all dates, as a stated bias |

Notes for phase 0:

- The candidate list is today's, so the universe at *t* is chosen from stocks known to have survived to today. The phase 0 review reports the size of this bias.
