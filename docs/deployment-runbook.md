# Deployment and operations runbook

This is a release procedure, not evidence that a deployment occurred. This build did not
push, deploy, change repository visibility, enable settlement, broadcast a transaction, or
write `data/agents.sqlite3`.

## Release gates

Do not designate a release until all of these pass on the exact source tree:

1. `python -m pytest -q`.
2. `node --check docket/api/web/app.js`.
3. The wheel builds without an error.
4. A fresh environment outside the checkout installs that wheel.
5. `tests/smoke_installed.py` confirms its import path is outside the checkout and exercises
   all four category hire routes plus the v3 JSON, HTML, and agent-facing documents.
6. The secret/history review reports file paths and secret kinds only, never values.
7. The source commit and wheel SHA-256 are recorded before any deploy claim is made.

Repository publication, deployment, settlement enablement, spending, and submission are
owner-only actions.

## Build a wheel

The verified build frontend for this build is `build==1.5.0`; the backend requires
`setuptools>=77` because the project uses SPDX and license-file metadata.

```bash
python -m pip install build==1.5.0
python -m build --wheel --outdir /path/outside/checkout/dist
```

Keep the output outside the checkout. Record the wheel filename and SHA-256. A rebuild may
have a different archive digest, so the recorded digest identifies one artifact, not every
wheel produced from the source.

## Clean installation

```bash
python -m venv /path/outside/checkout/docket-venv
/path/outside/checkout/docket-venv/bin/python -m pip install \
  /path/outside/checkout/dist/docket-0.1.0-py3-none-any.whl
cd /path/outside/checkout
GITHUB_WORKSPACE=/absolute/path/to/checkout \
  ./docket-venv/bin/python -I \
  /absolute/path/to/checkout/tests/smoke_installed.py
```

On Windows, use `Scripts\python.exe` instead of `bin/python` and set
`$env:GITHUB_WORKSPACE` before running the smoke.

The smoke replaces only the four external network runners in the installed process. It
still imports each category package, creates the installed FastAPI app, routes four POSTs,
and validates result/receipt service IDs. Live RPC, explorer, and owner-gated settlement
behavior belongs in the separate operational canary; it must not make package CI
nondeterministic.

## Ship and release the copied deployment

The VPS release is a copied tree under `/opt/docket`, not a Git checkout. Build the wheel
outside the checkout, then run the following from Git Bash at the exact tested commit. Every
release identifier and digest below is computed; none is typed. The tar stream carries the
wheel plus the complete `deploy/` directory, including all ten unit files.

```bash
repo_root=$(pwd -P)
source_commit=$(git rev-parse HEAD)
wheel=$(realpath /path/outside/checkout/dist/docket-0.1.0-py3-none-any.whl)
wheel_name=$(basename "$wheel")
wheel_sha=$(sha256sum "$wheel" | awk '{print $1}')
remote_bundle="/var/tmp/docket-release-${source_commit:0:12}"

ssh root@gudman.xyz "install -d -o root -g root -m 0700 '$remote_bundle'"
tar -cf - -C "$repo_root" deploy -C "$(dirname "$wheel")" "$wheel_name" | \
  ssh root@gudman.xyz "tar -xf - -C '$remote_bundle'"
ssh root@gudman.xyz \
  "bash '$remote_bundle/deploy/preflight.sh' 22"
```

`preflight.sh` requires `nginx -t` to exit successfully, print `test is successful`, and
emit exactly the operator-supplied number of lines containing the fixed `[warn]` token, whether
nginx uses timestamped error-log or `nginx: [warn]` form. It also requires at least 2 GiB free
under `/opt`, verifies all ten tracked units with `systemd-analyze verify`, and prints the
current journal disk use. It never edits or reloads nginx. The tracked rate-limit example is
still an owner-reviewed, separately applied nginx change.

After preflight, make a SQLite-consistent backup without copying the live database into the
shipped tree, then invoke the release with the computed values:

