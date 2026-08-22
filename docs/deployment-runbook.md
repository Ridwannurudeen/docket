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

## Stage and replace the copied release

The VPS deployment is a copied release under `/opt/docket`, not a Git checkout. Build and
audit the wheel before transfer, then stage the exact release in a separate directory such
as `/opt/docket.stage-<release-id>`. The staged tree must contain its `.venv`, the deployment
assets under `deploy/`, and the exact wheel/source identity recorded at the release gate.

Before changing the service, resolve all three paths and confirm that the stage and backup
are distinct children of `/opt`; never compute either from an empty variable. If the canary
timer is installed, stop the timer and confirm `docket-canary.service` is inactive so a run
cannot cross the replacement. Then stop `docket.service`, move the current `/opt/docket` to
a new timestamped `/opt/docket.bak-<UTC timestamp>`, and only then move the verified stage to
`/opt/docket`.
Do not delete the backup during the release. This is back-up-then-replace; neither the
canary installer nor the application service performs an in-place Git operation or copies
application code.

The live application service uses:

```bash
User=docket
WorkingDirectory=/var/lib/docket
Environment=DOCKET_DB=/var/lib/docket/data/agents.sqlite3
ExecStart=/opt/docket/.venv/bin/uvicorn --factory docket.api:create_app \
  --host 127.0.0.1 --port 8090
```

The package defines no console script. `docket.api:create_app` is the verified application
factory. The working directory makes its relative default database path resolve to the same
live file named by `DOCKET_DB`; the database stays under `/var/lib/docket` across replacement
of `/opt/docket`.

The application unit and nginx site remain host-managed. This repository tracks only the
daily canary units and their installer; their presence in source is not evidence that they
were installed.

## Configuration

With no settlement environment variables, all current services remain free and
unmetered because none is paid stock.

The x402 path is owner-gated by all three of:

- `DOCKET_ENABLE_SETTLEMENT=1`
- `DOCKET_FACILITATOR_URL`
- `DOCKET_PAY_TO`

Do not enable these until a service passes all four admission limbs and the chosen
facilitator/$U flow has a real preflight. Configuration alone does not change
`paid_stock`; the service admission must also pass.

The ERC-8183 broadcaster is separate and refuses to start without `DOCKET_SETTLE_KEY`.
This repository contains no key and this runbook does not direct an operator to create or
fund a job.

## Manual release checks

After a release candidate starts, check:

```bash
curl -fsS http://127.0.0.1:8090/health
curl -fsS http://127.0.0.1:8090/categories
curl -fsS http://127.0.0.1:8090/hire
curl -fsS http://127.0.0.1:8090/advantage/v2.json
curl -fsS http://127.0.0.1:8090/advantage/v3.json
curl -fsS http://127.0.0.1:8090/canary
```

Expected shape, not expected changing numbers:

- `/health` returns `status`, `snapshot_id`, the served snapshot's capture time, and its age.
- `/categories` has four rows and declares that category labels are Docket's.
- `/hire` exposes `paid_stock`, `stock_status`, and the four admission booleans per service.
- `/advantage/v2.json` builds from the artifacts included in the wheel.
- `/advantage/v3.json` has three registered families, all `registered_waiting_for_inputs`
  until an input is separately locked.
- `/canary` exposes the latest durable result and bounded history rather than inferring uptime.

Do not use a payment header in these manual checks. Only the governing runner may exercise
an unadmitted paid leg, and only with the separate owner-installed canary token and payment
configuration. Do not run a v3 arm or lock a v3 input as a deployment check.

## Daily governing canary

The tracked deployment units are:

- `deploy/systemd/docket-canary.service`
- `deploy/systemd/docket-canary.timer`
- `deploy/docket-canary.conf.example`
- `deploy/install-canary.sh`

The timer runs once daily at 04:17 UTC with up to 30 minutes of randomized delay and catches
one missed run after downtime. A oneshot cannot overlap another activation of the same unit,
does not retry, yields CPU and IO priority, and is killed after eight minutes. The runner's
exclusive end is `2026-09-24T00:00:00Z`, so Sep 23 remains inside the monitored window.

This duty cycle comes from the governing win specification. Before owner configuration, a
run is only a few sequential public HTTP reads. After the owner supplies a funded controlled
LP and the payment key file, it adds at most one free controlled-position preflight plus one
exact 0.50 $U paid execution and its rejected replay per day. The preflight proves the
decision-grade result before anything is spent; the replay is refused before work repeats.
From Aug 15 through Sep 23 inclusive that is at most 40 runs and 20 $U. It replaces the
explicitly cut six-hour registry refresh daemon, which would add load without protecting the
primary paid-service claim.

The runner appends what it checked, what it observed, its evidence, and its state to
`DOCKET_DB`. `not_yet_exercised` is not a pass: while the controlled wallet, position token,
economics, or private-key file are absent, the LP and paid legs remain in that state and the
paid admission gate remains closed. A failed or stale governing run removes paid admission;
the free verified example and free preview remain available.

The non-secret config is installed at `/etc/docket/docket-canary.conf`. The installer creates
a 32-byte shared token at `/etc/docket/docket-canary.token` without printing it and adds a
`docket.service` drop-in that points `DOCKET_CANARY_TOKEN_FILE` at that path. It does not
create `/etc/docket/docket-canary-payment.key`, fund an LP, or populate any controlled-LP
value. Those are owner actions. The owner-supplied key file must be readable by `docket`
without being public (for example, `root:docket` mode `0640`). Never put a private key value
in the config or a unit.

The installer assumes application code has already been staged and replaced separately. It
backs up every existing unit/config/token target under a UTC-named directory in
`/var/backups/docket-canary`, preserves existing operator config and token contents, installs
the unit files, reloads systemd, and enables the timer. It deliberately starts nothing and
does not restart `docket.service`; it prints the explicit restart/start commands for the
operator to run after review. Run it only after the copied release is in place:

```bash
bash /opt/docket/deploy/install-canary.sh
```

## Database handling

The runtime database contains observation snapshots and payment lifecycle state. Before a
release, copy it using a SQLite-consistent backup method and record the backup time. Do not
replace it with the repository's ignored `data/` path.

The store applies additive schema migrations at startup. A rollback must retain the same
database only if the previous source understands its schema; otherwise restore the backup
to a separate runtime path and investigate before serving it.

## Rollback

Retain the previous wheel, previous process definition, database backup, and static-asset
hashes. On failed canaries:

1. Stop the new process.
2. Restore the previous wheel/environment and its verified process definition.
3. Restore the database only when the failure or migration changed it.
4. Re-run the read-only canaries.
5. Record which source commit and wheel digest were restored.

This runbook cannot name a current rollback artifact because no deployed artifact is bound
to this source in the repository.

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
the matching committed file.

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
