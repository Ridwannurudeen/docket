# Range v3-07 registration, capture and run — Sep 4-8

> v3-07 is a **distinct successor** to v3-05, not a retry of it. v3-05's ledger, inputs and
> published state are never read, edited, relabelled or deleted by anything in this runbook.
> The operator-held v3-05 ledger records one manual primary permanently `interrupted`, which
> leaves `refuted` as that family's only terminal state; that ledger is outside the tracked
> tree, and nothing here repairs it or is meant to.

Run repository commands from the repository root in PowerShell, always through
`.\.venv\Scripts\python.exe`. No command in this runbook authorizes a push, deployment,
transaction or submission. Three of them spend money and every one of those is gated on the
owner's explicit approval immediately beforehand.

Digests below are written **without** their `0x` prefix and joined in code where a command
needs them. They are block and protocol hashes, but bare `0x`-plus-64-hex is also the shape of
a private key, and this repository blocks that pattern rather than asking each time which it
is.

The evidence stages are different operations and must not be reordered:

1. commit the registration — git history is the only registration witness;
2. collect the historical, block-hash-pinned enumerable frame;
3. calibrate both evaluator seats against the committed answer key;
4. capture pool truth at 12:00Z, 12:01Z or 12:02Z on 2026-09-05;
5. bind the successful capture and lock the input;
6. run three human manual primaries, then three settled agent primaries;
7. export, score, map and publish.

Every registered evidence path below is first-write. Do not delete, rename, truncate or
replace an artifact to make a second attempt possible. A scratch rehearsal is not the
registered frame, and deploying or enabling the timer remains an owner action.

## What is first-write and has no retry

| Artifact | Stage | If it goes wrong |
|---|---|---|
| `sources/range-v7-enumerable-frame.json` | 1 | Refuses if it exists. Rerun the exact full collector only while the file is still absent. |
| Each seat's calibration attempt | 2 | A captured response binds even when it fails. Never ask the same seat again. |
| `/var/lib/docket/v3-capture/range-v3-07` on the host | 3 | Three attempts only. After any `attempt-*` file exists, no restart and no manual rerun. |
| `data/range-v7-pool-capture-20260905` | 4 | One `Move-Item` from a verified staging copy. Only a failed staging copy may be discarded. |
| `sources/range-v7-pool-truth.json` and the input envelope | 5 | A byte-identical rewrite is accepted for crash recovery; different bytes refuse. |
| `inputs_sha256` in the spec | 5 | Once set, the input lock cannot be repeated. |
| Each of the six primaries | 6-7 | One attempt per case per arm. A blank, malformed, interrupted or schema-invalid answer consumes that primary. |
| `data/range-v7-seat-{a,b}.raw.json` and the imported sheets | 9-10 | Exclusive first writes. A missing or malformed first response leaves the family unscored. |

## Schedule

| Date (UTC) | Step | Who |
|---|---|---|
| Sep 4 | Owner commits the registration. **Nothing below may run first.** | Owner |
| Sep 4 | Deploy the tested commit. Outside every refusal window. | Owner |
| Sep 4 | Stage 1, the frame collection, about 12 minutes | Operator |
| Sep 4, or Sep 5 morning | Stage 2, both calibration seats | Operator |
| Sep 5 11:50 | `docket-v3-range-v7-capture.timer` arms; capture at 12:00 | Timer |
| Sep 5 after 12:03:06 | Stages 4 and 5, copy, bind, lock | Operator |
| Sep 6 | Stage 6, three manual primaries; stage 7, three settled hires | Owner |
| Sep 7 | Stages 8-10, seats, import, mapping, report | Operator |
| Sep 8 | Review before requesting any commit | Owner |

`deploy/release.sh` refuses releases in three windows: `2026-08-26T12:02:54Z` to
`2026-08-26T12:10:06Z`, `2026-09-03T11:49:54Z` to `2026-09-03T12:03:06Z` and
`2026-09-05T11:49:54Z` to `2026-09-05T12:03:06Z`. Do not run v3-06 and v3-07 arms on the same
day: the Claude seat adapter is what left v3-04 permanently `complete_unscored`, and one
family per day is the rule that came out of it.

## 0. Immutable state and preflight

