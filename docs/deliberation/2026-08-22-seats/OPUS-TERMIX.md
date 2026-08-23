# Docket vs the TermiX partner-track rubric — judge simulation and gap audit

Audited 2026-08-22. Repo `<repo>`, branch
`docs/deliberation-round2`, HEAD `fdf02cf`, read-only. Live site `https://docket.gudman.xyz`
serving `534af82` (6 commits behind HEAD; none of the 6 touch the web layer or the hire path —
`git log --oneline 534af82..HEAD --stat` shows only v3 orchestrator/calibration_driver and docs).

Rubric read verbatim from `docs/deliberation/2026-08-14-BRIEFING-V2.md` §1.2. Bar read from
`docs/deliberation/CODEX-WIN-SPEC-2026-08-14.md` §1.

---

## (a) Score per criterion

**Total: 48 / 100.** Podium-plausible on honesty and craft; not first place, because the one
thing the track is built around — *paying* for an agent and getting a measured advantage —
cannot happen on the live site today.

| Criterion | Weight | Score | One-line justification |
|---|---|---|---|
| Value of the services | 30% | **15** | The Range Doctor result a judge gets is genuinely decision-grade and arrives in ~5s — but it is free, because **no service is admitted to paid stock**, an `X-PAYMENT` header is silently ignored, and every card reads "not yet for sale". "A price and speed that beat the alternative" is a promise; the price is unreachable. |
| Proven agent advantage | 30% | **13** | The eligibility gate is **met** by v1 (3 paired agent-vs-human tasks, time/cost/quality, full outputs, one security task) — but n=1 per task, the security task is a recorded **loss**, the trading task's own notes say the agent arm did not answer the question, v1 quotes a `$0.01` price the catalogue no longer charges, and v3 has **zero runs**. |
| High-stakes categories & track record | 20% | **7** | The security category qualifies, but Warden's attached record is 1-of-4 hostile vectors (v1) and 14-of-31 labelled attacks (v2); there is **no precision figure anywhere** and no held-out result. No trading record exists at all: SOLVENT is stale since 2026-06-28 and labelled research, Grid is a preview with zero routed volume. |
| Marketplace quality | 20% | **13** | Find/compare/hire all work uncoached from the homepage, the comparison table renders, and the result presenter is excellent — but there is **no example input**, so a judge without a BSC LP position hits a soft dead end; the comparison table's cells are 200-word paragraphs; and four nav/footer links dump raw JSON. |

### What the judge's act actually returned (verified live, 2026-08-22 13:00–13:26Z)

`POST /hire/range-doctor` with `{"wallet":"0xe55816904796341bf8535e25f6c8b647927fc946"}` →
**HTTP 200 in ~38s (curl) / 3.5–5.2s (warm)**, block 117428314. Checked against Codex's
"exact hire TermiX must receive" (CODEX-WIN-SPEC §1, the 8-element list). The HTML presenter at
`/service?id=range-doctor` renders them as literally numbered sections 1–8:

| # | Element | Verdict | Evidence |
|---|---|---|---|
| 1 | Decision | ✅ | "Position 7141050 is below its range and currently earns no pool fees." |
| 2 | Verifiable facts | ✅ | pair USDT/WBNB, id 7141050, tick -65442, bounds [-65200,-63193), block 117428314, obs time |
| 3 | Economic consequence | ⚠️ **partial** | gross 103.05% / net 69.04% / 49.26% relative / 34.01pp all present; **every dollar field is `null`** — `declared_position_value_usd`, `annual_gross_usd`, `annual_net_usd`, `annual_overstatement_usd`. Codex demanded "dollar effect at the position's declared value". |
| 4 | Conditional actions | ✅ | wait vs recenter, each with its named assumption and cost, PancakeSwap deep link — but `estimated_recenter_cost_usd` and `cost_only_break_even_days` are `null` |
| 5 | Coverage | ✅ | "all 1 of this wallet's position NFTs were read… 0 are closed", `scan_complete: true`. Never returns bare `[]`. |
| 6 | Measured value | ❌ **missing** | `"benchmark_unavailable_reason": "The preregistered v3 paired report has not run, so no paired manual time, quality result, or v3 report link exists yet."` |
| 7 | Proof | ❌ **missing the payment half** | input_hash + output_hash + delivery time present; `payment.status: "free_tier"`; settlement tx and nonce both render "unavailable — This candidate is not admitted to paid stock, so no payment occurred." |
| 8 | Primary limitation | ✅ | one prominent sentence, raw JSON expandable below |

