# API and payment semantics

## Application contract

The application factory is `docket.api:create_app`. JSON errors have one shape:

```json
{"error": {"code": "machine_readable_code", "message": "human-readable detail"}}
```

The root content-negotiates: a browser requesting HTML receives the landing page; a client
requesting JSON receives the endpoint index.

| Method and path | Meaning |
|---|---|
| `GET /health` | Process status plus the served snapshot's ID, capture time, and current age |
| `GET /canary` | Durable canary history and the resulting dynamic admission decision |
| `GET /stats` | Observation counts with coverage and denominators |
| `GET /agents` | Paginated agents from the startup-bound snapshot |
| `GET /agents/{agent_id}` | One agent, observations, coverage, and explicitly bound services |
| `GET /categories` | Four Docket-declared jobs and service counts |
| `GET /services` | All service cards or one typed category |
| `GET /services/{service_id}` | Full service inputs, limitations, evidence, and identity note |
| `GET /hire` | Callable catalogue, terms, stock state, and admission booleans |
| `POST /hire/{service_id}` | Run one service and return result plus receipt |
| `GET /escrow` | ERC-8183 job template and chain terms |
| `GET /escrow/job/{job_id}` | Read one live ERC-8183 job from chain |
| `GET /advantage.json` | V1 paired single-observation artifacts |
| `GET /advantage/v2.json` | V2 registered experiments and computed report |

There is no v3 API route because v3 has specifications only and no input/run/report.

`GET /health` returns `snapshot_captured_at`, the exact capture time of the snapshot
bound at startup, and `snapshot_age_seconds`, its age in whole seconds when the response
is made.
Every `coverage` object repeats that snapshot's `captured_at` and computed
`snapshot_age_seconds`, so freshness is a served fact rather than something a caller has
to imply from an old timestamp. Both age fields are null when no valid capture time exists.

## Categories and identities

`GET /categories` returns a `declaration` explaining that a category is Docket's statement
about a service it runs. ERC-8004 does not supply that classification.

`GET /services` exposes `agent_id` and an `identity` string. The four category services
have no registered identity. SOLVENT alone is bound to
`56:0x8004a169fb4a3325136eb29fa0ceb6d2e539a432:136384`. A missing identity is returned as
missing rather than inferred from owner or endpoint similarity.

## Catalogue and admission

Every `GET /hire.services[]` record contains:

- `id`, `name`, and `what_you_get`
- the complete `input_schema`
- `typical_seconds`
- `price_display`, `price_atomic`, and `asset`
- `paid_stock` and `stock_status`
- `admission` with `fresh_paired_benchmark`, `cold_canary`,
  `decision_grade_presenter`, and `true_settlement`

`paid_stock` is the conjunction of those four admission values, recomputed from durable
state on every catalogue, service-detail, service-card, and paid-hire decision. The
latest canary run controls the `cold_canary` limb: only `passed` with a UTC
`finished_at` no more than 36 hours old opens it. An absent, running, failed,
`not_yet_exercised`, future-dated, or stale latest run closes it. `GET /canary` exposes
the 129600-second limit, latest run, bounded newest-first history, the resulting four
facts, and `paid_stock`; history starts empty. It is false for all six services now.
Every durable run names its target, start and finish time, verdict, and structured checks;
each check records the leg, what was checked, its status, what was observed, and the
evidence for the status. Closing the gate removes Pay and hire but leaves the free
verified example and free preview available.
The shared catalogue term is 0.50 $U, represented as
`500000000000000000` atomic units of token
`0xcE24439F2D9C6a2289F741120FE202248B666666`; it is not an available purchase while
`paid_stock` is false.

## Free hire

Without a payment header, a current hire validates the JSON body, runs the service, and
returns:

```json
{
  "result": {},
  "receipt": {
    "service": "service-id",
    "input_hash": "0x...",
    "output_hash": "0x...",
    "delivered_at": "UTC timestamp",
    "payment": {"status": "free_tier"}
  }
}
```

