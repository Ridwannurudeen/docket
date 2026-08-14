# Docket — Synthesis & Roadmap (2026-08-12)

> **SUPERSEDED 2026-08-14 by [`2026-08-14-SYNTHESIS-V2.md`](2026-08-14-SYNTHESIS-V2.md).**
> This document is preserved unedited below as the record of what was decided on 2026-08-12 and
> why. Its Path A/B framing produced Stages 0–4, which are now shipped and deployed. Read it for
> history; read v2 for the operative plan.

Three independent assessments (Claude plan/audit, Codex on max reasoning, Fable 5 independent), reconciled. Every load-bearing technical claim below was re-verified by Claude against the live code/data this session — the three integrity bugs are confirmed, not relayed.

## The one-paragraph truth

Docket is the best-built thing in this program and currently loses the demo. It built the hardest-to-fake thing first — a code path and culture for saying exactly what was observed — but overlearned the no-verdict lesson and under-built the product. As it stands: **TermiX is ours to lose; PancakeSwap is a legitimate but soft fit; BNB main track is not ours to win yet** — we forfeit the human journey, forfeit real-time data, and have *zero* rubric-complete categories (not one). And the evidence layer itself carries three integrity bugs that a TermiX-grade judge would catch.

## Verified corrections to Claude's opening position

| Claude said | Truth (verified) |
|---|---|
| "Yield covered; 1 of 4 categories" | **Zero of 4 at rubric depth.** Range Doctor diagnoses but doesn't *manage/reset* (Rebalancing) or *route to highest APR* (Yield). BNB's category verbs aren't met. |
| "Agent Diversity is data-and-config" | **Wrong — it's a build.** The 4 categories are near-empty in the indexed population (rebalancing 0, grid 1, yield 3, health 0–4 of 506). You cannot tag empty shelves. |
| "Data Quality is our strength" | **Half-true.** We win integrity; we *fail real-time* (snapshot 6 weeks stale by judging, no refresh loop). |
| "Functionality: skeptic-shaped" | **Understated — the human activation journey does not exist.** No hire control in any page, no category concept, CORS GET-only. |

## Three confirmed integrity bugs (fix before leaning on "evidence" as the moat)

