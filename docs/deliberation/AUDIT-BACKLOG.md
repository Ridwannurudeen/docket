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

## 6. `dd4fa8b` — Close the exclusion's own gaps, and stop over-claiming in the registration

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

## 7. `cd31b37` — Stop calling the pool's rate this position's earnings

**Status: OPEN FOR CODEX.** Fable: not reviewed. **This closes a defect Codex raised itself**
(LP ruling §5), so it is the first entry Codex can check against its own instruction.

`position_fee_apr` and `position_annual_fee_usd` were the pool-wide TVL-normalised net rate,
published under names asserting they were the position's. A v3 position earns in proportion to
its share of the liquidity active at the traded tick; nothing here measures that, so a
full-range position was credited with a rate it demonstrably does not earn.

Renamed to `pool_net_apr_if_in_range` and `pool_rate_at_declared_value_usd` across the API, the
v3 scoring projection, the canary field check and the browser presenter ("Pool net rate while in
range", "Pool rate at your declared value"). `RATE_LIMITATION` now states that the pool rate is
not the position's rate, why, and that the dollar figures are a fixed-notional proxy. A test
fails if either retired name reappears in `doctor.py` or if those clauses leave the limitation.

Verified: renaming back to `position_fee_apr` fails the new test. Neither field appears in any
registered v3 spec, so no protocol hash moved.

**Not verified, and worth Codex's attention:**

- This is a **labelling** fix, which is what Codex's ruling asked for. The **real** concentrated
  earnings figure is still not computed. Doing so needs the pool's active liquidity at the tick
  alongside the position's own, which is another chain read per position — not attempted.
- The v3-01 registered truth fields (`annual_gross_usd`, `annual_net_usd`,
  `annual_overstatement_usd`, `cost_only_break_even_days`) are all pool-rate-derived too and were
  **not** renamed, because they are inside the protocol hash. They carry the same proxy caveat
  and say so only via the limitation.
- Prod still serves the old field names until the next deploy.

## 8. `81addbb` — Start the controlled position's history while it is still happening

**Status: OPEN FOR CODEX.** Fable: not reviewed. **Installed and firing on the VPS 2026-08-15T21:41:39Z**; day one recorded at block 116154206.

Codex's LP ruling §3 asked for current ownership recorded at every daily observation and a
"state → diagnosis → owner decision → later state" record, never claimed as causal alpha. This
is that record. It begins now because a history cannot be backfilled: a position observed once
on judging day is a screenshot.

`docket/agents/pancake/lp_record.py` calls `doctor.report` — the same function the hire route
calls at `catalogue.py:376`, not a second implementation, so the record cannot drift from what a
buyer receives. One JSONL line per day, append-only.

Verified here: a failed read still writes a line carrying the exception, because a gap in an
append-only file is indistinguishable from nobody having run it; a closed or transferred
position records `still_held: false` rather than vanishing; lines are canonical JSON; `main`
returns non-zero on a day that produced no diagnosis even though the failure was recorded.

Caught during the build and worth noting as the same class as entry 2: `observe` originally
defaulted `reporter=doctor.report` in its signature. A default binds at import, so the seam was
unpatchable and a test that believed it had substituted a reader silently hit the live chain —
17s of real network in a unit test. Resolved at call time now.

**Not verified, and worth Codex's attention:**

- Installed 2026-08-15 and fired once by hand so the history starts the day the position was
  funded. Next scheduled 06:00Z daily. Only one day exists; nothing has yet exercised the
  catch-up path, a failed read in production, or a day on which the position is out of range.
- The declared value (50.55) and recenter cost (1.00) are baked into the unit's ExecStart. If
  either is revised, the unit is the place that has to change, and nothing checks the two agree
  with what any report or registration says.
- `Persistent=true` deliberately differs from the v3 capture's `false`: a late observation is
  still true of the position and is timestamped by when it ran. That reasoning was not audited.
- No retention, rotation or size bound on the JSONL. One line a day is small, but nothing caps it.

## 9. `b4f4e5c` — Make the Aug 21 capture something that will actually happen

**Status: OPEN FOR CODEX.** Fable: not reviewed. **This closes Codex's own unanswered audit
question** (`CODEX-AUDIT-CAPTURE-BRIDGE-2026-08-15.md` item 3), so it is checkable against the
question that raised it.

🔴 **The capture timer was never installed.** `docket-v3-capture.timer` did not exist on the VPS
and `/var/lib/docket/v3-capture` did not exist either. The registered moment — 2026-08-21
12:00:00Z, one shot, no recapture — would have passed with nothing running, and the protocol
says a missed moment means recommitting the family. Installed, enabled, scheduled
`Fri 2026-08-21 14:00:00 CEST` = 12:00:00 UTC, matching `YIELD_CAPTURE_ATTEMPTS[0]` exactly.
NTP is synchronised on the box, so the registration's 5-second tolerance stands.

**Codex's question 3 answered, against the real endpoints:** the live PancakeSwap bodies parse
through `_pool_rows`, `_token_allowlist` and `_partition` unchanged — 25 rows, 973 BSC tokens,
**21 pools clear the gates against `n_planned` 5** — and the full capture→assemble→lock sequence
run over those exact bodies **locked against the real validator**. That also settles its
question 1: the transcribed truth arithmetic in `_cases` agrees with `_validate_yield_inputs`'s
independent recomputation within `math.isclose(rel_tol=1e-12)`, because the lock accepted it.

Also verified: running the capture early is refused with the registered reason and exit 2, and
writes nothing. Hardened `_resolve_spec`, which crashed with `PermissionError` rather than
falling through to the packaged spec when the working directory could not be stat'd —
reproduced on the VPS, and the capture does not get to fail on the readability of a directory
it never uses.

**Not verified, and worth Codex's attention:**

- The rehearsal used bodies captured **2026-08-15**. It cannot detect a PancakeSwap shape change
  between now and Aug 21. **Re-run it on Aug 20** — the procedure is the script at
  `scratchpad/rehearse_yield.py`, which substitutes live bodies into
  `tests/test_advantage_v3_assemble.py`'s fixture and asserts the lock. It is a scratch script,
  not committed; a committed one nobody runs would be worse, but this is a real gap.
- The rehearsal's `evaluator_calibration` is synthetic (`test-build`, perfect answers). The real
  seat runs do not exist, so **the Yield family still cannot be locked for real** even after a
  successful capture. Capture and lock are separable, and only capture is ready.
- Codex required the registration be **externally anchored** before the capture. It is not.
  `docs/source-deploy-manifest.md` already states the GitHub push witnesses existence but not
  authorship, and names OpenTimestamps as what would close it. Owner-gated, still open.
- Nothing tests the systemd unit's ExecStart arguments against the module's actual CLI.

## 10. `a8ba05b` — A comparison surface, including the services with nothing to show

**Status: OPEN FOR CODEX.** Fable: not reviewed.

Codex's win spec (Marketplace quality, 20%) asked for one comparison table — "job, price,
measured time saved, quality/sample size, freshness, limitation, evidence" — and noted the plan
"still lacks an actual service-comparison surface".

`docket/hire/comparison.py` + `GET /compare`, documented in `llms.txt`. Live output: **6
services, 3 with a paired measurement** — range-doctor 485.2s saved, solvent-signal 219.9s,
warden-scan 71.6s, each n=1 with its source file named — and grid-operator, yield-router and
health-guard each carrying the sentence that no paired run against a human exists for them.

The design rule is that a cell is a measurement with its source and denominator, or a stated
reason there is none. Never blank, never zero, never a figure borrowed from another service. A
missing recorded run reports differently from a service that was never measured, because those
are different facts. Admission limbs are **named**, not counted.

Verified: 9 tests, including that every entry in `MEASURED_BY` maps to a file that exists, that
an arm without an elapsed time does not silently become a saving, and that unmeasured rows carry
no `seconds_saved`/`sample_size` keys at all rather than nulls.

**Not verified, and worth Codex's attention:**

- The table is now rendered on the home page (follow-up commit), using only stylesheet classes
  that exist — an undefined wrapper would have let a five-column table run off a phone. What is
  **not** verified is how it looks: no browser has opened it, and no cold reader has tried to
  compare with it. That is what the Aug 27–31 uncoached sessions are for.
- Codex named seven columns. **Freshness and evidence are not implemented**, and "quality" is
  represented only by sample size. Freshness needs a per-service data-recency notion that does
  not exist yet; evidence needs a per-service link to the specific artifact.
- `typical_seconds` is a catalogue declaration, not a measurement, and sits in the same table as
  measured seconds. Nothing marks that difference to a reader.
- The three savings come from v1 runs recorded 2026-08-08. Nothing reports their age.

## 11. `00528ea` — Capture what each seat was asked and what it actually said, once

**Status: OPEN FOR CODEX.** Fable: **guided this build**; has not reviewed the result.

Codex's step 3 of six for the Warden lock: "first-write capture of each seat's exact prompt,
untouched response bytes, model/build, session, timestamp and response hash. Preserve failed
attempts; do not select a later passing run." Steps 1–2 landed at `72b709d`. Steps 5–6 (external
anchor, real seat runs) remain gated.

