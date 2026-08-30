# Range v3-05 capture and input-lock run — Aug 26

> Current-state handover: v3-05 is already captured, calibrated, input-locked and
> deployed. Stages 0-3 are historical and must not be rerun. Confirm the locked input
> below, then proceed only to the genuine owner-operated manual slots in stage 4.

    @'
    from pathlib import Path
    from docket.advantage.v3.spec import assert_runnable, load

    root = Path('.').resolve()
    spec = load(root / 'docket/advantage/v3/specs/v3-05-range-doctor.json', repo_root=root)
    assert spec.stage_one_protocol_hash == '0x2a83c1a331d579e5cef461d52c539711b4fa2bba6dd397aaad1bf38b6b47f9ab'
    assert spec.inputs_sha256 == '73086fba1ddbb82074003b4c04ef8564358f86b896a0a609b5e5f7e3c543e8b6'
    assert_runnable(spec, repo_root=root)
    print('v3-05 locked input verified; stages 0-3 remain historical')
    '@ | .\.venv\Scripts\python.exe -

This is the operator procedure for `v3-05-range-doctor`. Run repository commands from the
repository root in PowerShell. The three evidence stages are different operations:

1. collect the historical, block-hash-pinned enumerable frame;
2. capture pool truth at 12:10Z, 12:11Z or 12:12Z;
3. bind the successful capture and lock the input after Range calibration exists.

Every registered evidence path below is first-write. Do not delete, rename, truncate or
replace an artifact to make a second attempt possible. The uniquely named stage-3 transfer
directory becomes registered evidence only when it is renamed once into the reserved path.
A scratch rehearsal is not the registered frame, and deploying or enabling the timer remains
an owner action.

Experiment arms run on the workstation against the repository tree. The installed package is
read-only and must not be used as a ledger target. A ledger becomes visible in production only
after it is committed to the repository and that commit is redeployed.

## 0. Immutable state and rehearsal evidence

The registration pins block `117841891`, hash
`0x5881782f547a332f473be1d4b1279912799bc11d3955e1015a3d27a48320b9ff`, observed at
`2026-08-24T16:42:59Z`. The pool-truth attempts are exactly:

- `2026-08-26T12:10:00Z`
- `2026-08-26T12:11:00Z`
- `2026-08-26T12:12:00Z`

On 2026-08-24, the complete collector captured 1,024 rows at block 117,841,891 in 11m27.6s
using 3,173 read calls, with zero failures. The observed block and hash matched the
registration. The frame SHA-256 was
`ea41a6391e2d40f15c394224d9c7b0699b3eeca4968a2de9f75c43df32469761`.

The real frame must match that digest byte-for-byte. A mismatch is a determinism defect: stop
without assembling or locking.

Before 12:10Z, read-only inspection, hash checks, scratch rehearsals, the real historical
frame and timer installation/arming are permitted. Do not fetch either pool-truth URL as a
registered attempt before 12:10Z, create a substitute capture directory, bind pool truth or
lock the input. The armed process owns the registered clock.

Before stage 1 or 2, require the unlocked registration and a clean explanation for every
change:

```powershell
git status --short
@'
from pathlib import Path
from docket.advantage.v3.spec import load

root = Path('.').resolve()
spec = load(root / 'docket/advantage/v3/specs/v3-05-range-doctor.json', repo_root=root)
assert spec.stage_one_protocol_hash == '0x2a83c1a331d579e5cef461d52c539711b4fa2bba6dd397aaad1bf38b6b47f9ab'
assert spec.spec_hash == '0xbc945b91d2b6649f077050da5eb1c8ee7472568dd9d76d9bdeb7f6974cfd449d'
assert spec.inputs_sha256 == ''
assert not (root / spec.inputs_ref).exists()
print('v3-05 remains unlocked')
'@ | .\.venv\Scripts\python.exe -
if ($LASTEXITCODE -ne 0) { throw 'v3-05 immutable preflight failed' }
```

