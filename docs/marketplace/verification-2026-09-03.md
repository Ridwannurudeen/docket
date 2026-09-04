# Verified marketplace census — 2026-09-03

One read-only pass over the BSC ERC-8004 registry for agents doing the four jobs Docket
serves, with every candidate put through `docket.marketplace.verification.verify_listing`.

Nothing here was paid for and nothing was signed. The pass reads the 8004scan index, reads
`ownerOf`/`tokenURI` from public BSC RPCs, makes at most one guarded GET per declared
endpoint and at most one sample invocation, and stops. No tool an MCP server lists was ever
called; the one sample Docket sends is `tools/list`, which asks a server what it can do.

**Reproduce it:**

```
python -m docket.marketplace.census --out docs/marketplace --seed docket/marketplace/seed
```

That writes `docs/marketplace/census-2026-09-03.json` — every query, every candidate, every
level attempt with the response excerpt that decided it — and
`docket/marketplace/seed/external-listings-2026-09-03.json`, which the API loads into an
empty `external_listings` table at startup. Both are committed, and every figure below is
read out of the first.

Re-running against a live registry will not reproduce these figures byte for byte, and that
is a property of the subject rather than a defect in the method. The registry grew while
this lane was being built: the unfiltered total read 300,424 on the first exploratory query
of the morning and 300,595 when the committed pass ran. An earlier rehearsal of the same
script selected agent 269224 into the grid cap; by the time the committed pass ran, agent
330536 had been registered, sorted ahead of it on token id, and taken the sixth grid slot —
which is why the 2xx count moved from 13 to 12 without any host changing its behaviour. The
committed JSON is the record of what was observed between `2026-09-03T09:27:56Z` and
`2026-09-03T09:30:31Z`, and it is the only pass any figure here is read from.

## What the level names mean here

`registered` < `endpoint_detected` < `live` < `payment_tested` < `docket_tested` <
`docket_verified`, each defined in `docket/marketplace/verification.py` and in `/llms.txt`.
Three of them need saying plainly before any number below is read.

**`live` follows the liveness sweep's vocabulary: a response at any status.** A 404 proves
a host is up and answering; it also says the declared path is not there. So `live` is
published beside a second, narrower count — how many of those responses were 2xx — and the
per-agent tables print the status code for every one. All 26 reached `live`; 12 of the 26
answered 2xx. Reading "26 live" as "26 working agents" would be wrong by fourteen.

**`payment_tested` is read-only and nothing reached it.** It requires a 402 carrying a body
that parses as an x402 challenge. Docket reads such a challenge and never presents a
payment, so the level would have said "a price exists", not "paying works". No agent in this
census answered 402 at all.

**`docket_tested` means one thing: a sample invocation returned a schema-valid structured
result.** It does not imply a payment was tested, and it does not imply one was not. Read
as a strict chain, the level ordering would mean an endpoint that answers a real request
for free can never be tested, which would put a service that only quotes a price above one
that did the work — so `payment_tested` and `docket_tested` both hang off `live`, and the
ordering is for display. Every listing therefore carries `verification.payment_tested` as
its own boolean beside `verification.level`, with `verification.payment_tested_evidence`
holding the run that decided it. The one agent that reached `docket_tested` here is
serialised as `payment_tested: false` with the evidence row saying "the endpoint answered
without an x402 payment challenge". When the question is about payment, that boolean is
the answer and the level is not.

## Numerators and denominators

Window: one pass, 2026-09-03, BSC chain 56, IdentityRegistry
`0x8004a169fb4a3325136eb29fa0ceb6d2e539a432`.