1. **`responded_pct_of_probed` counts un-probed targets.** `coverage.py:46` sets `probed = len(observations)`, including the 10 blocked + 11 unresolved that never made an HTTP request (the file's own comments say so). Live `/stats` publishes `13/35 = 37.143%` under a field name that promises "of probed." Honest split: **13 responded / 14 attempted (92.9%)** and **13 / 35 targets evaluated (37.1%)** — both fine with correct labels; the current single mislabeled number is not.
2. **`latest_snapshot_id` (store.py:157) has no `finished_at` filter.** Returns the max id regardless of completion. Safe today (snapshot 3 finished) — but an unfinished snapshot 2 exists in the DB, and the moment we add automated refresh, a crashed sweep becomes the served snapshot. **Must fix before the refresh loop, not after.**
3. **`publisher_key` (signals.py:37) is `name.split()[0]`** — name-family, not minter provenance. Rename to `name_family`; derive real provenance from chain history later.

## The unlock both Codex and Fable converged on: three planes

The no-verdict discipline was mis-scoped. It belongs to ONE plane, not the whole product.

- **Fact plane** — registry, liveness, bounded task outcomes, provenance. No global trust/safety/recommend verdicts. *(This is today's Docket, keep it.)*
- **Policy plane** — evaluate the user's *own stated* constraints ("observed inputs satisfy 4 of your 5 predicates; here's the one that failed"). Not a verdict — it's the user's own rule, checked.
- **Action plane** — simulate and execute only user-authorized actions inside on-chain-enforced caps.

**The key distinction (Codex, sharp):** *"Docket issues no global trust verdict"* does NOT mean *"correctness is out of scope."* We can and should measure **bounded task correctness against precommitted ground truth** — numerator/denominator/window/method/dataset-hash — and refuse only the unqualified `best`/`safe`/`trust_score`. That is evidence, and it's exactly what TermiX rewards. This is how BNB breadth and TermiX rigor coexist in one product rather than fighting.

## The resolved disagreement (Fable vs Claude on PancakeSwap execution)

- Fable: **don't** make Range Doctor act (dilutes the "cannot move funds" safety claim; worst points-per-effort for 1,000 CAKE); do a measured before/after experiment instead.
- Claude: leaned toward acting.
- **Codex resolves it, and its resolution wins:** keep Range Doctor **pure read-only** (Fable's safety point stands), and build execution as a **separate, on-chain-capped plane — Grid Operator first.** That one vertical simultaneously fills BNB's missing Grid category, routes real PancakeSwap volume, and is the only credible basis for an Altana session-key rider. Range Doctor's read-only diagnosis becomes an *input* to the planner; the diagnosis engine still cannot move funds.

## Where all three agree (do these regardless of ambition level)

1. **Deploy `main`; kill the live `/escrow` 404.** Repo↔live drift is a submission-blocking integrity bug for a project about claims matching observations. Today.
2. **Fix the three integrity bugs above** — small, and they protect every downstream claim.
3. **Scheduled refresh loop** (after fix #2) — converts "fails real-time" into "strongest in field." Highest points-per-effort on the board.
4. **A human hire/activation page** — scores BNB Functionality *and* TermiX marketplace-quality (20%) at once.
5. **Surface SOLVENT's win-rate / window / risk** on its listing — TermiX names those three; the data exists; the listing shows none.
6. **Keep the Advantage Report's published loss.** Version it (v2), never overwrite it.
7. **Don't chase Agent Studio/`bag`/Bedrock for its own sake** — one submission sentence ("Docket indexes and probes what Agent Studio ships") captures the alignment without a build.
8. **Housekeeping gate (user-approval):** repo public, LICENSE, README, Terms read, `AI_USAGE.md`.

## The strategic fork the user must choose

The full BNB-main-track transformation (4 real category agents at equal depth + marketplace ontology + execution plane + policy plane) is **weeks of work and a genuinely bigger, different product**. Two honest paths:

**Path A — Defend & sharpen (≈1 week, high confidence).** Fix the 3 integrity bugs, deploy main, add the refresh loop, ship the human hire page, add SOLVENT's track-record numbers, do one measured PancakeSwap before/after experiment, reframe the copy (warranty voice), close the housekeeping gate. Outcome: **TermiX 1st ~40–50%, PancakeSwap ~25–30%, BNB shortlist plausible, BNB win still unlikely.** Locks the prizes we actually targeted.

**Path B — Reach for BNB adoption (≈4 weeks, higher ceiling, real risk).** Everything in A, then the three-plane build: marketplace ontology unifying discovery+hire, a shared on-chain-capped action kernel, Grid Operator (Grid + Pancake volume + Altana rider), Range Keeper / Yield Router / Health Guard to four-category parity, v2 Advantage Report with repeated blinded trials and null baselines. Outcome (Fable's estimate): **BNB shortlist ~25–35%, win ~10–15%**, while strengthening TermiX and Pancake. This is the version BNB could actually adopt and grow — and the product with a future beyond the hackathon.

The concurrent OKX competition (live money, Aug 11–25) and the Sep 9 deadline are the real constraints on Path B.

## Recommended course

**Do Path A immediately and unconditionally — it is pure upside and locks the targeted prizes.** Then, if the user wants the BNB ceiling, execute Path B's Grid-Operator vertical first (it's the highest-leverage single vertical: Grid category + Pancake volume + Altana rider + the action primitive every other category reuses) and decide category-by-category how far to push before Sep 9. Never ship a four-category UI before its shelves are stocked — three empty categories score worse than an honest narrower scope.

Execution model (per updated partnership memory): Claude builds with Opus 5 subagents, Fable 5 reviews before each deploy.
