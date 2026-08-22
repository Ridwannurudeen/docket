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
baselines, denominators, falsifiers, and the current v3 unrunnable state.

## Artifact byte hashes

SHA-256 is over exact file bytes. The primary committed files at this build are:

| Artifact | SHA-256 |
|---|---|
| `docket/advantage/experiments/01-liquidity.json` | `c048e5ede594f4bb7055dcba871acf9c1c3a22bfd1100f5504377fa4f8394116` |
| `docket/advantage/experiments/02-trading.json` | `8735817bff88dc9b065f03fbdac7cefc5abaebbe28c94b16f9ebb4e9e90f4c17` |
| `docket/advantage/experiments/03-security.json` | `f4ad3c87b8cef5101dc1d1ed2e947b5012c7f77d0ff9d6d81cef1941b5c53f0c` |
| `docket/advantage/v2/corpus/liquidity/pools.json` | `f60b68ed4b7b4a04dec6f3772c9f8aab0955d0c1ad5d44397a16fddccfc015d5` |
| `docket/advantage/v2/corpus/security/payloads.json` | `11e9094f5a4a106d2f85be7a143c8c28ee6ee56c0521d1a0cda9672edab9f60a` |
| `docket/advantage/v2/corpus/series/bnbusdt-1h-2026-07.json` | `d642d970928d9ec45b228c047b4bc7fd99a62964515b68342c5eeb64c5003b72` |
| `docket/advantage/v2/runs/01-liquidity-arithmetic.json` | `bcb4836197192cb275a4d520646ef2c4d345023dcc547cbdb2d7a5afe10f35a7` |
| `docket/advantage/v2/runs/03-security-corpus.json` | `b67f0d3c1b923065c505705fe3358d0e7dacb64e6c15da4d0d33f2896afa34f0` |
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

The repository's latest live audit later recorded the same address with 21 positions, all
closed. That observation is in an audit record and regression fixture, not a frozen current
chain snapshot in the v1 artifact. The original live result therefore cannot be reproduced
against that address now; reproducing the file means checking its recorded bytes and
arithmetic, not claiming the wallet still has the old state.

## V2

Build the same report object used by the API:

```bash
python -c "from docket.advantage.v2.report import report; r=report(); print(r['summary'])"
```

The three registered identities are:

| Experiment | Spec hash | Dataset SHA-256 |
|---|---|---|
| `01-liquidity-arithmetic` | `0x56af9f16038fd3bbfa94ab19eb14ab492e8d60656e7f9f86a5bcd7ea4bc002bd` | `f60b68ed4b7b4a04dec6f3772c9f8aab0955d0c1ad5d44397a16fddccfc015d5` |
| `03-security-corpus` | `0x4538a0aaba0aae1c73485c050745265af7ceba5fad47858884b3cf99abd4594f` | `11e9094f5a4a106d2f85be7a143c8c28ee6ee56c0521d1a0cda9672edab9f60a` |
| `04-grid-replay` | `0xe7da3328dfb4b92df7430679b224727e1a0a26a7850b99bca5e8234934239699` | `d642d970928d9ec45b228c047b4bc7fd99a62964515b68342c5eeb64c5003b72` |

Read each report's `registration_provenance`, `null_baselines`, denominator fields, all
trials, and `falsifier_result`. V2 is not a human comparison and one claim is refuted; the
report summary states that rather than discarding it.

## V3

V3 has exactly three stage-one specifications:

| Spec | Stage-one protocol hash | Current spec hash |
|---|---|---|
| Range | `0x5436fe80f16558d06f2f8f09f2eb4bbad6a2f3e26e5bbbbbafd143b7f14d2fce` | `0x4844dfcf708d257c92d8d5c00f502c14af8fb187464d3b1a5314d1592c720d82` |
| Yield | `0x52930b5854db990fbde1fe2f66e63b1f1ab0b396b07f6f0a07eab9833840d7a7` | `0xb1b203db589bf1c78eccea132af9c82dee60b4e99e67268f5b010b90d4e6e1da` |
| Warden | `0xcd4c698f55c316fdedaa2eb52d80091c3a08d004175d7d156527f224c4e941eb` | `0x9321343763a7b8ff215b54f356ef8cc781ad4db56924d1bc5f23b3a53b7e618e` |

For all three, `inputs_sha256` is the empty string. The referenced input files do not exist,
and there is no runs directory. `load()` can validate the stage-one file; `assert_runnable()`
must refuse it.

Do not create the referenced inputs, call `lock_inputs`, or run an arm as part of
reproduction. Those are future registered-protocol events, not read-only verification.

## Running the evaluator seats

This is an operator-only input-lock procedure, not a reproduction step. Run it once on the
scheduled Warden lock day. Both commands derive `model_build` from the installed CLI's own
version and resolved-model output before the request record is opened; no model name or build
string is typed by the operator.

Run `seat-a` through Codex:

```bash
python -m docket.advantage.v3.calibration_driver v3-03-warden-security docket/advantage/v3/calibration-captures/2026-08-25 --evaluator-id seat-a --session-id warden-seat-a-2026-08-25T1200Z --calibration-set docket/advantage/v3/sources/warden-calibration-set.json --seat docket.advantage.v3.seats.codex_cli:ask
```

Run `seat-b` through Claude:

```bash
python -m docket.advantage.v3.calibration_driver v3-03-warden-security docket/advantage/v3/calibration-captures/2026-08-25 --evaluator-id seat-b --session-id warden-seat-b-2026-08-25T1200Z --calibration-set docket/advantage/v3/sources/warden-calibration-set.json --seat docket.advantage.v3.seats.claude_cli:ask
```

The session IDs must be distinct: one session ID reported by two seats is one run counted
twice, and the driver refuses the second request. Each command first writes
`attempt-01.request.json`, including the exact derived prompt bytes, under
`docket/advantage/v3/calibration-captures/2026-08-25/v3-03-warden-security/seat-<seat-id>/`.
It then writes `attempt-01.response.json` with either the untouched response bytes or a
`no_response` outcome. Do not delete a failed attempt or repeat a captured one; the first
attempt that returns bytes binds even when its answer fails calibration.

After both response records exist, assemble the authored cases, verify both captured rows,
write `docket/advantage/v3/inputs/03-security-heldout.json`, and save its generated
`inputs_sha256` into the existing specification in one command:

```bash
python -m docket.advantage.v3.assemble lock-warden docket/advantage/v3/specs/v3-03-warden-security.json docket/advantage/v3/sources/warden-heldout-cases.json docket/advantage/v3/sources/warden-vendor-snapshot.json docket/advantage/v3/sources/warden-calibration-set.json docket/advantage/v3/calibration-captures/2026-08-25
```

The lock refuses an uncaptured or edited seat, fewer than seven correct hostile-versus-benign
decisions, class micro-F1 below the registered floor, a changed vendor snapshot, or an invalid
held-out envelope. Review and commit the two seat-capture directories, generated input, and the
specification update together before either scored arm runs.

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
registration or prevent the owner from rewriting the private remote ref. To make the ordering
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
