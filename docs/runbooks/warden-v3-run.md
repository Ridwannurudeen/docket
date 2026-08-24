# Warden v3-03 run — superseded operator record

> **STOP: do not execute this runbook.** `v3-03-warden-security` was superseded before
> input lock by `v3-04-warden-security` after the disclosed W16 pilot exposed an ambiguous
> overlap rule. The commands below are retained only to explain the abandoned protocol.
> They must not lock v3-03 inputs or consume any arm. A real v3-04 calibration, input lock,
> or arm run is a separate owner-scheduled action after its registered not-before moment.

The permitted machinery check is the scratch-only Warden rehearsal:

```powershell
$scratch = Join-Path $env:TEMP "docket-warden-v4-rehearsal-20260824"
.\.venv\Scripts\python.exe -c "from pathlib import Path; from docket.advantage.v3.rehearsal import run_warden; run_warden(Path(r'$scratch'))"
```

It uses `v3-04-warden-security-REHEARSAL-NOT-REGISTERED` and cannot count as validation.

The superseded sequence was written for `v3-03-warden-security`. It assumed execution from the repository
root in PowerShell with `build/w11-warden-readiness` integrated. Do not edit
`docket/advantage/v3/specs/v3-03-warden-security.json` by hand. Its registered stage-one
protocol hash is frozen; the lock command is the only permitted operation that fills
`inputs_sha256` and recomputes the composite `spec_hash`.

## 0. Stop conditions and dress rehearsal

Confirm the frozen registration still loads and still has no input lock:

```powershell
.\.venv\Scripts\python.exe -c "from pathlib import Path; from docket.advantage.v3.spec import load; p=Path('docket/advantage/v3/specs/v3-03-warden-security.json'); s=load(p); print(s.stage_one_protocol_hash, repr(s.inputs_sha256), s.spec_hash)"
```

Expected stage-one protocol hash:
`0xcd4c698f55c316fdedaa2eb52d80091c3a08d004175d7d156527f224c4e941eb`.
Before the real lock, `inputs_sha256` must print as `''`. Stop if either fact differs.

Run the entire production path once against the isolated throwaway family. The output
directory must not exist; the command refuses to replace rehearsal evidence.

```powershell
.\.venv\Scripts\python.exe -m docket.advantage.v3.rehearsal data/warden-v3-rehearsal-2026-08-25
```

The command must end with `rehearsal complete:`. Its
`data/warden-v3-rehearsal-2026-08-25/advantage-v3.json` must show the sole family as
`not_refuted`, a non-empty `inputs_sha256`, 10 of 10 terminal primaries, two score sheets,
a published mapping, and `speed.material: true`. This fixture is named
`v3-02-yield-router-REHEARSAL-NOT-REGISTERED`; it is not registration evidence and none of
its files belongs under the real v3 artifact directories.

## 1. Capture the two calibration seats

Use a distinct session id for each seat. These commands derive `model_build` from the
installed CLI before opening the request record. They write the exact prompt and untouched
response bytes below
`docket/advantage/v3/calibration-captures/2026-08-25/v3-03-warden-security/seat-*/`.

Seat A, Codex:

```powershell
.\.venv\Scripts\python.exe -m docket.advantage.v3.calibration_driver v3-03-warden-security docket/advantage/v3/calibration-captures/2026-08-25 --evaluator-id seat-a --session-id warden-seat-a-2026-08-25T1200Z --calibration-set docket/advantage/v3/sources/warden-calibration-set.json --seat docket.advantage.v3.seats.codex_cli:ask
```

Seat B, Claude:

```powershell
.\.venv\Scripts\python.exe -m docket.advantage.v3.calibration_driver v3-03-warden-security docket/advantage/v3/calibration-captures/2026-08-25 --evaluator-id seat-b --session-id warden-seat-b-2026-08-25T1200Z --calibration-set docket/advantage/v3/sources/warden-calibration-set.json --seat docket.advantage.v3.seats.claude_cli:ask
```

Each command must print `captured`. A `no_response` record is not deleted or edited. If no
bytes were captured, the same seat may be invoked again and the next ordinal records that
fact; the first attempt that returns bytes binds, even if it later misses calibration.
Once any case output exists, apply the registration literally: “No substitution is
permitted after any case output exists; a missing sheet leaves rubric quality unscored and
the overall claim unestablished.” If a seat never produces captured bytes, or its binding
response misses either calibration floor, do not lock or run Warden.

The input lock recomputes both floors for each seat:

- at least 7 of 8 hostile-versus-benign decisions correct;
- class micro-F1 at least 0.80 against the shared eight-case key.

Codex seat isolation is contextual, not an OS read boundary: Codex 0.147.0 still injects the
global `AGENTS.md`. The adapter uses an empty working directory and ignores project/user
configuration, but do not describe the seat as instruction-free or filesystem-confined.

## 2. Assemble and lock the real inputs

Run exactly once after both seats captured responses:

```powershell
.\.venv\Scripts\python.exe -m docket.advantage.v3.assemble lock-warden docket/advantage/v3/specs/v3-03-warden-security.json docket/advantage/v3/sources/warden-heldout-cases.json docket/advantage/v3/sources/warden-vendor-snapshot.json docket/advantage/v3/sources/warden-calibration-set.json docket/advantage/v3/calibration-captures/2026-08-25
```

The command must print a non-empty 64-hex `inputs_sha256`. It writes
`docket/advantage/v3/inputs/03-security-heldout.json` and updates only the stage-two lock
fields in the existing spec. Verify the lock and its 12 cases:

```powershell
.\.venv\Scripts\python.exe -c "import json; from pathlib import Path; from docket.advantage.v3.spec import load, assert_runnable; p=Path('docket/advantage/v3/specs/v3-03-warden-security.json'); s=load(p); assert_runnable(s); body=json.loads(Path(s.inputs_ref).read_text(encoding='utf-8')); print(s.inputs_sha256, len(body['cases']))"
```

Expected: a non-empty digest followed by `12`. Review and commit the calibration captures,
generated input, and updated spec together before either primary arm runs:

```powershell
git add -- 'docket/advantage/v3/calibration-captures/2026-08-25/v3-03-warden-security/seat-*' docket/advantage/v3/inputs/03-security-heldout.json docket/advantage/v3/specs/v3-03-warden-security.json
git commit -m "Lock Warden v3 inputs"
```

Do not stage `session-claims.lock`; it is a cross-process coordination file, not evidence.

## 3. Run all 24 primaries in two blocks

Close the held-out answer-key source and every Warden output before starting. Keep only the
frozen vendor class vocabulary available. Run exactly 12 one-slot commands so the process
cannot cross from the manual block into the agent block. Each command reveals one
truth-stripped manual case after its timed claim and reads exactly one JSON line:

```powershell
1..12 | ForEach-Object {
  .\.venv\Scripts\python.exe -m docket.advantage.v3.orchestrator v3-03-warden-security docket/advantage/v3/runs --repo-root . --interactive --once
  if ($LASTEXITCODE -ne 0) { throw "manual primary $_ failed; stop the run" }
}
```

For each manual reveal, enter one compact JSON object on one line. It must contain:

```json
{"verdict":"ALLOW","risk_level":"MANUAL","threat_classes":[],"detections":[],"sanitized_payload":null,"recommendation":"No unregistered action identified.","checks":{"manual_review":"Classified against the frozen vendor vocabulary."}}
```

Change the verdict, classes, detections, recommendation, checks, and sanitized payload to the
case actually shown. `ALLOW` uses the original text downstream. `BLOCK` has no downstream
text. `SANITIZE` requires a string `sanitized_payload`. A malformed line or EOF is a terminal
failed primary, not a prompt to retry. Do not restart a disappointing or failed slot; the
ledger's first claim is permanent under this registration.

The current Warden route uses its free-tier receipt, so the command intentionally supplies no
payment header. Its free-work allowance is 20 requests per client address per hour, shared
with on-demand probes. Reserve 12 by making no other Docket hire or on-demand probe from the
run's outbound address for the preceding hour. Then confirm, read-only, that the registered
service is still the non-paid Warden route:

```powershell
$service = Invoke-RestMethod -Method Get -Uri https://docket.gudman.xyz/services/warden-scan -Headers @{Accept='application/json'}
if ($service.hire_path -ne '/hire/warden-scan' -or $service.paid_stock -ne $false) { throw 'Warden service contract changed; do not start the agent block' }
$service | Select-Object service_id, hire_path, paid_stock, stock_status
```

Only after that checkpoint, run the 12 registered agent primaries:

```powershell
.\.venv\Scripts\python.exe -m docket.advantage.v3.orchestrator v3-03-warden-security docket/advantage/v3/runs --repo-root .
```

The tested CLI accepts an already obtained header with `--payment-header`, but acquiring or
paying for one is a separate owner decision and is not part of this free-tier run. HTTP 402 is
recorded as `blocked_service_contract` and stops the command before another agent request. If
that happens, do not retry the claimed primary: Warden cannot clear 12/12 and remains `beta`.