The registration pins block `119531513`, block hash
`4e18a1905cf1f81a3dd4b78fca96d9b4e422cb6552fece64c3af369c8801b57b`, observed at
`2026-09-02T11:59:59Z`. That block was chosen by a public rule — the highest BSC block whose
header timestamp is strictly earlier than `2026-09-02T12:00:00Z` — and its number, hash and
timestamp read identically from three independent public BSC endpoints, so a reader can
re-derive the pin without trusting the operator. The pool-truth attempts are exactly
`2026-09-05T12:00:00Z`, `2026-09-05T12:01:00Z` and `2026-09-05T12:02:00Z`.

**There is no pre-registered frame digest, and that is deliberate.** v3-05 had one because a
rehearsal had already collected its frame. v3-07's frame has never been read, which is what
its registration means by not having read the frame before the commit. Determinism is checked
instead at the lock, which re-derives all 1,024 indices from the stage-one protocol hash,
requires every row to match its derived index, and requires the RPC call accounting to equal
exactly what the registered method implies. A frame that was not collected as registered
cannot pass either check.

Before stage 1, require the committed registration, the unlocked input and a clean
explanation for every other change:

```powershell
git status --short
git log --oneline -1 -- docket/advantage/v3/specs/v3-07-range-doctor.json
@'
from pathlib import Path
from docket.advantage.v3.spec import load

root = Path('.').resolve()
spec = load(root / 'docket/advantage/v3/specs/v3-07-range-doctor.json', repo_root=root)
assert spec.stage_one_protocol_hash == '0x' + '3305b8b3dd15ba3933dedc6b50ef94c4d2ea1f1a6cb26666ba84dd4ec45e67f5'
assert spec.spec_hash == '0x' + '90e1460ef5764d80c6b120d2552db3481d01b22b1f04edc6ac3098a64779b9da'
assert spec.inputs_sha256 == ''
assert not (root / spec.inputs_ref).exists()
assert spec.protocol_correction is None
assert spec.pilot_provenance is None
assert spec.successor_provenance['prior_spec_id'] == 'v3-05-range-doctor'
frame = spec.case_selection['frame_definition']
assert frame['observation_block'] == 119531513
assert frame['observation_block_hash'] == '0x' + '4e18a1905cf1f81a3dd4b78fca96d9b4e422cb6552fece64c3af369c8801b57b'
assert frame['pool_truth_capture_attempts'][0] == '2026-09-05T12:00:00Z'
assert spec.case_selection['prior_exposure_exclusion']['token_ids'] == [1056809, 1653348, 5223058]
print('v3-07 remains unlocked and registered as committed')
'@ | .\.venv\Scripts\python.exe -
if ($LASTEXITCODE -ne 0) { throw 'v3-07 immutable preflight failed' }
```

`git log` must print a commit. **If it prints nothing the registration is uncommitted and
nothing below may run** — an uncommitted registration has no witness, and every later artifact
would be unprovable.

Confirm the predecessor is untouched, before and after every stage that writes:

```powershell
git status --short -- docket/advantage/v3/specs/v3-05-range-doctor.json docket/advantage/v3/inputs/range-v5-positions.json docket/advantage/v3/sources/range-v5-enumerable-frame.json docket/advantage/v3/sources/range-v5-pool-truth.json
```

It must print nothing. The untracked `docket/advantage/v3/runs/v3-05-range-doctor.jsonl` is
never read, moved or deleted by this runbook.

## 1. Collect the archive-pinned enumerable frame — permitted after the registration commit

This stage is not time-bound and carries no foreknowledge: it reads a past block by EIP-1898
block hash, and the 1,024 indices it reads were fixed by the stage-one hash that is already
committed. **The committed v3-05 frame cannot be reused here.** The indices are derived from
the stage-one protocol hash, so v3-07 necessarily draws a different sample and must collect
its own frame; the measured overlap figures from v3-05's population say nothing about this
one. Run the collector once to the reserved repository source path; assembly refuses a frame
outside the repository. Load the endpoint without printing it:

```powershell
$frame = 'docket/advantage/v3/sources/range-v7-enumerable-frame.json'
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
    v3-07-range-doctor $frame
  $frameExit = $LASTEXITCODE
} finally {
  Remove-Item Env:DOCKET_ARCHIVE_RPC -ErrorAction SilentlyContinue
}
if ($frameExit -ne 0) { throw "Range frame capture refused with exit $frameExit; stop" }
```