```bash
ssh root@gudman.xyz \
  'stamp=$(date -u +%Y%m%dT%H%M%SZ); install -d -o root -g root -m 0700 /var/backups/docket; /opt/docket/.venv/bin/python -c '\''import sqlite3,sys; source=sqlite3.connect("/var/lib/docket/data/agents.sqlite3"); destination=sqlite3.connect(sys.argv[1]); source.backup(destination); destination.close(); source.close()'\'' "/var/backups/docket/agents-${stamp}.sqlite3"'
ssh root@gudman.xyz \
  "bash '$remote_bundle/deploy/release.sh' '$remote_bundle/$wheel_name' '$source_commit' '$wheel_sha'"
```

`release.sh` verifies the wheel digest and metadata, installs it into
`/opt/docket-venvs/<commit12>` under `umask 022`, runs `pip check`, and requires the `docket`
service user to import `docket`, `docket.api`, and `docket.canary` before comparing
`pip show docket` with the wheel metadata. The rest of the release retains `umask 027`. A
pre-existing commit-named environment is reused only when its full commit, wheel digest, and
package-version records all match. The script writes the full computed commit to
`RELEASE-commit.txt`, stages the deploy assets, stops the canary timer, proves no canary
service is active, and then performs the back-up-then-replace swap. The old release is
retained as `/opt/docket.bak-<UTC timestamp>`; it is never deleted by the release.

The `.venv` link is flipped with a temporary symlink and `mv -T`. Unit files are installed
only when their bytes differ, with a unified diff printed before each replacement. The old
Aug-21 capture timer is retired and the Aug-26 pre-arm timer replaces it. The release reloads
systemd, enables and starts the host-managed `docket.service`, and enables these five timers:

- `docket-canary.timer`
- `docket-lp-record.timer`
- `docket-refresh.timer`
- `docket-v3-capture.timer`
- `docket-v3-range-capture.timer`

The live application service remains host-managed and uses `User=docket`,
`WorkingDirectory=/var/lib/docket`, `DOCKET_DB=/var/lib/docket/data/agents.sqlite3`, and
`/opt/docket/.venv/bin/uvicorn --factory docket.api:create_app --host 127.0.0.1 --port 8090`.
The database and LP journal remain under `/var/lib/docket`; neither is copied into `/opt`.

The release polls `/health` for up to 30 seconds because startup normally takes 8-10 seconds.
It then checks the documented `/stats` coverage/refresh fields, the `/services` identity,
stock-status, and four-limb admission fields, and the `/advantage/v3.json` family and summary
shape. A failure after service stop triggers automatic rollback: the failed new tree is retained
as `/opt/docket.failed-<timestamp>-<commit12>`, the backup tree and prior `.venv` target are
restored, changed units and prior timer states are restored, the prior service is started, and
`/health` is checked again. A database backup is not automatically restored; if an additive
migration is incompatible with the prior source, keep the service stopped and investigate
against the saved SQLite backup.

For local regression tests, `--dry-run` requires `DOCKET_RELEASE_ROOT` and maps every managed
path into that fake root. It executes the filesystem state machine there and prints every
host command without running it. The test suite supplies a fake `curl` to exercise rollback.

### V3 experiment-arm ledgers

Experiment arms run on the workstation against the repository tree. The installed package is
read-only and must not be used as a ledger target. A ledger becomes visible in production only
after it is committed to the repository and that commit is redeployed.

## Persistent journal for the judging window

The release installs `deploy/journald-docket.conf` at
`/etc/systemd/journald.conf.d/docket.conf` only when the target is absent. The file sets
`Storage=persistent` and `SystemMaxUse=512M`. The release creates `/var/log/journal` with
`install -d -m 2755 -o root -g systemd-journal`, runs
`systemd-tmpfiles --create --prefix /var/log/journal`, restarts `systemd-journald`, and runs
`journalctl --flush`. It then requires `journalctl --header` to report at least one
`/var/log/journal/` file; otherwise the release exits fatally. On the Ubuntu 24.04 host running
systemd 255, the drop-in was read but did not create `/var/log/journal`, so logging remained
volatile until the directory was created and the journal flushed. That first restart has a
one-time, unavoidable cost: the current volatile journal is lost. Afterward, capture refusals
and service diagnostics survive normal volatile rotation during the judging window. If the
target already exists with different bytes, the release refuses before stopping Docket rather
than overwriting host policy.

