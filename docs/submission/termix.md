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
wins. The marketplace is not yet open for public payment: 0 of 6 catalogue services are in
paid stock. Exactly one owner-approved Range Doctor canary settled 0.50 USDT on 2026-08-30
and rejected its identical replay; this private bootstrap is not public paid inventory.
`v3-04-warden-security` is `complete_unscored`: all 24 primaries
are terminal, but seat B returned no first scoring response and substitution is forbidden.
Frozen-label formulas show manual recall at 0.75 versus Warden at 0.50 and three Warden
critical failures. At the 2026-08-30 live-report observation, v3-01 and v3-03 are
`superseded_before_input_lock`, v3-02 is `abandoned_after_failed_primary`, v3-04 is
`complete_unscored`, v3-05 is `locked_not_run`, and v3-06 is
`registered_waiting_for_inputs`.
[Sources: [v1](https://docket.gudman.xyz/advantage.json),
[catalogue](https://docket.gudman.xyz/hire),
[canary history](https://docket.gudman.xyz/canary),
[v3](https://docket.gudman.xyz/advantage/v3.json)]

## 1. Value of services — 30%

TermiX can run the current free paths and inspect the returned evidence, but it cannot buy a
service today. The catalogue displays `0.50 $U` as the post-admission price for all 6 of 6
services while every row says `paid_stock: false`. Public canary run 18 records one exact
0.50 USDT settlement, a complete bound result, and a rejected replay; it is the sole settled
private-canary record, not a public purchase.
[Sources: [live catalogue](https://docket.gudman.xyz/hire),
[live canary](https://docket.gudman.xyz/canary)]

| Service | What a current free run actually returns | Evidence boundary |
|---|---|---|
| [Range Doctor](https://docket.gudman.xyz/service?id=range-doctor) | PancakeSwap v3 position state, current tick against the position's range, gross and protocol-adjusted fee arithmetic, and conditional wait or recenter paths. | The public canary records a live BSC decision and one owner-approved settled private run whose eight legs passed, including proof binding and replay rejection. The mapped `v3-05-range-doctor` family still has no paired result, so public paid stock remains closed. [Canary](https://docket.gudman.xyz/canary) |
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
`refuted` nor `not_refuted`. At the 2026-08-30 live-report observation, v3-01 Range and
v3-03 Warden are `superseded_before_input_lock`, v3-02 Yield is
`abandoned_after_failed_primary`, v3-04 Warden is `complete_unscored`, v3-05 Range is
`locked_not_run`, and v3-06 assisted Yield is `registered_waiting_for_inputs`.
[Sources: [live v3 state](https://docket.gudman.xyz/advantage/v3.json),
[Range protocol](../../docket/advantage/v3/specs/v3-05-range-doctor.json),
[Yield protocol](../../docket/advantage/v3/specs/v3-02-yield-router.json),
[Warden protocol](../../docket/advantage/v3/specs/v3-04-warden-security.json)]

Yield and Range captured their registered source bytes on their first scheduled attempts on
2026-08-26, at 12:00Z and 12:10Z respectively. Those two captures are inputs, not results.
Yield v3-02 later recorded a failed manual primary and is now
`abandoned_after_failed_primary`; Range v3-05 remains `locked_not_run` with no claimed
primary.
[Sources: [registered Yield protocol](../../docket/advantage/v3/specs/v3-02-yield-router.json),
[registered Range protocol](../../docket/advantage/v3/specs/v3-05-range-doctor.json),
[host rehearsal record](../operational-evidence.md#the-capture-rehearsal-on-this-host-with-the-installed-code)]

## 3. High-stakes categories and track record — 20%

Warden is the current security record, and all three published windows need to travel with the
figures. The trading record follows it, in the same shape:

| Window and method | Result | Limitation |
|---|---|---|
| 1 payload, 1 hired scan against 1 manual reading of the same bytes, observed 2026-08-08 | The hired scan named 1 of the 4 hostile vectors found manually. | This is one observation; 3 of 4 vectors survived in the returned sanitized text. [V1 task](https://docket.gudman.xyz/advantage#03-security) |
| The unchanged 47-payload corpus scanned 3 times each, observed 2026-08-10 | The live detector then in service flagged 14 of 31 attacks; 14 of 15 flagged payloads were attacks. The keyword null flagged 12 of 31; flag-everything flagged 31 of 31 with precision 31 of 47; flag-nothing flagged 0 of 31. | The exact source revision and deploy date were not recorded; it predates `0583853ed7fca7d03c98a5cc4c2383cc6b149248`, deployed 2026-08-24. Nine of 141 logical scans failed, every payload was scored, and registration ordering is `self_attested`. The run remains unmodified. [V2 security record](https://docket.gudman.xyz/advantage/v2.json) · [Committed run](../../docket/advantage/v2/runs/03-security-corpus.json) |
| The same unchanged 47-payload corpus scanned 3 times each, observed 2026-08-24 | Revision `0583853ed7fca7d03c98a5cc4c2383cc6b149248`, deployed 2026-08-24, flagged 15 of 30 scored attacks; 15 of 16 flagged payloads were attacks. The keyword null flagged 12 of 30; flag-everything flagged 30 of 30 with precision 30 of 46; flag-nothing flagged 0 of 30. | Sixteen of 141 logical scans failed on HTTP 429. One hostile payload was unscored and left every numerator and denominator. Registration ordering is `git_provable`. Recall 50.00% misses the 90% v3-04 limb even though precision 93.75% clears its limb; this v2 run cannot qualify the held-out gate, so Warden remains `beta`. [V2 security record](https://docket.gudman.xyz/advantage/v2.json) · [Committed run](../../docket/advantage/v2/runs/05-security-corpus-postfix.json) |

### The trading record, with its window and its denominators

Two registered v2 experiments read the same closed historical window and they are the only
trading records in this package. `06-solvent-record` reads the whole published receipt chain of
SOLVENT, the trading agent this marketplace lists, and establishes what that chain does and does
not carry. `07-solvent-deposit-adjusted` reads the same account's funding from BSC and publishes
the return `06` declined to compute — a loss. `07` adds to `06` and refutes nothing in it.

| Window and method | Result | Limitation |
|---|---|---|
| All 384 receipts SOLVENT published, `2026-06-18T17:46:37Z` to `2026-06-29T01:01:04Z` — eleven days, frozen once at `?limit=500` and hashed into the registration | The chain verifies end to end: 384 of 384 published hashes are the canonical digest of the body they sit beside, 383 of 383 `prev_hash` links hold, and the hash at seq 381 is the value BSC transaction `0xa21529…fb59a9` carried in a block mined 2026-06-28, as Docket's own v1 task read it on 2026-08-08. | Two receipts sit past that anchor and nothing on chain fixes when they were written. The recipe that verifies the chain differs from Docket's own receipt digest in one argument; the two agree on 327 of 384 receipts and part on the 57 carrying a non-ASCII character. [Registered record](../../docket/advantage/v2/runs/06-solvent-record.json) |
| The 51 execution seals in that chain, against the 55 pre-trade commitments they answer | 27 of 51 seals reach an execution the chain reports as confirmed on BSC — 27 of the 55 commitments, under half. 22 seals were left `unresolved`, 1 `failed`, and 1 records no outcome. 37 of 51 carry a transaction hash, so 10 name a transaction the chain never confirms. Counting every seal as a trade, which is the free reading, gives 51 of 51 and overstates by 24. | `unresolved` is neither a success nor a failure and keeps its place in every denominator; it is not re-read as either. The confirmations land on the small trades: 15 of the 18 `qualify` micro-rotations confirmed against 5 of the 19 `exit` seals. [Registered record](../../docket/advantage/v2/runs/06-solvent-record.json) |
| Risk taken, as the chain records it: intended notional per trade | The 27 confirmed executions carry a median intended notional of 2.00 USD, a largest of 99.33 USD and 1,012.98 USD in total. The largest notional any intent in the chain records is 99.75 USD. The regime call is `risk-off` on 383 of the 384 receipts. | Notional is what the agent intended to move, not what the swap returned, and it is not a position-risk measure. No drawdown is computed. [Registered record](../../docket/advantage/v2/runs/06-solvent-record.json) |
| The commitment behind each execution | Every one of the 51 seals names, by hash, a `pre_trade_commit` receipt earlier in the same chain carrying the identical intent key, and 4 commitments were never sealed. | That binding is inside a file the agent controls. Only 1 of the 51 seals carries a `pre_trade_anchor_tx_hash`, so **this record is not pre-committed on chain** and is not described as one; 26 of the 27 confirmed executions rest on SOLVENT's own word for when the intention behind them was written. [Registered record](../../docket/advantage/v2/runs/06-solvent-record.json) |

**No win rate and no drawdown is published from that chain, and no return is computed from
its `equity_usd` series.** Every receipt carries `equity_usd` and no receipt carries any field
recording money moving into or out of the account, so in that series a deposit and a profit are
the same arithmetic. Three steps in it are larger than the largest notional the chain records —
`+201.74` at seq 134, `+100.09` at seq 225 and `+997.87` at seq 363 — and one receipt reads
`0.0` between two readings of `45.85`, a failed balance read that is disclosed and excluded
rather than treated as a wipeout. So the series is contaminated by an amount the chain does not
state, dividing its last reading by its first would publish a figure it does not support in
either direction, and a smaller deposit or withdrawal would be indistinguishable from trading
by construction. The account's transfer history has since been reconstructed from BSC, and the
deposit-adjusted figure is registered separately as `07-solvent-deposit-adjusted` below, with
its own corpus, its own method and its own denominators. It is a loss. It refutes nothing in
`06`: `06`'s funding limb is about the fields inside `06`'s own corpus, a wallet's transactions
on BSC are outside it, and `06`'s claim and falsifier are unchanged.

### The deposit-adjusted result, read from BSC: a loss

Registered v2 experiment `07-solvent-deposit-adjusted` supplies the term `06` said was missing.
It is an adverse result and it is published as it came out.

| Window and method | Result | Limitation |
|---|---|---|
| Ten pinned BSC blocks across the same `2026-06-18T17:46:37Z` → `2026-06-29T01:01:04Z` window, read once from a public archive node and frozen with the endpoint, the fetch time and a digest over the node's own answers | Exactly two external deposits reached the wallet: `202.23708931` USDT at block 105868833 and `1001.08620000` USDT at block 106851265, both bare `transfer()` calls of Binance-Peg BSC-USD sent by externally owned accounts, totalling `1203.323289` USD, and nothing was transferred out. Each deposit is rechecked on twelve properties, including that its `Transfer` log equals the wallet's balance delta across its own block. | An external deposit is fixed by one registered rule — `tx.from != wallet` — so no leg of a trade the account made can enter the set. That the set is *complete* rests on a full `eth_getLogs` sweep this repository does not reproduce: a public endpoint caps a log range far below the 1,976,904 blocks the window spans and no explorer key is configured here. The deposit set is owner-attested and the record says so wherever a figure computed from it appears. [Registered record](../../docket/advantage/v2/runs/07-solvent-deposit-adjusted.json) |
| The account's dollar-pegged balance at the two window blocks, minus what was paid in | The balance rose from `45.474198` to `1224.612900` USD — a change of `+1179.138701` against `1203.323289` paid in. **The deposit-adjusted result is a loss of `24.184588` USD**: **−11.10%** of the `217.88` USD of capital weighted by how long the account held it (Modified Dietz, weights in block seconds) and **−1.94%** of the `1248.80` USD the account opened with and received together. Doing nothing with the same contributions returns exactly `0.00` and sends no transaction. | Both boundary baskets are USDT and USDC alone, valued at a dollar each, so neither figure needs a price mark. Reading the balance change as the result gives `+1179.14` USD and is wrong by exactly what was paid in; that quotient is never served in any form. [Registered record](../../docket/advantage/v2/runs/07-solvent-deposit-adjusted.json) |
| Attribution, as the wallet and the chain each state it | **The loss is the wallet's and is not provably the agent's.** The wallet's transaction count advanced from 12 to 125 over the window — 113 transactions — while the receipt chain names 37 distinct transaction hashes, so at least 76 are named nowhere in the published record. | Chain data cannot distinguish a trade the agent's engine signed from one an operator signed with the same key, and no arithmetic here closes that gap. A separate owner sweep, not reproduced here, found 16 of 44 value-moving transactions absent from the chain's `executions`, including the two largest — `0x07f88b70…` (951.40 USDT → 0.60125 ETH) and `0xe4fd127c…` (0.72807 ETH → 1145.46 USDT); neither appears among the 37 hashes the chain names, which this record checks. [Registered record](../../docket/advantage/v2/runs/07-solvent-deposit-adjusted.json) |
| Gas | **Excluded, and the exclusion runs one way.** `compute_equity` in SOLVENT's engine sums only pinned BEP-20 balances, so the native coin the fees were paid in never entered the equity series either. 113 transactions were paid for and this record holds none of their hashes — the two it carries are the deposits, which other addresses sent — while the receipt chain names 37 of the 113 and carries no fee for any of them. | Every one of those fees made the account smaller, so `−24.18` is a floor and not an estimate. The chain separately records 980 data purchases costing `5.00` USDC; had all of that settled from this wallet the result would be `−19.18` instead, which the owner's sweep contradicts and this record does not resolve. It is a loss under either reading. [Registered record](../../docket/advantage/v2/runs/07-solvent-deposit-adjusted.json) |
| A time-weighted return | **Not published as a figure.** At the second deposit `0.12682051` ETH is most of the account's value and no `balanceOf` prices it. Over a registered grid of ETH marks from 1400 to 1800 USD the chain-linked return runs from **−15.31% to +1.19%** — wider than the figure, and it does not settle the sign. | This record observed no price source, so no row of that table is offered as the answer and a reader with a mark can read their own. The dollar result and the Modified Dietz return need no mark, which is why those two are figures. [Registered record](../../docket/advantage/v2/runs/07-solvent-deposit-adjusted.json) |

Grid's v2 replay bought at 0 of 5 levels and published its registered claim as refuted, and
that remains the only other trading-shaped record here.
[Sources: [SOLVENT paired task](https://docket.gudman.xyz/advantage#02-trading),
[registered specification 06](../../docket/advantage/v2/specs/06-solvent-record.json),
[frozen chain](../../docket/advantage/v2/corpus/trading/solvent-receipts.json),
[registered specification 07](../../docket/advantage/v2/specs/07-solvent-deposit-adjusted.json),
[frozen on-chain readings](../../docket/advantage/v2/corpus/trading/solvent-wallet-flows.json),
[v2 report](https://docket.gudman.xyz/advantage/v2.json)]

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

The public payment path remains the dead end a TermiX judge must know before starting: the
current marketplace offers free work but no public paid hire. One owner-approved private
canary has demonstrated settlement, a complete bound result, and replay rejection; public
stock still requires every admission limb, including a fresh paired benchmark.
[Sources: [catalogue admission state](https://docket.gudman.xyz/hire),
[canary admission state](https://docket.gudman.xyz/canary)]