Success prints `captured 1024 rows at block 119531513 with <n> read calls`. Exit `2` with
stderr beginning `range capture refused:` is a protocol refusal; preserve the exact error.

The substantive risk this stage carries is **archive depth**. The collector reads state at a
block roughly two days old, by block hash with `requireCanonical: true`. v3-05's comparable
collection ran against a block from the same day, so the configured endpoint has not been
observed serving state this far back. A head behind the registered block, a pruned-state
error or a missing trie node all surface here as a refusal with nothing written. If `$frame`
is still absent, wait for the **same** configured endpoint to recover and rerun the exact full
collector command above. Never retry a sampled call and never substitute an endpoint: either
would make the frame a mixture of two sources, and the registered failure policy does not
allow it. An existing output refuses before any network access and must never be removed to
permit another write.

Then confirm the frame the lock will accept:

```powershell
@'
import json
from pathlib import Path

frame = json.loads(Path('docket/advantage/v3/sources/range-v7-enumerable-frame.json').read_text(encoding='utf-8'))
assert frame['complete'] is True
assert frame['observation_block'] == 119531513
assert frame['observation_time'] == '2026-09-02T11:59:59Z'
assert len(frame['rows']) == 1024
assert len({row['token_id'] for row in frame['rows']}) == 1024
live = [row for row in frame['rows'] if row.get('liquidity')]
print('rows', len(frame['rows']), 'non-zero liquidity', len(live),
      'unique live pools', len({row['pool_id'] for row in live if 'pool_id' in row}))
'@ | .\.venv\Scripts\python.exe -
if ($LASTEXITCODE -ne 0) { throw 'collected frame is not the registered shape' }
```

Record the printed counts. They are the only pre-capture reading of the population, and they
say nothing about which rows will be eligible: eligibility depends on the pool truth that does
not exist yet. That ordering — register the derivation, then derive it — is the property this
family exists to preserve.

## 2. Calibrate both evaluator seats — before input lock

The answer key `docket/advantage/v3/sources/range-v7-calibration-set.json` is committed with
the registration. It is a new eight-case key whose inputs are disjoint from v3-05's, so a seat
cannot answer it from memory of the earlier run. A captured response binds even when it fails;
never delete one and never ask the same seat again.

```powershell
$specPath = 'docket/advantage/v3/specs/v3-07-range-doctor.json'
$calibrationSet = 'docket/advantage/v3/sources/range-v7-calibration-set.json'
$calibrationRoot = 'docket/advantage/v3/calibration-captures/2026-09-05-range-v7'
& .\.venv\Scripts\python.exe -m docket.advantage.v3.calibration_driver $specPath $calibrationRoot --evaluator-id seat-a --session-id "range-v7-seat-a-$([guid]::NewGuid().ToString('N'))" --calibration-set $calibrationSet --seat docket.advantage.v3.seats.codex_cli:ask
if ($LASTEXITCODE -ne 0) { throw 'seat-a calibration did not capture; preserve its attempt' }
& .\.venv\Scripts\python.exe -m docket.advantage.v3.calibration_driver $specPath $calibrationRoot --evaluator-id seat-b --session-id "range-v7-seat-b-$([guid]::NewGuid().ToString('N'))" --calibration-set $calibrationSet --seat docket.advantage.v3.seats.claude_cli:ask
if ($LASTEXITCODE -ne 0) { throw 'seat-b calibration did not capture; preserve its attempt' }
```

Assemble and verify the two binding responses:

```powershell
@'
import base64
import json
from pathlib import Path
from docket.advantage.v3.calibration import assemble_evaluator_calibration, verify_calibration_capture
from docket.advantage.v3.spec import load

root = Path('.').resolve()
spec = load(root / 'docket/advantage/v3/specs/v3-07-range-doctor.json', repo_root=root)
calibration_set = (root / 'docket/advantage/v3/sources/range-v7-calibration-set.json').read_bytes()
calibration_root = root / 'docket/advantage/v3/calibration-captures/2026-09-05-range-v7'
rows = assemble_evaluator_calibration(spec, calibration_root, calibration_set)
body = {
    'calibration_set': {'body_base64': base64.b64encode(calibration_set).decode('ascii')},
    'evaluator_calibration': rows,
}
verify_calibration_capture(spec, body, calibration_root)
out = root / 'docket/advantage/v3/sources/range-v7-evaluator-calibration.json'
with out.open('x', encoding='utf-8', newline='\n') as handle:
    json.dump(rows, handle, indent=2, sort_keys=True)
    handle.write('\n')
print(out)
'@ | .\.venv\Scripts\python.exe -
if ($LASTEXITCODE -ne 0) { throw 'v3-07 calibration assembly failed; preserve both sessions' }
```

