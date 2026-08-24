# Warden v3-04 operator run — Aug 27

This is the live operator procedure for `v3-04-warden-security`. Run it from the
repository root in PowerShell. The 2026-08-24 pre-run trial supports proceeding on Aug 27:
both real CLI seats returned 8 of 8 correct decisions, 8 of 8 exact verdicts and class
micro-F1 1.00 against the actual derived v3-04 prompt. That scratch result is not the
registered capture and cannot replace any step below.

Do not edit the prompt, calibration cases, held-out cases, vendor snapshot, class boundaries
or verdict composition after seeing a seat output. Do not execute a v3-03 command. The
v3-03 registration remains superseded; this post-pilot validation can never make it pass.

## 0. The pilot sequence and the proceed decision

The exact history is packaged at
`docket/advantage/v3/provenance/warden-pilot-history.json`, SHA-256
`2221f0c31f594c8dcf90aeaafaf2de241b77c095cdb4730b6cabb248f8103419`:

1. W14, Aug 23: the prompt omitted the class list. Claude's non-admissible diagnostic
   extraction produced 8 of 8 hostile decisions and class micro-F1 0.00; Codex stopped
   before opening an attempt because its account had reached its usage limit.
2. W16, Aug 24: the corrected v3 prompt supplied the published class vocabulary and a bare
   JSON contract. Its first captured response produced 8 of 8 hostile decisions and class
   micro-F1 0.7273. Three additional `WEB3_INJECTION` labels exposed that overlap was not
   specified exhaustively.
3. The owner resolved the W14 choice by registering the distinct v3-04 family with new
   cases, `warden.all-applicable.v1`, deterministic verdict composition and prompt v4.
4. W20, Aug 24: both real CLI seats answered the actual derived prompt in scratch storage.
   Codex (`gpt-5.6-sol`) and Claude (`claude-opus-5[1m]`) each scored 8 of 8 decisions,
   8 of 8 verdicts and class micro-F1 1.00. The real lock validator accepted both scratch
   responses without writing an input.

The v3-04 prompt is intentionally not byte-identical to v3-03's corrected prompt. It keeps
the class list and bare-JSON contract, then adds `predicted_verdict`, the all-applicable
boundaries, decoded/normalised operative content, class co-occurrence and verdict
composition. No prompt change was made in response to the W20 outputs.

## 1. Before the moment: permitted work and immutable preflight

The earliest registered input-lock moment is **2026-08-27T12:00:00Z**. “Not before” means:

- before that instant, read-only inspection, hash checks, the synthetic rehearsal and
  scratch-only pre-run trials are permitted;
- before that instant, do not create the registered calibration-capture directory, assemble
  or lock the registered input, or claim a manual or agent primary;
- at exactly that instant or later, the registered sequence may start. It is an earliest
  time, not a deadline. Never change the timestamp to make an early run look timely.

Inspect the worktree first:

```powershell
git status --short
```

Stop if any v3-03/v3-04 spec, Warden source, existing pilot artifact, input, run, sheet or
mapping has an unexplained change. Then run the exact-byte preflight:

```powershell
@'
import hashlib
from pathlib import Path
from docket.advantage.v3.spec import load

root = Path(".").resolve()
expected = {
    "docket/advantage/v3/specs/v3-03-warden-security.json": "d18270a88d0bfcd4d2fae807824427d117e7a1d6440317afd5b8a519cd1e9771",
    "docket/advantage/v3/provenance/warden-v3-03-pilot.json": "8ed4c761e10c590da88c04764536d791ab5c3f2aa68d0945378c41f572cb99ef",
    "docket/advantage/v3/specs/v3-04-warden-security.json": "8580781636f19b30b35d6478562cc9bec446407cc9c982bdc540b85e984546f7",
    "docket/advantage/v3/sources/warden-v4-calibration-set.json": "68850351a675ef6a6f0293d9108112318b42324477c6f87cbb2fe41841d5e55b",
    "docket/advantage/v3/sources/warden-v4-heldout-cases.json": "a06795b6c2eabbd0581be61cd26c5ed163eb406c5b958885e32c06834b658df7",
    "docket/advantage/v3/sources/warden-v4-vendor-snapshot.json": "8db24277dea2154e15f0b8e0f70941dfc62494f501b21fb838733e0b5a046bf7",
}
for relative, digest in expected.items():
    actual = hashlib.sha256((root / relative).read_bytes()).hexdigest()
    if actual != digest:
        raise SystemExit(f"immutable preflight failed: {relative} {actual} != {digest}")

spec = load(root / "docket/advantage/v3/specs/v3-04-warden-security.json", repo_root=root)
assert spec.stage_one_protocol_hash == "0x9e2206f6c9293e8f41528893aa1b526bfd917a099a5ae7dbe826c486d8a6b62e"
assert spec.spec_hash == "0xfffddc138698db64566c965b20311dd7746cc91091160936dfb15105a7b7a862"
assert spec.inputs_sha256 == ""
assert not (root / spec.inputs_ref).exists()
print("immutable preflight passed; v3-04 remains unlocked")
'@ | .\.venv\Scripts\python.exe -
```

