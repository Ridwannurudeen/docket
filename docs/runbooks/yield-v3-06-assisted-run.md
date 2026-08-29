# Yield v3-06 assisted successor — capture, lock and official run

This runbook applies only to `v3-06-yield-router-assisted`. It preserves
`v3-02-yield-router` and its failed manual primary as historical evidence. V3-06 is a
distinct comparison between the deployed Yield Router and a disclosed Codex-assisted
baseline; it is not a human-versus-agent experiment and it is not a retry of v3-02.

Experiment arms run on the workstation against the repository tree. The installed
package is read-only and serves the last deployed record. A new ledger becomes public
only after it is committed to the repository and that commit is redeployed.

No command in this runbook authorizes a commit, push, deployment or submission. Obtain
the owner's explicit approval before any of those actions.

## 1. Register and deploy stage one before capture

The stage-one registration must remain unlocked and must exist in deployed code before
the timer pre-arms:

```powershell
$specPath = 'docket/advantage/v3/specs/v3-06-yield-router-assisted.json'
@'
from pathlib import Path
from docket.advantage.v3.spec import load

spec = load(Path('docket/advantage/v3/specs/v3-06-yield-router-assisted.json'))
assert spec.inputs_sha256 == ''
assert spec.inputs_ref == 'docket/advantage/v3/inputs/06-yield-assisted-cases.json'
assert spec.stage_one_protocol_hash == '0x3dffb6610ac22f5e7b86d4f27e200a6168ad7ab4f91eb9a8c14d5d7ef4267350'
assert not (Path('.') / spec.inputs_ref).exists()
print('v3-06 stage one is unlocked')
'@ | .\.venv\Scripts\python.exe -
```

The deployed timer is `docket-v3-yield-v6-capture.timer`. It pre-arms at
`2026-09-03 11:50:00 UTC`; the registered observations are exactly 12:00, 12:01 and
12:02 UTC. Releases are refused during the protected capture window.

## 2. Copy and verify the future capture

After the service completes on the VPS, copy it once into a new staging directory. Do
not restart or edit the server capture.

```powershell
$captureDir = 'data/yield-v6-assisted-capture-20260903'
if (Test-Path -LiteralPath $captureDir) { throw "reserved capture path exists: $captureDir" }
$captureStaging = "$captureDir.staging-$([guid]::NewGuid().ToString('N'))"
scp -r <deploy-user>@<host>:/var/lib/docket/v3-capture/yield-v3-06 $captureStaging
if ($LASTEXITCODE -ne 0) { throw "capture copy failed: $captureStaging" }

@'
from pathlib import Path
import sys
from docket.advantage.v3.assemble import load_capture

capture = load_capture(Path(sys.argv[1]))
assert capture['captured'] is True
assert capture['pools']['sha256']
assert capture['token_list']['sha256']
print(capture['pools']['sha256'], capture['token_list']['sha256'])
'@ | .\.venv\Scripts\python.exe - $captureStaging
if ($LASTEXITCODE -ne 0) { throw 'capture digest verification failed' }
Move-Item -LiteralPath $captureStaging -Destination $captureDir
```

## 3. Capture fresh evaluator calibration sessions

Use the registered set
`docket/advantage/v3/sources/yield-v6-assisted-calibration-set.json`. Capture both
registered evaluator seats into distinct sessions beneath
`docket/advantage/v3/calibration-captures/2026-09-03-yield-v6-assisted`. A captured
response binds even when it fails; never delete it or ask the same seat again.

Assemble the two first responses into
`docket/advantage/v3/sources/yield-v6-assisted-evaluator-calibration.json` using
`docket.advantage.v3.calibration.assemble_evaluator_calibration`, exactly as the v3-02
calibration runbook does. Both seats must pass the registered threshold before input
assembly.

