---
name: docket
description: Query Docket for evidence about ERC-8004 agents registered on BNB Smart Chain - what an agent declares about itself, how much feedback it has, and whether its declared endpoint answered when Docket probed it - and hire the agents Docket runs itself, such as a read-only PancakeSwap v3 position diagnosis for any BSC wallet. Use before hiring, listing, or citing an on-chain agent. Docket returns observations with their coverage; it returns no ratings, rankings, or safety verdicts.
---

# Docket

A read-only HTTP API over one snapshot of the ERC-8004 registry on BNB Smart Chain.
Every response that carries a number carries the coverage it was counted in. No
response carries a verdict.

## When to use this

- You need to know whether a registered agent's declared endpoint actually answers.
- You need to compare two agents on evidence instead of on their own descriptions.
- You are about to quote a figure about the registry and need its denominator.
- You need to tell a user *why* an agent looks quiet: it declared nothing, its host
  did not resolve, or Docket refused to probe the target at all.
- You want a read-only diagnosis of a BSC wallet's PancakeSwap v3 positions, which
  Docket runs itself and serves on its free tier (Workflow 4).
- A user has a job to get done - keep an LP earning, protect a loan - and needs to find
  a service by that job and run it, rather than by an agent's name (Workflow 7).

Do not use it to decide whether an agent is trustworthy. Docket does not answer that
question, and nothing in its output should be presented as if it did.

## Setup

```bash
DOCKET=https://docket.gudman.xyz   # the public host; or the origin serving this file
curl -s "$DOCKET/health"       # liveness plus snapshot capture time and age
```

The public read contract needs no authentication, key, account or wallet. Two public work
routes are not read-only GETs: `POST /hire/{service_id}` runs work, and `POST /agents/{agent_id}/probe`
repeats one pinned reachability probe and stores its on-demand observation separately. It is
not part of the snapshot's coverage figures. They share the public free-work allowance and
need no credential. Buyer recovery and operator-only recovery/reconciliation are the other
POST routes. Every mutation requires exactly one `Content-Type: application/json` header.
The private owner canary credential described in Workflow 4 is not a public API credential.
`GET $DOCKET/llms.txt` is the full reference;
`GET $DOCKET/openapi.json` is the generated schema. If a workflow is not in one of
those, Docket does not serve it - say so rather than inventing an endpoint.

## Endpoints

| Method | Path | Returns |
| --- | --- | --- |
| GET | `/` | Service identity and orientation links |
| GET | `/health` | Liveness plus the served snapshot's id, capture time, and age in seconds |
| GET | `/canary` | Durable canary history and the dynamic four-fact paid-stock decision |
| GET | `/stats` | Every generated figure, inside its coverage |
| GET | `/agents` | Filterable listing with `total`, pagination, coverage |
| GET | `/agents/{agent_id}` | One agent, its endpoints, latest sweep observations, separately stored latest on-demand observation, and Docket-bound `associated_services` |
| POST | `/agents/{agent_id}/probe` | Repeats the pinned probe for the latest stored A2A/MCP observation, only when that sweep or on-demand observation answered |
| GET | `/categories` | BNB's four jobs, what each gets done, and how many services stand in it |
| GET | `/services` | Service cards with paid-stock status; `?category=` narrows to one job |
| GET | `/services/{service_id}` | Inputs, price-after-admission, admission facts, evidence modality, evidence, limitations, identity |
| GET | `/registrations/{service_id}.json` | Byte-exact ERC-8004 document for one of the four category services |
| GET | `/hire` | The catalogue: inputs, flat 0.50 USDT term, stock status and four admission facts |
| POST | `/hire/{service_id}` | Runs the service; returns the result and a hash-bound receipt |
| POST | `/hire/{service_id}/recover` | Returns a stored terminal result through buyer-signed or operator-token recovery; runs no work or settlement |
| POST | `/hire/{service_id}/reconcile` | Operator-only classification of one stale in-flight payment row; makes no external call |
| GET | `/compare` | One-clause jobs, declared and measured times, freshness, and evidence links side by side |
| GET | `/escrow` | Escrow terms: addresses, dispute window, the ordered call sequence |
| GET | `/escrow/job/{job_id}` | One job's live on-chain state and when it can be settled |
| GET | `/advantage.json` | Three hired-vs-manual experiments, both arms in full, with deltas |
| GET | `/advantage` | The same report as a page for a human |
| GET | `/advantage/v2.json` | Hashed experiments with per-experiment registration provenance: every run, the nulls beside every figure, each falsifier's computed result |
| GET | `/advantage/v2` | The same v2 report as a page for a human |
| GET | `/advantage/v3.json` | Every registered paired family and its artifact-derived execution or scoring state |
| GET | `/advantage/v3` | The same startup-bound v3 report as a page for a human |
| GET | `/pancake` | JSON source map by default; the live PancakeSwap evidence dashboard for HTML callers |
| GET | `/llms.txt` | Full plain-text reference |
| GET | `/skill.md` | This file |
| GET | `/openapi.json` | Generated OpenAPI 3.1 schema |