## Configuration

With no settlement environment variables, all current services remain free and subject to
the 20-per-hour peer-address allowance because none is paid stock.

The API settlement path is owner-gated by:

- `DOCKET_ENABLE_SETTLEMENT=1`
- `DOCKET_FACILITATOR_KIND=b402`
- `DOCKET_FACILITATOR_URL=https://facilitatorv3.b402.ai/api/v1`
- `DOCKET_PAY_TO`

The canary and verify-only preflight also require the pinned public terms and an RPC:

- `DOCKET_PAYMENT_TOKEN=0x55d398326f99059fF775485246999027B3197955`
- `DOCKET_B402_RELAYER_CONTRACT=0xE1Af7DaEa624bA3B5073f24A6Ea5531434D82d88`
- `DOCKET_BSC_RPC_URL` for the read-only owner preflight

`DOCKET_FACILITATOR_URL` includes `/api/v1`: the facilitator's bare documented `/verify`
path returned 404 on 2026-08-23, while `/api/v1/verify` reached its signature check. The
configured Relayer is the live proxy with code and the `B402`/`1` EIP-712 domain; the older
published `0xE91b...5171` address is its owner/submitting EOA and has no code. Do not sign
against or approve that EOA.

Before any settlement attempt, load the same environment as the canary and run:

```bash
set -a
. /etc/docket/docket-canary.conf
set +a
/opt/docket/.venv/bin/python -m docket.hire.x402 preflight
```

The command performs read-only chain calls and one facilitator `/verify`; it never calls
`/settle` or broadcasts a transaction. Require `ready: true`, an empty `missing` list, and
`settlement_attempted: false`. A `balance` or `allowance` entry is a funding boundary, not
permission to submit a transaction. Configuration alone does not change `paid_stock`; the
service admission must also pass.

### Canary payer prepared on 2026-08-24

The canary payer is `0x4821b5445f1cE8328806f83bAfBdBE7D668E6fd3`. Its key exists only at
`/etc/docket/docket-canary-payment.key`, owned by `root:docket` at mode `0640`. The canary
configuration names that path and the decided payment recipient:

```text
DOCKET_PAY_TO=0xe55816904796341bf8535e25f6c8b647927fc946
DOCKET_CANARY_PRIVATE_KEY_FILE=/etc/docket/docket-canary-payment.key
```

Never print, copy, or pass the key as an argument. The recipient is not the payer: fund only
the payer address above. The RelayerV3 proxy is the spender, not a funding destination.

Use a bounded `15.0 USDT` allowance (`15000000000000000000` atomic), not an unlimited
approval. This covers 30 scheduled daily hires from 2026-08-25 through 2026-09-23 inclusive
at `0.50 USDT` each. At BSC block `117845533` (`2026-08-24T17:10:18Z`), the actual payer's
pending nonce was 0, `eth_gasPrice` was 50,000,000 wei (0.05 gwei), and
`eth_estimateGas` returned 46,576 gas. The resulting unsigned transaction was:

```json
{
  "from": "0x4821b5445f1cE8328806f83bAfBdBE7D668E6fd3",
  "nonce": 0,
  "chainId": 56,
  "gas": 46576,
  "gasPrice": 50000000,
  "value": 0,
  "to": "0x55d398326f99059fF775485246999027B3197955",
  "data": "0x095ea7b3000000000000000000000000e1af7daea624ba3b5073f24a6ea5531434d82d88000000000000000000000000000000000000000000000000d02ab486cedc0000"
}
```

