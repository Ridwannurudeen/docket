# PancakeSwap — controlled LP decisions without custody

> “Your agent must deliver a real benefit to PancakeSwap traders or liquidity providers …
> without ever putting user funds at risk.” — [PancakeSwap partner-challenge brief](../deliberation/2026-08-14-BRIEFING-V2.md#13-pancakeswap--partner-challenge-1000-cake)

Docket answers that brief with Range Doctor: a read-only PancakeSwap V3 position analyst that reports current range state, pool economics, and conditional wait-or-recenter paths from BSC and PancakeSwap data. [Open the live position page](https://docket.gudman.xyz/pancake) or [inspect the service contract](https://docket.gudman.xyz/services/range-doctor).

The public record is useful, but it does not yet close the full decision loop: the state, diagnosis, and later state are public; the owner-decision event is missing. [Inspect all stored rows](https://docket.gudman.xyz/lp-record).

## The controlled-position loop

Status below was checked on 2026-08-23 UTC against the public record. [Raw record](https://docket.gudman.xyz/lp-record).

| Limb | What the public evidence shows | Evidence |
|---|---|---|
| State | PancakeSwap V3 position NFT `7141050` was observed inside `[-65200, -63193)` on 2026-08-21 at BSC block `117181279`. | [Observation row](https://docket.gudman.xyz/lp-record) |
| Diagnosis | On 2026-08-22 at block `117372750`, the current tick was `-65481`, below the lower bound `-65200`; Range Doctor reported that the position was outside its range and earning no pool fees, then returned conditional `RECENTER` and `WAIT` paths. | [Diagnosis and conditions](https://docket.gudman.xyz/lp-record) |
| Owner decision | **Missing.** The nine public rows from 2026-08-15 through 2026-08-23 are `lp-record.v1` observations; none is an `owner_decision`, and none carries `prior_observation_sha256` or `answers_decision_sha256`. | [Nine public rows](https://docket.gudman.xyz/lp-record) |
| Later state | On 2026-08-23 at block `117565445`, the position was still below range at tick `-65263`. | [Later observation](https://docket.gudman.xyz/lp-record) |

The repository contains the append-only observation → owner decision → later observation format and its narrow digest checks, but the documentation describes machinery rather than evidence that an owner decision was recorded. [Read the evidence-format limits](../controlled-lp-evidence.md#observation-decision-later-observation).

## Structural safety

Range Doctor loads no key, builds no transaction, and asks for no approval; every action it emits terminates at a PancakeSwap interface link. [Range Doctor source](../../docket/agents/pancake/doctor.py#L1-L7).

Its position reader makes only `eth_call` and block-number reads, signs nothing, and broadcasts nothing. [Position-reader source](../../docket/agents/pancake/positions.py#L1-L5).

That boundary is structural: within Range Doctor there is no credential or send path with which to move user funds. [Live boundary statement](https://docket.gudman.xyz/pancake#structural-safety-heading).

Yield Router is a separate service and the important exception to “nothing is built”: it can draft unsigned PancakeSwap swap calldata and a hash commitment, but its preview has no session, signer, submitter, or method that sends anything. [Yield Router boundary](../../docket/agents/yield_router/router.py#L99-L108) [Calldata construction](../../docket/agents/yield_router/router.py#L348-L395).

PancakeSwap uses the same human-handoff pattern in its own planning skills: its swap planner produces a prefilled UI deep link and does not execute, and its liquidity planner does the same for position creation. [PancakeSwap agent reference — swap](https://github.com/pancakeswap/pancakeswap-ai/blob/main/AGENTS.md#L11-L35) [PancakeSwap agent reference — liquidity](https://github.com/pancakeswap/pancakeswap-ai/blob/main/AGENTS.md#L41-L65).

## Real benefit, measured without hiding the null result

The decision-impact section is explicitly `post_hoc`: its questions were written after the run against the same frozen dataset, so it is not presented as preregistered evidence. [Read the registration note](https://docket.gudman.xyz/advantage/v2.json).

| Measure | Result | Denominator, window, and method |
|---|---|---|
| Pool-choice effect | Protocol-fee subtraction produced **0 of 231 pool-pair order reversals**; the top pool under the gross calculation was also the top pool under the net calculation. [Source](https://docket.gudman.xyz/advantage/v2.json) | Every pair among the eligible pools in the frozen corpus was compared under gross and protocol-adjusted net fee rates. [Method](https://docket.gudman.xyz/advantage/v2.json) |
| Dollar effect | At a declared **$10,000 fixed notional**, the median annual gross-to-net overstatement was **$126.78 across 22 eligible pools**. [Source](https://docket.gudman.xyz/advantage/v2.json) | The corpus contained 28 top-list pools, 22 passed the recorded eligibility gate, and one 24-hour fee window was annualised by multiplying by 365; the notional is an input, not an observed holding. [Frozen run](../../docket/advantage/v2/runs/01-liquidity-arithmetic.json#L7-L27) |
| Payback timing | At **$10,000 notional** and **$25 switching cost**, net rather than gross rates moved payback a median **8.30 days later across 231 candidate moves**. [Source](https://docket.gudman.xyz/advantage/v2.json) | The calculation compares gross-rate and net-rate cost-only payback for every included move in the same frozen pool corpus; it is not a realized-return measure. [Method and limitation](https://docket.gudman.xyz/advantage/v2.json) |

The result is deliberately narrower than “better returns”: this snapshot found no change in which pool an LP would choose, while it did find changes in fixed-notional fee expectations and cost-only payback timing. [Decision-impact finding](https://docket.gudman.xyz/advantage/v2.json).

## Data provenance

Docket's Pancake pool client reads the live PancakeSwap Explorer API at `explorer.pancakeswap.com/api/cached`, not the BSC V3 subgraph. [Pool-client source](../../docket/agents/pancake/pools.py#L29-L32) [Live Explorer endpoint](https://explorer.pancakeswap.com/api/cached/pools/v3/bsc/list/top).

A read-only `_meta` observation of the PancakeSwap BSC V3 subgraph reported `hasIndexingErrors: true` with an indexed timestamp on 2026-04-28; Docket publishes the observation and method on the live Pancake page. [Published subgraph observation](https://docket.gudman.xyz/pancake#pancake-context-heading).

For the frozen v2 analysis, the corpus records the Explorer URL, fetch time, and SHA-256 of the exact response bytes, while the run records the committed dataset digest used by the calculation. [Frozen corpus provenance](../../docket/advantage/v2/corpus/liquidity/pools.json#L1-L9) [Run dataset digest](../../docket/advantage/v2/runs/01-liquidity-arithmetic.json#L7-L10).

## Limits a judge should know

- The public controlled-position history covers one position and currently lacks the owner-decision limb, so it does not show that Docket changed what the owner did. [Public history](https://docket.gudman.xyz/lp-record).
- The v2 decision-impact measures are post-hoc, and the strongest pool-choice measure found 0 changes across 231 comparisons. [Registration and result](https://docket.gudman.xyz/advantage/v2.json).
- The dollar figures apply pool-wide rates to declared fixed notionals; they are not this position's earned fees, a forecast, or realized return. [Run method](../../docket/advantage/v2/runs/01-liquidity-arithmetic.json#L25-L27).
- The registered v3 Range successor has produced no result: v3-05 remains `registered_waiting_for_inputs`, while v3-01 is `superseded_before_input_lock`. [Live v3 report](https://docket.gudman.xyz/advantage/v3.json).

## Judge path

1. Open the [PancakeSwap position page](https://docket.gudman.xyz/pancake) for the live read and conditional paths.
2. Open the [raw LP record](https://docket.gudman.xyz/lp-record) and confirm the present owner-decision gap.
3. Open the [raw v2 report](https://docket.gudman.xyz/advantage/v2.json) and inspect `decision_impact`, including its registration note, denominators, inputs, and limitations.
4. Open the [Range Doctor service record](https://docket.gudman.xyz/services/range-doctor) for the callable contract and evidence links.
