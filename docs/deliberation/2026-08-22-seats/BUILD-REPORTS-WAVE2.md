# Wave-2 build reports (digest)
Base `build/integration` @ 5dce78d → `7aa3fc0`; 1450 tests pass.


---

# w6-hero-routes

# W6 build report — Pancake hero, registration route, and registry-agent actions

Built on `build/w6-hero-routes` from the wave-1 integration baseline. Commits:

- `ff2efe7 Build Pancake and agent action surfaces`
- `4abe077 Document and test W6 evidence routes`

The untracked joint audit and seat-report files were read but not edited, staged, or committed.

## Changes and closed audit items

### PancakeSwap hero and live evidence loop

- `docket/api/routes.py:609-645` closes JOINT-AUDIT §4 W6 item 1: advertises and content-negotiates `GET /pancake`, returns `Vary: Accept`, and gives the browser same-origin source routes plus the two README context observations.
- `docket/api/web/pancake.html:51-127` closes JOINT-AUDIT §4 W6 item 1 and §6's sponsor-proof priority: presents, in the required order, live decision, fixed-window record, economics, conditional actions, structural safety, v2 decision impact, and PancakeSwap context. The exact no-key/no-approval/no-transaction statement is at `pancake.html:98-107` and links to `/skill.md`.
- `docket/api/web/app.js:1977-2164` closes the live/data-integrity portion of W6 item 1: reads `/services/range-doctor`, reuses `exampleBody(record)`, posts to `record.hire_path`, reads every `/lp-record` line in sequence, reads `/advantage/v2.json`, and paints all figures from responses rather than from the HTML shell.
- `docket/api/web/style.css:871-1061` supplies the dependency-free evidence-dashboard presentation, table/action layout, and agent endpoint controls; `style.css:1147-1212` supplies the narrow viewport layout.
- `docket/api/web/index.html:39-40` and the other six existing page shells close the navigation item: every primary nav links `PancakeSwap` and renames the registry destination `Browse agents`.

### Byte-exact registration documents

- `docket/api/routes.py:107-121,647-657` closes JOINT-AUDIT §4 W6 item 2: loads exactly the four committed W5 registration files as bytes, serves `/registrations/{service_id}.json` as `application/json`, and returns the standard `registration_not_found` error otherwise.
- `tests/test_web_w6.py:68-95` proves all four bodies equal W5's committed bytes, preserve the final newline, and agree with W5's `REGISTRATION_BASE_URL`.

### Action on every registry-agent detail page

- `docket/api/routes.py:975-1056` closes JOINT-AUDIT §3's 506-dead-row finding and §4 W6 item 3: `POST /agents/{agent_id:path}/probe` accepts only the agent's stored A2A/MCP target, requires a callable declaration and last `responded` observation, shares the existing free-work allowance, calls the hardened `probe_one` in a worker thread with `trust_env=False`, appends the observation, and returns only the six-outcome vocabulary.
- `docket/api/web/app.js:2258-2372` adds “What you can do with this agent”: copyable observed A2A/MCP endpoints, dated outcome/status and existing explanation, x402 declaration, associated Docket service actions, and the exactly gated same-origin re-probe control. Web endpoints cannot enter the action list or gate.
- `docket/api/web/app.js:2373-2443` installs that action block on every `/agent?id=...` detail paint.

### Machine documentation and contract coverage

- `docket/api/static/llms.txt:55-64,188-202,282-289` and `docket/api/static/SKILL.md:35-68` close W6 item 4 by documenting all three new public paths, the probe gate/allowance, and the observation-only limits.
- `tests/test_web_w6.py:68-568` adds 21 W6 tests covering byte identity, the error contract, hardened-probe delegation/persistence/gates/rate limit/event-loop behavior, Pancake negotiation and runtime painting, documentation parity, agent actions, six-outcome wording, nav, and same-origin runtime sources.
- `tests/test_web_categories.py:35,423` extends the all-pages and exact-nav contracts to the new hero.

## Exit-test evidence

Baseline before edits:

```text
./.venv/Scripts/python.exe -m pytest -q
1366 passed, 2 warnings in 67.78s
```

Focused final contract run:

```text
./.venv/Scripts/python.exe -m pytest -q tests/test_web.py tests/test_web_categories.py tests/test_web_w6.py tests/test_services_api.py tests/test_api_contract.py tests/test_hire_api.py
179 passed, 2 warnings in 12.66s
```

New W6 file alone (includes the four registration byte comparisons):

```text
./.venv/Scripts/python.exe -m pytest -q tests/test_web_w6.py
21 passed, 2 warnings in 2.01s
```

Final full suite after both commits:

```text
./.venv/Scripts/python.exe -m pytest -q
1387 passed, 2 warnings in 62.84s (0:01:02)
```

The two warnings are the existing Starlette TestClient/httpx and websockets legacy deprecations.

```text
node --check docket/api/web/app.js
exit 0; no output

ruff.exe check docket/api/routes.py tests/test_web_w6.py tests/test_web_categories.py
All checks passed!

git diff --check HEAD
exit 0; no output
```

Installed behavior was checked before use: FastAPI 0.137.1, httpx 0.28.1, Pydantic 2.13.4, Starlette 1.6.0, and Node v24.15.0.

## Local rendered `/pancake` smoke

Command:

```text
./.venv/Scripts/python.exe -m uvicorn --factory docket.api:create_app --host 127.0.0.1 --port 58751
```

Playwright loaded `http://127.0.0.1:58751/pancake` at 1440×1000 and 390×844. Console result: `Total messages: 0 (Errors: 0, Warnings: 0)`. The narrow viewport had `innerWidth: 390`, document `scrollWidth: 390`, so there was no horizontal overflow. The eight browser requests were all to `127.0.0.1:58751`: HTML, CSS, JS, four same-origin GETs, and the one same-origin Range Doctor POST. The process was stopped and all smoke artifacts were removed.

Rendered section text/data:

1. **Live decision:** “Position 7141050 is below its range and currently earns no pool fees.” Position `7141050`; range state `below range`; BSC block `117454984`; observed `2026-08-22T16:20:15+00:00`. These values came from the live hire's read-only BSC observation.
2. **Fixed-window record:** “No rows are stored in the fixed-window record served by /lp-record.” The adjacent note says a surviving digest reference can expose editing/removal of the named prior row, but it is not a running hash, does not anchor unreferenced/final rows, authenticate the typist, provide an external timestamp, prove causality/returns, or prevent whole-chain rewriting; `/lp-record` does not run `verify_history`.
3. **Economics:** gross pool APR `98.65%`; protocol-adjusted net pool APR `66.10%`; relative overstatement `49.26%`; caller-declared fixed notional `$50.55`; annual gross/net/overstatement proxies `$49.87 / $33.41 / $16.46`; cost-only break-even `10.92 days`; post-hoc median payback delay `8.30 days across 231 candidate moves`. The rendered limitations identify these as fixed-notional and future-rate/cost proxies, not position earnings.
4. **Conditional actions:** the returned `RECENTER` and `WAIT` conditions, each with the returned PancakeSwap position deep link; the page states that opening a link does not submit an action.
5. **Structural safety:** “Range Doctor holds no key, requests no approval, and has no code path that sends a transaction,” followed by `/skill.md`.
6. **Decision impact:** median annual overstatement `$126.78` at `$10,000` fixed notional across `22` eligible pools; median payback delay `8.30 days` across the report's `231` candidate moves; ranking reversals `0/231`; registration state `post_hoc`, with the returned registration and realized-return limitations adjacent.
7. **PancakeSwap context:** first-party planner skills stop at generated deep links and Range Doctor keeps that plan-only boundary; the read-only subgraph observation was made `2026-08-22`, returned indexed time `2026-04-28T15:23:43Z`, and `hasIndexingErrors: true`; Docket instead reads the Explorer API and SHA-pins its response bytes.