**Elements 3, 6 and 7 collapse to two root causes: the canary's controlled-LP/settlement config
is absent on the box, and v3 has never run.** That is the spine of the ranking in (b).

Error paths are clean, not demo-grade: empty body → `422 missing_field` with the fix named;
no body → `400 invalid_json` with an example. A wallet with no position
(`0xd8dA…96045`) → 200 with `"This wallet holds no PancakeSwap v3 position NFT to diagnose."`
plus coverage and a stated limitation — it does **not** silently return `[]`. That closes one of
Codex's named track-losing failures.

**What still reads "demo/unfinished" to a judge:** every service card carries a status word from
{candidate, preview, preview, preview, research, beta} and the line **"not yet for sale —
cold_canary, fresh_paired_benchmark, true_settlement"**. Four of six service *names* literally
contain the word "Preview". Section 6 of the flagship result says the report backing its value
claim has not run. A judge reads that as a marketplace that has not opened.

---

## (b) Gaps, ranked by points-per-day-of-work

### 1. Nothing is for sale. A paying TermiX judge cannot pay. — ~8–10 pts

- **file:line** — `docket/hire/catalogue.py:117` `RANGE_ADMISSION = PaidStockAdmission(False, False, True, False)`; same shape at `:120` (Warden) and `:124` (Grid/Yield/Health). `:104-113` `passes` requires **all four** limbs. `docket/api/routes.py:1102` gates the entire paid branch on `payment_header_present and (paid_stock or canary_authorized)`.
- **What a judge sees** — live `GET /hire` returns `paid_stock: false` for all 6 services and
  `admission: {fresh_paired_benchmark: false, cold_canary: false, decision_grade_presenter: true, true_settlement: false}`.
  Sending `X-PAYMENT: <anything>` returns **HTTP 200 with a free result** and
  `receipt.payment = {"status":"not_for_sale","stock_status":"candidate","authorization_used":false}`.
  No 402 is ever issued. `/canary` shows the last run (id 8, 2026-08-22T04:21:32Z) verdict
  **`not_yet_exercised`**, with legs `controlled_live_lp` and `exact_0_50_settlement` both
  `{"reason":"controlled_live_lp_absent","configured":false}`.