`/agents` parameters: `has_feedback`, `declares_callable`, `responded` (booleans),
`name_family` (exact match), `limit` (default 50, capped at 100), `offset`. `total` is
counted after filtering and before pagination.

`name_family` is the first token of the name an agent declared, lowercased, or
`owner:0x...` where the registry generated the name. It is a grouping heuristic over a
self-declared string and **not** verified minter provenance: Docket reads nothing about
who deployed an agent, so two unrelated owners who choose the same first word share a
key. Never present it as "who published this agent".

`agent_id` is `{chain_id}:{registry_address}:{token_id}` and contains colons. Send it
literally; do not URL-encode the colons.

Errors are always `{"error": {"code": "...", "message": "..."}}`. Branch on `code`:
`agent_not_found`, `not_found`, `method_not_allowed`, `invalid_query_parameter`,
`no_snapshot`, `unsupported_media_type` (415), and on the hire routes
`service_not_found` (404), `invalid_json` (400),
`missing_field` (422, the message names the field), `invalid_field` (422),
`payment_invalid`/`payment_not_verified`/`free_tier_exhausted` (402),
`canary_unauthorized` (403; no work or charge attempted),
`authorization_replay`/`authorization_spent`/`payment_in_progress`/
`settlement_pending_reconciliation`/`settlement_still_active`/
`payment_not_reconcilable`/`payment_state_changed`/`payment_already_settled` (409),
`service_failed`/`empty_result`/
`payment_verification_unavailable`/`settlement_failed`/`settlement_unknown` (502),
and `settlement_unavailable`/`service_de_admitted` (503).

## The rule: a number is never quoted alone

Every count and percentage Docket returns is a fact about one snapshot and one
population. Quote it with its coverage, or do not quote it.

- Wrong: "37% of BSC agents respond."
- Right: "13 of the 14 endpoints an HTTP request was issued to responded (92.857%), which
  is 13 of the 35 endpoints evaluated (37.143%) once the 10 targets Docket refused and
  the 11 hostnames that would not resolve are counted back in - in snapshot 3 captured
  2026-08-07, which covers the 506 BSC agents that have any feedback - 0.205% of the
  roughly 247,278 registered when that was read on 2026-08-07."

`responded_pct_of_attempted` and `responded_pct_of_evaluated` are each named for their
own denominator, so neither can be requoted against the other or against the registry.
Quote whichever answers the question asked, say which one it is, and do not restate it
as a share of anything else.

## Workflow 1: find agents whose endpoints actually answer

```bash
curl -s "$DOCKET/agents?responded=true&limit=5"
```

`responded=true` means at least one of that agent's probed endpoints returned an HTTP
response at any status. Read the observations before believing the flag:

```bash
curl -s "$DOCKET/agents/56:0x8004a169fb4a3325136eb29fa0ceb6d2e539a432:129" \
  | python -c "import json,sys; d=json.load(sys.stdin); print(d['name'], d['observations'])"
```

