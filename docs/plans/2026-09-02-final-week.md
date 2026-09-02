# Final week — close the public-truth gaps and add the two missing evidence limbs

> **Status:** DRAFT for owner approval. No step here authorizes a commit, push, deployment,
> transaction, or submission. Steps use `- [ ]`.

**Goal:** By 2026-09-09, have (a) every public document true of the running system, (b) a
trading record with a stated window and denominators where there is currently none, and
(c) at least one paired benchmark that can pass, run against arms that were genuinely paid for.

**Why this order:** W1/W2 are cheap, are already wrong in public, and need almost no owner
attention. W3 is armed and fires whether or not we act. W4 converts a criterion that scores
zero today. W5 is the highest value and the highest risk, so it goes last and is conditional.

## Context — all verified 2026-09-02 against the repo, the host, and live endpoints

- `main` = `4a632c0`, `origin/main` = `4a632c0`, production `RELEASE-commit.txt` = `4a632c0`.
  Deployed today; rollback tree `/opt/docket.bak-20260902T144652Z`.
- Live admission, all six services `paid_stock=false`. Range Doctor holds
  `decision_grade_presenter=true` and `true_settlement=true`; `fresh_paired_benchmark=false`
  and `cold_canary=false`.
- `cold_canary` is dynamic (`docket/hire/admission.py:34-43`): true only while the latest
  canary run has `verdict == "passed"` and finished within `CANARY_MAX_AGE_SECONDS` (36 h).
  `docket-canary.timer` is `disabled/inactive`; its `OnCalendar` is `*-*-* 04:17:00 UTC`.
- `fresh_paired_benchmark` is a static constant (`docket/hire/catalogue.py:236`). Its written
  definition everywhere — `claims-checklist.md:78`, `operational-evidence.md:212`,
  `SKILL.md:273`, `termix.md:154` — is "fresh paired evidence" / "produces a paired
  benchmark". **No document and no code requires `not_refuted`.**
- v3-05 has 6 scheduled slots. One is terminal: manual case 1, `outcome=interrupted`,
  `eligible_for_speed=False`. `report.py:56-62` refutes on `any_pair_is_incomplete`, and
  `report.py:140` combines checks with `any()`, so **v3-05 can only terminate `refuted`.**
- v3-06 is armed: `docket-v3-yield-v6-capture.timer`, `NextElapse Thu 2026-09-03 13:50 CEST`
  (11:50 UTC), registered observations 12:00/12:01/12:02 UTC. `/var/lib/docket/v3-capture/
  yield-v3-06` does not exist and the service journal is empty — it has never captured.
- `deploy/release.sh:880` refuses releases between `2026-09-03T11:49:54Z` and
  `2026-09-03T12:03:06Z`.
- The v3 harness already supports a paid agent arm: `orchestrator.py:465-466`
  (`--payment-header`, "value of the X-PAYMENT header sent with agent hires") through to
  `runner.py:815`. `routes.py:2205` accepts a payment when
  `payment_header_present and (paid_stock or canary_authorized)`.
- SOLVENT `https://solvent.gudman.xyz/receipts?limit=500` returns the complete chain: 384
  receipts, seq 0→383, window `2026-06-18T17:46:37Z` → `2026-06-29T01:01:04Z`.
  Phases: 278 `cycle_summary`, 55 `pre_trade_commit`, 51 `execution_seal`.
  Seal outcomes: 27 `executed_now`, 22 `unresolved`, 1 `failed`, 1 null.
  37 of 51 seals carry `tx_hash`; **only 1 carries `pre_trade_anchor_tx_hash`.**
  All 384 receipts carry `equity_usd`, but the series is deposit-contaminated
  (`+997.87` on 2026-06-28, `+201.74` on 2026-06-23) and receipts have **no funding field**.

## Global constraints

- Run everything with `./.venv/Scripts/python`. No new dependencies.
- The untracked `docket/advantage/v3/runs/v3-05-range-doctor.jsonl`
  (sha256 `878ae303…1bf8a60`) stays untracked and is never deleted. It makes 6 tests fail
  locally and that is expected — they pass in a clean tree; CI is the authority.
- Never rewrite a dated observation in `docs/operational-evidence.md`. Dated records are
  historically true; corrections are **new dated records**.
- Every published number carries its numerator, denominator, window, and method.
- Deploys are owner-gated. No deploy inside the Sep 3 capture window.
- Wallet operations get explicit owner approval immediately before each one.
- No Claude/Anthropic attribution, no `Co-Authored-By`.