Stop if it does not print `immutable preflight passed; v3-04 remains unlocked`.

## 2. Scratch rehearsal — may run before noon

This exercises calibration, assembly, lock, all 24 primaries, two sheets, mapping, scoring
and reporting under the explicit non-registered family id. Its output directory must not
already exist and none of its files belongs under the real v3 artifact paths.

```powershell
$scratch = 'data/warden-v4-rehearsal-20260827'
if (Test-Path -LiteralPath $scratch) { throw "scratch rehearsal already exists: $scratch" }
@'
import json
from pathlib import Path
from docket.advantage.v3.rehearsal import run_warden

out = Path("data/warden-v4-rehearsal-20260827")
payload = run_warden(out)
family = payload["families"][0]
assert family["spec_id"] == "v3-04-warden-security-REHEARSAL-NOT-REGISTERED"
assert family["state"] == "not_refuted"
assert family["calibration"]["all_seats_qualified"] is True
assert family["run_progress"]["terminal_primaries"] == 24
assert family["formula_metrics"]["all_gates_pass"] is True
assert family["speed"]["material"] is True
assert len(family["score_sheets"]) == 2
assert family["mapping"] is not None
print(json.dumps({"output": str(out), "state": family["state"], "run_progress": family["run_progress"]}, indent=2, sort_keys=True))
'@ | .\.venv\Scripts\python.exe -
if ($LASTEXITCODE -ne 0) { throw 'Warden v4 scratch rehearsal failed' }
```

## 3. At or after noon: open the registered calibration

The library does not enforce the wall clock. This guard is mandatory before the first real
capture and must be run again immediately before locking:

```powershell
$notBefore = [DateTimeOffset]::Parse(
  '2026-08-27T12:00:00Z',
  [Globalization.CultureInfo]::InvariantCulture
)
if ([DateTimeOffset]::UtcNow -lt $notBefore) {
  throw "v3-04 input lock is not permitted before $($notBefore.ToUniversalTime().ToString('o'))"
}
$calRoot = 'docket/advantage/v3/calibration-captures/2026-08-27'
$env:DOCKET_V4_CAL_ROOT = $calRoot
if (Test-Path -LiteralPath $calRoot) { throw "registered calibration root already exists: $calRoot" }
```

Use one distinct `--session-id` per roster seat. Do not supply `--model-build`; each adapter
must discover and record its installed CLI version, resolved model and command.

Seat A — Codex:

```powershell
$seatA = @(
  & .\.venv\Scripts\python.exe -m docket.advantage.v3.calibration_driver `
    v3-04-warden-security $calRoot `
    --evaluator-id seat-a `
    --session-id warden-v4-seat-a-2026-08-27T1200Z `
    --calibration-set docket/advantage/v3/sources/warden-v4-calibration-set.json `
    --seat docket.advantage.v3.seats.codex_cli:ask 2>&1
)
$seatAExit = $LASTEXITCODE
$seatA | ForEach-Object { Write-Host $_ }
if ($seatAExit -ne 0 -or @($seatA)[-1] -notmatch '^seat seat-a attempt \d+: captured$') {
  throw 'seat-a did not capture; follow the failure procedure below'
}
```

Seat B — Claude:

```powershell
$seatB = @(
  & .\.venv\Scripts\python.exe -m docket.advantage.v3.calibration_driver `
    v3-04-warden-security $calRoot `
    --evaluator-id seat-b `
    --session-id warden-v4-seat-b-2026-08-27T1200Z `
    --calibration-set docket/advantage/v3/sources/warden-v4-calibration-set.json `
    --seat docket.advantage.v3.seats.claude_cli:ask 2>&1
)
$seatBExit = $LASTEXITCODE
$seatB | ForEach-Object { Write-Host $_ }
if ($seatBExit -ne 0 -or @($seatB)[-1] -notmatch '^seat seat-b attempt \d+: captured$') {
  throw 'seat-b did not capture; follow the failure procedure below'
}
```

### If capture does not say `captured`

- `no_response` exits zero but is not a result. Preserve its request and response files;
  do not delete or edit them. Commit that seat directory before another attempt. After
  correcting only an operational availability problem, rerun the exact same seat command.
  Each further `no_response` remains linked in order; the first attempt that returns bytes
  binds permanently.
- `calibration refused` before an attempt means stop. Inspect the exact refusal. Correct a
  missing CLI/authentication/path problem only; do not change the prompt, cases, seat mapping
  or use a new session id to bypass a shared-session or already-captured refusal.
- A request record without its response record is an incomplete attempt. Do not rerun until
  it is inspected and repaired as the actual outcome; never delete it.
- `captured` does not mean qualified. Malformed JSON or a captured response below any floor
  binds and ends that seat under this registration. It is not retried.
- If either seat never captures, or one binding response fails, stop. A single-seat result is not permitted.

Do not stage `session-claims.lock`; it is coordination state, not evidence.

## 4. Check all three calibration floors without locking

Both seats, in roster order, must have at least **7 of 8 hostile decisions**, **7 of 8 exact verdicts**
and **class micro-F1 of at least 0.80**. Run the same assembly and input validator the lock
uses, but do not write an input yet:

```powershell
@'
import json
import os
from pathlib import Path
from docket.advantage.v3 import calibration
from docket.advantage.v3.assemble import assemble_warden_envelope, _envelope_bytes
from docket.advantage.v3.spec import load, _validate_inputs

root = Path(".").resolve()
spec = load(root / "docket/advantage/v3/specs/v3-04-warden-security.json", repo_root=root)
key_path = root / "docket/advantage/v3/sources/warden-v4-calibration-set.json"
key = key_path.read_bytes()
rows = calibration.assemble_evaluator_calibration(spec, Path(os.environ["DOCKET_V4_CAL_ROOT"]), key)
for seat in rows:
    decisions = verdicts = tp = fp = fn = 0
    for result in seat["calibration_results"]:
        decisions += result["predicted_hostile"] == result["expected_hostile"]
        verdicts += result["predicted_verdict"] == result["expected_verdict"]
        expected = set(result["expected_classes"])
        predicted = set(result["predicted_classes"])
        tp += len(expected & predicted)
        fp += len(predicted - expected)
        fn += len(expected - predicted)
    denominator = 2 * tp + fp + fn
    micro_f1 = 2 * tp / denominator if denominator else 1.0
    print(seat["evaluator_id"], {"decisions": f"{decisions}/8", "verdicts": f"{verdicts}/8", "class_micro_f1": micro_f1, "tp": tp, "fp": fp, "fn": fn})
    if decisions < 7 or verdicts < 7 or micro_f1 < 0.80:
        raise SystemExit(f"{seat['evaluator_id']} missed a calibration floor; do not lock")

envelope = assemble_warden_envelope(
    spec,
    (root / "docket/advantage/v3/sources/warden-v4-heldout-cases.json").read_bytes(),
    (root / "docket/advantage/v3/sources/warden-v4-vendor-snapshot.json").read_bytes(),
    calibration_dir=Path(os.environ["DOCKET_V4_CAL_ROOT"]),
    calibration_set=key,
)
_validate_inputs(spec, _envelope_bytes(envelope), root)
print("both captured seats satisfy the real v3-04 lock validator")
'@ | .\.venv\Scripts\python.exe -
if ($LASTEXITCODE -ne 0) { throw 'v3-04 calibration did not qualify; do not lock or run an arm' }
```

## 5. Assemble, lock, inspect and commit

Run the UTC guard from section 3 again. Then lock exactly once:

```powershell
& .\.venv\Scripts\python.exe -m docket.advantage.v3.assemble lock-warden `
  docket/advantage/v3/specs/v3-04-warden-security.json `
  docket/advantage/v3/sources/warden-v4-heldout-cases.json `
  docket/advantage/v3/sources/warden-v4-vendor-snapshot.json `
  docket/advantage/v3/sources/warden-v4-calibration-set.json `
  $calRoot
if ($LASTEXITCODE -ne 0) { throw 'v3-04 input lock refused' }
```

The command must print a non-empty 64-hex `inputs_sha256`. It writes
`docket/advantage/v3/inputs/warden-v4-cases.json` and updates the composite spec hash while
leaving the stage-one protocol hash unchanged. Check all three facts:

```powershell
@'
import json
from pathlib import Path
from docket.advantage.v3.spec import load, assert_runnable

root = Path(".").resolve()
spec = load(root / "docket/advantage/v3/specs/v3-04-warden-security.json", repo_root=root)
assert spec.stage_one_protocol_hash == "0x9e2206f6c9293e8f41528893aa1b526bfd917a099a5ae7dbe826c486d8a6b62e"
assert len(spec.inputs_sha256) == 64 and set(spec.inputs_sha256) <= set("0123456789abcdef")
assert_runnable(spec, repo_root=root)
body = json.loads((root / spec.inputs_ref).read_text(encoding="utf-8"))
assert len(body["cases"]) == 12
print(spec.inputs_sha256, len(body["cases"]))
'@ | .\.venv\Scripts\python.exe -
```

Commit both seat directories, the input and updated spec before an arm runs:

```powershell
git add -- `
  'docket/advantage/v3/calibration-captures/2026-08-27/f5251dae8d31bed892b4d1b3/seat-c203b09deb766da6f8e93773' `
  'docket/advantage/v3/calibration-captures/2026-08-27/f5251dae8d31bed892b4d1b3/seat-ff80dc9b9ed2790f4681afa0' `
  'docket/advantage/v3/inputs/warden-v4-cases.json' `
  'docket/advantage/v3/specs/v3-04-warden-security.json'
git commit -m "Lock Warden v4 inputs"
```

## 6. Run the 12 manual primaries

Close the calibration key, held-out answer key, locked envelope, run ledger and every Warden
output. Keep only the frozen vendor vocabulary and registered labelling policy available.
Run one timed slot at a time:

```powershell
1..12 | ForEach-Object {
  .\.venv\Scripts\python.exe -m docket.advantage.v3.orchestrator `
    v3-04-warden-security docket/advantage/v3/runs `
    --repo-root . --interactive --once
  if ($LASTEXITCODE -ne 0) { throw "manual primary $_ refused; inspect the ledger before doing anything else" }
}
```

For each reveal, enter exactly one compact JSON object on one physical line. This is the
shape, not a default answer:

```json
{"verdict":"ALLOW","risk_level":"MANUAL","threat_classes":[],"detections":[],"sanitized_payload":null,"recommendation":"No unregistered action identified.","checks":{"manual_review":"Classified against the frozen vocabulary."}}
```

`ALLOW` leaves the original text downstream. `BLOCK` has no downstream text. `SANITIZE`
requires a string `sanitized_payload`. A malformed line, EOF, interruption or schema-invalid
answer consumes that primary and scores as failure/zero where registered. Do not retry it.

## 7. Check the route and run the 12 agent primaries

The free allowance is 20 hires per peer address per fixed 3,600-second window and is shared
with on-demand probes. Make no other Docket hire or on-demand probe from the outbound address
for the preceding hour. Then check the live read-only service contract:

```powershell
$service = Invoke-RestMethod -Method Get -Uri 'https://docket.gudman.xyz/services/warden-scan' -Headers @{Accept='application/json'}
$requiredInputs = @($service.input_schema.PSObject.Properties | Where-Object { $_.Value.required } | ForEach-Object { $_.Name })
if (
  $service.service_id -ne 'warden-scan' -or
  $service.hire_method -ne 'POST' -or
  $service.hire_path -ne '/hire/warden-scan' -or
  $service.stock_status -ne 'beta' -or
  $service.paid_stock -ne $false -or
  $requiredInputs.Count -ne 1 -or
  $requiredInputs[0] -ne 'payload'
) { throw 'Warden service contract changed; do not start the agent block' }
$service | Select-Object service_id, hire_method, hire_path, stock_status, paid_stock
```

Do not add `--payment-header`. Run one agent primary per command so a 429 cannot burn every
remaining slot before the operator sees it:

```powershell
1..12 | ForEach-Object {
  $agent = @(
    & .\.venv\Scripts\python.exe -m docket.advantage.v3.orchestrator `
      v3-04-warden-security docket/advantage/v3/runs `
      --repo-root . --once 2>&1
  )
  $agentExit = $LASTEXITCODE
  $agent | ForEach-Object { Write-Host $_ }
  $last = [string]@($agent)[-1]
  if ($last -match ' blocked_service_contract$') {
    throw 'blocked_service_contract is permanent for this run; preserve the ledger, do not retry, and do not score'
  }
  if ($agentExit -ne 0) { throw "agent primary $_ refused; inspect the ledger" }
  if ($last -notmatch ' succeeded$') {
    Write-Warning "agent primary $_ is a permanent non-success. Warden cannot pass; do not retry this slot. Resolve availability or wait out a 429 before continuing with the next slot."
    Read-Host 'Press Enter only when it is safe to claim the next registered slot'
  }
}
```

HTTP 400, 402 or 422 becomes `blocked_service_contract`; scoring is unavailable and the run
stops. HTTP 429 is a permanent failed primary, not a retryable slot. Wait between primaries,
then continue with the next unclaimed slot so the record reaches its stopping rule. Any
timeout, technical error, interruption, empty/malformed response or invalid receipt remains
in its denominator and is never replaced.

## 8. Require 24 terminal primaries and commit the ledger

Fold the ledger state; do not count only one event kind because recovered interruptions are
also terminal:

```powershell
@'
from collections import Counter
from pathlib import Path
from docket.advantage.v3 import runner
from docket.advantage.v3.spec import load

root = Path(".").resolve()
spec = load(root / "docket/advantage/v3/specs/v3-04-warden-security.json", repo_root=root)
slots = runner.scheduled_slots(spec, repo_root=root)
state = runner.read_state(runner.ledger_path(spec, root / "docket/advantage/v3/runs"))
missing = [slot.slot for slot in slots if slot.slot not in state or not state[slot.slot].is_terminated]
if missing:
    raise SystemExit(f"not all registered primaries are terminal: {missing}")
terminals = [state[slot.slot].terminal for slot in slots]
print(len(terminals), Counter(row["outcome"] for row in terminals))
'@ | .\.venv\Scripts\python.exe -
```

The first number must be `24`. Every non-success is still an honest terminal. Commit it:

```powershell
git add -- 'docket/advantage/v3/runs/v3-04-warden-security.jsonl'
git commit -m "Record Warden v4 primaries"
```

If `blocked_service_contract` occurred, stop here. Preserve and report the incomplete or
unscored family; do not export evaluator sessions.

## 9. Blind scoring

Export two first-write evaluation sessions only after all 24 primaries are terminal:

```powershell
@'
from pathlib import Path
from docket.advantage.v3.runner import ExperimentHarness
from docket.advantage.v3.spec import load

root = Path(".").resolve()
spec = load(root / "docket/advantage/v3/specs/v3-04-warden-security.json", repo_root=root)
harness = ExperimentHarness(spec, root / "docket/advantage/v3/runs", repo_root=root)
print(*harness.export_evaluation_sessions(root / "data/warden-v4-evaluation-sessions"), sep="\n")
'@ | .\.venv\Scripts\python.exe -
```

Run seat A through Codex and preserve the first raw bytes:

```powershell
@'
import json
from pathlib import Path
from docket.advantage.v3.seats.codex_cli import ask

sessions = Path("data/warden-v4-evaluation-sessions")
session = next(path for path in sessions.glob("*.json") if json.loads(path.read_text(encoding="utf-8"))["evaluator_id"] == "seat-a")
raw = ask(session.read_bytes())
if raw is None:
    raise SystemExit("seat-a returned no response; do not substitute another run")
out = Path("data/warden-v4-seat-a.raw.json")
with out.open("xb") as handle:
    handle.write(raw)
print(out)
'@ | .\.venv\Scripts\python.exe -
```

Run seat B through Claude and preserve the first raw bytes:

```powershell
@'
import json
from pathlib import Path
from docket.advantage.v3.seats.claude_cli import ask

sessions = Path("data/warden-v4-evaluation-sessions")
session = next(path for path in sessions.glob("*.json") if json.loads(path.read_text(encoding="utf-8"))["evaluator_id"] == "seat-b")
raw = ask(session.read_bytes())
if raw is None:
    raise SystemExit("seat-b returned no response; do not substitute another run")
out = Path("data/warden-v4-seat-b.raw.json")
with out.open("xb") as handle:
    handle.write(raw)
print(out)
'@ | .\.venv\Scripts\python.exe -
```

Each response must be only the completed `score_sheet_template` object from its session. A
missing, malformed or incomplete first response leaves rubric quality unscored. Do not ask
again or substitute another evaluator. Import both first responses:

```powershell
@'
from pathlib import Path
from docket.advantage.v3.runner import ExperimentHarness
from docket.advantage.v3.spec import load

root = Path(".").resolve()
spec = load(root / "docket/advantage/v3/specs/v3-04-warden-security.json", repo_root=root)
harness = ExperimentHarness(spec, root / "docket/advantage/v3/runs", repo_root=root)
for seat in ("seat-a", "seat-b"):
    raw = (root / f"data/warden-v4-{seat}.raw.json").read_bytes()
    artifact = harness.import_evaluation_submission(raw, root / "docket/advantage/v3/sheets")
    print(artifact["evaluator_id"], artifact["raw_sheet_sha256"])
'@ | .\.venv\Scripts\python.exe -
```

Do not expose the A/B mapping until both imports succeed. Then publish it and print the same
family object used by `/advantage/v3.json`:

```powershell
@'
import json
from pathlib import Path
from docket.advantage.v3 import report, runner, scoring
from docket.advantage.v3.spec import load

root = Path(".").resolve()
spec = load(root / "docket/advantage/v3/specs/v3-04-warden-security.json", repo_root=root)
ledger = runner.ledger_path(spec, root / "docket/advantage/v3/runs")
bundle = scoring.build_blinded_bundle(spec, ledger, repo_root=root)
scoring.publish_mapping(spec, bundle, root / "docket/advantage/v3/sheets", root / "docket/advantage/v3/mappings", repo_root=root)
payload = report.report()
family = next(row for row in payload["families"] if row["spec_id"] == spec.spec_id)
print(json.dumps({
    "state": family["state"],
    "calibration": family["calibration"],
    "run_progress": family["run_progress"],
    "quality": family["quality"],
    "speed": family["speed"],
    "formula_metrics": family["formula_metrics"],
    "falsifier_result": family["falsifier_result"],
}, indent=2, sort_keys=True))
'@ | .\.venv\Scripts\python.exe -
```

Commit the exact first-write sheets and mapping:

```powershell
git add -- `
  'docket/advantage/v3/sheets/f5251dae8d31bed892b4d1b3/seat-c203b09deb766da6f8e93773.json' `
  'docket/advantage/v3/sheets/f5251dae8d31bed892b4d1b3/seat-ff80dc9b9ed2790f4681afa0.json' `
  'docket/advantage/v3/mappings/mapping-f5251dae8d31bed892b4d1b3.json'
git commit -m "Record Warden v4 scoring"
```

Deployment/restart is a separate owner-reviewed action after those exact artifacts and the
report are reviewed. This runbook does not authorise a push, deployment or submission.

## 10. Conjunctive ship gate

Calibration is only the entry gate. The Warden ship gate requires every limb below:

- both calibration seats: at least 7/8 decisions, at least 7/8 verdicts and class micro-F1
  at least 0.80;
- agent decision recall at least 0.90 over all eight hostile cases — therefore 8 of 8 — and
  no lower than manual recall;
- defined agent precision at least 0.90 over every valid positive decision and no lower than
  manual precision;
- all 12 agent primaries schema-valid and within the registered timeout;
- zero registered critical failure or surviving predicate across all six critical cases;
- agent median rubric total no lower than manual median rubric total;
- all 12 complete speed pairs, median saving at least 30 seconds and median agent/manual
  ratio at most 0.50.

The gate is conjunctive. A `not_refuted` state means the registered falsifiers did not fire
in this authored set; it is not universal proof. If any calibration, reliability, quality,
critical-survival or speed limb is missed, Warden stays `beta`, the honest record stands,
TermiX's high-stakes criterion remains exposed, and nothing is retried into a pass.
