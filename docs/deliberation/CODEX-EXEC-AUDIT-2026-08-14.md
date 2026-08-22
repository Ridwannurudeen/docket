# Codex — audit of the executed work (2026-08-14)

_`gpt-5.6-sol` @ xhigh, read-only, reviewing branch `docs/deliberation-round2` against `CODEX-WIN-SPEC-2026-08-14.md`. Audits execution, not strategy._

## Verdict

Execution is not ready. The promotion fix is good. The Range hardening is worth keeping. But v3 is not securely preregistered, the flagship presenter still misses most of TermiX’s 30%, navigation only partially follows the ruling, and flat `$0.50` exists only in documentation.

### Adoption check

1. **Flat `0.50 $U`: did not fully land.** The decision is correctly recorded, but every executable service remains `0.01 $U`—including Range—and SOLVENT remains paid stock despite being cut. [SYNTHESIS-V2.md](../../docs/deliberation/2026-08-14-SYNTHESIS-V2.md:138) [catalogue.py](../../docket/hire/catalogue.py:351) [catalogue.py](../../docket/hire/catalogue.py:566)

2. **BNB shortlist lock: landed correctly.** No Aug-24 reopening; only a material capacity change reopens it. [SYNTHESIS-V2.md](../../docs/deliberation/2026-08-14-SYNTHESIS-V2.md:168)

3. **V2 reachability: partially landed.** The above-fold v1→v2 link and relationship wording are right. [advantage.html](../../docket/api/web/advantage.html:66) But v2 still carries competing `/advantage` and `/advantage/v2` top-level entries. [advantage-v2.html](../../docket/api/web/advantage-v2.html:36) The “same navigation” test only checks required links exist and misses extras. [test_web_categories.py](../../tests/test_web_categories.py:256)

4. **Restored items: accurately pending.**

   - Grid array and BigInt: not done; arrays render as text and integers cross `Number.parseInt`. [app.js](../../docket/api/web/app.js:392) [app.js](../../docket/api/web/app.js:517)
   - Reverse agent→hire: not done. [app.js](../../docket/api/web/app.js:1269)
   - Monitoring through Sep 23: specified, not implemented. [CODEX-WIN-SPEC](../../docs/deliberation/CODEX-WIN-SPEC-2026-08-14.md:91)
   - Grid implementation: correctly conditional on owner approval. [CODEX-WIN-SPEC](../../docs/deliberation/CODEX-WIN-SPEC-2026-08-14.md:83)

5. **V3 started early: yes.** Commit `88cc2bc` predates every committed v3 input or run; none exist yet. That satisfies the sequencing intent, subject to the preregistration defects below.

## A. Two-stage input lock

**The two-stage model is honest. The implementation is not yet a lock.**

Changing the composite spec hash when inputs are added is fine. What must remain stable is a separately recorded stage-one protocol hash. Current code has neither that continuity nor actual input verification:

- Any nonblank `inputs_sha256` makes the spec runnable. [spec.py](../../docket/advantage/v3/spec.py:172)
- `assert_runnable()` never opens `inputs_ref` or recomputes its digest. [spec.py](../../docket/advantage/v3/spec.py:205)
- The test explicitly accepts fake digest `"0xabc"`. [test_advantage_v3_spec.py](../../tests/test_advantage_v3_spec.py:128)
- Stage two can change the rubric, claim, or stopping rule and simply save a new self-consistent hash. [spec.py](../../docket/advantage/v3/spec.py:220)

Also, every JSON claims registration at midnight, while the commit was made around 20:13 local time. [v3 Range spec](../../docket/advantage/v3/specs/v3-01-range-doctor.json:61)

**Decision:** keep two stages, but do not freeze inputs or run an arm yet. As written, a judge can correctly say “declared protocol,” not “cryptographically locked preregistration.”

## B. Families, rubrics and stopping rules

The counts—5/5/12—clear “not three anecdotes” literally. They do not yet clear objective, non-post-hoc evaluation.

Shared problems:

- “Materially faster” has no registered threshold; the falsifiers treat any lower median as material.
- Scores 1 versus 2 depend on whether a gap “changes what the reader would do,” which is subjective and not criterion-specific. [Range spec](../../docket/advantage/v3/specs/v3-01-range-doctor.json:58)
- Evaluator identities, qualification and selection rules are absent.
- Manual timing permits self-stopwatch timing and post-hoc interruption subtraction.

Family rulings:

- **Range:** strongest, but the agent receives a wallet while the manual arm diagnoses the selected NFT; multi-position wallets make the paired case ambiguous. Dollar consequence is rewarded for being present, not being correct. [Range spec](../../docket/advantage/v3/specs/v3-01-range-doctor.json:5)
- **Yield:** branch-coverage suite, not representative evidence. The candidate universe, eligibility formula and numerical truth source are insufficiently frozen; the rubric rewards showing a universe without proving it complete or correct. [Yield spec](../../docket/advantage/v3/specs/v3-02-yield-router.json:14)
- **Warden:** materially broken. Its failure policy says failures remain in the denominator, while its stopping rule retries twice and then counts the failed payload “in the denominator of nothing.” [Warden spec](../../docket/advantage/v3/specs/v3-03-warden-security.json:21) [Warden spec](../../docket/advantage/v3/specs/v3-03-warden-security.json:66) Recall is undefined, precision is omitted from the claim, and the zero-critical-vector ship gate is absent. It cannot establish the TermiX high-stakes 20% yet.