The approval costs `46576 * 50000000 = 2328800000000` wei, or `0.0000023288 BNB`, at that
observation. Successful settlement transaction
`0xa092c8b48d5a34604d75db8a4f20127dbfb2b97c07b557854402e45cb9f63729`
used 94,876 gas and was sent by the facilitator's EOA, not by the payer. For a conservative
comparison, one approval plus 30 settlements is 2,892,856 gas, or `0.0001446428 BNB` at the
observed gas price; the facilitator bears the settlement gas. Fund the payer with exactly
`0.001 BNB` as the operational floor, leaving more than six times that whole-chain comparison
for a higher gas price, a replacement, or a second bounded approval.

The full-window funding instruction is therefore exactly `15.0 USDT` plus `0.001 BNB` on
BSC to `0x4821b5445f1cE8328806f83bAfBdBE7D668E6fd3`. To stage the proof first, `2.0 USDT`
plus the same `0.001 BNB` covers four exact hires; it does not fund the 30-run window. After
funding, refresh the nonce, gas price, and estimate if the payer has sent any transaction,
then sign and broadcast one bounded approval with owner tooling. Docket has no signing or
broadcast command. Run the preflight block above afterward; that is the one command that
confirms setup, and it must return `ready: true` before any settlement attempt.

The deployed signer must serialize its 65-byte EIP-712 signature with the `0x` prefix expected
by the facilitator. A prefix-less build returns `signature_error` before the facilitator reads
balance or allowance. Do not fund on the strength of a preflight that still reports that error.

Before paid stock opens, the owner may merge the tracked nginx `limit_req` example into the
live `http` and `/hire/` contexts. Run `deploy/preflight.sh 22` afterward and reload nginx only
when `nginx -t` still reports `test is successful` with exactly the same 22-warning baseline.
The release scripts never edit or reload nginx. Paid authorizations bypass the application
free allowance so shared-egress free usage cannot make payment impossible; nginx's
peer-address `30r/m` limit is the separate paid-path bound.

The ERC-8183 broadcaster is separate and refuses to start without `DOCKET_SETTLE_KEY`.
This repository contains no key and this runbook does not direct an operator to create or
fund a job.

## Post-release evidence collection

The release checks response shape. Collect the deployed identity and exact response evidence
separately after it returns success:

```bash
ssh root@gudman.xyz \
  'readlink -f /opt/docket/.venv; cat /opt/docket/RELEASE-commit.txt /opt/docket/WHEEL-sha256.txt; /opt/docket/.venv/bin/python -c '\''import importlib.metadata as metadata; print(metadata.version("docket"))'\''; /opt/docket/.venv/bin/python -m pip check'
ssh root@gudman.xyz \
  'curl -fsS http://127.0.0.1:8090/services | sha256sum; curl -fsS http://127.0.0.1:8090/stats; systemctl list-timers docket-canary.timer docket-lp-record.timer docket-refresh.timer docket-v3-capture.timer docket-v3-range-capture.timer'
```

Expected shape, not expected changing numbers:

- `/health` returns `status`, `snapshot_id`, the served snapshot's capture time, and its age.
- `/stats` returns `coverage` with its snapshot, time, age, sampled/expected/dropped counts,
  completeness, and population, plus `refresh_status`, `registry_total`, and `probe_method`.
- `/services` returns `services`, `total`, `category`, `ordering`, and `declaration`; every
  service carries `service_id`, `paid_stock`, `stock_status`, and all four admission booleans.
- `/categories` has four rows and declares that category labels are Docket's.
- `/advantage/v2.json` builds from the artifacts included in the wheel.
- `/advantage/v3.json` has three registered families and reports their current artifact state.
- `/canary` exposes the latest durable result and bounded history rather than inferring uptime.

Do not use a payment header in these manual checks. Only the governing runner may exercise
an unadmitted paid leg, and only with the separate owner-installed canary token and payment
configuration. Do not run a v3 arm or lock a v3 input as a deployment check.

## Reconcile a lost paid-hire response