| Figure | Count | Of what |
| --- | --- | --- |
| Registry size when the pass ran | 300,595 | agents the unfiltered `/agents` query reported for chain 56. A lower bound on the chain, not a census of it |
| Distinct agents matched by the twelve category queries | 262 | of 300,595 registered |
| Of those, declaring A2A or MCP | 76 | of 262 matched |
| Selected by classification (cap of 6 per category) | 24 | of 76 declaring an invocable protocol |
| Added because the pivot plan names them | 2 | 43129 and 171927; 6441 was already selected on its own text, so the plan's three add two |
| **Verified** | **26** | of 26 selected |
| Reached `registered` (`ownerOf` answered) | 26 | of 26 verified |
| Reached `endpoint_detected` | 26 | of 26 verified |
| Reached `live` (a response at any status) | 26 | of 26 verified |
| Of those, answered 2xx | 12 | of 26 live |
| Reached `payment_tested` | 0 | of 26 live |
| Reached `docket_tested` | 1 | of 26 live |
| Reached `docket_verified` | 0 | of 1 docket_tested |
| Chain reads that failed (outage) | 0 | of 26 `ownerOf` calls |
| Registrations declaring `x402_supported` | 20 | of 26 verified |

Highest level reached: `live` 25, `docket_tested` 1.
By category: rebalancing 6, grid_trading 6, health_factor 7, yield_optimisation 7.

### Against the targets set for this lane

| Target | Result |
| --- | --- |
| At least 8 listings across the four categories | **26** |
| At least 2 per category at level >= `endpoint_detected` | **6 / 6 / 7 / 7** — every listing in the census reached `live`, which is one level above `endpoint_detected` |
| At least one external agent at `docket_tested` | **1** — agent 43129, `Venus powered by HeyAnon` |

## The queries

`search=` on the 8004scan index matches whole tokens in an agent's name, description and
owner address. It is not a prefix match: `search=DeFiMatrix` returns nothing while
`search=DeFiMatrix.agent` returns the agent. `total` is what the index reported for that
narrowed query; `returned` is what one page of 50 held.

| Category | Query | Index total | Returned |
| --- | --- | --- | --- |
| rebalancing | `rebalancing` | 45 | 45 |
| rebalancing | `concentrated liquidity` | 23 | 23 |
| rebalancing | `liquidity position` | 83 | 50 |
| rebalancing | `LP range` | 6 | 6 |
| grid_trading | `grid` | 17 | 17 |
| yield_optimisation | `yield optimisation` | 3 | 3 |
| yield_optimisation | `yield router` | 2 | 2 |
| yield_optimisation | `APY` | 421 | 50 |
| yield_optimisation | `supply rate` | 34 | 34 |
| health_factor | `health factor` | 19 | 19 |
| health_factor | `liquidation` | 341 | 50 |
| health_factor | `lending position` | 9 | 9 |

Three queries hit the page cap, so their populations are larger than the rows this pass
saw: `liquidity position` (83), `APY` (421) and `liquidation` (341). The census is a bounded
sample of those, not a sweep of them, and the per-category cap of six bounds it further.
Nothing here should be read as "these are the BSC agents in this category".

## Per-agent outcomes

`source` is where the category came from: `docket_classified` means Docket's published
keyword rule table read the registration text; `registration_metadata` means the
registration's own `agent_type`/`categories` field said so. No agent in this census has a
provider-signed claim, so none is `provider_declared`. `x402` is what the registration
declares about payment support, which is not what its endpoint did.

### rebalancing

| Agent | Name | Source | Level | Status | x402 | Endpoint | Why it stopped |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 331750 | Assay Range | docket_classified | live | 200 | yes | a2a `assay-ten-iota.vercel.app/api/agents/range` | A2A with no declared sample input; Docket will not call an agent card a result |
| 331698 | SMEAI Reference PancakeSwap LP Monitor | docket_classified | live | 200 | yes | a2a `smeai-dev.vercel.app/api/a2a/lp` | same |
| 325413 | Sentinels LP Rebalancer | docket_classified | live | 401 | yes | a2a AWS Bedrock AgentCore runtime | the endpoint exists and refused an unauthenticated read with 401 |
| 302610 | test.agent | docket_classified | live | 404 | no | a2a `platform-backend.prod.termix.live/.../{agentId}/card` | the registered URL is an unexpanded template — `{agentId}` is literal — and the host answers 404 for it |
| 293902 | mandaterebalance-agent | docket_classified | live | 200 | yes | a2a `gvwyso8occ.execute-api.us-east-1.amazonaws.com/.well-known/agent-card.json` | A2A with no declared sample input |
| 293054 | bnb-lp-quant.agent | docket_classified | live | 404 | no | a2a `platform-backend-bnb8183.prod.termix.live/.../{agentId}/card` | same unexpanded `{agentId}` template |