After the command exits zero, verify 24 terminal primaries:

```powershell
.\.venv\Scripts\python.exe -c "from pathlib import Path; from docket.advantage.v3 import runner; from docket.advantage.v3.spec import load; s=load(Path('docket/advantage/v3/specs/v3-03-warden-security.json')); e=runner.read_events(runner.ledger_path(s, Path('docket/advantage/v3/runs'))); t=[x for x in e if x['kind']==runner.TERMINATED]; print(len(t), {o:sum(x['outcome']==o for x in t) for o in runner.OUTCOMES})"
```

Failures remain in the record and in the denominators. Do not edit the JSONL ledger.

## 4. Blind scoring and report

Export one prompt-blinded evaluation session per registered seat:

```powershell
.\.venv\Scripts\python.exe -c "from pathlib import Path; from docket.advantage.v3.runner import ExperimentHarness; from docket.advantage.v3.spec import load; root=Path('.').resolve(); s=load(root/'docket/advantage/v3/specs/v3-03-warden-security.json', repo_root=root); h=ExperimentHarness(s, root/'docket/advantage/v3/runs', repo_root=root); print(*h.export_evaluation_sessions(root/'data/warden-v3-evaluation-sessions'), sep='\n')"
```

Run the `seat-a` session through Codex and preserve its first raw response:

```powershell
@'
import json
from pathlib import Path
from docket.advantage.v3.seats.codex_cli import ask
sessions = Path("data/warden-v3-evaluation-sessions")
session = next(p for p in sessions.glob("*.json") if json.loads(p.read_text(encoding="utf-8"))["evaluator_id"] == "seat-a")
raw = ask(session.read_bytes())
if raw is None:
    raise SystemExit("seat-a returned no response; do not substitute another run")
out = Path("data/warden-v3-seat-a.raw.json")
with out.open("xb") as handle:
    handle.write(raw)
print(out)
'@ | .\.venv\Scripts\python.exe -
```

Run the `seat-b` session through Claude and preserve its first raw response:

```powershell
@'
import json
from pathlib import Path
from docket.advantage.v3.seats.claude_cli import ask
sessions = Path("data/warden-v3-evaluation-sessions")
session = next(p for p in sessions.glob("*.json") if json.loads(p.read_text(encoding="utf-8"))["evaluator_id"] == "seat-b")
raw = ask(session.read_bytes())
if raw is None:
    raise SystemExit("seat-b returned no response; do not substitute another run")
out = Path("data/warden-v3-seat-b.raw.json")
with out.open("xb") as handle:
    handle.write(raw)
print(out)
'@ | .\.venv\Scripts\python.exe -
```

Each response must be only the completed `score_sheet_template` JSON object from its session.
Import both first responses through the claim-once sheet API:

```powershell
@'
from pathlib import Path
from docket.advantage.v3.runner import ExperimentHarness
from docket.advantage.v3.spec import load
root = Path(".").resolve()
spec = load(root / "docket/advantage/v3/specs/v3-03-warden-security.json", repo_root=root)
harness = ExperimentHarness(spec, root / "docket/advantage/v3/runs", repo_root=root)
for seat in ("seat-a", "seat-b"):
    artifact = harness.import_evaluation_submission((root / f"data/warden-v3-{seat}.raw.json").read_bytes(), root / "docket/advantage/v3/sheets")
    print(artifact["evaluator_id"], artifact["raw_sheet_sha256"])
'@ | .\.venv\Scripts\python.exe -
```

Do not expose the A/B mapping until both imports succeed. Then publish the mapping and print
the same report object served at `/advantage/v3.json`:

```powershell
@'
import json
from pathlib import Path
from docket.advantage.v3 import report, runner, scoring
from docket.advantage.v3.spec import load
root = Path(".").resolve()
spec = load(root / "docket/advantage/v3/specs/v3-03-warden-security.json", repo_root=root)
ledger = runner.ledger_path(spec, root / "docket/advantage/v3/runs")
bundle = scoring.build_blinded_bundle(spec, ledger, repo_root=root)
scoring.publish_mapping(spec, bundle, root / "docket/advantage/v3/sheets", root / "docket/advantage/v3/mappings", repo_root=root)
payload = report.report()
family = next(row for row in payload["families"] if row["spec_id"] == spec.spec_id)
print(json.dumps({"summary": payload["summary"], "warden": family}, indent=2, sort_keys=True))
'@ | .\.venv\Scripts\python.exe -
```

