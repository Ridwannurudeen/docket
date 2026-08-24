# Wave-1 build reports (digest, untracked)
Base `fdf02cf` → `build/integration` @ 5dce78d; 1366 tests pass.


---

# w1-evidence

# W1 build report — v3 evidence machinery

Branch: `build/w1-evidence`

Commits:

- `6a4ca28 Pre-arm the recommitted Yield capture`
- `7fca5ea Bind evidence assembly to captured calibration`
- `5937055 Version the corrected calibration prompt`
- `5b9bd40 Prevent restarts after terminal capture outcomes`
- `d0885ce Harden registered capture recovery and deadlines`

`BUILD-REPORT.md` is intentionally uncommitted.

## Changes and audit closures

| Change | Location | Audit item closed |
|---|---|---|
| Early activation now writes `armed.json`, records the registered moment, three attempt slots, process start, spec hash, host identity and disk/write/clock checks, then sleeps inside the process. A wake after tolerance still refuses. | `docket/advantage/v3/capture.py:160`, `docket/advantage/v3/capture.py:369` | Joint audit §3 F1; W1 items 1 and 5 |
| `main()` injects its clock seam, passes `journal=output`, persists protocol refusals and unexpected failures, and returns distinct exit codes. A late activation performs zero HTTP. | `docket/advantage/v3/capture.py:429`, `docket/advantage/v3/capture.py:540` | F1; W1 items 2, 3 and 5 |
| Successful per-attempt raw bodies are exclusive-created and fsynced before the attempt JSON. Final raw bodies precede `capture-attempts.json`, and `capture-complete.json` is created last. Registered failure gets `capture-failed.json`. | `docket/advantage/v3/capture.py:455`, `docket/advantage/v3/capture.py:479` | F1; W1 item 2 |
| The timer pre-arms at 2026-08-26 11:50 UTC, catches missed activation, and has no jitter. The service uses bounded failure restarts. | `deploy/systemd/docket-v3-capture.timer:5`, `deploy/systemd/docket-v3-capture.timer:11`, `deploy/systemd/docket-v3-capture.service:7`, `deploy/systemd/docket-v3-capture.service:25` | F1; W1 items 1 and 3 |
| Yield was recommitted once to 2026-08-26T12:00:00Z, superseding `0x52930b…d7a7`; `inputs_sha256` remains empty. Both stored hashes were generated and independently recomputed. | `docket/advantage/v3/specs/v3-02-yield-router.json:15`, `docket/advantage/v3/specs/v3-02-yield-router.json:41`, `docket/advantage/v3/specs/v3-02-yield-router.json:47`, `docket/advantage/v3/specs/v3-02-yield-router.json:110`, `docket/advantage/v3/specs/v3-02-yield-router.json:119` | Joint audit §5 and §6 Aug 24; W1 item 4 |
| Range retains its Aug-21 boundary while the Yield validator and runtime schedule use Aug 26. | `docket/advantage/v3/spec.py:117`, `docket/advantage/v3/spec.py:118`, `docket/advantage/v3/spec.py:1870`, `docket/advantage/v3/runner.py:209` | W1 item 4; prevents recommit regression in v3-01 |
| Yield assembly now requires the calibration capture directory and calls `verify_calibration_capture` before accepting the envelope; the CLI passes the directory. | `docket/advantage/v3/assemble.py:44`, `docket/advantage/v3/assemble.py:125`, `docket/advantage/v3/assemble.py:306` | Joint audit L2; W1 item 6 |
| The calibration artifact parser preserves Warden fields and supports the registered `submitted` shape for Range/Yield, making the new assembly check functional on real artifacts. | `docket/advantage/v3/calibration.py:105`, `docket/advantage/v3/calibration.py:320` | Required prerequisite for L2 |
| Warden metrics now refuse when the vendor snapshot reference is absent instead of deriving vocabulary from case labels. | `docket/advantage/v3/scoring.py:1366` | Joint audit L3; W1 item 6 |
| The operations paragraph records the Aug-21 exit 2, empty output directory, rotated volatile journal and Aug-26 recommit. | `docs/operational-evidence.md:90` | F1; W1 item 7 |
| The exact-byte source manifest was regenerated for the changed Yield spec. | `docs/source-deploy-manifest.md:138` | Evidence digest consistency |
| Date-stable, pre-arm, late-zero-HTTP, duplicate activation, ordering, CLI, schedule, calibration-capture and Warden-vocabulary regressions were added. | `tests/test_advantage_v3_capture.py:80`, `tests/test_advantage_v3_capture.py:373`, `tests/test_advantage_v3_capture.py:602`, `tests/test_advantage_v3_capture.py:626`, `tests/test_advantage_v3_capture.py:652`, `tests/test_advantage_v3_runner.py:94`, `tests/test_advantage_v3_assemble.py:311`, `tests/test_advantage_v3_assemble.py:343`, `tests/test_advantage_v3_calibration.py:140`, `tests/test_advantage_v3_scoring.py:690` | F1, F9, L2 and L3 |

## Fix round (2026-08-22)

### Finding to change, commit and test

| Finding | Change and location | Commit | Exit test |
|---|---|---|---|
| ISSUE 1: a scalar httpx timeout did not bound a complete attempt. | Explicit 5/10/5/5-second phase limits are paired with a 50-second monotonic caller deadline. The async request runs on one daemon event-loop thread; timeout cancels it without joining cleanup. Every deadline result is ineligible for success, including completion/cancellation races. `docket/advantage/v3/capture.py:57`, `:73`, `:86`, `:170`, `:239`. | `d0885ce` | Drip, slow-close, filled-observation race, boundary completion and boundary exception tests at `tests/test_advantage_v3_capture.py:439`, `:492`, `:533`, `:566`. |
| ISSUE 2: exclusive `armed.json` prevented a legitimate pre-attempt restart. | The original arm remains immutable. A restart may create `armed-02.json` only for the same moment and spec hash with no `attempt-*.json`; malformed, mismatched or post-attempt state refuses before HTTP. The CLI holds the existing cross-process OS lock across arming, waiting, HTTP and attempt persistence, so a live duplicate cannot masquerade as a crash. `docket/advantage/v3/capture.py:504`, `:576`, `:584`, `:773`. | `d0885ce` | Crash/re-arm, all three attempt-artifact forms, moment/hash/type refusal and live-concurrency tests at `tests/test_advantage_v3_capture.py:919`, `:956`, `:1005`, `:1031`, `:1048`, `:1073`. |
| ISSUE 2 restart policy: exit 2/3 must be terminal to systemd. | Added `RestartPreventExitStatus=2 3`. `deploy/systemd/docket-v3-capture.service:27`. | `5b9bd40` | `tests/test_canary_deploy.py:75`. |
| ISSUE 3: the individual preflight and post-sleep late guards lacked isolated tests. | Both zero-HTTP refusal branches are exercised independently. `docket/advantage/v3/capture.py:311`, `:324`. | `d0885ce` | `tests/test_advantage_v3_capture.py:195`, `:208`. |
| ISSUE 4: an early window stop claimed all three attempts ran. | The failure record now names the actual count, blocked next ordinal, clock/tolerance reason and why later ordinals cannot be skipped. `docket/advantage/v3/capture.py:333`, `:358`, `:402`. | `d0885ce` | One- and two-attempt branches at `tests/test_advantage_v3_capture.py:286`, `:311`. |
| Suggestion (a): durability ordering was asserted in prose but not tested. | Exclusive writes now have an exact write -> flush -> fileno -> fsync sequence test. `docket/advantage/v3/capture.py:479`. | `d0885ce` | `tests/test_advantage_v3_capture.py:853`; the end-to-end ordering test also counts one fsync per exclusive create. |
| Suggestions (b)/(c): `capture-failed.json` had two shapes, and a terminal-write error escaped the handler. | Registered failures use the terminal `{outcome, recorded_at, reason}` schema. Terminal persistence failure emits a self-contained stderr line and returns distinct exit 4. `docket/advantage/v3/capture.py:603`, `:653`, `:751`. | `d0885ce` | `tests/test_advantage_v3_capture.py:634`, `:683`. |
| Suggestion (d): bind the superseded protocol pointer where derivable. | Runtime derivation is not possible: the installed record contains the predecessor digest but not the predecessor body, and package code cannot assume `.git`. The existing spec test pins all three pointers. A repository-only recomputation of the Yield predecessor body produced the declared `0x52930b58...d7a7`. No runtime code was added. | Documentation resolution | Existing literal/chain coverage remains in `tests/test_advantage_v3_spec.py:1311`. |
| Suggestion (e): non-Warden prompt wording changed without a version bump. | Warden keeps `v3.calibration-prompt.v1`; the changed Range/Yield schema is `v3.calibration-prompt.v2`. `docket/advantage/v3/calibration.py:115`, `:123`, `:130`. No calibration request/response artifact exists in this worktree or local refs, and the artifact checker uses stored prompt bytes/hash rather than re-deriving current wording. | `5937055` | `tests/test_advantage_v3_calibration.py:132`, `:157`. |

### Fix-round exit evidence

The regression additions were run before production changes:

```text
> .\.venv\Scripts\python.exe -m pytest -q tests\test_advantage_v3_capture.py tests\test_advantage_v3_calibration.py tests\test_canary_deploy.py
13 failed, 49 passed in 1.27s
```

The final focused slice includes capture, calibration, unit policy, spec and the reused cross-process lock:

```text
> .\.venv\Scripts\python.exe -m pytest -q tests\test_advantage_v3_capture.py tests\test_advantage_v3_calibration.py tests\test_canary_deploy.py tests\test_advantage_v3_spec.py tests\test_advantage_v3_runner.py
145 passed in 3.52s

> ruff check docket\advantage\v3\capture.py docket\advantage\v3\calibration.py tests\test_advantage_v3_capture.py tests\test_advantage_v3_calibration.py
All checks passed!

> ruff format --check docket\advantage\v3\capture.py docket\advantage\v3\calibration.py tests\test_advantage_v3_capture.py tests\test_advantage_v3_calibration.py
4 files already formatted
```

The final full suite ran after all three fix-round commits:

```text
> .\.venv\Scripts\python.exe -m pytest -q
1243 passed, 2 warnings in 49.75s
```

Warnings are the existing `websockets.legacy` and Starlette/httpx deprecations. `docket/api/web/app.js` was untouched, so `node --check` did not apply.

Local unit parsing used systemd 255 (255.4-1ubuntu8.16). It emitted no syntax or unknown-directive diagnostic. Its nonzero exit came only from DrvFs mode warnings and the absent production `/opt/docket/.venv/bin/python` path. The installed manpage states that `RestartPreventExitStatus` applies to the `ExecStart` main process regardless of `Restart=`.

### Fix-round mutation table

Each row is one isolated production mutation. The named test was red, the mutation was restored, and the same test was green before the next row.

| Test -> single mutation | Mutant | Restored |
|---|---:|---:|
| Dripping response -> extend the caller wait by 0.5 seconds | 1 failed (`0.547s >= 0.3s`) | 1 passed |
| Dripping response -> change connect timeout from 5 to 6 seconds | 1 failed | 1 passed |
| Filled-observation deadline race -> preserve an already-filled token-list 200/body | 1 failed | 1 passed |
| Boundary completion -> disable the `future.done()` race branch | 1 failed | 1 passed |
| Boundary worker exception -> suppress `future.exception()` | 1 failed | 1 passed |
| Late preflight -> disable only the preflight guard | 1 failed | 1 passed |
| Late wake -> disable only the post-sleep guard | 1 failed | 1 passed |
| One/two-attempt messages -> disable the early-stop count branch | 2 failed | 2 passed |
| Crash then restart -> restore unconditional existing-arm refusal | 1 failed | 1 passed |
| Three post-attempt restart cases -> disable the `attempt-*.json` gate | 3 failed | 3 passed |
| Different moment -> disable moment equality | 1 failed | 1 passed |
| Different spec -> disable spec-hash equality | 1 failed | 1 passed |
| Non-object `armed.json` -> disable JSON-object type check | 1 failed | 1 passed |
| Concurrent CLI activation -> give each activation a different lock path | 1 failed; duplicate HTTP seam ran | 1 passed |
| Failure record schema -> restore legacy `why` key | 1 failed | 1 passed |
| Terminal persistence fallback -> remove the `OSError` fallback | 1 failed with uncaught error | 1 passed |
| Exclusive persistence -> swap fsync before flush | 1 failed | 1 passed |
| End-to-end persistence -> remove fsync | 1 failed | 1 passed |
| Yield prompt version -> force v1 | 1 failed | 1 passed |
| Warden prompt version -> force v2 | 1 failed | 1 passed |
| Unit policy -> remove `RestartPreventExitStatus=2 3` | 1 failed | 1 passed |

### Fix-round limitations and owner actions

- `docs/deliberation/JOINT-AUDIT-2026-08-22.md` is absent from this worktree, base `fdf02cf` and all local refs, so its exact text could not be read. `CODEX-WIN-SPEC-2026-08-14.md` was read in full and its cut list was observed.
- No VPS or installed target-systemd check was permitted. The integrator must install commit `5b9bd40`, run `daemon-reload`, and confirm the timer/unit on the target as already listed below.
- The Aug-25 dress rehearsal and Aug-26 official capture remain future owner operations. No funds or new application configuration values are needed.
- Fix-round out-of-scope edits: none. The capture, calibration, unit and their tests are the files named by the findings. The capture reuses the existing lock in `runner.py` without editing that file.