The local default app had no configured `lp-record/controlled.jsonl`, so section 2 honestly rendered the empty state. The table painter itself was executed against observation → owner-decision → later-observation data in `tests/test_web_w6.py:423-566`; it preserved order and rendered below/in-range states, block/date/decision/digest columns, skipped-line and truncation warnings, and the integrity note.

## Mutation table

Every new test was exercised against a targeted broken implementation, then the implementation was restored and the new 21-test file was rerun green.

| Test group | Mutation introduced | Red evidence | Restored evidence |
|---|---|---|---|
| Four registration bytes + unknown registration | Disabled the registration route decorator | `pytest -q tests/test_web_w6.py -k registration` → `5 failed, 16 deselected` | W6 file → `21 passed` |
| Probe delegation, five non-responded gates, callable gate, allowance, event-loop health | Disabled the probe route decorator | `pytest -q tests/test_web_w6.py -k live_probe` → `9 failed, 12 deselected` | W6 file → `21 passed` |
| Pancake negotiation/source map | Disabled the Pancake route decorator | Exact route test → `1 failed` | Exact route test → `1 passed` |
| Runtime hero contract/dispatch | Renamed the `PAGES.pancake` dispatch entry | Exact frontend-contract test → `1 failed` | Exact test → `1 passed` |
| Runtime record/live/v2 painters | Replaced the live diagnosis decision with the fallback decision | Exact painter test → `1 failed` | Exact test → `1 passed` |
| Agent action copy/outcomes/gate | Changed the re-probe gate from `responded` to `timeout` | Exact executable action test → `1 failed` | Exact test → `1 passed` |
| A2A/MCP-only gate | Let a newer `web` response become the last probe | Exact executable action test → `1 failed` before the filter fix | Exact test → `1 passed` |
| Machine-document parity | Removed the registration path from `SKILL.md` | Exact docs test → `1 failed` | Exact test → `1 passed` |
| New page contract | Removed `pancake.html` from the all-pages set | Exact page-contract test → `1 failed` | Web suite → `92 passed` |
| Exact nav | Changed the homepage Pancake href | Exact navigation test → `1 failed` | Exact test → `1 passed` |
| Accept-cache correctness | Omitted `Vary: Accept` | Pancake negotiation test → `1 failed` | Exact test → `1 passed` |
| A2A/MCP display boundary | Let an unprobed web URL enter the action list | Executable action test → `1 failed` | Exact test → `1 passed` |

## Could not do

- I could not show real fixed-window rows in the local browser because this worktree has no configured controlled LP JSONL file. The UI and executable painter test cover the populated sequence, but the deployed data file is an owner/operations input.
- I did not deploy, touch the VPS, send a network write, sign/broadcast a transaction, or register an identity; all are forbidden for this workstream.
- I did not update the global Codex memory outside the worktree because the workstream explicitly forbids touching anything outside this worktree.

## OWNER actions

1. Integrate and deploy commits `ff2efe7` and `4abe077` through the owner-controlled release process.
2. Confirm the deployed service still mounts the controlled JSONL at the configured LP-record path so `/pancake` shows the observation/owner-decision history rather than the honest empty state.
3. Commit the owner-controlled untracked joint audit and seat reports separately; this branch deliberately does not contain them.

## Out-of-scope edits

None. No file outside the W6 scope was edited. `BUILD-REPORT.md` is the explicitly required uncommitted deliverable.

## Fix round

Commit: `5e8a4ce Isolate requested probes from snapshot coverage`

### Changes and finding closure

| Finding | Change | Source and tests |
|---|---|---|
| HIGH — public re-probes changed published snapshot coverage | Added the append-only `liveness_on_demand` table, kept sweep `liveness` unchanged, stored only a SHA-256 peer-address digest, and exposed the latest requested observation separately. `/stats` continues to read only sweep rows. The POST response states that the result is not part of snapshot coverage, and a timeout still closes the next re-probe gate. | `docket/store.py:94,816,839`; `docket/api/models.py:226`; `docket/api/routes.py:972,1010,1024,1057,1066`; `tests/test_web_w6.py:100-180` |
| LOW — probe route scanned every agent | Added an indexed `(snapshot_id, agent_id)` lookup and used it for both agent detail and re-probe requests. The route regression replaces `iter_agents` with a raising function while the request succeeds. | `docket/store.py:724`; `docket/api/routes.py:940,991`; `tests/test_web_w6.py:136-141` |
| HIGH — page did not distinguish capture evidence from requested evidence | The agent page labels the latest per-URL sweep observations and the latest on-demand re-probe separately, shows both timestamps/outcomes, and repeats the non-coverage statement after POST. Eligibility uses the latest requested row when one exists. | `docket/api/web/app.js:2225,2258,2311-2325,2379-2384`; `tests/test_web_w6.py:377-469` |
| INFO — empty LP record copy | `{"lines": []}` renders a panel saying “No record lines are mounted on this host.” and no table. | `docket/api/web/app.js:2010`; `tests/test_web_w6.py:535-545` |
| Response-contract documentation | Documented `latest_on_demand_observation`, `coverage_note`, separate persistence, and sweep/on-demand gating in both served machine documents. | `docket/api/static/llms.txt:25,168-207`; `docket/api/static/SKILL.md:35-53,129-132`; `tests/test_web_w6.py:317-332`; `tests/test_services_api.py:365-394` |

### Exit-test evidence

Baseline before fix-round edits:

```text
> .\.venv\Scripts\python.exe -m pytest -q
1387 passed, 2 warnings in 60.97s (0:01:00)
```

Focused restored backend, UI, documentation and adjacent contracts:

```text
> .\.venv\Scripts\python.exe -m pytest -q tests/test_web_w6.py tests/test_services_api.py tests/test_api_contract.py tests/test_store.py tests/test_coverage.py tests/test_web.py tests/test_web_categories.py
212 passed, 2 warnings in 12.44s

> ruff.exe format --check docket/store.py docket/api/models.py docket/api/routes.py tests/test_web_w6.py tests/test_services_api.py
5 files already formatted

> ruff.exe check docket/store.py docket/api/models.py docket/api/routes.py tests/test_web_w6.py tests/test_services_api.py
All checks passed!
```

Final suite on commit `5e8a4ce`:

```text
> .\.venv\Scripts\python.exe -m pytest -q
1387 passed, 2 warnings in 57.26s

> node --check docket/api/web/app.js
[no output; exit 0]

> git diff --check HEAD
[no output; exit 0]
```