### grid_trading

| Agent | Name | Source | Level | Status | x402 | Endpoint | Why it stopped |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 331751 | Assay Grid | docket_classified | live | 200 | yes | a2a `assay-ten-iota.vercel.app/api/agents/grid` | A2A with no declared sample input |
| 330536 | Sentinels Grid Trader | docket_classified | live | 401 | yes | a2a AWS Bedrock AgentCore runtime | refused an unauthenticated read with 401 |
| 303779 | marketplace-operated-grid-planner | docket_classified | live | 200 | yes | a2a `bnb-agent-marketplace-ruby.vercel.app/grid/.well-known/agent-card.json` | A2A with no declared sample input |
| 302258 | Brain on BNB — BSC Grid Planner | docket_classified | live | 200 | yes | a2a `agent.brainonbnb.com/a2a` | same |
| 292939 | bnb-grid-trader-test.agent | docket_classified | live | 404 | no | a2a `platform-backend-bnb8183.prod.termix.live/.../{agentId}/card` | unexpanded `{agentId}` template; the host answers 404 |
| 269233 | BNB Grid Trader (test) | docket_classified | live | 200 | yes | a2a `bnb-grid.172-104-171-139.nip.io/.well-known/agent-card.json` | A2A with no declared sample input |

### yield_optimisation

| Agent | Name | Source | Level | Status | x402 | Endpoint | Why it stopped |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 331752 | Assay Yield | docket_classified | live | 200 | yes | a2a `assay-ten-iota.vercel.app/api/agents/yield` | A2A with no declared sample input |
| 326106 | Sentinels Yield Router | docket_classified | live | 401 | yes | a2a AWS Bedrock AgentCore runtime | refused an unauthenticated read with 401 |
| 315721 | airdropium.agent | docket_classified | live | 404 | no | a2a `platform-backend.prod.termix.live/.../{agentId}/card` | unexpanded `{agentId}` template |
| 171927 | DeFiMatrix.agent | docket_classified | live | 404 | no | a2a `platform-backend.prod.termix.live/.../{agentId}/card` | **named by the plan.** Its registered A2A endpoint is a literal unexpanded template; the host answers 404 for the URL as registered |
| 133221 | eights.me | docket_classified | live | 404 | yes | a2a `me.hyreagent.fun/agent/eights/.well-known/agent-card.json` | the host answered; the card path did not |
| 6443 | Sperax Intelligence | docket_classified | live | 404 | yes | a2a `modelcontextprotocol.name/.well-known/agent-card.json` | the registered card path 404s |
| 6441 | DeFi Trading Agent SperaxOS | docket_classified | live | 404 | yes | a2a `modelcontextprotocol.name/.well-known/agent-card.json` | **named by the plan.** Registers the same third-party card URL as 6443, and it 404s |

### health_factor

| Agent | Name | Source | Level | Status | x402 | Endpoint | Why it stopped |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 43129 | Venus powered by HeyAnon | docket_classified | **docket_tested** | 200 | yes | mcp `erc8004.heyanon.ai/mcp/venus` | **reached the level.** `tools/list` returned a valid JSON-RPC result carrying 16 tools; the result hash is in the census JSON. Stopped below `docket_verified` because no paired-benchmark family is registered for it |
| 331625 | SMEAI Reference Health Factor Monitor | docket_classified | live | 200 | yes | a2a `smeai-dev.vercel.app/api/a2a` | A2A with no declared sample input |
| 330663 | Sentinels Health Guard | docket_classified | live | 401 | yes | a2a AWS Bedrock AgentCore runtime | refused an unauthenticated read with 401 |
| 302257 | Brain on BNB — Venus Health Factor Monitor | docket_classified | live | 200 | yes | a2a `agent.brainonbnb.com/a2a` | A2A with no declared sample input |
| 292058 | bnb-lending-guardian.agent | docket_classified | live | 404 | no | a2a `platform-backend-bnb8183.prod.termix.live/.../{agentId}/card` | unexpanded `{agentId}` template |
| 269228 | Health Factor Monitor | docket_classified | live | 200 | yes | a2a `agents.chainhelix.io/healthmon/.well-known/agent-card.json` | A2A with no declared sample input |
| 266933 | BNB Lending Guardian | registration_metadata | live | 405 | yes | a2a `bnb-guardian.172-104-171-139.nip.io/a2a` | the endpoint refuses GET with 405, which is a JSON-RPC endpoint behaving correctly; Docket has no A2A sample to POST |