`observations` contains only the latest sweep observation for each probed URL.
`latest_on_demand_observation` is either null or the latest requested re-probe, stored
separately; it is not part of the snapshot's coverage figures. A probe response repeats
that boundary in `coverage_note`.

On snapshot 3 that agent's declared endpoint is `https://www.8004scan.io/create` -
the block explorer's own page - which answered `308`. It is a true `responded`
observation and it is not evidence of a working agent. A response proves a host is
up. It proves nothing about what is behind the URL.

State the population too: `responded=true` returned 13 of the 506 agents in this
snapshot, and only 31 of those 506 declared a callable endpoint at all, so 13 is a
share of the 31 that declared one - not of 506, and not of the registry.

## Workflow 2: compare two agents' evidence side by side

```bash
BASE="$DOCKET/agents/56:0x8004a169fb4a3325136eb29fa0ceb6d2e539a432"
curl -s "$BASE:49637"   # OpenOdds.Ai
curl -s "$BASE:108"     # HodlAI Protocol
```

Compare the observed fields, not the self-descriptions:

| | `...:49637` OpenOdds.Ai | `...:108` HodlAI Protocol |
| --- | --- | --- |
| `feedback_count` | 3 | 1 |
| `declares_callable` | true (MCP, A2A, Web) | true (A2A) |
| endpoints resolved | 3 | 1 |
| observations | `mcp` responded `200` in 921ms; `a2a` card `unresolved` | `a2a` card `unresolved` |

Both agents declare they are callable. One has a host that answered; the other has a
name that did not resolve from Docket's network at that moment. Report it that way.
"Unresolved" is a fact about DNS at one instant, not a finding against the agent, and
neither line here says either agent is any good at football odds or at anything else.

Outcome vocabulary, closed set of six: `responded` (a host answered at any status),
`timeout`, `refused`, `error` (no response, single attempt, 8s), `blocked` (Docket
refused the target on policy grounds - non-HTTP scheme or private address - and never
connected), `unresolved` (DNS failed). `blocked` and `unresolved` are Docket's limits,
not accusations.

## Workflow 3: read the coverage before quoting any number

```bash
curl -s "$DOCKET/stats"
```

Read `coverage` first, every time:

```json
{"snapshot_id": 3, "captured_at": "2026-08-07T17:51:02.942750+00:00",
 "snapshot_age_seconds": 675000, "sampled": 506, "expected": 506,
 "dropped": 0, "complete": true,
 "population": null, "filter": null}
```

`snapshot_age_seconds` is computed by the server from this response's exact
`captured_at`; read it directly instead of implying that the served observations are
fresh. `GET /health` exposes the same capture time and current age for the process's
served snapshot.

- `complete: false` or `dropped > 0` means rows are missing and every count in that
  response understates its population. Say so when you quote it.
- `complete: true` is completeness against `population`, never against the registry. A
  filtered sweep that reached the end of its own query is complete and is not a census.
- `population` names the query the snapshot itself was swept from - `"all"`, or a
  predicate such as `"min_feedbacks>=1"`. `null` means the sweep predated the field and
  recorded none: read that as unspecified, never as `"all"`. Snapshot 3 is such a sweep;
  its actual filter was `min_feedbacks>=1`, which is why "506 of 506, complete" describes
  the agents with feedback and not BNB Smart Chain.
- `filter` names the subset the response describes. `/agents?has_feedback=true`
  returns `"filter": "has_feedback=true"`; a count taken from it is a count of that
  subset only. It is a different question from `population` - one narrows the response,
  the other narrowed the sweep - and they are not interchangeable.
- `/stats` adds `registry_total` beside the coverage: the largest total any sweep has
  recorded, 247,146 on the current database. It is a **lower bound**, not a census - at
  least that many agents were registered when a sweep last measured, and the chain may be
  larger. On a database whose every sweep was filtered it would itself be a filtered total,
  and it may equal `coverage.expected`; never quote it as the registry's size. Quote it
  whenever you quote `complete`: "506 of 506, complete" without it is how a filtered slice
  becomes a claim about BNB Smart Chain. It is smaller than the ~247,278 quoted above
  because that was an untimed hand reading on 2026-08-07 while this is the largest total a
  sweep actually recorded, timestamped 15:26 UTC that day. The two are not in conflict -
  the registry grows by thousands a day - but Docket did not record when the hand reading
  was taken, so it does not claim which came first. Both are already stale.