## Exit-test evidence

### Baseline

```text
> .\.venv\Scripts\python.exe -m pytest -q
1 failed, 1209 passed, 2 warnings in 64.64s

FAILED tests/test_advantage_v3_capture.py::test_running_the_capture_before_its_moment_exits_refused
Expected "Capturing early"; actual path was the Aug-21 late-refusal message.
```

### Focused regression and formatting

```text
> .\.venv\Scripts\python.exe -m pytest -q tests\test_advantage_v3_capture.py tests\test_advantage_v3_spec.py tests\test_advantage_v3_runner.py tests\test_advantage_v3_assemble.py tests\test_advantage_v3_calibration.py tests\test_calibration_driver.py tests\test_advantage_v3_scoring.py tests\test_advantage_v3_warden_heldout.py tests\test_canary_deploy.py tests\test_packaging.py
189 passed in 2.94s

> ruff format --check docket\advantage\v3\assemble.py docket\advantage\v3\calibration.py docket\advantage\v3\capture.py docket\advantage\v3\runner.py docket\advantage\v3\scoring.py docket\advantage\v3\spec.py tests\test_advantage_v3_assemble.py tests\test_advantage_v3_calibration.py tests\test_advantage_v3_capture.py tests\test_advantage_v3_runner.py tests\test_advantage_v3_scoring.py tests\test_advantage_v3_spec.py tests\test_canary_deploy.py tests\test_packaging.py
14 files already formatted

> ruff check docket\advantage\v3\assemble.py docket\advantage\v3\calibration.py docket\advantage\v3\capture.py docket\advantage\v3\runner.py docket\advantage\v3\scoring.py docket\advantage\v3\spec.py tests\test_advantage_v3_assemble.py tests\test_advantage_v3_calibration.py tests\test_advantage_v3_capture.py tests\test_advantage_v3_runner.py tests\test_advantage_v3_scoring.py tests\test_advantage_v3_spec.py tests\test_canary_deploy.py tests\test_packaging.py
All checks passed!
```

### Recommit identities

The command loaded the committed spec, independently applied `canonical_hash` to the stage-one and composite bodies, hashed the exact file bytes, and read the runtime schedule.

```text
> .\.venv\Scripts\python.exe -c "import hashlib,json; from pathlib import Path; from docket.advantage.v3.runner import registered_capture_schedule; from docket.advantage.v3.spec import load; from docket.hire.receipts import canonical_hash; p=Path('docket/advantage/v3/specs/v3-02-yield-router.json'); r=json.loads(p.read_text(encoding='utf-8')); protocol={k:v for k,v in r.items() if k not in {'inputs_sha256','stage_one_protocol_hash','spec_hash'}}; composite={k:v for k,v in r.items() if k not in {'stage_one_protocol_hash','spec_hash'}}; s=load(p); print(r['stage_one_protocol_hash'], canonical_hash(protocol)); print(r['spec_hash'], canonical_hash(composite)); print(hashlib.sha256(p.read_bytes()).hexdigest(), repr(s.inputs_sha256)); print([x.scheduled_at.isoformat().replace('+00:00','Z') for x in registered_capture_schedule(s)], p.read_text(encoding='utf-8').count('2026-08-21'))"

0x10d0fb31ea70c4bb31581952b99b6776d5f25d2c51bdf9543d47d07781266d3c 0x10d0fb31ea70c4bb31581952b99b6776d5f25d2c51bdf9543d47d07781266d3c
0x3037f77abf461e4d9fffebf6156847bab2488b4d5cd683e0f37b464b4e2b173b 0x3037f77abf461e4d9fffebf6156847bab2488b4d5cd683e0f37b464b4e2b173b
1292fbf63c0616a983b41cee7a3e727c867c78f12d01adbab576d45d5f85e15d ''
['2026-08-26T12:00:00Z', '2026-08-26T12:01:00Z', '2026-08-26T12:02:00Z'] 0
```

### Old/new CLI dry run

The command extracted the old committed spec from `fdf02cf` into an auto-removed temporary directory inside the worktree, invoked `capture.main()` with an injected clock and forbidden HTTP attempt for the old moment, then invoked the packaged family id with an advancing frozen clock and local attempt seam for the new moment.

```text
> .\.venv\Scripts\python.exe -m pytest -q tests\test_advantage_v3_capture.py::test_running_the_capture_after_its_window_exits_refused_without_http tests\test_advantage_v3_capture.py::test_packaged_cli_arms_and_waits_for_the_recommitted_moment tests\test_advantage_v3_capture.py::test_main_arms_then_persists_raw_bytes_before_the_success_manifests
3 passed in 0.16s
```

The supplementary one-off old-spec/new-package script produced:

```text
capture refused: the registered capture opened at 2026-08-21T12:00:00Z ... A late capture is not the registered attempt ...
old_exit 2
old_zero_http True
old_reason_has_late True
captured at attempt 1: pools 33f95b0793c60bfb… (12 bytes), token list 9ee12b34bcf7cf0f… (13 bytes)
new_exit 0
new_sleep_seconds [600.0]
new_registered_moment 2026-08-26T12:00:00Z
new_completion True
```

### Unit parsing and policy

```text
> wsl.exe -e sh -lc 'systemd-analyze --version && systemd-analyze verify deploy/systemd/docket-v3-capture.service deploy/systemd/docket-v3-capture.timer'
systemd 255 (255.4-1ubuntu8.16)
```

Both files were read without a unit syntax or unknown-directive diagnostic. The command exited 1 only because DrvFs exposes the source files as executable/world-writable and WSL does not contain the production `/opt/docket/.venv/bin/python` path. The committed directive parser/policy tests passed in the focused and full suites. A later attempt to construct a disposable fake root was blocked before execution by the active shell safety policy; no temporary path was created.

### Final full suite on the committed tree

```text
> .\.venv\Scripts\python.exe -m pytest -q
1243 passed, 2 warnings in 49.75s
```

Warnings are the existing `websockets.legacy` and Starlette/httpx deprecations. `docket/api/web/app.js` was untouched, so the conditional `node --check` gate did not apply.

## Mutation table

Each mutation was applied alone, the named focused test was run, and the production change was restored before the next row. `pytest -q <node id>` was the command form unless a group is stated.

| Test / mutation | Mutant result | Restored result |
|---|---:|---:|
| `test_an_early_start_arms_then_waits_for_the_registered_moment` plus packaged CLI; restore early refusal | 2 failed in 0.19s | capture slice: 36 passed in 0.29s |
| `test_arming_refuses_a_directory_without_free_disk_space`; bypass disk check | 1 failed in 0.23s | 36 passed |
| `test_arming_refuses_a_directory_without_write_access`; bypass write check | 1 failed in 0.32s | 36 passed |
| `test_arming_refuses_a_blank_host_identity`; bypass host check | 1 failed in 0.20s | 36 passed |
| `test_arming_refuses_a_timezone_naive_clock_before_writing`; bypass clock check | 1 failed in 0.19s | 36 passed |
| `test_running_the_capture_after_its_window_exits_refused_without_http`; remove late guards | 1 failed in 0.60s; forbidden HTTP ran | 36 passed |
| `test_duplicate_activation_is_refused_before_another_attempt`; bypass exclusive arm | 1 failed in 0.31s | 36 passed |
| `test_main_arms_then_persists_raw_bytes_before_the_success_manifests`; remove `journal=output` | 1 failed in 0.25s | 36 passed |
| same ordering test; write attempt manifest before raw bodies | 1 failed in 0.22s | 36 passed |
| same ordering test; rename/remove completion marker | 1 failed in 0.26s | 36 passed |
| `test_the_entry_point_reports_a_failed_capture_distinctly`; rename/remove failure marker | 1 failed in 0.19s | 36 passed |
| `test_the_entry_point_persists_an_unexpected_runtime_failure`; remove exception persistence | 1 failed in 0.20s | 36 passed |
| `test_the_v3_capture_prearms_and_has_bounded_failure_restarts`; move timer back to 12:00 | 1 failed in 0.12s | 36 passed |
| same unit test; `Persistent=false` | 1 failed in 0.15s | 36 passed |
| same unit test; `Restart=no` | 1 failed in 0.13s | 36 passed |
| same unit test; `StartLimitBurst=0` | 1 failed in 0.09s | 36 passed |
| `test_the_capture_timer_prearms_without_jitter_and_persists` plus unit test; `Persistent=false` after the out-of-scope assertion update | 2 failed in 0.11s | 2 passed in 0.03s |
| three validator node ids; move `YIELD_CAPTURE_NOT_BEFORE` back to Aug 21 | 3 failed in 0.52s | 3 passed in 0.14s |
| `test_registered_capture_schedule_keeps_range_boundary_and_recommits_yield`; reuse Yield schedule for Range | 1 failed in 0.30s | 1 passed in 0.12s |
| `test_yield_uses_a_complete_frozen_universe_and_probability_sample`; move spec date back with regenerated mutant hashes | 1 failed in 0.15s | 1 passed in 0.04s |
| `test_each_family_is_legibly_a_correction_before_input_lock`; link correction to the wrong predecessor with regenerated mutant hashes | 1 failed in 0.14s | 1 passed in 0.04s |
| `test_warden_case_labels_cannot_replace_the_vendor_vocabulary`; restore case-label fallback | 1 failed in 0.41s | calibration/scoring group: 123 passed in 1.23s |
| `test_pancake_prompt_requests_submitted_answers`; use Warden prompt schema | 1 failed in 0.39s | 123 passed |
| `test_pancake_calibration_captures_submitted_answers`; force Warden result parser | 1 failed in 0.23s | 123 passed |
| `test_an_uncaptured_calibration_edit_is_refused`; remove assembler capture check | 1 failed in 0.22s | 123 passed |
| `test_cli_verifies_the_supplied_calibration_capture`; pass capture dir instead of calibration dir | 1 failed in 0.18s | 123 passed |

The Yield slice also ran its five selected tests before the fix (`5 failed in 0.40s`) and after it (`5 passed in 0.17s`). Every mutation above was restored; final sentinel search and `git diff --check` were clean before commit.

## Not performed

- No VPS file, service, timer, journal setting or deployment was touched.
- The installed-unit Aug-25 dress rehearsal and the official Aug-26 capture are future operational actions and could not be performed locally.
- No network write, transaction, signature, push, PR, publication or submission occurred.
- A zero-exit `systemd-analyze verify` against the production filesystem cannot be obtained on this Windows/WSL host because the production interpreter path and Linux file modes do not exist here. The parser produced no syntax diagnostic, and the source-policy tests are green.

## Owner / integrator actions

No funds or application configuration values are required for this workstream. After these commits are integrated into the release and its wheel is installed, the integrator must run the following on the VPS; none of these commands was run here.

```bash
sudo install -o root -g root -m 0644 deploy/systemd/docket-v3-capture.service /etc/systemd/system/docket-v3-capture.service
sudo install -o root -g root -m 0644 deploy/systemd/docket-v3-capture.timer /etc/systemd/system/docket-v3-capture.timer
sudo systemctl daemon-reload
sudo systemctl enable --now docket-v3-capture.timer
sudo systemctl list-timers docket-v3-capture.timer --all
```

Make journald durable for the judging window:

```bash
sudo mkdir -p /var/log/journal
sudo systemd-tmpfiles --create --prefix /var/log/journal
sudo mkdir -p /etc/systemd/journald.conf.d
printf '[Journal]\nStorage=persistent\n' | sudo tee /etc/systemd/journald.conf.d/docket-persistent.conf >/dev/null
sudo systemctl restart systemd-journald
sudo journalctl --flush
sudo journalctl --disk-usage
```

Then perform the audit-required Aug-25 dress rehearsal with the installed interpreter and a throwaway future-moment spec. It must create `armed.json` before the moment. If it does not arm, do not use another Yield moment; drop Yield as the joint audit directs. Before Aug 26, confirm the real timer is scheduled for `2026-08-26 11:50:00 UTC`, the output directory is writable by `docket`, and no stale `armed.json` or terminal marker exists from a rehearsal path mistakenly pointed at the official directory.

## Out-of-scope edits

These were the minimum cross-file changes required to keep the requested behavior functional and the full suite green:

- `docket/advantage/v3/runner.py` and `tests/test_advantage_v3_runner.py`: Range and Yield shared one Aug-21 constant; moving it without splitting the runner silently moved Range too.
- `docket/advantage/v3/calibration.py` and `tests/test_advantage_v3_calibration.py`: the required capture checker assembled only Warden fields, while `assemble.py` is Yield-only. Calling it unchanged would make the real Yield CLI unusable.
- `tests/test_packaging.py`: its old `Persistent=false` assertion directly contradicted W1's required `Persistent=true`.
- `docs/source-deploy-manifest.md`: its exact-byte digest had to follow the recommitted Yield spec or the package integrity gate would fail.


---

# w2-pancake-lp

# W2 PancakeSwap build report

