# Docket — Synthesis & Roadmap v2 (2026-08-14)

**Supersedes `SYNTHESIS-AND-ROADMAP.md` (2026-08-12) as the operative plan.** That document is
preserved unedited; its Path A/B framing produced Stages 0–4 and is now history. Nothing in it
is rewritten.

Three independent assessments, reconciled:
- `CODEX-ASSESSMENT-2026-08-14.md` — Codex, `gpt-5.6-sol` @ xhigh, read-only, 272k tokens
- `FABLE-AUDIT-2026-08-14.md` — Fable 5, verification-first, 61 tool calls, 194k tokens
- `CLAUDE-ASSESSMENT-2026-08-14.md` — Claude, written before seeing either

Shared fact base: `2026-08-14-BRIEFING-V2.md` (sponsor rubrics verbatim, fetched live).

**Every load-bearing claim below was re-verified by Claude against the code or the live product
this session.** Verification notes are inline. Where a claim could not be checked, it says so.

---

## The one-paragraph truth

Docket is a genuinely well-engineered evidence product with a working cold hire path and a
human journey that now exists — a real reversal since the last audit. But **it is two
half-marketplaces that never touch**: 506 indexed on-chain agents that cannot be hired, and six
hireable services of which five have no on-chain identity. Against the three sponsors:
**TermiX first place is the most winnable and is being lost on presentation, not substance;
PancakeSwap is winnable and under-evidenced; BNB first place is not reachable by Sep 9 and
should not be chased at the cost of the other two.** The single most damaging fact found today
is that the flagship service, hired with the wallet from its own published evidence run, returns
an **empty position list** — 21 positions held, the default `limit` examines only 10, all 10 are
closed, and nothing is returned or explained.

> **This document was audited by Codex on 2026-08-14 after being written.** See
> `CODEX-AUDIT-OF-SYNTHESIS-2026-08-14.md`. Its rulings are folded in below and marked
> **[Codex audit]**. It also caught a factual error by Claude — the wallet cited in an earlier
> draft was the first 40 hex characters of a 64-hex `input_hash`, not an address. Corrected and
> re-verified against the live service.

---

## §1 — Verdicts, reconciled

| Track | Codex | Fable 5 | Claude | **Agreed** |
|---|---|---|---|---|
| TermiX 1st | Winnable, conditional | Winnable — strongest (~30–40% → ~50%+) | Most winnable | **Primary target.** |
| PancakeSwap | Winnable | Winnable, under-evidenced (~25% → ~35–40%) | Winnable, under-claimed | **Primary target.** |
| BNB $30k | **Not winnable**; shortlist attainable | Shortlist ~20–30%, win ~8–15% | Reachable, not favoured | **Shortlist-quality; do not chase first place.** |

All three assessors independently reached the same ordering. That convergence is the finding.

**The user's goal was to win all three. The honest answer is that two are winnable and the
third is not, on one builder in 26 days.** What makes this palatable: almost every item on the
critical path *also* serves BNB. Settled payment, freshness, human-readable results, on-chain
identity and clean packaging are BNB's Functionality and Data Quality criteria directly. The
**only** work that is BNB-exclusive is a **provider-onboarding platform** — letting a third
party list a service and get hired. That single item is the difference between shortlist and a
credible win attempt, and it is the one thing that would cannibalise TermiX and PancakeSwap.

**Decision deferred to ~Aug 24, deliberately:** do the shared work first, then decide on
provider onboarding with real information about remaining calendar. Do not decide it now.

---

## §2 — What both assessors found independently (highest confidence)

### 2.1 The identity seam — the marketplace does not join itself
*Codex: "serious eligibility ambiguity." Fable: "two half-marketplaces that never touch."
Claude flagged it pre-independently. Three for three.*

**Verified by Claude:** `GET /services/{id}` live — `range-doctor`, `grid-operator`,
`yield-router`, `health-guard`, `warden-scan` all return `agent_id: None`. Only
`solvent-signal` is bound (`56:0x8004…a432:136384`), and that agent is halted. Fable further
verified that none of the 506 indexed agents has any hire affordance (`app.js:1162-1224`).

