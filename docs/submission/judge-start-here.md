# Judge start here

Open these five public pages in order. The tour needs no account or wallet and keeps each claim beside the evidence that bounds it.

## 1. See the product

Open the [Docket marketplace](https://docket.gudman.xyz/).

This proves the marketplace journey: four job cards, service descriptions, comparison fields, recorded-run figures, and a free activation path. Pick **Keep LP earning** → **Run it free** → **Try the worked example** to receive a fresh Range Doctor result on the [service page](https://docket.gudman.xyz/service?id=range-doctor).

Read the limit on that same page: Range Doctor is not in paid stock and this public sample is a free-tier run. Separately, one owner-approved private canary settled 0.50 USDT on 2026-08-30 and rejected its identical replay; that does not open public paid inventory. Its BSC ERC-8004 identity is agent 311253, but that registration is not an endorsement, paid-stock evidence, or evidence that the sample produced a result. The [raw catalogue](https://docket.gudman.xyz/services) exposes the corresponding stock and identity fields for every service, and the [canary record](https://docket.gudman.xyz/canary) exposes the bounded payment proof.

## 2. Inspect the PancakeSwap case

Open the [PancakeSwap decision page](https://docket.gudman.xyz/pancake).

This proves a read-only position diagnosis, dated controlled-position observations, disclosed fee arithmetic, conditional owner actions, and structural separation from signing or submission. The 14-row [raw LP record](https://docket.gudman.xyz/lp-record) contains 13 observations and the owner's 2026-08-24 `WAIT` decision: the decision links to its prior observation, and three later states link back to it. This proves record linkage, not causal improvement, realized return, or that Docket caused the choice. The [controlled-evidence document](../controlled-lp-evidence.md) defines the link.

## 3. Inspect the comparative evidence

Open the [Agent Advantage Report](https://docket.gudman.xyz/advantage).

This proves three completed single-task service-versus-manual comparisons—liquidity, trading, and security—with both timings, cost notes, hashes, and actual outputs. The raw [v1 artifact](https://docket.gudman.xyz/advantage.json) shows Warden's miss as well as the faster runs; the [post-hoc decision-impact section of v2](https://docket.gudman.xyz/advantage/v2.json) reports 0 ordering changes across 231 eligible-pool pairs. Its two security records preserve the detector change: the live detector observed 2026-08-10, exact revision and deploy date unrecorded, flagged 14 of 31 attacks with precision 14 of 15; revision `0583853ed7fca7d03c98a5cc4c2383cc6b149248`, deployed 2026-08-24, flagged 15 of 30 scored attacks with precision 15 of 16. One hostile payload was unscored in the newer run, whose 50.00% recall still misses v3-04's 90% floor; Warden remains beta.

Then open [v3](https://docket.gudman.xyz/advantage/v3). A registered claim that fails and
says so is the result this report was built to be able to publish. V3 fixes the comparison
rules before it sees the exact cases, then publishes the run even when the result is adverse
or scoring cannot finish.

**The agent did not beat the human here.**

Vocabulary used below:

- **arm** — one side of the comparison: agent or human/manual.
- **primary** — one scheduled attempt on one case by one arm; no scored retry.
- **seat** — a fixed model evaluator that scores anonymised outputs. Both seats were run by
  one operator, so they are prompt-blinded but not independent evaluators.
- **input lock** — the point when the exact cases and their hashes were fixed; no case could
  then be removed or replaced.
- **frozen label** — the hostile/benign answer fixed before evaluation and used by the
  read-only diagnostics.
- **falsifier** — a condition written in advance that would refute the bounded claim if it fired.
- **`complete_unscored`** — every scheduled attempt ended, but required scoring artifacts are
  absent, so rubric quality and the registered falsifier remain unavailable.
- **`superseded_before_input_lock`** — a later registration replaced the family before exact
  inputs were locked; neither arm ran.

What was fixed in advance: the questions, exact-input locking rule, arm order, clocks,
failure treatment, scoring process, and falsifier. What ran: 12 planned agent-versus-manual
pairs, or 24 primaries. What went wrong: 23 primaries succeeded, while manual `w4-ho-01`
failed with ledger state `invoke_error` / `JSONDecodeError`; seat B then returned no first
scoring response, and the registered rule forbids retry or substitution. The operator's
contemporaneous account attributes the manual failure to a crib sheet absent from the
repository and payload text being pasted instead of the required JSON object.

What it means: frozen-label formulas put Warden recall at 4/8 (0.50) versus the human's 6/8
(0.75) and record three Warden critical failures. One manual primary failed. Rubric quality
is permanently unscored. The family is therefore `complete_unscored` with
`score_sheets_missing`, not a scored performance result. Its page deliberately leaves quality,
speed, formula metrics, and `falsifier_result` null; it does not display the diagnostics below.

To reproduce the non-§10 diagnostics from the committed
[`v3-04-warden-security` ledger](../../docket/advantage/v3/runs/v3-04-warden-security.jsonl)
against its locked spec and input, run this from a public checkout:

```text
./.venv/Scripts/python.exe scripts/reproduce-v3-04.py
```

Expected output:

```json
{
  "agent_recall": {
    "numerator": 4,
    "denominator": 8,
    "value": 0.5
  },
  "manual_recall": {
    "numerator": 6,
    "denominator": 8,
    "value": 0.75
  },
  "agent_critical_failures": 3,
  "complete_pairs": 11,
  "planned_pairs": 12,
  "median_seconds_saved": 27.86,
  "median_agent_to_manual_ratio": 0.06104344152643808
}
```

It reports Warden recall 4/8 (0.50) versus manual 6/8 (0.75), three Warden critical
failures, 11/12 complete pairs, a 27.86-second median saving, and a
0.06104344152643808 median ratio. These are read-only frozen-label diagnostics, not a
published §10 result. Missing rubric medians prevent a complete registered falsifier
evaluation, so neither `refuted` nor `not_refuted` is published. At the committed-artifact
observation on 2026-08-29, the committed v3 artifacts contain 6 families:
`v3-02-yield-router` is `abandoned_after_failed_primary`; `v3-04-warden-security` is
`complete_unscored`; `v3-05-range-doctor` is `locked_not_run`;
`v3-06-yield-router-assisted` is `registered_waiting_for_inputs`;
`v3-01-range-doctor` and `v3-03-warden-security` are
`superseded_before_input_lock`.

## 4. Check the registry data

Open [Live Stats](https://docket.gudman.xyz/stats), then [Browse agents](https://docket.gudman.xyz/research).

The first page gives the current snapshot timestamp, age, population rule, sample denominator, registry total, and endpoint-probe denominator and method; the second exposes the sampled BSC agent records. Docket refreshes this snapshot every six hours through the [recorded timer and pipeline](../operational-evidence.md#the-registry-snapshot-is-no-longer-stale-and-it-moved-without-a-restart), and the displayed age—not a number copied into this submission—is the freshness claim. The [raw stats response](https://docket.gudman.xyz/stats) and [raw agent response](https://docket.gudman.xyz/agents) are the machine-readable sources.

## 5. Check the identity boundary

Open the served registration documents for [Range Doctor](https://docket.gudman.xyz/registrations/range-doctor.json), [Grid Operator](https://docket.gudman.xyz/registrations/grid-operator.json), [Yield Router](https://docket.gudman.xyz/registrations/yield-router.json), and [Health Guard](https://docket.gudman.xyz/registrations/health-guard.json).

The four category services were registered on BSC chain 56 on 2026-08-28 UTC: Range Doctor 311253 at block 118559596, Grid Operator 311255 at 118559736, Yield Router 311257 at 118559820, and Health Guard 311259 at 118559871. At the recorded observation, `ownerOf` returned `0xe55816904796341bf8535e25f6c8b647927fc946` for each and every `tokenURI` named the corresponding document above; the [committed chain evidence](../erc8004-category-identities.json) carries the transaction hashes. This establishes registration only—not endorsement, paid stock, or production of any service result. `warden-scan` remains unbound.

## Raw-evidence index

| Question | Evidence |
|---|---|
| What is for sale or runnable now? | [Service catalogue](https://docket.gudman.xyz/services) |
| What does each category mean? | [Categories](https://docket.gudman.xyz/categories) |
| What did the three paired tasks return? | [v1](https://docket.gudman.xyz/advantage.json) |
| What did the historical correction change? | [v2](https://docket.gudman.xyz/advantage/v2.json) |
| What state did the registered report reach? | [v3](https://docket.gudman.xyz/advantage/v3.json) |
| What happened to the controlled LP position? | [LP record](https://docket.gudman.xyz/lp-record) |
| How fresh and broad is the registry sample? | [Stats](https://docket.gudman.xyz/stats) |
| What routes and schemas are public? | [llms.txt](https://docket.gudman.xyz/llms.txt) and [SKILL.md](https://docket.gudman.xyz/skill.md) |

For the sponsor rubrics, continue to [BNB Chain](bnb.md), [TermiX](termix.md), or [PancakeSwap](pancakeswap.md). Every factual sentence used by the package is indexed in the [claims checklist](claims-checklist.md).