The warnings are the existing `websockets.legacy` deprecation and FastAPI TestClient's Starlette/httpx deprecation.

### Fix-round mutation table

Every mutation below was temporary, produced the stated red result, and was restored before the 212-test focused run and final full suite.

| Test | Temporary broken behavior | Red evidence |
|---|---|---|
| `test_live_probe_records_on_demand_without_changing_snapshot_coverage` | Wrote the timeout back to `record_liveness` | 1 failed: the byte-stable `/stats` response changed at byte 365 |
| same | Restored the full `iter_agents` scan | 1 failed: `the probe route must use the snapshot agent primary key` |
| same | Stored raw `request.client.host` instead of its digest | 1 failed: stored `testclient` instead of the expected SHA-256 |
| same | Ignored the latest on-demand timeout when gating the next probe | 1 failed: second request returned 200 instead of 409 |
| `test_agent_listings_stay_raw_while_detail_carries_the_reverse_marketplace_link` | Removed `latest_on_demand_observation` from `AgentDetail` | 1 failed: response omitted the required separate field |
| `test_agent_action_block_renders_endpoint_evidence_and_exact_reprobe_gate` | Gated the browser control from sweep rows only | 1 failed: `an on-demand timeout left the re-probe control enabled` |
| `test_pancake_painters_render_runtime_rows_figures_and_actions` | Restored the old empty-record sentence | 1 failed: `empty record did not explain the missing host mount` |
| `test_w6_paths_are_in_both_machine_documents` | Removed the non-coverage statement from `SKILL.md` | 1 failed: required phrase absent |

### Could not do

- No production database or mounted LP journal is present in this worktree, so the fix round did not inspect production rows. The API/UI tests exercised both populated sweep-plus-on-demand data and the exact empty `{"lines": []}` response.
- No deployment, VPS access, network write, transaction, signing, push, or submission was performed; all are forbidden for this workstream.

### OWNER actions

1. Integrate and deploy `5e8a4ce` through the owner-controlled release process. Opening the existing database with `Store` creates `liveness_on_demand`; no destructive migration is required.
2. After deployment, confirm `/stats` is unchanged across a controlled on-demand timeout and that `/agents/{id}` shows the sweep and requested observations separately.
3. Confirm the production LP journal mount remains configured; otherwise `/pancake` will intentionally show “No record lines are mounted on this host.”

### Fix-round out-of-scope edits

None. The fix changed only W6 API/store, agent/Pancake UI, served machine documentation, and their tests. This report remains uncommitted as required.


---

# w7-seats-lock

# W7 build report — evaluator seats and Warden lock machinery

Date: 2026-08-22  
Branch: `build/w7-seats-lock`  
Base: `5dce78d` (`build/integration`)  
Commits: `576cd49`, `f4e7ca7`, `7d4d258`, `319b9a4`, `952c510`

## Changes and audit closure

| Change | Evidence | Audit item closed |
|---|---|---|
| Added the packaged evaluator-seat namespace and shared raw-byte subprocess boundary. The boundary writes stdin to a temporary file, runs from an empty scratch directory, preserves nonempty response bytes without trimming, maps nonzero/empty/non-bytes to no response, kills the process tree at the hard timeout, and bounds the post-kill pipe wait. | `docket/advantage/v3/seats/__init__.py:1`; `docket/advantage/v3/seats/record.py:13,32,63,101,129,164,183`; `pyproject.toml:32` | Audit backlog 16: the driver-owned-no-timeout finding; joint audit §6 Aug-25 Warden seat machinery exit. |
| Added the Codex adapter, exact last-message-file capture, CLI-reported model extraction, version/model/argv provenance in `model_build`, and the requested real-CLI self-test. | `docket/advantage/v3/seats/codex_cli.py:15,52,70,87,114` | Audit backlog 16: replace the synthetic-only callable boundary with an operator-callable seat. |
| Added the Claude adapter, safe-mode/tool-free invocation, raw stdout capture, and resolved primary-model discovery from the CLI's JSON usage metadata. | `docket/advantage/v3/seats/claude_cli.py:13,35,62,97,115` | Audit backlog 16 and joint audit §6 Aug-25 two-seat exit. |
| Let the calibration CLI obtain `model_build` from the selected seat and refuse shared or already-captured seats before the provenance lookup can contact a model. The existing first-write request/response schema was not changed. | `docket/advantage/v3/calibration_driver.py:95,206,253-275` | Audit backlog 16: real CLI driver seam while preserving first-write capture. |
| Added Warden envelope assembly from the authored 12 cases, vendor snapshot, authored eight-case key, and both first-write captures. The path calls `verify_calibration_capture`, validates the exact deterministic bytes before writing, creates inputs exclusively, accepts only an identical interrupted-write retry, locks through `lock_inputs`, and atomically replaces the saved stage-one spec. | `docket/advantage/v3/assemble.py:49,53,324,345,357,371,396-421` | Joint audit §6 Aug-25 `inputs/03-security-heldout.json` lock exit; audit backlog 16 key/capture promotion; W1 L2 capture-verification requirement. |
| Added fake-PATH CLI tests for raw bytes, invalid/absent results, nonzero exits, hard timeout and descendant death, bounded failed-kill cleanup, version refusal, cwd/argv/environment isolation, model/command provenance, pre-probe refusal, self-test, synthetic end-to-end Warden lock, capture verification, and interrupted-save recovery. | `tests/test_advantage_v3_seats.py:147-472`; `tests/test_advantage_v3_assemble.py:446-507` | Behavioral proof for all W7 machinery; no real calibration call is hidden in the suite. |
| Documented the two exact seat commands, distinct-session rule, artifact locations, metadata probe, isolation limits, and one-command Warden lock. | `docs/evidence-reproduction.md:114-162` | Joint audit §6 Aug-25 operator runbook. |

## Exit-test evidence

Baseline before W7:

```text
./.venv/Scripts/python.exe -m pytest -q
1366 passed, 2 warnings in 59.00s
```

Installed CLI framing was verified before relying on the adapters. The Codex check used `codex exec --sandbox danger-full-access -C <empty> --skip-git-repo-check --ignore-user-config --ignore-rules --ephemeral --color never -o <file> -`: return code 0; the output file was exactly 21 bytes (`SEAT_CLI_SELF_TEST_OK`, no newline); stdout was 22 bytes with one LF; transcript model line was `model: gpt-5.6-sol`. `codex --version` returned `codex-cli 0.147.0`. The Claude adapter's exact stdin path used `claude --print --safe-mode --no-chrome --no-session-persistence --disable-slash-commands --strict-mcp-config --tools '' --permission-mode dontAsk --prompt-suggestions false --output-format text` from an empty cwd: return code 0; stdout was exactly 19 bytes (`W7-CLAUDE-STDIN-OK` plus one LF, hex `57372d434c415544452d535444494e2d4f4b0a`); stderr was empty. `claude --version` returned `2.1.239 (Claude Code)`.

Requested read-only self-test, run once:

```text
./.venv/Scripts/python.exe -m docket.advantage.v3.seats.codex_cli --self-test
bytes=21
model_build=version=codex-cli 0.147.0; model=gpt-5.6-sol; command=<home> exec --sandbox danger-full-access -C . --skip-git-repo-check --ephemeral --ignore-user-config --ignore-rules --disable plugins --color never -o ..\last-message.bin -
```