Against BNB's hard gate — *"Agents surfaced on your marketplace must be live on BSC"* — the
four scored category slots are filled entirely by services with no BSC identity. **Close this
by registering, not by arguing.** ~1–2 days plus user-approved transactions and gas.

### 2.2 The Advantage Report v2 does not satisfy TermiX's gate — v1 does
*Codex named it as "the unnamed problem." Fable reached the same conclusion independently.*

**Verified by Claude** at `docket/advantage/v2/report.py:114`, in Docket's own words:

> "v1 … is the only place in this build where an agent arm is compared against a human one, and
> that comparison is n=1 by construction. v2 does not supersede it: repeated trials here are
> **agent-versus-null-baseline**, and no human arm was simulated."

TermiX requires *"3 real tasks run both ways: with an agent hired through your marketplace vs.
without."* **v1 is the eligibility artifact; v2 is armor around it.** Consequence: the Sep 1–5
re-run must produce **paired agent-vs-human arms**, and no harness for that exists in v2.

⚠ Also verified: v2's own `METHOD` discloses that only experiment 04 is git-provably
pre-registered; 01 and 03 entered history together with their completed runs. Honest, but it
means **the final report must be git-provably specified before either arm runs.**

### 2.3 Pricing — one cent is indefensible, and so is $70
Both assessors rejected the one-cent price and both rejected the design spec's "$21–100 judge's
band." See §4 for the resolved decision.

---

## §3 — What each assessor found alone (verified before adoption)

### From Codex

| Finding | Verified? |
|---|---|
| `pyproject.toml:23-37` omits `docket.agents.venus` and `docket.agents.yield_router`; both exist on disk. **A built wheel loses two of the four scored categories.** | ✅ Confirmed |
| `routes.py:288` resolves the snapshot **once at startup** by design. A refresh loop is invisible without dynamic promotion or app reload. | ✅ Confirmed |
| `ingest.py:66-84` breaks on `max_pages` or a non-advancing paginator, then still calls `finish_snapshot()`; `store.py:183` checks only `finished_at`/`sampled`, never `sampled == expected`. **A finished-but-partial sweep can be promoted.** Stage 0 fixed the *crashed* case, not the *truncated* case. | ✅ Confirmed |
| `index.html:53` claims "Every service … can show a recorded run behind it." Live: `grid-operator`, `yield-router`, `health-guard` all return `metrics=0 evidence=0`. **The homepage makes a false claim.** | ✅ Confirmed |
| `x402.py` verifier establishes no settlement, no replay protection, no asset-domain binding, no `validAfter` — all disclosed in its own docstring. `verified_unsettled` cannot clear TermiX's bar. | ✅ Confirmed |
| PancakeSwap hero figure: over **22 eligible pools**, quoting gross overstates the net fee rate by a **median 49.3%**; gross error exceeds rounding error on **22 of 22**. Dataset SHA-pinned. | ✅ Confirmed |

### From Fable 5

| Finding | Verified? |
|---|---|
| **`/advantage/v2` has no human path.** The served v1 page links `/advantage` and `/advantage.json` only — zero `v2` strings. The homepage's sole reference is `advantage/v2.json`, the machine endpoint. **TermiX's 30% criterion is scored against a page a judge cannot find.** | ✅ Confirmed |
| **The flagship's evidence run is irreproducible.** Cold `POST /hire/range-doctor` with the v1 task-01 wallet `0x451871A1753903FB8fdd64a6B838E95aB8D5B80f` returns HTTP 200 in 9.1s with `positions_held: 21`, `positions_examined: 10` (the default `limit`), `closed_skipped: 10`, and **`positions: []`** — an empty result with no guidance to raise `limit`. The Aug-8 recorded run saw 14 held / 14 examined / 13 closed and returned one position. | ✅ Confirmed exactly as Fable reported |
| `yield-router`'s input schema is `['pool','position_size_usd','switching_cost_usd','horizon_days']` — **no `wallet`**, so it cannot draft on the hire path. | ✅ Confirmed |
| 792 tests pass (36.7s); live == repo; 8 cold hires across all six services all returned HTTP 200 in 1.6–23s with receipts. | ✅ Matches Claude's own run (792, 40.7s) |
| **Nobody has read the Terms of Participation to confirm one entry can take all three tracks.** Registration is overdue. | ⚠ **Unverified — user-only, and foundational** |