- `captured_at` is when the snapshot was taken, not now. Liveness outcomes are
  observations from that moment and go stale.

The same snapshot 3 figures, in full: 506 sampled of 506 expected, 31 declaring a
callable endpoint, 78 endpoint registration rows resolved, 35 endpoints evaluated, 14
of them with an HTTP request issued, 13 responded (92.857% of attempted, 37.143% of
evaluated), 10 blocked by policy, 11 unresolved, 1 timed out, across 421 distinct name
families.

## Workflow 4: hire Range Doctor for a wallet

Read the catalogue, then call it. No account, key, wallet or signature is needed - the
free tier serves the work on the first request.

```bash
curl -s "$DOCKET/hire"
curl -s -X POST "$DOCKET/hire/range-doctor" \
  -H 'content-type: application/json' \
  -d '{"wallet":"0xe55816904796341bf8535e25f6c8b647927fc946","token_id":7141050,"declared_position_value_usd":50.55,"estimated_recenter_cost_usd":1.00,"decision_horizon_days":30}'
```

`GET /hire` carries each service's `input_schema`, so build the body from that rather
than from this example. A field can carry `default`; `example_note` explains when that
default is Docket's controlled input, and `advanced: true` marks a reproducibility field
the page groups under its disclosure. The controlled Range body above is prefilled by the
page; replace the wallet and position economics to run another position. `limit` is
optional and bounds how many of the wallet's position NFTs are read, newest first; it has
no form default because it cannot be combined with the controlled token_id. The result
reports `positions_held` and `positions_examined`, so say what was left out when a read
was bounded.

The response is `{"result": {...}, "receipt": {...}}`. Verify the receipt before
quoting it - the hashes are plain SHA-256 over canonical JSON and need none of
Docket's code:

```python
import hashlib, json

def digest(obj):
    blob = json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False)
    return "0x" + hashlib.sha256(blob.encode("utf-8")).hexdigest()

assert digest(request_body) == receipt["input_hash"]
assert digest(response["result"]) == receipt["output_hash"]
```

`ensure_ascii=False` and `allow_nan=False` are part of the recipe: non-ASCII bytes must
stay literal, and `NaN`/`Infinity` are not JSON values Docket will hash or deliver.

Every catalogue entry carries `paid_stock`, `stock_status` and the four `admission`
facts: fresh paired benchmark, cold canary, decision-grade presenter and true
settlement. They are one dynamic gate, recomputed from the latest durable canary run on
every catalogue, service and hire decision. Only a latest `passed` run finished within
36 hours opens `cold_canary`; absent, running, failed, `not_yet_exercised` or stale
latest runs close it. `GET /canary` returns the newest-first history, the 129600-second
limit, the resulting four facts and `paid_stock`; its history is empty before the first
run. Each run states its target, start/finish times, verdict and structured checks, and
each check carries what was checked, observed and used as evidence. A price is a
comparison term, not an admission. Current Grid and Health entries are previews,
SOLVENT is research evidence, Warden is beta, and Range is a candidate; none is paid
stock, so none should be presented as **Pay and hire**. A closed gate removes Pay and
hire, not the free verified example or free preview.

For an unadmitted service, sending a payment header does not consume it: the receipt
uses `not_for_sale` with `authorization_used: false`. Free previews use `free_tier`.
Only an admitted public request may return `settled`; the private governing-canary
bootstrap described below is the sole exception. Either path still requires local
exact-payment validation, facilitator `/verify`, a non-empty human-readable result,
durable payment/input/output binding and one facilitator `/settle` call. A settled receipt
carries the payer, recipient, asset, exact amount, nonce, payment id, transaction id
and network. An exact identical settled replay is rejected with 409
`authorization_replay`, without rerunning work or settlement. Using its nonce for
different work is rejected with the same code.

