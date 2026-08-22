# Architecture

Docket has four separate planes so an observation, a marketplace declaration, an action
draft, and evidence about prior work cannot silently become the same kind of fact.

Competition context: the BNB Chain main track has one $30,000 winner plus official
adoption; it is not a shared prize pool.

```text
8004scan response
      |
      v
snapshot ingest --> SQLite snapshot --> enrichment + guarded probes --> coverage-bound API

static service records --> category/service API --> hire runner --> hash-bound receipt
                                                   |
                                                   +--> optional x402 settlement (off)

action intent --> policy checks --> simulation --> authority/session checks --> submitter

committed inputs/specs/runs --> v1/v2/v3 report builders --> HTML + JSON evidence routes
```

## Observation plane

`docket.scan8004` reads the 8004scan internal API. `docket.ingest` stores a snapshot with
the population query, expected count, sampled count, stop reason, and timestamps. Docket
does not claim this is a direct chain index or a census when the source query is filtered.

`docket.enrich` resolves declared endpoint metadata. Before a liveness request,
`docket.netguard` resolves and rejects loopback, private, link-local, multicast, reserved,
and otherwise non-public destinations. `docket.liveness` sends no redirects and records
attempt, outcome, status, latency, and detail as a new observation rather than overwriting
history.

`docket.coverage` computes every published count against a `Coverage` object. The public
contract distinguishes targets evaluated, requests attempted, responses received, blocked
targets, unresolved targets, and the population/filter that produced the snapshot.

## Marketplace plane

`docket.marketplace.models` defines the closed category vocabulary, service records,
denominator-bearing metrics, evidence references, and identity links.
`docket.marketplace.registry` is Docket's declaration layer over its own services; the
category is not read from ERC-8004.

`docket.hire.catalogue` defines the six callable units, input schemas, admission state,
catalogue term, stock state, and runner. The current inventory is one candidate, three
previews, one research service, and one beta service. Every admission evaluates false, so
none is paid stock.

`POST /hire/{service_id}` validates input, runs the service, and returns a receipt containing
the canonical request hash, result hash, delivery time, service ID, and payment state. The
hashes bind bytes to a delivery record; they do not establish result quality.

## How a third party would list

There is no provider onboarding route today. A third-party listing would require a source
change and review, using the pieces that already exist:

1. **Manifest:** map the provider's declaration into the existing `ServiceRecord` fields,
   including its category, activation/identity data, denominator-bearing metrics, evidence
   references, and limitations. Add a catalogue entry only when Docket can actually call the
   service.
2. **Verifier:** run the existing endpoint enrichment and SSRF-guarded liveness probe. That
   records whether the declared endpoint was reachable at an observation time; it does not
   establish the content's correctness.
3. **Receipt:** for a callable catalogue service, use the existing receipt builder to bind
   canonical input and output hashes to the service, delivery time, and payment state.

That Manifest → Verifier → Receipt shape describes an extension path, not current third-party
inventory. It does not make a listing paid stock, establish settlement, or create a v3 result.

## Payment planes

There are two distinct rails.

The x402 rail in `docket.hire.x402` is for one request answered and settled now. It verifies
the exact resource, BSC network, $U asset/domain, amount, recipient, authorization window,
nonce, and signature. `docket.store` persists the nonce-to-input/output transition before
the single facilitator settlement call. This path is disabled by default and unreachable
for the current unadmitted stock.

The ERC-8183 rail in `docket.escrow` is a separate buyer-funded job with a seven-day dispute
window on BSC mainnet. The API publishes a transaction template; the buyer fills and signs
it. Docket holds no buyer key or escrow. The committed E1c artifact used `eth_call` only and
did not broadcast settlement.

## Action plane

`docket.execution.intent` creates deterministic, hashable action descriptions.
`docket.execution.simulate` obtains quote and call evidence. `docket.execution.authority`
and `docket.execution.state` enforce the allowlist, spend cap, expiry, revocation, and state
transition before a submitter can act.

The public Grid hire constructs `GridPreview`, which has no signer or submitter. The Health
Guard has no armed counterpart. Yield can draft one swap leg only when all five execution
inputs are supplied together, but the public service does not sign, approve, or submit it.
Range Doctor is read-only.

## Evidence plane

V1 stores three paired single-observation experiment records in
`docket/advantage/experiments/` and serves them at `/advantage.json`.

V2 stores corpora, hash-bearing specifications, runs, null baselines, every trial, and
computed falsifiers under `docket/advantage/v2/`. `docket.advantage.v2.report.report()` is
the common builder for `/advantage/v2.json` and its HTML page.

V3 stores three stage-one paired specifications plus its claim-once runner, prompt-blinded
scoring, and artifact-derived report under `docket/advantage/v3/`. It has no input or run
artifacts today, so all three families serve `registered_waiting_for_inputs` at
`/advantage/v3.json`. Its registration fields identify a local Git sequence only; see
[Evidence reproduction](evidence-reproduction.md#the-git-witness) for the external-anchor
limitation.

## Runtime and persistence

The application factory is `docket.api:create_app`. At startup it opens a SQLite store,
selects the newest complete chain-56 snapshot once, and loads the v1, v2, and v3 artifacts.
The v2 and v3 pages are each rendered from the same startup object returned by their JSON
route. Observation reads stay bound to that startup snapshot. Hire payment lifecycle writes
use the same SQLite file.

The default database path is relative: `data/agents.sqlite3` under the process working
directory. A clean installed-wheel smoke starts from a temporary directory and therefore
cannot read or alter the repository's database.