Branch: `build/w2-pancake-lp`  
Base: `fdf02cf8161b7d57a183c7af01bdccf9739a72fd`  
Build commits:

- `fbb6f6e` Add owner decisions to the LP history
- `8e29cf4` Add archive RPC failover for pinned reads
- `146929b` Lead Pancake impact with dollars and payback
- `6fe8497` Document the controlled LP evidence chain
- `4964b8b` Cache the Pancake decision impact
- `458c6af` Route archive RPC only for historical reads
- `1270a9e` Harden the controlled LP decision chain
- `d6c7024` Clarify the controlled LP evidence chain

## Changes and audit closure

- `docket/agents/pancake/lp_record.py:40` defines compact UTF-8 canonical JSON for SHA-256 references and decision lines. Observation lines retain the original `json.dumps(..., sort_keys=True)` byte format at line 193; `_append_line` at line 201 flushes and fsyncs appended lines.
- `docket/agents/pancake/lp_record.py:92` checks the ordered observation -> owner decision -> optional superseding decisions -> later observation references. A decision must point to an earlier observation; every decision names its predecessor; every later observation points to the latest decision. This closes the owner-decision/hash-chain gap and fix-round Issues 2-4 without claiming causation.
- `docket/agents/pancake/lp_record.py:232`, `:239`, and `:289` expose `read_history`, `append_owner_decision`, and `verify_history` for W3. `read` remains an alias for existing callers.
- `docket/agents/pancake/lp_record.py:293` preserves the timer's positional observation command and adds `decide --path ... --decision WAIT|RECENTER --rationale ...`. The owner supplies the decision; chain state is never used to infer it.
- `tests/test_lp_record.py:214-597` covers compact/fsynced decisions, the synthetic history plus decisions and later observations, alteration/removal of referenced lines, broken-history append, CLI input, and invalid decisions.
- `docket/agents/pancake/positions.py:224-302` reads `DOCKET_ARCHIVE_RPC` separately from the public order, tries it first only for caller-pinned historical reads, continues after pruned-state failures, and retains the archive remedy when public nodes are pruned and the configured archive is unreachable. `docket/agents/pancake/doctor.py:367` keeps numeric blocks derived during live reports on the public order.
- `tests/test_pancake_positions.py:359-507` and `tests/test_pancake_doctor.py:350-378` use stub sessions/readers for live, historical, derived-live, explicit-URL, all-pruned, mixed-failure, and unreachable-archive behavior.
- `deploy/systemd/docket-lp-record.service:14` adds the owner-supplied `# Environment=DOCKET_ARCHIVE_RPC=` placeholder without inventing a URL.
- `docket/agents/pancake/doctor.py:60-90` builds the Pancake presenter headline from the generated v2 decision-impact artifact. Fixed-notional annual dollars and median payback delay lead; ranking reversals and the `post_hoc` state remain explicit. `RATE_LIMITATION` is unchanged and no price feed was added.
- `docket/agents/pancake/doctor.py:93-101` caches the frozen decision-impact calculation once per process; line 389 includes the unchanged headline in `doctor.report`. `tests/test_pancake_doctor.py:561-605` proves one computation and exact text.
- `docs/controlled-lp-evidence.md:1-93` explains the controlled record, explicit owner event, decision chain, unanchored-line limit, observed association rather than causal alpha, damaged-history append behavior, canonical digest reproduction, block pin, and live-versus-historical archive order without transcribing changing outputs.

## Fix round

| Finding | Commit | Closure and test | Mutation result |
|---|---|---|---|
| ISSUE 1 | `458c6af` | `positions.py:224-302,568-635` and `doctor.py:367`; stub ordering tests at `test_pancake_positions.py:359-422` plus report-provenance test at `test_pancake_doctor.py:350` | Inverting latest/historical selection failed 4 tests; making a derived-live block use archive failed 1; forcing report preference true/false failed the corresponding live/historical case. |
| ISSUE 2 | `1270a9e` | `lp_record.py:324-342` requires the newest observation to have `observed is True` and a nonblank report decision; tests at `test_lp_record.py:436,471,502` use two observations | Forward selection plus removed guards failed all 3 selected tests. |
| ISSUE 3 | `1270a9e` | `lp_record.py:180-232` tolerates earlier valid-JSON and invalid-JSON damage only while appending observations; strict checking still names the line and blocks decisions; test at `test_lp_record.py:365` uses eight prior lines and appends line 9 | Restoring strict pre-append verification failed both corruption cases. |
| ISSUE 4 | `1270a9e` | `lp_record.py:48,100-112,259-286` writes and verifies `supersedes_decision_sha256`; test at `test_lp_record.py:323` alters and removes the superseded decision | Removing the writer field failed 3 selected cases; removing predecessor verification failed both tamper cases. |
| ISSUE 5 | `1270a9e` | `lp_record.py:193` retains the original spaced, ASCII-escaped observation bytes while `_record_sha256` remains canonical; test at `test_lp_record.py:174` includes non-ASCII text | Compact observation serialization failed the byte-format test. No observation byte-format change remains to declare out of scope. |
| ISSUE 6 | `1270a9e` | Validators at `lp_record.py:59-88` plus tests at `test_lp_record.py:532,550,568`; latest-selection coverage at line 436; explicit unreferenced-observation limit at line 423 | Gutting UTC/rationale/token checks failed 4 cases; forward selection failed; deliberately rejecting the documented unreferenced alteration failed its by-design test. |
| SUGGESTION A | `458c6af` | `positions.py:283-302`; `test_pancake_positions.py:481` keeps the reachable-archive remedy and failure detail | Disabling the archive-unreachable classification failed the remedy test. |
| SUGGESTION B | `4964b8b` | `doctor.py:58,93-101,389`; `test_pancake_doctor.py:561` checks one computation and the exact committed headline | Bypassing the cache failed `assert 2 == 1`; changing headline text failed the exact-text assertion. The artifact has 22 eligible pools and 231 candidate moves, not 231 pools. |
| NITs | `1270a9e` | `lp_record.py:281,317-324` removes the dead alternatives ternary, preserves top-level help, and gives `decide` one history read; help test at `test_lp_record.py:592` | Regressing the help shim failed the help test. |
| Documentation | `d6c7024` | `docs/controlled-lp-evidence.md:22-93` states the decision chain, unanchored-line boundary, damaged-history behavior, and live/historical RPC split | Exercised by the behavioral tests above; no separate documentation behavior was introduced. |

## Exit-test evidence

### First-round evidence retained from `6fe8497`

Scoped integration:

```text
> ./.venv/Scripts/python.exe -m pytest -q tests/test_lp_record.py tests/test_pancake_positions.py tests/test_pancake_doctor.py
60 passed, 1 warning in 1.23s
```

The synthetic history plus reference-removal/edit and archive/headline exit cases:

```text
> ./.venv/Scripts/python.exe -m pytest -q tests/test_lp_record.py::test_later_observation_answers_latest_owner_decision tests/test_lp_record.py::test_verify_history_rejects_tampering_with_a_referenced_line tests/test_lp_record.py::test_verify_history_requires_later_observation_to_answer_latest_decision tests/test_pancake_positions.py::test_a_pruned_endpoint_fails_over_to_archive tests/test_pancake_positions.py::test_all_pruned_endpoints_raise_pruned_state_error tests/test_pancake_doctor.py::test_pancake_headline_leads_with_generated_dollars_and_payback
9 passed, 1 warning in 0.69s
```

Python lint:

```text
> ruff check docket/agents/pancake/lp_record.py docket/agents/pancake/positions.py docket/agents/pancake/doctor.py tests/test_lp_record.py tests/test_pancake_positions.py tests/test_pancake_doctor.py
All checks passed!
```

Full suite, including the declared W1 exception:

```text
> ./.venv/Scripts/python.exe -m pytest -q
FAILED tests/test_advantage_v3_capture.py::test_running_the_capture_before_its_moment_exits_refused
1 failed, 1224 passed, 2 warnings in 49.85s
```

Full suite with only that named W1 test deselected:

```text
> ./.venv/Scripts/python.exe -m pytest -q -k "not test_running_the_capture_before_its_moment_exits_refused"
1224 passed, 1 deselected, 2 warnings in 49.95s
```

JavaScript syntax, although W2 did not touch the file:

```text
> node --check docket/api/web/app.js
exit 0; no output
```

### Fix-round final evidence at `d6c7024`

Scoped Python suite:

```text
> ./.venv/Scripts/python.exe -m pytest -q tests/test_lp_record.py tests/test_pancake_positions.py tests/test_pancake_doctor.py
81 passed, 1 warning in 1.31s
```

Python formatting and lint:

```text
> ruff format --check docket/agents/pancake/lp_record.py docket/agents/pancake/positions.py docket/agents/pancake/doctor.py tests/test_lp_record.py tests/test_pancake_positions.py tests/test_pancake_doctor.py
6 files already formatted
> ruff check docket/agents/pancake/lp_record.py docket/agents/pancake/positions.py docket/agents/pancake/doctor.py tests/test_lp_record.py tests/test_pancake_positions.py tests/test_pancake_doctor.py
All checks passed!
```

Full suite, including the declared W1 exception:

```text
> ./.venv/Scripts/python.exe -m pytest -q
FAILED tests/test_advantage_v3_capture.py::test_running_the_capture_before_its_moment_exits_refused
1 failed, 1245 passed, 2 warnings in 47.66s
```

Full suite with only that named W1 test deselected:

```text
> ./.venv/Scripts/python.exe -m pytest -q -k "not test_running_the_capture_before_its_moment_exits_refused"
1245 passed, 1 deselected, 2 warnings in 48.71s
```

JavaScript syntax (unchanged file, rerun for handoff):

```text
> node --check docket/api/web/app.js
exit 0; no output
```

## Mutation table

### First-round mutations retained from `6fe8497`

Each implementation mutation was applied with a patch, the named test was run, and the implementation was restored before the green run.

| Test or parameter group | Temporary implementation mutation | Mutated result | Restored result |
|---|---|---:|---:|
| `test_read_history_returns_every_nonblank_line_in_order` | Reverse parsed lines | 1 failed | 1 passed |
| `test_a_recorded_line_is_canonical_json`; `test_owner_decision_is_canonical_and_fsynced` | Remove compact separators | 2 failed | 2 passed |
| `test_owner_decision_is_canonical_and_fsynced` | Remove `os.fsync` | 1 failed | 1 passed |
| `test_later_observation_answers_latest_owner_decision` | Stop attaching `answers_decision_sha256` | 1 failed | 1 passed |
| `test_verify_history_rejects_tampering_with_a_referenced_line[alter-observation]`; `[remove-observation]` | Remove prior-observation hash membership check | 2 failed | 2 passed |
| `test_verify_history_rejects_tampering_with_a_referenced_line[alter-decision]`; `[remove-decision]` | Remove later-observation decision-hash checks | 2 failed | 2 passed |
| `test_verify_history_requires_later_observation_to_answer_latest_decision` | Remove latest-decision mismatch check | 1 failed | 1 passed |
| `test_decide_subcommand_records_only_the_owner_s_typed_decision` | Replace typed `WAIT` with `RECENTER` | 1 failed | 1 passed |
| `test_owner_decision_rejects_a_value_outside_the_owner_choices` | Remove WAIT/RECENTER validation | 1 failed | 1 passed |
| `test_default_reader_prepends_archive_rpc_and_explicit_urls_stay_explicit` | Put archive after public endpoints | 1 failed, 1 warning in 0.76s | 1 passed, 1 warning in 0.90s |
| `test_a_pruned_endpoint_fails_over_to_archive` | Restore immediate pruned-state raise | 1 failed, 1 warning in 0.89s | 1 passed, 1 warning in 0.60s |
| `test_all_pruned_endpoints_raise_pruned_state_error` | Raise `RuntimeError` for all-pruned | 1 failed, 1 warning in 0.79s | 1 passed, 1 warning in 0.52s |
| `test_mixed_pruned_and_ordinary_failures_raise_ordinary_aggregate` | Treat any pruned endpoint as terminal | 1 failed, 1 warning in 0.81s | 1 passed, 1 warning in 0.59s |
| `test_pancake_headline_leads_with_generated_dollars_and_payback` | Put reversals before dollars/payback | 1 failed, 1 warning in 1.11s | 1 passed, 1 warning in 0.55s |
| `test_pancake_headline_leads_with_generated_dollars_and_payback` | Source the dollar field from the notional input | 1 failed, 1 warning in 0.92s | 1 passed, 1 warning in 0.51s |

The LP implementation file's pre/post mutation SHA-256 was identical (`1EF269BAA805B224E296A6B3257BC886F4DEA6BE1C7E103454F9C585E7759A23`). The archive and doctor feature diffs were likewise restored before their final scoped suites.

### Fix-round mutations

