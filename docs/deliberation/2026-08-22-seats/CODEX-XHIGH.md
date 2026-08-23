# Audit ruling — 2026-08-22

Bottom line: keep TermiX and PancakeSwap as P0. Cap BNB at a two-day eligibility/shortlist lane unless the primary gates are green by September 3. Docket has substantial machinery, but today it is still protocol-plus-preview, not sponsor-verifiable delivery.

I used the repository’s August 14 verbatim sponsor snapshot as instructed; I did not re-fetch the rules today. The briefing records its own live-fetch provenance at [2026-08-14-BRIEFING-V2.md:24](docs/deliberation/2026-08-14-BRIEFING-V2.md:24).

## 1. Verdict by track

| Track | Ruling — my judgment | Single deciding verified fact |
|---|---|---|
| **TermiX 1st** | **Red today, but still salvageable.** | TermiX will hire and gives 30% to working service value, yet every Docket service is outside paid stock and the repository contains no settled receipt or transaction. [Briefing:106](docs/deliberation/2026-08-14-BRIEFING-V2.md:106), [README.md:17](README.md:17) |
| **PancakeSwap winner** | **Amber; best recoverable win path.** | There is no completed state → diagnosis → owner decision → later-state record. The LP recorder explicitly says it cannot establish whether the owner acted. [lp_record.py:20](docket/agents/pancake/lp_record.py:20), [win spec:54](docs/deliberation/CODEX-WIN-SPEC-2026-08-14.md:54) |
| **BNB top-3 / $30k winner** | **Red; not credible within 18 days without sacrificing the stronger tracks.** | Range, Grid, Yield, and Health all have `agent_id=None`, while BNB requires surfaced agents to be live on BSC. [registry.py:60](docket/marketplace/registry.py:60), [registry.py:98](docket/marketplace/registry.py:98), [registry.py:131](docket/marketplace/registry.py:131), [registry.py:170](docket/marketplace/registry.py:170), [Briefing:75](docs/deliberation/2026-08-14-BRIEFING-V2.md:75) |

Pancake’s current arithmetic is honest but insufficient for first: it is explicitly post hoc and reports zero ranking reversals across 231 ordered pairs—the best pool remains unchanged. [report.py:579](docket/advantage/v2/report.py:579), [report.py:621](docket/advantage/v2/report.py:621)

## 2. Ten highest points-per-day gaps

### 1. Prove one real paid Range hire

The x402 binding, no-result/no-charge and settlement state machine substantially exist, but live evidence does not. [routes.py:1103](docket/api/routes.py:1103), [README.md:20](README.md:20)

**Files:** `docket/store.py`, `docket/api/routes.py`, `docket/hire/catalogue.py`, `docket/canary.py`, `deploy/docket-canary.conf.example`, `tests/test_hire_api.py`, `tests/test_hire_x402.py`, `tests/test_canary.py`, `tests/test_canary_api.py`.

**Exit:** a live controlled-position request returns a non-empty result, settles exactly once, preserves receipt/input/output/transaction bindings, refuses replay with 409, passes the daily canary, and reconciles safely after a forced process death while payment is `settling`. Only then set Range’s four admission limbs true.

### 2. Recommit and make Yield capture operationally durable

The current CLI loads dependencies/specification before checking the five-second tolerance; the timer starts exactly at the registered moment and has `Persistent=false`, while the service has `Restart=no`. [capture.py:29](docket/advantage/v3/capture.py:29), [capture.py:185](docket/advantage/v3/capture.py:185), [timer:4](deploy/systemd/docket-v3-capture.timer:4), [service:19](deploy/systemd/docket-v3-capture.service:19)

**Files:** `docket/advantage/v3/capture.py`, `docket/advantage/v3/spec.py`, `docket/advantage/v3/specs/v3-02-yield-router.json`, `deploy/systemd/docket-v3-capture.service`, `deploy/systemd/docket-v3-capture.timer`, `tests/test_advantage_v3_capture.py`, `tests/test_advantage_v3_spec.py`, `tests/test_canary_deploy.py`.

**Exit:** see the Yield ruling below. The final artifact must have raw immutable bodies, statuses and hashes for every registered slot, a non-empty `inputs_sha256`, and a lock that can be reproduced from those bytes.

### 3. Resolve Range’s impossible population frame

