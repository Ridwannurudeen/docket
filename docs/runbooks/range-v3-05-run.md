# Range v3-05 capture and input-lock run — Aug 26

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

$archiveConfig = @(ssh -o BatchMode=yes root@gudman.xyz 'cat /etc/docket/docket-archive.conf')
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
    (service, "ExecStart", "/opt/docket/.venv/bin/python -m docket.advantage.v3.capture v3-05-range-doctor /var/lib/docket/v3-capture/range"),
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
$rangeUnitAudit | ssh root@gudman.xyz "bash -s -- $releasedCommit"
if ($LASTEXITCODE -ne 0) {
  throw 'released Range units or schedule do not match the tested commit'
}
```

At or after 12:03Z but before 12:10Z, the expected state is an active sleeping oneshot plus
one first-write arm record:

```powershell
ssh root@gudman.xyz 'set -o pipefail; systemctl is-active docket-v3-range-capture.service && test -f /var/lib/docket/v3-capture/range/armed.json && find /var/lib/docket/v3-capture/range -maxdepth 1 -type f -printf "%f\n" | sort'
if ($LASTEXITCODE -ne 0) { throw 'Range arm check failed; only if the timer missed 12:03Z and no Range service or artifact exists, follow the one-start recovery below' }
```

If the timer is enabled but not yet due, do nothing. If it missed 12:03Z and no Range service
or artifact exists, the owner may start the tracked service once before 12:10Z:

```powershell
ssh root@gudman.xyz 'systemctl start --no-block docket-v3-range-capture.service'
```

Do not manually start it when `armed.json`, `armed-*.json` or any `attempt-*` file exists.
After the service stops, inspect the evidence and journal without changing either:

```powershell
ssh root@gudman.xyz 'systemctl show docket-v3-range-capture.service -p Result -p ExecMainCode -p ExecMainStatus; journalctl -u docket-v3-range-capture.service --since "2026-08-26 12:00:00 UTC" --no-pager; find /var/lib/docket/v3-capture/range -maxdepth 1 -type f -printf "%f\n" | sort'
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
scp -r root@gudman.xyz:/var/lib/docket/v3-capture/range $poolCaptureStaging
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