---

## W1 — Make the public documents true again (today; no owner attention beyond approval)

Today's deploy falsified four tracked, public statements.

**Files:** `docs/source-deploy-manifest.md`, `docs/api-and-payment-semantics.md`,
`docs/deployment-runbook.md`, `docs/operational-evidence.md`

- [ ] `source-deploy-manifest.md:16` — `Current production release commit` → `4a632c0…9381`.
- [ ] `source-deploy-manifest.md:36` — the `RELEASE-commit.txt` row and the surrounding
      "Current deployed identity" table → wheel
      `923d410953e11bd98cec7dc9d26ef371ccd6e5c73bb8f11d3ce964c32b3769b6`, runtime-lock
      `2b0fb7bc…` (unchanged), venv `/opt/docket-venvs/4a632c01ebcf`.
      Delete the "one source-only commit after the deployed release / do not describe
      production as running that base" paragraph — source and production are now equal.
- [ ] `api-and-payment-semantics.md:119-122` — remove "Production remains on the pre-update
      `b8b6ed7` runtime and therefore still serves its earlier `true_settlement=false` static
      limb". Replace with the live fact: Range Doctor serves `true_settlement=true`,
      `fresh_paired_benchmark=false` keeps `paid_stock=false`.
- [ ] `deployment-runbook.md:397-398` — the `b8b6ed7` sentence and "no deployment is
      scheduled before the Sep 3 capture" are both false. Rewrite to the deployed state and
      restate the refusal window from `release.sh:880` verbatim.
- [ ] `operational-evidence.md` — **append** a `## Collected 2026-09-02 — release of 4a632c0`
      record. Do not edit the 2026-08-30 record. Include: read-back release commit, venv,
      wheel sha, runtime-lock unchanged, all six timer states, the v3-06 NextElapse, the
      rollback tree, `preflight.sh 22` with the host's live `nginx -t` warn count, the
      `install-canary.sh` backup at `/var/backups/docket-canary/20260902T144452Z`, and the
      live admission limbs.
- [ ] Run `./.venv/Scripts/python -m pytest -q tests/test_claims_to_evidence.py
      tests/test_judge_facing_state.py` — both cross-check docs against artifacts and may pin
      wording. Fix wording to satisfy them; do not weaken a test.
- [ ] Show the full diff to the owner. **Commit only on explicit approval.** State that the
      commit puts `main` one doc-commit ahead of production, which the manifest already
      describes as the normal state.

## W2 — Finish the publication checklist (today; owner says yes, I run it)

Steps 11, 13 and 14 were never done after the visibility flip. Verified via `gh`:
`description` and `homepageUrl` are both `""`, `rulesets` is `[]`, `secret_scanning` and
`secret_scanning_push_protection` are both `disabled`.

- [ ] `gh repo edit Ridwannurudeen/docket --homepage https://docket.gudman.xyz/
      --description "<owner-supplied one line>"` (step 11).
- [ ] Create a `main` branch ruleset blocking force pushes and requiring the `test` and
      `package` checks (step 13). The visibility conversion disabled all push rulesets.
- [ ] Enable Secret Protection, secret scanning and push protection (step 14).
- [ ] Re-verify with `gh repo view --json visibility,defaultBranchRef,homepageUrl` and
      `gh api repos/Ridwannurudeen/docket/rulesets`.

## W3 — Land v3-06 (Sep 3; attended, unrepeatable)

The capture fires on its own. The follow-through is what needs a person. v3-06 is 5 planned
pairs, agent = deployed Yield Router, manual = a disclosed Codex-assisted baseline. It makes
**no human-versus-agent claim**, so it does **not** satisfy TermiX's eligibility gate — its
value is 5 fresh pairs with zero burned slots and a genuine chance of `not_refuted`.

- [ ] Before 11:50 UTC: confirm the timer is still armed and take no action that could
      disturb it. No deploy today.
- [ ] After **12:03:06 UTC**: runbook stage 2 — a one-time
      `scp -r root@75.119.153.252:/var/lib/docket/v3-capture/yield-v3-06 <staging>`, verify
      `capture['captured']`, `pools.sha256`, `token_list.sha256`, then a single `Move-Item`
      into `data/yield-v6-assisted-capture-20260903`. **First write. No rehearsal, no
      re-copy, never restart or edit the server capture.**