The original block-0 archive scan is not executable with the recorded free infrastructure. The dry run says archive access is the honest fix; if unavailable, a three-stratum protocol is defensible only when recommitted before drawing cases. [Range feasibility:20](docs/deliberation/RANGE-FEASIBILITY-2026-08-15.md:20), [replacement dry run:101](docs/deliberation/RANGE-REPLACEMENT-DRYRUN-2026-08-15.md:101)

**Files:** `docket/advantage/v3/specs/v3-01-range-doctor.json`, `docket/advantage/v3/spec.py`, `docket/advantage/v3/assemble.py`, `tests/test_advantage_v3_spec.py`, `tests/test_advantage_v3_assemble.py`, `tests/test_advantage_v3_range_conflict.py`, plus new `docket/advantage/v3/inputs/01-range-positions.json`.

**Exit:** by August 23, either prove usable archive access against the original frame or recommit a feasible three-stratum design. By August 25, lock five valid conflict-free cases with a non-empty hash and reproduce them from a pinned source.

### 4. Record an actual LP-owner decision

The daily JSONL schema records observation and report only; no decision field or event exists. [lp_record.py:53](docket/agents/pancake/lp_record.py:53), [lp_record.py:106](docket/agents/pancake/lp_record.py:106)

**Files:** `docket/agents/pancake/lp_record.py`, `tests/test_lp_record.py`, `deploy/systemd/docket-lp-record.service`, and a new public `docs/controlled-lp-evidence.md`.

**Exit:** an append-only owner event records `WAIT` or `RECENTER`, timestamp, rationale, prior-observation digest and position identifier; a later observation links back to it. The report must say that association is observed but market causality is not proved.

### 5. Finish Warden’s real calibration and held-out evidence

Warden requires two calibrated seats, 12/12 successful scans, at least 0.90 recall and precision, and zero surviving critical vector; inputs remain empty. [Warden spec:21](docket/advantage/v3/specs/v3-03-warden-security.json:21), [Warden spec:38](docket/advantage/v3/specs/v3-03-warden-security.json:38), [Warden spec:85](docket/advantage/v3/specs/v3-03-warden-security.json:85)

**Files:** `docket/advantage/v3/calibration.py`, `calibration_driver.py`, `assemble.py`, `orchestrator.py`, `scoring.py`, `specs/v3-03-warden-security.json`, `tests/test_advantage_v3_calibration.py`, `tests/test_advantage_v3_warden_heldout.py`, `tests/test_advantage_v3_orchestrator.py`, plus new `inputs/03-security-heldout.json` and run/sheet/mapping artifacts.

**Exit:** both seats pass calibration, all 24 primaries become terminal, both blinded sheets are preserved, and the frozen gates decide the result. If any gate fails, Warden stays beta—do not relax the threshold.

### 6. Exercise the actual v3 orchestrator end to end

The latest audit backlog still records no real endpoint execution and untested CLI/payment/error branches. [AUDIT-BACKLOG.md:570](docs/deliberation/AUDIT-BACKLOG.md:570)

**Files:** `docket/advantage/v3/orchestrator.py`, `runner.py`, `report.py`, `page.py`, `tests/test_advantage_v3_orchestrator.py`, `tests/test_advantage_v3_runner.py`, `tests/test_advantage_v3_report.py`, `tests/test_advantage_v3_api.py`.

**Exit:** Range, Yield and Warden all leave `registered_waiting_for_inputs`; every scheduled arm has a terminal ledger record; failures remain in denominators; sheets and mappings recompute; an installed-package run reaches the real public service endpoint.

### 7. Register the four BNB category identities

This is the fastest BNB eligibility gain, but it does not by itself fix the equal-depth actor gap.

**Files:** `docket/marketplace/registry.py`, `tests/test_marketplace.py`, `tests/test_services_api.py`, `README.md`, `docs/claims-to-evidence.md`.

**Exit:** after explicit owner approval for the on-chain registrations, all four identities resolve on BSC, agent → service → hire and service → agent links work, and a process restart preserves them.

### 8. Make registry freshness and deployed parity real

The tree’s supported ingestion path is a targeted complete sweep; full-registry paging is explicitly impractical. [ingest.py:110](docket/ingest.py:110), [ingest.py:133](docket/ingest.py:133)

**Files:** add a CLI entry in `docket/ingest.py`; add `deploy/systemd/docket-registry-refresh.service` and `.timer`; update `tests/test_ingest.py`, `tests/test_canary_deploy.py`, `docs/operational-evidence.md`, and `docs/source-deploy-manifest.md`.

