# Deployment and operations runbook

This is a release procedure, not evidence that any particular source revision was deployed.
Use the source/deploy manifest and dated operational evidence for deployment and settlement
claims; do not infer them from the presence of a command in this runbook.

## Release gates

Do not designate a release until all of these pass on the exact source tree:

1. `python -m pytest -q`.
2. `node --check docket/api/web/app.js`.
3. `uv==0.11.16` reproduces the committed hashed runtime lock without a diff.
4. The clean-HEAD release builder produces and verifies the wheel and manifest.
5. A fresh environment outside the checkout installs the hashed runtime lock, then that
   wheel without resolving any additional dependencies, and passes `pip check`.
6. `tests/smoke_installed.py` confirms its import path is outside the checkout and exercises
   all four category hire routes plus the v3 JSON, HTML, and agent-facing documents.
7. The secret/history review reports file paths and secret kinds only, never values.
8. The generated manifest records the source commit and every shipped digest before any
   deploy claim is made.

Repository publication, deployment, settlement enablement, spending, and submission are
owner-only actions.

## Build an integrity-bound release bundle

The reviewed builder lock pins `build==1.5.0`, `setuptools==83.0.0`, all builder
transitive dependencies, and the `uv==0.11.16` dependency-lock exporter to exact wheel hashes.

```bash
python -m pip install --require-hashes --only-binary=:all: -r deploy/build-requirements.txt
uv export --quiet --frozen --no-dev --no-emit-project --format requirements.txt \
  --output-file deploy/runtime-requirements.txt
git diff --exit-code -- deploy/runtime-requirements.txt
python deploy/release_bundle.py build /path/outside/checkout/docket-release
```

The builder refuses any tracked or untracked working-tree change, derives the full Git HEAD,
and uses `git archive` so the build reads only that committed tree. It creates a temporary
builder virtual environment, installs the committed builder lock with `--require-hashes` and
`--only-binary=:all:`, and builds without build isolation using only that environment. It adds
`docket-provenance.json` to the wheel's dist-info directory and rewrites `RECORD` with the
embedded commit member's correct SHA-256 and size. It then emits
`release-manifest.json`, binding the source commit, final wheel filename and SHA-256, runtime
lock SHA-256, and every file under `deploy/`. The output directory must not already exist and
must remain outside the checkout.

The manifest and embedded member provide an integrity binding, not artifact authenticity.
They are deliberately unsigned: they detect omission, corruption, mixing, and substitution
within a release bundle, but do not prove who built or approved it. This procedure makes no
signature, identity, or reproducible-byte claim.

## Clean installation

```bash
bundle=/path/outside/checkout/docket-release
python -m venv /path/outside/checkout/docket-venv
/path/outside/checkout/docket-venv/bin/python -m pip install --require-hashes \
  --only-binary=:all: \
  -r "$bundle/deploy/runtime-requirements.txt"
/path/outside/checkout/docket-venv/bin/python -m pip install --no-deps \
  "$bundle"/docket-*.whl
/path/outside/checkout/docket-venv/bin/python -m pip check
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

The VPS release is a copied tree under `/opt/docket`, not a Git checkout. Build the release
bundle outside the checkout, then run the following from Git Bash. The tar stream carries the
generated manifest and wheel plus the complete `deploy/` directory, including the hashed
runtime lock and all twenty-one tracked unit files.

```bash
bundle=$(realpath /path/outside/checkout/docket-release)
source_commit=$(python -c 'import json,sys; print(json.load(open(sys.argv[1], encoding="utf-8"))["source_commit"])' \
  "$bundle/release-manifest.json")
remote_bundle="/var/tmp/docket-release-${source_commit:0:12}"

ssh <deploy-user>@<host> "install -d -o root -g root -m 0700 '$remote_bundle'"
tar -cf - -C "$bundle" . | \
  ssh <deploy-user>@<host> "tar --no-same-owner -xf - -C '$remote_bundle'"
ssh <deploy-user>@<host> \
  "bash '$remote_bundle/deploy/preflight.sh' 22"