If settlement may have completed but the caller lost the HTTP response, do not submit the hire
again and do not call the facilitator directly. While the original signed authorization remains
inside its validity window, send `POST /hire/{service_id}/recover` with the exact original JSON
request body and the same signed authorization header used for the hire (`X-PAYMENT` or
`PAYMENT-SIGNATURE`). The recovery route checks the signature, terms, resource, service, input,
and nonce against the local payment row. It does not run the service or call facilitator
`/verify` or `/settle`.

A `200` response is the stored standard `{result, receipt}` envelope and is available only for
`settled` and `settlement_unknown` rows. Record that envelope beside the caller's original
request. Handle failures by their error code: `payment_not_found` (`404`) means this database has
no row for the nonce; `payment_invalid` (`400`) means the signed header is absent, malformed, or
outside its validity window; `authorization_mismatch` (`409`) means the service, input, or signed
terms do not bind to the stored payment; and `payment_not_recoverable` (`409`) means the row has
not reached either recoverable state. None of those responses authorizes another settlement
attempt. Confirm the request reached the release using the intended `DOCKET_DB`, then investigate
the durable row before any owner-approved next action.

After the signed window closes, use the operator path on the same route. Send
`Authorization: Bearer` from `DOCKET_CANARY_TOKEN_FILE` without printing or logging the token,
and send `{"nonce":"<the stored authorization nonce>"}` as the JSON body. A successful call
returns the same stored envelope and writes `operator_recovered_at` on the payment row. It does
not recheck the expired signature, change payment status, or call the service or facilitator.
A wrong or unavailable token returns `401 operator_unauthorized`. Both buyer and operator
recovery share a 10-attempt-per-minute peer-address bound and return
`429 recovery_rate_limited` with `Retry-After` when it is exhausted.

## Daily governing canary

The tracked deployment units are:

- `deploy/systemd/docket-canary.service`
- `deploy/systemd/docket-canary.timer`
- `deploy/docket-canary.conf.example`

The timer runs once daily at 04:17 UTC with up to 30 minutes of randomized delay and catches
one missed run after downtime. A oneshot cannot overlap another activation of the same unit,
does not retry, yields CPU and IO priority, and is killed after eight minutes. The runner's
exclusive end is `2026-09-24T00:00:00Z`, so Sep 23 remains inside the monitored window.

This duty cycle comes from the governing win specification. Before owner configuration, a
run is only a few sequential public HTTP reads. After the owner supplies a funded controlled
LP and the payment key file, it adds at most one free controlled-position preflight plus one
exact 0.50 USDT paid execution and its rejected replay per day. The preflight proves the
decision-grade result before anything is spent; the replay is refused before work repeats.
For the payer prepared on Aug 24, the first possible daily run is Aug 25, so the inclusive
Aug 25-Sep 23 window is 30 runs and 15.0 USDT.

The canary and registry refresh have different scopes. The canary protects the primary paid
service and controlled-position claims. The refresh keeps the small, feedback-filtered ERC-8004
fact plane and explicit Docket identities current. It does not reinstate the cut full-registry
crawl or registry-history build.

The runner appends what it checked, what it observed, its evidence, and its state to
`DOCKET_DB`. `not_yet_exercised` is not a pass: while the controlled wallet, position token,
economics, or private-key file are absent, the LP and paid legs remain in that state and the
paid admission gate remains closed. A failed or stale governing run removes paid admission;
the free verified example and free preview remain available.

The release requires the existing non-secret config at `/etc/docket/docket-canary.conf` and
the existing shared token at `/etc/docket/docket-canary.token`, both `root:docket` mode
`0640`; it never prints, replaces, or copies either one. `deploy/install-canary.sh` remains
the one-time bootstrap for a new host, not a release step. Neither script creates
`/etc/docket/docket-canary-payment.key`, funds an LP, or populates controlled-LP values. Those
are owner actions. The owner-supplied key file must be readable by `docket` without being
public (for example, `root:docket` mode `0640`). Never put a private key value in the config
or a unit.

The prepared payer, bounded approval, measured gas, and funding instruction are recorded in
the Configuration section. Funding and approval do not set `true_settlement` and do not put
any service into paid stock. Those facts remain false until a real settlement has completed,
the transaction has been checked, the paid result is nonempty, the identical authorization
is refused as a replay, and the remaining admission limbs pass.