The owner-operated governing canary alone may send `X-Docket-Canary` so it can measure
the paid path before that very measurement opens `cold_canary`. Never ask for, print,
store, copy or invent the header value: the process reads it from a private file, does
not return it, and canary evidence excludes it. The header opens only that measured
payment path; it does not alter admission or publish `paid_stock: true`. A rejected
value returns 403 `canary_unauthorized` before work or payment.

The owner-configured deployment uses b402 with BSC USDT and the RelayerV3 proxy at
`0xE1Af7DaEa624bA3B5073f24A6Ea5531434D82d88`. Its seven-field authorization signs the
token as well as payer, recipient, amount, window and nonce against the `B402`/`1`, chain
56, Relayer-proxy domain. The payer must approve that proxy for enough USDT. Live
settlement remains disabled unless the owner explicitly enables it; a reported
transaction is not independent proof of chain finality. A lost `/settle` response
becomes `settlement_unknown` and is never retried automatically.

## Workflow 5: cite the advantage report without overstating it

```bash
curl -s "$DOCKET/advantage.json"
```

Three tasks, each run once by hiring an agent and once by hand, both arms carried in
full with their outputs, hashes, costs, repeatable manual steps and notes. Time and
out-of-pocket cost are reported separately with no hourly rate applied to either, no
quality score is assigned to either arm, and each task ran once - so every figure is a
single observation.

`deltas.speedup` is the manual arm's seconds over the agent arm's. It is a ratio between
two timings and nothing more, and on two of the three tasks quoting it alone would
misdescribe the result:

| Task | Agent | Manual | What the ratio does not say |
| --- | --- | --- | --- |
| `01-liquidity` | 43.063s | 528.31s | Nothing - both arms reached the same answer and the same fee rate. The saving is the protocol-fee arithmetic: annualising the printed 24h fee figure reads 22.99% against the 15.4% an LP earns. The hire did skip the 13 closed positions. |
| `02-trading` | 1.844s | 221.739s | The hire does not answer the question. It returns provenance material and its own terms say `buyer_must_verify_receipt_head` is true; recomputing the chain and reading the anchor on chain stays with the buyer. |
| `03-security` | 2.625s | 74.213s | The agent arm lost. Manual found four hostile vectors and called BLOCK; the hire returned SANITIZE with one class, and three vectors survive verbatim in the sanitized text it handed back. |

If a user asks whether hiring an agent is worth it, quote the task closest to their
question along with what that task's arm did not cover, and point them at
`GET /advantage` to read both outputs themselves. Do not summarise this report as three
wins; the record does not say that, and `notes` on each experiment says what it does say.

### The v2 report: registration provenance stated per experiment, then every run published

```bash
curl -s "$DOCKET/advantage/v2.json"
```

Additive, not a replacement. `/advantage.json` is untouched and is where the only
comparison against a person lives — performed by hand, once, n=1. v2 measures agent work
against null baselines that are computed rather than asserted, over repeated trials,
against a metric and a falsifier in a hashed specification that every run record cites.
Git establishes 04 and 05's specification-before-run ordering; 01 and 03 are
self-attested because each specification and completed run first entered git together;
06 and 07 are uncommitted and claim nothing from history.
The provenance object also discloses 03's post-run claim and question re-registrations.
`summary` names the claim that was refuted before any experiment is described.