Each seat must exactly match at least seven of the eight canonical answers. The input lock,
not this stage, is what enforces that; a seat that falls short makes the lock fail and the
family cannot run.

## 3. Registered pool truth — the only time-bound stage

The tracked timer is `docket-v3-range-v7-capture.timer`. It fires at `11:50:00Z`, writes
`armed.json`, and sleeps in-process to `12:00:00Z`. There is no randomized delay.

After the owner releases the exact tested commit, verify the installed bytes and schedule:

```powershell
$releasedCommit = (& git rev-parse HEAD).Trim()
if ($LASTEXITCODE -ne 0 -or $releasedCommit -notmatch '^[0-9a-f]{40}$') {
  throw 'could not identify the released commit'
}
$unitAudit = @'
set -euo pipefail
expected_commit=$1
service=/etc/systemd/system/docket-v3-range-v7-capture.service
timer=/etc/systemd/system/docket-v3-range-v7-capture.timer
test "$(</opt/docket/RELEASE-commit.txt)" = "$expected_commit"
cmp -s "$service" /opt/docket/deploy/systemd/docket-v3-range-v7-capture.service
cmp -s "$timer" /opt/docket/deploy/systemd/docket-v3-range-v7-capture.timer
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
    (timer, "OnCalendar", "2026-09-05 11:50:00 UTC"),
    (timer, "Unit", "docket-v3-range-v7-capture.service"),
    (service, "ExecStart", "/opt/docket/.venv/bin/python -P -m docket.advantage.v3.capture v3-07-range-doctor /var/lib/docket/v3-capture/range-v3-07"),
)
for path, name, wanted in expected:
    actual = values(path, name)
    if actual != [wanted]:
        raise SystemExit(f"{path}: expected exactly one {name}={wanted!r}, got {actual!r}")
PY
systemd-analyze verify "$service" "$timer"
systemctl is-enabled docket-v3-range-v7-capture.timer >/dev/null
systemctl list-timers docket-v3-range-v7-capture.timer
'@
$unitAudit | ssh <deploy-user>@<host> "bash -s -- $releasedCommit"
if ($LASTEXITCODE -ne 0) {
  throw 'released v3-07 units or schedule do not match the tested commit'
}
```

At or after 11:50Z but before 12:00Z, the expected state is an active sleeping oneshot plus
one first-write arm record:

```powershell
ssh <deploy-user>@<host> 'set -o pipefail; systemctl is-active docket-v3-range-v7-capture.service && test -f /var/lib/docket/v3-capture/range-v3-07/armed.json && find /var/lib/docket/v3-capture/range-v3-07 -maxdepth 1 -type f -printf "%f\n" | sort'
if ($LASTEXITCODE -ne 0) { throw 'v3-07 arm check failed; only if the timer missed 11:50Z and no service or artifact exists, follow the one-start recovery below' }
```

If the timer is enabled but not yet due, do nothing. If it missed 11:50Z and no service or
artifact exists, the owner may start the tracked service once before 12:00Z:

```powershell
ssh <deploy-user>@<host> 'systemctl start --no-block docket-v3-range-v7-capture.service'
```

Do not manually start it when `armed.json`, `armed-*.json` or any `attempt-*` file exists.
After the service stops, inspect the evidence and journal without changing either:

```powershell
ssh <deploy-user>@<host> 'systemctl show docket-v3-range-v7-capture.service -p Result -p ExecMainCode -p ExecMainStatus; journalctl -u docket-v3-range-v7-capture.service --since "2026-09-05 11:45:00 UTC" --no-pager; find /var/lib/docket/v3-capture/range-v3-07 -maxdepth 1 -type f -printf "%f\n" | sort'
```

Interpret the exit and files exactly:

- `0`: captured. Require `capture-complete.json`, `capture-attempts.json`, both final raw
  bodies and the chosen attempt files.
