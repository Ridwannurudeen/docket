# Fable 5 — audit of the v3 lock (commit `8125fc0`, 2026-08-14)

_Auditor, read-only. Reviewing Codex's repair of the v3 pre-registration machinery on branch
`docs/deliberation-round2`, HEAD `8125fc0`. Roles: Codex builds, Claude and Fable audit._

The question this audit answers: **does the claim "the question provably predates the inputs, and
the inputs provably predate the runs" survive a hostile read?**

---

## Method note — what I ran, and what I could not check

Everything below was **run**, not reasoned. All attacks executed against a throwaway `git clone` of
the repo in my own temp dir, with `repo_root` pointed at the clone so no v3 input was ever locked and
no arm ever ran in the real tree. I made **no writes to the repository** other than this file.

What I ran:

1. **Sanity pass.** `load()` on all three shipped specs; both stored hashes (`stage_one_protocol_hash`,
   `spec_hash`) recompute exactly. All three carry `inputs_sha256: ""` — nothing is locked, as required.
2. **Backdate demonstration (the money shot).** In the clone, weakened the Warden ship gate
   (`at least 0.90` → `at least 0.50`) in the registered `claim`, re-saved through the library's own
   `save()`, and committed it with `GIT_AUTHOR_DATE`/`GIT_COMMITTER_DATE` set to 74 minutes *before* the
   real registration commit. Result: the forged commit `load()`s cleanly and reads as the **earliest**
   v3 registration by timestamp.
3. **Hand-authored bypass.** Wrote a JSON with a rewritten protocol and both hashes recomputed the way
   the library computes them. `load()` **accepted** it, minting a new self-consistent
   `stage_one_protocol_hash`. The two-stage `save()` guard is real, but it only governs edits *through the
   library*; a from-scratch hand-authored file is bounded only by internal self-consistency and git.
4. **Seed binding.** Confirmed the blinding seed `SHA256(stage_one_hash || inputs_sha256 || salt)`
   changes when either hash changes — a run under a different protocol produces a different blinding, but
   nothing external forces *which* protocol governed a given run.
5. **Determinism / no-cherry-pick.** Read the selection code: cases are forced to the lowest
   `SHA256(stage_one_hash || …)` within each stratum, so the input author cannot choose which
   positions/pools become cases.
6. **No network in the validator.** Grepped and read `lock_inputs`/`assert_runnable`: validation is
   purely local byte-hashing (`path.read_bytes()`, `hashlib.sha256`, embedded base64). No RPC, no HTTP.
7. **Independent test run.** At a clean `8125fc0` clone, `test_advantage_v3_spec.py` + `test_ingest.py`
   = **55 passed**. (Claude already ran the full 855 and mutation-tested the digest check; I did not repeat.)
8. **Git witness state.** `git ls-remote origin` and `git merge-base --is-ancestor` for every registration
   commit.

What I could **not** check:

- **Whether the frozen input bytes are the true on-chain / live-endpoint state.** No input is locked yet,
  and even once locked the validator never contacts a chain or an HTTP source (finding S3). I can verify
  internal consistency and determinism; I cannot verify authenticity of captured bytes.
- **Whether the git history has already been rewritten.** With no external anchor there is nothing to
  compare against; I can only report that the history is currently local-only and forgeable (S1).
- **The real repo's full suite as it now sits** — a concurrent build session (Codex) is actively writing
  test files into the working tree during this audit (see the adjacent finding). I read a moving tree, so
  I took my green reading from a pinned clean clone instead.

---

## Findings, ranked by severity

### S1 — CRITICAL. The git witness is local-only and self-controlled, so "provably predates" is currently "predates by dates we own."

Every spec's `registration_provenance` says: *"Git history is the registration witness: the first commit
containing this exact stage-one protocol hash establishes that the repaired protocol predates later
input-lock and run commits."* The entire pre-registration claim rests on that one external fact.

That witness does not exist off this laptop. `git ls-remote origin` returns only `main` (`0fb9c77`) and
`feat/phase0`. Every registration commit is unreachable from any pushed ref:

```
88cc2bc reachable-from-origin/main: NO      (register the three v3 specs)
93c103b reachable-from-origin/main: NO
8125fc0 reachable-from-origin/main: NO      (make the v3 lock a lock)
```

The chain `88cc2bc … 8125fc0` lives only as a mutable file tree on the author's own machine. A hostile
judge does not need to argue amend/rebase mechanics — the history can be rewritten wholesale and no
external copy contradicts it. I demonstrated it:

```
git log --date-order (after forging a weakened Warden registration):
2026-08-14T19:00:00  b2ecbb6  feat(advantage): register the three v3 paired specifications ...
2026-08-14T22:26:31  8125fc0  feat(advantage): make the v3 lock a lock ...
2026-08-14T20:54:08  93c103b  ...
```

The forged commit carries a Warden gate of `0.50` instead of `0.90`, `load()`s cleanly, and by timestamp
reads as the original registration. (The naive amend I ran leaves one tell — a child commit older than its
parent; a full rebase of the unpushed chain with monotonic backdated dates removes even that.)

This is not a code defect. `spec.py`'s own docstring is honest about it: *"No file can prove its own
history."* The specs correctly disclaim any wall-clock registration time. But honesty about the limitation
does not remove the limitation. **Until the stage-one commit is anchored outside our control** — pushed to
a remote we do not own the history of, plus an external timestamp (OpenTimestamps, an on-chain hash of the
commit id, or a public PR with a server-side authored date) — the "provably predates" half of the claim is
unproven to anyone but us. This finding is what decides the verdict.

### S2 — HIGH. Every independence the design leans on is self-attested by owner-controlled identities the code cannot tell apart.

The rubric and input schema assume independence between roles: two blinded evaluators, two independent
label authors plus a separate adjudicator, a distinct calibration author, and a manual operator who never
saw the labels. The code enforces this only as **distinct id strings with all-false conflict booleans the
author types in**:

- Evaluator seats are literally `claude-audit-seat` and `fable-5-audit-seat` — two models under one
  operator. `_validate_evaluator_calibration` checks that each seat's `conflicts` dict is all-`False` and
  that ids are distinct; it cannot detect that both seats, and the person running them, are the same party.
- Warden's `_validate_warden_inputs` requires two label authors with distinct `author_id`s, an adjudicator
  distinct from both, and reconciled disagreement — ~360 lines enforcing a two-independent-labeller
  process whose independence is a set of self-declared strings.
- The calibration author is validated the same way: `author_id` not in the evaluator roster, four all-`False`
  conflicts.

A hostile judge reads "Claude and Fable 5, calibrated and blinded" as **one vendor scoring its own product
with its own two models**, and reads the two label authors + adjudicator as the same owner wearing three
hats. The cryptographic machinery is real; the social facts it certifies are not verifiable by the machinery
and, as currently populated, are not true. This is the second thing a skeptical reader attacks after S1.

### S3 — MEDIUM. Input authenticity is enforced only where a third party could re-derive it; the pool/token snapshots rest entirely on author honesty.

`lock_inputs` makes no network call. It validates internal consistency and deterministic selection over
bytes the author supplies. That splits cleanly into two halves:

- **Re-derivable in principle:** the Range `transfer_logs` and `position_enumeration` sources pin the real
  contract addresses (`RANGE_POSITION_MANAGER 0x46a1…`, `RANGE_MASTER_CHEF 0x556b…`) and specific block
  numbers. A third party with a BSC archive node can recompute them after the fact, so fabrication *there*
  is detectable in principle.
- **Not re-derivable:** `pool_truth` (PancakeSwap explorer top-pools) and `token_list` are HTTP snapshots
  captured at a specific minute from live endpoints with no historical cache. Once the minute passes, no
  one can reproduce those bytes. They rest **entirely** on the author having honestly captured real data.