| Test or parameter group | Temporary production mutation | Mutated result | Restored result |
|---|---|---:|---:|
| Latest/pinned wallet and pool ordering | Invert the archive-selection condition | 4 failed, 23 deselected | 28 position tests passed |
| `test_explicit_rpc_urls_do_not_gain_the_archive_rpc` | Let explicit URLs inherit `DOCKET_ARCHIVE_RPC` | 1 failed | 1 passed |
| `test_pruned_public_endpoints_and_unreachable_archive_keep_archive_remedy` | Disable archive-unreachable classification | 1 failed | 1 passed |
| `test_a_block_derived_from_latest_keeps_the_public_rpc_order` | Treat its numeric block as historical | 1 failed | 1 passed |
| `test_report_only_prefers_archive_for_caller_pinned_history` | Force archive preference `True`, then `False` | 1 live case failed; 1 historical case failed | 2 passed |
| Latest decision binding: two-observation, failed-latest, blank decision | Search forward and remove both diagnosis guards | 3 failed | 3 passed |
| `test_a_broken_history_does_not_stop_the_next_observation` | Restore strict whole-history verification before observation append | 2 failed | 2 passed |
| Owner decision serialization and back-to-back chain | Omit `supersedes_decision_sha256` from the writer | 3 failed | 3 passed |
| Back-to-back decision tamper cases | Remove predecessor-hash verification | 2 failed | 2 passed |
| `test_an_observation_keeps_the_original_jsonl_byte_format` | Serialize observations as compact UTF-8 JSON | 1 failed | 1 passed |
| UTC, rationale, and token validation | Gut all three validators | 4 failed | 4 passed |
| `test_top_level_help_lists_both_subcommands` | Let the observe compatibility shim swallow `--help` | 1 failed | 1 passed |
| `test_altering_an_unreferenced_observation_is_not_detected_by_design` | Add an intentionally over-strict rejection | 1 failed | 1 passed |
| `test_reports_reuse_the_unchanged_frozen_decision_impact_headline` | Bypass cache, then alter headline wording | `assert 2 == 1`; exact text failed | 1 passed |

The LP test-first run before production fixes was `9 failed, 22 passed, 1 warning in 0.95s`; after every mutation was restored, the module was `31 passed, 1 warning in 0.81s` in the integrator run. The combined final scoped result was `81 passed, 1 warning`.

## Could not do

- `docs/deliberation/JOINT-AUDIT-2026-08-22.md` is absent from this worktree, sibling worktrees under the project parent, reachable refs, and git history. The fix round used the explicit findings in the workstream prompt and the present `CODEX-WIN-SPEC-2026-08-14.md` cut list; no content was inferred from the missing file.
- The real `/var/lib/docket/lp-record/controlled.jsonl` was not read or changed because this workstream forbids VPS and outside-worktree access. The eight-observation exit path is therefore synthetic.
- No archive RPC URL was available, purchased, or called. Endpoint behavior is covered with stub sessions; no URL was invented.
- No owner decision was recorded. That must remain an explicit owner action.
- Shared session memory was not edited because this workstream expressly forbids writes outside this worktree; this report is the in-worktree handoff.

## OWNER actions

Record today's decision by typing both values, then run the exact command below. `decided_at` defaults to the current UTC time. This intentionally makes no recommendation between `WAIT` and `RECENTER`.

```sh
read -r -p 'Decision (WAIT or RECENTER): ' DOCKET_LP_DECISION
read -r -p 'Rationale: ' DOCKET_LP_RATIONALE
/opt/docket/.venv/bin/python -m docket.agents.pancake.lp_record decide --path /var/lib/docket/lp-record/controlled.jsonl --decision "$DOCKET_LP_DECISION" --rationale "$DOCKET_LP_RATIONALE"
```

After purchasing archive access, set the service environment to the owner-supplied value and reload the unit definition:

```ini
[Service]
Environment=DOCKET_ARCHIVE_RPC=<OWNER-SUPPLIED-BSC-ARCHIVE-URL>
```

W3 must wire `read_history` and `append_owner_decision` into its owned API surface. No funds, transaction signing, network write, deployment, push, or submission occurred in W2.

## Out-of-scope edits

None.


---

# w3-api-hardening

# W3 Build Report — API hardening, freshness, payment recovery, identity surfacing

Date: 2026-08-22  
Branch: `build/w3-api-hardening`  
Base: `fdf02cf`  
Head: `c3dd011`

The plan-of-record file was absent from this worktree and from base `fdf02cf`. I read the complete copy at the sibling integration worktree, `../docket/docs/deliberation/JOINT-AUDIT-2026-08-22.md`, without copying or changing it here. I also read `docs/deliberation/CODEX-WIN-SPEC-2026-08-14.md` section 6. This build retains the audit's targeted six-hour refresh and does not add the cut full-registry crawl.

## Changes and audit closure

### F8 — keep blocking hire work off the event loop

- `docket/api/routes.py:1191` keeps the handler asynchronous so request parsing, payment ordering, allowance refunds, and response construction retain their existing order, while service execution, facilitator calls, and SQLite operations cross `run_in_threadpool` at their original sequence points. A synchronous handler would have required moving async body parsing and widened the behavioral rewrite.
- `tests/test_hire_api.py:366` starts a deliberately blocked service call, waits for proof that it entered, then measures a concurrent `/health` request and requires it to complete in less than 0.5 seconds.

### F8 — bound every hire attempt and add an outer deployment control

- `docket/api/routes.py:494` applies the hourly allowance to free and unadmitted hires using the peer address in `request.client.host`. It evicts expired windows on each call, caps the ordered peer map at 10,000 entries, and retains pre-work refund behavior. Admitted paid attempts now use the separate nginx bound described in the Fix round.
- `tests/test_hire_api.py:272`, `:286`, `:312`, `:344`, and `:382` cover no-payment hires, the 429 payment challenge, payment at the free cap, the hard cap, and expired-window eviction.
- `deploy/nginx/docket-rate-limit.conf.example:2` defines the per-address `30r/m` zone; `:8` applies it to `/hire/` with burst 10; `:9` returns 429. This is an example only and was not applied.

### F10 — prevent DNS rebinding between policy check and liveness connection

- `docket/netguard.py:61` centralizes address classification; `:73` returns the complete set of resolver addresses that passed policy while preserving the existing `check_url` API.
- `docket/liveness.py:61` checks the connected peer from httpx/httpcore response metadata. `:80` connects to the approved literal address, retains the original `Host` header and TLS SNI, disables environment proxy inheritance, and refuses absent, private, or different peers before recording response metadata. `:137` records such refusals as `blocked`, with null status and elapsed fields.
- `tests/test_netguard.py:30` and `tests/test_liveness.py:56`, `:114`, `:135`, `:154` cover the approved address, identity preservation, loopback rebinding, different-public-address rebinding, and missing peer metadata.

### F7 — refresh targeted marketplace data and serve promotions without restart

- `docket/ingest.py:39` validates and deduplicates full owned-agent IDs; `:56` fetches each owned identity by chain and token and checks returned identity fields; `:219` truthfully unions zero-feedback owned agents into the targeted `min_feedbacks>=1` population and supports hidden candidates.
- `docket/refresh.py:44` runs targeted ingest, enriches every callable candidate, probes every A2A/MCP endpoint, checks true completeness, and only then promotes. `:103` reads `DOCKET_OWNED_AGENT_IDS`; `:115` supplies the `python -m docket.refresh` entry point.
- `docket/store.py:45`, `:171`, `:463`, `:511`, and `:588` add promotion state, migrate legacy complete rows, finish candidates without exposure, reject incomplete promotions, and resolve only promoted snapshots.
- `docket/api/routes.py:416` cheaply resolves the latest promoted snapshot per request when the app was not explicitly pinned. Response fields are unchanged.
- `tests/test_ingest.py:274-346`, `tests/test_refresh.py:74-205`, `tests/test_store.py:165-244`, and `tests/test_api_contract.py:176` cover owned-agent identity handling, hidden candidates, completeness refusal, promotion, migration, and a running app adopting the new snapshot.
- `deploy/systemd/docket-refresh.service:17` runs the refresh module as a protected oneshot. `deploy/systemd/docket-refresh.timer:5` schedules 01:41, 07:41, 13:41, and 19:41 UTC with persistence.
- `docs/deployment-runbook.md:211` documents the refresh pipeline, configuration, installation, and inspection steps.

### Lost-response payment reconciliation

- `docket/store.py:302` persists the hash-bound receipt with a `settlement_unknown` row.
- `docket/api/routes.py:1174` serves `POST /hire/{service_id}/recover`. The buyer re-presents the exact original JSON body and authorization header while its signed window is live. The operator path added in the Fix round permits later token-authenticated delivery by nonce. Neither path calls the service or settlement again.
- `docket/api/routes.py:1505` creates the recovery receipt once at the unknown settlement transition, so repeated recovery is byte-equivalent.
- `tests/test_hire_api.py:638-837` cover both recoverable states, an altered signature, altered input, stable stored output, and an unknown nonce.
- `docs/api-and-payment-semantics.md:178` and `docs/deployment-runbook.md:140` document the exact recovery envelope, terminal states, refusals, signed-window constraint, and operator reconciliation procedure.

### F9 — public identity surfaces

- `docket/api/routes.py:899` redirects an HTML `GET /services/{id}` caller with 302 to `/service?id={id}` while keeping JSON behavior unchanged.
- `docket/api/routes.py:337` and `:659` publish a bounded, tolerant view of the controlled-position JSONL journal at `GET /lp-record`. The default path is `lp-record/controlled.jsonl`, overridable with `DOCKET_LP_RECORD_PATH`.
- `tests/test_api_contract.py:142` and `:162-317` cover the redirect, JSON compatibility, ordered LP lines, malformed input, both caps, missing/rotated files, the structured error envelope, and OpenAPI presence.

## Exit-test evidence

Final full suite:

```text
> .\.venv\Scripts\python.exe -m pytest -q
...
FAILED tests/test_advantage_v3_capture.py::test_running_the_capture_before_its_moment_exits_refused
1 failed, 1243 passed, 2 warnings in 51.92s
```

The sole failure is the explicitly exempt W1 date-armed baseline test. Its registered capture opened at `2026-08-21T12:00:00Z`, while this run occurred on 2026-08-22, so it produced the late-window refusal instead of the test's expected `Capturing early` text. No W3 file is involved.

Final W3 and adjacent API regression set:

```text
> .\.venv\Scripts\python.exe -m pytest -q tests\test_refresh.py tests\test_ingest.py tests\test_netguard.py tests\test_liveness.py tests\test_hire_api.py tests\test_hire_x402.py tests\test_api_contract.py tests\test_store.py tests\test_api.py tests\test_services_api.py
........................................................................ [ 35%]
........................................................................ [ 70%]
...........................................................              [100%]
203 passed, 2 warnings in 13.12s
```

Final formatting and lint:

```text
> ruff.exe format --check docket\api\routes.py docket\ingest.py docket\liveness.py docket\netguard.py docket\refresh.py docket\store.py tests\test_api_contract.py tests\test_hire_api.py tests\test_ingest.py tests\test_liveness.py tests\test_netguard.py tests\test_refresh.py tests\test_store.py
13 files already formatted
> ruff.exe check docket\api\routes.py docket\ingest.py docket\liveness.py docket\netguard.py docket\refresh.py docket\store.py tests\test_api_contract.py tests\test_hire_api.py tests\test_ingest.py tests\test_liveness.py tests\test_netguard.py tests\test_refresh.py tests\test_store.py
All checks passed!
```

Diff check:

```text
> git diff --check fdf02cf..HEAD
[no output; exit 0]
```

Focused component runs used during integration:

```text
> .\.venv\Scripts\python.exe -m pytest -q tests\test_netguard.py tests\test_liveness.py
26 passed in 1.12s

> .\.venv\Scripts\python.exe -m pytest -q tests\test_ingest.py tests\test_refresh.py
26 passed, 2 warnings in 2.09s

> .\.venv\Scripts\python.exe -m pytest -q tests\test_hire_api.py tests\test_hire_x402.py tests\test_api_contract.py tests\test_store.py tests\test_api.py tests\test_services_api.py
151 passed, 2 warnings in 10.92s
```

The two suite warnings are upstream deprecations from `fastapi.testclient` using Starlette's httpx adapter and `websockets.legacy`. No JavaScript was touched, so the requested `node --check docket/api/web/app.js` gate does not apply.

Installed behavior checked before implementation: Python 3.12.10, httpx 0.28.1, httpcore 1.0.9, Starlette 1.6.0, FastAPI 0.137.1, and Pydantic 2.13.4. The installed httpcore source consumes `sni_hostname`, and its response stream exposes `server_addr`.

## Mutation table

Every mutation below was temporary, produced the stated red result, was restored, and is included in the final passing focused set above.

