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

## 4. `0d8bd8e` — Protect the input envelope from line-ending rewriting

**Status: OPEN FOR CODEX.** Fable: not reviewed.

`.gitattributes` protected `v3/sources/*` and `v3/specs/*.json` but not
`docket/advantage/v3/inputs/*.json` — the one path `assert_runnable` reopens and rehashes
immediately before either arm runs. Same class as the defect `004bd0f` fixed for the vendor page,
in the directory that did not exist yet when that fix was written.

Not verified: no input envelope exists yet, so this is protection against a failure that cannot
currently be reproduced. The v2 corpus rule was proven by an actual 224-byte discrepancy; this
one is reasoned by analogy.

## 5. `05184cd` — Cover the other connection nobody was testing

**Status: OPEN FOR CODEX.** Fable: not reviewed.

Follow-up to entry 2, which left open that "every other `Web3` construction was not audited for
the same omission" and that the injected-seam blind spot "is a class of gap, not one bug". Both
were swept.

Verified here: `docket/agents/pancake/positions.py` was the only component building a session
without the proof-of-authority middleware. `venus/markets.py`, `execution/authority.py` and
`execution/simulate.py` all route through `escrow.chain.Rpc`, whose `_default_session` has always
injected it. The remaining `Web3()` constructions — `venus/guard.py:96`, `escrow/flow.py:30`,
`escrow/settle.py:72`, `execution/simulate.py:64` — are ABI encoders that never contact a node.

The blind spot itself was real and is now closed: `Rpc` takes a `session_factory`, every escrow
test supplied its own, and the factory production uses had no coverage. Removing the middleware
line from `escrow/chain.py` failed nothing before this commit and fails a test after it.

**Not verified, and worth Codex's attention:**

- `eth.block_number` was treated as safe because `eth_blockNumber` returns a scalar rather than a
  header, so it cannot raise `ExtraDataLengthError`. That is reasoning about web3.py's behaviour,
  not a test. The three call sites using it would be affected the moment any of them fetches a
  block instead.
- The sweep covered proof-of-authority specifically. Whether these components share **other**
  latent chain-shape assumptions was not examined.

## 6. `<pending>` — Close the exclusion's own gaps, and stop over-claiming in the registration

**Status: OPEN FOR CODEX.** Fable: **audited entries 3 and 4 and found real defects in both** —
this entry is the response to that audit, so it has itself had no review.

v3-01 stage-one hash `0xc49c7dd8` → `0x361f830f`, superseding correctly.

Three findings from the interim auditor, all reproduced here before being fixed:

1. **The registration floor had no ceiling.** `_range_conflict_exclusion` required only
   `RANGE_CONTROLLED_WALLETS <= wallets`. A later re-registration could *pad* the list with an
   honest third party's wallet and delete their positions from the draw deterministically — on a
   claim ("we control this") that no reader can disprove from chain, unlike a fabricated
   enumeration. Now equality, so growing the list needs a code change and a re-registration
   together, both visible in git.
2. **One token could be excluded under one holder and drawn under another.** The derivation
   deduplicated within `positions` but never against `conflicted`. Both equality directions
   passed because each set was internally consistent. Both insertions now check the other
   collection.
3. 🔴 **The registration contained the blanket completeness attestation this file claimed it
   avoided.** Entry 3 says the wording states only what was established; the registered text
   actually said the party "attests that these lists name every position it controls". The
   registration is the published, hash-bound half, so the file and the artifact contradicted each
   other and the artifact over-claimed. Corrected: the wording now says the lists are not an
   exhaustive enumeration, marks the evidence-wallet judgement as inferential and names the four
   inferences, and rests the guarantee on the invalidation clause.

**Not verified, and worth Codex's attention:**

- The interim auditor judged the belt-and-braces per-case check in `_validate_range_inputs`
  **provably refusal-redundant** — it changes which message fires, never accept/reject — and
  noted it silently lacks the farm-beneficiary prong. It was kept as regression armor and is
  **not** a second net. Decide whether to make it real or delete it.
- Two guards found mutually redundant across scan orders: disabling either alone fails no test,
  disabling both fails two. That is genuine belt-and-braces, but it means neither is individually
  pinned.
- Dropping the duplicate-declared-conflict guard and allowing extra keys in declared conflict
  records remain invisible to the suite (auditor's finding 5). Cosmetic, unfixed.
- **The Range source files have no `.gitattributes` home yet.** `sources/*` and `inputs/*.json`
  globs do not cross `/`, so if the future capture writes the three typed source files into a
  subdirectory they are unprotected by the defect class entry 4 just fixed. Decide the directory
  before the sampler is written.
- The auditor could not independently re-derive the four evidence-wallet inferences, and takes
  on trust that no sample index or drawn outcome was inspected. `inputs_sha256 == ""` is the only
  checkable half of that.