Focused final checks:

```text
ruff format --check docket/advantage/v3/assemble.py docket/advantage/v3/calibration_driver.py docket/advantage/v3/seats/record.py tests/test_advantage_v3_seats.py tests/test_advantage_v3_assemble.py
5 files already formatted

ruff check docket/advantage/v3/assemble.py docket/advantage/v3/calibration_driver.py docket/advantage/v3/seats/record.py tests/test_advantage_v3_seats.py tests/test_advantage_v3_assemble.py
All checks passed!

./.venv/Scripts/python.exe -m pytest -q tests/test_advantage_v3_seats.py tests/test_advantage_v3_calibration.py tests/test_advantage_v3_assemble.py
52 passed in 19.81s

git diff --check 5dce78d..HEAD
<no output; exit 0>
```

Final full suite:

```text
./.venv/Scripts/python.exe -m pytest -q
1389 passed, 2 warnings in 71.74s (0:01:11)
```

The two warnings are the pre-existing `websockets.legacy` deprecation and Starlette/httpx transition warning. `node --check docket/api/web/app.js` was not applicable because W7 did not touch that file.

## Mutation checks

Each mutant below was applied alone, its named new test was run, and the implementation was restored. The focused and full green runs above were performed after restoration.

| New-test behavior | Deliberate mutant | Mutant result |
|---|---|---|
| Preserve raw response bytes | Trim the CLI response | `2 failed in 1.08s` |
| Reject `str`, empty bytes, and `None` | Accept `str` as a response | `2 failed, 4 passed in 0.47s` |
| Reject nonzero CLI exit | Ignore the subprocess return code | `2 failed in 0.84s` |
| Timeout kills descendants | Kill only the wrapper process | `2 failed in 37.69s` |
| Failed tree kill cannot leave an unbounded pipe wait | Leave timed-out pipes open | `1 failed in 0.18s` |
| Version command failure refuses provenance | Ignore the version return code | `2 failed in 1.28s` |
| Pin the CLI-owned model and record the exact command | Omit the resolved model from the seat command | `1 failed, 1 passed in 1.67s` |
| Driver stores seat-owned provenance | Bypass the seat's `model_build` callable | `1 failed in 0.48s` |
| Spent/shared seats refuse before provenance | Skip the pre-probe refusal block | `1 failed in 0.19s` |
| Codex self-test reports the actual response length | Print a fixed length | `1 failed in 0.87s` |
| Warden command saves a nonempty real lock | Skip the stage-two spec save | `1 failed in 0.48s` |
| Warden assembly enforces first-write capture verification | Skip `verify_calibration_capture` | `1 failed in 0.43s` |
| Interrupted spec save preserves stage one and is retryable | Write the locked spec directly to the registered path | `1 failed in 0.19s` |

## Could not do, and why

- **Zero real calibration runs were performed here. Zero real Warden inputs were locked.** The brief reserves both registered seats and the real lock for the Aug-25 operator event. The only model calls were the required harmless CLI-framing checks and the requested Codex self-test; none used the calibration key or derived calibration prompt.
- Codex 0.147.0 cannot meet a hard “instruction-free and cannot read the repository” boundary under the required `--sandbox danger-full-access`. Local `codex debug prompt-input` confirmed the user's global `AGENTS.md` remains model-visible; installed help exposes no instruction-disable flag. A clean `CODEX_HOME` removes those instructions but `codex login status` then reports `Not logged in`. The adapter supplies an empty cwd and strips repository-bearing environment context, but that is contextual isolation, not OS confinement. This limitation is explicit in the runbook.
- No command field was added to calibration request/response JSON: `calibration.py` rejects extra fields and those exact records are digest-linked. The existing `model_build` field carries the verified version, resolved model, and exact argv instead.
- Shared Codex/Claude memory was not updated because that location is outside this worktree and the W7 hard scope forbids external writes.

## OWNER actions

1. Before Aug 25, decide whether the disclosed Codex contextual isolation is acceptable. If a hard filesystem/instruction boundary is required, do not run `seat-a` until a clean authenticated Codex profile mechanism is available and verified.
2. On Aug 25, run the two commands in `docs/evidence-reproduction.md:124-133` exactly once, with distinct session IDs. Each new seat performs one fixed metadata query before its captured calibration prompt. Preserve and review every request/response artifact, including `no_response`.
3. If both seats satisfy the registered 7-of-8 and 0.80 micro-F1 floors, run the lock command at `docs/evidence-reproduction.md:153-156`. Review and commit both capture directories, the generated input, and the updated spec together before any scored arm.

## Out-of-scope edits

None. The owner-untracked joint audit and seat-report directory were read but not modified or staged. No push, deployment, transaction, funded signature, network write, or real registered run occurred.


---

# w8-release

# W8 build report — guarded release tooling

Branch: `build/w8-release`

Commits:

- `fbc638b Add guarded staged release tooling`
- `ac082e8 Document the guarded release procedure`
- `bb3aa4b Harden release identity and health checks`
- `6cfc5a3 Pin release host safety guards`
- `6dd6e7c Ensure service-readable release environments`

This report is intentionally uncommitted. No push, deploy, VPS access, nginx change,
service action, transaction, signature, submission, or network write occurred.

## Changes and audit closure