The shipped test `test_each_family_schema_accepts_only_a_complete_synthetic_input_artifact` already proves
the point: it constructs fully **fictional** chain data and `lock_inputs` accepts it. The validator gates
*structure and determinism*, not *truth*. This is inherent to preregistration — its job is sequencing, not
data provenance — but the claim should name the boundary rather than let a reader assume the frozen bytes
are chain-attested. The pool/token half in particular is a trust-me input dressed in a SHA-256.

### MEDIUM (adjacent to the audited commit, not part of it). The working tree is mid-build and currently red; the adopted "855 passing" is not reproducible against it.

The working tree was clean at my first `git status`. During the audit it grew to five modified test files
(`test_pancake_doctor`, `test_pancake_positions`, `test_hire_api`, `test_hire_catalogue`,
`test_web_categories`), with on-disk mtimes inside the last few minutes — a concurrent Codex build session
writing the Range-presenter and flat-`$0.50` settlement work that Codex's own EXEC-AUDIT listed as next
steps. Replayed against committed source, **8 of those tests fail** (e.g. `PositionReader.wallet_positions()
got an unexpected keyword argument 'token_id'`; `diagnose()` provides none of `verifiable_facts` /
`economic_consequence` / `conditional_actions`). This is **not a regression in `8125fc0`** — the audited
commit's own nine files are pristine in the working tree and its own tests pass (55 in the clean clone). It
only means: do not measure the suite against the working tree right now, and treat "855 green" as a claim
about a pinned commit, not the live tree.

### LOW / observation. The Warden precision gate is brittle to a single benign misfire.

The registered `Precision = TP/(TP+FP)`, ship gate `≥ 0.90`, with the schema minimum of ≥4 hostile and ≥4
benign (populated as 8 hostile / 4 benign in the fixtures). One benign false positive gives `8/9 = 0.889 <
0.90` and fails the gate. This is the registered formula behaving strictly, not a defect — but a judge will
note that the ≥0.90 precision result turns on a single classification at n=12, and `≥0.99 successful scans`
is effectively a 12/12 point gate (11/12 = 0.917). The evidence is real but thin; the claim is honest that
it is bounded to 12 authored cases and is "not a population confidence estimate."

---

## What holds (confirmations — Codex's repairs land)

These were the defects Codex was repairing (CODEX-EXEC-AUDIT sections A and B). All are genuinely fixed:

- **The two-stage lock now verifies bytes, not a filled-in field.** `assert_runnable` re-reads the
  referenced file and compares `sha256` with `hmac.compare_digest`; `lock_inputs` computes the digest from
  the file rather than accepting one from its caller; the in-place `save()` transition permits only
  `inputs_sha256` to change. I re-confirmed `load()` recomputes both hashes for all three shipped specs.
- **Selection is deterministic and un-cherry-pickable** — lowest hash within each stratum, keyed to the
  stage-one hash.
- **Warden denominators are named and the ship gate is encoded faithfully.** Recall = TP/every frozen
  hostile; precision = TP/(TP+FP) with null defined; zero-critical-survivor computed from survival
  predicates against effective downstream text; ≥0.99 = 12/12 scans. This is exactly the win-spec gate
  (≥90% recall, ≥90% precision, zero critical survivor, ≥99% scans). The "denominator of nothing"
  contradiction is gone.
- **Materiality is a fixed number** (30.0s median saving, 0.50 ratio), not "any lower median."
- **The rubric is objective on paper.** Every criterion defines all four score levels against factual
  anchors keyed to frozen truth, and the scale note explicitly disowns "what a reader would do." No
  criterion is scoreable-to-fit: each is a presence/exact-match/within-tolerance check against a frozen
  answer key. Two strangers with the key would score consistently — *if* they were actually strangers (S2).

---

## Are the 2,624 lines justified?

**Use the discriminator: a line earns its place iff deleting it would let a fabricated, hand-authored, or
post-hoc-modified artifact pass.** By that test the file splits.