**Fable's discipline note, recorded:** it raised and then withdrew a mojibake alarm that turned
out to be its own cp1252 decode; the site is clean UTF-8. It also could not verify health-guard
against a live borrower from its vantage. Both stated rather than buried.

---

## §4 — The two genuine disagreements, resolved

### 4.1 Pricing

- **Codex:** flat **0.50 $U** for every completed hire; one prefilled free sample; settlement required.
- **Fable:** **measurement-derived** — each service priced against its own recorded manual-arm cost, stated on the card: range-doctor 2 $U, grid/yield/health 1 $U, warden-scan 0.5 $U, solvent 0.1 $U.
- **Claude (original):** two-tier, free preview + $20–100 band. **Withdrawn** — both assessors showed the band is wrong for seconds-long calls.

**RESOLVED — flat `0.50 $U`. [Codex audit] rejected the measurement-derived ladder, and it was
right.** Claude's draft adopted Fable's ladder; the audit dismantled it on facts:

- It is **not actually measurement-derived**. Grid, Yield and Health have **no recorded manual
  arms and no service metrics at all** (`registry.py:73`, `:107`, `:148`) — there is nothing to
  derive their price from.
- The two services that *do* have recorded manual arms report a direct cash cost of **$0**
  (`01-liquidity.json:123-127`, `03-security.json:54-58`). A $0 manual arm cannot yield a price.
- Docket's own harness **explicitly refuses** to convert elapsed time into money without an
  hourly-rate assumption (`harness.py:9-13`). The ladder does that implicitly and inconsistently.
- SOLVENT at 0.1 $U sits **below** the verified $0.50 market floor, contradicting the very
  constraint the ladder was claimed to satisfy.

The flat rate's advantage, which Claude missed: it is **externally derived** — from TermiX's
observed minimum — uniform, auditable, and impossible to mistake for fabricated precision. A
ladder with invented derivations would be the one place Docket asserted a number it could not show.

**Decision: `0.50 $U` for every completed personalized hire through Sep 23. One separate,
prefilled free sample. Remove the halted SOLVENT from paid stock unless U2 produces a genuinely
resumed service** — a stale historical read is research evidence, not paid inventory.

**Also adopted:** retire the design spec's "$21–100 judge's band" **in writing**. TermiX's $70
median buys multi-day professional work; a $70 30-second call fails "Value of the services" in
the opposite direction.

### 4.2 How much BNB to chase

- **Codex:** concede first place; do not build provider onboarding.
- **Fable:** shortlist plausible; the human journey now exists; staleness and the identity gap are what remain.

**RESOLVED — lock BNB to shortlist scope NOW; no Aug-24 revisit. [Codex audit] rejected the
deferral**, and the argument holds: the shared work improves the shortlist but **does not make
provider onboarding any smaller**. A credible supply path needs provider manifests, ownership
verification, schema/evidence validation, deploy-free publication, and an independent provider
actually hired — none of which arrives via settlement, freshness or identity work. If BNB first
place is not credible with 26 days, it does not become credible because the calendar reaches
Aug 24.

**Reopen only on a material capacity change — never on a date.** Fable's correction still
stands: BNB is not a write-off, and the shared work lifts the shortlist substantially.

---

## §5 — The roadmap

Calendar-anchored. 26 days. Aug 31 paid-hire gate · Sep 1–5 report · Sep 6 freeze · Sep 9 submit.

### Tier 0 — user-only, blocks everything, must move THIS WEEK

