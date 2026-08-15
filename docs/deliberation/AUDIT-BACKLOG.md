# Audit backlog — work landed while the auditor of record was unavailable

The auditor of record is Codex. Its quota was exhausted on 2026-08-15, and the owner's
instruction is that Codex audits everything when the quota returns — **resuming from where it
stopped and working forward until it catches up to wherever the build has reached.**

This file is what makes that instruction executable. Without it, "where it stopped" is a
question nobody can answer in a week's time.

**Rules.**

- Append an entry on every commit that lands without a Codex audit. Append at commit time, not
  reconstructed afterwards from memory — the point is to record what was believed *then*.
- Fable 5 is the interim auditor and guide. **A Fable pass does not close an entry.** It is
  recorded in the entry and the entry stays `OPEN FOR CODEX`. Fable is a gate, not a substitute
  for the auditor of record.
- Entries are ordered oldest first. Codex works down the list.
- State what was *verified* versus what was *believed*. An entry that only says what was built
  is useless to an auditor; the useful part is which claims were never independently checked.

---

## 1. `72b709d` — Refuse a calibration key that scores seats on classes the vendor never published

**Status: OPEN FOR CODEX.** Fable: not yet reviewed.

Codex specified this work (its ruling of 2026-08-15, §1 steps 1–2) but has **not seen the
implementation**. It ruled on the requirement, not on the code that met it.

What changed: `_warden_vendor_classes()` extracted in `docket/advantage/v3/spec.py` and shared by
`_validate_evaluator_calibration` and `_validate_warden_inputs`; `repo_root` threaded into the
calibration validator; calibration `expected_classes` and both seats' `predicted_classes` now
required to be published vendor classes; distinct seat `session_id` now required.

Verified here: the gap was reproduced by mutation before the fix (`NOT_A_VENDOR_CLASS` locked the
envelope) and refused after. The repository's own positive-path fixture carried the same defect —
it declared `class-0..class-3` as the vendor list and calibrated on `test-class`.

**Not verified, and worth Codex's attention:**

- Whether placing the vocabulary check inside `_validate_evaluator_calibration` (which already
  branches on the Warden family) rather than inside `_validate_warden_inputs` is the right
  partition. It moves a family-specific requirement into the generic path, which is why
  `tests/test_advantage_v3_scoring.py::_locked_family` had to start supplying a vendor snapshot.
- `scoring._warden_vocabulary()` (`docket/advantage/v3/scoring.py:1374`) **falls back to deriving
  the vocabulary from the cases' own labels** when no snapshot is present — a self-certifying
  path. Believed unreachable in production because a locked envelope always carries a snapshot.
  That belief is untested.
- Codex's steps 3–6 of the same ruling (first-write capture of each seat's prompt and untouched
  response bytes, promoting the authored eight-case key, external anchoring, running the two
  seats) are **not built**.

## 2. `3873e2c` — Read a BSC header the way BSC actually writes one

**Status: OPEN FOR CODEX.** Fable: not yet reviewed. **Deployed to production.**

Codex has never seen this. It was found *after* its last run, by calling the live hire endpoint
with the newly funded LP wallet.

The live Range Doctor was returning no diagnosis for any wallet: every endpoint in the failover
list failed with `ExtraDataLengthError` (280-byte extraData) because the connection
`docket/agents/pancake/positions.py` builds for itself never injected
`ExtraDataToPOAMiddleware`. `docket/escrow/chain.py` has carried that exact line all along.
Latent until the observation-block pinning made every read begin with a block fetch.

Verified here: reproduced against a 280-byte header fixture and against live BSC from the VPS —
without the middleware `ExtraDataLengthError`, with it `block=116129096 balanceOf=1
tokens=[7141050]`. After deploy, the live hire returns a decision-grade result.

**Not verified, and worth Codex's attention:**

- Every other `Web3` construction in the codebase was **not** audited for the same omission. Only
  the pancake reader was fixed. There may be more.
- The reason the test suite could not catch it — every positions test supplies its own `w3`
  through `PositionReader`'s injected seam, so the connection production actually builds had no
  coverage at all — **is a class of gap, not one bug.** Any other component with an injected
  seam has the same blind spot and none were checked.
- The deploy itself (release gates, staged replacement, rollback) followed
  `docs/deployment-runbook.md` but was not independently reviewed.
- `position_fee_apr == net_apr` is confirmed live. Codex flagged this as an invalid
  concentrated-position earnings calculation. **Unfixed.**

## 3. `58f0461` — Refuse to draw our own position into our own evidence

**Status: OPEN FOR CODEX.** Fable: guided this build before it was written; has **not** reviewed
the result.

Codex ruled the conflict exclusion mandatory and supplied the registration wording. It has seen
neither the implementation nor the registration that carries it.

Verified here, by mutation rather than by reading: dropping the token-id prong, making the
declaration check one-directional, dropping the closed-position reconciliation, classifying
before excluding, dropping the farm-beneficiary requirement, and disabling either half of the
registration floor each fail exactly one test. The wallet half of that floor initially failed
nothing — the test omitted the wallet and the token id together — which mutation found and
reading did not.

**Not verified, and worth Codex's attention:**

- One deliberate departure from the interim auditor's build order. It asked that a conflicted row
  not increment `closed_count`; that counter is reconciled against the scanner's own
  `closed_skipped` (`spec.py`), so dropping a *closed* conflicted row there would fail an honest
  manifest. It is counted instead, on the reasoning that counting is not classifying. If that
  reasoning is wrong the manifest schema is wrong with it.
- The exclusion is enforced in the validator only. **There is no Range sampler yet.** When one is
  written it must import the validator's own conflict helper rather than reimplement the
  partition, and nothing currently forces that.
- The registration's completeness attestation is deliberately narrower than the auditor asked
  for. It states what was established — the listed token was minted by the party, and the v1
  evidence wallet `0x451871A1753903FB8fdd64a6B838E95aB8D5B80f` was examined and found not to be
  party-controlled — rather than asserting the list is complete, because the owner has not
  enumerated every wallet they hold. **The blanket attestation should be added once they have.**
- The evidence-wallet determination itself rests on four inferences, not on an attestation: no
  key generation exists in the repository, the project's first commit is 2026-08-06 while that
  wallet held 14 positions on 2026-08-08, it has 1,546 outbound transactions where this project
  has sent none, and it gained 8 positions after our last read. Strong, but not the same thing as
  the owner confirming it.
- Whether registering the exclusion should also have re-derived anything else keyed on the
  stage-one hash was not checked beyond the test suite.

## 4. `<this commit>` — Protect the input envelope from line-ending rewriting

**Status: OPEN FOR CODEX.** Fable: not reviewed.

`.gitattributes` protected `v3/sources/*` and `v3/specs/*.json` but not
`docket/advantage/v3/inputs/*.json` — the one path `assert_runnable` reopens and rehashes
immediately before either arm runs. Same class as the defect `004bd0f` fixed for the vendor page,
in the directory that did not exist yet when that fix was written.

Not verified: no input envelope exists yet, so this is protection against a failure that cannot
currently be reproduced. The v2 corpus rule was proven by an actual 224-byte discrepancy; this
one is reasoned by analogy.