```

`preflight.sh` requires `nginx -t` to exit successfully, print `test is successful`, and
emit exactly the operator-supplied number of lines containing the fixed `[warn]` token, whether
nginx uses timestamped error-log or `nginx: [warn]` form. It also requires at least 2 GiB free
under `/opt`, verifies all twenty-one tracked units with `systemd-analyze verify`, and prints the
current journal disk use. It never edits or reloads nginx. The tracked rate-limit example is
still an owner-reviewed, separately applied nginx change.

On an existing host, migrate the signer boundary before the release:

```bash
ssh <deploy-user>@<host> \
  "bash '$remote_bundle/deploy/install-canary.sh' && ! systemctl is-enabled --quiet docket-canary.timer && ! systemctl is-active --quiet docket-canary.timer && ! systemctl is-active --quiet docket-canary.service"
```

The installer shares the release lock, disables the timer before changing identity, ownership,
ACLs, units, or the public web drop-in, and refuses an active canary worker. It leaves the timer
disabled. Existing config, token, key, data, and database targets are prevalidated before file
replacement; an interrupted migration remains quiescent and can be rerun under the same lock.
A successful release preserves that disabled state; enabling it requires separate owner
approval.

`--no-same-owner` is required because extraction runs as root: it makes every copied artifact
root-owned instead of preserving the workstation's numeric owner. The private mode-`0700`
bundle directory prevents another user from replacing verified artifacts.

After preflight, pass only the generated manifest. The release itself quiesces timer-triggered
writers, then makes and verifies the SQLite-consistent backup before it stops the application
service or swaps the live tree:

```bash
ssh <deploy-user>@<host> \
  "bash '$remote_bundle/deploy/release.sh' '$remote_bundle/release-manifest.json'"