| Test(s) | Temporary broken behavior | Before restoration | After restoration |
|---|---|---|---|
| `test_public_addresses_are_returned_for_a_pinned_connection` | Return no approved addresses | 1 failed: `() != ('93.184.216.34',)` | netguard/liveness: 26 passed |
| `test_probe_pins_the_approved_address_and_preserves_the_http_identity` | Connect with the original hostname | 1 failed: observed `ok.example`, not `93.184.216.34` | netguard/liveness: 26 passed |
| `test_rebound_connected_peer_is_a_policy_refusal_not_a_response` | Ignore the peer-policy result | 1 failed: `responded` was 1, expected 0 | netguard/liveness: 26 passed |
| `test_different_public_connected_peer_is_also_refused` | Disable exact approved-peer equality | 1 failed: `responded` was 1, expected 0 | netguard/liveness: 26 passed |
| `test_missing_connected_peer_is_refused` | Accept a response with no peer metadata | 1 failed: `responded` was 1, expected 0 | netguard/liveness: 26 passed |
| `test_targeted_sweep_adds_a_zero_feedback_owned_agent_to_its_population`, malformed/mismatched/missing owned-ID tests, and `test_refresh_includes_an_allowlisted_agent_with_zero_feedback` | Discard the owned-ID list | 5 failed | ingest/refresh: 26 passed |
| `test_targeted_candidate_can_finish_without_becoming_current` and `test_refresh_promotes_only_after_enrichment_and_probing` | Promote the ingest candidate immediately | 2 failed: candidate became current before enrichment/probing | ingest/refresh: 26 passed |
| `test_bounded_refresh_is_refused_and_never_promoted` and `test_non_advancing_refresh_is_refused_and_never_promoted` | Remove final completeness checks | 2 failed | ingest/refresh: 26 passed |
| `test_refresh_promotes_only_after_enrichment_and_probing` and `test_running_app_serves_the_snapshot_promoted_by_refresh` | Remove final promotion | 2 failed | ingest/refresh: 26 passed |
| `test_owned_agent_ids_are_read_from_the_refresh_environment` and `test_owned_agent_ids_environment_rejects_an_empty_list_item` | Split the environment value on the wrong delimiter | 2 failed | ingest/refresh: 26 passed |
| `test_refresh_systemd_units_run_the_pipeline_every_six_hours` | Change the timer to daily | 1 failed | ingest/refresh: 26 passed |
| explicit-promotion store/API tests | Run against the pre-promotion store/API | 4 failed | routes/store set: 151 passed |
| `test_a_database_predating_the_column_is_migrated_not_rejected` | Remove legacy `promoted_at` backfill | 1 failed: timestamp was `None` | routes/store set: 151 passed |
| `test_unpinned_app_adopts_only_a_newly_promoted_snapshot` | Remove the per-request latest-snapshot lookup | 1 failed: new snapshot was not served | routes/store set: 151 passed |
| `test_service_detail_redirects_html_callers_without_changing_json` | Remove content negotiation | 1 failed: 200 instead of 302 | routes/store set: 151 passed |
| `test_lp_record_returns_every_stored_observation` | Remove `/lp-record` | 1 failed: 404 instead of 200 | routes/store set: 151 passed |
| `test_lp_record_returns_every_stored_observation` OpenAPI assertion | Hide `/lp-record` from OpenAPI | 1 failed: path absent | routes/store set: 151 passed |
| `test_the_allowance_applies_even_without_a_payment_route` and `test_an_available_payment_route_still_returns_its_challenge_at_the_limit` | Skip the universal allowance | expected refusal became 200 | routes/store set: 151 passed |
| `test_the_allowance_map_evicts_its_oldest_window_at_the_hard_cap` | Remove the hard-cap eviction | 1 failed: evicted peer remained limited | routes/store set: 151 passed |
| `test_expired_allowance_windows_are_evicted_on_the_next_hire` | Remove expired-window eviction | 1 failed: three peers remained instead of the new peer only | routes/store set: 151 passed |
| `test_a_slow_hire_does_not_delay_concurrent_health` | Execute the slow service directly on the event loop | 1 failed: health took about 0.797 seconds, limit 0.5 | routes/store set: 151 passed |
| settled/unknown recovery and unknown-nonce tests | Remove the recovery route | recovery returned 404 | routes/store set: 151 passed |
| `test_payment_recovery_rejects_a_tampered_signature` | Bypass the invalid-signature branch | 1 failed through invalid `None` access instead of 400 | routes/store set: 151 passed |
| `test_payment_recovery_refuses_a_different_request_body` | Remove request-body hash binding | 1 failed: 200 instead of 409 | routes/store set: 151 passed |
| `test_an_unknown_settlement_result_can_be_recovered_without_retry` | Do not persist the unknown receipt | 1 failed: 500 instead of 200 | routes/store set: 151 passed |
| `test_an_unknown_settlement_result_can_be_recovered_without_retry` repeated recovery | Rebuild a receipt on each recovery | 1 failed: `delivered_at` values differed | routes/store set: 151 passed |

## Work not performed and why

- The W1 date-armed capture test was not changed because W1 owns it and the workstream instructions explicitly exempt it.
- No VPS, nginx, systemd, funded key, transaction, or public network write was touched. Those actions are prohibited for this workstream.
- `systemd-analyze calendar '*-*-* 01,07,13,19:41:00 UTC'` normalized the timer expression under WSL. A full local `systemd-analyze verify` could not model production because the Windows mount reports Windows mode bits and `/opt/docket/.venv/bin/python` intentionally does not exist locally.
- The plan-of-record file was missing from this branch/base. The sibling copy was read only; it was not added because it is outside W3 scope and belongs to integration.

## OWNER actions

These were documented but not executed:

1. Back up the production database.
2. Once the owned ERC-8004 identities exist, set `DOCKET_OWNED_AGENT_IDS` in the root-readable refresh configuration. Keep `DOCKET_DB` pointed at the production database.
3. Install `docket-refresh.service` and `docket-refresh.timer`, run daemon reload, enable/start the timer, and inspect the first oneshot and its logs before relying on the schedule.
4. Merge the nginx example into the appropriate production `http` and `/hire/` contexts, run `nginx -t`, then reload nginx.
5. Preserve the original signed request envelope for buyer recovery while its authorization window is live. After expiry, use the token-authenticated operator path by nonce.

No funds or signing approvals are required for the W3 code itself.

## Out-of-scope edits

- `docket/api/static/llms.txt`: added only the `/lp-record` and `POST /hire/{service_id}/recover` endpoint descriptions required by the existing OpenAPI/`llms.txt` consistency test. This is the minimum W4-owned documentation edit; the integrator should retain or reconcile it when merging W4.

No other out-of-scope file was changed.

## Fix round

This section supersedes the first-round allowance, recovery, LP-record, and owner-action wording above where the behavior changed.

### Changes and finding closure

- Item 1 — `docket/api/routes.py:494` generalizes the peer-address window helper; `:1385-1413` gates only free work, returns a 429 plus `Retry-After` and the x402 challenge at the free cap, and lets an admitted payment attempt proceed without debiting or refunding free work. `deploy/nginx/docket-rate-limit.conf.example:2-9` is the separate, higher paid-path bound: 30 requests per peer address per minute across `/hire/`. This was chosen because the durable nonce already supplies replay finality and a shared-egress free counter must not make payment impossible. Tests: `tests/test_hire_api.py:286` and `:312`.
- Item 2 — `docket/api/routes.py:99` publishes the 8 MiB/10,000-line bounds; `:337-379` streams the file, rejects malformed UTF-8/JSON/non-finite or non-serializable values, counts skipped nonblank lines, never returns a partial over-cap line, and treats a missing or rotated-away file as empty; `:659-667` maps other I/O failures to `500 lp_record_unavailable`. Tests: `tests/test_api_contract.py:162-317`. The route deliberately does not import W2's private `_read_history`, so it works whether that helper is present or absent; during integration, prefer consolidating on W2's tolerant reader only if the caps, skip count, truncation flag, and error envelope remain intact.
- Item 3 — `docket/api/routes.py:555` validates the bearer loaded from `DOCKET_CANARY_TOKEN_FILE` in constant time; `:1174-1329` adds nonce-only operator recovery for `settled` and `settlement_unknown` while preserving buyer signature-window verification. `docket/store.py:111`, `:187-191`, and `:217-228` add/migrate/write `operator_recovered_at`. Tests: `tests/test_hire_api.py:712`, `:751`, and `:788`; `tests/test_store.py:190`.
- Item 4 — `docket/api/routes.py:143-144` sets the 10-per-minute recovery bound; `:1182-1204` applies it by `request.client.host` before JSON/signature work and returns 429 plus `Retry-After`. Test: `tests/test_hire_api.py:829`.
- Item 5 — `docket/ingest.py:20-23` accepts `0x` or `0X` before canonical lowercase storage. `docket/refresh.py:20`, `:27-39`, and `:122-128` atomically write `last-refresh.json` with `ok`/`refused`/`error` and a UTC timestamp. `docket/api/models.py:101-108` types the field; `docket/api/routes.py:395` and `:764-774` expose the current file through `/stats` without restart. Tests: `tests/test_ingest.py:299`, `tests/test_refresh.py:76-173` and `:210-227`, and `tests/test_api_contract.py:78-92`, `:319-337`.
- Item 6 — `tests/test_store.py:278` directly inspects `promoted_at` after `finish_snapshot` sees `sampled != expected`; it does not call the duplicate read-side resolver and therefore pins the SQL guard at `docket/store.py:528`.
- Item 7 — `docket/api/routes.py:1284-1292` removes the tautological comparison between a stored recipient and a challenge constructed from that same stored value. Signature verification still binds the buyer authorization to the stored requirements.
- Contract/operations — `docket/api/static/llms.txt:115`, `:292-312`, and `:485-523`; `docs/api-and-payment-semantics.md:53-63`, `:128-140`, and `:204-220`; and `docs/deployment-runbook.md:109-114`, `:165-173`, and `:254-262` document the changed fields, statuses, limits, signed-window boundary, and operator checks.

Commits:

```text
188fe4c Harden paid hires, recovery, refresh status, and LP reads
c3dd011 Document W3 hardening operations and contracts
```

### Fix-round exit-test evidence

Focused affected and adjacent suite:

```text
> .\.venv\Scripts\python.exe -m pytest -q tests\test_hire_api.py tests\test_hire_x402.py tests\test_api_contract.py tests\test_refresh.py tests\test_ingest.py tests\test_store.py tests\test_api.py tests\test_services_api.py
........................................................................ [ 37%]
........................................................................ [ 74%]
.................................................                        [100%]
193 passed, 2 warnings in 12.55s
```

Final full suite:

```text
> .\.venv\Scripts\python.exe -m pytest -q
........................................................................ [  5%]
........................................................................ [ 11%]
......................................F................................. [ 17%]
........................................................................ [ 22%]
........................................................................ [ 28%]
........................................................................ [ 34%]
........................................................................ [ 40%]
........................................................................ [ 45%]
........................................................................ [ 51%]
........................................................................ [ 57%]
........................................................................ [ 62%]
........................................................................ [ 68%]
........................................................................ [ 74%]
........................................................................ [ 80%]
........................................................................ [ 85%]
........................................................................ [ 91%]
........................................................................ [ 97%]
....................................                                     [100%]
FAILED tests/test_advantage_v3_capture.py::test_running_the_capture_before_its_moment_exits_refused
1 failed, 1259 passed, 2 warnings in 53.31s
```

The only failure is the explicitly exempt W1 date-armed test: it expects `Capturing early`, but the registered capture opened on 2026-08-21 and the final run occurred on 2026-08-22.

Formatting, lint, and committed diff:

```text
> ruff.exe format --check docket\api\models.py docket\api\routes.py docket\ingest.py docket\refresh.py docket\store.py tests\test_api_contract.py tests\test_hire_api.py tests\test_ingest.py tests\test_refresh.py tests\test_store.py
10 files already formatted
> ruff.exe check docket\api\models.py docket\api\routes.py docket\ingest.py docket\refresh.py docket\store.py tests\test_api_contract.py tests\test_hire_api.py tests\test_ingest.py tests\test_refresh.py tests\test_store.py
All checks passed!
> git diff --check fdf02cf..HEAD
[no output; exit 0]
```

`docket/api/web/app.js` was not changed, so the conditional `node --check` gate does not apply.

### Fix-round mutation table

Every break below was temporary, failed as stated, was restored immediately, and is covered by the final focused suite.

| Test(s) | Temporary mutation | Before restoration | After restoration |
|---|---|---|---|
| paid hire at free cap | Force every paid attempt through the free window | 1 failed: 429 instead of 200 | 1 passed |
| free request at cap | Change the cap response back to 402 | 1 failed: 402 instead of 429 | 1 passed |
| operator recovery | Reject the configured token | 1 failed: 401 instead of 200 | 2 operator tests passed |
| wrong operator bearer | Accept every bearer | 1 failed: 200 instead of 401 | 1 passed |
| operator audit field | Return success without the store update | 1 failed: `operator_recovered_at` was null | 1 passed |
| buyer expiry boundary | Force a no-token buyer onto the operator branch | 1 failed: operator nonce message instead of expired signature | 1 passed |
| recovery peer bound | Disable the window exhaustion branch | 1 failed: 404 instead of 429 | 1 passed |
| LP order | Reverse parsed lines | 1 failed: file order reversed | 1 passed |
| LP malformed count | Remove the skip increment | 1 failed: 0 instead of 5 | 1 passed |
| LP missing file | Mark a missing file truncated | 1 failed: true instead of false | 1 passed |
| LP rotation race | Restore `exists()` then `open()` | 1 failed: 500 instead of empty 200 | 1 passed |
| LP line cap | Remove the physical-line condition | 1 failed: third line returned and truncation false | 1 passed |
| LP byte cap | Parse a partial over-cap line | 1 failed: partial counted as skipped | 1 passed |
| LP read failure | Catch only `FileNotFoundError` at the route | 1 failed with `PermissionError` | 1 passed |
| uppercase owned ID | Restore lowercase-only `0x` regex | 1 failed with `ValueError` | 1 passed |
| refresh terminal status and live `/stats` | Disable status-file writes | 4 failed: three missing files and null live status | 4 passed |
| refresh timestamp | Write a naive local timestamp | 1 failed: no UTC offset | 1 passed |
| stats model contract | Remove `refresh_status` | 1 failed: field absent | 1 passed |
| stats pre-refresh state | Invent an `ok` status when no file exists | 1 failed: object instead of null | 1 passed |
| legacy payment schema | Disable `operator_recovered_at` migration | 1 failed: column absent | 1 passed |
| finish write-side guard | Remove `sampled = expected` from the promotion update | 1 failed: incomplete row gained `promoted_at` | 1 passed |
| `llms.txt` contract | Rename `operator_unauthorized` in the served document | 1 failed: term absent | 1 passed |
| refresh runbook check | Rename the documented status-file path | 1 failed: required path absent | 1 passed |