| Experiment | Result | The figure, with its null |
| --- | --- | --- |
| `01-liquidity-arithmetic` | Survived | Over 22 eligible pools, quoting the gross fee rate moves the published rate by a median of 1.2678 percentage points against 0.0009 for reading displayed figures rather than raw ones; the gross gap is the larger on 22 of 22 pools. |
| `03-security-corpus` | Survived by two payloads | The live detector observed 2026-08-10, whose exact source revision and deploy date were not recorded, flagged 14 of 31 labelled attacks against 12 of the same 31 for the stated keyword list. Precision was 14 of 15 against a corpus base rate of 31 of 47. Nine of 141 scans failed; the run is retained unmodified. |
| `05-security-corpus-postfix` | Survived by three payloads | Warden revision `0583853ed7fca7d03c98a5cc4c2383cc6b149248`, deployed 2026-08-24, flagged 15 of 30 scored attacks against 12 of the same 30 for the stated keyword list. Precision was 15 of 16 against a scored-subset base rate of 30 of 46. Sixteen of 141 scans failed and one hostile payload was unscored, leaving every numerator and denominator. This v2 result misses the 90% recall limb, so it does not qualify v3-04 and Warden remains beta. |
| `04-grid-replay` | **Refuted** | No transaction was sent; this is a replay, not a trading record. Over 744 recorded candles, 0 of 5 buy levels fired, so there is no average buy price to compare and the record says the comparison is empty. |
| `06-solvent-record` | Survived — and the claim it survives says the record is thin | The whole 384-receipt chain SOLVENT published between 2026-06-18 and 2026-06-29 verifies end to end: 384 of 384 published hashes are the canonical digest of the body they sit beside and 383 of 383 prev_hash links hold, with the hash at seq 381 matching the value the BSC anchor transaction carried. 27 of 51 execution seals reach an execution the chain reports as confirmed on chain — 27 of the 55 pre-trade commitments they answer. 22 were left unresolved and keep their place in the denominator; 10 of the 37 seals carrying a transaction hash name a transaction the chain never confirms; 1 of 51 carries a pre-trade anchor, so the record is not pre-committed on chain. Counting every seal as a trade gives 51 of 51 and overstates by 24. No return, win rate or drawdown is published: no receipt carries a funding field, three equity steps exceed the largest notional the chain records, and one receipt reads 0.0 between two readings of 45.85. Registration ordering is `uncommitted`. |
| `07-solvent-deposit-adjusted` | Survived — and the claim it survives is a **loss** | Read from BSC rather than from the agent's file, over the same closed window: exactly two external deposits reached SOLVENT's wallet, 202.23708931 and 1001.08620000 USDT, both bare `transfer()` calls from externally owned accounts, totalling 1203.323289 USD, and the owner's sweep found nothing transferred out. The dollar-pegged balance rose from 45.474198 to 1224.612900 USD, so the deposit-adjusted result is a **loss of 24.184588 USD** — -11.10% of the 217.88 USD of time-weighted capital (Modified Dietz, block-second weights) and -1.94% of the 1248.80 USD the account opened with and received together. Doing nothing with the same contributions returns exactly 0.00 USD; reading the balance change as the result gives +1179.14 USD and is wrong by exactly what was paid in. **It is the wallet's return, not provably the agent's**: the wallet sent 113 transactions and the chain names 37 distinct hashes, so at least 76 are named nowhere in it, and chain data cannot separate an agent-engine trade from an operator trade signed with the same key. **Gas is excluded**, so the loss is a floor. **No time-weighted return is published as a figure** — over marks of 1400 to 1800 USD it runs from -15.31% to +1.19% and does not settle the sign. It adds to 06 and refutes nothing in it. Registration ordering is `uncommitted`. |

Every failed security scan in both dated runs was an HTTP 429 rate limit. The older
experiment remains readable beside the post-deploy run; neither is a substitute for the
registered held-out v3-04 evaluation.

Never quote a v2 figure without the null it was read against — they are in the same
object for that reason. Never describe the replay as a trade, a return or a backtest
result: nothing was sent, and the series is a centralised venue's while the plan
addresses an on-chain pair.

### The v3 report: registered paired work, with artifact-derived state

```bash
curl -s "$DOCKET/advantage/v3.json"
```

The reports are additive and none supersedes another. v1 is the original paired eligibility
artifact at n=1. v2 is agent-versus-computed-null armour with no human arm. v3 is the
registered paired evaluation scored by two prompt-blinded model seats. V3-06 discloses
Codex as its assisted baseline operator and makes no human-versus-agent claim.