```

`release.sh` requires the manifest beside the wheel and the executing `deploy/` directory.
It verifies the exact manifest schema, every declared digest and deploy-file inventory, the
entire wheel `RECORD`, and the embedded wheel commit. A live release also requires the bundle
tree to be root-owned and neither group- nor world-writable; every ancestor must be similarly
protected or a root-owned sticky directory such as `/var/tmp`.

A nonblocking whole-process lock at `/run/docket/release.lock` is acquired before artifact
verification, environment construction, staging, or runtime mutation and remains held through
health validation or rollback. `/run` must be root-owned and non-writable by group or world;
the script creates `/run/docket` as root mode `0700` and accepts an existing lock only at
`root:root` mode `0600`. A concurrent release fails before it can touch artifacts or services.

The script installs the runtime dependencies with
`pip install --require-hashes --only-binary=:all: -r deploy/runtime-requirements.txt`, then
installs the wheel with `pip install --no-deps <wheel>`, then runs `pip check`. These steps
happen in `/opt/docket-venvs/<commit12>.partial` under `umask 022`, before any database or
service mutation. It
requires the `docket` service user to import `docket`, `docket.api`, and `docket.canary` before
comparing `pip show docket` with the wheel metadata. The rest of the release retains
`umask 027`. A pre-existing commit-named environment is reused only when its full commit,
wheel digest, package version, and runtime-lock digest records all match and its `pip check`,
imports, and installed version validate. A matching but invalid environment is retained until
a replacement passes those checks. The four identity files receive file fsync, the partial
directory receives directory fsync, the environment is atomically renamed to the final path,
and the parent environment directory receives directory fsync. Failed construction removes
the partial tree; an interrupted partial or quarantined invalid tree is recoverable on rerun.

The exact manifest is reverified immediately before the database/service mutation boundary,
and its second verifier output must equal the first. The script writes the derived commit to
`RELEASE-commit.txt`, retains the manifest and runtime-lock digest, and stages the bound deploy
assets. It then uses the currently deployed Python and SQLite backup API to write
`/var/backups/docket/agents-<UTC timestamp>.sqlite3` through an exclusive temporary file.
It requires `PRAGMA quick_check` to return exactly `ok`, atomically publishes the backup,
and requires mode `0600` with owner `root:root` outside dry-run. Before that backup, the script
captures the enabled and active states of every tracked timer, stops every tracked timer, and
requires every corresponding worker service to be inactive. It never kills an active worker: it aborts
and restores all captured timer states instead. A failed backup likewise restores timer state
while leaving the application service and current release tree untouched. After the verified
backup, the script stops the application service and performs the release-tree swap. A stale
root-owned staging tree from an interrupted pre-swap copy is removed under the process lock,
and a failed copy removes its partial stage. The old release is retained as
`/opt/docket.bak-<UTC timestamp>`; it is never deleted by the release.

The `.venv` link is flipped with a temporary symlink and `mv -T`. Unit files are installed
only when their bytes differ, with a unified diff printed before each replacement. The old
Aug-21 capture timer is retired and the Aug-26 pre-arm timer replaces it. The release reloads
systemd, then enables and starts the tracked `docket.service`. Only after health, inventory,
v3-state, homepage, and static-asset gates all pass does it enable these timers; an intentionally
disabled `docket-canary.timer` remains disabled:

- `docket-canary.timer`
- `docket-lp-record.timer`
- `docket-refresh.timer`
- `docket-v3-capture.timer`
- `docket-v3-range-capture.timer`
- `docket-v3-yield-v6-capture.timer`

The tracked application unit uses `User=docket`, `Group=docket`,
`WorkingDirectory=/var/lib/docket`, `DOCKET_DB=/var/lib/docket/data/agents.sqlite3`, and
`/opt/docket/.venv/bin/python -P -m uvicorn --factory docket.api:create_app --host 127.0.0.1 --port 8090`.
The interpreter-module form is intentional: console-script shebangs record the temporary
`.partial` environment path before that environment is atomically published under its commit;
`-P` also keeps the docket-writable working directory off the module search path.
All six scheduled Python worker units use the same `python -P -m` boundary.
Host-specific archive and canary-token environment files remain separate systemd drop-ins;
they are not folded into the tracked base unit. The database and LP journal remain under
`/var/lib/docket`; neither is copied into `/opt`.

The governing canary instead runs as the dedicated `docket-canary` system user and group,
with named ACLs that grant only directory traversal, the shared recovery token, and the live
SQLite paths it needs. Its account has `/nonexistent` as its home and `/usr/sbin/nologin` as its shell; the
`docket` web user must never belong to the `docket-canary` group. The web unit also makes the
canary config and payment-key paths inaccessible with `InaccessiblePaths`, independently of
their discretionary permissions. The installer grants named `docket` and `docket-canary`
access ACLs on the live database and access/default ACLs on its directory, with no access for
other users, so SQLite rollback journals remain recoverable by both writers without sharing
signer files. Docket supports SQLite `DELETE` journal mode only: the release and every `Store`
initialization reject WAL without changing it, so conversion requires a separate quiesced
operator action that preserves any uncheckpointed WAL state.

Every tracked Python service applies the runtime-tested systemd 255 containment set:
`UMask=0027`, an empty `CapabilityBoundingSet=`, `PrivateDevices=true`,
`ProtectClock=true`, `ProtectHostname=true`, `ProtectKernelLogs=true`,
`ProtectKernelModules=true`, `ProtectKernelTunables=true`,
`ProtectControlGroups=true`, `ProtectProc=invisible`, `ProcSubset=pid`,
`LockPersonality=true`, `MemoryDenyWriteExecute=true`,
`RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6`, `RestrictNamespaces=true`,
`RestrictRealtime=true`, `RestrictSUIDSGID=true`, `RemoveIPC=true`,
`SystemCallArchitectures=native`,
`SystemCallFilter=@system-service`, and `SystemCallErrorNumber=EPERM`. They retain the
existing filesystem and no-new-privileges protections. They do not set `PrivateNetwork` or
`IPAddressDeny`, because Docket requires DNS, outbound TLS, RPC, and facilitator access.
The timer units remain scheduling-only and are unchanged by this containment policy.

The release polls `/health` for up to 30 seconds because startup normally takes 8-10 seconds.
It then checks the documented `/stats` coverage/refresh fields; the exact six service IDs
(`range-doctor`, `grid-operator`, `health-guard`, `yield-router`,
`solvent-signal`, and `warden-scan`); the exact four categories; every service's
stock and four-limb admission fields; and the exact six v3 IDs with their committed current
states. It also requires the browser homepage and tracked stylesheet to serve their authored
markers. A failure after service stop triggers automatic rollback: the failed new tree is retained
as `/opt/docket.failed-<timestamp>-<commit12>`, the backup tree and prior `.venv` target are
restored, changed units and prior timer states are restored, the prior service is started, and
`/health` is checked again. A database backup is not automatically restored; if an additive
migration is incompatible with the prior source, keep the service stopped and investigate
against the saved SQLite backup.

The live-tree transition is a two-directory rename, not an atomic symlink exchange. A power loss
between moving `/opt/docket` to its timestamped backup and moving the staged tree into place can
leave `/opt/docket` absent. After reboot, keep `docket.service` and every tracked timer stopped; inspect
the exact `/opt/docket.bak-<timestamp>` and `/opt/docket.stage-<commit12>` recorded for that
release. If the live path is absent, restore the known prior tree with
`mv -- /opt/docket.bak-<timestamp> /opt/docket`, verify its `.venv` target and release identity,
restore the saved unit files when they had been changed, run `systemctl daemon-reload`, start only
`docket.service`, and require the complete health/inventory/web gates before restoring the captured
timer states. Do not blindly rerun the release or delete either residue before this recovery.

The v3 state gate is intentionally release-specific:

- `v3-01-range-doctor`: `superseded_before_input_lock`
- `v3-02-yield-router`: `abandoned_after_failed_primary`
- `v3-03-warden-security`: `superseded_before_input_lock`
- `v3-04-warden-security`: `complete_unscored`
- `v3-05-range-doctor`: `locked_not_run`
- `v3-06-yield-router-assisted`: `registered_waiting_for_inputs`

Change that gate only with a committed artifact-state transition and its regression test.

For local regression tests, `--dry-run` requires `DOCKET_RELEASE_ROOT` and maps every managed
path into that fake root. It executes the filesystem state machine, including a real backup
of the fake-root SQLite database, verifies the artifact bindings twice, and prints every host
command without running it. The process lock path and host commands are injectable only in this
fake-root mode for deterministic concurrency and failure tests. The live root-ownership check is
omitted because the fake bundle is intentionally owned by the test user. The test suite supplies
a fake `curl` to exercise rollback.

### Session keys and `docket-jobs.service`

`docket-jobs.service` is the only unit that reads `DOCKET_SESSION_KEY_FILE`, and
`docket.service` must never be given it: the web process is deliberately incapable of
minting a session key or sweeping one. See `deploy/docket-sessions.conf.example`.

While the key file is absent, persistent activations are still created and still
readable. They stop at `awaiting_session`, and any that were closing stop at `revoking`.
Both of those states **occupy one of the five open-activation slots an owner is allowed**,
so an owner who tries repeatedly on a deployment with no key file installed will be
refused with `too_many_activations` until the file arrives or they cancel. One-shot
activations are unaffected.

`TimeoutStartSec=infinity`, deliberately. One activation can legitimately hold a pass for
about thirteen minutes (eight sends each waiting up to 90 s for a receipt, plus a 60 s
sweep wait), so a queue of them has no wall-clock bound and any finite value would
eventually SIGTERM a pass inside a batch rather than between two activations. The bound is
in the code: `docket.jobs.tick.PASS_BUDGET_SECONDS` stops the pass starting new
activations after twenty minutes and lets it finish the one in hand, and systemd will not
start a second instance of a oneshot while one is running. A pass that is still going when
the next timer fires is not an error; the queue it did not reach is picked up next time.

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
the 20-per-hour peer-address allowance. At the 2026-09-04 observation, `cold_canary=false`
for all six services, so none is paid stock; settlement configuration cannot change that
admission fact.

The API settlement path is owner-gated by:

- `DOCKET_ENABLE_SETTLEMENT=1`
- `DOCKET_FACILITATOR_KIND=b402`
- `DOCKET_FACILITATOR_URL=https://facilitatorv3.b402.ai/api/v1`
- `DOCKET_PAY_TO`