| Change | Location | Audit item closed |
|---|---|---|
| Added a root-only release entry point with strict 40-hex commit and 64-hex wheel inputs, exact SHA-256 verification, wheel metadata parsing, commit-named venv identity markers, `pip install`, `pip check`, and `pip show docket` version comparison. Existing venvs are reused only when the full commit, wheel digest, and version all match. | `deploy/release.sh:1`, `:98`, `:145`, `:177`, `:183`, `:187` | W8 Build 1; source/deploy manifest identity rule; operational-evidence rule that release identities are computed, never padded or typed. |
| Requires the existing canary config/token, checks real-host `0640 root:docket` ownership, stages the complete deploy bundle, writes the computed full commit and wheel record, stops the canary timer, proves the canary service inactive, and stops the app only afterward. | `deploy/release.sh:141`, `:231`, `:249`, `:408` | W8 Build 1; prevents a paid/canary run crossing the swap and preserves host-managed configuration. |
| Performs back-up-then-replace without deletion, flips `.venv` through a temporary link plus `mv -T`, retains the prior release, and tracks swap state for failure recovery. | `deploy/release.sh:249`, `:287`, `:415` | W8 Build 1; production copied-release topology. |
| Backs up installed units and timer states, retires an installed Aug-21 capture timer, prints unified diffs, copies only changed bytes, daemon-reloads, enables `docket.service`, and enables the canary, LP-record, refresh, and Aug-26 capture timers. | `deploy/release.sh:326`, `:421`, `:438`, `:450`, `:469`, `:480` | Joint audit §3 F1 and §6 Aug 24/Aug 29-30; W8 Build 1. No tracked systemd unit required an edit. |
| Polls `/health` for up to 30 seconds and requires `status=ok`; asserts the documented coverage/refresh fields on `/stats` and service/admission fields on `/services`. | `deploy/release.sh:303`, `:485`, `:495`, `:508` | W8 Build 1; avoids the known false outage at six seconds and binds the served contract after the swap. |
| On any post-stop failure, retains the failed tree, restores the prior release and link, restores prior unit content/state, restarts the prior app, rechecks health, and exits non-zero with the original reason. | `deploy/release.sh:326`, `:355`, `:379` | W8 Build 1 rollback requirement. |
| Added sandboxed `--dry-run`: every managed absolute path is mapped below `DOCKET_RELEASE_ROOT`; filesystem transitions execute there, host commands are traced only, and injected read commands drive deterministic local tests. | `deploy/release.sh:6`, `:33`, `:62`; `deploy/preflight.sh:6`, `:20` | W8 Build 4 local-test requirement. |
| Added preflight gates for exact nginx warning count plus `test is successful`, at least 2 GiB free under `/opt`, all eight unit files through `systemd-analyze verify`, and `journalctl --disk-usage`. It contains no nginx write or reload. | `deploy/preflight.sh:1`, `:73`, `:82`, `:90`, `:106`, `:116` | W8 Build 2; 22-warning house guard. |
| Added the persistent judging-window journal policy. Release installs it only when absent, restarts journald once, and refuses a differing existing host policy before downtime. | `deploy/journald-docket.conf:1`; `deploy/release.sh:239`, `:470` | Joint audit §3 F1; W8 Build 3. |
| Replaced the manual copied-release and refresh-unit procedures with computed tar-over-SSH shipping, preflight, SQLite backup, guarded release, automatic rollback, one-time journal-loss warning, and post-release version/body/timer evidence commands. | `docs/deployment-runbook.md:58`, `:132`, `:168`, `:225`, `:265`, `:319` | W8 Build 5 and source/deploy evidence parity. |
| Added Windows Git Bash regression coverage for syntax, SHA refusal, venv collision, installed-version mismatch, canary files/ownership/order, nginx non-mutation, rollback, strict health, Aug-21 retirement, four timers, content-diff unit copies, journald one-time install/conflict, served contracts, and every preflight gate. | `tests/test_release_scripts.py:174`, `:186`, `:207`, `:232`, `:261`, `:283`, `:296`, `:305`, `:344`, `:365`, `:404`, `:440`, `:484`, `:510`, `:534`, `:564` | W8 Build 4 and all release behavior above. |

I folded unit installation into `release.sh`. Unit backup/restore and timer-state rollback
share the release swap state; a separate installer would split one atomic failure path across
two processes without adding a second caller.

## Exit-test evidence

### Baseline before changes

```text
> .\.venv\Scripts\python.exe -m pytest -q
1366 passed, 2 warnings in 59.42s
```

### Red test before implementation

```text
> .\.venv\Scripts\python.exe -m pytest -q tests\test_release_scripts.py
14 failed, 1 passed in 7.01s
```

The passing case was the pre-existing `deploy/install-canary.sh` syntax check. Every new
release/preflight behavior was red because the scripts did not exist.

### Final focused tests

```text
> .\.venv\Scripts\python.exe -m pytest -q tests\test_release_scripts.py
25 passed in 24.50s

> .\.venv\Scripts\python.exe -m pytest -q tests\test_release_scripts.py tests\test_canary_deploy.py tests\test_refresh.py
35 passed, 2 warnings in 22.79s
```

### Syntax, lint, formatting, and committed diff

```text
> "C:\Program Files\Git\bin\bash.exe" -n deploy/release.sh
[no output; exit 0]
> "C:\Program Files\Git\bin\bash.exe" -n deploy/preflight.sh
[no output; exit 0]
> "C:\Program Files\Git\bin\bash.exe" -n deploy/install-canary.sh
[no output; exit 0]
> ruff.exe check tests\test_release_scripts.py
All checks passed!
> ruff.exe format --check tests\test_release_scripts.py
1 file already formatted
> git diff HEAD --check
[no output; exit 0]
```

`shellcheck` is not installed in PowerShell or Git Bash, so the required fallback was
`bash -n` plus the executable dry-run suite.

### Final full suite

```text
> .\.venv\Scripts\python.exe -m pytest -q
1391 passed, 2 warnings in 88.51s (0:01:28)
```

The warnings are the existing `websockets.legacy` and FastAPI/Starlette httpx-adapter
deprecations. `docket/api/web/app.js` was not touched, so the conditional `node --check`
gate did not apply.

## Dry-run transcript

The local transcript below is from a successful fake-root run. Only the repeated temporary
directory prefix is normalized to `<fake-root>`; the test wheel digest belongs only to this
generated fixture.

```text
exit=0
+ sha256sum <fake-root>/docket-0.1.0-py3-none-any.whl
+ python3 - <fake-root>/docket-0.1.0-py3-none-any.whl
+ install -d -m 0755 <fake-root>/root/opt <fake-root>/root/opt/docket-venvs
+ umask 022
+ python3 -m venv <fake-root>/root/opt/docket-venvs/aaaaaaaaaaaa
+ <fake-root>/root/opt/docket-venvs/aaaaaaaaaaaa/bin/python -m pip install -- <fake-root>/docket-0.1.0-py3-none-any.whl
+ <fake-root>/root/opt/docket-venvs/aaaaaaaaaaaa/bin/python -m pip check
+ <fake-runuser> -u docket -- <fake-root>/root/opt/docket-venvs/aaaaaaaaaaaa/bin/python -c import\ docket\,\ docket.api\,\ docket.canary
+ <fake-root>/root/opt/docket-venvs/aaaaaaaaaaaa/bin/python -m pip show docket
+ install -d -m 0755 <fake-root>/root/opt/docket.stage-aaaaaaaaaaaa/deploy
+ cp -a deploy/. <fake-root>/root/opt/docket.stage-aaaaaaaaaaaa/deploy/
+ systemctl stop docket-canary.timer
+ systemctl is-active --quiet docket-canary.service
+ systemctl stop docket.service
+ mv -- <fake-root>/root/opt/docket <fake-root>/root/opt/docket.bak-20260822T120000Z
+ mv -- <fake-root>/root/opt/docket.stage-aaaaaaaaaaaa <fake-root>/root/opt/docket
+ ln -sfn <fake-root>/root/opt/docket-venvs/aaaaaaaaaaaa <fake-root>/root/opt/docket/.venv.new-aaaaaaaaaaaa
+ mv -Tf <fake-root>/root/opt/docket/.venv.new-aaaaaaaaaaaa <fake-root>/root/opt/docket/.venv
Unit differs: docket-v3-capture.timer (retiring Aug-21 schedule)
+ systemctl disable --now docket-v3-capture.timer
Installing new unit: docket-canary.service
Installing new unit: docket-canary.timer
Installing new unit: docket-lp-record.service
Installing new unit: docket-lp-record.timer
Installing new unit: docket-refresh.service
Installing new unit: docket-refresh.timer
Installing new unit: docket-v3-capture.service
Installing new unit: docket-v3-capture.timer
+ systemctl daemon-reload
+ systemctl restart systemd-journald
Persistent journald configured; the former volatile journal was lost at this restart.
+ systemctl enable --now docket.service
+ systemctl enable --now docket-canary.timer
+ systemctl enable --now docket-lp-record.timer
+ systemctl enable --now docket-refresh.timer
+ systemctl enable --now docket-v3-capture.timer
+ <fake-curl> -fsS http://127.0.0.1:8090/health
Health accepted on attempt 1 of 2.
+ <fake-curl> -fsS http://127.0.0.1:8090/stats
+ <fake-curl> -fsS http://127.0.0.1:8090/services
Release complete: aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa (0.1.0), wheel 15e41af65d1b4768c4dbebda19b37bea6f356c5ed48bd68b83433eb802e019a4.
```

