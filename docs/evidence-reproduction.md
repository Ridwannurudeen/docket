# Evidence reproduction

These steps inspect or recompute committed evidence. They do not lock a v3 input, run a v3
arm, send a payment, broadcast a transaction, or touch the repository's ignored database.

## Environment

Use Python 3.11 or newer from a clean checkout or an installed wheel. From the checkout:

```bash
python -m venv .venv
# activate the environment for your shell
python -m pip install -e ".[dev]"
```

## Verify the packaged evidence set

```bash
python -m pytest -q tests/test_packaging.py
python -m pytest -q tests/test_advantage_report.py tests/test_advantage_v2_api.py
python -m pytest -q tests/test_advantage_v2_spec.py tests/test_advantage_v2_scoring.py
python -m pytest -q tests/test_advantage_v2_replay.py tests/test_advantage_v3_spec.py
```

These tests recompute stored object identities, corpus hashes, spec-to-run links, null
baselines, denominators, falsifiers, and the current v3 artifact-derived states.

## Artifact byte hashes

SHA-256 is over exact file bytes. The primary committed files at this build are:

| Artifact | SHA-256 |
|---|---|
| `docket/advantage/experiments/01-liquidity.json` | `c048e5ede594f4bb7055dcba871acf9c1c3a22bfd1100f5504377fa4f8394116` |
| `docket/advantage/experiments/01-liquidity/live-audit.json` | `742ddd03abbbf9df8db5548bad98a7925b3c14eb57ccba48963bdf8cba3bb6c9` |
| `docket/advantage/experiments/02-trading.json` | `8735817bff88dc9b065f03fbdac7cefc5abaebbe28c94b16f9ebb4e9e90f4c17` |
| `docket/advantage/experiments/03-security.json` | `f4ad3c87b8cef5101dc1d1ed2e947b5012c7f77d0ff9d6d81cef1941b5c53f0c` |
| `docket/advantage/v2/corpus/liquidity/pools.json` | `f60b68ed4b7b4a04dec6f3772c9f8aab0955d0c1ad5d44397a16fddccfc015d5` |
| `docket/advantage/v2/corpus/security/payloads.json` | `11e9094f5a4a106d2f85be7a143c8c28ee6ee56c0521d1a0cda9672edab9f60a` |
| `docket/advantage/v2/corpus/series/bnbusdt-1h-2026-07.json` | `d642d970928d9ec45b228c047b4bc7fd99a62964515b68342c5eeb64c5003b72` |
| `docket/advantage/v2/runs/01-liquidity-arithmetic.json` | `bcb4836197192cb275a4d520646ef2c4d345023dcc547cbdb2d7a5afe10f35a7` |
| `docket/advantage/v2/runs/03-security-corpus.json` | `b67f0d3c1b923065c505705fe3358d0e7dacb64e6c15da4d0d33f2896afa34f0` |
| `docket/advantage/v2/runs/05-security-corpus-postfix.json` | `456e1ee9cc5656097e7eb24dbf50fd234b5d31ade5e900edfd18f1bc71211a33` |
| `docket/advantage/v2/runs/04-grid-replay.json` | `7a81088a5b7189c5b260e0957e1221b2557711bc8f71f934515b0dbc82128af4` |
| `experiments/e1c-result.json` | `eae28a4b029b6c656afb82f244e591aaa859a35468e94188a0c762d1b9fb5dc4` |

On PowerShell:

```powershell
Get-FileHash -Algorithm SHA256 docket\advantage\experiments\01-liquidity.json
```

On POSIX:

```bash
sha256sum docket/advantage/experiments/01-liquidity.json
```

## V1

V1 is three paired, single-observation records. Inspect each file's `question`, both arms,
complete outputs, elapsed seconds, cost note, receipt, and notes. Do not turn one observation
into a mean or a population estimate.

For Range, the committed receipt binds:

- input hash `0x916b75efe34d514427029d4534057ed220edf0644f8ffa23c2602592f157b852`
- output hash `0xf95c55ae7e28b8df65b69175f47525cc69933f0a9a5cbac17e54939b46d5a7ce`
- wallet `0x451871A1753903FB8fdd64a6B838E95aB8D5B80f`
- recorded coverage: 14 held/examined and 13 closed/skipped
- payment status `free_tier`

The repository's frozen live audit later recorded the same address with 25 positions, all
closed, at BSC block 117992875 on 2026-08-25. Its `limit=30` request returned
`positions_held=25`, `positions_examined=25`, `closed_skipped=25`, `open_skipped=0`,
`scan_complete=true`, and `stopped_by=null`, so the observation was not truncated. The
original live result therefore cannot be reproduced against that address at the audit block;
reproducing either file means checking its recorded bytes and arithmetic, not claiming the
wallet retained that state after its observation.

