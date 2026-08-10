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

Do not use it to decide whether an agent is trustworthy. Docket does not answer that
question, and nothing in its output should be presented as if it did.

## Setup

```bash
DOCKET=https://docket.gudman.xyz   # the public host; or the origin serving this file
curl -s "$DOCKET/health"       # {"status":"ok","snapshot_id":3}
```

No authentication, no key, no account, no wallet. Every path but one is GET and
read-only; `POST /hire/{service_id}` is the one route that runs work, and it needs no
credentials either. `GET $DOCKET/llms.txt` is the full reference;
`GET $DOCKET/openapi.json` is the generated schema. If a workflow is not in one of
those, Docket does not serve it - say so rather than inventing an endpoint.

## Endpoints

| Method | Path | Returns |
| --- | --- | --- |
| GET | `/` | Service identity and orientation links |
| GET | `/health` | Docket's liveness and the snapshot id being served |
| GET | `/stats` | Every generated figure, inside its coverage |
| GET | `/agents` | Filterable listing with `total`, pagination, coverage |
| GET | `/agents/{agent_id}` | One agent, its endpoints, and every observation of them |
| GET | `/hire` | The catalogue: every service, its input schema, price, typical seconds |
| POST | `/hire/{service_id}` | Runs the service; returns the result and a hash-bound receipt |
| GET | `/escrow` | Escrow terms: addresses, dispute window, the ordered call sequence |
| GET | `/escrow/job/{job_id}` | One job's live on-chain state and when it can be settled |
| GET | `/advantage.json` | Three hired-vs-manual experiments, both arms in full, with deltas |
| GET | `/advantage` | The same report as a page for a human |
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
`no_snapshot`, and on the hire routes `service_not_found` (404), `invalid_json` (400),
`missing_field` (422, the message names the field), `invalid_field` (422),
`free_tier_exhausted` (402), `service_failed` (502).

## The rule: a number is never quoted alone

Every count and percentage Docket returns is a fact about one snapshot and one
population. Quote it with its coverage, or do not quote it.

- Wrong: "37% of BSC agents respond."
- Right: "13 of the 14 endpoints an HTTP request reached responded (92.857%), which is
  13 of the 35 endpoints evaluated (37.143%) once the 10 targets Docket refused and
  the 11 hostnames that would not resolve are counted back in - in snapshot 3 captured
  2026-08-07, which covers the 506 BSC agents that have any feedback - 0.205% of the
  roughly 247,278 registered."

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
 "sampled": 506, "expected": 506, "dropped": 0, "complete": true,
 "population": null, "filter": null}
```

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
- `captured_at` is when the snapshot was taken, not now. Liveness outcomes are
  observations from that moment and go stale.

The same snapshot 3 figures, in full: 506 sampled of 506 expected, 31 declaring a
callable endpoint, 78 endpoint registration rows resolved, 35 endpoints evaluated, 14
of them reached by an HTTP request, 13 responded (92.857% of attempted, 37.143% of
evaluated), 10 blocked by policy, 11 unresolved, 1 timed out, across 421 distinct name
families.

## Workflow 4: hire Range Doctor for a wallet

Read the catalogue, then call it. No account, key, wallet or signature is needed - the
free tier serves the work on the first request.

```bash
curl -s "$DOCKET/hire"
curl -s -X POST "$DOCKET/hire/range-doctor" \
  -H 'content-type: application/json' \
  -d '{"wallet":"0x451871A1753903FB8fdd64a6B838E95aB8D5B80f","limit":5}'
```

`GET /hire` carries each service's `input_schema`, so build the body from that rather
than from this example. `limit` is optional and bounds how many of the wallet's
position NFTs are read, newest first; the result reports `positions_held` and
`positions_examined`, so say what was left out when a read was bounded.

The response is `{"result": {...}, "receipt": {...}}`. Verify the receipt before
quoting it - the hashes are plain SHA-256 over canonical JSON and need none of
Docket's code:

```python
import hashlib, json

def digest(obj):
    blob = json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "0x" + hashlib.sha256(blob.encode("utf-8")).hexdigest()

assert digest(request_body) == receipt["input_hash"]
assert digest(response["result"]) == receipt["output_hash"]
```

`ensure_ascii=False` is part of the recipe: with `ensure_ascii=True` a non-ASCII
payload hashes to something else.

`receipt["payment"]["status"]` is `free_tier` or `verified_unsettled`. Report the
second one precisely: it means Docket checked an EIP-712 signature - right recipient,
right amount, chain 56, unexpired, recovering to its declared payer - and **did not
settle it**. Nothing was broadcast, no balance was read, nothing moved; the receipt
says `"settlement": "not performed by Docket"`. Never describe such a hire as settled.

Where a payment recipient is configured, the free tier is an allowance of 20 hires per
caller per hour and it counts every hire that ran, authorization or not. A request
Docket could not read - unknown service, non-JSON body, missing or unparseable field -
costs nothing, so a fumbled request cannot lock out the next caller sharing your
address. Spending the allowance returns `402` carrying an x402 v2 challenge
(`x402Version`, `accepts`) alongside the error object. Where no recipient is configured
there is no allowance at all.

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
- `settle()` is permissionless, so the wait does not require the user to come back;
  Docket closes jobs it brokered once `settle_at` passes.
- Mainnet only. The testnet route is dead at the router, not withheld.

Read `settle_ready` and `settle_at` from `/escrow/job/{job_id}` rather than computing
the date yourself, and never describe a job as settled because its window has passed —
a disputed job stays open, and the same response tells you whether it is disputed.

## What Docket will not give you

No safety rating, trust score, rank, or recommendation - the response models forbid
those field names and a test enforces it. Docket lists no agent as safe. If a user
asks "is this agent trustworthy", answer with the observations and their coverage,
name what is missing, and leave the judgement with them.