### Fix-round work not performed

- The W1-owned date-armed failure was not changed.
- No deployment, VPS, nginx/systemd installation, funded signing, transaction, public network write, or push occurred.
- No W2 file was changed. W2's private tolerant reader is absent on this branch and, as described above, integration must preserve the W3 response contract and bounds if the implementations are consolidated.

### Fix-round OWNER actions

1. Before opening paid stock, install the tracked nginx limit in the production `http` and `/hire/` contexts, run `nginx -t`, and reload nginx. This is the paid-path bound relied on by item 1.
2. Keep `DOCKET_CANARY_TOKEN_FILE` root-managed and non-empty; use it for operator recovery without printing or logging its contents.
3. Monitor `/var/lib/docket/data/last-refresh.json`, `/stats.refresh_status`, `systemctl status docket-refresh.service`, and `journalctl -u docket-refresh.service`. `Restart=no` provides no automatic retry or alert.
4. No funds or signing approval are required for this code-only fix round.

### Fix-round out-of-scope edits

- `docket/api/static/llms.txt` remains the sole W4-owned file changed, limited to the response fields, statuses, bounds, and operator path required by this fix round. The integrator must reconcile it with W4.
- No other out-of-scope file was edited.


---

# w4-web-docs

# W4 build report — web, vocabulary, comparison, README truth, redactions

Date: 2026-08-22  
Branch: `build/w4-web-docs`  
Base: `fdf02cf`  
Commits: `f7570b7`, `cf4e68b`, `0d1ebb0`, `cdfc0dc`, `e085bcf`, `038657a`,
`4d15354`, `c3f6215`

`docs/deliberation/JOINT-AUDIT-2026-08-22.md` is absent from the worktree, every
local ref, and local history. The W4 brief supplied in the workstream prompt and the cut
list in `docs/deliberation/CODEX-WIN-SPEC-2026-08-14.md` therefore governed this build.

## Changes and audit closures

| Audit item | Change | Source and tests |
|---|---|---|
| Joint-audit F4 — zero-typing worked example | Added the controlled wallet and Range defaults for token `7141050`, `$50.55`, `$1`, and 30 days; Grid and Health use the same read target. Kept wallet required at the API boundary. Marked five reproducibility inputs advanced and attached the controlled-position note. The service page renders normal inputs first, the advanced disclosure second, and a worked-example submit control; every submit control is disabled while a run is pending. | `docket/hire/catalogue.py:48,636-752,767-790,871-898`; `docket/api/web/app.js:500-557,1221-1272`; `docket/api/web/style.css:789-807`; `tests/test_catalogue_services.py:80-135`; `tests/test_services_api.py:232-260`; `tests/test_web_categories.py:683-699` |
| Joint-audit F9 — marketplace vocabulary and coverage | Free cards and forms say “Run it free”; admission state and post-admission price moved below the action under “Why this isn't for sale yet.” Empty metric cards say “No run recorded yet.” Coverage renders days, treats age `>=7` days and missing age as non-current, includes an age sentence in the banner, and prints the feedback-filtered sample against the registry total. | `docket/api/web/app.js:263-320,336-390,527-550,1397-1404`; `docket/api/web/style.css:502-526`; `tests/test_web.py:198-222`; `tests/test_web_categories.py:702-716` |
| Codex gaps #8/#9 — comparison | Added one-clause `job_summary`; replaced the long job cell; marked catalogue time as declared and paired runs as measured with `n=1` and date; added freshness and evidence cells; retained a stated reason for every missing measurement/evidence record. Admission detail sits below the table. | `docket/hire/catalogue.py:135,636-639,767,871-873,925-927,1050-1052,1085`; `docket/hire/comparison.py:33-158`; `docket/api/web/app.js:1458-1529`; `docket/api/static/llms.txt:297-308`; `docket/api/static/SKILL.md:56,445-449`; `tests/test_hire_comparison.py:123-170`; `tests/test_web_categories.py:725-744` |
| Joint-audit §11 — evidence modality | Added the closed five-value `EvidenceModality`, made it required on `ServiceRecord`, populated all six records, and exposed it on every real list/detail/associated-service card. `ServiceCard` uses a defaulted nullable field plus a post-model lookup because W3 owns the explicit route constructors. Agent docs describe the closed vocabulary. | `docket/marketplace/models.py:112-118,242,258-262`; `docket/marketplace/registry.py:70,107,146,180,252,309`; `docket/api/models.py:199-215`; `docket/api/static/llms.txt:218-228`; `docket/api/static/SKILL.md:440-449`; `docket/api/web/app.js:382,586`; `tests/test_marketplace.py:365-389`; `tests/test_services_api.py:202-229`; `tests/test_web_categories.py:719-722` |
| Copy and generated Pancake impact | Changed homepage metadata/tagline, added the two caveated preprint references, scoped the first-party planner/deep-link statement to the documented execution model, and stated the Explorer/subgraph boundary. The homepage headline reads the v2 JSON at runtime; README figures were copied only after regenerating the same values from `report()`. | `docket/api/web/index.html:6-9,49-61,77-101`; `docket/api/web/app.js:1533-1568`; `docket/api/web/style.css:326-341`; `README.md:3-8,65-87`; `tests/test_web_categories.py:747-788` |
| JSON-link clarity and cache coherence | Labelled raw JSON footer destinations on every HTML page and moved every static asset reference to one cache token. | `docket/api/web/index.html:306-313`; `docket/api/web/service.html:89-96`; `docket/api/web/research.html:132-137`; `docket/api/web/agent.html:76-81`; `docket/api/web/advantage.html:1083-1089`; `docket/api/web/advantage-v2.html:155-162`; `docket/api/web/advantage-v3.html:123-129`; `tests/test_web.py:224-241` |
| README / claims / manifest truth | Reconciled the builder-collected deploy record to commit `534af826...` as of 2026-08-16; corrected registration reachability; regenerated all six v3 hashes from the specs; fixed the registry inventory docstring; documented the existing Manifest → Verifier → Receipt extension shape without claiming third-party stock, settlement, or v3 results. | `README.md:34-45`; `docs/claims-to-evidence.md:12,16-17`; `docs/source-deploy-manifest.md:5-57,140,152-157`; `docs/evidence-reproduction.md:103-138`; `docs/architecture.md:53-70`; `docket/marketplace/registry.py:3-5` |
| Security seat M1 — prose-only redaction | Replaced the public host/root-copy recipe with placeholder-host commands and converted all absolute Windows user paths to repo-relative paths. | `docs/plans/2026-08-06-phase0-foundations.md:27,68,110,318,335,377,453,460,470-473,525`; `docs/plans/2026-08-07-phase1a-evidence-spine.md:21,302`; `docs/plans/2026-08-07-phase1b-liveness.md:21`; `docs/plans/2026-08-07-phase1c-agent-api.md:21`; `docs/plans/2026-08-08-phase1d-web-ui.md:21`; `docs/plans/2026-08-08-phase1e-range-doctor.md:26`; `docs/plans/2026-08-08-phase1f-hire-flow.md:21`; `docs/plans/2026-08-08-phase1g-advantage-report.md:21`; `docs/plans/2026-08-10-phase1h-escrow-rail.md:31`; `docs/plans/2026-08-12-stage0-evidence-contract.md:16`; `docs/deliberation/BUILD-BRIEF-RUNNER-ORCHESTRATOR.md:7`; `docs/deliberation/CODEX-ASSESSMENT-2026-08-14.md:29-226`; `docs/deliberation/CODEX-EXEC-AUDIT-2026-08-14.md:11-113`; `docs/deliberation/CODEX-WIN-SPEC-2026-08-14.md:18-127` |

## Exit-test evidence

Baseline before W4 changes:

```text
.\.venv\Scripts\python.exe -m pytest -q
1 failed, 1209 passed, 2 warnings in 67.17s
```

Only failure: `tests/test_advantage_v3_capture.py::test_running_the_capture_before_its_moment_exits_refused` (the known W1 date-armed test).

Final full suite:

```text
.\.venv\Scripts\python.exe -m pytest -q
FAILED tests/test_advantage_v3_capture.py::test_running_the_capture_before_its_moment_exits_refused
1 failed, 1231 passed, 2 warnings in 53.81s
```

There are no W4 failures. Focused checks:

```text
.\.venv\Scripts\python.exe -m pytest -q tests/test_web.py tests/test_web_categories.py
70 passed, 2 warnings in 4.59s

.\.venv\Scripts\python.exe -m pytest -q tests/test_web.py::test_no_external_requests_anywhere_in_the_ui tests/test_web.py::test_ui_uses_no_verdict_language tests/test_web.py::test_no_registry_figure_is_typed_into_a_page tests/test_web.py::test_json_footer_links_are_labelled_as_json
4 passed, 2 warnings in 0.73s

.\.venv\Scripts\python.exe -m pytest -q tests/test_services_api.py::test_controlled_example_defaults_do_not_make_an_empty_body_valid tests/test_services_api.py::test_every_card_carries_its_closed_evidence_modality tests/test_hire_comparison.py
16 passed, 2 warnings in 1.08s

.\.venv\Scripts\python.exe -m pytest -q tests/test_api_contract.py tests/test_hire_comparison.py tests/test_marketplace.py tests/test_services_api.py tests/test_catalogue_services.py
137 passed, 2 warnings in 3.85s

.\.venv\Scripts\python.exe -m pytest -q tests/test_packaging.py
7 passed

node --check docket/api/web/app.js
exit 0

git diff --check fdf02cf..HEAD
exit 0
```

Generated Pancake values:

```text
.\.venv\Scripts\python.exe -
notional=10000
median_annual_overstatement_usd=126.782410
n_pools=22
median_days_later=8.302442
ranking_reversals=0/231
```

V3 spec-loader check: `V3_DOC_HASH_SYNC=3/3`. Redaction-only semantic comparison:
`REDACTION_ONLY_FILES=14 MISMATCHES=0`.

Final residue checks:

```text
rg -n --pcre2 'C:\\Users\\|<user-home>\.119\.153\.252|ssh\s+root@|scp\s+.*root@' docs
zero matches
```

## Mutation table

| Test set / deliberate break | Mutated or pre-change result | Restored result |
|---|---:|---:|
| Three controlled-default/catalogue tests before implementation | 3 failed, 9 passed | 12 passed |
| Three comparison contract tests before implementation | 3 failed, 9 passed | 12 passed |
| Eight modality/API tests before implementation | 8 failed, 92 passed | 100 passed |
| Agent-doc advanced-field drift test before docs change | 1 failed | 1 passed |
| SOLVENT measurement date changed to the source timestamp rather than receipt date | 1 failed | comparison suite: 12 passed |
| Range wallet changed to `required=False` | 1 failed (`502 != 422`; runner sentinel fired) | 1 passed (`422`) |
| Modality vocabulary expanded with `testimonial` | 1 failed (`ValueError` not raised) | 1 passed |
| Ten new web behavior tests before implementation | 10 failed, 60 passed | 70 passed |
| Coverage/footer/example/vocabulary/metrics/modality/comparison/homepage/metadata grouped break | 9 failed, 61 passed | 70 passed |
| Population-filter source removed | 1 failed | 70-test web suite passed |
| Worked-example submit control broken | 1 failed | 1 passed |
| Advanced/example CSS rules removed | 2 failed | 2 passed |
| No-wallet-connection wording restored to the contradictory claim | 1 failed | 1 passed |

All deliberate breaks were removed before commit. No mutation marker remains.

## Could not do

- The named joint-audit plan is absent from this branch, its base, local refs, and local
  history. For the fix round, its 430-line source was found and read without modification in
  the sibling `docket` worktree before any fix was applied.
- The historical `docs/specs/2026-08-06-docket-design.md` was left unchanged under the
  reviewer's ruling because it has no reader-note section at the top.
- This workstream issued no live hire POST. The independent reviewer did: the worked-example
  request returned HTTP 200 at block `117443373` with `target_found: true`.

## OWNER actions

- No W4 configuration value, funded key, or funds are required.
- Push, deploy, or submit only after explicit owner approval; none occurred in this workstream.