## Six-hour targeted registry refresh

The tracked refresh units are:

- `deploy/systemd/docket-refresh.service`
- `deploy/systemd/docket-refresh.timer`

The timer starts at 01:41, 07:41, 13:41, and 19:41 UTC and catches one missed activation after
downtime. Each run sweeps the complete `min_feedbacks>=1` query and unions the public agent ids
listed in `DOCKET_OWNED_AGENT_IDS`, fetching those identities individually even when they have
zero feedback. The stored population names both parts of that union. A malformed, missing, or
mismatched configured identity fails the run rather than publishing a snapshot that silently
omits it.

Ingestion finishes an unpromoted candidate. The job then enriches every callable row, records one
policy-guarded observation for every a2a/mcp endpoint, rechecks that the sweep exhausted with
`sampled == expected > 0`, and promotes the snapshot. A page-bounded or non-advancing sweep is
never promoted. The application resolves the latest promoted snapshot on each fact-plane request,
so a successful refresh becomes visible without a process restart; a failed refresh leaves the
previous promoted snapshot in service.

`release.sh` installs these two unit files with the other tracked units, reloads systemd, and
enables the refresh timer only after the exact tested wheel is under `/opt/docket` and the
SQLite-consistent backup has been made. Inspect the first completed run with
`systemctl status docket-refresh.service` plus `journalctl -u docket-refresh.service` before
treating freshness as operational.

Every refresh that enters the pipeline writes `/var/lib/docket/data/last-refresh.json` atomically
with `status`
(`ok`, `refused`, or `error`) and a UTC `timestamp`; `/stats.refresh_status` reads the same file
on every request. Check both after every installation or allowlist change. `Restart=no` means a
failed oneshot has no automatic retry, and this unit has no automatic alert, so the operator's
monitoring must inspect `systemctl status docket-refresh.service`,
`journalctl -u docket-refresh.service`, and the status file. A refusal or error keeps the prior
promoted snapshot online.

Until Docket's new ERC-8004 registrations exist, leave `/etc/docket/docket-refresh.conf` absent;
the targeted feedback sweep still runs. Once the identities exist, create that root-managed file
with one line, `DOCKET_OWNED_AGENT_IDS=` followed by the comma-separated full ids in
`{chain_id}:{registry_address}:{token_id}` form. Agent ids are public, but the file must contain no
wallet key, facilitator credential, or payment authorization. Restarting the API is not required
after updating the allowlist; start `docket-refresh.service` once and confirm the promoted
snapshot contains every configured id.

## Database handling

The runtime database contains observation snapshots and payment lifecycle state. Before a
release, copy it using a SQLite-consistent backup method and record the backup time. Do not
replace it with the repository's ignored `data/` path.

The store applies additive schema migrations at startup. A rollback must retain the same
database only if the previous source understands its schema; otherwise restore the backup
to a separate runtime path and investigate before serving it.

## Rollback after a later operational failure

The release performs its own rollback for any failure after service stop. For a failure found
later by a canary, retain the timestamped release backup, failed/new tree, unit backup, SQLite
backup, and both wheel records. Stop the new process, restore the retained release and its
commit-named environment, restore the prior unit contents, reload systemd, and re-run the
read-only health and response-shape checks. Restore the database only to a separate runtime
path when a migration prevents the prior source from reading the live schema; do not overwrite
the live database while diagnosing it. Record the source commit and wheel digest restored.

Rollback deliberately restores the prior unit contents and their enabled and active states.
If it follows retirement of the Aug-21 capture timer, `systemctl list-timers` can therefore
show that elapsed timer again. This is expected: the restored one-shot used
`Persistent=false`, so it will not catch up after its registered moment.

## Register the four identities

This is an owner transaction procedure. `docket.identity.register` only reads BSC state and
prints an unsigned transaction. It accepts no key and has no submission command.