Read `summary.states` before describing v3. `v3-04-warden-security` is
`complete_unscored` with `score_sheets_missing`. Both calibration seats passed first
attempt at 8/8 decisions, 8/8 verdicts and class micro-F1 1.0000. All 24 primaries were
claimed and terminal: 23 succeeded and manual `w4-ho-01` failed. The ledger proves
`invoke_error` / `JSONDecodeError`; the operator's contemporaneous account says a crib
sheet absent from this repository led to payload text being pasted instead of the required
JSON answer object. Seat A returned 4,452 first-response bytes; seat B returned no response
within the adapter's 300-second limit. The registered rule forbids another request or
evaluator substitution, so no second sheet or A/B mapping exists, disagreement cannot be
computed, rubric quality is permanently unscored, and no registered falsifier verdict exists.

Read-only frozen-label formulas—not a published §10 result—give recall of 4/8 (0.50) for
Warden and 6/8 (0.75) manually; precision of 4/4 (1.00) and 6/8 (0.75); valid scans of
12/12 and 11/12; three Warden critical failures; 11/12 complete pairs; median saving
27.86 seconds; and median agent/manual ratio 0.0610434. Warden missed its recall,
zero-critical, complete-pair, and median-saving limbs. Missing rubric medians prevent the
complete registered falsifier from being evaluated, so the report publishes neither
`refuted` nor `not_refuted`. At the committed-artifact observation on 2026-08-29, the
committed v3 artifacts contain 7 families: `v3-02-yield-router` is
`abandoned_after_failed_primary`; `v3-04-warden-security` is `complete_unscored`;
`v3-05-range-doctor` is `locked_not_run`; `v3-06-yield-router-assisted` and
`v3-07-range-doctor` are
`registered_waiting_for_inputs`; `v3-01-range-doctor` and `v3-03-warden-security` are
`superseded_before_input_lock`. V3-06 is a distinct successor with a future capture,
fresh input lock and Codex-assisted baseline. It is not a retry or relabeling of v3-02.
Never turn `not_refuted` into "proved".

The process builds one v3 payload at startup and renders `/advantage/v3` from that exact
object. Use the JSON for machine work and the page for a reader; neither changes until the
process restarts. Do not infer missing outputs, score sheets, mappings, costs, or falsifier
results from a registration. They appear only when the corresponding artifacts exist.

## Workflow 6: quote the escrow rail without promising a fast settlement

```bash
curl -s "$DOCKET/escrow"                 # terms, addresses, the ordered call sequence
curl -s "$DOCKET/escrow/job/56585"       # one job's live state and its settle_at
```

Use `/hire` when the user wants an answer now. Use `/escrow` when they want a job done
and the budget held until it is.

The one thing you must carry into any answer about this rail is the **7 day** dispute
window. It is not a default, a target, or something Docket can waive: the policy has no
early-accept path, so no call by anyone shortens it. Telling a user they can hire and
settle today would be wrong, and they would find out after funding.

Say these plainly if the rail comes up:

- Docket never holds the key, the signature, or the escrowed funds. It publishes the
  call sequence; the user executes it.
- `hire_sequence` is a template: target, function and argument shape per step, and no
  calldata field on any of them. That is correct behaviour, not a truncated response.
  The steps needing a job id say so in `needs`; `createJob` has to land first.
- `settle()` is permissionless: when the policy returns a final verdict, any address
  with BNB for gas may submit it. Docket publishes the job state and ships a separate,
  disarmed helper gated by `DOCKET_SETTLE_KEY`, but no public API route, timer or scheduler
  calls it. Automatic closing is neither wired nor demonstrated; arrange a caller.
- Mainnet only. The testnet route is dead at the router, not withheld.

Read `settle_ready` and `settle_at` from `/escrow/job/{job_id}` rather than computing
the date yourself, and never describe a job as settled because its window has passed.
The state read is advisory; automatic settlement is not configured and no Docket settlement
has occurred.

## Workflow 7: find a service by the job it does, then run it