Owner-facing wording decision: the button says “Try the worked example” because the requested
alternative contains a prohibited evidence-status term. The Pancake copy is limited to the
first-party planner execution model because the broader repository also describes configured
execution.

## Out-of-scope edits

None.

## Fix round

### Changes and audit closures

| Review item | Change | Source and tests |
|---|---|---|
| 1 — inert worked-example duplicate | `[data-example]` submissions now reset every scalar and array control, including Advanced controls, to its schema default before validation and POST. The normal submit path still reads edits, and the existing per-field example note remains rendered. | `docket/api/web/app.js:718-768,1277-1322`; `tests/test_web_categories.py:254-337` |
| 2 — BNB prize ruling | Current public documents now state that the BNB main track has one `$30,000` winner plus official adoption, not a shared pool. The dated design spec has no top reader-note section and remains untouched. | `README.md:46-47`; `docs/architecture.md:6-7`; `docs/claims-to-evidence.md:18`; `docs/operational-evidence.md:12-13` |
| 3 — nullable evidence modality | `ServiceCard.evidence_modality` is required and non-nullable; `_card()` supplies the required registry value explicitly, so missing catalogue/registry data fails model construction. The parity assertion remains. The existing `llms.txt` and `SKILL.md` already say every card carries the field and required no edit. | `docket/api/models.py:199`; `docket/api/routes.py:213`; `tests/test_services_api.py:203-242` |
| 4 — README figure drift | Added a format-tolerant guard that parses the Pancake figures and compares their rounded values with `decision_impact_section()`. | `README.md:67-71`; `tests/test_decision_impact.py:173-218` |
| 5 — controlled-wallet disclosure | Grid now labels the prefilled address as Docket's controlled wallet. Health states plainly that this wallet has no Venus position, so its honest result is no position. | `docket/hire/catalogue.py:791-793,902-905`; `tests/test_catalogue_services.py:78-117` |
| 6 — Warden freshness | The Warden card and comparison now say the hire is a live upstream call and the recorded run is evidence rather than freshness. | `docket/hire/catalogue.py:1094`; `docket/hire/comparison.py:34-39,146-152`; `tests/test_hire_comparison.py:145-183` |
| 7 — subgraph primary source | README now cites the exact read-only GraphQL `_meta` query and its returned block, timestamp/date, and indexing-error flag, while distinguishing that source from Docket's Explorer input. | `README.md:85-92` |

The read-only GraphQL POST was issued exactly once:

```text
endpoint: https://thegraph.pancakeswap.com/exchange-v3-bsc
query: { _meta { block { number timestamp } hasIndexingErrors } }
HTTP 200
{"data":{"_meta":{"block":{"number":95193979,"timestamp":1777389823},"hasIndexingErrors":true}}}
timestamp: 2026-04-28T15:23:43Z
```

Independent review evidence, correcting the first-round report: the reviewer submitted the
worked example to the live hire endpoint and received HTTP 200, block `117443373`,
`target_found: true`. This workstream did not repeat that network write.

### Exit-test evidence

```text
.\.venv\Scripts\python.exe -m pytest -q
FAILED tests/test_advantage_v3_capture.py::test_running_the_capture_before_its_moment_exits_refused
1 failed, 1235 passed, 2 warnings in 57.50s
```

The only failure is the known date-armed capture test owned by W1.

```text
node --check docket/api/web/app.js
exit 0

.\.venv\Scripts\python.exe -m pytest -q tests/test_web.py tests/test_web_categories.py
71 passed, 2 warnings in 3.14s

.\.venv\Scripts\python.exe -m pytest -q tests/test_services_api.py tests/test_api_contract.py tests/test_marketplace.py::test_evidence_modality_is_closed_and_populated_for_every_service
48 passed, 2 warnings in 3.50s

.\.venv\Scripts\python.exe -m pytest -q tests/test_catalogue_services.py tests/test_hire_comparison.py
25 passed, 1 warning in 0.53s

.\.venv\Scripts\python.exe -m pytest -q tests/test_decision_impact.py tests/test_packaging.py tests/test_api_contract.py
31 passed, 1 warning in 0.86s

git diff --check fdf02cf..HEAD
exit 0
```

### Fix-round mutation table

| Test / deliberate break | Mutated result | Restored result |
|---|---:|---:|
| Worked-example submit handler changed back to `readForm(record, form)` | 1 failed; handler-dispatch assertion | 71 web tests passed |
| `ServiceCard` restored to nullable with lazy registry fill | 1 failed; field absent from required schema | 48 API/parity tests passed |
| README annual overstatement changed from `$126.78` to `$126.79` | 1 failed; `126.79 != 126.78` | 12 decision-impact tests passed |
| Grid/Health notes removed and Warden left on recorded-run freshness | 3 failed (`KeyError`, missing card phrase, recorded-vs-live mismatch) | 3 focused tests passed |

Every deliberate break was restored before commit. No mutation marker remains.

### Could not do

- The plan of record could not be added to this branch because that was outside this
  workstream; it was read from the sibling worktree as the source of truth.
- The historical design spec was not changed because the reviewer explicitly required it to
  remain untouched when no top reader-note section exists.

### OWNER actions

- No fix-round config values, funds, keys, or approvals are required.
- Push, deploy, publish, or submit only after explicit owner approval; none occurred here.

### Out-of-scope edits

None.


---

# w5-identity

# W5 build report — ERC-8004 identity registration tooling

Branch: `build/w5-identity`  
Base: `fdf02cf8161b7d57a183c7af01bdccf9739a72fd`  
Commits: `2e0819c`, `31ee2bc`, `fca978d`, `ebe2639`  
Network writes, signatures, broadcasts, pushes, deployments, and submissions: none.

## Changes and audit closure

- `abis/IdentityRegistry.json:1` — closes Joint Audit F7 / W5 Build 1 with the live-observed minimal ABI: `register(string)`, `tokenURI(uint256)`, `ownerOf(uint256)`, Transfer, MetadataUpdate, Registered, and MetadataSet. `totalSupply()` is omitted because its selector is absent and its call reverts.
- `docket/identity/__init__.py:1` and `docket/identity/register.py:24` — add the W5 identity package and the four-service boundary.
- `docket/identity/register.py:154` — closes W5 Build 2a with registration-v1 generation from the catalogue's current name and `what_you_get`, the public hire URL, and `x402Support`.
- `docket/identity/register.py:174` — closes W5 Build 2b with chain-56 enforcement, live gas estimation, live gas price, pending nonce, and a complete unsigned `register(string)` transaction.
- `docket/identity/register.py:196` — closes W5 Build 2c by decoding agent ID, URI, and owner from the Registered receipt log. It decoded the live SOLVENT mint as agent 136384.
- `docket/identity/register.py:212` — closes W5 Build 2d with the marketplace's exact lower-case canonical identity string.
- `docket/identity/register.py:220` — closes W5 Build 2e with the sole CLI action, `plan`. Unknown actions and signing flags are rejected by argument parsing before Web3 is touched.
- `docket/api/static/agents/range-doctor.registration.json:1`, `grid-operator.registration.json:1`, `yield-router.registration.json:1`, and `health-guard.registration.json:1` — close W5 Build 3. All four files were emitted from the generator; semantic equality is pinned in tests.
- `pyproject.toml:41` and `pyproject.toml:47` — close W5 Build 4 by packaging `docket.identity` and the nested registration documents.
- `docs/deployment-runbook.md:212` — closes W5 Build 5 with the owner-only, sequential plan/sign/broadcast/receipt procedure, live gas observation, and integrator handoff.
- `tests/test_identity_register.py:83` — covers generator/static parity, ABI shape, transaction construction, live event decoding shape, canonical binding, CLI refusal, wheel declarations, and the absence of signing/broadcast calls.

## Chain evidence used for the ABI

Read-only RPC checks against `https://bsc-dataseed.bnbchain.org` and independently against `https://bsc-dataseed1.defibit.io` found:

```text
chainId: 56
proxy implementation: 0x7274e874ca62410a93bd8bf61c69d8045e399c02
implementation runtime bytes: 14474
register(string) f2c298be: present
newAgent(string,address) 4750d0fa: absent
tokenURI(uint256) c87b56dd: present
ownerOf(uint256) 6352211e: present
totalSupply() 18160ddd: absent; eth_call reverted
```

SOLVENT mint transaction
`0xda8461a78cc715964a8d653a6cf8a1968119516e443475f6ef5ca46c4eaa90b6`
at block 104586936 emitted Transfer, MetadataUpdate, Registered, and MetadataSet.
The live `decode_registration` result was:

```text
{'agent_id': 136384, 'token_uri': 'https://solvent.gudman.xyz', 'owner': '0xE4fe23FB57dbb9AC2f685ea29B6b9A1409A0d359'}
```

The runbook gas statement comes from `eth_gasPrice` at block 117439816:
50,000,000 wei (0.05 gwei).

## Exit-test evidence

### Red test before implementation

```powershell
./.venv/Scripts/python.exe -m pytest -q tests/test_identity_register.py
```

```text
ModuleNotFoundError: No module named 'docket.identity'
1 error in 0.76s
```

### Focused W5 tests

```powershell
./.venv/Scripts/python.exe -m pytest -q tests/test_identity_register.py
```

```text
........                                                                 [100%]
8 passed, 1 warning in 0.53s
```

### Contract bans and formatting

```powershell
ruff check docket/identity tests/test_identity_register.py
ruff format --check docket/identity tests/test_identity_register.py
rg -n 'sign_transaction|send_raw_transaction|send_transaction|\.transact\(' docket/identity
```

```text
All checks passed!
3 files already formatted
no signing or broadcast calls found in docket/identity
```

### Clean-wheel check

The build cache, temporary directory, wheel output, and install target were pinned below
`.w5-wheel-test` so no file was written outside the worktree. The generated artifacts were
removed afterward.

```powershell
./.venv/Scripts/python.exe -m pip wheel . --no-deps --wheel-dir .w5-wheel-test/dist
./.venv/Scripts/python.exe -m pip install --no-deps --target .w5-wheel-test/site .w5-wheel-test/dist/docket-0.1.0-py3-none-any.whl
```

```text
Successfully built docket
Created wheel for docket: filename=docket-0.1.0-py3-none-any.whl size=582374 sha256=227bc9ba867a7882822e0f408190ee6b268df7e49b6feedc6d3bb0d7cc9e6486
Successfully installed docket-0.1.0
installed_identity_import=ok
installed_registration_documents=4
```

The installed-wheel copy of `docket.identity.register` also ran the live read-only plan
shown below.

### Live range-doctor plan

```powershell
./.venv/Scripts/python.exe -m docket.identity.register plan --service range-doctor --from 0xE4fe23FB57dbb9AC2f685ea29B6b9A1409A0d359
```

```json
{
  "bnb_cost": "0.0000081658",
  "gas_estimate": 163316,
  "gas_price_wei": 50000000,
  "registration": {
    "description": "A read-only diagnosis of the PancakeSwap v3 liquidity positions a BSC wallet holds or has staked: for each one, whether the current tick sits inside its range and where in that range it sits, the pool's gross and protocol-adjusted net 24h fee rates when its reported figures clear a plausibility gate, and conditional wait and recenter paths. Name one token id and declare its USD value and estimated recenter cost to add fixed-notional dollar effects and cost-only break-even; those two inputs are labelled as the caller's rather than derived from an unverified price feed. Every finding carries the numbers it was computed from, so you can check it against the chain yourself. Nothing is signed, approved, or moved.",
    "name": "Range Doctor",
    "services": [
      {
        "description": "A read-only diagnosis of the PancakeSwap v3 liquidity positions a BSC wallet holds or has staked: for each one, whether the current tick sits inside its range and where in that range it sits, the pool's gross and protocol-adjusted net 24h fee rates when its reported figures clear a plausibility gate, and conditional wait and recenter paths. Name one token id and declare its USD value and estimated recenter cost to add fixed-notional dollar effects and cost-only break-even; those two inputs are labelled as the caller's rather than derived from an unverified price feed. Every finding carries the numbers it was computed from, so you can check it against the chain yourself. Nothing is signed, approved, or moved.",
        "endpoint": "https://docket.gudman.xyz/hire/range-doctor",
        "name": "range-doctor",
        "protocol": "Web"
      }
    ],
    "type": "https://eips.ethereum.org/EIPS/eip-8004#registration-v1",
    "x402Support": true
  },
  "service_id": "range-doctor",
  "token_uri": "https://docket.gudman.xyz/agents/range-doctor.registration.json",
  "unsigned_transaction": {
    "chainId": 56,
    "data": "0xf2c298be0000000000000000000000000000000000000000000000000000000000000020000000000000000000000000000000000000000000000000000000000000003f68747470733a2f2f646f636b65742e6775646d616e2e78797a2f6167656e74732f72616e67652d646f63746f722e726567697374726174696f6e2e6a736f6e00",
    "from": "0xE4fe23FB57dbb9AC2f685ea29B6b9A1409A0d359",
    "gas": 163316,
    "gasPrice": 50000000,
    "nonce": 132,
    "to": "0x8004A169FB4a3325136EB29fA0ceB6D2e539a432",
    "value": 0
  }
}
```

### Full suite

Final run:

```powershell
./.venv/Scripts/python.exe -m pytest -q
```