- [ ] Follow `docs/runbooks/yield-v3-06-assisted-run.md` stages 3→end: calibration sessions,
      input lock, manual (Codex baseline) primaries, agent primaries, both seats, import,
      mapping, report.
- [ ] **Do not run v3-05 or v3-07 seats on this day.** Seat B (`claude_cli.py:7`,
      `TIMEOUT_SECONDS = 300`) is the adapter that left v3-04 permanently
      `complete_unscored`. One family per day.

## W4 — SOLVENT trading record (Sep 3-5; mostly my work)

TermiX weights "High-stakes categories and track record" at 20% and asks trading agents for
"win rate, the window, and the risk taken". Docket publishes none today. SOLVENT's chain is
real evidence, but it is weaker than it first appears and the plan must say so.

Build it on the **v2 pattern**, which already exists: `docket/advantage/v2/corpus/`,
`specs/`, `runs/`, with `dataset_ref` + `dataset_sha256` + `fetched_at` + `method` +
`n_planned` + explicit denominators.

**Files:** `docket/advantage/v2/corpus/trading/solvent-receipts.json` (new),
`docket/advantage/v2/specs/` (new spec), `docket/advantage/v2/runs/06-solvent-record.json`
(new), plus the report/page wiring and tests.

- [ ] Freeze the corpus: fetch `https://solvent.gudman.xyz/receipts?limit=500` once, record
      the URL, fetch time, byte SHA-256, and the chain's own `prev_hash` linkage. Verify the
      hash chain end-to-end and publish whether it verifies.
- [ ] Register the method **before** computing: which receipts count, what an "executed
      trade" is, how `unresolved` is treated, and what will not be claimed.
- [ ] Compute and publish, each with its denominator:
      - execution reliability — `executed_now` 27 / 51 seals, `unresolved` 22, `failed` 1
      - the window — 2026-06-18 → 2026-06-29, 11 days, stated as a closed historical window
      - trade count and sizing from `intent_key`
      - on-chain coverage — 37/51 seals with `tx_hash`, **1/51** with
        `pre_trade_anchor_tx_hash`
      - regime-call distribution
- [ ] **The deposit problem, stated as a limit, not hidden.** `equity_usd` mixes funding with
      P&L; receipts carry no funding field. Either (a) reconstruct deposits from BSC transfer
      history for `0xE4fe23FB57dbb9AC2f685ea29B6b9A1409A0d359` and publish a
      deposit-adjusted return with its method, or (b) publish **no** return/win-rate figure
      and say exactly why. **Do not publish a naive return.** The raw series would read
      +2558%, which is a funding artifact.
- [ ] Treat the single `0.0` equity reading (2026-06-19T20:30:02, between two `45.85`
      readings) as a read failure, disclose it, and exclude it from any drawdown with a note.
- [ ] Tests: chain-linkage verification, every published figure's denominator, and a
      regression asserting no unadjusted return figure is emitted.
- [ ] Wire into `/advantage/v2.json` and the page, and add rows to
      `docs/submission/claims-checklist.md` and `termix.md` §3.

**Honest ceiling:** this yields an execution-reliability record over 11 days, and a
return/win-rate only if the deposit reconstruction lands. A 43% unresolved rate is an adverse
finding. Publishing it is consistent with the project's posture and is worth more than the
current zero — but it will not read as a strong trading track record, and the plan should not
pretend otherwise.

## W5 — v3-07 Range successor (Sep 5-8; attended, CONDITIONAL)

Fixes two things at once: a paired benchmark that *can* pass, and arms that were genuinely
hired and paid for rather than run on the free tier.

**Precedent:** v3-06 is a registered successor to v3-02, a locked family that failed its
primary. Its `registration_provenance` states the rules — git history is the registration
witness, and "the v3-02 ledger remains separate and unchanged."

**Start only if W3 lands clean and the owner wants it.** Do not start this if v3-06 ends
`complete_unscored`; a second seat failure in the same week is worse than not running.

- [ ] Write `docket/advantage/v3/specs/v3-07-range-doctor.json` as a **distinct** comparison,
      not a retry of v3-05: new cases from the committed enumerable frame, a human manual arm,
      and an agent arm that **sends `X-PAYMENT`** via the canary-authorized path
      (`routes.py:2205`) so each agent primary is a genuinely settled 0.50 USDT hire.
