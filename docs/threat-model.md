# Threat model

## Scope

This model covers the Python package, FastAPI surface, SQLite state, outbound discovery and
protocol reads, action-intent machinery, x402 boundary, ERC-8183 helper, packaged evidence,
and browser assets. It does not assert the security of 8004scan, PancakeSwap, Venus, $U,
ERC-8004/8183 contracts, RPC providers, a facilitator, nginx, a VPS, or any untracked
deployment configuration.

## Assets

- Integrity and scope of agent observations.
- Service/category declarations and limitations.
- Request, output, payment, nonce, and receipt bindings.
- Spend caps, allowlists, deadlines, revocation state, and action calldata.
- Evidence corpus/spec/run bytes and their hashes.
- SQLite snapshot and payment lifecycle state.
- Runtime credentials if an owner later supplies them outside the repository.

## Actors and trust boundaries

| Actor or boundary | Trust posture |
|---|---|
| API caller | Untrusted input, including JSON, addresses, arrays, integers, and payment headers |
| 8004scan/internal API | External observation source; not a direct-chain ground truth |
| Agent-declared endpoints | Untrusted network destinations and response bodies |
| BSC RPC/explorer/protocol APIs | External, mutable, and potentially unavailable |
| Service runner | Trusted to stay within its code-level capability, not trusted to be correct |
| x402 facilitator | External verifier/settler; its response is not chain-finality proof |
| SQLite file/process account | Trusted state boundary; compromise can alter snapshots and payment state |
| Repository owner/Git history | Self-controlled until a registration or release hash is anchored externally |
| Browser | Untrusted display/input boundary; no wallet authority is granted by viewing pages |

## Threats and current controls

### Unsupported verdicts and denominator stripping

Threat: an observation is presented as `safe`, `trusted`, `best`, ranked, or statistically
meaningful without its population.

Controls: response models ban verdict field names; service metrics bind numerator and
denominator; coverage includes snapshot, sampled/expected, completeness, population, and
filter; the UI renders the supplied display string rather than recomputing shares.

Residual risk: prose outside the enforced API models can still overclaim. The public claims
table must be reviewed sentence by sentence.

### SSRF, redirects, and endpoint confusion

Threat: an agent URI reaches loopback, private infrastructure, link-local metadata, or a
public host that redirects into a private range.

Controls: `netguard` resolves and rejects non-public addresses; liveness requests disable
redirects; blocked and unresolved targets are observations rather than failures attributed
to an agent.

Residual risk: DNS answers can change after validation, and external HTTP content remains
untrusted. The current code's resolver/request boundary is not claimed to eliminate every
DNS rebinding race.

### Partial snapshots presented as complete

Threat: a capped, crashed, or non-advancing ingestion becomes the served snapshot.

Controls: snapshots record expected, sampled, population, finish time, and stop reason;
only positive, count-equal, exhausted snapshots are promoted, with a compatibility rule for
older rows.

Residual risk: a complete filtered query is complete only for that filter, not the chain.

### Payment replay, double settlement, and output substitution

Threat: one authorization funds different work, the same nonce settles twice, a result is
changed after verification, or an ambiguous facilitator failure is retried.

Controls: x402 validation binds resource, offer, asset, recipient, chain, validity window,
nonce, and signature; SQLite atomically reserves a nonce and binds service/input; output is
hashed before the state moves one way into `settling`; a settlement call is attempted once;
unknown outcomes are terminal pending reconciliation rather than automatically retried.

Residual risk: a successful facilitator response is not independent chain-finality proof.
There is no committed live settlement record. The whole path remains disabled and no stock
is admitted.

### Empty or failed work charged as a result

Threat: an upstream failure, empty response, or malformed human result settles anyway.

Controls: the paid branch records `failed_no_charge` before settlement on service error,
empty result, or absent human-readable decision. Current services do not reach the paid
branch because every admission is false.

Residual risk: the controls have fixture coverage, not live facilitator evidence.

### Action authority expansion

Threat: a preview or compromised planner widens a token/call allowlist, exceeds a cap, acts
after expiry/revocation, or submits calldata different from the simulated intent.

Controls: intent hashes bind calldata; policies carry explicit caps, floors, deadlines, and
selectors; authority validation is separate from planning; session state enforces expiry,
remaining cap, and revocation; the Grid public hire has no signer/submitter; Health has no
armed counterpart.

Residual risk: the action kernel's unit tests are not a live transaction history. No
benefit, fill quality, or trading record follows from a valid intent.

### Evidence mutation and preregistration forgery

Threat: input/spec/run bytes are changed, or local history is rewritten to make a protocol
appear older than its results.

Controls: v1 receipts bind input/output; v2 runs cite spec and dataset hashes; v3 separates
stage-one protocol and later input hashes and refuses a run when the input bytes do not
match.

Residual risk: local Git cannot attest its own wall clock. The current v3 commits are not
reachable from configured remote refs, and a backdated rewrite was reproduced in a clone.
An external timestamp or immutable commitment is required before calling it externally
preregistered.

### Package omission and source-tree false confidence

Threat: editable tests import a package from the checkout that is absent from the wheel.

Controls: `tests/test_packaging.py` compares importable packages on disk with the explicit
setuptools list and names all four category packages; CI builds a wheel, installs it outside
the checkout, asserts the import path, imports the four category packages, and POSTs the
four routes.

Residual risk: package declaration is manual, the dependency set has no lockfile, and
data-only directories trigger setuptools ambiguity warnings even though current package
data globs include them.

### Secrets and operational authority

Threat: credentials enter source/history, logs, documentation, or model prompts; a public
runbook accidentally enables a stateful path.

Controls: secret-like files are ignored; settlement requires explicit external environment
configuration; the public docs contain no credential values; publication, deployment,
transactions, spending, and submission are owner-only.

Residual risk: the completed review used targeted patterns because no dedicated entropy
scanner was installed. Ignored runtime data and external secret stores were deliberately
not inspected.

## Security reporting

No public security contact or response SLA is tracked in this repository. Until the owner
adds one, security reports must use the repository owner's existing private contact
channel; this document does not invent an address or response time.