## 1. Historical chain frame — permitted before 12:10Z

This stage is not time-bound. It reads the registered past block by EIP-1898 block hash. Run
it once to the reserved repository source path; assembly refuses a frame outside the
repository. Load the endpoint without printing it:

```powershell
$frame = 'docket/advantage/v3/sources/range-v5-enumerable-frame.json'
if (Test-Path -LiteralPath $frame) { throw "first-write frame already exists: $frame" }

$archiveConfig = @(ssh -o BatchMode=yes <deploy-user>@<host> 'cat /etc/docket/docket-archive.conf')
if ($LASTEXITCODE -ne 0) { throw 'could not read the archive configuration' }
$rpcLines = @($archiveConfig | Where-Object { $_ -match '^DOCKET_ARCHIVE_RPC=' })
if ($rpcLines.Count -ne 1) { throw 'archive configuration must contain one RPC assignment' }
$endpoint = ($rpcLines[0] -replace '^DOCKET_ARCHIVE_RPC=', '').Trim().Trim('"').Trim("'")
if (-not [Uri]::IsWellFormedUriString($endpoint, [UriKind]::Absolute)) {
  throw 'archive endpoint is not an absolute URI'
}

$env:DOCKET_ARCHIVE_RPC = $endpoint
try {
  & .\.venv\Scripts\python.exe -m docket.advantage.v3.range_capture `
    v3-05-range-doctor $frame
  $frameExit = $LASTEXITCODE
} finally {
  Remove-Item Env:DOCKET_ARCHIVE_RPC -ErrorAction SilentlyContinue
}
if ($frameExit -ne 0) { throw "Range frame capture refused with exit $frameExit; stop" }

$frameSha = (Get-FileHash -Algorithm SHA256 -LiteralPath $frame).Hash.ToLowerInvariant()
if ($frameSha -ne 'ea41a6391e2d40f15c394224d9c7b0699b3eeca4968a2de9f75c43df32469761') {
  throw "determinism blocker: real frame SHA-256 is $frameSha"
}
```

Success prints `captured 1024 rows ... with 3173 read calls`. Exit `2` and stderr beginning
`range capture refused:` is a protocol refusal. Any RPC, ABI, header or completeness problem
aborts before the output is linked into place. Preserve the exact error. If `$frame` is still
absent, wait for the same configured endpoint to recover and rerun the exact full collector
command above. Never retry sampled calls or switch endpoints. Stage 1 is not time-bound:
continue stage 2 on schedule regardless. An existing output also refuses before network
access and must never be removed or replaced to permit another write.

## 2. Registered pool truth — only the middle stage is time-bound

The tracked timer is `docket-v3-range-capture.timer`. It fires at `12:03:00Z`, after Yield's
last bounded request can finish at `12:02:55Z`, then the process writes `armed.json` and sleeps
to 12:10Z. There is no randomized delay. Range and Yield use distinct services, directories
and locks; no service-ordering directive is used because a failed Yield restart must not
delay Range past its registered moment.

After the owner releases the exact tested commit, verify the installed bytes and schedule:

```powershell
$releasedCommit = (& git rev-parse HEAD).Trim()
if ($LASTEXITCODE -ne 0 -or $releasedCommit -notmatch '^[0-9a-f]{40}$') {
  throw 'could not identify the released commit'
}
$rangeUnitAudit = @'
set -euo pipefail
expected_commit=$1
service=/etc/systemd/system/docket-v3-range-capture.service
timer=/etc/systemd/system/docket-v3-range-capture.timer
test "$(</opt/docket/RELEASE-commit.txt)" = "$expected_commit"
cmp -s "$service" /opt/docket/deploy/systemd/docket-v3-range-capture.service
cmp -s "$timer" /opt/docket/deploy/systemd/docket-v3-range-capture.timer
python3 - "$service" "$timer" <<'PY'
from pathlib import Path
import sys