`docket/advantage/v3/calibration.py`, reusing `scoring._write_exclusive` rather than copying it.
Request record written **before** the call, response record written **always** including on
failure. **The binding attempt is the first that produced bytes, whatever they say.** The write
gate refuses a further attempt once anything has been captured; each attempt names the digest of
the previous attempt's response file, so a removed attempt leaves a dangling link rather than an
invisible gap. The prompt is **derived** from the registration, not recorded as sent — what was
actually sent cannot be verified past this boundary, so derivation is the only defensible anchor.

The bridge does **no scoring**: `spec._validate_evaluator_calibration` remains the one place the
7/8 and 0.80 micro-F1 floors are computed. Expected answers come from the shared key, never from
the seat's own reply.

Verified by mutation, 5 for 5, including both mutations the interim auditor named as the ones a
tautological suite would miss: binding `max(ordinal)` instead of the first captured attempt, and
`except JSONDecodeError: continue` falling through to a later, better-looking run. Both tests
assert **which attempt's values reach the envelope**, with a superior second attempt planted
directly on disk bypassing the write gate — not merely that something raised.

**Not verified, and worth Codex's attention:**

- 🔴 **This is not deletion-proof and the module says so.** An operator owning the filesystem can
  delete a seat's directory and start over, or run a model out of band and record the attempt as
  `no_response`. The retry rule itself creates that second incentive. The stated guarantee is
  only: everything that passed through the machinery is preserved and ordered. The intended
  mitigation — committing artifacts as they are written, so the remote history anchors them — is
  **not implemented and not enforced anywhere.**
