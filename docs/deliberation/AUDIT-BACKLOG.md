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
