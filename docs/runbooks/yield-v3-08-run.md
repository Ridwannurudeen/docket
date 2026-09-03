# Yield v3-08 registration, capture and run — Sep 5-9

> v3-08 is a **newly registered family**, not a successor. It corrects no unlocked draft and
> answers no published ledger, so it carries no `protocol_correction`, `pilot_provenance` or
> `successor_provenance`. v3-02's and v3-06's registrations, inputs, ledgers and published
> states are never read, edited, relabelled or deleted by anything in this runbook. What
> v3-08 adds is the arm v3-06 does not have: v3-06 registered a disclosed Codex-assisted
> baseline and made no human-versus-agent claim, while this family puts a human operator on
> the manual arm and says so in its claim.

Run repository commands from the repository root in PowerShell, always through
`.\.venv\Scripts\python.exe`. No command in this runbook authorizes a push, deployment,
transaction or submission.

Digests below are written **without** their `0x` prefix and joined in code where a command
needs them. They are protocol hashes, but bare `0x`-plus-64-hex is also the shape of a
private key, and this repository blocks that pattern rather than asking each time which it
is.

The evidence stages are different operations and must not be reordered:

1. commit the registration — git history is the only registration witness;
2. calibrate both evaluator seats against the committed answer key;
3. capture the top-pools and token-list bytes at 12:00Z, 12:01Z or 12:02Z on 2026-09-06;
4. bind the successful capture and lock the input;
5. run three human manual primaries, then three agent primaries;
6. export, score, map and publish.

Every registered evidence path below is first-write. Do not delete, rename, truncate or
replace an artifact to make a second attempt possible.

## What is first-write and has no retry

| Artifact | Stage | If it goes wrong |
|---|---|---|
| Each seat's calibration attempt | 2 | A captured response binds even when it fails. Never ask the same seat again. |
| `/var/lib/docket/v3-capture/yield-v3-08` on the host | 3 | Three attempts only. After any `attempt-*` file exists, no restart and no manual rerun. |
| `data/yield-v8-capture-20260906` | 4 | One `Move-Item` from a verified staging copy. Only a failed staging copy may be discarded. |
| `docket/advantage/v3/inputs/08-yield-cases.json` | 4 | A byte-identical rewrite is accepted for crash recovery; different bytes refuse. |
| `inputs_sha256` in the spec | 4 | Once set, the input lock cannot be repeated. |
| Each of the six primaries | 5 | One attempt per case per arm. A blank, malformed, interrupted or schema-invalid answer consumes that primary. |
| `data/yield-v8-seat-{a,b}.raw.json` and the imported sheets | 6 | Exclusive first writes. A missing or malformed first response leaves the family unscored. |

## Schedule

| Date (UTC) | Step | Who |
|---|---|---|
| Sep 5 | Owner commits the registration. **Nothing below may run first.** | Owner |
| Sep 5 morning, or Sep 6 before 11:40 | Deploy the tested commit, outside every refusal window | Owner |
| Sep 5, or Sep 6 morning | Stage 2, both calibration seats | Operator |
| Sep 6 11:50 | `docket-v3-yield-v8-capture.timer` arms; capture at 12:00 | Timer |
| Sep 6 after 12:03:06 | Stages 3 and 4, copy, bind, lock | Operator |
| Sep 7 | Stage 5, three manual primaries by the owner | Owner |
| Sep 8 | Stage 5, three agent primaries | Operator |
| Sep 8 | Stage 6, seats, import, mapping, report | Operator |
| Sep 9 | Review before requesting any commit | Owner |

**One family per day.** Do not run v3-07's, v3-08's or v3-09's arms or evaluator seats on the
same day. The Claude seat adapter is what left v3-04 permanently `complete_unscored`, and one
family per day is the rule that came out of it. v3-07's manual primaries are scheduled for
Sep 6, so v3-08's manual primaries wait for Sep 7.

**Seat-a is unavailable until Sep 7.** The Codex adapter behind `seat-a` is at its usage limit
and cannot answer before then, and evaluator seats may be scheduled at any time after that.
That constraint has one hard consequence at stage 2: **calibration has to be captured before
the input lock**, so if seat-a cannot answer before Sep 6 the lock cannot happen and the
registered capture cannot be used. There is no lawful way to lock first and calibrate
afterwards. If seat-a has not answered by the time stage 4 would run, do not lock: preserve
the capture directory as it stands, publish the family as it is, and recommit the protocol
with new capture times before another capture is attempted. Trying it the other way round is
exactly the substitution the registration exists to prevent.