The concrete first-write sequence is:

    $specPath = 'docket/advantage/v3/specs/v3-06-yield-router-assisted.json'
    $calibrationSet = 'docket/advantage/v3/sources/yield-v6-assisted-calibration-set.json'
    $calibrationRoot = 'docket/advantage/v3/calibration-captures/2026-09-03-yield-v6-assisted'
    & .\.venv\Scripts\python.exe -m docket.advantage.v3.calibration_driver $specPath $calibrationRoot --evaluator-id seat-a --session-id "yield-v6-seat-a-$([guid]::NewGuid().ToString('N'))" --calibration-set $calibrationSet --seat docket.advantage.v3.seats.codex_cli:ask
    if ($LASTEXITCODE -ne 0) { throw 'seat-a calibration did not capture; preserve its attempt' }
    & .\.venv\Scripts\python.exe -m docket.advantage.v3.calibration_driver $specPath $calibrationRoot --evaluator-id seat-b --session-id "yield-v6-seat-b-$([guid]::NewGuid().ToString('N'))" --calibration-set $calibrationSet --seat docket.advantage.v3.seats.claude_cli:ask
    if ($LASTEXITCODE -ne 0) { throw 'seat-b calibration did not capture; preserve its attempt' }

Assemble and verify the two binding responses:

    @'
    import base64
    import json
    from pathlib import Path
    from docket.advantage.v3.calibration import assemble_evaluator_calibration, verify_calibration_capture
    from docket.advantage.v3.spec import load

    root = Path('.').resolve()
    spec = load(root / 'docket/advantage/v3/specs/v3-06-yield-router-assisted.json', repo_root=root)
    calibration_set = (root / 'docket/advantage/v3/sources/yield-v6-assisted-calibration-set.json').read_bytes()
    calibration_root = root / 'docket/advantage/v3/calibration-captures/2026-09-03-yield-v6-assisted'
    rows = assemble_evaluator_calibration(spec, calibration_root, calibration_set)
    body = {
        'calibration_set': {'body_base64': base64.b64encode(calibration_set).decode('ascii')},
        'evaluator_calibration': rows,
    }
    verify_calibration_capture(spec, body, calibration_root)
    out = root / 'docket/advantage/v3/sources/yield-v6-assisted-evaluator-calibration.json'
    with out.open('x', encoding='utf-8', newline='\n') as handle:
        json.dump(rows, handle, indent=2, sort_keys=True)
        handle.write('\n')
    print(out)
    '@ | .\.venv\Scripts\python.exe -
    if ($LASTEXITCODE -ne 0) { throw 'v3-06 calibration assembly failed; preserve both sessions' }

## 4. Assemble, review and lock stage two

```powershell
$specPath = 'docket/advantage/v3/specs/v3-06-yield-router-assisted.json'
$captureDir = 'data/yield-v6-assisted-capture-20260903'
$calibrationSet = 'docket/advantage/v3/sources/yield-v6-assisted-calibration-set.json'
$evaluatorCalibration = 'docket/advantage/v3/sources/yield-v6-assisted-evaluator-calibration.json'
$calibrationRoot = 'docket/advantage/v3/calibration-captures/2026-09-03-yield-v6-assisted'

& .\.venv\Scripts\python.exe -m docket.advantage.v3.assemble `
  $specPath $captureDir $calibrationSet $evaluatorCalibration $calibrationRoot
if ($LASTEXITCODE -ne 0) { throw 'v3-06 input assembly failed' }
```

Review the generated input file before locking it: five distinct cases, exact source
digests, complete truth partitions, two distinct evaluator sessions and eight submitted
calibration answers per seat. Then lock and save atomically:

```powershell
@'
from pathlib import Path
from docket.advantage.v3.spec import assert_runnable, load, lock_inputs, save

root = Path('.').resolve()
path = root / 'docket/advantage/v3/specs/v3-06-yield-router-assisted.json'
spec = load(path, repo_root=root)
locked = lock_inputs(spec, repo_root=root)
temporary = path.with_suffix('.json.locking')
temporary.write_bytes(path.read_bytes())
save(locked, temporary, repo_root=root)
temporary.replace(path)
assert_runnable(locked, repo_root=root)
print('locked', locked.inputs_sha256)
'@ | .\.venv\Scripts\python.exe -
if ($LASTEXITCODE -ne 0) { throw 'v3-06 lock/save failed; preserve all evidence' }
```

Commit and deploy the capture, calibration evidence, locked input and updated spec only
after explicit owner approval. Do not run a primary against an uncommitted or undeployed
stage-two lock.

## 5. Official Codex-assisted baseline primaries

Codex is the registered baseline operator. Each invocation first prints the unscored
synthetic readiness fixture and reads one exact JSON answer. A malformed or wrong
readiness answer writes no official event and may be retried. After readiness passes,
the harness claims one official primary, reveals its case and frozen sources, and reads
one final answer JSON line. That second answer is claim-once and has no retry.

Run this command once per baseline primary, five times total:

```powershell
& .\.venv\Scripts\python.exe -m docket.advantage.v3.orchestrator `
  v3-06-yield-router-assisted docket/advantage/v3/runs `
  --repo-root . --interactive --once
