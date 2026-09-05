# Health v3-09 registration, frame collection and run — Sep 5-9

> v3-09 is a **newly registered family**, not a successor. It corrects no unlocked draft and
> answers no published ledger, so it carries no `protocol_correction`, `pilot_provenance` or
> `successor_provenance`, and no earlier family's published state is changed by it.
>
> It is also the first family in the Health Factor category, and the category name is the
> exact place a reader would assume a published figure exists. **Venus publishes no health
> factor.** Its comptroller answers `(error, liquidity, shortfall)` in 1e18-scaled USD and
> nothing else about an account's condition. Everything else in this family is derived here,
> by the formula `docket/agents/venus/guard.py` applies, and is labelled as derived.

Run repository commands from the repository root in PowerShell, always through
`.\.venv\Scripts\python.exe`. No command in this runbook authorizes a push, deployment,
transaction or submission.

Digests below are written **without** their `0x` prefix and joined in code where a command
needs them. They are block and protocol hashes, but bare `0x`-plus-64-hex is also the shape of
a private key, and this repository blocks that pattern rather than asking each time which it
is.

The evidence stages are different operations and must not be reordered:

1. commit the registration — git history is the only registration witness;
2. collect the block-hash-pinned Venus borrower frame;
3. calibrate both evaluator seats against the committed answer key;
4. bind the frame and lock the input;
5. run three human manual primaries, then three agent primaries;
6. export, score, map and publish.

Every registered evidence path below is first-write. Do not delete, rename, truncate or
replace an artifact to make a second attempt possible.

## What is first-write and has no retry

| Artifact | Stage | If it goes wrong |
|---|---|---|
| `sources/health-v9-enumerable-frame.json` | 2 | Refuses if it exists. Rerun the exact full collector only while the file is still absent. |
| Each seat's calibration attempt | 3 | A captured response binds even when it fails. Never ask the same seat again. |
| `docket/advantage/v3/inputs/09-health-accounts.json` | 4 | A byte-identical rewrite is accepted for crash recovery; different bytes refuse. |
| `inputs_sha256` in the spec | 4 | Once set, the input lock cannot be repeated. |
| Each of the six primaries | 5 | One attempt per case per arm. A blank, malformed, interrupted or schema-invalid answer consumes that primary. |
| `data/health-v9-seat-{a,b}.raw.json` and the imported sheets | 6 | Exclusive first writes. A missing or malformed first response leaves the family unscored. |

## Schedule

| Date (UTC) | Step | Who |
|---|---|---|
| Sep 5 | Owner commits the registration. **Nothing below may run first.** | Owner |
| Any time after the registration commit | Stage 2, the frame collection | Operator |
| Sep 9, or the first free day | Stage 3, both calibration seats | Operator |
| After stage 3 | Stage 4, bind and lock | Operator |
| Sep 9 | Stage 5, three manual primaries by the owner, then three agent primaries | Owner |
| Sep 9 | Stage 6, seats, import, mapping, report | Operator |
| After stage 6 | Review before requesting any commit | Owner |

**Stage 2 is not time-bound.** It reads a past block by block hash, and the enumeration
window, chunk size, conflict list, strata and selection hash were all fixed by the stage-one
hash that is already committed. Collecting the frame therefore buys no foreknowledge: which
accounts it names and what status each one has are unknown until it runs.

**One family per day.** Do not run v3-07's, v3-08's or v3-09's arms or evaluator seats on the
same day. **Calibration seats are seats.** The rule is about the adapters, not about which stage
happens to be running: a calibration seat and a scoring seat go through the same
`docket.advantage.v3.seats.*` adapter, and the Claude one is what returned no first response
and left v3-04 permanently `complete_unscored`. Two families' seats on one day is the
condition that produced that outcome, whichever stage each family is at. A capture is neither
an arm nor a seat and does not compete for anything, so a timer may fire on a day another
family owns.

v3-07 needs Sep 7 for its calibration, lock, primaries and scoring seats. v3-08 then takes
Sep 8 for the same complete sequence, so v3-09's seats and primaries wait for Sep 9.

Every family owns whole days, and both kinds of evaluator seat count:

`v3-07` owns Sep 7; `v3-08` owns Sep 8; `v3-09` may own Sep 9.

