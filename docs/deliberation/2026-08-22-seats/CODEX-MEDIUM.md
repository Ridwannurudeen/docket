## 1. Track verdicts

| Track | Verdict today | Deciding fact |
|---|---|---|
| **TermiX 1st** | **Not first-place competitive; recoverable.** | No service can complete a paid hire, no settled receipt exists, and all three v3 families remain unlocked/unrun. That leaves TermiX’s two 30% criteria unproven. [README](README.md:17) [TermiX rubric](docs/deliberation/2026-08-14-BRIEFING-V2.md:116) |
| **PancakeSwap** | **Not win-ready; still the strongest recoverable track.** | The controlled LP record lacks the required owner-decision event, so Docket cannot yet show `state → diagnosis → owner decision → later state`. [win spec](docs/deliberation/CODEX-WIN-SPEC-2026-08-14.md:54) [recorder limitation](docket/agents/pancake/lp_record.py:20) |
| **BNB top-3** | **Not top-3-ready; as represented today it risks failing eligibility.** | Zero of the four scored-category services has an ERC-8004 BSC identity; the claims table explicitly says they are four services, not four registered agents. [BNB gate](docs/deliberation/2026-08-14-BRIEFING-V2.md:78) [claims table](docs/claims-to-evidence.md:9) |

Pancake’s structural safety is already excellent: Range Doctor holds no key and cannot move funds, matching the sponsor’s only absolute requirement. [doctor.py](docket/agents/pancake/doctor.py:1) [Pancake brief](docs/deliberation/2026-08-14-BRIEFING-V2.md:166)

Production facts—missed capture, stale snapshot, failed canary, LP state, deployment lag—are Claude-supplied and not independently verified here.

## 2. Ten highest points-per-day gaps

Ordered by expected sponsor impact; I am not inventing numeric scores because BNB published no weights and Pancake published no scoring rubric.