- [ ] Commit the spec **before** any capture — git history is the registration witness.
- [ ] Deploy (owner-gated, outside any capture window), arm a capture timer for a future
      registered time, capture, calibrate both seats, lock inputs.
- [ ] Run 3 manual primaries (20-min deadline each, no retry), then 3 agent primaries with
      the payment header, then export sessions and run both seats.
- [ ] Owner approval immediately before each 0.50 USDT settlement. 3 primaries = 1.5 USDT.
- [ ] Publish whatever it returns, including `refuted`.

**Feasibility, re-measured 2026-09-02 — much better than first stated.** A successor does
**not** need a new capture, a deploy, or an armed timer. The Range sources are already
committed and tracked: `sources/range-v5-enumerable-frame.json` (1,024 rows, archive-pinned
at block 117841891, `complete: true`) and `sources/range-v5-pool-truth.json` (the 29-pool
Explorer top-list captured 2026-08-26T12:10:02Z). Measured against them:

| Population | Count |
|---|---:|
| Frame rows | 1,024 |
| Rows with non-zero liquidity | 68 |
| …whose pool is in the captured top-list | 31 |
| …unused by v3-05 — **disjoint candidates** | **29** |

So the remaining work is: register a spec, calibrate, lock, run 6 slots and 2 seats. The
capture/deploy/timer risk is gone; the seat-B risk is not.

**But reuse costs integrity, and the spec must say so.** v3-05's guarantee was
register → capture at a *future* time → lock. A successor reusing already-committed sources
loses that: the frame and pool truth are public in the repo before registration, so it
cannot claim its inputs were unknown when the protocol was fixed. The manual arm's
one-case-at-a-time reveal still holds, but an operator could study the 29 candidates in
advance. Two honest routes — **owner's call, this is a methodology decision:**

- ~~(a) Reuse, and disclose the weakening.~~ Not chosen.
- **(b) CHOSEN by the owner 2026-09-02. Capture fresh pool truth at a future registered time.**
  The frame is block-pinned history, so foreknowledge buys nothing there; only pool economics
  need future capture. Preserves the register → capture → lock property v3-05 had.

**Route (b)'s real cost, mapped and verified: it needs a deploy**, because the capture runs on
the VPS from a unit the release installs. Five coordinated edits:

| # | File | Change |
|---|---|---|
| 1 | `deploy/systemd/` | new `.service` + `.timer`, modelled on the two existing capture units |
| 2 | `deploy/preflight.sh` | the `readonly -a UNIT_NAMES=(…)` array |
| 3 | `deploy/release.sh` | `UNIT_NAMES` (~498), `TIMER_NAMES` (~512), and a new `refuse_*_capture_window()` guard (~870-891) called in both places |
| 4 | `docs/deployment-runbook.md` | "all thirteen tracked unit" appears exactly twice → fifteen |
| 5 | `tests/test_release_scripts.py:375-391` | `assert len(expected) == 13` → 15, plus a refusal-window test |

That count assertion is a deliberate tripwire against silent unit drift — update it consciously,
never delete it.

**Ordering consequence of (b):** a fresh pool-truth capture changes which pools are covered, so
the eligible candidate set will differ from the 29 counted against the Aug-26 capture. **Case
selection therefore happens AFTER the capture** — register the derivation, then derive. That
ordering is the whole point of choosing (b).

**RESOLVED 2026-09-02 — and two of the "verified facts" above were wrong.**

1. **Frame reuse was impossible, not merely weaker.** `spec.py:1092-1106` derives the 1,024
   enumerable indices from `stage_one_protocol_hash`, and `spec.py:2031` validates every frame
   row against that derivation. A different hash is a different frame; the v5 frame could never
   validate against v3-07. The "29 disjoint candidates" table above is therefore moot, and
   route (a) never existed as an option. A fresh collection is mandatory.
2. **The harness did *not* already pay.** HEAD's orchestrator sent only `X-PAYMENT`
   (`orchestrator.py:486`); `routes.py:2197` derives `canary_authorized` from a separate
   `X-Docket-Canary` header, so on a `paid_stock=false` service the payment was silently
   ignored and the hire ran on the free allowance. A `--canary-header` flag was added; **a paid
   v3-07 agent primary needs both headers.**