**Exit:** a complete targeted snapshot under 24 hours old contains the four identities, survives restart, and production reports the same commit/wheel/static hashes as the tested release.

### 9. Make compare → hire judge-proof

The table currently offers only service, price, declared time, sale state and a single `n=1` timing comparison. [comparison.py:56](docket/hire/comparison.py:56), [app.js:1391](docket/api/web/app.js:1391). Worse, “Pay … and hire” opens a page that deliberately performs only a free preview. [app.js:335](docket/api/web/app.js:335), [app.js:478](docket/api/web/app.js:478)

**Files:** `docket/hire/comparison.py`, `docket/api/web/app.js`, `docket/api/web/index.html`, `docket/api/web/service.html`, `tests/test_hire_comparison.py`, `tests/test_web.py`, `tests/test_web_categories.py`.

**Exit:** comparison exposes job, price, actual time, output quality, sample size, freshness, limitation and evidence link; language accurately distinguishes browser preview from agent x402 hire; three uncoached users complete find → compare → run without repeated help.

### 10. Produce one truthful release package

The current README, claims table and deployment documents disagree about registration reachability and deployed commit. [README.md:33](README.md:33), [claims-to-evidence.md:16](docs/claims-to-evidence.md:16), [README.md:40](README.md:40), [claims-to-evidence.md:17](docs/claims-to-evidence.md:17)

**Files:** `README.md`, `docs/claims-to-evidence.md`, `docs/evidence-reproduction.md`, `docs/source-deploy-manifest.md`, `docs/operational-evidence.md`, `AI_USAGE.md`, `docket/api/web/index.html`, `tests/test_advantage_v3_capture.py`, `.github/workflows/ci.yml`.

**Exit:** current-date tests green, exact release commit green in CI, `main` equals the release, production matches it, repository is public, all public claims agree, and internal deliberation material is excluded from the sponsor-facing release.

## 3. Yield ruling

**Recommit once, for 2026-08-25 12:00:00Z. Do not drop Yield yet.**

It has unusually high leverage: it is one of the operative three replicated families, supplies a required BNB category, and directly addresses Pancake’s “finding better yields” example. [win spec:16](docs/deliberation/CODEX-WIN-SPEC-2026-08-14.md:16), [Briefing:166](docs/deliberation/2026-08-14-BRIEFING-V2.md:166). Its own frozen protocol says a failed registered window requires recommitment. [Yield spec:14](docket/advantage/v3/specs/v3-02-yield-router.json:14)

The revised design must:

1. Fire the timer at **11:50Z**, not at the observation moment. Load imports/specification, check disk/permissions/clock/endpoints, open the journal and write an `armed` record before 12:00.
2. Wait inside the already-running process until each registered slot.
3. Represent expired slots explicitly and permit a restart to continue only with still-future preregistered slots.
4. Wire `main()` to per-attempt journaling. Currently `run_registered_capture()` supports a journal, but the production entry point does not pass one. [capture.py:158](docket/advantage/v3/capture.py:158), [capture.py:421](docket/advantage/v3/capture.py:421)
5. Persist each URL response and body atomically, make restart idempotent, and create the completion marker last.
6. Use `Restart=on-failure`, bounded restart attempts, `Persistent=true`, and an explicit failure alert. A start after the last registered slot must perform zero HTTP and record terminal failure.
7. Freeze the test clock. Today’s suite failure comes from a test that assumes August 21 is still in the future. [test_advantage_v3_capture.py:279](tests/test_advantage_v3_capture.py:279)
8. Test the exact installed CLI and systemd command, not only injected functions.

Hard kill: if the new service has not produced a verified pre-moment `armed` record by **August 24 18:00Z**, do not hold the moment. Drop Yield and run v3 with Range + Warden only. If the August 25 capture fails despite that verified state, drop it permanently for this submission.

No system can guarantee that a host and two public endpoints never fail. This design eliminates the observed late-start/import failure and makes every remaining failure immediate, durable and non-silent.

## 4. Revised build order