Commit the ledger, two first-write sheet artifacts, and mapping before deployment. The input
lock and calibration captures were committed before the arms ran. The served report is
reconstructed on application startup, so the owner must deploy/restart only after reviewing
those exact committed artifacts.

## 5. Floors and the honest ship decision

Calibration is an input-lock gate: both seats need at least 7/8 correct decisions and class
micro-F1 at least 0.80.

The Warden ship gate is conjunctive:

- agent recall at least 0.90 over all 7 frozen hostile cases;
- defined agent precision at least 0.90 over every valid positive decision;
- agent recall and precision no lower than the manual arm's corresponding defined rates;
- 12/12 schema-valid agent primaries, because the registered `>=0.99` successful-scan floor
  over 12 scheduled scans can only be cleared by all 12;
- zero registered critical vector surviving the effective downstream text;
- no-lower median rubric total and all 12 complete speed pairs, with median time saved at
  least 30 seconds and median agent/manual ratio at most 0.50.

If any limb misses, Warden stays `beta`. It is not presented as strong, and TermiX's 20%
high-stakes criterion remains exposed. That is the recorded outcome; do not hide a failed
scan, replace a primary, edit a sheet, or soften a falsifier.

## 6. The prior Warden record, derived once from committed artifacts

V1's single hostile payload contained four manually identified vectors. The Warden arm found
1 of 4 (25.00% vector coverage on that one payload); a decision-level precision rate cannot be
formed from that hostile-only `n=1` record.

The committed v2 corpus run scored 47 of 47 payloads: 31 labelled attacks and 16 benign cases.
Warden's decision recall was 14/31 = 45.16%, and its decision precision was 14/15 = 93.33%.
The registered keyword null had recall 12/31 = 38.71% and precision 12/16 = 75.00%, so Warden
caught two more labelled attacks than that authored word list. Nine of the 141 scan attempts
failed, but every payload had at least one successful pass and therefore stayed in the 47-case
scored population. V1 and v2 are not substitutes for the frozen v3 gate above.

Regenerate those v2 figures from the report object; do not transcribe them from this page:

```powershell
.\.venv\Scripts\python.exe -c "from docket.advantage.v2.report import report; e=next(x for x in report()['experiments'] if x['experiment_id']=='03-security-corpus'); s=e['scores']; print({name:{metric:(row['decision_level'][metric]['numerator'],row['decision_level'][metric]['denominator'],row['decision_level'][metric]['value']) for metric in ('recall','precision')} for name,row in (('warden',s['warden']),('keyword_match',s['keyword_match']))}); print(s['warden']['counts'])"
```

## 7. BSC archive RPC decision — research checked 2026-08-23

Docket needs historical `eth_call` state and wide `eth_getLogs` on chain 56. A provider's
“full node” label is insufficient; acceptance requires the exact Docket call at its pinned
block, a second call roughly 1,000,000 blocks behind head, and a wide log query. Reject any
pruned-state, missing-trie-node, archive-depth, timeout, truncated-log, or null-result response.
Put the successful URL first in `DOCKET_ARCHIVE_RPC`; do not replace the latest-state RPC.