| # | Action | Why it cannot wait |
|---|---|---|
| U1 | **Hackathon registration + read Terms of Participation** | Overdue since Aug 10. **Confirm one entry can take all three tracks** — nobody has verified this and it is foundational to the whole plan. |
| U2 | **Decide SOLVENT funding** by **Aug 20** (drop-dead) | Determines whether it can carry a trading record or is retired to research evidence. |
| U3 | **Approve the paid-hire proof** (small, ~0.5 $U) | Aug 31 hard gate sits in front of it. |
| U4 | **Approve four ERC-8004 registrations** + gas | Closes the BSC-identity gate; needs lead time. |
| U5 | **Fund a Docket demo wallet** (live LP + small Venus borrow) | Fixes the empty-output problem and makes Sep re-runs reproducible through judging. |
| U6 | **Decide the Grid mainnet proof** by **Aug 23** | If no, no volume claim appears anywhere. |
| U7 | **Flip repo public** by **Aug 28** · 8004scan Pro form | Hard eligibility gate. |

### Tier 1 — integrity and release defects (Aug 14–17, no approval needed)

1. `pyproject.toml` — package `docket.agents.venus` + `docket.agents.yield_router`; add CI that builds a wheel, installs it **outside** the checkout, and smoke-tests all four category hires.
2. `index.html:53` — remove the false "every service can show a recorded run" claim.
3. **Make v2 reachable — [Codex audit] specifies how.** Keep **one** top-level `/advantage`
   destination in the nav; add an **above-fold, labelled link from the v1 page to v2** that states
   the relationship: *v1 is the paired agent-vs-human report TermiX's gate asks for; v2 is the
   methodological armor around it.* Do **not** create competing top-level report destinations and
   do **not** call v2 "the" TermiX artifact. Verified today: only `advantage-v2.html` carries a v2
   nav link, and `tests/test_web_categories.py:243` asserts "the same navigation" while checking
   only four hrefs — widen it so the relationship is enforced, not just present.
4. `store.py` / `ingest.py::_sweep` — a closed `stop_reason`; never promote a bounded or non-advancing sweep; promotion predicate requires true completeness.
5. **[Codex audit] UI correctness, dropped from Claude's draft:** Grid's `filled` array is rendered
   and submitted as text, and large integers pass through precision-losing `Number.parseInt`
   (`app.js:392-403`, `:517-529`; `catalogue.py:186`, `:424-428`). Restore the real array control
   and BigInt-safe handling.
6. **[Codex audit] Start the v3 report specification NOW, in parallel** — not conceptually at
   Tier 6. The whole point of an Aug-14 kickoff is that **git proves the spec predates every run**.

### Tier 2 — the refresh loop, done safely (Aug 14–18)

New `docket/refresh.py::refresh_once` (ingest → enrich → probe → validate → promote), VPS timer,
and **dynamic promotion or app reload** — without it the loop is invisible (`routes.py:288`).
Tests in `tests/test_refresh.py`. Registry refresh ≥ every 6h; owned-service canaries more often.
*Codex's correction to Claude adopted: BNB names freshness, not a minimum window — but start now,
because every delayed day is unrecoverable operational evidence.*

### Tier 3 — real settlement (Aug 15–20) — **Aug 20 kill gate**

`x402.py` asset-domain binding + both validity bounds; new `docket/hire/settlement.py` (settle
exactly once, return proof); persistent payment/hire records with unique nonce; paid work runs
only after settlement; replay idempotent or refused. Price per §4.1. Separate "Try the sample"
from "Pay and hire" in the UI.

**Gate: if a controlled preflight cannot settle once, reject replay, and bind payment to
output by Aug 20, TermiX first place becomes unlikely.** Re-verify the current Binance/x402
facilitator before writing code. Keep $U (the EIP-3009 asset the verifier understands).

**[Codex audit] The exit gate must also require a NON-EMPTY, human-readable result.** Settling
payment for empty raw JSON does not prove value to TermiX — and given the Range Doctor finding,
that is not a hypothetical failure mode.

### Tier 4 — make the demo survive a cold judge (Aug 18–23)

**This is the fix for the single most damaging finding.** A Docket-owned demo wallet with a live
LP position and a small Venus borrow, wired as "try the worked example" on every category
service. Three of four category services currently require a wallet a zero-knowledge judge does
not have, and the flagship returns empty on its own evidence wallet.