`deploy/release.sh` refuses releases in four windows: `2026-08-26T12:02:54Z` to
`2026-08-26T12:10:06Z`, `2026-09-03T11:49:54Z` to `2026-09-03T12:03:06Z`,
`2026-09-05T11:49:54Z` to `2026-09-05T12:03:06Z` and `2026-09-06T11:49:54Z` to
`2026-09-06T12:03:06Z`. The v3-08 timer therefore has to be installed either before Sep 5
11:49:54Z or in the gap between Sep 5 12:03:06Z and Sep 6 11:49:54Z.

## 0. Immutable state and preflight

The registration fixes the capture attempts at exactly `2026-09-06T12:00:00Z`,
`2026-09-06T12:01:00Z` and `2026-09-06T12:02:00Z`, three days after the registration itself,
so the rows this protocol classifies did not exist when it was fixed.

Before stage 2, require the committed registration, the unlocked input and a clean
explanation for every other change:

```powershell
git status --short
git log --oneline -1 -- docket/advantage/v3/specs/v3-08-yield-router.json
@'
from pathlib import Path
from docket.advantage.v3.spec import load

root = Path('.').resolve()
spec = load(root / 'docket/advantage/v3/specs/v3-08-yield-router.json', repo_root=root)
assert spec.stage_one_protocol_hash == '0x' + '250a7fadca72a93383b928d469e01ab54529bf52fa1e8613b0f4805d0e14ea91'
assert spec.spec_hash == '0x' + 'a52c6a8e7ee12ae863326adc8e2792899fe7a31371daf5f4f1579c33fd15aa0e'
assert spec.inputs_sha256 == ''
assert not (root / spec.inputs_ref).exists()
assert spec.protocol_correction is None
assert spec.pilot_provenance is None
assert spec.successor_provenance is None
assert spec.n_planned == 3
assert spec.arms['manual']['display_name'] == 'Human operator'
assert spec.case_selection['source_capture_attempts'][0] == '2026-09-06T12:00:00Z'
print('v3-08 remains unlocked and registered as committed')
'@ | .\.venv\Scripts\python.exe -
if ($LASTEXITCODE -ne 0) { throw 'v3-08 immutable preflight failed' }
```

`git log` must print a commit. **If it prints nothing the registration is uncommitted and
nothing below may run** — an uncommitted registration has no witness, and every later artifact
would be unprovable.

Confirm both earlier Yield families are untouched, before and after every stage that writes:

```powershell
git status --short -- docket/advantage/v3/specs/v3-02-yield-router.json docket/advantage/v3/specs/v3-06-yield-router-assisted.json docket/advantage/v3/inputs/02-yield-cases.json
```

It must print nothing.

## 1. Nothing to collect

Unlike the Range and Health families, v3-08 has no chain frame to collect. Its whole
population is the two response bodies stage 3 captures, and until that capture happens the
eligible candidate count is not knowable. That is the point of the ordering.

## 2. Calibrate both evaluator seats — before input lock

The answer key `docket/advantage/v3/sources/yield-v8-calibration-set.json` is committed with
the registration. It is a new eight-case key whose inputs are disjoint from both v3-02's and
v3-06's, so a seat cannot answer it from memory of either earlier run. A captured response
binds even when it fails; never delete one and never ask the same seat again.