**What was built (route b, option i):** a fresh frame pinned at **block 119531513**, hash
`0x4e18a190…`, `2026-09-02T11:59:59Z` — verified on-chain — chosen by a public rule (the
highest BSC block strictly before 2026-09-02T12:00:00Z) so no one can ask whether the block was
shopped. Pool truth registered for **2026-09-05 12:00 / 12:01 / 12:02 UTC**; timer
`docket-v3-range-v7-capture.timer` at `11:50:00 UTC`; release refusal `11:49:54Z`–`12:03:06Z`.
Frame-to-pool-truth gap is 3 days (v3-05's was 2). Prior-exposure exclusion of
`{1056809, 1653348, 5223058}` is enforced in `spec.py` and disclosed in the registration.

**The deploy surface was eight places, not five.** In addition to the five above:
`release.sh` ~1139 (the `/advantage/v3.json` smoke's expected family/state map — a release
**rolls back** without it), `scoring.FAMILY_PROTOCOLS` (salt `range-v7-blinding`), and
`spec.INPUT_VALIDATORS`.

**Blockers and hazards surfaced by the build:**
- `judge-start-here.md` still said "6 families"; the untracked ledger masks that locally but
  CI would have failed. **Fixed** — reproduced and re-tested in a clean worktree.
- **Sep 3 rebase hazard.** `release.sh`'s expected map and six state docs hard-code
  `v3-06: registered_waiting_for_inputs`. After W3 locks v3-06 that is false. Whoever lands
  the lock must update the same lines, or the Sep 4 deploy's smoke rolls back.
- The registration cites the untracked v3-05 ledger as operator-held evidence outside the
  tree, and says so. Committing the ledger instead would flip v3-05 to `running` in six
  docs, `release.sh`, and the hire-API message.
- The new 1,024-index draw may not fill all three strata; that cannot be known before the
  capture, and an empty stratum fails the lock with no substitute. Registered as such.

**Next, in order:** commit (git history is the only registration witness; stage 1 refuses to
start without it) → stage 1: collect the frame at block 119531513 from the host archive RPC,
read-only, first-write to `sources/range-v7-enumerable-frame.json` → deploy on Sep 4, outside
both windows → capture fires Sep 5 → copy, calibrate, lock → Sep 6 slots, Sep 7 seats, Sep 8
review.

**Mandatory exclusion either way:** token `5223058` must be excluded — the operator saw its
reveal during the interrupted v3-05 slot on 2026-08-30. Cleanest is to exclude all three
v3-05 tokens (`5223058`, `1056809`, `1653348`), leaving 29 candidates, and to disclose the
prior exposure in the registration.

## W6 — Paid stock (only after W5 completes)

All four limbs must hold. After W5, Range Doctor would hold three; `cold_canary` is the last.

- [ ] Confirm W5 produced a terminal paired benchmark, then flip
      `RANGE_ADMISSION.fresh_paired_benchmark` in `docket/hire/catalogue.py:236` with a
      comment citing the family and its result. **Owner decision** — the written definition
      permits a `refuted` benchmark, but it is the owner's call whether to sell on one.
- [ ] Enable `docket-canary.timer`. **This is a recurring wallet commitment:** 0.50 USDT per
      day, ~10 USDT through 2026-09-23, and one failed run closes paid stock for that day —
      a facilitator hiccup or RPC outage on the day a judge tries to hire means they still
      see `paid_stock: false`. Explicit owner approval, and monitor daily.
- [ ] Verify `paid_stock: true` on `/services` and that a real purchase completes end to end.

**Unverifiable assumption to carry:** opening paid stock is necessary but not sufficient for
TermiX's 30%. Their own marketplace runs USDC escrow with optimistic proof; whether a judge
can or will execute an x402 payment on BSC is not something this repo can establish.

## W7 — Submission (BLOCKING; owner only)

- [ ] **Owner supplies the portal URL.** It is recorded nowhere in the repo or in memory.
- [ ] Map the portal's fields onto `docs/submission/README.md`, `bnb.md`, `termix.md`,
      `pancakeswap.md`, `judge-start-here.md`, `demo-script.md` — all already written.
- [ ] Owner files it. **Never submit without explicit approval.**

Nothing else in this plan matters if Sep 9 passes unfiled.

## What this plan does not fix

- **v3-05 stays `refuted`-capable only.** The burned manual primary is permanent. W5 routes
  around it with a successor; it does not repair it.
- **The v1 arms stay free-tier.** v3-05's spec is locked and cannot be retrofitted with
  payment. Only W5's new family can carry paid arms.
- **The trading record stays short.** 11 days and 27 executed trades is what exists. No
  honest work makes it longer before Sep 9.