The canary and non-settling payment preflight also require the pinned public terms and an RPC:

- `DOCKET_PAYMENT_TOKEN=0x55d398326f99059fF775485246999027B3197955`
- `DOCKET_B402_RELAYER_CONTRACT=0xE1Af7DaEa624bA3B5073f24A6Ea5531434D82d88`
- `DOCKET_BSC_RPC_URL` for the owner payment preflight

`DOCKET_FACILITATOR_URL` includes `/api/v1`: the facilitator's bare documented `/verify`
path returned 404 on 2026-08-23, while `/api/v1/verify` reached its signature check. The
configured Relayer is the live proxy with code and the `B402`/`1` EIP-712 domain; the older
published `0xE91b...5171` address is its owner/submitting EOA and has no code. Do not sign
against or approve that EOA.

With separate approval for the additional live authorization, load the same environment as
the canary and optionally run:

```bash
set -a
. /etc/docket/docket-canary.conf
set +a
/opt/docket/.venv/bin/python -P -m docket.hire.x402 preflight
```

The chain calls are read-only, but the facilitator `/verify` receives a live signed
authorization valid for up to 300 seconds. The command never calls `/settle` or broadcasts a
transaction. Require `ready: true`, an empty `missing` list, and
`settlement_attempted: false`. A `balance` or `allowance` entry is a funding boundary, not
permission to submit a transaction. Configuration alone does not change `paid_stock`; the
service admission must also pass.