The hashes are canonical SHA-256 object identities from `docket.hire.receipts`. They bind
the delivered request and result, not truth, endorsement, or finality.

If a public caller supplies a payment header to an unadmitted service, the service still
runs but the receipt says `not_for_sale`, includes `stock_status`, and sets
`authorization_used=false`.

## x402 exact settlement

The public paid branch requires both dynamic `paid_stock=true` and owner-supplied
settlement configuration. Enabling configuration cannot bypass admission.

There is one private bootstrap for measuring the paid path that governs its own
admission: the owner-operated canary may send `X-Docket-Canary`. Its value is loaded
from a private file and must never be printed, copied into documentation, returned by an
endpoint, or persisted as canary evidence. The header allows only that measured payment
branch while public admission is closed; it does not modify any admission fact or make
public `paid_stock` true. An absent or rejected value cannot use the bootstrap, and a
rejected value returns `403 canary_unauthorized` before work or payment.

For either an admitted public request or the authorized canary, the challenge uses x402
version 2, scheme `exact`, network `eip155:56`, the service's exact
amount/asset/recipient, and EIP-3009
`TransferWithAuthorization`. Local verification checks:

1. Resource equality with this hire URL.
2. Equality of the advertised payment requirements.
3. BSC chain and supported $U EIP-712 domain.
4. Exact recipient and amount.
5. Canonical six-field authorization and 32-byte nonce.
6. `validAfter < now < validBefore`.
7. Signature recovery to the declared payer.

After facilitator verification, the store atomically binds nonce, payment ID, service,
recipient, asset, amount, resource, and input hash. The result and output hash are persisted
before a one-way transition to `settling`. The facilitator's `/settle` call is made once.

Outcomes are intentionally terminal:

| Status/code | Meaning |
|---|---|
| `settled` | Facilitator returned success, transaction, network, and matching payer |
| `settlement_unknown` | Call returned no usable result; Docket will not retry automatically |
| `settlement_failed` | Facilitator refused settlement; authorization cannot be replayed |
| `failed_no_charge` | Work failed/empty before settlement; authorization cannot be replayed |
| `authorization_replay` | Nonce is bound to different work, or an exact identical authorization already settled |
| `authorization_spent` | Prior attempt reached a terminal state |

A `settled` receipt is evidence of the configured facilitator response. It is not an
independent receipt lookup or chain-finality proof. No committed Docket receipt has this
status and no live settlement transaction is recorded in the repository.

An exact identical settled request returns `409 authorization_replay`; it does not return
the stored result and cannot repeat either the service work or settlement.

## ERC-8183 escrow

This is a separate rail. `GET /escrow` publishes BSC mainnet chain ID 56, contract addresses,
$U payment-token metadata, the seven-day dispute window, and a five-call template for the
buyer to create/register/budget/approve/fund a job.

The template is not signable bytes because the job ID and final expiry do not exist yet.
The buyer supplies values and signs. Docket does not hold or proxy that key and does not
take custody of the escrowed funds.

The committed E1c result establishes through `eth_call` that the configured policy is open
on mainnet and that `settle` is permissionless for a ripe undisputed job. It explicitly
states that no call was broadcast. The source contains an optional broadcaster, but this
package has no artifact showing Docket created, funded, delivered, or settled a live job.

## Failure boundaries

- Invalid/non-object JSON: `400 invalid_json`.
- Missing required fields: `422 missing_field`.
- Invalid field value: `422 invalid_field`.
- Upstream/service failure: `502 service_failed`.
- Unknown service: `404 service_not_found`.
- Rejected private canary credential: `403 canary_unauthorized`; no work or charge.
- Settlement required/configuration absent for admitted stock: `503 settlement_unavailable`.
- Admission closes after payment verification: `503 service_de_admitted`; no result is
  delivered and settlement does not run.

An upstream timeout or 5xx is not converted into a partial success. SOLVENT and Warden
relay upstream structures; failure surfaces as a typed service error.