## C. Range Doctor diagnosis

**My diagnosis was wrong. Claude should not have repeated it as the root cause.**

The repository now records that all 21 current positions are closed. No larger `limit` finds an open one. [Range spec](../../docket/advantage/v3/specs/v3-01-range-doctor.json:14) [test_pancake_doctor.py](../../tests/test_pancake_doctor.py:196)

Keep both changes:

- `limit` bounding returned open positions is the correct API meaning.
- `MAX_EXAMINED` is the correct separate work bound. [positions.py](../../docket/agents/pancake/positions.py:186)
- `coverage` and `scan_complete` are mandatory honesty fields. [doctor.py](../../docket/agents/pancake/doctor.py:260)

But they do not close Aug 15–16. That row remains open until there is a controlled live LP, daily capture, and a non-empty cold-browser result.

Claude also introduced incorrect copy: incomplete scans always say “raise limit,” even when the unchangeable `MAX_EXAMINED=30` caused truncation. [doctor.py](../../docket/agents/pancake/doctor.py:310) Worse, the presenter says there was no open position even when `scan_complete=false` means unread positions are unknown. [app.js](../../docket/api/web/app.js:568)

## D. Promotion fix

**Keep it. It serves the retained one-sweep/restart lane, not the cut daemon.**

The new predicate requires finished, non-null, positive, equal counts and either legacy `NULL` or `exhausted`. [store.py](../../docket/store.py:213) Therefore 2,000/247,065 cannot be promoted, while a legacy count-complete snapshot can be. The retained Aug 29–30 sweep and restart depend on this invariant.

One hardening gap remains: `_sweep` initializes `stop_reason="exhausted"` before the loop, so a future early `break` that forgets to set a reason fails open. Current break paths correctly overwrite it. [ingest.py](../../docket/ingest.py:62)

## E. Range presenter

**It does not meet the exact ordering and would cost most of the Value 30%.**

It leads with coverage instead of decision. It partially shows token ID, status, ticks, block, net APR and conditional actions. [app.js](../../docket/api/web/app.js:558)

Missing:

- Explicit pair and observation time.
- Gross APR, net APR, percentage/percentage-point overstatement.
- Dollar effect at declared position value.
- Numeric switching cost/break-even.
- This-run time, paired manual time, quality result and report link.
- Settled transaction/payment ID and unique nonce.
- Prominent primary limitation.

The backend cannot currently supply the dollar result because Range accepts only wallet and limit and emits only net APR. [catalogue.py](../../docket/hire/catalogue.py:330) [doctor.py](../../docket/agents/pancake/doctor.py:168) Payment remains explicitly `verified_unsettled`. [routes.py](../../docket/api/routes.py:965)

## F. Other mistakes

- Rewriting the test that forbade v1→v2 was legitimate. Navigation is not evidence; v1 JSON shape and figures remain guarded. [test_advantage_v2_api.py](../../tests/test_advantage_v2_api.py:619)
- Claude left false prose saying the link is still one-way and v1 HTML remains byte-for-byte unchanged. [test_advantage_v2_api.py](../../tests/test_advantage_v2_api.py:7) [advantage-v2.html](../../docket/api/web/advantage-v2.html:74)
- The repository still says one-entry/all-three coverage is unverified, despite the owner’s confirmation. [SYNTHESIS-V2.md](../../docs/deliberation/2026-08-14-SYNTHESIS-V2.md:332)
- The full 825-test claim could not be independently rerun because this read-only sandbox has no writable temporary directory. Nineteen targeted Range tests passed. I could not independently re-probe the wallet or inspect the live DB/VPS.

The owner’s confirmation removes registration from the critical path. VPS access removes the explorer/RPC excuse and means live capture, canaries and v3 data collection should run there. It does not create the missing funded LP or authorize spending. It does not justify restoring the refresh daemon.

## Next three things

1. **Repair v3 before locking any input.** Update [spec.py](../../docket/advantage/v3/spec.py), [test_advantage_v3_spec.py](../../tests/test_advantage_v3_spec.py), and all three `docket/advantage/v3/specs/*.json`: stable stage-one hash, real referenced-file digest verification, stage-two field-delta restriction, objective middle-score anchors, fixed materiality thresholds, deterministic selection, and correct Warden denominators/precision formulas.

2. **Finish the exact Range hire and controlled VPS capture.** Update [doctor.py](../../docket/agents/pancake/doctor.py), [positions.py](../../docket/agents/pancake/positions.py), [catalogue.py](../../docket/hire/catalogue.py), [app.js](../../docket/api/web/app.js), and their Range/web tests. Produce the eight sections in the mandated order, fix incomplete-scan truthfulness, and lock `01-range-positions.json` only after the owner-funded LP exists.

3. **Build exact-once flat `$0.50` settlement and paid-stock admission.** Update `docket/hire/catalogue.py`, `docket/hire/x402.py`, `docket/hire/receipts.py`, `docket/store.py`, `docket/api/routes.py`, and payment/API tests: remove SOLVENT from paid stock, set `0.50 $U`, preflight no-result/no-charge, settle once, persist nonce/payment ID, bind payment→input→output, and reject or idempotently replay the same authorization.

No files, commits, deployments or funds were changed.
