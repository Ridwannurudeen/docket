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
DOCKET=http://127.0.0.1:8099   # the origin serving this file; no public host yet
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
| GET | `/llms.txt` | Full plain-text reference |
| GET | `/skill.md` | This file |
| GET | `/openapi.json` | Generated OpenAPI 3.1 schema |

`/agents` parameters: `has_feedback`, `declares_callable`, `responded` (booleans),
`publisher` (exact match), `limit` (default 50, capped at 100), `offset`. `total` is
counted after filtering and before pagination.

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
- Right: "13 of the 35 endpoints Docket probed responded (37.143%), in snapshot 3
  captured 2026-08-07, which covers the 506 BSC agents that have any feedback -
  0.205% of the roughly 247,278 registered."

`responded_pct_of_probed` is named for its denominator so it cannot be requoted
against the registry. Do not restate it as a share of anything else.

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
share of 31 attempted - not of 506, and not of the registry.

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
 "sampled": 506, "expected": 506, "dropped": 0, "complete": true, "filter": null}
```

- `complete: false` or `dropped > 0` means rows are missing and every count in that
  response understates its population. Say so when you quote it.
- `filter` names the subset the response describes. `/agents?has_feedback=true`
  returns `"filter": "has_feedback=true"`; a count taken from it is a count of that
  subset only.
- `captured_at` is when the snapshot was taken, not now. Liveness outcomes are
  observations from that moment and go stale.

The same snapshot 3 figures, in full: 506 sampled of 506 expected, 31 declaring a
callable endpoint, 78 endpoint registration rows resolved, 35 probed, 13 responded
(37.143% of probed), 10 blocked by policy, 11 unresolved, 1 timed out, across 421
distinct publishers.

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

## What Docket will not give you

No safety rating, trust score, rank, or recommendation - the response models forbid
those field names and a test enforces it. Docket lists no agent as safe. If a user
asks "is this agent trustworthy", answer with the observations and their coverage,
name what is missing, and leave the judgement with them.