## V2

Build the same report object used by the API:

```bash
python -c "from docket.advantage.v2.report import report; r=report(); print(r['summary'])"
```

The four registered identities are:

| Experiment | Spec hash | Dataset SHA-256 |
|---|---|---|
| `01-liquidity-arithmetic` | `0x56af9f16038fd3bbfa94ab19eb14ab492e8d60656e7f9f86a5bcd7ea4bc002bd` | `f60b68ed4b7b4a04dec6f3772c9f8aab0955d0c1ad5d44397a16fddccfc015d5` |
| `03-security-corpus` | `0x4538a0aaba0aae1c73485c050745265af7ceba5fad47858884b3cf99abd4594f` | `11e9094f5a4a106d2f85be7a143c8c28ee6ee56c0521d1a0cda9672edab9f60a` |
| `05-security-corpus-postfix` | `0xd01c85bf7fc471ec93dd077cb153ff1e05924b2e2712120f51b0b029dfc863a8` | `11e9094f5a4a106d2f85be7a143c8c28ee6ee56c0521d1a0cda9672edab9f60a` |
| `04-grid-replay` | `0xe7da3328dfb4b92df7430679b224727e1a0a26a7850b99bca5e8234934239699` | `d642d970928d9ec45b228c047b4bc7fd99a62964515b68342c5eeb64c5003b72` |

The two security identities deliberately cite the same frozen corpus. The 2026-08-10 run
measured a live detector whose exact source revision and deploy date were not recorded and
remains byte-identical at the hash above. The separate 2026-08-24 run declares Warden revision
`0583853ed7fca7d03c98a5cc4c2383cc6b149248`, deployed that date; its endpoint did not
self-attest a source commit.

Read each report's `registration_provenance`, `null_baselines`, denominator fields, all
trials, and `falsifier_result`. V2 is not a human comparison and one claim is refuted; the
report summary states that rather than discarding it.

## V3

V3 has exactly nine stage-one specifications:

| Spec | Stage-one protocol hash | Current spec hash |
|---|---|---|
| `v3-01-range-doctor`, superseded before input lock | `0x5436fe80f16558d06f2f8f09f2eb4bbad6a2f3e26e5bbbbbafd143b7f14d2fce` | `0x4844dfcf708d257c92d8d5c00f502c14af8fb187464d3b1a5314d1592c720d82` |
| `v3-02-yield-router`, abandoned after a failed primary | `0x10d0fb31ea70c4bb31581952b99b6776d5f25d2c51bdf9543d47d07781266d3c` | `0xad391e9aa3b039ee5e43397d488deb25893253d3376b08ff544c5651566395d9` |
| `v3-03-warden-security`, superseded before input lock | `0xcd4c698f55c316fdedaa2eb52d80091c3a08d004175d7d156527f224c4e941eb` | `0x9321343763a7b8ff215b54f356ef8cc781ad4db56924d1bc5f23b3a53b7e618e` |
| `v3-04-warden-security`, complete unscored | `0x9e2206f6c9293e8f41528893aa1b526bfd917a099a5ae7dbe826c486d8a6b62e` | `0x08ad28caac2d76da2c2d6844341b7930f9338383ee7e82b4e712d426f7791d49` |
| `v3-05-range-doctor`, locked not run | `0x2a83c1a331d579e5cef461d52c539711b4fa2bba6dd397aaad1bf38b6b47f9ab` | `0x2a15b50e88b164ff57a7256aa9e35bdfb539cb02549e9c1374641fef92b4a43a` |
| `v3-06-yield-router-assisted`, waiting for inputs | `0x3dffb6610ac22f5e7b86d4f27e200a6168ad7ab4f91eb9a8c14d5d7ef4267350` | `0xa7cfadfe301f4b81d4142aa902635e72e7b38a27bff31a849fe7eef56d0ace64` |
| `v3-07-range-doctor`, waiting for inputs | `0x3305b8b3dd15ba3933dedc6b50ef94c4d2ea1f1a6cb26666ba84dd4ec45e67f5` | `0x90e1460ef5764d80c6b120d2552db3481d01b22b1f04edc6ac3098a64779b9da` |
| `v3-08-yield-router`, waiting for inputs | `0x250a7fadca72a93383b928d469e01ab54529bf52fa1e8613b0f4805d0e14ea91` | `0xa52c6a8e7ee12ae863326adc8e2792899fe7a31371daf5f4f1579c33fd15aa0e` |
| `v3-09-health-guard`, waiting for inputs | `0x5c5dc57de1e640d0c79d017e3c5d5dafdbe3ee1057b746ae3bf9940c177bf9f6` | `0xa0dfeb40bfcbe9a8747f70fe830cda12b91f825d7886dfb0889d7e5c264b1815` |