- **Justified (~the bulk, roughly 1,900 lines): the family truth-recomputation validators.** `_validate_range_inputs`,
  `_validate_yield_inputs`, `_validate_warden_inputs` and their helpers recompute every economic truth
  (APR, dollar overstatement, break-even, move/stay decision) and every evidence span/survival predicate
  from the frozen bytes, and reject a hand-authored manifest that differs. Delete them and a cherry-picked
  or internally-fudged answer key passes. That is the whole point of the lock; the length is the cost of
  making the answer key non-forgeable relative to the frozen inputs. Keep it.

- **Theater (~600–700 lines): the independence/conflict paperwork.** The Warden two-author + adjudicator
  apparatus (~360 lines around 2100–2464) and the per-seat evaluator-calibration artifact plumbing (~290
  lines, 1387–1680) enforce *social* facts — who is independent of whom — that the code cannot verify and
  that are, as populated, one owner in every seat (S2). The all-`False` conflict field-sets
  (`CALIBRATION_CONFLICT_FIELDS`, `WARDEN_*_CONFLICT_FIELDS`) prove nothing an adversary could not simply
  type. This layer manufactures an *impression* of rigor a judge can turn against the artifact.

Concrete cut/keep guidance: **keep the calibration logic** (recomputing the answer key from the registered
formulas — that is a real correctness check). **Cut or externalize the identity/conflict attestation** —
either make the roles genuinely independent (different people/orgs, external attestation) or stop encoding
self-declared booleans as if the code proved them. A shorter, honest schema that says "these seats are
owner-run, here is the blinding we could enforce and the independence we could not" is more defensible to a
judge than 650 lines that look like they establish independence and do not.

Net: the file is **mostly** justified by its goal, but a meaningful minority is validation of things code
cannot validate, and that minority is exactly what a hostile reader would seize on.

---

## Do the three families produce evidence a skeptic would accept?

- **Range (n=5):** strongest. Rubric anchors are objective and keyed to frozen chain truth; strata force
  coverage of in/above/below-range, failed-gate and lowest-hash cases; selection is deterministic. Honest
  evidence here would be persuasive **once a real funded LP and a real capture exist** (still pending) and
  **once the scoring seats are independent** (S2).
- **Yield (n=5):** objective and deterministic, but it is a branch-coverage suite over one frozen top-pools
  response, and its completeness rests on the non-re-derivable HTTP snapshot (S3). A skeptic accepts it as
  "correct against these exact bytes," not as "representative."
- **Warden (n=12):** the gate math now faithfully computes the ship threshold, and that is the real repair.
  But its persuasiveness is capped by n=12 brittleness (a single FP sinks precision) and by S2 — the two
  label authors, the adjudicator, and both evaluators are owner-controlled identities.

All three are **objectively scoreable by two people who never spoke** — the rubrics are that tight — but the
two people the specs name are Claude and Fable 5, and that is the gap between "objectively scoreable" and
"independently scored."

---

## Verdict

**No — not as it currently stands.** The machinery is sound for what code *can* do: the lock verifies bytes,
selection is deterministic, the denominators are named, the ship gate is faithfully encoded, and the specs
are honest about their own limits. Codex's repair is real and its headline fixes all land.

But the claim under audit is "the question **provably** predates the inputs." That word rests on exactly one
external fact — that the stage-one commit came first — and that fact **has no witness outside the author's
own machine.** I reproduced a weakened registration backdated ahead of the real one; it loads clean and
sorts first. Right now "provably predates" means "predates according to dates we control."

The verdict is therefore **conditional**, and the conditions are specific and cheap:

1. **Anchor the stage-one commit outside our control** — push the registration chain to a remote whose
   history we cannot rewrite, and add an external timestamp (OpenTimestamps / an on-chain hash of the commit
   id / a public PR with a server-authored date). This converts S1 from open to closed and is the single
   highest-value action.
2. **Make the evaluator/labeller independence real, or downgrade the claim to match reality** (S2).

Do (1) and the sequencing claim survives a hostile read. Do (2) and the scoring claim does. **Code ready;
witness absent.**

_No files, commits, deployments or funds were changed by this audit. No v3 input was locked and no arm was
run — the standing ruling this commit exists to protect was honored._