- `1`: unexpected runtime failure; `capture-failed*.json` records it.
- `2`: protocol refusal; `capture-refused*.json` records it. A late Persistent catch-up takes
  this path before HTTP. For v3-07, any start after `12:00:05Z` is late.
- `3`: registered non-capture. `capture-attempts.json` and `capture-failed*.json` explain the
  exhausted or unusable attempts.
- `4`: the terminal condition occurred but even its evidence could not be written; preserve
  stderr and investigate the filesystem.

After any `attempt-*` evidence exists, no restart or manual rerun is permitted. If all three
attempts fail, preserve the entire directory, do not make a fourth request, and do not run
stage 4. A later capture requires a newly committed registration with new timestamps, a new
empty directory **and a newly collected frame**, because a new registration means a new
stage-one hash and therefore a different 1,024-index draw.

## 4. Copy the completed capture once

```powershell
$poolCapture = 'data/range-v7-pool-capture-20260905'
if (Test-Path -LiteralPath $poolCapture) { throw "local capture already exists: $poolCapture" }
$poolCaptureParent = Split-Path -Parent $poolCapture
if (Test-Path -LiteralPath $poolCaptureParent -PathType Leaf) {
  throw "capture parent is not a directory: $poolCaptureParent"
}
[IO.Directory]::CreateDirectory([IO.Path]::GetFullPath($poolCaptureParent)) | Out-Null
$poolCaptureStaging = "$poolCapture.staging-$([guid]::NewGuid().ToString('N'))"
scp -r <deploy-user>@<host>:/var/lib/docket/v3-capture/range-v3-07 $poolCaptureStaging
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

Only a staging directory whose copy or verification failed may be discarded. Never discard the
reserved final path or the host evidence directory.

## 5. Bind and lock

Require every input before assembly is attempted:

```powershell
$specPath = 'docket/advantage/v3/specs/v3-07-range-doctor.json'
$frame = 'docket/advantage/v3/sources/range-v7-enumerable-frame.json'
$poolCapture = 'data/range-v7-pool-capture-20260905'
$poolTruth = 'docket/advantage/v3/sources/range-v7-pool-truth.json'
$calibrationSet = 'docket/advantage/v3/sources/range-v7-calibration-set.json'
$evaluatorCalibration = 'docket/advantage/v3/sources/range-v7-evaluator-calibration.json'
$calibrationRoot = 'docket/advantage/v3/calibration-captures/2026-09-05-range-v7'

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
  throw 'could not read the v3-07 registration'
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
  if ($LASTEXITCODE -ne 0) { throw 'v3-07 assembly/input lock refused; preserve every file' }
}
```

The registered ways this refuses, each of which ends the family rather than starting a second
attempt:

- **A stratum is empty.** All three strata must hold at least one eligible position after the
  conflict and prior-exposure exclusions. Nothing substitutes a stratum, and no other frame or
  capture may be used to fill one.
- **A frame row was not derived as registered**, or the RPC call accounting does not equal what
  the registered method implies. That is a determinism defect, not a retryable error.
- **A seat missed the calibration floor.**
- **A frozen pool row contradicts its on-chain position** — token identities or fee tier
  differ.

Verify the unchanged stage-one hash and the now-runnable input before committing the frame,
pool truth, input, calibration evidence and updated spec together:

```powershell
@'
import json
from pathlib import Path
from docket.advantage.v3.spec import assert_runnable, load