| Day (UTC) | Family that owns the adapters | What may also happen |
|---|---|---|
| Sep 5 | No family uses an adapter | v3-07's capture and verified copy |
| Sep 6 | No family uses an adapter | v3-08's capture and verified copy |
| Sep 7 | v3-07 calibration, lock, primaries and scoring seats | — |
| Sep 8 | v3-08 calibration, lock, primaries and scoring seats | — |
| Sep 9 | v3-09 seats, lock and primaries, if there is room | — |

**Seat-a is unavailable until Sep 7.** The Codex adapter behind `seat-a` is at its usage limit
and cannot answer before then, and evaluator seats may be scheduled at any time after that.
Stage 3 therefore cannot start before Sep 7, and because the input envelope has to carry both
seats' eight responses, stage 4 waits on stage 3. Nothing in this family is on a clock that a
delay can spoil: unlike v3-08 there is no registered capture moment here, so stages 3 to 6 may
move to whichever day both seats can answer.

**This family is the one with room to slip, and it should be the one that slips.** The table
above leaves Sep 9 — the submission day — as the first free day for v3-09. If Sep 9 is too
full, the honest outcome is
to leave v3-09 `registered_waiting_for_inputs` with its frame collected and committed. That is
a published state, not a failure: the registration, the frame and the answer key stand on their
own, and a reader can check every one of them without a single arm having run. Do not compress
two families' evaluator seats into one day to avoid it — that is precisely the shortcut that
left v3-04 permanently `complete_unscored`.

## 0. Immutable state and preflight

The registration pins block `119627412`, block hash
`bb5a6f67cb1e7ea06ec8472187dc8ee844ee9709d7a6d05142bea2a5b55ff78e`, observed at
`2026-09-02T23:59:59Z`. That block was chosen by a public rule — the highest BSC block whose
header timestamp is strictly earlier than `2026-09-03T00:00:00Z` — and its number, hash and
timestamp read identically from the three independent public BSC endpoints the registration
names, so a reader can re-derive the pin without trusting the operator.

```powershell
git status --short
git log --oneline -1 -- docket/advantage/v3/specs/v3-09-health-guard.json
@'
from pathlib import Path
from web3 import Web3
from docket.advantage.v3.spec import load

root = Path('.').resolve()
spec = load(root / 'docket/advantage/v3/specs/v3-09-health-guard.json', repo_root=root)
assert spec.stage_one_protocol_hash == '0x' + '5c5dc57de1e640d0c79d017e3c5d5dafdbe3ee1057b746ae3bf9940c177bf9f6'
assert spec.spec_hash == '0x' + 'a0dfeb40bfcbe9a8747f70fe830cda12b91f825d7886dfb0889d7e5c264b1815'
assert spec.inputs_sha256 == ''
assert not (root / spec.inputs_ref).exists()
assert spec.protocol_correction is None
assert spec.pilot_provenance is None
assert spec.successor_provenance is None
frame = spec.case_selection['frame_definition']
assert frame['observation_block'] == 119627412
assert frame['observation_block_hash'] == '0x' + 'bb5a6f67cb1e7ea06ec8472187dc8ee844ee9709d7a6d05142bea2a5b55ff78e'
assert frame['observation_time'] == '2026-09-02T23:59:59Z'
assert frame['borrow_topic'] == '0x' + Web3.keccak(text=frame['borrow_event']).hex()
assert frame['enumeration_to_block'] - frame['enumeration_from_block'] + 1 == 200000
print('v3-09 remains unlocked and registered as committed')
'@ | .\.venv\Scripts\python.exe -
if ($LASTEXITCODE -ne 0) { throw 'v3-09 immutable preflight failed' }
```

`git log` must print a commit. **If it prints nothing the registration is uncommitted and
nothing below may run** — an uncommitted registration has no witness, and every later artifact
would be unprovable.

Re-derive the block pin from two of the registered public endpoints before trusting it. This
is read-only and spends nothing:

```powershell
@'
import json
import urllib.request
from pathlib import Path
from docket.advantage.v3.spec import load

root = Path('.').resolve()
spec = load(root / 'docket/advantage/v3/specs/v3-09-health-guard.json', repo_root=root)
frame = spec.case_selection['frame_definition']

def header(url, number):
    body = json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': 'eth_getBlockByNumber',
                       'params': [hex(number), False]}).encode()
    request = urllib.request.Request(url, data=body,
                                     headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(request, timeout=30) as handle:
        return json.load(handle)['result']

for endpoint in frame['block_pin_endpoints']:
    block = header(endpoint, frame['observation_block'])
    successor = header(endpoint, frame['observation_block'] + 1)
    assert block['hash'].lower() == frame['observation_block_hash'], endpoint
    assert int(block['timestamp'], 16) == 1788393599, endpoint
    assert int(successor['timestamp'], 16) >= 1788393600, endpoint
    print(endpoint, 'agrees')
'@ | .\.venv\Scripts\python.exe -
```

An endpoint that refuses the read is not a failure of the pin; two endpoints that disagree
about the hash are, and nothing below may run until that is explained.

## 1. Immutable predecessors

Confirm every earlier family is untouched, before and after every stage that writes:

```powershell
git status --short -- docket/advantage/v3/specs docket/advantage/v3/inputs docket/advantage/v3/sources
```

Only the v3-09 artifacts this runbook creates may appear.

## 2. Collect the pinned Venus borrower frame — permitted after the registration commit

The collector has one endpoint, one attempt per JSON-RPC request and no fallback. It reads
the `Borrow` logs of the two registered vTokens over the registered 200,000-block window in
registered 2,000-block chunks, takes the distinct borrower addresses, drops the registered
experiment-party wallets **before any balance is read**, and then reads every remaining
account's entered markets, comptroller liquidity, per-market snapshot, collateral factor and
oracle price once at the pinned block hash. The two vTokens bound where a borrower is found,
not which markets an account may have entered: every entered market is read, because the
cross-check against Venus's own liquidity figure is only meaningful over the same set.

Run it once to the reserved repository source path; assembly refuses a frame outside the
repository. Load the endpoint without printing it:

```powershell
$frame = 'docket/advantage/v3/sources/health-v9-enumerable-frame.json'
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
  & .\.venv\Scripts\python.exe -m docket.advantage.v3.venus_capture `
    v3-09-health-guard $frame
  $frameExit = $LASTEXITCODE
} finally {
  Remove-Item Env:DOCKET_ARCHIVE_RPC -ErrorAction SilentlyContinue
}
if ($frameExit -ne 0) { throw "Venus frame capture refused with exit $frameExit; stop" }
```

Success prints `captured <n> accounts from <m> Borrow logs at block 119627412 with <k> read
calls`. Exit `2` with stderr beginning `venus capture refused:` is a protocol refusal;
preserve the exact error.

Two substantive risks this stage carries:

- **Archive depth and `eth_getLogs` support.** The collector reads state by block hash with
  `requireCanonical: true` and asks for 100 log windows. A head behind the registered block, a
  pruned-state error, a missing trie node or an endpoint that caps log ranges below 2,000
  blocks all surface here as a refusal with nothing written. If the frame file is still
  absent, wait for the **same** configured endpoint to recover and rerun the exact full
  collector command. Never retry a single call and never substitute an endpoint: either would
  make the frame a mixture of two sources, and the registered failure policy does not allow
  it.
- **An empty stratum.** All three strata — `shortfall`, `borrowing_with_headroom` and
  `supplied_no_borrow` — must hold at least one account. `shortfall` is the one at risk: an
  account Venus reports as liquidatable at that exact block is uncommon, and 200,000 blocks is
  roughly 42 hours of borrowers. If a stratum is empty, the input lock fails and this
  protocol must be **recommitted with a new window** before another frame is collected. No
  later block and no substitute frame may fill the gap, and no other stratum may stand in.

Then confirm the frame the lock will accept:

```powershell
@'
import json
from collections import Counter
from pathlib import Path