Plus: result presenters per service — finding, observed block/time, economic consequence, next
step, primary limitation, expandable raw JSON. Today `app.js:540` dumps raw JSON into `<pre>`.

**[Codex audit] corrections to Claude's draft:**
- **Yield is underspecified.** Adding `wallet` alone is not enough — drafting also needs catalogue
  wiring for the reader, token pair, amount and cap (`catalogue.py:285-299`;
  `agents/yield_router/router.py:405-468`).
- **Range Doctor's empty result is a `limit` defect, not just a data one.** 21 held, 10 examined,
  10 closed, nothing returned and nothing explained. Fix the default, and say what was skipped.
- **Registering identities does not join the two marketplaces.** A service page can link to an
  indexed identity, but an agent detail page exposes no service and no hire action
  (`routes.py:641-671`; `app.js:1162-1224`). **Add the reverse agent → service/hire link** or the
  seam stays open.

### Tier 5 — evidence parity and identity (Aug 18–27)

Measured figures for grid/yield/health (currently `metrics=0 evidence=0`); bind the four
identities after U4; SOLVENT's win-rate/window/risk per U2 (the data exists in task-02
artifacts — Fable estimates half a day).

### Tier 6 — the real TermiX report (spec by Aug 27, run Sep 1–5)

New `docket/advantage/v3/` with **paired agent-vs-human arms** — the thing v2 does not have.
Three tasks: Range Doctor vs manual LP diagnosis · Yield Router vs manual pool comparison ·
Warden vs manual security review. Warden satisfies the required high-stakes category (the
sponsor says trading, stock, **or** security). **Lock every spec, input, rubric and stopping
rule in git before either arm runs.** v1 and v2 preserved as linked appendices, neither rewritten.

### Tier 7 — public package (Aug 24–28)

README, LICENSE, AI_USAGE.md, architecture, runbook, threat model, claims-to-evidence table.
Secret/history review before the flip. Clean clone → wheel install → tests → four smokes.

### Tier 8 — conditional Grid proof lane (Aug 21–25) — **[Codex audit] restored**

U6 asks for a decision but Claude's draft scheduled no implementation if the answer is yes. If
approved by Aug 23: re-verify the current Altana SDK, add only the minimal session-key submitter
`GridOperator` requires (its armed class refuses construction without one, `operator.py:23-27`),
rehearse on testnet, then one tiny mainnet proof — registered session → agreed simulation → one
confirmed swap → cap decrement → revoke → post-revoke refusal. **If not approved, no volume claim
appears anywhere in the submission.**

### Then: Aug 27–31 cold rehearsal · Sep 1–5 report · Sep 6 freeze · Sep 8–9 submit on approval.

**[Codex audit] Operations do not stop at submission.** Persistent service-availability history
plus uptime and freshness monitoring must run **through Sep 23**, not merely to Sep 9 — the
submission must stay functional and publicly accessible for the whole judging window, which is a
stated eligibility condition.

---

## §6 — What NOT to build

Adopted from Codex, unchanged: no Agent Studio/Bedrock/`bag` work (BNB says don't); no ERC-8183
browser flow (its 7-day window doesn't solve Aug 31); no Altana bounty UI; no V3 automatic range
reset; no Yield Router liquidity migration; no Venus executor; no autonomous grid keeper; no
second chain; no trust score; **no $20–70 price on seconds-long calls**; no cosmetic redesign
before payment/results/freshness/packaging; **no rewrite or removal of v1/v2 evidence**; and no
provider-onboarding platform in the primary plan.

Added: **do not manufacture a 20-day "trading record" to fill a rubric field.**

---

## §7 — The thing that decides this

Everything above is execution. One thing is not:

**Nobody has read the Terms of Participation to confirm that a single entry can take all three
tracks.** BNB states "one entry per team" and says partner tracks are "judged independently…
check that track's page separately." The plan assumes one submission enters all three. If that
assumption is wrong, the strategy changes shape entirely — and registration is already four days
overdue.

That is the first thing to do, before any code.

---

*Superseded document: `SYNTHESIS-AND-ROADMAP.md` (2026-08-12) — preserved, not edited.*