root = Path('.').resolve()
spec = load(root / 'docket/advantage/v3/specs/v3-07-range-doctor.json', repo_root=root)
assert spec.stage_one_protocol_hash == '0x' + '3305b8b3dd15ba3933dedc6b50ef94c4d2ea1f1a6cb26666ba84dd4ec45e67f5'
assert len(spec.inputs_sha256) == 64
assert_runnable(spec, repo_root=root)
body = json.loads((root / spec.inputs_ref).read_text(encoding='utf-8'))
exposed = set(spec.case_selection['prior_exposure_exclusion']['token_ids'])
assert not exposed & {case['token_id'] for case in body['cases']}
print(spec.inputs_ref, spec.inputs_sha256)
print([case['case_id'] for case in body['cases']])
print('eligible positions', len(body['selection_manifest']['eligible_positions']))
'@ | .\.venv\Scripts\python.exe -
if ($LASTEXITCODE -ne 0) { throw 'locked v3-07 input did not validate' }
```

## 6. Owner-only manual-arm handover

Close Docket, every agent transcript and all Range Doctor output. Every manual primary is
completed before any agent request is sent, because an operator cannot un-see a service
answer. From the repository root, run exactly three manual slots:

```powershell
1..3 | ForEach-Object {
  .\.venv\Scripts\python.exe -m docket.advantage.v3.orchestrator `
    v3-07-range-doctor docket/advantage/v3/runs `
    --repo-root . --interactive --once
  if ($LASTEXITCODE -ne 0) {
    throw "v3-07 manual primary $_ refused; preserve the ledger and do not retry"
  }
}
```

For each reveal, submit one JSON object on one physical line. It must contain exactly the
top-level answer fields `position`, `observation`, `range`, `pool_evidence`, `rates`,
`dollars`, `action`, `coverage`, `limitations` and `sources`. Fill every field from the
revealed frozen case, including the exact token/block/range facts, bound pool evidence, rate
and dollar work, action, complete-frame coverage, registered limits and source identities.

The clock is 1,200 seconds and it never pauses. Do not prepare answers in advance and do not
paste the revealed payload as the answer. A blank, malformed, multiline, interrupted or
schema-invalid submission consumes that primary. There is one final submission per slot and no
retry or replacement. **Interrupting a claimed slot is exactly what made v3-05 unable to
pass.** Do not start a slot you cannot finish.

## 7. Run the three settled Range Doctor agent primaries

Only after all three manual primaries are terminal. Each of these three requests spends
0.50 USDT. **Get the owner's explicit approval immediately before each one.** Three primaries
is 1.5 USDT.

Range Doctor's `paid_stock` is false at registration, so `X-PAYMENT` alone is ignored and the
hire would silently run on the free allowance. The registered arm therefore sends the
owner-operated `X-Docket-Canary` header as well, which is the only path on which the payment
is verified and settled. Read the token from its private file and never print, store, copy or
paste it:

```powershell
$canaryToken = (ssh -o BatchMode=yes <deploy-user>@<host> 'cat /etc/docket/docket-canary.token').Trim()
if ($LASTEXITCODE -ne 0 -or -not $canaryToken) { throw 'could not read the canary credential' }
```

For each primary, obtain a fresh challenge and sign one exact authorization for it, exactly
as `docket/canary.py` does. A probe carrying an invalid payment plus the canary header returns
the 402 challenge without running work and without spending the free allowance — but the hire
route validates the body first and answers 422 `missing_field` before it ever reaches the
payment branch, so the probe body must satisfy `range-doctor`'s schema. Its only required
field is `wallet`:

```powershell
@'
import os

import httpx
from eth_account import Account

from docket.canary import _encoded_payment
from docket.hire.x402 import build_signed_payment

endpoint = 'https://docket.gudman.xyz/hire/range-doctor'
token = os.environ['DOCKET_CANARY_TOKEN']
account = Account.from_key(os.environ['DOCKET_CANARY_PAYMENT_KEY'])
probe = httpx.post(
    endpoint,
    json={'wallet': '0xe55816904796341bf8535e25f6c8b647927fc946'},
    headers={'X-PAYMENT': 'invalid', 'X-Docket-Canary': token},
    timeout=30,
)
if probe.status_code != 402:
    raise SystemExit(f'expected a 402 challenge, got {probe.status_code}: {probe.text[:200]}')
challenge = probe.json()
offers = challenge['accepts']
if len(offers) != 1 or challenge['resource']['url'] != endpoint:
    raise SystemExit('the challenge does not carry exactly one offer for this resource')