def values(path, name):
    text = Path(path).read_text(encoding="utf-8").replace("\\\n", " ")
    found = []
    for raw in text.splitlines():
        key, sep, value = raw.strip().partition("=")
        if sep and key.strip() == name:
            found.append(" ".join(value.split()))
    return found

service, timer = sys.argv[1:]
expected = (
    (timer, "OnCalendar", "2026-08-26 12:03:00 UTC"),
    (timer, "Unit", "docket-v3-range-capture.service"),
    (service, "ExecStart", "/opt/docket/.venv/bin/python -P -m docket.advantage.v3.capture v3-05-range-doctor /var/lib/docket/v3-capture/range"),
)
for path, name, wanted in expected:
    actual = values(path, name)
    if actual != [wanted]:
        raise SystemExit(f"{path}: expected exactly one {name}={wanted!r}, got {actual!r}")
PY
systemd-analyze verify "$service" "$timer"
systemctl is-enabled docket-v3-range-capture.timer >/dev/null
systemctl list-timers docket-v3-range-capture.timer
'@
$rangeUnitAudit | ssh <deploy-user>@<host> "bash -s -- $releasedCommit"
if ($LASTEXITCODE -ne 0) {
  throw 'released Range units or schedule do not match the tested commit'
}
```

At or after 12:03Z but before 12:10Z, the expected state is an active sleeping oneshot plus
one first-write arm record:

```powershell
ssh <deploy-user>@<host> 'set -o pipefail; systemctl is-active docket-v3-range-capture.service && test -f /var/lib/docket/v3-capture/range/armed.json && find /var/lib/docket/v3-capture/range -maxdepth 1 -type f -printf "%f\n" | sort'
if ($LASTEXITCODE -ne 0) { throw 'Range arm check failed; only if the timer missed 12:03Z and no Range service or artifact exists, follow the one-start recovery below' }
```

If the timer is enabled but not yet due, do nothing. If it missed 12:03Z and no Range service
or artifact exists, the owner may start the tracked service once before 12:10Z:

```powershell
ssh <deploy-user>@<host> 'systemctl start --no-block docket-v3-range-capture.service'
```

Do not manually start it when `armed.json`, `armed-*.json` or any `attempt-*` file exists.
After the service stops, inspect the evidence and journal without changing either:

```powershell
ssh <deploy-user>@<host> 'systemctl show docket-v3-range-capture.service -p Result -p ExecMainCode -p ExecMainStatus; journalctl -u docket-v3-range-capture.service --since "2026-08-26 12:00:00 UTC" --no-pager; find /var/lib/docket/v3-capture/range -maxdepth 1 -type f -printf "%f\n" | sort'
```

Interpret the exit and files exactly:

- `0`: captured. Require `capture-complete.json`, `capture-attempts.json`, both final raw
  bodies and the chosen attempt files.
- `1`: unexpected runtime failure; `capture-failed*.json` records it.
- `2`: protocol refusal; `capture-refused*.json` records it. A late Persistent catch-up takes
  this path before HTTP. For v3-05, any start after `12:10:05Z` is late.
- `3`: registered non-capture. `capture-attempts.json` and `capture-failed*.json` explain the
  exhausted or unusable attempts.
- `4`: the terminal condition occurred but even its evidence could not be written; preserve
  stderr and investigate the filesystem.

After any `attempt-*` evidence exists, no restart or manual rerun is permitted. If all three
attempts fail, preserve the entire directory, do not make a fourth request, and do not run
stage 3. A later capture requires a newly committed registration with new timestamps and a
new empty directory.

## 3. Copy, bind and lock — only after a successful capture and calibration

Copy the completed VPS directory once into the reserved local path:

```powershell
$frame = 'docket/advantage/v3/sources/range-v5-enumerable-frame.json'
$poolCapture = 'data/range-v5-pool-capture-20260826'
if (Test-Path -LiteralPath $poolCapture) { throw "local capture already exists: $poolCapture" }
$poolCaptureParent = Split-Path -Parent $poolCapture
if (Test-Path -LiteralPath $poolCaptureParent -PathType Leaf) {
  throw "capture parent is not a directory: $poolCaptureParent"
}
[IO.Directory]::CreateDirectory([IO.Path]::GetFullPath($poolCaptureParent)) | Out-Null
$poolCaptureStaging = "$poolCapture.staging-$([guid]::NewGuid().ToString('N'))"
scp -r <deploy-user>@<host>:/var/lib/docket/v3-capture/range $poolCaptureStaging
if ($LASTEXITCODE -ne 0) {
  throw "copy failed; only failed staging copy $poolCaptureStaging may be discarded before retry"
}
try {
  $captureLog = Get-Content -Raw -LiteralPath "$poolCaptureStaging/capture-attempts.json" `
    -ErrorAction Stop | ConvertFrom-Json -ErrorAction Stop
} catch {
  throw "staging copy has no readable capture log; only $poolCaptureStaging may be discarded"
}
$captureAttempts = @($captureLog.attempts)
if (-not $captureLog.captured -or $captureAttempts.Count -lt 1) {
  throw "staging copy is not a completed capture; only $poolCaptureStaging may be discarded"
}
$chosenAttempt = $captureAttempts[-1]
if (-not $chosenAttempt.succeeded) {
  throw "staging copy has no successful chosen attempt; only $poolCaptureStaging may be discarded"
}
$chosenOrdinal = [int]$chosenAttempt.attempt_ordinal
foreach ($required in @(
  "$poolCaptureStaging/capture-complete.json",
  "$poolCaptureStaging/capture-attempts.json",
  "$poolCaptureStaging/pools.raw.json",
  "$poolCaptureStaging/token-list.raw.json",
  ("$poolCaptureStaging/attempt-{0:D2}.pools.raw.json" -f $chosenOrdinal),
  ("$poolCaptureStaging/attempt-{0:D2}.token-list.raw.json" -f $chosenOrdinal)
)) {
  if (-not (Test-Path -LiteralPath $required -PathType Leaf)) {
    throw "staging copy is incomplete: $required; only $poolCaptureStaging may be discarded"
  }
}
[IO.Directory]::Move(
  [IO.Path]::GetFullPath($poolCaptureStaging),
  [IO.Path]::GetFullPath($poolCapture)
)
```

Only a staging directory whose copy or verification failed may be discarded. Never discard
the reserved final path or the VPS evidence directory.

`lock-range` also requires three production calibration artifacts. They do not exist in the
registered source tree as of this runbook. The calibration workstream must publish them at
these reserved paths before assembly is attempted:

```powershell
$calibrationSet = 'docket/advantage/v3/sources/range-v5-calibration-set.json'
$evaluatorCalibration = 'docket/advantage/v3/sources/range-v5-evaluator-calibration.json'
$calibrationRoot = 'docket/advantage/v3/calibration-captures/2026-08-26-range-v5'
$poolTruth = 'docket/advantage/v3/sources/range-v5-pool-truth.json'
$specPath = 'docket/advantage/v3/specs/v3-05-range-doctor.json'

foreach ($required in @(
  $frame,
  "$poolCapture/capture-complete.json",
  "$poolCapture/capture-attempts.json",
  "$poolCapture/pools.raw.json",
  "$poolCapture/token-list.raw.json",
  $calibrationSet,
  $evaluatorCalibration,
  $calibrationRoot
)) {
  if (-not (Test-Path -LiteralPath $required)) { throw "required input is absent: $required" }
}
try {
  $specState = Get-Content -Raw -LiteralPath $specPath -ErrorAction Stop | `
    ConvertFrom-Json -ErrorAction Stop
} catch {
  throw 'could not read the Range registration'
}
$alreadyLocked = -not [string]::IsNullOrEmpty([string]$specState.inputs_sha256)
```

Only after every preflight succeeds, bind and lock. If a crash left pool truth or the input
envelope behind while the spec remains unlocked, rerun this exact command: byte-identical
derived bytes are accepted and different bytes refuse. If the spec is already locked, do not
rerun the command; continue directly to verification.

```powershell
if (-not $alreadyLocked) {
  & .\.venv\Scripts\python.exe -m docket.advantage.v3.assemble lock-range `
    $specPath `
    $frame `
    $poolCapture `
    $poolTruth `
    $calibrationSet `
    $evaluatorCalibration `
    $calibrationRoot
  if ($LASTEXITCODE -ne 0) { throw 'v3-05 assembly/input lock refused; preserve every file' }
}
```

The command first-writes the bound pool truth and input envelope, then updates the spec. An
existing byte-identical pool truth or envelope is accepted only for crash recovery; different
bytes refuse. Once `inputs_sha256` is set, the input lock cannot be repeated. Verify the
unchanged stage-one hash and the now-runnable input before committing the frame, pool truth,
input, calibration evidence and updated spec together:

```powershell
@'
from pathlib import Path
from docket.advantage.v3.spec import assert_runnable, load

root = Path('.').resolve()
spec = load(root / 'docket/advantage/v3/specs/v3-05-range-doctor.json', repo_root=root)
assert spec.stage_one_protocol_hash == '0x2a83c1a331d579e5cef461d52c539711b4fa2bba6dd397aaad1bf38b6b47f9ab'
assert len(spec.inputs_sha256) == 64
assert_runnable(spec, repo_root=root)
print(spec.inputs_ref, spec.inputs_sha256)
'@ | .\.venv\Scripts\python.exe -
if ($LASTEXITCODE -ne 0) { throw 'locked Range input did not validate' }
```

No command in this runbook authorizes a push, deployment, transaction or submission.

## 4. Owner-only manual-arm handover after release

The next action belongs to the owner after the reviewed reveal/recording change is released.
The interactive reveal contains the truth-stripped case and `source_snapshots.pools` plus
`source_snapshots.token_list` from the committed pool-truth artifact. Each snapshot carries
its committed source reference, URL, observation, digest, exact base64 bytes and decoded JSON
body. It contains neither locked truth nor agent output. After the timed claim and before
stdin is read, the harness records one `source_query` event for each revealed snapshot,
bound to its source reference and body digest. Close Docket and all agent output and, from
the repository root, run exactly three manual slots:

```powershell
1..3 | ForEach-Object {
  .\.venv\Scripts\python.exe -m docket.advantage.v3.orchestrator `
    v3-05-range-doctor docket/advantage/v3/runs `
    --repo-root . --interactive --once
  if ($LASTEXITCODE -ne 0) {
    throw "Range manual primary $_ refused; preserve the ledger and do not retry"
  }
}
```

For each reveal, submit one JSON object on one physical line. It must contain exactly the
top-level answer fields `position`, `observation`, `range`, `pool_evidence`, `rates`, `dollars`,
`action`, `coverage`, `limitations` and `sources`. Fill every field from the revealed frozen
case, including the exact token/block/range facts, bound pool evidence, rate and dollar work,
action, complete-frame coverage, registered limits and source identities.

Do not prepare answers in advance and do not paste the revealed payload as the answer. A blank,
malformed, multiline, interrupted or schema-invalid submission consumes that primary. There is
one final submission per slot and no retry or replacement.

## 5. Run the three Range Doctor agent primaries

Only after all three owner-operated manual primaries are terminal, run the deployed Range
Doctor block. Run one slot per command so the operator sees every permanent outcome before
claiming the next slot. Do not add `--payment-header`; the harness records the receipt the
registered endpoint actually returns.

```powershell
1..3 | ForEach-Object {
  $agent = @(
    & .\.venv\Scripts\python.exe -m docket.advantage.v3.orchestrator `
      v3-05-range-doctor docket/advantage/v3/runs `
      --repo-root . --once 2>&1
  )
  $agentExit = $LASTEXITCODE
  $agent | ForEach-Object { Write-Host $_ }
  $last = [string]@($agent)[-1]
  if ($last -match ' blocked_service_contract$') {
    throw 'blocked_service_contract is permanent for this run; preserve the ledger, do not retry, and do not score'
  }
  if ($agentExit -ne 0) {
    throw "Range Doctor agent primary $_ refused; preserve the ledger and do not retry"
  }
  if ($last -notmatch ' succeeded$') {
    Write-Warning "Range Doctor agent primary $_ is a permanent non-success; do not retry or replace it"
  }
}
```

HTTP 400, 402 or 422 becomes `blocked_service_contract`; scoring is unavailable and the run
stops with its preserved record. Any timeout, transport or other HTTP error, interruption, empty
or malformed result, invalid receipt, wrong token id/block or incomplete answer remains a
permanent terminal in the registered denominator. Never delete, edit, replay or replace a
claimed primary.

## 6. Require all six registered primaries to be terminal

Fold the ledger rather than counting only one event kind, because recovered interruptions are
also terminal. Every non-success remains part of the record.

```powershell
@'
from collections import Counter
from pathlib import Path
from docket.advantage.v3 import runner
from docket.advantage.v3.spec import load

root = Path('.').resolve()
spec = load(root / 'docket/advantage/v3/specs/v3-05-range-doctor.json', repo_root=root)
slots = runner.scheduled_slots(spec, repo_root=root)
state = runner.read_state(runner.ledger_path(spec, root / 'docket/advantage/v3/runs'))
missing = [slot.slot for slot in slots if slot.slot not in state or not state[slot.slot].is_terminated]
if missing:
    raise SystemExit(f'not all six registered primaries are terminal: {missing}')
terminals = [state[slot.slot].terminal for slot in slots]
if len(terminals) != 6:
    raise SystemExit(f'expected six registered primaries, found {len(terminals)}')
blocked = [row['slot'] for row in terminals if row['outcome'] == runner.BLOCKED_CONTRACT]
print(len(terminals), Counter(row['outcome'] for row in terminals))
if blocked:
    raise SystemExit(f'blocked service contract leaves the family unscored; do not export evaluator sessions: {blocked}')
'@ | .\.venv\Scripts\python.exe -
if ($LASTEXITCODE -ne 0) { throw 'Range terminal-primary closeout failed; preserve the ledger' }
```

Do not continue until the command prints `6` and exits zero.

## 7. Export two first-write blind-evaluation sessions

Export only after all six primaries are terminal and no `blocked_service_contract` terminal
exists. Session files are exclusive first writes; an existing file refuses rather than being
overwritten.

```powershell
@'
from pathlib import Path
from docket.advantage.v3.runner import ExperimentHarness
from docket.advantage.v3.spec import load

root = Path('.').resolve()
spec = load(root / 'docket/advantage/v3/specs/v3-05-range-doctor.json', repo_root=root)
harness = ExperimentHarness(spec, root / 'docket/advantage/v3/runs', repo_root=root)
print(*harness.export_evaluation_sessions(root / 'data/range-v5-evaluation-sessions'), sep='\n')
'@ | .\.venv\Scripts\python.exe -
if ($LASTEXITCODE -ne 0) { throw 'Range evaluation-session export refused; do not replace an existing session' }
```

Run seat A through the registered Codex adapter and preserve its first raw response bytes:

```powershell
@'
import json
from pathlib import Path
from docket.advantage.v3.seats.codex_cli import ask

sessions = Path('data/range-v5-evaluation-sessions')
session = next(path for path in sessions.glob('*.json') if json.loads(path.read_text(encoding='utf-8'))['evaluator_id'] == 'seat-a')
raw = ask(session.read_bytes())
if raw is None:
    raise SystemExit('seat-a returned no response; do not ask again or substitute another evaluator')
out = Path('data/range-v5-seat-a.raw.json')
with out.open('xb') as handle:
    handle.write(raw)
print(out)
'@ | .\.venv\Scripts\python.exe -
if ($LASTEXITCODE -ne 0) { throw 'seat-a first response was not preserved; stop without retry' }
```

Run seat B through the registered Claude adapter and preserve its first raw response bytes:

```powershell
@'
import json
from pathlib import Path
from docket.advantage.v3.seats.claude_cli import ask

sessions = Path('data/range-v5-evaluation-sessions')
session = next(path for path in sessions.glob('*.json') if json.loads(path.read_text(encoding='utf-8'))['evaluator_id'] == 'seat-b')
raw = ask(session.read_bytes())
if raw is None:
    raise SystemExit('seat-b returned no response; do not ask again or substitute another evaluator')
out = Path('data/range-v5-seat-b.raw.json')
with out.open('xb') as handle:
    handle.write(raw)
print(out)
'@ | .\.venv\Scripts\python.exe -
if ($LASTEXITCODE -ne 0) { throw 'seat-b first response was not preserved; stop without retry' }
```

Each response must be only the completed `score_sheet_template` object from that seat's
session. A missing, malformed or incomplete first response leaves the family unscored. Do not
ask again, repair the response bytes or substitute another evaluator.

## 8. Import both score sheets, publish mapping and close the report

Import the two preserved first responses through the claim-once API:

```powershell
@'
from pathlib import Path
from docket.advantage.v3.runner import ExperimentHarness
from docket.advantage.v3.spec import load

root = Path('.').resolve()
spec = load(root / 'docket/advantage/v3/specs/v3-05-range-doctor.json', repo_root=root)
harness = ExperimentHarness(spec, root / 'docket/advantage/v3/runs', repo_root=root)
for seat in ('seat-a', 'seat-b'):
    raw = (root / f'data/range-v5-{seat}.raw.json').read_bytes()
    artifact = harness.import_evaluation_submission(raw, root / 'docket/advantage/v3/sheets')
    print(artifact['evaluator_id'], artifact['raw_sheet_sha256'])
'@ | .\.venv\Scripts\python.exe -
if ($LASTEXITCODE -ne 0) { throw 'Range score-sheet import failed; preserve the first raw responses and do not retry either seat' }
```

Do not reveal the A/B assignment until both first-write imports succeed. Then publish the
deterministic mapping and derive the same family object served by `/advantage/v3.json`:

```powershell
@'
import json
from pathlib import Path
from docket.advantage.v3 import report, runner, scoring
from docket.advantage.v3.spec import load

root = Path('.').resolve()
spec = load(root / 'docket/advantage/v3/specs/v3-05-range-doctor.json', repo_root=root)
ledger = runner.ledger_path(spec, root / 'docket/advantage/v3/runs')
bundle = scoring.build_blinded_bundle(spec, ledger, repo_root=root)
scoring.publish_mapping(
    spec,
    bundle,
    root / 'docket/advantage/v3/sheets',
    root / 'docket/advantage/v3/mappings',
    repo_root=root,
)
payload = report.report()
family = next(row for row in payload['families'] if row['spec_id'] == spec.spec_id)
expected_terminal = (
    'refuted' if family['falsifier_result']['refuted'] else 'not_refuted'
)
assert family['state'] == expected_terminal
print(json.dumps({
    'state': family['state'],
    'calibration': family['calibration'],
    'run_progress': family['run_progress'],
    'quality': family['quality'],
    'speed': family['speed'],
    'formula_metrics': family['formula_metrics'],
    'falsifier_result': family['falsifier_result'],
}, indent=2, sort_keys=True))
'@ | .\.venv\Scripts\python.exe -
if ($LASTEXITCODE -ne 0) { throw 'Range mapping/report closeout failed; preserve every artifact' }
```

`refuted` is an honest completed result, not a failed closeout. `not_refuted` means only that
the registered falsifier did not fire; it is not proof of the claim. Review the exact ledger,
two raw responses, imported score-sheet artifacts, published mapping and derived report before
requesting owner approval for any commit or deployment. This runbook does not authorize a
commit, push, deployment, transaction or submission.