At the source-artifact observation on 2026-08-30, three families have locked inputs:
v3-02 digest `55d419a1b70910f76f334be417188901bfaa3d35adf795f1048c223e38719181`,
v3-04 digest `23b09164c6940848ac109f05db3f7342f46a0bad71c17ebc9cac53dd4f8fc4e6`,
and v3-05 digest `73086fba1ddbb82074003b4c04ef8564358f86b896a0a609b5e5f7e3c543e8b6`.
Their input locks remain valid. V3-02 recorded one failed manual primary and is
`abandoned_after_failed_primary`; v3-04 is `complete_unscored`; and v3-05 has no claimed
primary and is `locked_not_run`. V3-01 and v3-03 remain superseded with empty input digests.
V3-06 is `registered_waiting_for_inputs` with an empty input digest until its scheduled
2026-09-03 capture.
V3-07 is a distinct successor to v3-05 registered against a separate archive-pinned
frame at BSC block 119531513. Its 1,024 enumerable indices derive from its own
stage-one protocol hash, so it draws a different sample and cannot reuse v3-05's
committed frame. It is `registered_waiting_for_inputs` with an empty input digest
until its scheduled 2026-09-05 capture. It does not replace, retry or relabel v3-05,
whose registration, locked input and ledger remain separate and unchanged.
V3-08 and v3-09 are newly registered families rather than successors: each corrects no
unlocked draft and answers no published ledger, so neither carries a protocol correction,
pilot provenance or successor provenance, and neither changes any earlier family's state.
Both are `registered_waiting_for_inputs` with empty input digests. V3-08 puts a human
operator against the deployed Yield Router on three pools drawn from a top-pools response
captured at its registered 2026-09-06 moment; that is the arm v3-06 does not have, because
v3-06 registered a disclosed Codex-assisted baseline and made no human-versus-agent claim.
V3-09 puts a human operator against the deployed Health Guard on three Venus Core Pool
accounts drawn from a borrower frame pinned at BSC block 119627412, whose number, hash and
timestamp were read identically from the three public endpoints its registration names.
Its frame is collected by `python -m docket.advantage.v3.venus_capture`, which refuses
without `DOCKET_ARCHIVE_RPC` and refuses to overwrite an existing artifact; collecting it
is an operator action, not part of read-only reproduction.

Do not call `lock_inputs`, alter an input, or run an arm as part of reproduction. Those are
operator actions, not read-only verification.

## Evaluator-seat record

This page is read-only evidence reproduction, not an operator procedure. The stopped
[`runbooks/warden-v3-run.md`](runbooks/warden-v3-run.md) remains the superseded v3-03 record;
none of its Aug 25 capture, lock or arm commands may be executed.

The v3-04 procedure is preserved in
[`runbooks/warden-v4-run.md`](runbooks/warden-v4-run.md). It contains the mandatory
2026-08-27T12:00:00Z guard, two distinct real-seat captures, three calibration floors,
assembly and lock, all 24 primaries, blind scoring and the conjunctive ship decision. The
two-pilot sequence and separate pre-run validation are preserved in
[`warden-pilot-history.json`](../docket/advantage/v3/provenance/warden-pilot-history.json).

The v3-04 input is locked and its committed ledger contains all 24 terminal primaries: 23
succeeded, while manual `w4-ho-01` ended `failed` with `invoke_error` /
`JSONDecodeError`. Seat B returned no first scoring response, and the registered rule
forbids retry or substitution. No score sheets or mapping are committed, so rubric quality
is permanently unscored, `falsifier_result` is null, and read-only reproduction reports
`complete_unscored`.

## The Git witness

Each v3 spec says Git history is the registration witness and disclaims an independently
attested wall-clock registration time. Check the local sequence with:

```bash
git show --stat 88cc2bc
git branch -a --contains 88cc2bc
git branch -a --contains HEAD
```

At this build, `88cc2bc` and commit `534af826575a` are reachable from
`origin/docs/deliberation-round2`. GitHub recorded that ref at `2026-08-15T06:08:36Z`, so
the content pushed at that moment existed by then. That timestamp does not cover a later
registration or establish when any individual commit was authored. A hostile audit also
demonstrated that an owner can edit a spec, recompute its hashes through the library, and
create a backdated local commit that loads cleanly.