envelope = build_signed_payment(account, offers[0], challenge['resource'])
print(_encoded_payment(envelope))
'@ | .\.venv\Scripts\python.exe -
```

Read the probe's status before signing anything, because a status other than 402 means the
paid path is not available and a real primary sent into it would burn a slot permanently:

- **422** — the probe body does not satisfy the schema. Fix the probe, not the harness.
- **403 `canary_unauthorized`** — the canary credential was rejected, which usually means the
  API process has no token loaded from `docket.service.d/10-canary-token.conf`. Stop. No slot
  has been claimed.
- **503 `settlement_unavailable`** — the recipient or facilitator is not configured on that
  process. Stop; a primary sent now would terminate `blocked_service_contract`.
- **200** — the canary header was ignored and the hire ran on the free allowance. Stop and
  investigate before claiming a slot; the registered arm requires a settled receipt.

Supply `DOCKET_CANARY_TOKEN` and `DOCKET_CANARY_PAYMENT_KEY` from their private files for the
lifetime of that one command and clear them immediately afterwards. Never write either value
into a file, a transcript or this runbook. Sign immediately before the orchestrator command
that will use the header: `validBefore` is `maxTimeoutSeconds` after the signing instant, and
an authorization that expires in transit spends the primary without settling.

Then run one slot per command, so the operator sees every permanent outcome before claiming
the next slot:

```powershell
1..3 | ForEach-Object {
  # Owner approval for this 0.50 USDT settlement belongs here, before the command runs.
  $paymentHeader = <the freshly signed header for this primary>
  $agent = @(
    & .\.venv\Scripts\python.exe -m docket.advantage.v3.orchestrator `
      v3-07-range-doctor docket/advantage/v3/runs `
      --repo-root . --once `
      --payment-header $paymentHeader `
      --canary-header $canaryToken 2>&1
  )
  $agentExit = $LASTEXITCODE
  $agent | ForEach-Object { Write-Host $_ }
  $last = [string]@($agent)[-1]
  if ($last -match ' blocked_service_contract$') {
    throw 'blocked_service_contract is permanent for this run; preserve the ledger, do not retry, and do not score'
  }
  if ($agentExit -ne 0) {
    throw "v3-07 agent primary $_ refused; preserve the ledger and do not retry"
  }
  if ($last -notmatch ' succeeded$') {
    Write-Warning "v3-07 agent primary $_ is a permanent non-success; do not retry or replace it"
  }
}
```

Each authorization is single-use: a replayed nonce returns 409 and the primary is spent with
no result. HTTP 400, 402 or 422 becomes `blocked_service_contract`; scoring is unavailable and
the run stops with its preserved record. Any timeout, transport or other HTTP error,
interruption, empty or malformed result, invalid receipt, wrong token id/block or incomplete
answer remains a permanent terminal in the registered denominator. Never delete, edit, replay
or replace a claimed primary.

Confirm each hire actually settled. The registered cost measure says a zero-amount receipt is
published as the anomaly it would be, not recorded as the price:

```powershell
@'
import json
from pathlib import Path
from docket.advantage.v3 import runner
from docket.advantage.v3.spec import load

root = Path('.').resolve()
spec = load(root / 'docket/advantage/v3/specs/v3-07-range-doctor.json', repo_root=root)
events = runner.read_events(runner.ledger_path(spec, root / 'docket/advantage/v3/runs'))
for event in events:
    if event.get('kind') == 'attempt_terminated' and '::agent::' in str(event.get('slot')):
        print(event['slot'], event['outcome'], json.dumps(event.get('cost')))
'@ | .\.venv\Scripts\python.exe -
```

## 8. Require all six registered primaries to be terminal

Fold the ledger rather than counting only one event kind, because recovered interruptions are
also terminal. Every non-success remains part of the record.

```powershell
@'
from collections import Counter
from pathlib import Path
from docket.advantage.v3 import runner
from docket.advantage.v3.spec import load

root = Path('.').resolve()
spec = load(root / 'docket/advantage/v3/specs/v3-07-range-doctor.json', repo_root=root)
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
if ($LASTEXITCODE -ne 0) { throw 'v3-07 terminal-primary closeout failed; preserve the ledger' }
```

Do not continue until the command prints `6` and exits zero.

## 9. Export two first-write blind-evaluation sessions

Export only after all six primaries are terminal and no `blocked_service_contract` terminal
exists. Session files are exclusive first writes; an existing file refuses rather than being
overwritten.

```powershell
@'
from pathlib import Path
from docket.advantage.v3.runner import ExperimentHarness
from docket.advantage.v3.spec import load