- Nothing yet calls `verify_calibration_capture`. It exists and is tested; no producer of an
  envelope is required to run it, so an envelope assembled by hand still locks.
- The derived prompt's wording is my authorship, not the registration's. It is fixed by the
  protocol hash once used, but no auditor has read it for whether it leads the seat.
- `assemble.py` still takes `evaluator_calibration` as a parameter. Wiring the bridge into the
  real assembly path is not done.
- Zero real seat runs exist. This is machinery with no evidence through it yet.

## 12. `aaba01a` — CI has been failing at zero seconds since Aug 15, and nothing here noticed

**Status: OPEN FOR CODEX.** Fable: not reviewed. **Codex wrote the commit that broke this**
(`49765f0`, "Built by Codex, audited here"), so this entry is a correction to its own work and
to the audit of it — mine — that let it through.

Every CI run since `49765f0` failed in **0 seconds with no job started**: eleven consecutive
failures across two days. GitHub reports that as "this run likely failed because of a workflow
file issue", which reads like infrastructure trouble rather than a syntax error in a tracked
file, and nothing on this side ever parsed the workflow.

The defect, at `.github/workflows/ci.yml` line 30 column 52: in YAML a value beginning with a
quote **ends at its closing quote**, so `run: "$RUNNER_TEMP/venv/bin/python" -m pip install …`
is a quoted scalar followed by text the parser cannot place. Two steps had it. It looks exactly
like a shell line that would work. Fixed with block scalars.

Second defect, independent and arguably worse: `on.push.branches` was `[main]` while every
commit since Stage 4 has landed on `docs/deliberation-round2`. **Even with valid YAML, CI would
have run nothing on the branch carrying the work** — and the package job it added exists
precisely to catch the packaging defect that has now shipped three times. Trigger widened to
`[main, "docs/**"]`.

`tests/test_workflows.py` now parses every workflow, checks each `run:` command survives parsing
whole, and asserts the working branch is covered. Verified by reintroducing the original line:
three tests fail. `pyyaml==6.0.2` added to the `dev` extra for it.

**Not verified, and worth Codex's attention:**

- ✅ **Resolved: run 31943515697 is green.** `test` passed in 1m8s and `package` in 22s — the
  first completed run since Aug 11, and the first time this work has been checked on Linux by
  anything other than my own Windows machine. The wheel builds, installs outside the checkout
  and smoke-tests there on a runner, which is the claim the package job exists to make.
- The runner warns that `actions/checkout@v4` and `actions/setup-python@v5` target Node 20 and
  are being forced onto Node 24. Not a failure today; it will become one. Unaddressed.
- CI said nothing about any commit between Stage 4 and `aaba01a`. Every "N tests pass" recorded
  in entries 1–11 of this file is a local Windows claim that no runner ever checked. They are not
  retroactively verified by this run — only the tree at `aaba01a` is.
- The quote-balance check is a heuristic. It catches this defect; it does not make the workflow
  correct.