Therefore the reachable ref establishes a third-party timestamp for the ref content at that
push, while the commit graph establishes sequence. It does not independently timestamp each
registration or make the owner-controlled public ref immutable. To make the ordering
durable outside the owner's control, publish or commit the exact registration object hash to
an independently readable system before inputs or runs, then record that external
identifier here.

## SOLVENT's narrow on-chain evidence

V1 task 02 records ERC-8004 agent 136384 and anchor transaction
`0xa21529122b39aab0c8fd848e0546b5691a52531a4b06b76ea650b64a60fb59a9`
at BSC block 106960688. The recorded anchor covers the receipt chain only through sequence
381. The served signal in that artifact is sequence 383 and is not anchor-covered.

Recomputing the local chain can show internal consistency. The transaction can show the
anchored head existed at that block. Neither establishes that sequence 383 existed then or
that the historical market call was correct. SOLVENT remains halted research evidence.

## Clean wheel proof

Follow [the runbook](deployment-runbook.md#clean-installation). The proof is valid only if:

- `docket.__file__` resolves outside the checkout;
- all four category agent packages import;
- all four POST routes return 200 with their own result/receipt service IDs;
- the smoke uses a temporary database outside the checkout;
- no live RPC, explorer, payment, or transaction is required.

## Recorded category runs

The three files under `docket/advantage/recorded_runs/` are each a single recorded read;
no paired run against a person exists for them. They are separate from
`docket/advantage/experiments/` because every top-level `*.json` there is loaded as a
two-arm experiment. The nested `01-liquidity/live-audit.json` is claim evidence only and is
excluded from that loader.

The Health Guard wallet was selected read-only from a recent vUSDT `Borrow` event and then
read through the catalogue runner. The address is an observation of chain activity, not a
claim about the borrower. Grid uses Docket's controlled worked-example wallet. Yield takes
an empty payload and compares the eligible set from the live explorer snapshot.

From a POSIX shell, re-run the same catalogue call path with:

```bash
python -m docket.advantage.record_run health-guard \
  --payload '{"wallet":"0x41eE916D25C38fED953098525Ea3A74d2148A32a"}' \
  --out docket/advantage/recorded_runs/05-health-guard-read.json

python -m docket.advantage.record_run grid-operator \
  --payload '{"wallet":"0xe55816904796341bf8535e25f6c8b647927fc946"}' \
  --out docket/advantage/recorded_runs/06-grid-preview-read.json

python -m docket.advantage.record_run yield-router \
  --payload '{}' \
  --out docket/advantage/recorded_runs/07-yield-router-read.json
```

Each command resolves `docket.hire.catalogue.get_service()` and invokes that service's
`Service.run` callable, which is the callable the hire route invokes. It does not call the
public hire endpoint, settle a payment, sign, or submit anything. A successful record keeps
the full response, monotonic elapsed time, observation block where the service reports one,
source time, population, method, limits, and a receipt-shaped hash pair.

These are live reads, so a re-run is expected to differ. Health balances and the account's
entered markets can change; Grid quotes, calldata hashes, deadlines, and blocks move; Yield's
top list, eligible count, rates, source time, and hashes can move. A difference is new state,
not a reproduction failure. Preserve the committed files before re-running if the purpose is
inspection rather than replacement.

The exact committed request and result make the receipt hashes independently checkable:

```bash
python - <<'PY'
import json
from pathlib import Path
from docket.hire.receipts import canonical_hash

for path in sorted(Path("docket/advantage/recorded_runs").glob("*.json")):
    body = json.loads(path.read_text(encoding="utf-8"))
    arm = body["agent_arm"]
    output = arm["output"]
    receipt = output["receipt"]
    assert receipt["input_hash"] == canonical_hash(output["request"])
    assert receipt["output_hash"] == canonical_hash(output["result"])
    assert arm["output_hash"] == canonical_hash(output)
    print(path.name, receipt["input_hash"], receipt["output_hash"])
PY
```

Those checks establish byte-equivalent canonical JSON inputs and outputs. They do not prove
that an old public node can still answer the recorded state. Public BSC endpoints can prune
historical state soon after a read. `DOCKET_ARCHIVE_RPC` is the existing archive-first setting
for Docket's caller-pinned Pancake position reads; these Health and Grid catalogue paths do not
accept an old observation block, and the comparison-only Yield path reports no chain block.
Checking their old state therefore requires separate archive-capable read tooling configured
by the reader. Running the recorder again checks current state instead.