## Mutation table

Each mutant was applied alone, its named test was red, and the exact production code was
restored before the next mutant. The final focused and full suites above ran after all
restorations.

| Test / temporary mutation | Mutant result | Restored result |
|---|---:|---:|
| Bash syntax — remove `then` from `release.sh` | 1 failed, 2 passed | syntax clean |
| Wheel SHA — bypass digest equality | 1 failed; metadata error replaced required SHA refusal | 25 passed |
| Existing venv — bypass full commit/digest/version comparison | 1 failed | 25 passed |
| Installed version — ignore `pip show`/wheel version mismatch | 1 failed | 25 passed |
| Canary config — bypass missing-config refusal | 1 failed, 1 passed | 2 passed |
| Canary token — bypass missing-token refusal | 1 failed, 1 passed | 2 passed |
| Canary ownership — change token requirement from `0640` to `0600` | 1 failed | 1 passed |
| Canary ordering — stop the app before checking canary inactivity | 1 failed | 1 passed |
| nginx isolation — add `systemctl reload nginx` to release | 1 failed | 1 passed |
| Post-swap rollback — disable the exit-trap rollback branch | 1 failed; new tree remained live | 1 passed |
| Strict health — accept `no_snapshot` as healthy | 1 failed | 1 passed |
| Old capture timer — detect Aug 20 instead of Aug 21 | 1 failed | 1 passed |
| Four timers — omit `docket-refresh.timer` from the enable list | 1 failed | 1 passed |
| Release identity — write only commit12 to the live record | 1 failed | 1 passed |
| Unit compare — install an identical unit instead of continuing | 1 failed; mtime changed | 1 passed |
| Journald one-time install — overwrite/restart when target already matched | 1 failed | 1 passed |
| Journald conflict — bypass differing-target refusal | 1 failed; release incorrectly succeeded | 1 passed |
| `/stats` contract — bypass the post-swap field assertion | 1 failed; release incorrectly succeeded | 1 passed |
| `/services` contract — bypass the post-swap field assertion | 1 failed; release incorrectly succeeded | 1 passed |
| Preflight warning baseline — accept any count at or below 22 | 1 failed | 6 passed |
| Preflight success text — bypass `test is successful` requirement | 1 failed | 6 passed |
| Preflight nginx exit — ignore non-zero `nginx -t` | 1 failed, 5 passed | 6 passed |
| Preflight disk — bypass the 2 GiB threshold | 1 failed | 6 passed |
| Preflight unit verification — ignore non-zero `systemd-analyze verify` | 1 failed | 6 passed |
| Preflight journal check — ignore non-zero `journalctl --disk-usage` | 1 failed | 6 passed |
| Preflight GO boundary — raise the minimum by 1 KiB | 1 failed | 1 passed |

## Could not do

- The workstream forbids VPS access, so the scripts were not run against production. No live
  systemd, journald, nginx, `/health`, `/stats`, or `/services` claim is made.
- `shellcheck` is absent. GNU Bash 5.3.9 `bash -n`, 25 dry-run tests, and the complete Python
  suite are the available local evidence.
- Persistent journald's first restart necessarily loses the currently volatile journal. The
  release and runbook state that cost before the owner runs anything.
- The nginx rate-limit example remains a separate owner-reviewed host change. W8 neither
  installs it nor reloads nginx.
- Shared memory was not updated because this workstream explicitly forbids writes outside
  this worktree.

## OWNER commands — not run

Run the release only from Git Bash after the integrated commit has passed the release gates.
The local values are computed first:

```bash
repo_root=$(pwd -P)
source_commit=$(git rev-parse HEAD)
wheel=$(realpath /path/outside/checkout/dist/docket-0.1.0-py3-none-any.whl)
wheel_name=$(basename "$wheel")
wheel_sha=$(sha256sum "$wheel" | awk '{print $1}')
remote_bundle="/var/tmp/docket-release-${source_commit:0:12}"
```

These are exactly the SSH commands the integrator runs:

```bash
ssh root@gudman.xyz "install -d -o root -g root -m 0700 '$remote_bundle'"
tar -cf - -C "$repo_root" deploy -C "$(dirname "$wheel")" "$wheel_name" | ssh root@gudman.xyz "tar -xf - -C '$remote_bundle'"
ssh root@gudman.xyz "bash '$remote_bundle/deploy/preflight.sh' 22"
ssh root@gudman.xyz 'stamp=$(date -u +%Y%m%dT%H%M%SZ); install -d -o root -g root -m 0700 /var/backups/docket; /opt/docket/.venv/bin/python -c '\''import sqlite3,sys; source=sqlite3.connect("/var/lib/docket/data/agents.sqlite3"); destination=sqlite3.connect(sys.argv[1]); source.backup(destination); destination.close(); source.close()'\'' "/var/backups/docket/agents-${stamp}.sqlite3"'
ssh root@gudman.xyz "bash '$remote_bundle/deploy/release.sh' '$remote_bundle/$wheel_name' '$source_commit' '$wheel_sha'"
ssh root@gudman.xyz 'readlink -f /opt/docket/.venv; cat /opt/docket/RELEASE-commit.txt /opt/docket/WHEEL-sha256.txt; /opt/docket/.venv/bin/python -c '\''import importlib.metadata as metadata; print(metadata.version("docket"))'\''; /opt/docket/.venv/bin/python -m pip check'
ssh root@gudman.xyz 'curl -fsS http://127.0.0.1:8090/services | sha256sum; curl -fsS http://127.0.0.1:8090/stats; systemctl list-timers docket-canary.timer docket-lp-record.timer docket-refresh.timer docket-v3-capture.timer'
```

Do not run the release if preflight is NO-GO. Do not apply or reload the nginx rate-limit
example as part of this release; it remains the owner's separate reviewed operation.

## Out-of-scope edits

None. No `deploy/systemd/*`, `deploy/docket-canary.conf.example`, `deploy/install-canary.sh`,
`docket/**`, or other test file changed.

## Fix round — Fable 5 audit findings (2026-08-22)

### Changes and audit closure