| Dates | Work and hard exit |
|---|---|
| **Aug 22–23** | Fix current test failure; configure and execute live Range settlement/canary; decide archive access. **Exit Aug 23:** settled receipt + replay refusal + crash recovery; archive available or three-stratum recommit chosen. |
| **Aug 24–25** | Recommit/prearm Yield; lock Range. **Exit Aug 24 18:00Z:** Yield armed. **Exit Aug 25 12:00Z:** capture complete. **Exit Aug 25 23:59Z:** Range input locked. |
| **Aug 26–27** | Run Warden calibration and lock held-out input; record the LP owner decision. **Exit:** two calibrated seats, non-empty Warden input hash, append-only owner event. |
| **Aug 28–31** | Run all Range/Yield/Warden primary arms, preserving failures. **Exit Aug 31:** every scheduled primary terminal; no replacement cases or scored retries. |
| **Sep 1–2** | Complete scoring, blinded sheets, mappings, reports and later LP observation. **Exit:** Warden passes frozen gates or stays beta; Pancake report publishes decision/later-state evidence without causal overclaim. |
| **Sep 3–4** | Two-day BNB lane only: owner-approved identities, reverse links, fresh targeted snapshot and daily refresh. **Exit:** all four identities live on BSC and discoverable after restart. If P0 is still red, cut this lane entirely. |
| **Sep 5** | Comparison finish and three uncoached sessions. **Exit:** no repeated dead end; claims corrected from session evidence. |
| **Sep 6** | Public exact tested release; deploy parity; clean-machine/wheel/restart/failure smoke. **Exit:** release SHA equals CI, production and default branch. |
| **Sep 7** | Freeze source, artifacts and claims. No new features. Demo rehearsal against live production. |
| **Sep 8** | Record the real-voice demo and prepare final submission package for owner review. |
| **Sep 9** | Submit only after explicit owner approval; keep the public deployment healthy through the judging window. |

Cut now: Grid mainnet execution, four full autonomous BNB actors, SOLVENT expansion, Health expansion, second-chain work, provider onboarding, trust/scoring systems, background daemons unrelated to evidence, and aesthetic refactors. These are already outside the governing cut line. [win spec:118](docs/deliberation/CODEX-WIN-SPEC-2026-08-14.md:118)

## 5. Sponsor-judge embarrassments

These are verified in the tree:

- Every service says it is not paid stock, while TermiX intends to hire. [README.md:17](README.md:17)
- The security hero’s v1 evidence caught only one of four attack vectors. [03-security.json:122](docket/advantage/experiments/03-security.json:122)
- V3 still has no inputs or runs after the registered Yield date. [README.md:103](README.md:103)
- The full test suite is red today because a production-entry test depends on the real calendar: **1 failed, 1,209 passed**. [test_advantage_v3_capture.py:279](tests/test_advantage_v3_capture.py:279)
- README says `b883e3f` is deployed; operational evidence says `534af82` replaced it; the claims allowlist says no parity evidence exists. [README.md:40](README.md:40), [operational-evidence.md:20](docs/operational-evidence.md:20), [claims-to-evidence.md:17](docs/claims-to-evidence.md:17)
- The claims table carries obsolete v3 hashes compared with the registered specifications. [claims-to-evidence.md:12](docs/claims-to-evidence.md:12), [Yield spec:119](docket/advantage/v3/specs/v3-02-yield-router.json:119)
- The public deliberation tree includes admissions of a hash-bound false statement and manually invented hash characters. These should not be present in a sponsor-facing repository. [AUDIT-BACKLOG.md:445](docs/deliberation/AUDIT-BACKLOG.md:445), [AUDIT-BACKLOG.md:512](docs/deliberation/AUDIT-BACKLOG.md:512)
- The same deliberation documents contain absolute Windows paths exposing the local username and links that will not work for a judge. [CODEX-WIN-SPEC:18](docs/deliberation/CODEX-WIN-SPEC-2026-08-14.md:18)
- Homepage metadata claims Docket publishes the recorded run behind each service, while the visible page admits several have none. [index.html:6](docket/api/web/index.html:6), [index.html:55](docket/api/web/index.html:55)
- The default branch is 66 commits behind audited HEAD locally. Per the supplied external facts, the repository is also still private and production is six commits behind HEAD.

## Evidence boundary

**Verified locally:** current source, local Git relationships, sponsor documents in the repository, all cited implementation/evidence states, and the pytest result. The worktree remained clean after the audit; no file was created or modified, and no network request was made.

**Accepted as stipulated, not independently verified here:** production at `534af82`, snapshot 3 being 15 days old, the August 21 service failure, host load 25.9, missing live canary configuration, eight LP records, position 7141050 being below range, and the absence of a live settled receipt.

**Judgment rather than fact:** the track verdicts, points-per-day ranking and dated recovery plan. My strongest forecast is: Pancake remains genuinely winnable, TermiX first remains possible only if the paid hire and v3 hard exits land this week, and BNB top-3 should not be allowed to consume those gates.