| # | Gap and exact files | Hard exit |
|---|---|---|
| **1** | **Complete one real paid Range hire.** Change [catalogue.py](docket/hire/catalogue.py:95), [admission.py](docket/hire/admission.py:33), [routes.py](docket/api/routes.py:1045), [canary.py](docket/canary.py:33), `deploy/docket-canary.conf.example`, tests, and production `/etc/docket/docket-canary.conf`. The exactly-once state machine already exists. [routes.py](docket/api/routes.py:1144) | Stranger pays exactly `$0.50`; non-empty Range result; settled receipt binds nonce/payment/input/output/transaction; replay returns 409; latest daily canary passes; public Pay CTA appears. |
| **2** | **Record the owner decision now.** Change [lp_record.py](docket/agents/pancake/lp_record.py:35), `tests/test_lp_record.py`, and the fixed-window report/presenter. Add an append-only decision event bound to the preceding observation digest—decision, rationale, alternatives, owner time—with no inferred action. | Public sequence contains observation → diagnosis → explicit owner decision → later observation, plus dollar consequence and limitations. Removing or changing the referenced observation breaks verification. |
| **3** | **Recommit and capture Yield once.** Change [capture.py](docket/advantage/v3/capture.py:158), [timer](deploy/systemd/docket-v3-capture.timer:4), [service](deploy/systemd/docket-v3-capture.service:8), `v3-02-yield-router.json`, and `tests/test_advantage_v3_capture.py`. | Official Aug 26 capture validates both raw hashes, complete attempt history and exactly five cases; locked spec has non-empty `inputs_sha256`; any late run refuses. Failure by **12:05Z Aug 26** permanently drops Yield. |
| **4** | **Make Warden earn the security lane.** Change `calibration.py`, `calibration_driver.py`, `assemble.py`, `orchestrator.py`, `sources/warden-heldout-cases.json`, `specs/v3-03-warden-security.json`, tests, and generated input/run/sheet artifacts. Current evidence includes a substantive loss. [security record](docket/advantage/experiments/03-security.json:127) | Real calibration seats pass; 12/12 primary scans succeed; recall and precision ≥0.90; zero critical survival; no-lower blinded quality; registered speed gate passes. [registered gate](docket/advantage/v3/specs/v3-03-warden-security.json:22) |
| **5** | **Lock feasible Range cases.** Resolve the known producer/schema conflict in `docket/agents/pancake/positions.py`, `docket/advantage/v3/spec.py`, `assemble.py`, `specs/v3-01-range-doctor.json`, `tests/test_advantage_v3_spec.py`, and `tests/test_advantage_v3_range_conflict.py`. [open mismatch](docs/deliberation/AUDIT-BACKLOG.md:472) | Five conflict-free, open, archive-readable positions at frozen blocks; public hire can select token and observation block; locked input passes `assert_runnable`. Hard stop Aug 27. |
| **6** | **Execute and publish the full v3 report.** Populate `docket/advantage/v3/inputs/*.json`, `runs/*.jsonl`, `sheets/**`, and `mappings/**`; finish `runner.py`, `orchestrator.py`, `scoring.py`, `report.py`, and `page.py`. Today all input hashes are empty. [README](README.md:97) | All scheduled manual-first and agent arms are terminal; failures remain; time, cost, output quality, actual outputs, both sheets and mappings are served; no family remains `registered_waiting_for_inputs`. |
| **7** | **Register four BSC agents and bind them to the four categories.** Owner-approved on-chain action, then change [registry.py](docket/marketplace/registry.py:60), `tests/test_marketplace.py`, `tests/test_services_api.py`, README and claims table. | Health, Yield, Grid and Range each have a chain-resolved ERC-8004 identity; service→agent and agent→service links both resolve after a complete sweep/restart. |
| **8** | **Make comparison decision-grade.** Change [comparison.py](docket/hire/comparison.py:76), `docket/api/web/app.js`, `index.html`, `tests/test_hire_comparison.py`, and `tests/test_web_categories.py`. The current table is largely catalogue terms plus n=1 timing. [comparison.py](docket/hire/comparison.py:83) | Each row visibly distinguishes declared versus measured time and contains job, identity, price, quality/denominator, freshness, limitation, evidence link and activation. |
| **9** | **Restore public/default/live truth.** Change [README](README.md:33), [claims-to-evidence](docs/claims-to-evidence.md:16), [source manifest](docs/source-deploy-manifest.md:14), and [operational evidence](docs/operational-evidence.md:20). Owner actions: public repository, correct default branch, fresh deploy. | One release commit and wheel digest agree across default branch, deployment and documentation; clean clone/install passes; repo and product remain public through Sep 23. |
| **10** | **Fresh registry snapshot plus cold judge proof.** Use `docket/scan8004.py`, `docket/ingest.py`, `docket/api/routes.py`, UI files and web/integration tests. The application pins its chosen snapshot at startup. [architecture](docs/architecture.md:98) | Same-day complete BSC snapshot contains all four IDs; restart serves it; three uncoached users find, compare, sample, pay and explain Range without a repeated dead end. |

## 3. Yield ruling

**Recommit once for 2026-08-26 12:00:00Z. Do not drop it today.**

Yield is already a bounded five-case family, helps the three-family TermiX proof, and supplies calculations beneath the singular Pancake hero. [win spec](docs/deliberation/CODEX-WIN-SPEC-2026-08-14.md:18) [Pancake positioning](docs/deliberation/CODEX-WIN-SPEC-2026-08-14.md:60)

Required capture design:

- Fire pre-arm triggers at T−10m and T−5m. Load the installed spec, imports and client before T, then wait without making an early evidence GET.
- Preserve strict late refusal. Current code correctly refuses a later universe rather than mislabelling it. [capture.py](docket/advantage/v3/capture.py:185)
- Pass `journal=Path(args.out)` from `main()`. Today the CLI bypasses immediate per-attempt journalling and writes only after the whole runner returns. [capture.py](docket/advantage/v3/capture.py:445)
- Write successful raw bodies and fsync them before writing the exclusive success manifest. Current ordering can leave a “succeeded” attempt record without both bodies after a crash. [capture.py](docket/advantage/v3/capture.py:342)
- Persist refusals and startup identity outside the rotating journal.
- Test the installed systemd command with delayed startup, process death after attempt one, duplicate pre-arm activation, overwrite refusal and late boot.

No single-host design can guarantee evidence through host/kernel/network failure. This design makes the observed import/load miss impossible and makes every remaining failure explicit and fail-closed.