| Finding | Change | Location |
|---|---|---|
| HIGH — a new root-owned venv inherited global `umask 027`, making its directories and files unreadable by the `docket` service account. | Venv creation and wheel installation now run in a subshell under `umask 022`; the outer release remains under `027`. After `pip check`, the real release requires `runuser -u docket -- <venv-python> -c "import docket, docket.api, docket.canary"` to succeed before any service stop or release move. Dry-run traces the command and executes an injected `DOCKET_RELEASE_RUNUSER` when supplied. | `deploy/release.sh:146`, `:174`, `:192`; `tests/test_release_scripts.py:262`, `:286`; `docs/deployment-runbook.md:97` |
| LOW — rollback can restore the retired Aug-21 capture timer. | The rollback runbook now says that prior unit contents and enabled/active states are deliberately restored, so the elapsed Aug-21 timer may reappear in `list-timers`; its restored `Persistent=false` policy prevents catch-up. | `docs/deployment-runbook.md:331` |
| LOW — release identity through `/health`. | No code change: `docket/api/routes.py:642` returns status and snapshot fields but no commit. Post-deploy identity remains the installed-version check from `pip show docket` plus the full `RELEASE-commit.txt` marker; the existing post-release command also collects the wheel digest. | `deploy/release.sh:200`, `:213`, `:284`; `docs/deployment-runbook.md:170` |

Commit: `6dd6e7c Ensure service-readable release environments`.

### Exit-test evidence

The two regressions were red before the production change:

```text
> .\.venv\Scripts\python.exe -m pytest -q tests\test_release_scripts.py::test_release_creates_and_installs_a_new_venv_under_umask_022 tests\test_release_scripts.py::test_release_refuses_an_unusable_venv_before_stopping_services
2 failed in 4.49s
```

Final focused and static checks after both mutations were restored:

```text
> .\.venv\Scripts\python.exe -m pytest -q tests\test_release_scripts.py
27 passed in 45.62s

> ruff.exe check tests\test_release_scripts.py
All checks passed!

> ruff.exe format --check tests\test_release_scripts.py
1 file already formatted

> git diff --check
[no output; exit 0]
```

Final exit checks from commit `6dd6e7c`:

```text
> .\.venv\Scripts\python.exe -m pytest -q
1393 passed, 2 warnings in 101.59s (0:01:41)

> "C:\Program Files\Git\bin\bash.exe" -n deploy/release.sh
[no output; exit 0]

> "C:\Program Files\Git\bin\bash.exe" -n deploy/preflight.sh
[no output; exit 0]
```

The two warnings are the existing `websockets.legacy` and FastAPI/Starlette httpx-adapter
deprecations. `docket/api/web/app.js` was untouched, so `node --check` did not apply.

### Mutation table

Each production mutation was applied alone and restored before the next one and before the
final suite.

| Test | Temporary production mutation | Mutant result | Restored result |
|---|---|---:|---:|
| `test_release_creates_and_installs_a_new_venv_under_umask_022` | Removed `run_fs umask 022` from the new-venv subshell. | 1 failed in 8.01s | 1 passed in 2.17s |
| `test_release_refuses_an_unusable_venv_before_stopping_services` | Replaced the dry-run/real-run guard condition with `false`, bypassing the service-user import. | 1 failed in 8.90s; release returned 0 | 1 passed in 0.60s |

### Could not do

- This workstream forbids VPS access, so the real host's service account and installed
  `/opt/docket-venvs/*` permissions were not rechecked here. The executable dry-run used an
  injected failing `runuser` and proved refusal precedes every stop and move.
- `/health` cannot bind a release commit because the current route has no commit field. No
  response-shape assertion was invented; the version and full-commit marker pair remains the
  release identity check.
- No push, deploy, systemd action, nginx action, network write, signature, transaction, or
  submission occurred.

### OWNER actions

- After integration and the existing release gates, the owner may run the documented release.
  The script now checks the `docket` user's imports before downtime; no new configuration is
  required.
- If automatic or later rollback restores the elapsed Aug-21 capture timer, treat its presence
  in `systemctl list-timers` as expected. Its restored `Persistent=false` setting means it will
  not run late.

### Out-of-scope edits

None. The fix round changed only `deploy/release.sh`, `tests/test_release_scripts.py`, and
`docs/deployment-runbook.md`. This report remains uncommitted.


---

# w9-evidence-parity

# W9 build report — evidence parity

Branch: `build/w9-evidence-parity`
Base merge-base with `build/integration`: `5dce78d00dc83857912c191c88a6cbc2688e7e08`

Commits:

- `5c26cb4` — Record live category reads through the hire catalogue
- `75c5055` — Populate category cards from recorded reads
- `87aa503` — Regenerate category registration documents
- `ebd341e` — Cover recorder CLI parsing

## Changes and audit closure

| Change | File:line | Audit/build item closed |
|---|---|---|
| Added a single-read recorder that resolves `get_service`, invokes the same `Service.run(payload)` callable used by the hire route, hashes request/result with `docket.hire.receipts.canonical_hash`, records elapsed monotonic time and full response, refuses empty/error/semantically incomplete reads, and writes deterministic UTF-8 JSON. | `docket/advantage/record_run.py:13`, `:39`, `:50`, `:201`, `:294` | W9 Build 1; W9 Build 4 CLI reproduction |
| Kept single-read records out of the paired-experiment loader and included them in wheels. | `pyproject.toml:54` | W9 Build 2; truthful separation from `/advantage` paired experiments |
| Recorded Health Guard against a live Venus borrower observation. | `docket/advantage/recorded_runs/05-health-guard-read.json:12`, `:16`, `:22-23` | W9 Build 2a |
| Recorded Grid Operator's worked-example wallet with six live, simulation-matched, hash-bound quote previews. | `docket/advantage/recorded_runs/06-grid-preview-read.json:12`, `:16`, `:22-23` | W9 Build 2b |
| Recorded Yield Router's live PancakeSwap explorer population; the comparison-only path truthfully reports no chain block. | `docket/advantage/recorded_runs/07-yield-router-read.json:12`, `:16`, `:22-23` | W9 Build 2c |
| Loaded committed records and derived every published category figure from their response fields. Each metric has a denominator, observation time, window, method, and the exact single-read sentence. Modalities are `live_read`. | `docket/marketplace/registry.py:36-47`, `:75-124`, `:134-178`, `:188-239` | W9 Build 3; BNB category evidence parity |
| Added reproduction commands, moving-state expectations, independent canonical-hash checks, and the pruned-state/archive boundary. | `docs/evidence-reproduction.md:160-226` | W9 Build 4 |
| Added recorder, refusal, hash-binding, package-data, CLI, and documentation coverage. | `tests/test_record_run.py:71`, `:132`, `:172`, `:188`, `:234`, `:241`, `:273` | W9 Build 1, 2, and 4 |
| Added record-to-card regeneration equality, modality/denominator/wording checks, and served-card parity. | `tests/test_marketplace.py:524`, `:611`, `:654`; `tests/test_services_api.py:282` | W9 Build 3 and `/services` EXIT |
| Regenerated the three W5 registration documents whose generated `limitations` field follows the registry. | `docket/api/static/agents/grid-operator.registration.json:11`; `health-guard.registration.json:11`; `yield-router.registration.json:11` | Full-suite generated-artifact consistency |

## Recorded observations

The Venus address below is an observation of chain activity, not an endorsement or owner attribution.

