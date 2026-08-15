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
   all four category hire routes.
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
and validates result/receipt service IDs. Live RPC/explorer behavior belongs in separate
read-only canaries; it must not make package CI nondeterministic.

## Start the service

Use a dedicated runtime working directory. The relative `data/agents.sqlite3` path will be
created there.

```bash
cd /opt/docket/runtime
/opt/docket/venv/bin/python -m uvicorn --factory docket.api:create_app \
  --host 127.0.0.1 --port 8000
```

The package defines no console script. `docket.api:create_app` is the verified application
factory.

A process manager should set the working directory explicitly, run as a non-root service
account, restart on failure, and preserve the runtime database across wheel replacement.
No systemd unit or nginx virtual host is tracked in this repository, so no exact deployed
unit, proxy path, hostname, TLS configuration, or process environment can be claimed from
source today.

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

## Read-only canaries

After a release candidate starts, check:

```bash
curl -fsS http://127.0.0.1:8000/health
curl -fsS http://127.0.0.1:8000/categories
curl -fsS http://127.0.0.1:8000/hire
curl -fsS http://127.0.0.1:8000/advantage/v2.json
```

Expected shape, not expected changing numbers:

- `/health` returns `status` and `snapshot_id`.
- `/categories` has four rows and declares that category labels are Docket's.
- `/hire` exposes `paid_stock`, `stock_status`, and the four admission booleans per service.
- `/advantage/v2.json` builds from the artifacts included in the wheel.

Do not use a payment header as a canary while stock is unadmitted. Do not run a v3 arm or
lock a v3 input as a deployment check.

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