frame = json.loads(Path('docket/advantage/v3/sources/health-v9-enumerable-frame.json').read_text(encoding='utf-8'))
assert frame['complete'] is True
assert frame['observation_block'] == 119627412
assert frame['observation_time'] == '2026-09-02T23:59:59Z'
statuses = Counter(row['status'] for row in frame['accounts'])
print('accounts', len(frame['accounts']), 'borrow logs', frame['borrow_log_count'])
print('conflict exclusions', frame['conflict_exclusions'])
print('statuses', dict(sorted(statuses.items())))
for stratum in ('shortfall', 'borrowing_with_headroom', 'supplied_no_borrow'):
    if not statuses.get(stratum):
        raise SystemExit(f'stratum {stratum!r} is empty; the protocol must be recommitted')
'@ | .\.venv\Scripts\python.exe -
if ($LASTEXITCODE -ne 0) { throw 'collected frame cannot fill the registered strata' }
```

Record the printed counts. They are the whole population this family draws from, and the
registration is what fixed how they were found.

## 3. Calibrate both evaluator seats — before input lock

The answer key `docket/advantage/v3/sources/health-v9-calibration-set.json` is committed with
the registration. Its eight cases cover a shortfall, a borrowing account with headroom, and
states that have no ratio at all, and the lock recomputes every expected figure from the
registered formula. A captured response binds even when it fails; never delete one and never
ask the same seat again.

```powershell
$specPath = 'docket/advantage/v3/specs/v3-09-health-guard.json'
$calibrationSet = 'docket/advantage/v3/sources/health-v9-calibration-set.json'
$calibrationRoot = 'docket/advantage/v3/calibration-captures/2026-09-09-health-v9'
& .\.venv\Scripts\python.exe -m docket.advantage.v3.calibration_driver $specPath $calibrationRoot --evaluator-id seat-a --session-id "health-v9-seat-a-$([guid]::NewGuid().ToString('N'))" --calibration-set $calibrationSet --seat docket.advantage.v3.seats.codex_cli:ask
if ($LASTEXITCODE -ne 0) { throw 'seat-a calibration did not capture; preserve its attempt' }
& .\.venv\Scripts\python.exe -m docket.advantage.v3.calibration_driver $specPath $calibrationRoot --evaluator-id seat-b --session-id "health-v9-seat-b-$([guid]::NewGuid().ToString('N'))" --calibration-set $calibrationSet --seat docket.advantage.v3.seats.claude_cli:ask
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
spec = load(root / 'docket/advantage/v3/specs/v3-09-health-guard.json', repo_root=root)
calibration_set = (root / 'docket/advantage/v3/sources/health-v9-calibration-set.json').read_bytes()
calibration_root = root / 'docket/advantage/v3/calibration-captures/2026-09-09-health-v9'
rows = assemble_evaluator_calibration(spec, calibration_root, calibration_set)
body = {
    'calibration_set': {'body_base64': base64.b64encode(calibration_set).decode('ascii')},
    'evaluator_calibration': rows,
}
verify_calibration_capture(spec, body, calibration_root)
out = root / 'docket/advantage/v3/sources/health-v9-evaluator-calibration.json'
with out.open('x', encoding='utf-8', newline='\n') as handle:
    json.dump(rows, handle, indent=2, sort_keys=True)
    handle.write('\n')
print(out)
'@ | .\.venv\Scripts\python.exe -
if ($LASTEXITCODE -ne 0) { throw 'v3-09 calibration assembly failed; preserve both sessions' }
```

Each seat must exactly match at least seven of the eight canonical answers. The input lock,
not this stage, is what enforces that.

## 4. Bind the frame and lock

```powershell
& .\.venv\Scripts\python.exe -m docket.advantage.v3.assemble lock-health `
  docket/advantage/v3/specs/v3-09-health-guard.json `
  docket/advantage/v3/sources/health-v9-enumerable-frame.json `
  docket/advantage/v3/sources/health-v9-calibration-set.json `
  docket/advantage/v3/sources/health-v9-evaluator-calibration.json `
  docket/advantage/v3/calibration-captures/2026-09-09-health-v9
if ($LASTEXITCODE -ne 0) { throw 'v3-09 assembly/input lock refused; preserve every file' }
```

The registered ways this refuses, each of which ends the family rather than starting a second
attempt:

- **A stratum is empty.** Nothing substitutes a stratum, and no other frame may fill one.
- **A frame row's derived block contradicts the guard formula applied to the raw figures
  beside it.** That is a determinism defect, not a retryable error.