- Borrower observation: `0x41eE916D25C38fED953098525Ea3A74d2148A32a`.
- Discovery event: vUSDT `Borrow` at BSC block `117450944`, `2026-08-22T15:49:56Z`, transaction `0xf019db946ad204b3c6acecb9b957079e2775a6ceccbfcbd1848545168fc36107`.
- Recorded Health Guard read: block `117453014`, recorder completion `2026-08-22T16:05:41.904205+00:00`; one non-zero-borrow market of two entered and 52 listed. The recorded vUSDT raw borrow balance was `270000259137772521556`.
- Grid read: block `117453016`, recorder completion `2026-08-22T16:05:45.744877+00:00`; six of six requested levels quoted and simulation-matched.
- Yield read: explorer snapshot `2026-08-22T16:05:30+00:00`; 26 eligible pools of 35 considered; no chain block because this path made no `eth_call`.

Committed file SHA-256 values:

- Health: `bffb12645785453aee3a2e0275c40cac691f50a2fd43815d036ecc0e6c4bd865`
- Grid: `b0565b958f307062cec563b3077637d8fb6ab9d3e637395ec6c3eb9296df2b11`
- Yield: `710a71b4702c602d06e5c9aefeba6f9e9b58a3fdd50f0b5a9623d3f00ceaf386`

## Exit-test evidence

Baseline before edits:

```text
> ./.venv/Scripts/python.exe -m pytest -q
1366 passed, 2 warnings in 59.28s
```

Red test before implementation:

```text
> ./.venv/Scripts/python.exe -m pytest -q tests/test_record_run.py tests/test_marketplace.py tests/test_services_api.py
ImportError: cannot import name 'record_run' from 'docket.advantage'
1 error, 2 warnings in 2.07s
```

Final scoped suite:

```text
> ./.venv/Scripts/python.exe -m pytest -q tests/test_record_run.py tests/test_marketplace.py tests/test_services_api.py
115 passed, 2 warnings in 3.97s
```

Final full suite:

```text
> ./.venv/Scripts/python.exe -m pytest -q
1379 passed, 2 warnings in 54.97s
```

Syntax, lint, format, and diff checks:

```text
> node --check docket/api/web/app.js
exit 0
> <home> check docket/advantage/record_run.py docket/marketplace/registry.py tests/test_record_run.py tests/test_marketplace.py tests/test_services_api.py
All checks passed!
> <home> format --check docket/advantage/record_run.py docket/marketplace/registry.py tests/test_record_run.py tests/test_marketplace.py tests/test_services_api.py
5 files already formatted
> git diff --check HEAD
exit 0
```

Wheel/package verification:

```text
> ./.venv/Scripts/python.exe -m pip wheel . --no-deps --wheel-dir .w9-wheel-check
Successfully built docket
> inspect wheel with zipfile
docket/advantage/recorded_runs/05-health-guard-read.json
docket/advantage/recorded_runs/06-grid-preview-read.json
docket/advantage/recorded_runs/07-yield-router-read.json
```

The temporary wheel directory was removed after its exact path and sole file were checked.

Local API inspection returned non-empty metrics for all four categories:

```text
range-doctor: 3 metrics
health-guard: 1 of 2 entered markets read
grid-operator: 6 of 6 requested grid levels
yield-router: 26 of 35 top-list pools considered
```

Each of the three new metric windows contains `single recorded read; no paired run against a person`.

## Mutation table

Every mutation was temporary, the named test failed, the implementation was restored, and the same test passed afterward.

| Test/behavior | Temporary mutation | Kill evidence |
|---|---|---|
| Catalogue runner and canonical record shape | Called `service.run({})` instead of the supplied payload | `test_record_uses...`: 1 failed, then 1 passed |
| Per-service observation block/time | Replaced Grid's reported block with `None` | observation parameterization: 1 failed / 1 passed, then 2 passed |
| Refusal of incomplete/error/empty results | Bypassed Health's `complete is True` guard | refusal parameterization: 1 failed / 4 passed, then 5 passed |
| Committed hash binding | Changed one hex digit in Health's receipt output hash | committed-run test: 1 failed, then 1 passed |
| Package data | Removed `recorded_runs/*.json` | package-data test: 1 failed, then 1 passed |
| Reproduction/archive documentation | Renamed `DOCKET_ARCHIVE_RPC` in the section | documentation test: 1 failed, then 1 passed |
| CLI payload forwarding | Forwarded `{}` instead of parsed JSON | CLI test: 1 failed, then 1 passed |
| Live-read modality | Reverted Health to `preview` | category service test: 1 failed, then 1 passed |
| Required denominator | Removed Health's denominator | test collection failed at `Metric` construction, then category test passed |
| Regenerated metric equality | Added one to Health's derived numerator | regeneration test: 1 failed, then 1 passed |
| Served card wording | Replaced one Health metric window with `single live read` | services API test: 1 failed, then 1 passed |
| Evidence link mapping | Pointed Health at the wrong service path | evidence mapping test: 1 failed, then 1 passed |
| Truthful limitations | Restored all three stale “no recorded run” tails | 3 limitation tests failed, then 3 passed |
| Generated registration consistency | Left W5 documents stale after the registry correction | first full suite: 1 failed / 1377 passed; regeneration test then passed |

## Could not do

1. `/compare` still says `No paired run against a human exists...` for these three services. This text is not derived from registry metrics or evidence. It is hardcoded at `docket/hire/comparison.py:25-46`, and the UI renders `measured.reason` at `docket/api/web/app.js:1525`. Editing `hire/*` or `web/*` is explicitly forbidden in W9. Mapping tasks 05–07 into `MEASURED_BY` would falsely represent single reads as paired benchmarks.
2. The raw committed JSON does not have a public artifact route. `routes.py` loads only paired `experiments/*.json` for `/advantage`; `/static` mounts only `WEB_DIR` at `routes.py:1797`. The allowed `EvidenceRef` therefore points at the served `/services/{id}` transcription and labels the committed file and route limitation explicitly.
3. The recorded Health block was already pruned by a public node during verification (`missing trie node`). `DOCKET_ARCHIVE_RPC` is used by the caller-pinned Range path, not these Health/Grid catalogue functions, which accept no historical block. Current-state reruns work; historical replay needs separate archive-capable tooling.
4. Shared Codex memory was not edited because that location is outside this worktree and the workstream forbids outside-worktree writes.

## Owner actions

1. Recommended: authorize or assign a minimal `docket/hire/comparison.py` plus comparison-test change that distinguishes `single_read` from `paired_benchmark` and uses the required sentence without claiming time saved.
2. Recommended: authorize a read-only raw-record route (plus required `llms.txt`, `SKILL.md`, and route tests) so `EvidenceRef` can point to the actual committed JSON rather than its service summary.
3. Configure archive-capable read tooling only if historical state at the recorded blocks must be independently replayed; a current rerun intentionally produces new blocks, responses, and hashes.
4. Preserve and commit the owner-controlled untracked joint audit and seat-report files separately.

## Out-of-scope edits

- Minimum generated-artifact correction: `docket/api/static/agents/grid-operator.registration.json`, `health-guard.registration.json`, and `yield-router.registration.json`, one generated `limitations` line each. The full-suite generator equality test required these updates.
- Within the allowed `registry.py`, the module evidence description and three stale limitations tails were corrected in addition to the narrowly named metrics/evidence tuples. Leaving them unchanged would directly contradict the new records.
- No routes, web code, hire code, agents, Advantage v2/v3, deployment files, external systems, keys, transactions, or network-write operations were changed.