Treat that signed verification as a separate possible `0.50 USDT` exposure. If approval covers
only one charge, skip the command: perform the balance, allowance, whitelist, pause, bytecode,
and EIP-712 checks with signature-free chain calls, then let the single approved canary
activation exercise `/verify` and `/settle`.

### Canary payer prepared on 2026-08-24

The canary payer is `0x4821b5445f1cE8328806f83bAfBdBE7D668E6fd3`. Its key exists only at
`/etc/docket/docket-canary-payment.key`, owned by `root:docket-canary` at mode `0640`. The canary
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

The 2026-08-24 full-window funding plan was therefore exactly `15.0 USDT` plus `0.001 BNB` on
BSC to `0x4821b5445f1cE8328806f83bAfBdBE7D668E6fd3`. To stage the proof first, `2.0 USDT`
plus the same `0.001 BNB` covers four exact hires; it does not fund the 30-run window. After
funding, refresh the nonce, gas price, and estimate if the payer has sent any transaction,
then sign and broadcast one bounded approval with owner tooling. Docket has no signing or
broadcast command. Confirm balance, allowance, whitelist, pause state, bytecode, and domain
with signature-free chain calls. The optional signed preflight above additionally confirms
facilitator verification, but requires its own approval because it creates another live
authorization. This was a funding plan, not approval to start a recurring schedule.

### Approved canary executed on 2026-08-30

Exactly one owner-approved Range Doctor canary was started. Run 18 settled
`500000000000000000` atomic units, or 0.50 USDT, and the identical signed request was
rejected with `409 authorization_replay`; all eight canary legs passed. The post-canary
source records Range Doctor's `true_settlement` and `decision_grade_presenter` limbs as
true. `fresh_paired_benchmark` is now derived from the newest terminal v3 family or complete
v1 pair for the service inside a 30-day window. At 2026-09-04 12:00 UTC it is true for
Range Doctor and SOLVENT until September 7 and for Warden until September 26, and false
for Grid Operator, Yield Router, and Health Guard. The source released to production on
2026-09-02 as `4a632c0` reports `true_settlement=true` for Range Doctor. The disabled
canary timer leaves `cold_canary=false` for all six services, so all six remain
`paid_stock=false` regardless of their paired-benchmark value. `release.sh` refuses any
further release between
`2026-09-03T11:49:54Z` and `2026-09-03T12:03:06Z`, the v3-06 capture activation window.

The canary timer is disabled and inactive. Do not run another canary, enable the timer, or
treat the remaining allowance or balance as permission for another payment without fresh
owner approval.

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

The release checks the response contract and pinned inventory. Collect the deployed identity
and exact response evidence separately after it returns success:

```bash
ssh <deploy-user>@<host> \
  'readlink -f /opt/docket/.venv; cat /opt/docket/RELEASE-commit.txt /opt/docket/WHEEL-sha256.txt /opt/docket/RUNTIME-LOCK-sha256.txt; sha256sum /opt/docket/release-manifest.json; /opt/docket/.venv/bin/python -c '\''import importlib.metadata as metadata; print(metadata.version("docket"))'\''; /opt/docket/.venv/bin/python -m pip check'
ssh <deploy-user>@<host> \
  'curl -fsS http://127.0.0.1:8090/services | sha256sum; curl -fsS http://127.0.0.1:8090/stats; systemctl list-timers docket-canary.timer docket-lp-record.timer docket-refresh.timer docket-v3-capture.timer docket-v3-range-capture.timer docket-v3-yield-v6-capture.timer'
```