```text
FAILED tests/test_advantage_v3_capture.py::test_running_the_capture_before_its_moment_exits_refused
1 failed, 1217 passed, 2 warnings in 48.53s
```

This is exactly the W1-owned, date-armed baseline failure named in the workstream brief. One
earlier full run also hit
`tests/test_execution_intent.py::test_the_same_intent_always_produces_the_same_key`.
Inspection showed its fixture hashes `deadline=now()+600` twice, so crossing a whole-second
boundary creates different keys. The isolated rerun passed (`1 passed in 0.67s`), and the
final full run did not reproduce it. No W5 file imports or changes that module.

`node --check docket/api/web/app.js` was not required because W5 did not touch `app.js`.

## Mutation table

| Test | Temporary break | Broken result | Restored result |
|---|---|---:|---:|
| `test_registration_documents_are_generated_from_the_catalogue` | Generator emitted `x402Support: false` | 1 failed | 1 passed |
| `test_identity_abi_matches_the_observed_contract_surface` | Renamed MetadataUpdate in the ABI artifact | 1 failed | 1 passed |
| `test_build_register_tx_estimates_and_builds_an_unsigned_bsc_transaction` | Added one to the estimated gas placed in the transaction | 1 failed | 1 passed |
| `test_decode_registration_extracts_the_registered_event_and_refuses_absence` | Matched the Transfer topic instead of Registered | 1 failed | 1 passed |
| `test_bind_agent_id_uses_the_marketplace_canonical_form` | Changed canonical chain prefix from 56 to 57 | 1 failed | 1 passed |
| `test_plan_cli_prints_an_unsigned_costed_plan_and_refuses_other_actions` | Shortened the planned token URI suffix | 1 failed | 1 passed |
| `test_identity_package_and_static_documents_are_declared_for_the_wheel` | Removed the nested registration package-data glob | 1 failed | 1 passed |
| `test_identity_module_has_no_signing_or_broadcast_surface` | Replaced `estimate_gas` with a forbidden submission call name | 1 failed | 1 passed |

All eight mutations were restored before the final suite.

## Could not do

- `docs/deliberation/JOINT-AUDIT-2026-08-22.md` is absent from this worktree and commit
  `fdf02cf`. It was read read-only from the main Docket worktree at the path named by the
  owner; W5 did not copy or edit it.
- No existing route defines the public token-URI path. W5 adopts
  `/agents/<service_id>.registration.json` as the integration contract because the CLI
  needs a deterministic URI. The integrator must implement those exact paths or coordinate
  a W5 URI change before any owner transaction.
- BscScan's HTML source page returned HTTP 403. Two RPCs, the live implementation bytecode,
  observed receipts, successful calls, and the official contract source GET agreed on the
  ABI used here.
- The four transactions, resulting agent IDs, registry bindings, allowlist, sweep, restart,
  and public route do not exist yet. They require owner and integrator action.
- The shared memory index was not updated because this workstream forbids every write outside
  its worktree.

## Owner and integrator actions

1. The owner explicitly approves and funds the registration wallet for four freshly estimated
   transactions plus their chosen gas margin.
2. The owner follows `docs/deployment-runbook.md:212` one service at a time: plan, inspect,
   sign in owner tooling, broadcast once, wait for the receipt, and decode the agent ID.
3. The owner hands the four service-to-ID pairs and receipts to the integrator.
4. The integrator exposes the four token-URI paths, sets each `agent_id` in
   `docket/marketplace/registry.py`, adds the IDs to `DOCKET_OWNED_AGENT_IDS`, runs the
   targeted refresh, and restarts the application.

## Out-of-scope edits

None. W5 changed only its allowed files plus this uncommitted report.

## Fix round — independent review findings (2026-08-22)

Commits: `fca978d` (`Generate complete ERC-8004 registration documents`) and
`ebe2639` (`Refuse registration plans with stale metadata`). No network write, signature,
broadcast, push, deploy, submission, or edit outside the W5 worktree occurred.

### Changes and review closure

- `docket/identity/register.py:30`, `:251`, and `:323` — closes finding 1. Plans now use
  `https://docket.gudman.xyz/registrations/<service_id>.json`, GET the URI without following
  redirects, require HTTP 200, and compare the served body SHA-256 with the exact committed
  bytes before Web3 is touched or an unsigned transaction is printed.
- `docket/identity/register.py:173` and `:239` — closes finding 2. The generator emits the
  full house object plus the separately documented `hireUrl`; accepts an explicit `clock` and
  optional minted `agent_id`; emits an empty pre-mint `registrations` array and the exact
  `eip155:56:0x8004a169fb4a3325136eb29fa0ceb6d2e539a432` entry post-mint; and renders
  deterministic UTF-8 bytes with a final newline.
- `docket/api/static/agents/range-doctor.registration.json:1`,
  `grid-operator.registration.json:1`, `yield-router.registration.json:1`, and
  `health-guard.registration.json:1` — regenerated from the fixed `2026-08-22T14:57:44Z`
  clock. Their SHA-256 values are respectively
  `93477a9bd857a096e224451da7d9f672a09f53c8807d55ee6d51db1a42db7be6`,
  `13995f47ff6b3e2762b26bdc774e7988dddcf2aceb9879f7a1b2b09da92cafab`,
  `5e89af968b77a4d0e5705d826f89a55f1296fc5086ac601b22ec9928c4c79225`, and
  `64fbedde9790f402834f3ae10a7305bced228a0f87c065895128c34c7f26c4bc`.
- `docket/identity/register.py:203` and the four generated documents — closes finding 3.
  `services[].endpoint` is the live GET `/services/<service_id>` discovery resource;
  `hireUrl` preserves the POST `/hire/<service_id>` action separately.
- `tests/test_identity_register.py:105`, `:173`, `:266`, and `:316` — closes finding 4 and
  pins all new behavior. Committed files are compared as bytes, not parsed JSON.
- `docs/deployment-runbook.md:223`, `:235`, `:266`, and `:279` — requires the integrator to
  serve the new paths from `docket/api/static/agents/`, requires exact-byte HTTP 200 before
  mint, documents explicit-clock post-mint regeneration at the same URI, and requires
  redeploy, byte confirmation, and an 8004scan re-parse. No `setAgentURI` call is needed.

### Fix-round exit-test evidence

Schema/URI tests were red before implementation:

```powershell
./.venv/Scripts/python.exe -m pytest -q tests/test_identity_register.py
```

```text
FAILED test_registration_documents_are_generated_from_the_catalogue
FAILED test_registration_document_adds_the_minted_identity_without_changing_its_url
FAILED test_plan_cli_prints_an_unsigned_costed_plan_and_refuses_other_actions
3 failed, 6 passed, 1 warning in 0.68s
```

Preflight tests were red before implementation:

```powershell
./.venv/Scripts/python.exe -m pytest -q tests/test_identity_register.py::test_plan_cli_prints_an_unsigned_costed_plan_and_refuses_other_actions tests/test_identity_register.py::test_plan_preflight_refuses_missing_or_changed_documents_before_web3
```

```text
3 failed, 1 warning in 0.70s
TypeError: main() got an unexpected keyword argument 'http_get'
```

Final focused tests and formatting:

```powershell
ruff format --check docket/identity/register.py tests/test_identity_register.py
ruff check docket/identity/register.py tests/test_identity_register.py
./.venv/Scripts/python.exe -m pytest -q tests/test_identity_register.py
git diff HEAD --check
```

```text
2 files already formatted
All checks passed!
...........                                                              [100%]
11 passed, 1 warning in 0.55s
```

The actual public URI still returns 404, so the required live CLI refuses and prints no
unsigned transaction:

```powershell
./.venv/Scripts/python.exe -m docket.identity.register plan --service range-doctor --from 0xE4fe23FB57dbb9AC2f685ea29B6b9A1409A0d359
```

```text
Exit code: 1
Traceback (most recent call last):
  File "<frozen runpy>", line 198, in _run_module_as_main
  File "<frozen runpy>", line 88, in _run_code
  File "docket\identity\register.py", line 378, in <module>
    raise SystemExit(main())
                     ^^^^^^
  File "docket\identity\register.py", line 338, in main
    preflight_registration(token_uri, document, http_get=http_get)
  File "docket\identity\register.py", line 264, in preflight_registration
    raise ValueError(
ValueError: registration preflight refused: GET https://docket.gudman.xyz/registrations/range-doctor.json returned HTTP 404, not 200
```

With the exact committed bytes supplied as the simulated deployed GET response, the same
plan used the live public BSC RPC and produced this compact transaction shape:

```powershell
@'
import contextlib
import io
import json
from pathlib import Path
from docket.identity.register import main

committed = Path("docket/api/static/agents/range-doctor.registration.json").read_bytes()

class Response:
    status_code = 200
    content = committed

def get(url, *, timeout, follow_redirects):
    return Response()

stdout = io.StringIO()
with contextlib.redirect_stdout(stdout):
    main(["plan", "--service", "range-doctor", "--from", "0xE4fe23FB57dbb9AC2f685ea29B6b9A1409A0d359"], http_get=get)
plan = json.loads(stdout.getvalue())
tx = plan["unsigned_transaction"]
print(json.dumps({
    "token_uri": plan["token_uri"], "chainId": tx["chainId"], "to": tx["to"],
    "from": tx["from"], "nonce": tx["nonce"], "gas": tx["gas"],
    "gasPrice": tx["gasPrice"], "value": tx["value"],
    "data_prefix": tx["data"][:10], "bnb_cost": plan["bnb_cost"],
}, indent=2))
'@ | ./.venv/Scripts/python.exe -
```

```text
{
  "token_uri": "https://docket.gudman.xyz/registrations/range-doctor.json",
  "chainId": 56,
  "to": "0x8004A169FB4a3325136EB29fA0ceB6D2e539a432",
  "from": "0xE4fe23FB57dbb9AC2f685ea29B6b9A1409A0d359",
  "nonce": 132,
  "gas": 163243,
  "gasPrice": 50000000,
  "value": 0,
  "data_prefix": "0xf2c298be",
  "bnb_cost": "0.00000816215"
}
```

Final full suite, after every mutation was restored:

```powershell
./.venv/Scripts/python.exe -m pytest -q
```

```text
FAILED tests/test_advantage_v3_capture.py::test_running_the_capture_before_its_moment_exits_refused
1 failed, 1220 passed, 2 warnings in 49.78s
```

This is only the named W1-owned date-armed baseline failure. `node --check
docket/api/web/app.js` was not required because this fix round did not touch `app.js`.

### Fix-round mutation table

| Test | Temporary break | Broken result | Restored result |
|---|---|---:|---:|
| `test_registration_documents_are_generated_from_the_catalogue` | Replaced required `supportedTrust: ["reputation"]` with an empty array | 1 failed | 11 passed |
| `test_registration_documents_are_generated_from_the_catalogue` byte lock | Changed only the indentation of `range-doctor.registration.json` | 1 failed | 11 passed |
| `test_registration_document_adds_the_minted_identity_without_changing_its_url` | Changed the emitted registration chain from 56 to 57 | 1 failed | 11 passed |
| `test_plan_preflight_refuses_missing_or_changed_documents_before_web3` HTTP case | Removed the explicit HTTP-200 guard | 1 failed; `_ExplodingW3` proved Web3 was reached | 11 passed |
| `test_plan_preflight_refuses_missing_or_changed_documents_before_web3` SHA case | Removed the SHA-256 equality guard | 1 failed; `_ExplodingW3` proved Web3 was reached | 11 passed |

All mutations were restored. `git status --short` then showed only `?? BUILD-REPORT.md`.

### Fix-round could not do

- `docs/deliberation/JOINT-AUDIT-2026-08-22.md` is absent from the checkout, all local refs,
  base `fdf02cf`, and all 1,122 local Git tree objects. Its sections 3 and 6 could not be
  read in this worktree. The available `CODEX-WIN-SPEC-2026-08-14.md` section 6 was read and
  explicitly retains the four registrations while cutting the broader BNB work.
- The new public paths still return HTTP 404. This workstream may not edit W3's routes or
  deploy, so the correct current behavior is refusal.
- No registration was signed or broadcast. Agent IDs, post-mint document bytes, registry
  bindings, the sweep, restart, and 8004scan re-parse therefore do not exist yet.
- Shared memory was not updated because this workstream forbids writes outside its worktree.

### Fix-round owner and integrator actions

1. The integrator serves each committed file at its exact `/registrations/<service_id>.json`
   URI from `docket/api/static/agents/` and deploys that mapping.
2. The owner confirms HTTP 200 with exact bytes by running `plan`, explicitly approves and
   funds each transaction, signs in owner tooling, broadcasts once, and waits for its receipt.
3. After each receipt, decode the integer ID, regenerate the same document with that ID and
   an explicit UTC clock value, redeploy the same URI, confirm exact bytes again, and request
   an 8004scan re-parse.
4. The integrator binds the four IDs, updates `DOCKET_OWNED_AGENT_IDS`, runs the one retained
   sweep, and restarts the application.

### Fix-round out-of-scope edits

None. The fix round changed only W5-owned identity code/tests, the four generated documents,
and the existing deployment runbook. This report remains uncommitted as required.
