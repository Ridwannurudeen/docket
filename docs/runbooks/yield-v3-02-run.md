# Yield v3-02 capture, calibration and input-lock run — Aug 26

This is the operator procedure for `v3-02-yield-router`. Run repository commands from the
repository root in PowerShell.

Experiment arms run on the workstation against the repository tree. The installed package is
read-only and must not be used as a ledger target. A ledger becomes visible in production only
after it is committed to the repository and that commit is redeployed.

## 0. Hard stop and immutable state

Each evaluator seat has one binding attempt. **Do not run either seat until the corrected
calibration set is merged and pushed.** Do not run either experiment arm until the input,
updated registration and calibration evidence are committed and pushed.

The real source capture already lives on the VPS at
`/var/lib/docket/v3-capture/yield`. Never restart that capture, delete it or replace any of
its evidence. Verify the still-unlocked registration:

```powershell
git status --short
@'
from pathlib import Path
from docket.advantage.v3.spec import load

root = Path('.').resolve()
spec_path = root / 'docket/advantage/v3/specs/v3-02-yield-router.json'
spec = load(spec_path, repo_root=root)
assert spec.stage_one_protocol_hash == '0x10d0fb31ea70c4bb31581952b99b6776d5f25d2c51bdf9543d47d07781266d3c'
assert spec.spec_hash == '0x3037f77abf461e4d9fffebf6156847bab2488b4d5cd683e0f37b464b4e2b173b'
assert spec.inputs_sha256 == ''
assert not (root / spec.inputs_ref).exists()
print('v3-02 remains unlocked')
'@ | .\.venv\Scripts\python.exe -
if ($LASTEXITCODE -ne 0) { throw 'v3-02 immutable preflight failed' }
```

## 1. Copy and verify the real capture

The reserved local capture path is `data/yield-v2-capture-20260826`. Copy through a unique
staging directory so a failed transfer cannot occupy the reserved path:

```powershell
$captureDir = 'data/yield-v2-capture-20260826'
if (Test-Path -LiteralPath $captureDir) { throw "reserved capture path exists: $captureDir" }
[IO.Directory]::CreateDirectory([IO.Path]::GetFullPath('data')) | Out-Null
$captureStaging = "$captureDir.staging-$([guid]::NewGuid().ToString('N'))"
scp -r root@gudman.xyz:/var/lib/docket/v3-capture/yield $captureStaging
if ($LASTEXITCODE -ne 0) {
  throw "copy failed; only failed staging path $captureStaging may be discarded"
}
@'
import sys
from pathlib import Path
from docket.advantage.v3.assemble import load_capture

capture = load_capture(Path(sys.argv[1]))
assert capture['captured'] is True
assert capture['pools']['sha256']
assert capture['token_list']['sha256']
print(capture['pools']['sha256'], capture['token_list']['sha256'])
'@ | .\.venv\Scripts\python.exe - $captureStaging
if ($LASTEXITCODE -ne 0) { throw 'copied capture failed its recorded digest checks' }
foreach ($required in @(
  "$captureStaging/capture-complete.json",
  "$captureStaging/capture-attempts.json",
  "$captureStaging/pools.raw.json",
  "$captureStaging/token-list.raw.json"
)) {
  if (-not (Test-Path -LiteralPath $required -PathType Leaf)) {
    throw "copied capture is incomplete: $required"
  }
}
[IO.Directory]::Move(
  [IO.Path]::GetFullPath($captureStaging),
  [IO.Path]::GetFullPath($captureDir)
)
```

Only a failed GUID-named staging copy may be discarded. Never discard the reserved local
path or the VPS evidence directory.

## 2. Bind the one-shot calibration

The two reserved source files and the seat-capture root are:

```powershell
$specPath = 'docket/advantage/v3/specs/v3-02-yield-router.json'
$calibrationSet = 'docket/advantage/v3/sources/yield-v2-calibration-set.json'
$evaluatorCalibration = 'docket/advantage/v3/sources/yield-v2-evaluator-calibration.json'
$calibrationRoot = 'docket/advantage/v3/calibration-captures/2026-08-26-yield-v2'
$inputPath = 'docket/advantage/v3/inputs/02-yield-cases.json'

$setSha = (Get-FileHash -Algorithm SHA256 -LiteralPath $calibrationSet).Hash.ToLowerInvariant()
if ($setSha -ne '4194cd7f5ae7b5eb6535a8a228deaf238b80ee68630bf0a18ca8bb4bb0f2c5b6') {
  throw "wrong Yield calibration set bytes: $setSha"
}
if (-not (Test-Path -LiteralPath $calibrationRoot -PathType Container)) {
  throw "seat capture root is absent: $calibrationRoot"
}
if (Test-Path -LiteralPath $evaluatorCalibration) {
  throw "first-write evaluator artifact already exists: $evaluatorCalibration"
}
```

The seat driver must have created both seats beneath `$calibrationRoot`, with distinct
sessions. A captured response binds even if it fails; never delete it or ask that seat
again. Assemble the evaluator source from those preserved responses, never by hand:

```powershell
@'
import json
import os
from pathlib import Path
from docket.advantage.v3 import calibration
from docket.advantage.v3.spec import load

root = Path('.').resolve()
spec = load(root / 'docket/advantage/v3/specs/v3-02-yield-router.json', repo_root=root)
set_bytes = (root / 'docket/advantage/v3/sources/yield-v2-calibration-set.json').read_bytes()
rows = calibration.assemble_evaluator_calibration(
    spec,
    root / 'docket/advantage/v3/calibration-captures/2026-08-26-yield-v2',
    set_bytes,
)
raw = (json.dumps(rows, indent=2, sort_keys=True) + '\n').encode('utf-8')
path = root / 'docket/advantage/v3/sources/yield-v2-evaluator-calibration.json'
with path.open('xb') as handle:
    handle.write(raw)
    handle.flush()
    os.fsync(handle.fileno())
print(path)
'@ | .\.venv\Scripts\python.exe -
if ($LASTEXITCODE -ne 0) { throw 'evaluator calibration assembly failed; preserve all captures' }
```

## 3. Assemble, review, then explicitly lock

The generic CLI takes exactly five positional artifacts:

```powershell
& .\.venv\Scripts\python.exe -m docket.advantage.v3.assemble `
  $specPath `
  $captureDir `
  $calibrationSet `
  $evaluatorCalibration `
  $calibrationRoot
if ($LASTEXITCODE -ne 0) { throw 'Yield assembly refused; preserve every artifact' }
```

Success ends with **“Review it, then lock and commit.”** The CLI does not lock or save the
registration. Review `$inputPath`, confirm five distinct cases, the exact capture digests,
both roster seats and all eight calibration results per seat, then validate the exact bytes:

```powershell
@'
from pathlib import Path
from docket.advantage.v3.spec import _validate_inputs, load

root = Path('.').resolve()
spec = load(root / 'docket/advantage/v3/specs/v3-02-yield-router.json', repo_root=root)
raw = (root / spec.inputs_ref).read_bytes()
_validate_inputs(spec, raw, root)
print(spec.inputs_ref, len(raw))
'@ | .\.venv\Scripts\python.exe -
if ($LASTEXITCODE -ne 0) { throw 'assembled Yield input did not validate; do not lock' }
```

Only after review, lock and atomically replace the saved registration:

```powershell
@'
import os
import tempfile
from pathlib import Path
from docket.advantage.v3.spec import assert_runnable, load, lock_inputs, save

root = Path('.').resolve()
spec_path = root / 'docket/advantage/v3/specs/v3-02-yield-router.json'
spec = load(spec_path, repo_root=root)
if spec.inputs_sha256:
    assert_runnable(spec, repo_root=root)
    print('already locked', spec.inputs_sha256)
    raise SystemExit(0)
locked = lock_inputs(spec, repo_root=root)
temporary_path = None
try:
    with tempfile.NamedTemporaryFile(
        dir=spec_path.parent,
        prefix=f'.{spec_path.name}.',
        suffix='.tmp',
        delete=False,
    ) as temporary:
        temporary_path = Path(temporary.name)
        temporary.write(spec_path.read_bytes())
        temporary.flush()
        os.fsync(temporary.fileno())
    save(locked, temporary_path, repo_root=root)
    temporary_path.replace(spec_path)
finally:
    if temporary_path is not None:
        temporary_path.unlink(missing_ok=True)
assert_runnable(load(spec_path, repo_root=root), repo_root=root)
print('locked', locked.inputs_sha256)
'@ | .\.venv\Scripts\python.exe -
if ($LASTEXITCODE -ne 0) { throw 'Yield lock/save failed; preserve the input and spec' }
```

Commit `$calibrationSet`, `$evaluatorCalibration`, `$calibrationRoot`, `$inputPath` and the
updated `$specPath` together. The copied `data/` directory is ignored. Push/release remains
a separate owner action; neither experiment arm runs before that release.

## 4. First-write and crash recovery

- If the VPS capture exists, never restart it. Retry only a failed copy into a fresh staging
  name; never replace the reserved local copy.
- If any seat has a captured response, it binds. Never delete its directory, edit its bytes
  or request another answer under this registration.
- If `$evaluatorCalibration` exists, do not overwrite it. Verify it against the preserved
  seat captures; different bytes are a hard stop.
- If `$inputPath` is absent and the spec is unlocked, rerun the generic assemble command.
- If `$inputPath` exists and the spec is unlocked, do not rerun assemble: validate that exact
  file, review it, then run only the lock/save block.
- If the spec is already locked, do not assemble or lock again; run `assert_runnable` and
  verify the committed digest.
- Any different pre-existing bytes, invalid capture, failed seat, or digest mismatch stops
  this registration. Preserve the evidence and recommit a new protocol rather than retrying.

No command in this runbook authorizes a push, deployment, transaction or submission.