If the installed process is not demonstrably armed by Aug 25 12:00Z, or the real capture is absent/invalid at Aug 26 12:05Z, drop Yield permanently and run v3 with Range + Warden. Do not select a third moment.

## 4. Revised dated build order

- **Aug 22–23 — Paid Range first.** Configure the controlled LP/payment material, complete one live settlement, reject replay, obtain a passing canary. Record the owner decision before changing the LP.

- **Aug 24–25 — Yield capture readiness.** Land pre-arm/atomic persistence, recommit the spec, deploy the exact build and conduct a future-moment systemd rehearsal. Hard exit Aug 25 noon: armed or dropped.

- **Aug 26 — Official Yield capture.** Capture at 12:00Z; validate and lock by end of day. No retry after 12:05Z.

- **Aug 27–28 — Range and Warden locks.** Close the Range schema/archive decision, lock five cases, run real Warden calibration and freeze its 12 payloads. Public repo and truthful evidence package by Aug 28.

- **Aug 29–30 — BNB lane, capped at two days.** With explicit owner approval, register the four agents, bind reverse links, run one complete registry sweep and restart. No Agent Studio build or registry daemon.

- **Aug 31 — Release gate.** Green suite, installed-wheel smoke, settlement/replay recovery, three uncoached cold sessions, desktop/mobile.

- **Sep 1–4 — Execute v3.** Manual-first then agent arms; preserve every failure; no replacement cases or scored retries.

- **Sep 5 — Score and publish.** Both sheets, mappings, actual outputs, fixed-window LP decision record and claims audit.

- **Sep 6 — Freeze.** Exact tested deployment, source/wheel/static/evidence hashes and fresh canary.

- **Sep 7–8 — Demo rehearsal.** One-minute Range hire, Pancake benefit loop, TermiX report and BNB identities. No new features.

- **Sep 9 — Submission.** Submit only after explicit owner approval.

Cut Grid execution and volume claims, Altana, SOLVENT revival, Venus/Health evidence work, Yield execution drafting, provider onboarding, a continuous registry daemon, second-chain work, trust scoring, new services and visual redesign. This matches the governing cut list. [win spec](docs/deliberation/CODEX-WIN-SPEC-2026-08-14.md:118)

## 5. Sponsor-judge embarrassment risks

Tree-verified:

- **The suite is red today:** 1 failed, 1209 passed. The test permanently expects “Capturing early” even after Aug 21. [test](tests/test_advantage_v3_capture.py:279)
- **The expired Aug 21 timer still ships**, and the operational document still describes it as armed/pending. [timer](deploy/systemd/docket-v3-capture.timer:2) [operational evidence](docs/operational-evidence.md:86)
- **Registration provenance contradicts itself:** README says remote-reachable; the claims table says local and unreachable. [README](README.md:33) [claims table](docs/claims-to-evidence.md:16)
- **Deployment identity contradicts itself:** README/source manifest name `b883e3f`; operational evidence names `534af82`. [README](README.md:40) [manifest](docs/source-deploy-manifest.md:15) [operations](docs/operational-evidence.md:27)
- **The submission README admits no paid inventory, settlement or completed v3 report.** Honest today, fatal if unchanged. [README](README.md:17)
- **BNB diversity is presently four labels with zero eligible category identities.** Health, Yield, Grid and Range all have `agent_id=None`. [registry.py](docket/marketplace/registry.py:60)
- **The LP proof omits the human decision**, even though that decision is the difference between an APR observation and a Pancake user benefit. [lp_record.py](docket/agents/pancake/lp_record.py:20)
- **Current Warden evidence is weak enough to invite hostile questioning**, including the recorded 1-of-4 result. [security record](docket/advantage/experiments/03-security.json:127)
- **Declared “typical” times sit beside n=1 measurements without a clear visual distinction.** [comparison.py](docket/hire/comparison.py:90)
- **The repository itself states it remains private**, while public accessibility during judging is an eligibility condition. [source manifest](docs/source-deploy-manifest.md:63)

Claude-supplied, not independently verified here: production is six commits behind; `/stats` is 15 days old; the Aug 21 capture failed and wrote nothing; the canary fails daily; settlement has never run; token 7141050 is below range and earning no pool fees; default `main` is stale and the repository remains private.

No files or repository state were changed. The final read-only status remained clean at `fdf02cf`.