- **The fix**, in dependency order:
  1. Set `DOCKET_CANARY_WALLET=0xe558…c946`, `DOCKET_CANARY_TOKEN_ID=7141050`,
     `DOCKET_CANARY_POSITION_VALUE_USD`, `DOCKET_CANARY_RECENTER_COST_USD`,
     `DOCKET_CANARY_PRIVATE_KEY_FILE` — all commented out at
     `deploy/docket-canary.conf.example:14-18`. The wallet demonstrably holds 7141050 right now,
     so this leg is config-only. **Hours.**
  2. Stand up / point at an x402 v2 facilitator that settles $U on BSC and set
     `DOCKET_FACILITATOR_URL`, `DOCKET_PAY_TO`, `DOCKET_ENABLE_SETTLEMENT=1`
     (`docket/api/routes.py:370-377`). **Unknown — see (c) unverified.** Then flip
     `true_settlement=True` in `catalogue.py`.
  3. `fresh_paired_benchmark` needs v3-01 (gap #2). **This is the hard coupling: paid stock
     cannot open until the v3 Range family has run.**
- **Note** — limbs 1, 3 and 4 are **hardcoded literals in source**, not computed. Only
  `cold_canary` is resolved at runtime (`docket/hire/admission.py:33-40`). Opening paid stock is
  a code change + redeploy, not a config toggle.
- **Exit test** — `curl -X POST .../hire/range-doctor -H 'X-PAYMENT: bad'` returns **402** with
  the x402 challenge body; a valid authorization returns `receipt.payment.status == "settled"`
  with a `transaction_id`; the same authorization replayed returns **409 `authorization_replay`**.

### 2. v3 has zero runs, so "Proven advantage" rests entirely on v1. — ~6–8 pts

- **file:line** — all three specs carry `"inputs_sha256": ""` and
  `"inputs_ref": "docket/advantage/v3/inputs/0N-….json"`; **`docket/advantage/v3/inputs/` does
  not exist** (`find docket/advantage/v3 -type d` → only `sources/` and `specs/`). Live
  `/advantage/v3.json` → `{"n_families":3,"states":{"registered_waiting_for_inputs":3}}`.
- **What a judge sees** — a beautifully registered protocol with nothing in it, and section 6 of
  every paid result saying so out loud.
- **What each family needs to lock and run** (read from the three specs):

| Family | n | Inputs it needs | Blocker | Feasible by Sep 5? |
|---|---|---|---|---|
| **v3-03-warden-security** | 12 payloads × 2 arms = 24 attempts | Already authored: `sources/warden-heldout-cases.json` — **12 cases, 7 hostile / 5 benign, 3 critical, every one carrying `expected_verdict`**; 8-case calibration key at `sources/warden-calibration-set.json` (promoted out of the test file in `fdf02cf`) | Owner must publish the answer key, write `inputs/03-security-heldout.json`, lock its SHA, then run **2 real evaluator seats** through `calibration_driver.py` (floor: 7 of 8 correct) before any timed arm | **YES — this is the only one that is close.** Inputs exist; the work is a lock + calibration + 24 attempts. |
| **v3-02-yield-router** | 5 cases × 2 arms | One frozen top-pools + token-list response pair captured at an exact registered moment | **The Aug-21 12:00Z capture did not produce a lock** (`inputs_sha256` still `""`). The spec's own `case_selection` says "otherwise input lock fails and this protocol **must be recommitted** before another time is used." | **YES, but only via recommit.** Precedent exists: all three specs already carry a `protocol_correction` with `status: "corrected_before_input_lock"` superseding a prior `stage_one_protocol_hash`. Register a new moment, run `capture.py`, lock. ~1–2 days. |
| **v3-01-range-doctor** | 5 positions × 2 arms | A frozen manifest of candidate positions | **`case_selection.chosen_by` requires reading *every* ERC-721 Transfer log from block 0 to the observation block for PancakeSwap NPM `0x46A1…4364` and MasterChefV3 `0x556B…Cd59e`, then enumerating each distinct recipient at that block, and refuses partial results** ("If any log or enumeration range cannot complete, input lock fails"). No such sampler exists in the tree. Also excludes token 7141050 as party-controlled. | **NO, not as registered.** This is an archive-node full-history log sweep. Either build it (multi-day, needs an archive node) or recommit `case_selection` to a narrower, still-preregistered frame. |

- **Manual arm cost, all three** — every family requires a human arm run once per case: 5, 5 and
  12 manual cases respectively. That is real operator hours and it is not automatable.
- **Exit test** — `GET /advantage/v3.json` shows at least one family in `complete_unscored` or
  `not_refuted`, with every case record and every failure retained, and
  `measured_value.paired_manual_seconds` non-null in a live `/hire/range-doctor` response.

### 3. No dollar figures without caller-supplied inputs. — ~2–3 pts, ~0.5 day

- **file:line** — live response `economic_consequence.unavailable_reason`: *"declared_position_value_usd was not supplied for this exact token_id; Docket has no trusted first-party source for this NFT's USD value"*.
- **What a judge sees** — Codex's element 3 half-answered. Percentages, no money.
- **The fix** — the *canary/example* path already has env slots for both
  (`DOCKET_CANARY_POSITION_VALUE_USD`, `DOCKET_CANARY_RECENTER_COST_USD`). Ship a one-click
  "Try the verified example" that prefills `token_id=7141050` plus both declared values, so the
  default judge run produces dollars. Do **not** invent a price feed — the current abstention is
  correct and is a strength.
- **Exit test** — the example run returns non-null `annual_overstatement_usd` and
  `cost_only_break_even_days`.

### 4. No example input on the run form → soft dead end. — ~2–3 pts, ~0.5 day

- **file:line** — `docket/api/web/service.html` / `docket/api/web/app.js` — grep for
  `placeholder|example|prefill` on the hire form finds nothing; the only "Worked example" in
  app.js (`:1772`) belongs to the *registry agent* page, not the hire form.
- **What a judge sees** — a required `WALLET` field and **ten** optional fields including
  `POOL_SNAPSHOT` ("exact top-pools HTTP response bytes as base64 with URL, observation time and
  bare SHA-256"), `TOKEN_LIST_SNAPSHOT`, `SOURCE_REFS` (an array control with Add/Remove) and
  `POSITION_MANAGER`. TermiX almost certainly has no BSC LP position; their own wallet returns
  "This wallet holds no PancakeSwap v3 position NFT to diagnose". They have nothing to type.
- **The fix** — a prefilled "Try the verified example" button (Codex specified exactly this) and
  collapse the seven reproducibility fields behind an "Advanced / reproducibility" disclosure.
- **Exit test** — a cold user reaches a populated 8-section result in ≤2 clicks with zero typing.

### 5. Comparison table is unreadable. — ~1–2 pts, ~0.5 day

- **file:line** — `docket/hire/comparison.py:91` puts `service.what_you_get` verbatim into the
  `job` cell. Rendered, the Yield Router row's job cell is a ~250-word paragraph.
- **What a judge sees** — the right columns (service, price, typically, for sale?, measured
  against a person) buried under six paragraphs. Codex asked for "job, price, measured time
  saved, quality/sample size, freshness, limitation, evidence" — a *scannable* row.
- **The fix** — add a short `job_summary` (one clause) to `Service` and use it in the table;
  keep the full text on the service page. Add the missing `freshness` column.
- **Exit test** — every comparison row fits on one screen; the whole table is scannable in <30s.

### 6. Raw JSON dead ends off the nav. — ~1 pt, ~0.5 day

- **What a judge sees** — the footer links `/services`, `/categories`, `/stats`, `/agents`
  (`docket/api/web/index.html:281-288`) and every one returns a raw JSON dump in a browser.
  Worse, the *guessable* URL `https://docket.gudman.xyz/services/range-doctor` renders raw JSON —
  the HTML page lives at `/service?id=range-doctor`. `/compare` is JSON-only and appears in no
  nav (the table is fetched by JS into the homepage, which is fine, but the URL is a trap).
- **The fix** — content-negotiate on `Accept: text/html` for `/services`, `/stats`, `/agents`,
  `/compare`, and 302 `/services/{id}` → `/service?id={id}`. Label the remaining JSON links
  "(JSON)".
- **Exit test** — no link reachable from a rendered page returns `application/json` to a browser
  without saying so first.

### 7. Warden has no precision figure and no held-out result. — ~3–4 pts but gated on #2

- **file:line** — `docket/advantage/v2/runs/03-security-corpus.json` records `14 of 31` labelled
  attacks flagged; `docket/advantage/experiments/03-security.json` notes read verbatim:
  **"THE AGENT LOST THIS ONE ON SUBSTANCE. It was 28 times faster and it returned one of the four
  vectors."** and *"Three of the four survive verbatim in the sanitized_payload it handed back."*
- **What a judge sees** — an agent in the highest-weighted category whose own evidence page says
  it missed a credential-exfiltration instruction and passed it through as "sanitized". The
  honesty is admirable and it still scores badly against "a real record".
- **The fix** — run v3-03 (gap #2); Codex's internal ship gate is ≥90% held-out recall AND ≥90%
  precision AND zero critical vector surviving sanitization AND ≥99% successful scans. **On the
  current 14/31 evidence, Warden is unlikely to clear 90% recall.** Decide now whether to
  remediate the detector before the run or accept staying `beta`.
- **Exit test** — `/advantage/v3.json` family `v3-03-warden-security` in a terminal state with
  both arms' recall and precision published, and the service page shows them.

### 8. Registry snapshot is 14 days old. — ~1 pt, ~0.5 day

- **What a judge sees** — `/canary` leg `snapshot_age_surface` observed
  `snapshot_age_seconds: 1247429` (≈14.4 days), `captured_at: 2026-08-07T17:51:02Z`. Hits BNB's
  "real-time data" harder than TermiX, but a TermiX judge browsing `/stats` still sees stale.
- **Fix / exit test** — one verified complete sweep before Sep 9; `snapshot_age_seconds` under
  24h during Sep 9–23.

### Not a gap — worth protecting

The paid code path, though unreachable, is the strongest thing in the repo and answers three of
Codex's four track-losing failures **in code**: durable nonce binding
(`routes.py:1146-1188`), replay refused with distinct terminal states `settled` /
`settlement_unknown` / `failed_no_charge` / `settlement_failed` (`:1161-1183`), no-charge on an
empty or non-human-readable result (`:1264-1272`), de-admission checked *after* the run and
before settlement (`:1275-1289`), one settle attempt with no auto-retry (`:1297-1310`), and
transaction/network/payer binding verified before the receipt is issued (`:1317-1334`).
**`verified_unsettled` — the status Codex named as a track-losing failure — appears nowhere in
`docket/` or `tests/`; `grep -rn "verified_unsettled" docket/ tests/` returns nothing, and it
survives only in historical planning and deliberation docs.** Do not refactor this.

---

## (c) Verified vs unverified

### Verified this session — command or file

| Claim | How |
|---|---|
| Live hire returns a full 8-section result for 7141050 | `curl -X POST https://docket.gudman.xyz/hire/range-doctor -d '{"wallet":"0xe558…c946"}'` → 200, block 117428314, decision "below its range" |
| Empty body → 422; no body → 400; both with actionable messages | same endpoint, `-d '{}'` and no `-d` |
| A no-position wallet gets an explained null, not `[]` | same endpoint with `0xd8dA…96045` → `positions_held: 0`, coverage sentence, limitation |
| **No service is in paid stock** | `GET /hire` → `paid_stock: false` × 6, all admission dicts show `true_settlement: false` |
| **An `X-PAYMENT` header is ignored, no 402 ever** | `curl … -H 'X-PAYMENT: eyJhIjoxfQ=='` → 200, `receipt.payment.status = "not_for_sale"` |
| Canary ran but its LP + settlement legs are unconfigured | `GET /canary` → run id 8 finished 2026-08-22T04:21:32Z, verdict `not_yet_exercised`, `controlled_live_lp_absent`, `configured: false` |
| Snapshot age 1,247,429s | `/canary` leg `snapshot_age_surface` |
| Admission limbs 1/3/4 are source literals; only `cold_canary` is computed | `docket/hire/catalogue.py:96-124`, `docket/hire/admission.py:33-40` |
| **`docket/hire/settlement.py` does not exist** | `ls docket/hire/` → `__init__.py admission.py catalogue.py comparison.py receipts.py x402.py`. Settlement lives in `routes.py:1102-1340` + `x402.py`. |
| Price served is `0.50 $U` / `500000000000000000` atomic of `0xcE24439F2D9C6a2289F741120FE202248B666666` | live `/services`; `catalogue.py:45-47` |
| v1 has 3 paired agent-vs-human tasks incl. security; agent lost the security one | `docket/advantage/experiments/0{1,2,3}.json`, notes quoted above |
| v1 quotes cost `0.01 $U` while the catalogue charges `0.50 $U` | `01-liquidity.json` `agent_arm.cost.amount = "0.01"` vs live `/services` |
| v3: 3 families, all `registered_waiting_for_inputs`, zero runs, no `inputs/` dir | `GET /advantage/v3.json`; `find docket/advantage/v3 -type d` |
| All three v3 specs have empty `inputs_sha256` | parsed each spec JSON |
| Warden held-out set is authored: 12 cases, 7 hostile / 5 benign, 3 critical | parsed `sources/warden-heldout-cases.json` |
| 8-case calibration key exists | `sources/warden-calibration-set.json` |
| v3-01 requires a from-block-0 Transfer-log sweep of two contracts | `v3-01-range-doctor.json` → `case_selection.chosen_by` |
| Corrections before input lock are a registered mechanism | all three specs' `protocol_correction.status = "corrected_before_input_lock"` |
| Warden v2 corpus scan endpoint and dataset | `03-security-corpus.json`: `POST https://warden.gudman.xyz/api/demo/scan`, dataset sha256 `11e9094f…` |
| Homepage renders 4 job categories + a real comparison table | browser render of `https://docket.gudman.xyz/` |
| Service HTML page is `/service?id=…`; `/services/{id}` returns raw JSON in a browser | browser navigation to both |
| The run form exposes 11 fields with no example prefill | browser DOM enumeration of `input`/`button` on `/service?id=range-doctor` |
| Live web assets are byte-identical to the repo's | `diff` of fetched `/` against `docket/api/web/index.html` → identical |
| Zero commits between the deployed `534af82` and HEAD touch the hire path or web layer | `git log --oneline 534af82..HEAD --stat` |

### Unverified / believed — do not cite as fact

- **Whether any x402 v2 facilitator that settles $U on BSC exists or will accept Docket.** `x402.py`'s own docstring says "No concrete facilitator URL is built in… Fixture responses prove Docket's state machine; they do not prove a particular facilitator accepts $U, has funds, submitted the authorization on chain". **This is the single largest unknown in the whole plan** — if no facilitator exists, `true_settlement` can never be true and gap #1 is unclosable at any price.
- **Whether prod has `DOCKET_ENABLE_SETTLEMENT` / `DOCKET_PAY_TO` set.** Behaviour cannot distinguish: `routes.py:1102` gates on `paid_stock` *before* reaching the settlement-config check, and `paid_stock` is false. Requires reading the box's systemd env.
- **Whether the payment table survives a process restart** — `store.reserve_payment` etc. are SQLite-backed by declaration; not exercised across a restart here.
- **That the Aug-21 12:00Z Yield capture exited 2 specifically.** I verified the *outcome* (no lock, `inputs_sha256` empty) and that `capture.py:443,451` returns 2 on `CaptureRefused` and 3 on a non-captured result — I did not read the box's journal.
- **CI covers `aaba01a`, not HEAD** — `docs/operational-evidence.md` Entry 12 states run `31943515697` was green on `aaba01a`; the 5 commits after it have not been checked by any runner. Not re-verified.
- **The 1210-test suite was not run in this audit** (read-only remit, and a full run touches network).
- **Whether Warden can clear a 90% held-out recall gate.** Believed unlikely on 14/31 + 1/4 priors; unproven until v3-03 runs.
- **Whether two real evaluator seats can pass the 8-case calibration floor (7 of 8).** `AUDIT-BACKLOG.md` §16 states verbatim: **"Zero real seat runs still. This has been driven only by a synthetic callable."**
- **The orchestrator has never run against a real endpoint.** `AUDIT-BACKLOG.md` §15: *"No orchestrator has ever run against a real endpoint. This is machinery with no paired run through it."* Its `main()` agent path and `--payment-header` plumbing are untested end to end.
- **Judge weighting inside each criterion** is my inference; TermiX publishes weights but not sub-rubrics.

---

## Bottom line for the owner

Docket's evidence integrity is genuinely first-place material and its Range Doctor result is the
best single artifact in the build. It loses this track on one structural fact: **the marketplace
is not open for business.** TermiX's rubric is built around "TermiX will hire from your
marketplace themselves" and 30% is scored on whether the agents are "worth paying for" — and
today nobody can pay. Two of the four admission limbs are hardcoded `False`; one of those
(`fresh_paired_benchmark`) is gated on a v3 Range family whose input lock requires a
full-history log sweep that does not exist.

**The one decision that matters before Sep 5:** either recommit `v3-01`'s `case_selection` to a
frame that can actually be locked in the time available, or accept that Range never enters paid
stock and re-plan the paid hero around **Warden** — whose 12-case held-out set and 8-case
calibration key are already authored and are the only v3 inputs that exist. Everything else in
this report is worth 1–3 points; this one is worth 15.