- **A market row does not follow `getAssetsIn` exactly once each**, or an account entered
  neither registered enumeration market, so the Borrow logs could not have named it.
- **An experiment-party wallet reached the frame.** Conflicts are removed before any account
  state is read, not scored afterwards.
- **A seat missed the calibration floor.**

Verify the unchanged stage-one hash and the now-runnable input before committing the frame,
input, calibration evidence and updated spec together:

```powershell
@'
import json
from pathlib import Path
from docket.advantage.v3.spec import assert_runnable, load

root = Path('.').resolve()
spec = load(root / 'docket/advantage/v3/specs/v3-09-health-guard.json', repo_root=root)
assert spec.stage_one_protocol_hash == '0x' + '5c5dc57de1e640d0c79d017e3c5d5dafdbe3ee1057b746ae3bf9940c177bf9f6'
assert len(spec.inputs_sha256) == 64
assert_runnable(spec, repo_root=root)
body = json.loads((root / spec.inputs_ref).read_text(encoding='utf-8'))
print(spec.inputs_ref, spec.inputs_sha256)
print([case['case_id'] for case in body['cases']])
print('eligible accounts', len(body['selection_manifest']['eligible_accounts']))
print('conflict exclusions', body['selection_manifest']['conflict_exclusions'])
'@ | .\.venv\Scripts\python.exe -
if ($LASTEXITCODE -ne 0) { throw 'locked v3-09 input did not validate' }
```

## 5. The six primaries — manual first

Close Docket, every agent transcript and all Health Guard output. Every manual primary is
completed before any agent request is sent, because an operator cannot un-see a service
answer. From the repository root, run exactly three manual slots:

```powershell
1..3 | ForEach-Object {
  .\.venv\Scripts\python.exe -m docket.advantage.v3.orchestrator `
    v3-09-health-guard docket/advantage/v3/runs `
    --repo-root . --interactive --once
  if ($LASTEXITCODE -ne 0) {
    throw "v3-09 manual primary $_ refused; preserve the ledger and do not retry"
  }
}
```

Each reveal hands over the account's own pinned frame rows with the digest they were locked
under, and withholds the derived block. Submit one JSON object on one physical line containing
exactly the top-level answer fields `account`, `observation`, `status`, `venus`,
`derived_ratio`, `cross_check`, `markets` and `limitations`. Repeat Venus's liquidity and
shortfall verbatim with the call and scale that produced them, derive the collateral ratio in
the 1e18 scale by truncating integer division and show every per-market input, cross-check the
derived headroom against Venus's own and print the exact difference, classify the status, and
state the registered limits — Venus publishes no health factor, the rows are the entered
markets only, minted VAI is a debt this derivation does not count, and every figure describes
one pinned block.

The clock is 1,200 seconds and it never pauses. A blank, malformed, multiline, interrupted or
schema-invalid submission consumes that primary. There is one final submission per slot and no
retry or replacement.

Then run the three agent primaries:

```powershell
1..3 | ForEach-Object {
  .\.venv\Scripts\python.exe -m docket.advantage.v3.orchestrator `
    v3-09-health-guard docket/advantage/v3/runs `
    --repo-root . --once
  if ($LASTEXITCODE -ne 0) {
    throw "v3-09 agent primary $_ refused; preserve the ledger and do not retry"
  }
}
```

**Expect the agent arm to block.** At registration the deployed Health Guard reads Venus at
its own head and accepts no observation block, so a response describing the frozen account at
a later block does not answer the registered question. `orchestrator.hire_agent` records that
as `blocked_service_contract`: it is published exactly as it happened, it is **not** a rubric
zero, and the family remains `complete_unscored` rather than recording a task loss that did
not occur. That is the registered outcome, not a defect in this runbook. If the deployed
endpoint gains a pinned-block read before these primaries run, that is visibly a change to the
service and not a change to this protocol.

Require all six to be terminal, and read what the agent arm actually did:

```powershell
@'
from collections import Counter
from pathlib import Path
from docket.advantage.v3 import runner
from docket.advantage.v3.spec import load

root = Path('.').resolve()
spec = load(root / 'docket/advantage/v3/specs/v3-09-health-guard.json', repo_root=root)
slots = runner.scheduled_slots(spec, repo_root=root)
state = runner.read_state(runner.ledger_path(spec, root / 'docket/advantage/v3/runs'))
missing = [slot.slot for slot in slots if slot.slot not in state or not state[slot.slot].is_terminated]
if missing:
    raise SystemExit(f'not all six registered primaries are terminal: {missing}')
terminals = [state[slot.slot].terminal for slot in slots]
blocked = [row['slot'] for row in terminals if row['outcome'] == runner.BLOCKED_CONTRACT]
print(len(terminals), Counter(row['outcome'] for row in terminals))
if blocked:
    print('blocked service contract; the family stays unscored and no seat is exported:')
    for slot in blocked:
        print(' ', slot)
'@ | .\.venv\Scripts\python.exe -
if ($LASTEXITCODE -ne 0) { throw 'v3-09 terminal-primary closeout failed; preserve the ledger' }
```

If any agent primary is `blocked_service_contract`, **stop here**. Do not export evaluator
sessions, do not run a seat, and do not publish a mapping: the registered agent arm could not
be run, so there is nothing to score. Publish the report as it stands, which will show
`complete_unscored` with `unscored_reason` `blocked_service_contract`.

## 6. Export, score, map and publish — only if nothing blocked

```powershell
@'
from pathlib import Path
from docket.advantage.v3.runner import ExperimentHarness
from docket.advantage.v3.spec import load

root = Path('.').resolve()
spec = load(root / 'docket/advantage/v3/specs/v3-09-health-guard.json', repo_root=root)
harness = ExperimentHarness(spec, root / 'docket/advantage/v3/runs', repo_root=root)
print(*harness.export_evaluation_sessions(root / 'data/health-v9-evaluation-sessions'), sep='\n')
'@ | .\.venv\Scripts\python.exe -
if ($LASTEXITCODE -ne 0) { throw 'v3-09 evaluation-session export refused; do not replace an existing session' }
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
sessions = Path('data/health-v9-evaluation-sessions')
session = next(path for path in sessions.glob('*.json') if json.loads(path.read_text(encoding='utf-8'))['evaluator_id'] == '$($seat.id)')
raw = ask(session.read_bytes())
if raw is None:
    raise SystemExit('$($seat.id) returned no response; do not ask again or substitute another evaluator')
out = Path('data/health-v9-$($seat.id).raw.json')
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

```powershell
@'
import json
from pathlib import Path
from docket.advantage.v3 import report, runner, scoring
from docket.advantage.v3.runner import ExperimentHarness
from docket.advantage.v3.spec import load

root = Path('.').resolve()
spec = load(root / 'docket/advantage/v3/specs/v3-09-health-guard.json', repo_root=root)
harness = ExperimentHarness(spec, root / 'docket/advantage/v3/runs', repo_root=root)
for seat in ('seat-a', 'seat-b'):
    raw = (root / f'data/health-v9-{seat}.raw.json').read_bytes()
    artifact = harness.import_evaluation_submission(raw, root / 'docket/advantage/v3/sheets')
    print(artifact['evaluator_id'], artifact['raw_sheet_sha256'])
ledger = runner.ledger_path(spec, root / 'docket/advantage/v3/runs')
bundle = scoring.build_blinded_bundle(spec, ledger, repo_root=root)
scoring.publish_mapping(spec, bundle, root / 'docket/advantage/v3/sheets', root / 'docket/advantage/v3/mappings', repo_root=root)
payload = report.report()
family = next(row for row in payload['families'] if row['spec_id'] == spec.spec_id)
assert family['state'] == ('refuted' if family['falsifier_result']['refuted'] else 'not_refuted')
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
if ($LASTEXITCODE -ne 0) { throw 'v3-09 mapping/report closeout failed; preserve every artifact' }
```

`refuted` is an honest completed result, not a failed closeout. `not_refuted` means only that
the registered falsifier did not fire; it is not proof of the claim, and with three accounts at
one block and one non-independent human operator it is a narrow result either way. Publish
whatever it returns.

Review the exact frame, ledger, both raw responses, the imported score-sheet artifacts, the
published mapping and the derived report before requesting owner approval for any commit or
deployment. This runbook does not authorize a commit, push, deployment, transaction or
submission.