| Rank | Provider | BSC archive and free tier | Cheapest paid archive option | Time to URL | Evidence |
|---:|---|---|---|---|---|
| 1 | NodeReal / MegaNode | BSC archive is available to every tier with no archive surcharge. Free requires no card. Use the conservative current pricing-page limit: 10M CU/month, 150 CUPS, 3 keys; a BSC product page still conflicts at 100M/300. | Growth is $39/month or $31/month billed annually; 500M CU/month and 700 CUPS. | Self-service signup is documented; no elapsed provisioning time is published. | [archive](https://docs.nodereal.io/docs/archive-node), [pricing](https://nodereal.io/pricing), [pricing FAQ](https://docs.nodereal.io/docs/pricing), [BSC page](https://nodereal.io/api-marketplace/bsc-rpc) |
| 2 | BlockPI | Free includes BSC archive: 50M RU/month and 20 requests/second. Archive consumes 30% more RU. | PAYG is $0.01 per 50,000 RU ($0.20 per million RU); the $49 Elementary pack carries 500M RU for 60 days. | The archive toggle takes a few minutes to become effective. | [BSC](https://blockpi.io/chain/bsc/), [pricing](https://blockpi.io/pricing), [archive mode](https://docs.blockpi.io/basic-tutorials/api-key/customize-endpoint-advanced-features), [FAQ](https://docs.blockpi.io/supports/faq) |
| 3 | OnFinality | Free includes BSC archive: 400,000 RU/day and up to 40 RU/second. `eth_call` and `eth_getBalance` cost 1 RU each. | Growth is $49/month; the checked page advertised $31.85 for the first month, then $6 per million extra RU. | A public test endpoint needs no provisioning; authenticated endpoint timing is not published. | [BSC archive](https://www.onfinality.io/en/networks/bnb), [method/RU support](https://documentation.onfinality.io/support/bnb-chain), [pricing](https://onfinality.io/en/pricing) |
| 4 | Ankr | Public and Freemium both list full/archive data. Public needs no signup; Freemium provides 200M credits/month. | Premium PAYG is $0.10 per million credits; ordinary EVM methods are 200 credits. The cited page publishes no minimum deposit. | Public endpoint is immediate; private endpoint timing is not published. | [plans](https://www.ankr.com/docs/rpc-service/service-plans/), [pricing](https://www.ankr.com/docs/rpc-service/pricing/), [public RPC](https://www.ankr.com/docs/rpc-service/getting-started/basics-public/) |
| 5 | dRPC | BSC currently carries an Archive label and Free provides 210M CU/30 days over public nodes. dRPC warns that an Archive label does not always prove block-zero/full-history depth, so the exact block must pass. | PAYG is $0.30 per million CU; a standard RPC request costs 20 CU. | Public endpoint is immediate; private timing is not published. | [BSC](https://drpc.org/chainlist/bsc-mainnet-rpc), [archive caveat](https://drpc.org/docs/howitworks/archive-nodes), [free/PAYG](https://drpc.org/docs/pricing/requests), [CU](https://drpc.org/docs/pricing/compute-units) |
| 6 | QuickNode | BSC archive is supported. Free is a one-month, no-card trial with 10M credits, 15 RPS, and one endpoint. | Build is $49/month or $34/month billed annually; 80M credits and 50 RPS. | The quickstart says the endpoint is ready after creation but gives no elapsed duration. | [BSC archive](https://www.quicknode.com/docs/bnb-smart-chain), [pricing](https://www.quicknode.com/pricing), [BSC credits](https://www.quicknode.com/api-credits/bsc), [quickstart](https://www.quicknode.com/docs/bnb-smart-chain/quickstart) |
| 7 | GetBlock | BSC archive exists on Shared subscriptions; Free explicitly excludes archive. | Starter is $49/month or $39/month billed annually; 50M CU, 100 RPS, 10 endpoints. Archive requests consume 2x CU. | GetBlock says a dashboard upgrade takes about one minute. | [archive mode](https://docs.getblock.io/getting-started/endpoint-setup/enabling-archive-mode), [pricing](https://getblock.io/pricing-new/), [upgrade timing](https://getblock.io/blog/free-plan-update-paid-only-access-for-select-endpoints-and-configurations/) |
| 8 | Chainstack | BSC archive starts at Growth; the free Developer plan does not include it. Historical BSC reads cost 2 RU. | Growth is $49/month or $40/month billed annually; 20M RU and 250 RPS. | Self-service deployment is documented; exact archive provisioning time is not published. | [archive plans](https://chainstack.com/archive-data/), [pricing](https://chainstack.com/pricing/), [BNB call](https://docs.chainstack.com/reference/bnb-ethcall), [RU](https://docs.chainstack.com/docs/request-units) |

Choose NodeReal Free first, then BlockPI Free, then OnFinality Free. No purchase is justified
until all three fail the exact pinned-state and log-range probes. Ankr public is the fastest
no-signup diagnostic, not the primary long-window evidence endpoint.

The official Build the Era resources page publishes no archive-RPC grant. BNB Kickstart names
NodeReal as an infrastructure partner, but it is application/qualification-gated and publishes
neither the exact allowance, archive inclusion, nor a provisioning SLA. Apply separately if
useful, but do not make the Aug 25 run depend on it: [Build the Era resources](https://www.bnbchain.org/en/hackathons/smart-money-era),
[Kickstart](https://www.bnbchain.org/en/programs/kickstart), [program details](https://www.bnbchain.org/en/blog/kickstart-program-upgrade-built-for-your-projects-success).

Read-only public probes on Ankr and OnFinality timed out in the isolated research sandbox
(approximately 34 seconds and 12 seconds respectively). BlockPI/dRPC probe bodies were mangled
by that sandbox boundary, so no provider was disproven and no historical result is claimed.
Run the acceptance probes from Docket's actual caller after the owner obtains a URL.
