# Docket for TermiX

> **The TermiX question:** “Does hiring an agent on this marketplace actually beat doing the
> job yourself, and can you prove it with numbers?” TermiX says it will hire from the marketplace
> and scores Value of services 30%, Proven agent advantage 30%, High-stakes categories and track
> record 20%, and Marketplace quality 20%. The Agent Advantage Report is an eligibility gate:
> at least 3 real tasks run with and without an agent, with time, cost, output quality, actual
> outputs, and at least 1 trading, stock, or security task.
> [Source: TermiX brief](../deliberation/2026-08-14-BRIEFING-V2.md#12-termix--partner-track-6000--3000--1000)

The honest answer today is mixed. Docket's v1 report alone satisfies that formal eligibility
gate, but it contains one paired observation per task and records material losses as well as
wins. The marketplace is not yet open for payment: 0 of 6 catalogue services are in paid stock,
and no settlement has run. `v3-04-warden-security` is `complete_unscored`: all 24 primaries
are terminal, but seat B returned no first scoring response and substitution is forbidden.
Frozen-label formulas show manual recall at 0.75 versus Warden at 0.50 and three Warden
critical failures. v3-02 and v3-05 still wait for inputs, while v3-01 and v3-03 remain
superseded.
[Sources: [v1](https://docket.gudman.xyz/advantage.json),
[catalogue](https://docket.gudman.xyz/hire),
[canary history](https://docket.gudman.xyz/canary),
[v3](https://docket.gudman.xyz/advantage/v3.json)]

## 1. Value of services — 30%

TermiX can run the current free paths and inspect the returned evidence, but it cannot buy a
service today. The catalogue displays `0.50 $U` as the post-admission price for all 6 of 6
services while every row says `paid_stock: false`; every published canary settlement leg says
`not_yet_exercised` with `exercised: false`.
[Sources: [live catalogue](https://docket.gudman.xyz/hire),
[live canary](https://docket.gudman.xyz/canary)]

| Service | What a current free run actually returns | Evidence boundary |
|---|---|---|
| [Range Doctor](https://docket.gudman.xyz/service?id=range-doctor) | PancakeSwap v3 position state, current tick against the position's range, gross and protocol-adjusted fee arithmetic, and conditional wait or recenter paths. | The public canary records a live BSC decision for the controlled position, but the run fails its measured-value requirement because its mapped `v3-05-range-doctor` family has no locked inputs. [Canary](https://docket.gudman.xyz/canary) |
| [Yield Router](https://docket.gudman.xyz/service?id=yield-router) | A bounded PancakeSwap v3 pool comparison with the observed window, protocol-adjusted rates, declared switching cost, and break-even arithmetic. | Its current comparison row says no paired run against a person exists, so it makes no time-saving claim. [Comparison](https://docket.gudman.xyz/compare) |
| [Grid Operator](https://docket.gudman.xyz/service?id=grid-operator) | A read-only PancakeSwap v2 grid preview with live quotes, bounded levels, and calldata hashes. | Its current comparison row says no paired run against a person exists; its v2 replay bought at 0 of 5 registered levels and the registered claim was refuted. [Comparison](https://docket.gudman.xyz/compare) · [v2 output](https://docket.gudman.xyz/advantage/v2.json) |
| [Venus Health Guard](https://docket.gudman.xyz/service?id=health-guard) | A read-only Venus Core Pool account report with market balances, stated formulas, and bounded draft protective actions when the input condition is met. | Its current comparison row says no paired run against a person exists, so it makes no time-saving claim. [Comparison](https://docket.gudman.xyz/compare) |
| [Warden Payload Scan](https://docket.gudman.xyz/service?id=warden-scan) | A live upstream scan returning the service's decision, threat classes, detections, sanitized text, and per-layer checks. | It is telemetry rather than an enforcement boundary, and its published records include misses. [Service evidence](https://docket.gudman.xyz/services/warden-scan) |
| [SOLVENT Last Published Regime Signal](https://docket.gudman.xyz/service?id=solvent-signal) | A historical regime payload and the receipt-chain material needed to inspect when its anchored prefix existed. | It is not a live trading feed and establishes neither correctness nor profit. [Paired output](https://docket.gudman.xyz/advantage#02-trading) |

The `0.01 $U` amounts in v1 are historical catalogue quotes, not paid outcomes: every agent-arm
cost note says the run used the free allowance and transferred nothing, with out-of-pocket cost
0. They must not be read as evidence that a paid service beats an alternative.
[Source: [v1 raw report](https://docket.gudman.xyz/advantage.json)]

## 2. Proven agent advantage — 30%

### The report that satisfies the eligibility gate today

V1 contains exactly 3 paired tasks: each task was run once through Docket and once by hand; each
record carries both full outputs, elapsed seconds, separate cost notes, output hashes, manual
reproduction steps, and an account of where the hired arm fell short. One task is security and
one is trading, so v1 alone clears the formal “at least 3” and high-stakes-task requirements.
[Sources: [live v1 report](https://docket.gudman.xyz/advantage.json),
[LP artifact](../../docket/advantage/experiments/01-liquidity.json),
[trading artifact](../../docket/advantage/experiments/02-trading.json),
[security artifact](../../docket/advantage/experiments/03-security.json)]

| Paired task | Time, cost, and output-quality reading | Actual outputs |
|---|---|---|
| LP diagnosis, 1 pair observed 2026-08-08 | Agent 43.063 seconds versus manual 528.310 seconds. Both arms concluded the funded position was out of range and derived nearly the same one-day annualised net fee rate, while the manual output contained richer detail for the 13 closed positions. Both arms recorded out-of-pocket cost 0; the agent row also preserved its `0.01 $U` catalogue quote. | [Live task](https://docket.gudman.xyz/advantage#01-liquidity) · [Committed JSON](../../docket/advantage/experiments/01-liquidity.json) |
| Trading-provenance question, 1 pair observed 2026-08-08 | Agent 1.844 seconds versus manual 221.739 seconds, with out-of-pocket cost 0 in both arms. The hire returned provenance material but did not establish the answer; the manual arm recomputed the receipt chain and inspected the BSC anchor. Neither arm established that the regime call was correct or profitable. | [Live task](https://docket.gudman.xyz/advantage#02-trading) · [Committed JSON](../../docket/advantage/experiments/02-trading.json) |
| Security payload, 1 pair observed 2026-08-08 | Agent 2.625 seconds versus manual 74.213 seconds, with out-of-pocket cost 0 in both arms. The manual arm found 4 hostile vectors; the hire returned 1 of those 4, and the other 3 survived in its sanitized text. | [Live task](https://docket.gudman.xyz/advantage#03-security) · [Committed JSON](../../docket/advantage/experiments/03-security.json) |

V2 does not add another human comparison: it explicitly describes its repeated trials as
agent-versus-computed-null work and points back to v1 as the only current agent-versus-person
report. [Source: [v2 method and prior-version note](https://docket.gudman.xyz/advantage/v2.json)]

### What v3 completed—and what remains unscored

V3 registers 3 Range Doctor cases, 5 Yield Router pairs, and 12 Warden pairs in the active
`v3-04-warden-security` family, retaining first primary outputs and failures under fixed
stopping and scoring rules. Both calibration seats passed on their first attempt at 8/8
decisions, 8/8 verdicts, and class micro-F1 1.0000. All 24 primaries were claimed and
terminal: 23 succeeded and manual `w4-ho-01` failed. The ledger proves `invoke_error` /
`JSONDecodeError`; the operator's contemporaneous account says a crib sheet absent from this
repository led to payload text being pasted instead of the required JSON answer object. Seat A
returned 4,452 first-response bytes; seat B returned no response within the adapter's
300-second limit. The registered rule forbids another request or evaluator substitution, so
no second sheet or A/B mapping exists, disagreement cannot be computed, rubric quality is
permanently unscored, and the report state is `complete_unscored` with
`score_sheets_missing`.

Read-only frozen-label formulas—not a published §10 result—give recall of 4/8 (0.50) for
Warden and 6/8 (0.75) manually; precision of 4/4 (1.00) and 6/8 (0.75); valid scans of
12/12 and 11/12; three Warden critical failures; 11/12 complete pairs; median saving
27.86 seconds; and median agent/manual ratio 0.0610434. Warden missed its 0.90 recall,
zero-critical, complete-pair, and 30-second saving limbs; its precision, comparative
precision, all-agent-scans, and ratio limbs passed. Missing rubric medians prevent the
machinery from evaluating the complete registered falsifier, so the report publishes neither
`refuted` nor `not_refuted`. v3-05 Range and v3-02 Yield remain
`registered_waiting_for_inputs`; v3-01 Range and v3-03 Warden remain
`superseded_before_input_lock`.
[Sources: [live v3 state](https://docket.gudman.xyz/advantage/v3.json),
[Range protocol](../../docket/advantage/v3/specs/v3-05-range-doctor.json),
[Yield protocol](../../docket/advantage/v3/specs/v3-02-yield-router.json),
[Warden protocol](../../docket/advantage/v3/specs/v3-04-warden-security.json)]

Yield and Range captured their registered source bytes on their first scheduled attempts on
2026-08-26, at 12:00Z and 12:10Z respectively. Those two captures are inputs, not results:
neither associated family has locked its input or run an arm.
[Sources: [registered Yield protocol](../../docket/advantage/v3/specs/v3-02-yield-router.json),
[registered Range protocol](../../docket/advantage/v3/specs/v3-05-range-doctor.json),
[host rehearsal record](../operational-evidence.md#the-capture-rehearsal-on-this-host-with-the-installed-code)]

## 3. High-stakes categories and track record — 20%

Warden is the current security record, and all three published windows need to travel with the
figures:

| Window and method | Result | Limitation |
|---|---|---|
| 1 payload, 1 hired scan against 1 manual reading of the same bytes, observed 2026-08-08 | The hired scan named 1 of the 4 hostile vectors found manually. | This is one observation; 3 of 4 vectors survived in the returned sanitized text. [V1 task](https://docket.gudman.xyz/advantage#03-security) |
| The unchanged 47-payload corpus scanned 3 times each, observed 2026-08-10 | The live detector then in service flagged 14 of 31 attacks; 14 of 15 flagged payloads were attacks. The keyword null flagged 12 of 31; flag-everything flagged 31 of 31 with precision 31 of 47; flag-nothing flagged 0 of 31. | The exact source revision and deploy date were not recorded; it predates `0583853ed7fca7d03c98a5cc4c2383cc6b149248`, deployed 2026-08-24. Nine of 141 logical scans failed, every payload was scored, and registration ordering is `self_attested`. The run remains unmodified. [V2 security record](https://docket.gudman.xyz/advantage/v2.json) · [Committed run](../../docket/advantage/v2/runs/03-security-corpus.json) |
| The same unchanged 47-payload corpus scanned 3 times each, observed 2026-08-24 | Revision `0583853ed7fca7d03c98a5cc4c2383cc6b149248`, deployed 2026-08-24, flagged 15 of 30 scored attacks; 15 of 16 flagged payloads were attacks. The keyword null flagged 12 of 30; flag-everything flagged 30 of 30 with precision 30 of 46; flag-nothing flagged 0 of 30. | Sixteen of 141 logical scans failed on HTTP 429. One hostile payload was unscored and left every numerator and denominator. Registration ordering is `git_provable`. Recall 50.00% misses the 90% v3-04 limb even though precision 93.75% clears its limb; this v2 run cannot qualify the held-out gate, so Warden remains `beta`. [V2 security record](https://docket.gudman.xyz/advantage/v2.json) · [Committed run](../../docket/advantage/v2/runs/05-security-corpus-postfix.json) |

Docket has no trading-performance record that supplies a win rate together with its window and
risk taken. SOLVENT's v1 task dates a historical claim rather than testing whether the call was
right or profitable, while Grid's v2 replay bought at 0 of 5 levels and published its registered
claim as refuted.
[Sources: [SOLVENT paired task](https://docket.gudman.xyz/advantage#02-trading),
[Grid v2 result](https://docket.gudman.xyz/advantage/v2.json)]

## 4. Marketplace quality — 20%

A cold judge can test the intended path in this order:

1. Open the [marketplace](https://docket.gudman.xyz/) and choose a category or service.
2. Use the [comparison table](https://docket.gudman.xyz/#compare-heading) to inspect all 6
   services by job, current price state, declared or measured time basis, freshness, evidence
   availability, and stock state; 3 of the 6 rows have a paired measurement and the largest
   sample is 1 pair.
3. Open [Range Doctor](https://docket.gudman.xyz/service?id=range-doctor) and use **Try the worked
   example**; the page supplies Docket's controlled wallet, position id, declared position value,
   recenter cost, and horizon, so the free example requires no judge-owned LP position.
4. Inspect the result beside the [public canary](https://docket.gudman.xyz/canary), which records
   the live BSC block and decision and also exposes why the current run does not clear admission.
5. Read the raw [v1](https://docket.gudman.xyz/advantage.json),
   [v2](https://docket.gudman.xyz/advantage/v2.json), and
   [v3](https://docket.gudman.xyz/advantage/v3.json) evidence rather than relying on card copy.

The payment path remains the dead end a TermiX judge must know before starting: the current
marketplace can demonstrate free work, but it cannot demonstrate paid value until a service has
a fresh paired benchmark, a passing cold canary, a decision-grade presenter, and an exercised
settlement path.
[Sources: [catalogue admission state](https://docket.gudman.xyz/hire),
[canary admission state](https://docket.gudman.xyz/canary)]