Expected response contract; only the operational numbers change:

- `/health` returns `status`, `snapshot_id`, the served snapshot's capture time, and its age.
- `/stats` returns `coverage` with its snapshot, time, age, sampled/expected/dropped counts,
  completeness, and population, plus `refresh_status`, `registry_total`, and `probe_method`.
- `/services` returns `services`, `total`, `category`, `ordering`, and `declaration`; every
  service carries `service_id`, `paid_stock`, `stock_status`, and all four admission booleans.
- `/categories` has four rows and declares that category labels are Docket's.
- `/advantage/v2.json` builds from the artifacts included in the wheel.
- `/advantage/v3.json` lists every registered family and reports its current artifact state.
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

For an in-flight row left by a process crash, wait at least 15 minutes from its unchanged
`updated_at`, then send the same operator bearer and `{"nonce":"<nonce>"}` body to
`POST /hire/{service_id}/reconcile`. A stale `verified` or `output_ready` row becomes terminal
`failed_no_charge`; the response confirms `charge_attempted:false` and
`result_delivered:false` and carries no receipt. A stale `settling` row becomes
`settlement_unknown` and returns a recoverable result and receipt because the pre-crash
settlement outcome cannot be known. This route never calls the service or facilitator. A fresh
row returns `409 settlement_still_active`, and a concurrent state change returns
`409 payment_state_changed` without being overwritten.

## Daily governing canary

The tracked deployment units are:

- `deploy/systemd/docket-canary.service`
- `deploy/systemd/docket-canary.timer`
- `deploy/docket-canary.conf.example`

When explicitly enabled, the timer is configured to run once daily at 04:17 UTC with up to
30 minutes of randomized delay and catches one missed run after downtime. It is currently
disabled and inactive after the one approved 2026-08-30 activation. A oneshot cannot overlap
another activation of the same unit,
does not retry, yields CPU and IO priority, and is killed after eight minutes. The runner's
exclusive end is `2026-09-24T00:00:00Z`, so Sep 23 remains inside the monitored window.
Before any owner-approved manual one-shot, run
`systemctl disable --now docket-canary.timer`; require the timer to be both inactive and
disabled, and require `systemctl is-active --quiet docket-canary.service` to report inactive.
Start the service exactly once and inspect its terminal status. Leave the timer disabled;
re-enabling it requires separate owner approval. Never launch the module directly beside the
scheduled unit or retry a payment-bearing run.

This configured duty cycle comes from the governing win specification; it is not the current
authorization state. Before owner configuration, a
run is only a few sequential public HTTP reads. After the owner supplies a funded controlled
LP and the payment key file, it adds at most one free controlled-position preflight plus one
exact 0.50 USDT paid execution and its rejected replay per activation. The preflight proves the
decision-grade result before anything is spent; the replay is refused before work repeats.
The Aug 24 funding plan counted an inclusive Aug 25-Sep 23 window as 30 possible runs and
15.0 USDT. Only the single approved Aug 30 run has executed; the timer remains disabled.

The canary and registry refresh have different scopes. The canary protects the primary paid
service and controlled-position claims. The refresh keeps the small, feedback-filtered ERC-8004
fact plane and explicit Docket identities current. It does not reinstate the cut full-registry
crawl or registry-history build.

The runner appends what it checked, what it observed, its evidence, and its state to
`DOCKET_DB`. `not_yet_exercised` is not a pass: while the controlled wallet, position token,
economics, or private-key file are absent, the LP and paid legs remain in that state and the
paid admission gate remains closed. A failed or stale governing run removes paid admission;
the free verified example and free preview remain available.