root = Path('.').resolve()
spec = load(root / 'docket/advantage/v3/specs/v3-07-range-doctor.json', repo_root=root)
harness = ExperimentHarness(spec, root / 'docket/advantage/v3/runs', repo_root=root)
print(*harness.export_evaluation_sessions(root / 'data/range-v7-evaluation-sessions'), sep='\n')
'@ | .\.venv\Scripts\python.exe -
if ($LASTEXITCODE -ne 0) { throw 'v3-07 evaluation-session export refused; do not replace an existing session' }
```

Run seat A through the registered Codex adapter and preserve its first raw response bytes:

```powershell
@'
import json
from pathlib import Path
from docket.advantage.v3.seats.codex_cli import ask

sessions = Path('data/range-v7-evaluation-sessions')
session = next(path for path in sessions.glob('*.json') if json.loads(path.read_text(encoding='utf-8'))['evaluator_id'] == 'seat-a')
raw = ask(session.read_bytes())
if raw is None:
    raise SystemExit('seat-a returned no response; do not ask again or substitute another evaluator')
out = Path('data/range-v7-seat-a.raw.json')
with out.open('xb') as handle:
    handle.write(raw)
print(out)
'@ | .\.venv\Scripts\python.exe -
if ($LASTEXITCODE -ne 0) { throw 'seat-a first response was not preserved; stop without retry' }
```

Run seat B through the registered Claude adapter and preserve its first raw response bytes.
This adapter has a 300-second timeout and is the one that left v3-04 permanently
`complete_unscored`; run it on a day when no other family's seats are running:

```powershell
@'
import json
from pathlib import Path
from docket.advantage.v3.seats.claude_cli import ask

sessions = Path('data/range-v7-evaluation-sessions')
session = next(path for path in sessions.glob('*.json') if json.loads(path.read_text(encoding='utf-8'))['evaluator_id'] == 'seat-b')
raw = ask(session.read_bytes())
if raw is None:
    raise SystemExit('seat-b returned no response; do not ask again or substitute another evaluator')
out = Path('data/range-v7-seat-b.raw.json')
with out.open('xb') as handle:
    handle.write(raw)
print(out)
'@ | .\.venv\Scripts\python.exe -
if ($LASTEXITCODE -ne 0) { throw 'seat-b first response was not preserved; stop without retry' }
```

Each response must be only the completed `score_sheet_template` object from that seat's
session. A missing, malformed or incomplete first response leaves the family unscored. Do not
ask again, repair the response bytes or substitute another evaluator.

## 10. Import both score sheets, publish mapping and close the report

```powershell
@'
from pathlib import Path
from docket.advantage.v3.runner import ExperimentHarness
from docket.advantage.v3.spec import load

root = Path('.').resolve()
spec = load(root / 'docket/advantage/v3/specs/v3-07-range-doctor.json', repo_root=root)
harness = ExperimentHarness(spec, root / 'docket/advantage/v3/runs', repo_root=root)
for seat in ('seat-a', 'seat-b'):
    raw = (root / f'data/range-v7-{seat}.raw.json').read_bytes()
    artifact = harness.import_evaluation_submission(raw, root / 'docket/advantage/v3/sheets')
    print(artifact['evaluator_id'], artifact['raw_sheet_sha256'])
'@ | .\.venv\Scripts\python.exe -
if ($LASTEXITCODE -ne 0) { throw 'v3-07 score-sheet import failed; preserve the first raw responses and do not retry either seat' }
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
spec = load(root / 'docket/advantage/v3/specs/v3-07-range-doctor.json', repo_root=root)
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
predecessor = next(row for row in payload['families'] if row['spec_id'] == 'v3-05-range-doctor')
assert 'abandoned_by' not in predecessor
print(json.dumps({
    'state': family['state'],
    'calibration': family['calibration'],
    'run_progress': family['run_progress'],
    'quality': family['quality'],
    'speed': family['speed'],
    'costs': family['costs'],
    'falsifier_result': family['falsifier_result'],
}, indent=2, sort_keys=True))
'@ | .\.venv\Scripts\python.exe -
if ($LASTEXITCODE -ne 0) { throw 'v3-07 mapping/report closeout failed; preserve every artifact' }
```

`refuted` is an honest completed result, not a failed closeout. `not_refuted` means only that
the registered falsifier did not fire; it is not proof of the claim, and with three cases and
one non-independent human operator it is a narrow result either way. Publish whatever it
returns.

Review the exact ledger, both raw responses, the imported score-sheet artifacts, the published
mapping and the derived report before requesting owner approval for any commit or deployment.
This runbook does not authorize a commit, push, deployment, transaction or submission.