```powershell
$specPath = 'docket/advantage/v3/specs/v3-08-yield-router.json'
$calibrationSet = 'docket/advantage/v3/sources/yield-v8-calibration-set.json'
$calibrationRoot = 'docket/advantage/v3/calibration-captures/2026-09-06-yield-v8'
& .\.venv\Scripts\python.exe -m docket.advantage.v3.calibration_driver $specPath $calibrationRoot --evaluator-id seat-a --session-id "yield-v8-seat-a-$([guid]::NewGuid().ToString('N'))" --calibration-set $calibrationSet --seat docket.advantage.v3.seats.codex_cli:ask
if ($LASTEXITCODE -ne 0) { throw 'seat-a calibration did not capture; preserve its attempt' }
& .\.venv\Scripts\python.exe -m docket.advantage.v3.calibration_driver $specPath $calibrationRoot --evaluator-id seat-b --session-id "yield-v8-seat-b-$([guid]::NewGuid().ToString('N'))" --calibration-set $calibrationSet --seat docket.advantage.v3.seats.claude_cli:ask
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
spec = load(root / 'docket/advantage/v3/specs/v3-08-yield-router.json', repo_root=root)
calibration_set = (root / 'docket/advantage/v3/sources/yield-v8-calibration-set.json').read_bytes()
calibration_root = root / 'docket/advantage/v3/calibration-captures/2026-09-06-yield-v8'
rows = assemble_evaluator_calibration(spec, calibration_root, calibration_set)
body = {
    'calibration_set': {'body_base64': base64.b64encode(calibration_set).decode('ascii')},
    'evaluator_calibration': rows,
}
verify_calibration_capture(spec, body, calibration_root)
out = root / 'docket/advantage/v3/sources/yield-v8-evaluator-calibration.json'
with out.open('x', encoding='utf-8', newline='\n') as handle:
    json.dump(rows, handle, indent=2, sort_keys=True)
    handle.write('\n')
print(out)
'@ | .\.venv\Scripts\python.exe -
if ($LASTEXITCODE -ne 0) { throw 'v3-08 calibration assembly failed; preserve both sessions' }
```

Each seat must exactly match at least seven of the eight canonical answers. The input lock,
not this stage, is what enforces that; a seat that falls short makes the lock fail and the
family cannot run.

## 3. Registered source capture — the only time-bound stage

The tracked timer is `docket-v3-yield-v8-capture.timer`. It fires at `11:50:00Z`, writes
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
service=/etc/systemd/system/docket-v3-yield-v8-capture.service
timer=/etc/systemd/system/docket-v3-yield-v8-capture.timer
test "$(</opt/docket/RELEASE-commit.txt)" = "$expected_commit"
cmp -s "$service" /opt/docket/deploy/systemd/docket-v3-yield-v8-capture.service
cmp -s "$timer" /opt/docket/deploy/systemd/docket-v3-yield-v8-capture.timer
grep -qx 'OnCalendar=2026-09-06 11:50:00 UTC' "$timer"
grep -qx 'Unit=docket-v3-yield-v8-capture.service' "$timer"
systemd-analyze verify "$service" "$timer"
systemctl is-enabled docket-v3-yield-v8-capture.timer >/dev/null
systemctl list-timers docket-v3-yield-v8-capture.timer
'@
$unitAudit | ssh <deploy-user>@<host> "bash -s -- $releasedCommit"
if ($LASTEXITCODE -ne 0) {
  throw 'released v3-08 units or schedule do not match the tested commit'
}
```

At or after 11:50Z but before 12:00Z, the expected state is an active sleeping oneshot plus
one first-write arm record:

```powershell
ssh <deploy-user>@<host> 'set -o pipefail; systemctl is-active docket-v3-yield-v8-capture.service && test -f /var/lib/docket/v3-capture/yield-v3-08/armed.json && find /var/lib/docket/v3-capture/yield-v3-08 -maxdepth 1 -type f -printf "%f\n" | sort'
```

If the timer is enabled but not yet due, do nothing. If it missed 11:50Z and no service or
artifact exists, the owner may start the tracked service once before 12:00Z:

```powershell
ssh <deploy-user>@<host> 'systemctl start --no-block docket-v3-yield-v8-capture.service'
```

Do not manually start it when `armed.json`, `armed-*.json` or any `attempt-*` file exists.
After the service stops, inspect the evidence and journal without changing either:

```powershell
ssh <deploy-user>@<host> 'systemctl show docket-v3-yield-v8-capture.service -p Result -p ExecMainCode -p ExecMainStatus; journalctl -u docket-v3-yield-v8-capture.service --since "2026-09-06 11:45:00 UTC" --no-pager; find /var/lib/docket/v3-capture/yield-v3-08 -maxdepth 1 -type f -printf "%f\n" | sort'
```

Interpret the exit and files exactly:

- `0`: captured. Require `capture-complete.json`, `capture-attempts.json`, both final raw
  bodies and the chosen attempt files.
- `1`: unexpected runtime failure; `capture-failed*.json` records it.
- `2`: protocol refusal; `capture-refused*.json` records it. A late Persistent catch-up takes
  this path before HTTP. For v3-08, any start after `12:00:05Z` is late.
- `3`: registered non-capture. `capture-attempts.json` and `capture-failed*.json` explain the
  exhausted or unusable attempts.
- `4`: the terminal condition occurred but even its evidence could not be written; preserve
  stderr and investigate the filesystem.

After any `attempt-*` evidence exists, no restart or manual rerun is permitted. If all three
attempts fail, preserve the entire directory, do not make a fourth request, and do not run
stage 4. A later capture requires a newly committed registration with new timestamps and a
new empty directory.

## 4. Copy, bind and lock

```powershell
$capture = 'data/yield-v8-capture-20260906'
if (Test-Path -LiteralPath $capture) { throw "local capture already exists: $capture" }
$captureStaging = "$capture.staging-$([guid]::NewGuid().ToString('N'))"
scp -r <deploy-user>@<host>:/var/lib/docket/v3-capture/yield-v3-08 $captureStaging
if ($LASTEXITCODE -ne 0) {
  throw "copy failed; only failed staging copy $captureStaging may be discarded before retry"
}
foreach ($required in @(
  "$captureStaging/capture-complete.json",
  "$captureStaging/capture-attempts.json",
  "$captureStaging/pools.raw.json",
  "$captureStaging/token-list.raw.json"
)) {
  if (-not (Test-Path -LiteralPath $required -PathType Leaf)) {
    throw "staging copy is incomplete: $required; only $captureStaging may be discarded"
  }
}
[IO.Directory]::Move(
  [IO.Path]::GetFullPath($captureStaging),
  [IO.Path]::GetFullPath($capture)
)
```

Only a staging directory whose copy or verification failed may be discarded. Then write the
input envelope. The Yield assembler takes its five arguments positionally and writes the
envelope only; the lock is the separate step below, so the envelope can be read before it is
bound.

```powershell
$specPath = 'docket/advantage/v3/specs/v3-08-yield-router.json'
$captureDir = 'data/yield-v8-capture-20260906'
$calibrationSet = 'docket/advantage/v3/sources/yield-v8-calibration-set.json'
$evaluatorCalibration = 'docket/advantage/v3/sources/yield-v8-evaluator-calibration.json'
$calibrationRoot = 'docket/advantage/v3/calibration-captures/2026-09-06-yield-v8'