The release requires the existing config at `/etc/docket/docket-canary.conf` as
`root:docket-canary` mode `0640` and the shared token at
`/etc/docket/docket-canary.token` as `root:docket` mode `0640`; it never prints, replaces, or
copies either one. For a paid deployment it also requires the configured payment key to be a
regular non-symlink file at `/etc/docket/docket-canary-payment.key`, owned by
`root:docket-canary` at mode `0640`. Before runtime mutation, it validates the dedicated
nologin/no-home system identity, exact named/default database ACLs, signer read/write access,
and denial of config/key reads to the web user. `deploy/install-canary.sh` remains the one-time
bootstrap for a new host: it creates or strictly validates that identity, backs up an existing
key before changing its ownership, and installs the ACL boundary. Neither script creates
`/etc/docket/docket-canary-payment.key`, funds an LP, or populates controlled-LP values. Those
are owner actions. Never put a private key value in the config or a unit.

The prepared payer, bounded approval, measured gas, and funding instruction are recorded in
the Configuration section. Funding and allowance alone do not set `true_settlement` and do
not put any service into paid stock. The approved run-18 evidence established one real
settlement, a nonempty bound result, and rejected replay, so the post-canary source records
`true_settlement=true`. Paid stock still requires every other admission limb. Range Doctor's
fresh paired v1 evidence opens its derived `fresh_paired_benchmark` limb at the 2026-09-04
observation, but run 18 is outside the 36-hour canary window and the timer remains disabled.
Its `cold_canary=false`, like that of the other five services, keeps all six
`paid_stock=false`.

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
SQLite-consistent backup and all release response gates have passed. Inspect the first completed run with
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

## Status and probes

Two surfaces answer "is this deployment working", and they are the same document twice.
`GET /api/status` serves it as JSON; `GET /status` renders it as a page with every reading's
observation time and the tolerance it is judged against beside it.

Both routes are public and one of the readings is an outbound chain read, so the reading is
bounded rather than the requests. **A reading is taken at most once every 60 seconds per
process** and served until it expires; `generated_at` is when the figures were observed, not
when they were asked for, so a reader can see the staleness instead of being told a held
document is current. `/api/status` additionally carries a per-peer allowance of **60 reads per
3600 seconds**, the same shape the free hire and on-demand probe routes use, and answers `429`
with `{error_code: "status_rate_limited", message}` and a `Retry-After` header beyond it. The
page is not metered: it costs a render of a reading already taken. Restarting `docket.service`
empties both the held reading and the allowances.

The document carries `status` (`ok`, `degraded` or `down`), `deployed_commit`, and five
readings:

- `db` — whether the store could be read, its SQLite journal mode, and the database file and
  its directory. Docket requires DELETE journal mode; `wal` here means the application will
  refuse the database on its next connection.
- `latest_refresh` — the newest **complete** snapshot, the one actually being served: its
  `finished_at`, its age in seconds, and `complete`. Out of tolerance when no complete sweep
  exists or the served one is older than 43,200s, which is two `docket-refresh.timer` windows.
  Read against the newest row rather than the newest complete one, this would sit degraded for
  the whole of every two-hour sweep, which is how a status page teaches an operator to ignore
  it. A sweep that finished partial is not promoted, so the previous snapshot stays in service
  and stays correct; a run of partial sweeps surfaces here as staleness.
- `refresh_in_progress` — `{started_at, age_seconds}` while a sweep is running, else `null`.
  Out of tolerance only past 7,200s, the `TimeoutStartSec` systemd starts the refresh with: a
  sweep still running past its own deadline is one systemd has killed or is about to.
- `latest_canary` — the newest recorded verdict, when it finished, its age, and `exercised`.
  Two things count against the deployment: a `failed` verdict, and a `running` row older than
  480s, the canary unit's `TimeoutStartSec` — a run whose result nobody will ever receive.
  `not_yet_exercised` does not: it is what the canary records when its paid limbs are
  unconfigured, and the timer is deliberately disabled between exercises. `exercised` is false
  for both of those, which is why **`ok` never means the paid path works** — the page's lede
  says so and names when it was last exercised.
