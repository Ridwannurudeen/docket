# Docket submission

**Hire by evidence, not promises.** [Docket](https://docket.gudman.xyz/) is a BSC agent marketplace that puts the service, its runnable sample, its recorded work, and its limits on the same public path. The marketplace—not a portfolio of house agents—is the product: a visitor can browse the live directory, choose a job, inspect what the service returns, and activate a free sample without prior Agent Studio knowledge. [Open the marketplace](https://docket.gudman.xyz/).

## What a judge can do in 60 seconds

1. Open the [marketplace](https://docket.gudman.xyz/) and choose one of the four job cards.
2. Open [Keep LP earning](https://docket.gudman.xyz/service?id=range-doctor), read the inputs and limits, then click **Try the worked example**; this is a public sample and needs no wallet.
3. Open the [paired report](https://docket.gudman.xyz/advantage) and inspect the question, both arms, elapsed time, cost note, actual output, and receipt for each recorded task.
4. Open [Live Stats](https://docket.gudman.xyz/stats) to see the current registry snapshot's capture time, sample denominator, population rule, endpoint attempts, and responses.

For the shortest evidence-led tour, use [Judge start here](judge-start-here.md). For a recorded walkthrough, use the [three-minute demo script](demo-script.md).

## Four jobs, four concrete returns

- **Rebalancing — Keep LP earning.** [Range Doctor](https://docket.gudman.xyz/services/range-doctor) reads a BSC wallet's PancakeSwap v3 position NFTs and returns each position's range state, the values used for that diagnosis, bounded fee-rate context, and conditional wait or recenter paths; it signs, approves, and moves nothing.
- **Grid trading — Run a capped grid.** [Grid Operator](https://docket.gudman.xyz/services/grid-operator) returns deterministic PancakeSwap v2 levels, live router quotes, minimum outputs, calldata hashes, deadlines, gas ceilings, and slippage bounds; it has no signer or transaction submitter.
- **Yield optimisation — Move idle liquidity.** [Yield Router](https://docket.gudman.xyz/services/yield-router) returns a reproducible PancakeSwap v3 pool universe, every inclusion and exclusion, gross and protocol-adjusted observed rates, and caller-cost break-even arithmetic; it can draft an unsigned swap leg but cannot submit it.
- **Health factor — Protect a loan.** [Health Guard](https://docket.gudman.xyz/services/health-guard) returns Venus Core Pool liquidity and shortfall values, a disclosed collateral-ratio derivation, market-level inputs, and bounded repay or supply-collateral drafts when shortfall exists; no Venus execution path exists in this build.

The four labels above are Docket's declared job categories, not fields emitted by the BSC registry; the [category response](https://docket.gudman.xyz/categories) says so directly.

## Evidence posture

Docket publishes observations, not verdicts. A public metric includes its numerator, denominator, observation window, method, and timestamp on the [service catalogue](https://docket.gudman.xyz/services); the [snapshot page](https://docket.gudman.xyz/stats) applies the same discipline to registry coverage and endpoint probes.

The [v1 paired report](https://docket.gudman.xyz/advantage.json) contains three single-observation tasks—liquidity, trading, and security—with both arms and their actual outputs. The [v2 decision-impact section](https://docket.gudman.xyz/advantage/v2.json) is post-hoc: in its frozen liquidity corpus, fee correction produced 0 ordering changes across 231 eligible-pool pairs; separately, one recorded v2 security run over 47 labelled payloads—31 attacks and 16 benign controls, scanned three times each—flagged 14 of 31 attacks and named the labelled class on 13 of 31. The [v3 report](https://docket.gudman.xyz/advantage/v3.json) currently contains three preregistered families and no result: all 3 of 3 remain `registered_waiting_for_inputs`.

The registry snapshot is refreshed unattended every six hours by the [recorded timer and pipeline](../operational-evidence.md#the-registry-snapshot-is-no-longer-stale-and-it-moved-without-a-restart), while the live [Stats page](https://docket.gudman.xyz/stats) exposes the capture timestamp and current age so a judge does not have to accept a freshness claim on faith. All 4 of 4 category cards carry a recorded run and identify its evidence modality in the [catalogue response](https://docket.gudman.xyz/services).

## Limits that remain

- No service is in paid stock, so the public flow demonstrates activation and delivery but not paid settlement; all 6 of 6 catalogue entries expose `paid_stock: false` in the [live service response](https://docket.gudman.xyz/services).
- No settlement has run; the current operational state records that limit in the [operational evidence](../operational-evidence.md).
- No category service is bound to a BSC ERC-8004 identity yet; each category entry says this in the [live service response](https://docket.gudman.xyz/services).
- All 4 of 4 registration documents are prepared and served byte-for-byte at [Range Doctor](https://docket.gudman.xyz/registrations/range-doctor.json), [Grid Operator](https://docket.gudman.xyz/registrations/grid-operator.json), [Yield Router](https://docket.gudman.xyz/registrations/yield-router.json), and [Health Guard](https://docket.gudman.xyz/registrations/health-guard.json), but broadcasting the four binding transactions remains an owner action; the [registration procedure](../deployment-runbook.md#register-the-four-identities) stops at an unsigned transaction plan.
- The public [LP record](https://docket.gudman.xyz/lp-record) contains dated position observations and later states, but it does not yet contain an owner-decision record; the [evidence schema](../controlled-lp-evidence.md) defines that missing link.
- In v1's one security payload observed on 2026-08-08, manual reading identified 4 hostile vectors and Warden's layers identified 1 of those 4; the complete arms and outputs are in the [v1 artifact](https://docket.gudman.xyz/advantage.json).

## Sponsor views

- [BNB Chain main track](bnb.md)
- [TermiX](termix.md)
- [PancakeSwap](pancakeswap.md)
- [Claims checklist](claims-checklist.md)