& .\.venv\Scripts\python.exe -m docket.advantage.v3.assemble `
  $specPath $captureDir $calibrationSet $evaluatorCalibration $calibrationRoot
if ($LASTEXITCODE -ne 0) { throw 'v3-08 input assembly failed; preserve every file' }
```

Read the generated envelope before locking it: three distinct cases, exact source digests,
a partition that covers every captured row exactly once, two distinct evaluator sessions and
eight submitted calibration answers per seat. Then lock and save atomically:

```powershell
@'
from pathlib import Path
from docket.advantage.v3.spec import assert_runnable, load, lock_inputs, save

root = Path('.').resolve()
path = root / 'docket/advantage/v3/specs/v3-08-yield-router.json'
spec = load(path, repo_root=root)
locked = lock_inputs(spec, repo_root=root)
temporary = path.with_suffix('.json.locking')
temporary.write_bytes(path.read_bytes())
save(locked, temporary, repo_root=root)
temporary.replace(path)
assert_runnable(locked, repo_root=root)
print('locked', locked.inputs_sha256)
'@ | .\.venv\Scripts\python.exe -
if ($LASTEXITCODE -ne 0) { throw 'v3-08 input lock refused; preserve every file' }
```

The registered ways this refuses, each of which ends the family rather than starting a second
attempt:

- **Fewer than three eligible pools.** The captured universe cannot fill the registration and
  no later capture may substitute.
- **A row is missing from the partition, or a partition membership is duplicated.**
- **A seat missed the calibration floor.**
- **A snapshot observed outside its registered one-minute attempt window.**

Verify the unchanged stage-one hash and the now-runnable input before committing the capture,
input, calibration evidence and updated spec together:

```powershell
@'
import json
from pathlib import Path
from docket.advantage.v3.spec import assert_runnable, load

root = Path('.').resolve()
spec = load(root / 'docket/advantage/v3/specs/v3-08-yield-router.json', repo_root=root)
assert spec.stage_one_protocol_hash == '0x' + '250a7fadca72a93383b928d469e01ab54529bf52fa1e8613b0f4805d0e14ea91'
assert len(spec.inputs_sha256) == 64
assert_runnable(spec, repo_root=root)
body = json.loads((root / spec.inputs_ref).read_text(encoding='utf-8'))
print(spec.inputs_ref, spec.inputs_sha256)
print([case['case_id'] for case in body['cases']])
print('included', len(body['truth_manifest']['included_pool_ids']),
      'excluded', len(body['truth_manifest']['excluded']))
'@ | .\.venv\Scripts\python.exe -
if ($LASTEXITCODE -ne 0) { throw 'locked v3-08 input did not validate' }
```

## 5. The six primaries — manual first, on separate days

Close Docket, every agent transcript and all Yield Router output. Every manual primary is
completed before any agent request is sent, because an operator cannot un-see a service
answer. From the repository root, run exactly three manual slots on Sep 7:

```powershell
1..3 | ForEach-Object {
  .\.venv\Scripts\python.exe -m docket.advantage.v3.orchestrator `
    v3-08-yield-router docket/advantage/v3/runs `
    --repo-root . --interactive --once
  if ($LASTEXITCODE -ne 0) {
    throw "v3-08 manual primary $_ refused; preserve the ledger and do not retry"
  }
}
```

For each reveal, submit one JSON object on one physical line containing exactly the top-level
answer fields `sources`, `universe`, `rates`, `scenario`, `decision` and `limitations`. Fill
every field from the revealed frozen case: both source identities, the complete included and
excluded partition with each exclusion's first failed gate, every eligible net APR with its
raw fee, protocol-fee and TVL inputs, the incremental dollars per day and days to recover, the
MOVE or STAY decision with its destination, and the registered limits.

The clock is 1,200 seconds and it never pauses. Do not prepare answers in advance and do not
paste the revealed payload as the answer. A blank, malformed, multiline, interrupted or
schema-invalid submission consumes that primary. There is one final submission per slot and
no retry or replacement.

Then, on Sep 8, run the three agent primaries. Yield Router's catalogue admission exposes no
paid hire, so the harness records the receipt actually returned; a free-tier receipt records
zero rather than an invented price.

```powershell
1..3 | ForEach-Object {
  .\.venv\Scripts\python.exe -m docket.advantage.v3.orchestrator `
    v3-08-yield-router docket/advantage/v3/runs `
    --repo-root . --once
  if ($LASTEXITCODE -ne 0) {
    throw "v3-08 agent primary $_ refused; preserve the ledger and do not retry"
  }
}
```

Then require all six to be terminal before anything is exported:

```powershell
@'
from collections import Counter
from pathlib import Path
from docket.advantage.v3 import runner
from docket.advantage.v3.spec import load

root = Path('.').resolve()
spec = load(root / 'docket/advantage/v3/specs/v3-08-yield-router.json', repo_root=root)
slots = runner.scheduled_slots(spec, repo_root=root)
state = runner.read_state(runner.ledger_path(spec, root / 'docket/advantage/v3/runs'))
missing = [slot.slot for slot in slots if slot.slot not in state or not state[slot.slot].is_terminated]
if missing:
    raise SystemExit(f'not all six registered primaries are terminal: {missing}')
terminals = [state[slot.slot].terminal for slot in slots]
blocked = [row['slot'] for row in terminals if row['outcome'] == runner.BLOCKED_CONTRACT]
print(len(terminals), Counter(row['outcome'] for row in terminals))
if blocked:
    raise SystemExit(f'blocked service contract leaves the family unscored; do not export evaluator sessions: {blocked}')
'@ | .\.venv\Scripts\python.exe -
if ($LASTEXITCODE -ne 0) { throw 'v3-08 terminal-primary closeout failed; preserve the ledger' }
```

## 6. Export, score, map and publish

Export two first-write blind-evaluation sessions, run each registered seat once, and preserve
its first raw response bytes:

```powershell
@'
from pathlib import Path
from docket.advantage.v3.runner import ExperimentHarness
from docket.advantage.v3.spec import load

root = Path('.').resolve()
spec = load(root / 'docket/advantage/v3/specs/v3-08-yield-router.json', repo_root=root)
harness = ExperimentHarness(spec, root / 'docket/advantage/v3/runs', repo_root=root)
print(*harness.export_evaluation_sessions(root / 'data/yield-v8-evaluation-sessions'), sep='\n')
'@ | .\.venv\Scripts\python.exe -
if ($LASTEXITCODE -ne 0) { throw 'v3-08 evaluation-session export refused; do not replace an existing session' }
```

```powershell
foreach ($seat in @(
  @{ id = 'seat-a'; module = 'docket.advantage.v3.seats.codex_cli' },
  @{ id = 'seat-b'; module = 'docket.advantage.v3.seats.claude_cli' }
)) {
  $script = @"
import importlib, json
from pathlib import Path

ask = importlib.import_module('$($seat.module)').ask
sessions = Path('data/yield-v8-evaluation-sessions')
session = next(path for path in sessions.glob('*.json') if json.loads(path.read_text(encoding='utf-8'))['evaluator_id'] == '$($seat.id)')
raw = ask(session.read_bytes())
if raw is None:
    raise SystemExit('$($seat.id) returned no response; do not ask again or substitute another evaluator')
out = Path('data/yield-v8-$($seat.id).raw.json')
with out.open('xb') as handle:
    handle.write(raw)
print(out)
"@
  $script | .\.venv\Scripts\python.exe -
  if ($LASTEXITCODE -ne 0) { throw "$($seat.id) first response was not preserved; stop without retry" }
}
```

Each response must be only the completed `score_sheet_template` object from that seat's
session. A missing, malformed or incomplete first response leaves the family unscored. Do not
ask again, repair the response bytes or substitute another evaluator.

Import both sheets, publish the mapping and derive the same family object the JSON route
serves:

```powershell
@'
import json
from pathlib import Path
from docket.advantage.v3 import report, runner, scoring
from docket.advantage.v3.runner import ExperimentHarness
from docket.advantage.v3.spec import load

root = Path('.').resolve()
spec = load(root / 'docket/advantage/v3/specs/v3-08-yield-router.json', repo_root=root)
harness = ExperimentHarness(spec, root / 'docket/advantage/v3/runs', repo_root=root)
for seat in ('seat-a', 'seat-b'):
    raw = (root / f'data/yield-v8-{seat}.raw.json').read_bytes()
    artifact = harness.import_evaluation_submission(raw, root / 'docket/advantage/v3/sheets')
    print(artifact['evaluator_id'], artifact['raw_sheet_sha256'])
ledger = runner.ledger_path(spec, root / 'docket/advantage/v3/runs')
bundle = scoring.build_blinded_bundle(spec, ledger, repo_root=root)
scoring.publish_mapping(spec, bundle, root / 'docket/advantage/v3/sheets', root / 'docket/advantage/v3/mappings', repo_root=root)
payload = report.report()
family = next(row for row in payload['families'] if row['spec_id'] == spec.spec_id)
assert family['state'] == ('refuted' if family['falsifier_result']['refuted'] else 'not_refuted')
for prior in ('v3-02-yield-router', 'v3-06-yield-router-assisted'):
    row = next(item for item in payload['families'] if item['spec_id'] == prior)
    assert 'abandoned_by' not in row or row['abandoned_by'] != spec.spec_id
print(json.dumps({
    'state': family['state'],
    'calibration': family['calibration'],
    'run_progress': family['run_progress'],
    'quality': family['quality'],
    'speed': family['speed'],
    'costs': family['costs'],
    'formula_metrics': family['formula_metrics'],
    'falsifier_result': family['falsifier_result'],
}, indent=2, sort_keys=True))
'@ | .\.venv\Scripts\python.exe -
if ($LASTEXITCODE -ne 0) { throw 'v3-08 mapping/report closeout failed; preserve every artifact' }
```

`refuted` is an honest completed result, not a failed closeout. `not_refuted` means only that
the registered falsifier did not fire; it is not proof of the claim, and with three pools and
one non-independent human operator it is a narrow result either way. Publish whatever it
returns.

Review the exact ledger, both raw responses, the imported score-sheet artifacts, the published
mapping and the derived report before requesting owner approval for any commit or deployment.
This runbook does not authorize a commit, push, deployment, transaction or submission.