- `rpc` — one `eth_blockNumber`, **one connection, no retry**, against the first endpoint in
  `docket/escrow/constants.py`, capped at 5s, with `reason` naming what happened when it did
  not answer. Two things are switched off here, not one. There is no failover:
  `escrow/chain.py::Rpc` walks four endpoints twice each because a job that cannot read the
  chain cannot proceed, whereas a status reading that could not read the chain has read
  something true. And the provider's own retry is disabled with
  `exception_retry_configuration=None`: web3 7.16.0 defaults to retrying `ConnectionError`,
  `HTTPError` and `Timeout` five times with exponential backoff, and `eth_blockNumber` is on
  its retry allowlist, so `request_kwargs={"timeout": 5}` bounds one connection while the
  provider quietly makes five. Measured against a socket that accepts and never answers, the
  default cost 5 connections and ~27s inside the lock a reading is built under. A BSC outage
  now costs one 5s wait per 60s window.
- `probes` — how many `docket-probe.service` runs passed and failed in the last 24 hours,
  when the newest started, and `recent_ok` of `recent_considered`. **The verdict is the last
  3 runs, not the window**: a transient failure is reported in the 24h counts but does not
  hold the page red for the rest of the day, while a run of failures does.

`deployed_commit` is read from `/opt/docket/.venv/RELEASE-commit.txt`, which `release.sh`
writes at the root of the environment it publishes. `release.sh` also refuses to finish unless
the served `/api/status` reports `ok` or `degraded` **and** names the commit the release just
published, so a process that came up on the previous wheel rolls back instead of shipping.

The tracked probe units are:

- `deploy/systemd/docket-probe.service`
- `deploy/systemd/docket-probe.timer`

The timer fires on the hour and every ten minutes after it, and catches one missed activation
after downtime. Each run makes five requests to `http://127.0.0.1:8090` — the loopback port
the application unit listens on, so the probe measures the application rather than nginx in
front of it — and records one row in `probe_runs` whatever any step did:

1. `GET /` must serve a shell carrying a Docket title.
2. `GET /services` must list services and agree with its own `total`.
3. `GET /api/status` must report `ok` or `degraded`.
4. `GET /advantage/v3.json` must agree with its own `summary.n_families`.
5. `POST /hire/range-doctor` with the catalogue's own worked example must return a result and
   a receipt. This is the only step that reaches BSC, and it is the request a buyer makes.

Step 5 spends one free-tier hire. The allowance is 20 hires per hour per caller and the probe
reaches the application over loopback with no forwarded-for header, so it spends the
`127.0.0.1` bucket at six an hour and never a public caller's.

**Reading a degraded state.** `degraded` names no reason on its own; the page does. Open
`/status`, find the row whose verdict reads `out of tolerance`, and act on that row:

| Row out of tolerance | What to do |
| --- | --- |
| Snapshot refresh | `systemctl status docket-refresh.service`, `journalctl -u docket-refresh.service`, and `/var/lib/docket/data/last-refresh.json`. A refused or failed refresh keeps the previous promoted snapshot online, so the site is serving stale but valid observations. |
| Sweep in flight | Only ever out of tolerance past 7,200s. `systemctl status docket-refresh.service` — systemd kills the unit at that deadline, so this row going red means the sweep did not finish and no new snapshot will be promoted from it. |
| Service canary | `journalctl -u docket-canary.service` and `GET /canary`. A `failed` verdict names the leg that failed in `checks`; a `running` row older than 480s is a run the unit's own deadline killed, and the next timer firing clears it. |
| BSC read | Compare against another node before touching the deployment; every endpoint in the failover list refusing at once is usually the road, not this host. |
| Synthetic probes | `journalctl -u docket-probe.service` — the readings are printed before the row is written, so a probe that could not reach its database still journalled what it found. The failing run's row in `probe_runs` names the step, its status code, its latency and what it found; step 5 failing alone is a chain or position-read fault rather than a serving fault. |

`down` means only one thing: the runtime database could not be read. Every other reading is
taken out of it, so treat the readings on a `down` page as absent rather than as zero, and go
to Database handling below.

## Database handling

The runtime database contains observation snapshots and payment lifecycle state.
`release.sh` stops timer scheduling, proves all timer workers inactive, creates its timestamped
SQLite-consistent backup, and prints the verified path before stopping the application service.
Record that path and time in the deployment record. Do not
replace the runtime database with the repository's ignored `data/` path.

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
