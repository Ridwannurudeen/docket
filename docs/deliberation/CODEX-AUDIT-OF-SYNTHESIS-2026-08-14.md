_Codex CLI 0.147.0, `gpt-5.6-sol` @ xhigh, read-only. Audit of `2026-08-14-SYNTHESIS-V2.md` with Fable's audit as additional input. Its ruling governs per the standing director directive; the one factual correction it makes to the synthesis was independently re-verified by Claude and confirmed._

# Codex audit — Synthesis v2

**Verdict: sound strategic direction, but not operative unchanged.** Reject the pricing departure and the Aug 24 scope reopening; correct the factual and implementation gaps below.

## 1. Pricing — reject the departure

Use the flat **0.50 $U** competition price.

The “measurement-derived” ladder is not actually measurement-derived:

- Grid, Yield, and Health have no recorded manual arms or service metrics (`docket/marketplace/registry.py:73`, `:107`, `:148`).
- The recorded Range and Warden manual arms report direct cash cost of **$0** (`docket/advantage/experiments/01-liquidity.json:123-127`; `03-security.json:54-58`).
- Docket’s harness explicitly refuses to convert elapsed time into money without an hourly-rate assumption (`docket/advantage/harness.py:9-13`). Fable nevertheless does that implicitly and inconsistently.
- SOLVENT at **0.1 $U** is below the verified **$0.50** market floor, directly contradicting the synthesis’s claim that the schedule satisfies that constraint (`2026-08-14-BRIEFING-V2.md:136-143`; `2026-08-14-SYNTHESIS-V2.md:127-138`).

The flat rate’s missed advantage is that it is externally derived—from TermiX’s observed minimum—uniform, auditable, and impossible to mistake for fabricated precision (`CODEX-ASSESSMENT-2026-08-14.md:61-71`).

**Decision:** 0.50 $U for every completed personalized hire through Sep 23; one separate prefilled free sample; remove halted SOLVENT from paid stock unless U2 produces a genuine resumed service.

## 2. BNB scope — do not defer

The Aug 24 revisit is a mistake. Lock BNB to shortlist scope now.

Shared work improves the shortlist; it does not make provider onboarding smaller. A credible supply path needs provider manifests, ownership verification, schema/evidence validation, deploy-free publication, and an independent provider successfully hired (`CODEX-ASSESSMENT-2026-08-14.md:163-179`, `:247`). None of that appears through doing settlement, freshness, or identity work.

If BNB first place was not credible with 26 days, it will not become credible merely because the calendar reaches Aug 24. Reopen only upon a material capacity change—not on a date (`CODEX-ASSESSMENT-2026-08-14.md:263`; `2026-08-14-SYNTHESIS-V2.md:47-52`).

## 3. Ordering — mostly right, with corrections

**Yes:** making v2 discoverable is the highest-value single edit and belongs in Tier 1.

But the synthesis describes it incorrectly. V1 is the paired agent-versus-human eligibility artifact; v2 is methodological armor (`2026-08-14-SYNTHESIS-V2.md:71-86`). Keep the homepage’s single `/advantage` destination, add an above-fold labelled link from v1 to v2, and make the relationship explicit. Do not create competing top-level report destinations or call v2 “the” TermiX artifact (`FABLE-AUDIT-2026-08-14.md:222-227`, `:308`).

Three ordering changes are required:

1. Start the v3 specification in Tier 1, in parallel, not conceptually at Tier 6. Codex specified an Aug 14 kickoff precisely so git proves the specification predates every run (`CODEX-ASSESSMENT-2026-08-14.md:269`, `:279`; synthesis `:217-223`).
2. Make a non-empty, human-readable result part of the Tier 3 paid-hire exit gate. Settlement of empty raw JSON does not prove TermiX value (`2026-08-14-SYNTHESIS-V2.md:189-209`).
3. Restore the conditional Grid-proof implementation lane. U6 asks for a decision, but Tiers 1–7 schedule no downstream implementation if approved (`2026-08-14-SYNTHESIS-V2.md:171`; `CODEX-ASSESSMENT-2026-08-14.md:276`).

## 4. What Fable changes

Fable strengthens the BNB shortlist case: the cold category-to-hire journey genuinely works (`FABLE-AUDIT-2026-08-14.md:118-130`). It does not change the no-first-place conclusion.

It materially raises three priorities:

- The empty flagship response makes owned demo inputs and result presentation release-critical, not polish (`FABLE-AUDIT-2026-08-14.md:90-109`).
- Yield is worse than “advisor-only”: the hire path cannot currently draft at all (`FABLE-AUDIT-2026-08-14.md:169-181`).
- The identity problem is a structural seam between browse and hire, not merely missing identity labels (`FABLE-AUDIT-2026-08-14.md:238-267`).

## 5. Errors, omissions, and softening

- **The “worse than reported” wallet claim is not verified as written.** The synthesis’s `0x916b…` value is the receipt’s `input_hash`; the actual task-01 wallet is `0x4518…B80f` (`docket/advantage/experiments/01-liquidity.json:13`, `:21`). Fable’s evidenced real-wallet probe found 21 held but an empty returned position slice—not zero held (`FABLE-AUDIT-2026-08-14.md:90-102`). Correct synthesis line 112.
- **Registration alone does not join the marketplaces.** Service pages can link to an indexed identity, but agent details expose no associated service or hire action (`docket/api/routes.py:641-671`; `docket/api/web/app.js:1162-1224`). Add the reverse agent → service/hire link.
- **Yield is underspecified.** Adding `wallet` alone is insufficient. Drafting also requires catalogue wiring for the reader, token pair, amount, and cap (`docket/hire/catalogue.py:285-299`; `docket/agents/yield_router/router.py:405-468`).
- **Two immediate UI correctness fixes were dropped.** Grid’s `filled` array is rendered and submitted as text, while large integers pass through precision-losing `Number.parseInt` (`docket/api/web/app.js:392-403`, `:517-529`; `docket/hire/catalogue.py:186`, `:424-428`). Restore Codex’s array control and BigInt-safe handling.
- **Operations stop too early.** Restore persistent service-availability history and uptime/freshness monitoring through Sep 23, not merely through submission (`CODEX-ASSESSMENT-2026-08-14.md:239`, `:246`, `:282`; synthesis `:183-187`, `:230`).
- **SOLVENT is internally inconsistent.** The synthesis both prices its stale historical read at 0.1 $U and says U2 may retire it to research evidence (`2026-08-14-SYNTHESIS-V2.md:127-138`, `:167`). If not genuinely resumed, it is research evidence—not paid inventory.