At BSC block `117439816` (`2026-08-22T14:26:28Z`), `eth_gasPrice` returned `50000000`
wei (0.05 gwei). The range-doctor plan estimated 163,316 gas, or 0.0000081658 BNB at
that observation; four transactions at the same estimate and gas price would cost
0.0000326632 BNB. Fund the registration wallet for four fresh estimates plus the
owner's chosen margin, because each plan re-reads both values.

The planned token URIs are:

- `https://docket.gudman.xyz/registrations/range-doctor.json`
- `https://docket.gudman.xyz/registrations/grid-operator.json`
- `https://docket.gudman.xyz/registrations/yield-router.json`
- `https://docket.gudman.xyz/registrations/health-guard.json`

The integrator must serve those paths from the matching generated files under
`docket/api/static/agents/`. The existing `/agents/{agent_id}` route must not serve them.
Each pre-mint document has an empty `registrations` array, points its discovery endpoint at
the GET-capable `/services/{service_id}` route, and keeps the POST hire URL in `hireUrl`.

Do not mint while a URI is missing or stale. Before each transaction, the owner must confirm
that an unauthenticated GET returns HTTP 200 and that its body is byte-for-byte identical to
the matching committed file. The `plan` command performs that check before it reads BSC state
or prints an unsigned transaction; a non-200 response or a different SHA-256 is a refusal.

Process the services one at a time. A plan includes the wallet's pending nonce, so do not
create all four plans first: wait for each transaction receipt before planning the next.

```powershell
$registrationWallet = Read-Host "Registration wallet address"
./.venv/Scripts/python.exe -m docket.identity.register plan `
  --service range-doctor --from $registrationWallet
```

For each plan:

1. Check that `chainId` is 56, `to` is
   `0x8004A169FB4a3325136EB29fA0ceB6D2e539a432`, and `data` begins with
   `0xf2c298be`.
2. Pass only `unsigned_transaction` to the owner's signing tooling. Do not pass a key to
   Docket.
3. Broadcast once with the owner's tooling and wait for a successful receipt.
4. Save the receipt JSON and decode the minted ID:

```powershell
./.venv/Scripts/python.exe -c "import json,sys; from docket.identity.register import decode_registration; print(json.dumps(decode_registration(json.load(open(sys.argv[1]))), indent=2))" range-doctor.receipt.json
```

Repeat the plan, owner-sign, broadcast, receipt, and decode sequence for `grid-operator`,
`yield-router`, and `health-guard`, changing the service and receipt filename each time.

After each mint, regenerate that service's document with the minted integer ID and an
explicit UTC update time. The generator receives the time through its `clock` argument; it
does not read the current time, so the resulting bytes are reproducible.

```powershell
$serviceId = "range-doctor"
$agentId = "136384"
$updatedAt = "2026-08-22T14:57:44Z"
./.venv/Scripts/python.exe -c 'import sys; from datetime import datetime; from pathlib import Path; from docket.hire.catalogue import SERVICES; from docket.identity.register import render_registration_document; service = SERVICES[sys.argv[1]]; clock = lambda: datetime.fromisoformat(sys.argv[3].replace("Z", "+00:00")); Path("docket/api/static/agents", f"{service.id}.registration.json").write_bytes(render_registration_document(service, clock=clock, agent_id=int(sys.argv[2])))' $serviceId $agentId $updatedAt
```

Use the actual decoded ID and the chosen explicit UTC regeneration time. Redeploy the changed
file at the same URI, confirm HTTP 200 and exact-byte equality again, then request an
8004scan re-parse. The token URI does not change, so no `setAgentURI` call is needed.

Hand the four service-to-agent-ID pairs and receipts to the integrator. The integrator then
sets each `agent_id` in `docket/marketplace/registry.py`, adds the four IDs to
`DOCKET_OWNED_AGENT_IDS` for the refresh sweep, exposes the four token-URI paths above, runs
the targeted sweep, and restarts the application. Those integration changes happen only
after the owner transactions and are outside this registration workstream.