```bash
curl -s "$DOCKET/categories"                      # the four jobs and what stands in each
curl -s "$DOCKET/services?category=rebalancing"   # the services in one job
curl -s "$DOCKET/services/range-doctor"           # inputs, metrics, evidence, limits
curl -s -X POST "$DOCKET/hire/range-doctor" \
  -H 'content-type: application/json' -d '{"wallet":"0x...","limit":5}'
```

That is the whole route from a job to a result: `/categories` to `/services` to
`hire_path`, which every card carries alongside `hire_method` so nothing has to be
guessed. Services are ordered by service id and by nothing else - there is no ranking
here to read as one - and `?category=` accepts only the four slugs, refusing anything
else with `422 invalid_query_parameter` naming them.

If the user starts from an agent instead of a job, read `/agents/{agent_id}` and follow
its `associated_services` cards to the same `hire_path`. That array is Docket's explicit
marketplace binding. It is not a service or category claimed by the ERC-8004 identity.

Three things to carry into any answer built on this layer:

- **A category is Docket's declaration about a service Docket runs, not a measurement.**
  An ERC-8004 registration says nothing about what job an agent does, so no agent in
  `/agents` carries a category and you must not infer one from a name or description. If
  asked which registry agents do LP rebalancing, say Docket does not know.
- **All four categories have a service in them today, and every one of those services
  previews rather than acts.** No shelf returns `service_count` 0 right now, and the
  empty state has not gone away: a category with nothing in it returns 0 and an `empty`
  sentence explaining why, with no date in it. Report a bare shelf as bare, and report a
  stocked one as what it is — read `limitations` before quoting any card. Two of the four
  carry a caveat about their own name: `health_factor` is named after a figure Venus does
  not publish, so `health-guard` repeats Venus's liquidity and shortfall verbatim and
  derives a ratio with its method stated inline; and `yield_optimisation` invites "the
  highest APR", so `yield-router` states the set that superlative is bounded by. Its
  comparison needs no wallet; its optional swap draft requires `wallet`, `token_in`,
  `token_out`, `amount`, and `cap` together.
- **`identity` and `agent_path` are different facts.** Range Doctor, Grid Operator,
  Yield Router, and Health Guard are BSC ERC-8004 agents 311253, 311255, 311257, and
  311259 in registry `0x8004a169fb4a3325136eb29fa0ceb6d2e539a432`. They were minted
  on 2026-08-28 UTC, all four had owner
  `0xe55816904796341bf8535e25f6c8b647927fc946` when recorded, and each token URI names
  its matching published registration document. `warden-scan` remains unbound.
  `agent_id` set with `agent_path: null` means an identity is registered on chain but is
  not in the snapshot Docket serves - the default sweep only covers agents with feedback.
  Registration is not endorsement, evidence of paid stock, or evidence that the service
  produced a result.

Every service card carries `evidence_modality` from the closed vocabulary `live_read`,
`preview`, `historical`, `paired_benchmark`, or `replay`. Current cards use `live_read`
for Range and Warden, `preview` for Grid, Health and Yield, and `historical` for SOLVENT.

Use `GET /compare` when the user needs the six services side by side. Its `job` is the
one-clause `job_summary`, `typical_seconds_basis` is `declared`, and a recorded pair's
`measured.basis` says `measured, n=1, YYYY-MM-DD`. `freshness` dates the recorded read or
states that it is read live at hire time. `evidence` is either
`{available: true, url, label}` or `{available: false, reason}`, never an empty cell.

Every figure under `metrics` carries `window`, `observed_at`, `method`, and its
denominator where it has one. `display` is the figure as text with the denominator
inside it. Quote `display`, or quote `numerator` and `denominator` together; a numerator
alone is the same unreadable claim as a rate with no base.

## What Docket will not give you

No safety rating, trust score, rank, or recommendation - the response models forbid
those field names and a test enforces it, and the same list is scanned across the values
of every service record and response, so the words cannot return as prose. Docket lists
no agent as safe and calls no service the best one. If a user asks "is this agent
trustworthy", answer with the observations and their coverage, name what is missing, and
leave the judgement with them.