```

For each invocation, Codex must submit exactly two physical JSON lines in sequence:

1. the canonical synthetic readiness answer computed from the printed readiness fixture;
2. the official answer computed only after the official reveal appears.

The official answer contains exactly `sources`, `universe`, `rates`, `scenario`,
`decision` and `limitations`. Never paste the reveal itself as the answer, invoke the
deployed Yield Router from the assisted arm, or call the assisted arm human/manual in a
published claim. The internal ledger arm key remains `manual` only for schema
compatibility.

## 6. Deployed Yield Router primaries

Only after all five assisted-baseline primaries are terminal, run the five deployed-arm
slots in registered order:

```powershell
1..5 | ForEach-Object {
  & .\.venv\Scripts\python.exe -m docket.advantage.v3.orchestrator `
    v3-06-yield-router-assisted docket/advantage/v3/runs `
    --repo-root . --once
  if ($LASTEXITCODE -ne 0) {
    throw "Yield v3-06 deployed primary $_ refused; preserve the ledger"
  }
}
```

Publish every terminal result, including failures. Never delete, edit or replay a
claimed primary. Scoring and A/B mapping begin only after all ten registered primaries
are terminal.

## 7. Blind evaluation, mapping and report closeout

Export the two first-write evaluator sessions only after all ten primaries terminate:

    @'
    from pathlib import Path
    from docket.advantage.v3.runner import ExperimentHarness
    from docket.advantage.v3.spec import load

    root = Path('.').resolve()
    spec = load(root / 'docket/advantage/v3/specs/v3-06-yield-router-assisted.json', repo_root=root)
    harness = ExperimentHarness(spec, root / 'docket/advantage/v3/runs', repo_root=root)
    print(*harness.export_evaluation_sessions(root / 'data/yield-v6-evaluation-sessions'), sep='\n')
    '@ | .\.venv\Scripts\python.exe -

Give each session to its registered isolated evaluator and preserve that evaluator's first
raw score-sheet bytes as data/yield-v6-seat-a.raw.json and
data/yield-v6-seat-b.raw.json. A response must be only the completed
score_sheet_template object from its session. Do not rerun a malformed or incomplete first
response. Import both:

    @'
    from pathlib import Path
    from docket.advantage.v3.runner import ExperimentHarness
    from docket.advantage.v3.spec import load

    root = Path('.').resolve()
    spec = load(root / 'docket/advantage/v3/specs/v3-06-yield-router-assisted.json', repo_root=root)
    harness = ExperimentHarness(spec, root / 'docket/advantage/v3/runs', repo_root=root)
    for seat in ('seat-a', 'seat-b'):
        raw = (root / f'data/yield-v6-{seat}.raw.json').read_bytes()
        artifact = harness.import_evaluation_submission(raw, root / 'docket/advantage/v3/sheets')
        print(artifact['evaluator_id'], artifact['raw_sheet_sha256'])
    '@ | .\.venv\Scripts\python.exe -

Do not reveal the A/B mapping until both imports succeed. Then publish it and verify the
same family object served by /advantage/v3.json:

    @'
    import json
    from pathlib import Path
    from docket.advantage.v3 import report, runner, scoring
    from docket.advantage.v3.spec import load

    root = Path('.').resolve()
    spec = load(root / 'docket/advantage/v3/specs/v3-06-yield-router-assisted.json', repo_root=root)
    ledger = runner.ledger_path(spec, root / 'docket/advantage/v3/runs')
    bundle = scoring.build_blinded_bundle(spec, ledger, repo_root=root)
    scoring.publish_mapping(spec, bundle, root / 'docket/advantage/v3/sheets', root / 'docket/advantage/v3/mappings', repo_root=root)
    payload = report.report()
    family = next(row for row in payload['families'] if row['spec_id'] == spec.spec_id)
    assert family['state'] == 'complete_scored'
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

Review the exact ledger, calibration captures, score sheets, mapping and report before
requesting owner approval to commit or deploy them. This runbook does not authorize a push,
deployment or submission.