## What this census did not reach, and why

**Nothing reached `payment_tested`.** Not one of the 26 endpoints answered 402. Twenty of
the 26 registrations declare `x402_supported`; none of those twenty declarations was backed
by a challenge on the endpoint Docket probed. That is a finding about the registry rather
than a gap in the check: `payment_tested` is implemented, exercised on every listing, and
recorded as `false` with the observed status beside it. A registration field is a claim; a
402 body is evidence, and here there are twenty of the first and none of the second.

**Nothing reached `docket_verified`, and nothing could have.** The level requires
`docket_tested` plus a registered paired-benchmark family, and Docket's v3 families are
registered against Docket's own service ids (`hire.catalogue.SERVICE_BENCHMARK_FAMILIES`).
`verification.benchmark_ref` returns `None` for every external listing by construction. The
level is computed and recorded as unreached rather than skipped, so the day a family is
registered for an external agent the ladder already runs the check.

**Only one agent reached `docket_tested`, and the reason is structural rather than a
shortfall of effort.** 25 of the 26 declare A2A. `docket_tested` — and therefore `hireable`
— can only be reached by a sample Docket itself defined, and Docket has exactly one: the MCP
`tools/list` capability query. There is no equivalent default for A2A that is both free of
side effects and a result rather than a description: the only zero-cost A2A read is the
agent card, and a card describes an agent rather than being something the agent produced.
Handing out `docket_tested` for serving a card would be the exact inflation the ladder
exists to prevent.

A provider-supplied sample cannot raise the level either, however well it validates. A
seller who supplies both the input and the schema it is checked against is a seller
certifying themselves, so such a sample is sent, checked and published under the evidence
row `provider_sample_ok`, which sits outside the level vocabulary and carries
`raises_level: false`. The two honest routes to a higher number are therefore a
Docket-defined per-category request for A2A, which does not exist yet, or more MCP agents
registering. Neither was available to this read-only census.

**Six endpoints are registered as unexpanded templates.** Agents 302610, 293054, 292939,
292058, 315721 and 171927 all register an A2A endpoint containing the literal characters
`{agentId}`, across two Termix platform hosts. The URL is recorded verbatim, as registered,
and probed as registered; Docket does not guess an expansion, because a guess that happened
to work would publish an observation of a URL nobody registered. All six hosts answer, and
all six answer 404 for the path as written.

**Four endpoints refuse an unauthenticated read.** 325413, 330536, 330663 and 326106 all sit
behind AWS Bedrock AgentCore runtimes and answer 401. The host is up and the runtime exists;
Docket holds no credential for it and will not manufacture one, so those four stop at `live`
with the 401 recorded.

**The index and the chain disagree, and the chain wins.** `GET /agents/56/311253` on 8004scan
answered 404 on 2026-09-03 for a token whose `ownerOf` returns Docket's own address. An index
miss is therefore not evidence that an agent is unregistered, which is why `registered` is
decided by `IdentityRegistry.ownerOf` and never by the index.

## What a category on these listings is

Every listing carries `capability_source`. For 25 of these 26 it is `docket_classified`:
Docket's keyword rule table, printed in full in `docket/marketplace/external.py`, read the
registration's own capability text and matched it. `classification_rationale` on every
listing names every rule that matched and every category that lost.

This is a reading of published prose, labelled as a reading. It is not measured, it is not
declared by the operator, and it is not on `/agents` — the snapshot plane still assigns no
category to anybody. A tie between two categories assigns nothing at all.
