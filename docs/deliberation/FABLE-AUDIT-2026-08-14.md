# Fable 5 — Independent Verification Audit (2026-08-14)

Second-round audit for the three-track question. Everything load-bearing below was checked
this session against the repo at `main` (`0fb9c77`, working tree clean apart from the three
untracked deliberation files) and the live product at https://docket.gudman.xyz. I audit the
sponsors' criteria as quoted verbatim in `2026-08-14-BRIEFING-V2.md` §1; I did not re-fetch
the sponsor pages myself.

## Method note — what I ran, and what I could not check

**Ran this session:**

- Full test suite: `./.venv/Scripts/python -m pytest` → **792 passed, 2 warnings, 36.70s**.
  The briefing's count is exact.
- **Ten cold POSTs against the live product, no auth, no wallet**, as a judge would:
  eight hires covering all six services (plus a defaults re-run and a named-pool run)
  and two error-path probes.
  Every response, latency and byte count is in §2 below.
- Live/repo parity: `sha256` of served `/static/app.js` and `/static/style.css` ==
  repo bytes (both MATCH). Live `/stats`: snapshot 3, `captured_at 2026-08-07T17:51:02Z` —
  7 days stale at audit time. `/escrow` 200 with full terms. `/` content-negotiates:
  curl gets JSON, a browser Accept header gets the category-first landing page.
- Advantage artifacts as served: `/advantage.json` (37,601 B), `/advantage/v2.json`
  (301,261 B), both HTML pages, plus the repo-side `docket/advantage/v2/runs/*` and the
  scoring path in `docket/marketplace/registry.py`.
- Code read: `registry.py` in full, `app.js` in full, `routes.py` (root/hire/allowance/
  CORS/snapshot resolution), `/hire` catalogue schemas as served.
- Grep sweeps: no scheduler/refresh loop anywhere in `docket/` or `.github/workflows/`
  (the only hits for "schedule|refresh" are a prose string in `marketplace/models.py:102`
  and a comment in `store.py:206`).

**Could not check, stated plainly:**

- **Health-guard against a live Venus borrower.** Three RPC routes failed from this
  machine mid-session (local DNS refused `bsc-dataseed*`/`defibit`/`llamarpc`;
  `publicnode` answered once, then 403'd, then stopped resolving). The known fixture
  account was already empty at my Stage-3 audit (F12). Note the flip side, which is
  itself a finding: **a judge cannot find a distressed Venus account either** — the
  "Protect a loan" category has no demonstrable non-empty case for anyone who is not
  already in trouble on Venus.
- The paid x402 path end-to-end — user-gated, per briefing §2.5; not re-litigated.
- Sponsor texts beyond §1's quotes; TermiX's live marketplace census (taken as given).
- Whether the Terms of Participation allow one submission to enter main + both partner
  tracks simultaneously. I assumed yes throughout; **nobody has verified it and only the
  user can** (registration is already overdue).
- I deliberately did **not** open `CLAUDE-ASSESSMENT-2026-08-14.md` or
  `CODEX-ASSESSMENT-2026-08-14.md` (both present, untracked). Independence is the point.

**A false alarm I caught myself, recorded as discipline:** mojibake ("â€”") in my first
read of the served JSON was my own `open()` defaulting to cp1252 on Windows. The served
bytes are clean UTF-8 (`b'\xe2\x80\x94' in raw` → True; no mojibake byte sequence
present). The site is not at fault. One wrong bug report costs more than ten right ones
earn; this one died in-session.

---

## Executive verdict table

| Track | Verdict | Confidence path |
|---|---|---|
| **TermiX 1st ($6,000)** | **Winnable — strongest of the three.** The eligibility gate is satisfied today by v1 (verified §5); the evidence culture matches the judge's. But the 30% "Value" criterion is currently answered by a one-cent price, an empty-result flagship hire, and a v2 report no human nav reaches. Fix those three and this is the favourite. | ~30–40% as-is → **~50%+** with §8 items 2–6 |
| **PancakeSwap (1,000 CAKE)** | **Winnable, under-evidenced.** Range Doctor + Yield Router + Grid Preview are genuine LP/trader benefit, and "no code path to move funds" answers their only absolute structurally. Zero routed volume remains the gap; one bounded, recorded grid session (user-gated) or a pool-gap analysis artifact closes it. | ~25% as-is → ~35–40% with one measured proof |
| **BNB main ($30,000 + adoption)** | **Shortlist plausible; win unlikely. Not winnable in the "four actors" sense by Sep 9 — and it does not have to be.** The human journey now exists (verified cold, §3) — this is no longer the forfeit my first audit found. What remains: staleness (33 days at judging), three of four category cards with zero observed metrics, four advisors where the rubric's verbs describe actors, an unanswered adoption narrative, and an eligibility ambiguity (§6) that must be closed, not argued. | shortlist ~20–30%, win ~8–15% with the full §8 order landed |

All three remain simultaneously pursuable: nothing in §8 trades one track against another
— the overlap is nearly total. The binding constraints are the calendar and the seven
user-only blockers, not track conflict. (One caveat: whether one submission may enter all
three tracks is a Terms question nobody has read yet — see Method.)

---

## §2 — The cold hires, exactly as served

All `POST https://docket.gudman.xyz/hire/{id}`, `Content-Type: application/json`, no auth,
no account, no wallet. Every response HTTP 200 with a hash-bound receipt,
`payment.status: "free_tier"`.

| Service | Input | Time | Size | What a paying stranger gets |
|---|---|---|---|---|
| `range-doctor` | wallet `0x4518…B80f`, limit 5 | **22.9s** | 1,130 B | **`positions: []`** — 21 held, 5 examined, 5 closed-skipped |
| `range-doctor` | same wallet, default limit | 6.9s | 1,132 B | **`positions: []`** — 21 held, 10 examined, **10 closed-skipped** |
| `grid-operator` | wallet only, defaults | 6.9s | 13,739 B | Real: 6 levels, per-level live router quote, min-out, calldata hash, deadline, gas ceiling, slippage bound, block stamp |
| `yield-router` | `{}` | 5.5s | 51,594 B | Real but inert: 23 candidates, net-vs-gross stated, **`net_fee_apr_delta: 0.0`** (baseline defaults to the set's own first row), `actions: []` |
| `yield-router` | named pool + size/cost/horizon | **1.6s** | 52,474 B | **Genuinely good**: current pool named, per-candidate delta and break-even, within-horizon labelled, exclusions reasoned |
| `health-guard` | wallet `0x4518…B80f` | 3.2s | 4,761 B | Honest emptiness: `status: "no_position"`, full read provenance, cross-check `exactly_equal: true` on zeros |
| `solvent-signal` | `{}` | 3.4s | 1,999 B | The June-29 halted payload, `degraded: true`, `top_momentum: []`, `fear_greed: null` — dated, disclosed, unchanged |
| `warden-scan` | injection payload | 3.1s | 1,296 B | **Convincing**: verdict SANITIZE, 2 threat classes, per-layer checks, attack probability 0.9972, 1.8s upstream latency |
| error paths | bad wallet / unknown service | 2.2s / — | — | 422 `invalid_field` with honest message; 404 `service_not_found` pointing at `GET /hire`. Clean. |

**The finding the table understates — the flagship's evidence run is irreproducible.**
`0x4518…B80f` is not a wallet I picked: it is **the exact wallet the recorded Aug-8
advantage run used** (`docket/advantage/experiments/01-liquidity.json`, address field),
the run every one of range-doctor's three published metrics is transcribed from
(`registry.py:178-215`). On Aug 8 that run read 14 positions and produced the diagnosis
the card advertises. Today the same wallet returns an empty positions array on both the
default and an explicit limit — the open position has moved outside the newest-10 slice
(21 held now vs 14 then) or closed. So: **the recorded evidence behind the flagship
category service cannot be reproduced by hiring the service with its own recorded
input.** The response does announce the truncation (`positions_held: 21`,
`positions_examined: 10`) — the honesty machinery works — but nothing tells the reader
*to raise `limit`*, and the human page renders the empty result as raw JSON with no
guidance (`app.js:538-540`).

**Would the outputs convince a paying stranger?** grid-operator, yield-router-with-a-pool
and warden-scan: yes — dense, checkable, priced work. health-guard: yes *if* the judge
has a Venus position; no judge does. range-doctor: **the most likely cold outcome is an
empty array after 7–23 seconds**, and that is the category BNB lists first and the
service TermiX will meet first. solvent-signal: a byte-identical six-week-old JSON —
honest, and not worth a cent to anyone but an auditor of provenance.

---

## §3 — BNB Functionality, walked literally

"Land, find an agent by category, understand what it does, activate it, with minimal
friction… zero Agent Studio knowledge… without hitting a dead end."

What works, verified cold in a browser-shaped request:

- **Land**: `/` with a browser Accept serves the category-first landing — "Hire an agent
  for the job you have", four job panels painted from `/categories` + `/services`
  (`app.js:339-382`), evidence below the fold, not instead of the shop front. This is a
  real reversal of my first audit's central finding, and it is deployed (static hashes
  match repo).
- **Find by category**: four panels, one service each, uncategorised stock separated with
  a stated reason (`registry.py:55-58`).
- **Understand**: the service page carries what-you-get, price, typical seconds,
  limitations, identity, evidence links (`app.js:440-503`).
- **Activate**: the form exists, posts same-origin, renders result + receipt
  (`app.js:565-603`). Six-for-six cold hires succeeded.

The dead ends that remain, named:

1. **The required-input wall.** `range-doctor`, `grid-operator`, `health-guard` all
   require a 0x wallet (`/hire` input_schema, `required: true`). A judge with zero Agent
   Studio knowledge has no BSC LP wallet and no Venus loan. There is no example input,
   no "try this wallet" pre-fill, no demo path anywhere in `app.js` (the form renders
   schema defaults only, `app.js:392-404`). What such a judge sees after typing their own
   or a random address: an empty diagnosis (§2), `no_position`, or a grid for a wallet
   that means nothing to them. **Three of four category services have an empty modal
   outcome for exactly the person the criterion describes.** `yield-router` is the
   exception — it runs on `{}` — and it is the page to learn from.
2. **The result is a raw JSON dump.** `paintOutcome` renders
   `JSON.stringify(answer.result, null, 2)` into a `<pre>` (`app.js:540`). For
   grid-operator that is 13 KB of atomic-unit integers. "Doesn't make them think too
   hard about it" this is not. The receipt panel below it is excellent; the result panel
   above it is the machine's view handed to a human.
3. **The staleness banner is self-inflicted at judging.** The landing's evidence section
   prints "captured 1 week ago" today via `relativeTime` (`app.js:241-247`); on Sep 9 it
   prints "captured 4 weeks ago" under a criterion whose first word is "real-time".
   Verified: no refresh loop exists (grep, Method), and `create_app` resolves
   `snapshot_id` once at startup (`routes.py:288-295` — "Resolved once here rather than
   per request"), so the fix is a sweep loop **plus** either process restart per sweep or
   a re-resolve.
4. **`/advantage/v2` is unreachable by any human path.** The primary nav on every page
   links `/advantage` (v1). The served v1 page contains **zero** occurrences of the
   string "v2" (grep over the fetched HTML). v2 links only to itself
   (`advantage-v2.html:40`); discovery is via `llms.txt` or the root JSON — machine
   docs. A TermiX judge who clicks "Advantage report" meets the weaker artifact and has
   no route to the stronger one.

---

## §4 — Agent Diversity, tested against BNB's verbs

BNB's table: *manages/resets* (Rebalancing), *places and manages* (Grid), *routes*
(Yield), *protects* (Health). What each service actually does, from code and live output:

| Category | Verb asked | What is served | Distance |
|---|---|---|---|
| Rebalancing | manages, resets | Read-only diagnosis; conditional next steps naming beliefs and costs; nothing signed (`doctor` via catalogue) | Advisor. And its one recorded run no longer reproduces (§2) |
| Grid | places, manages | Full action records per level — quote, min-out, calldata hash, deadline, gas ceiling — **preview only, structurally**; the mainnet runbook's first line: "NOTHING IN THIS DOCUMENT HAS BEEN EXECUTED" | The closest to an actor: the whole mechanism exists unarmed |
| Yield | routes | APR comparison + break-evens. **The hire path cannot even draft a move: `wallet` is not in yield-router's input schema** (verified against `/hire` as served), so `actions` is always `[]` and `submitted: false` on every hire | Furthest from its verb |
| Health | protects | Reads Venus verbatim, derives ratio with method inline, drafts repay/supply-collateral **only when Venus itself reports shortfall** — cannot execute | Advisor that drafts; the drafting is invisible to any judge (no reachable shortfall account) |

Claude's claim 4 is not over-read; it is, if anything, understated on Yield. But the
conclusion "build four actors" is wrong for 26 days. The honest, winnable shape is:
**one real actor** (grid — the runbook exists, one bounded session, user-gated),
**drafted actions surfaced everywhere they exist** (health-guard already drafts;
yield-router should accept a wallet and draft the one swap leg it already knows how to
build — the code exists at `router.py`, it is simply not wired into the hire schema),
and the preview/act distinction sold as the safety feature PancakeSwap's brief demands
rather than apologised for. Also fix the stale internal docstrings that still say the
shelves are empty (`registry.py:4-6`, `registry.py:411-413` — "three of the four
categories return it") before a diligence reader greps the repo.

## §5 — Data Quality and the Advantage Reports, against what is served

**Service-card data.** `grid-operator`, `health-guard`, `yield-router` carry **zero
metrics** — their cards say "No recorded run stands behind this service yet"
(`registry.py:73, 107, 148`). `range-doctor` carries three figures from **one** run that
no longer reproduces (§2). Only `warden-scan` carries a distribution (14/31 with three
named nulls, computed at import from the committed corpus so card and report cannot
diverge — `registry.py:335-363`, the best pattern in the codebase). Against "a genuinely
informed call on which agent to hire": a judge comparing the four category services has
observed evidence on exactly one of them, and it is the one whose evidence is stale.
`solvent-signal` still publishes **no win rate, no window, no risk** — the three numbers
TermiX names for trading agents — while both exist in the task-02 artifacts.

**TermiX's eligibility gate — satisfied today, by v1.** Verified as served: 3 tasks, both
arms each, `seconds` per arm (43.06 vs 528.31; 1.84 vs 221.74; 2.62 vs 74.21), cost per
arm, full outputs attached with hashes, and both a trading task (02) and a security task
(03). The gate is passed. The published loss (03: agent named 1 of 4 vectors) still sits
where a reader meets it first.

**v2 as served (`/advantage/v2.json`), audited:**

- **03-security-corpus is the real thing**: 47 labelled payloads × 3 passes, 9 failed
  scans counted as failures not misses, recall 14/31 against three *computed* nulls
  (flag-nothing / flag-everything with its 31/47 precision / keyword-match 12/31), and
  provenance honestly `self_attested` with post-run re-registrations disclosed. No
  headline here is a single observation dressed as a distribution.
- **01-liquidity-arithmetic**: distributions over 22 pools (median 1.27pp vs 0.0009pp,
  margin stated), but provenance `self_attested` with `spec_precedes_run: false` — spec
  and run entered git together. Disclosed in-band. A hostile reader will still discount
  it, and they will be right to; it is the weakest of the three as proof-of-advantage.
- **04-grid-replay is a refuted claim, published**: 0 of 5 buy levels fired, the
  falsifier tripped, and the headline itself says the venue substitution (Binance prices
  vs a PancakeSwap plan) "is not evidence about the venue the plan trades." Publishing
  it is integrity; **counting it toward "3+ real tasks" for TermiX would be a mistake**
  — as an advantage demonstration it is a null result.
- Net: **v2 alone does not satisfy TermiX's gate wording** ("run both ways… time, cost
  and output quality" — v2's arms are nulls, not the manual alternative, and one of its
  three experiments refuted itself). v1 satisfies the gate; v2 is the anti-p-hacking
  armor on top. They are one story — and they are currently two pages with no link
  between them (§3.4). Merge the narrative or at minimum cross-link, and say explicitly
  which artifact answers the gate.

**The report/live consistency check a TermiX judge will run:** hire range-doctor with
the report's own wallet, get `[]`, open the card that says "14 of 14 position NFTs
read." Nothing anywhere is false — every figure is dated and windowed — but the *first
experience of the evidence is a contradiction between the record and the button*. The
Sep 1–5 re-runs must use inputs that will still produce non-empty output during Sep 9–23
judging, which means **inputs Docket controls** (see §8 item 3).

## §6 — The thing nobody has named

**Docket is two half-marketplaces that never touch, and the seam sits exactly under
BNB's eligibility sentence.**

- The browse plane indexes 247,146 registered agents, samples 506, probes their
  endpoints — and **not one of them can be hired through Docket**. The agent detail page
  has no hire affordance of any kind (`app.js:1162-1224`).
- The hire plane serves six services — and **five of the six have no ERC-8004 identity**
  (`agent_id=None`; only solvent-signal binds #136384, `registry.py:246`, and the served
  snapshot doesn't even hold that one). The identity strings on the cards say it
  outright: "No BSC identity bound yet… no on-chain record of it to read."

Two consequences, one per judge:

1. **Eligibility risk, BNB's own hard gate**: "Agents surfaced on your marketplace must
   be live on BSC." Docket's *hireable* stock is six off-chain services reading BSC. I
   state this as a **risk to close, not a verdict of ineligibility** — the fact (5 of 6
   `agent_id: None`) is verified; the rubric reading is mine. But it is not a reading to
   gamble $30,000 on when closing it costs a day of ops: register Docket's services
   under ERC-8004 on BSC with declared endpoints, then let the next sweep index them —
   at which point the marketplace's own listings become its best-evidenced agents, the
   probe layer shows *its own* endpoints answering, and the browse and hire planes meet
   for the first time. This was item 5 of my first audit; it is still undone and it has
   quietly become the highest-stakes cheap item on the board.
2. **The adoption question (Claude's claim 6) is this same seam, seen from the other
   side.** BNB is buying a discoverability layer for *other people's* agents. Today
   Docket demonstrates discoverability of dead endpoints and hireability of only itself.
   The honest bridge narrative exists — "registration says nothing about what an agent
   does; Docket is where an agent's claims get probed, and Docket's own listings are the
   first to submit to that" — but only if Docket's own agents are actually in the
   registry taking the same probes.

## §7 — Pricing: the concrete recommendation

The design spec's "price in the judge's band ($21–$100)" is **wrong for this product
class** and should be explicitly retired. TermiX's median $70 buys a 1–5 *day* human-ish
deliverable; Docket sells 2–30 *second* bounded reads. A $70 API call fails the "Value"
criterion in the opposite direction — it is worse than the alternative, and Docket's own
advantage report proves it (the manual arm of task 01 cost ~9 minutes; at any sane rate
that is single-digit dollars, not $70).

**Recommendation — measurement-derived pricing, committed, not optional:**

- Price each service against its **own recorded manual-arm cost**, stated on the card:
  range-doctor **2 $U** (~$2; manual arm 528s), grid-operator **1 $U**, yield-router
  **1 $U**, health-guard **1 $U**, warden-scan **0.5 $U** (manual 74s), solvent-signal
  **0.1 $U** flat as a historical record.
- Put the derivation sentence on every card: *"Priced against the measured cost of doing
  this without the agent — the measurement is attached."* No competitor will have
  pricing that cites its own evidence; for this jury that sentence IS the product.
- **Keep the free tier exactly as is** (20/hour, `routes.py:119`), relabelled "trial
  allowance" — it is why the judge's first hire is frictionless, and it is why "TermiX
  will hire from your marketplace themselves" succeeds on contact.
- The Sep 1–5 report re-runs must record the **new** prices in their cost fields, or the
  cards and the report will disagree about a number for the first time.

One cent survives nowhere: on a criterion literally named *Value of the services*, 0.01 $U
reads as "demo", and a $70 sticker reads as "delusion". $0.50–$2, derived from the
attached measurement, reads as "priced like it knows what it replaces."

## §8 — Ranked build order (points-per-effort, 26 days, one builder)

User-only items are flagged; nothing below re-recommends §2.2's shipped work — items 3
and 5 are gaps *in* the shipped pages, not re-dos.

| # | Item | Effort | Why this rank |
|---|---|---|---|
| 1 | **Housekeeping gate** — register (overdue), read Terms (incl. the three-tracks-one-entry question), repo public, README, LICENSE, AI_USAGE **(user-gated)** | hours | Fatal if missed; zero build. "Top 3 shortlisted publicly" also makes the README a Phase-2 artifact, not paperwork |
| 2 | **Refresh loop + serve the newest complete snapshot** (sweep scheduler; either restart-per-sweep or re-resolve `snapshot_id` — it is pinned at `routes.py:288-295`) | 1–2 days | Converts the one criterion whose first word is "real-time"; must run for weeks before judging to be a credible claim, so it is *calendar-critical now* |
| 3 | **Demo-input rail on the shipped hire pages**: a Docket-controlled demo wallet holding (a) one live Pancake v3 position and (b) one small real Venus borrow **(funding user-gated, ~tens of $)**; "Try the worked example" pre-fill per service; an in-response note when every examined position was closed ("raise limit"); render key result fields as prose/table above the raw JSON (`app.js:540`) | 2–3 days | Kills the empty-modal-outcome (§2, §3.1) for BNB *and* the TermiX first-hire experience at once; also makes the Sep re-run inputs reproducible through judging — the demo wallet is what the report re-runs against |
| 4 | **ERC-8004-register Docket's own services on BSC**, declared endpoints; re-sweep so they index **(registration tx user-gated)** | 1–2 days | Closes the §6 eligibility risk and joins the two half-marketplaces; the probe layer starts proving Docket's own listings answer |
| 5 | **One advantage surface**: nav → one report page, v1 (the gate artifact) + v2 (the armor) cross-linked and labelled as such | 0.5 day | TermiX's 30% is currently scored against a page judges cannot find (§3.4) |
| 6 | **SOLVENT win rate / window / risk on the card**, with sample size and halt date | 0.5 day | TermiX names these three; the data exists in task-02 artifacts; pure yield |
| 7 | **Pricing per §7** + re-run cost fields | 1 day | 30% criterion, designed answer |
| 8 | **Paid x402 hire proven end-to-end** on the new prices **(user-gated, Aug 31 spec gate)** | 1 day | "A stranger completes a paid hire" is the briefing's own gate; unproven today |
| 9 | **Yield-router accepts a wallet on the hire path and drafts its one swap leg** (schema + catalogue wiring; drafting code exists) | 1 day | Cheapest verb-distance closer on the board (§4); makes "routes" at least draft |
| 10 | **Grid mainnet proof — one bounded session, real fills, published as v2 experiment 05 with nulls (user-gated: session key + funds)** | 2–3 days + approvals | The single build that moves all three at once: BNB gets its one actor, PancakeSwap gets routed volume, TermiX gets a live trading record with window and risk. Do it exactly once, capped, and stop |
| 11 | **Adoption/README narrative** ("Docket probes what Agent Studio ships"; growth framing per my first audit §4) + 90-second journey video **(voice user-gated)** | 1–2 days | Phase-2 survivability is already the moat; Phase-1 optics and the public shortlist need this |
| 12 | Stale-prose sweep: `registry.py:4-6`, `:411-413`, and a grep for other pre-Stage-3 inventory sentences | hours | The repo goes public; diligence readers grep |

Cut order if the calendar collapses: 11's video, then 10 (grid proof), then 9. Never cut
1–5: 1 is eligibility, 2–5 are where the three juries actually land.

## §9 — Claude's seven claims, engaged one by one

1. **"Data Quality / real-time is the highest-leverage pure-build gap."** **Agree**, with
   two sharpenings: the snapshot is pinned at startup (`routes.py:288-295`), so the loop
   alone is not enough — the app must serve the newest complete snapshot; and the
   calendar makes this item 2, not item 5: a "real-time" claim needs weeks of uptime
   history before Sep 9, so its cost grows every idle day.
2. **"Pricing is a live risk and the fix is not simply raising the price."** **Agree on
   the risk, disagree that it lacks a designed answer.** §7 is the answer: price against
   the measured manual-arm cost, on the card, at $0.5–2 per hire, free trial tier kept.
   The design spec's $21–$100 band is wrong for per-call services and should be retired
   in writing so it stops steering.
3. **"SOLVENT is the only place we are silent on something a sponsor named."** **Agree,
   and it is cheaper than claimed** — the win/window/risk numbers exist in the task-02
   artifacts; half a day (§8 item 6). But do not oversell: presented honestly they come
   with a halt date, which TermiX's "the window" wording actually accommodates.
4. **"Four advisors where the rubric describes four actors."** **Agree it is real, not
   verb over-reading — and it is worse than stated on Yield** (the hire path cannot
   draft at all; `wallet` is absent from the input schema, verified live). The response
   is not four actors: one real actor (grid, §8.10), drafts surfaced everywhere
   (§8.9, health-guard already drafts), and the preview/act boundary marketed as the
   safety property. See §4.
5. **"PancakeSwap winnable and under-claimed."** **Agree.** The structural
   no-key answer to their only absolute is the strongest form available, and the
   net-vs-gross correction is the kind of detail their team recognises. The gap is one
   *measured* benefit record; the grid proof or a recorded before/after LP experiment
   supplies it. Zero volume routed remains true today.
6. **"The adoption question has never been answered."** **Agree, and name the reason:**
   the browse and hire planes never touch (§6). The adoption narrative cannot be written
   convincingly until Docket's own agents are in the registry it indexes. Register
   first, then the sentence writes itself.
7. **"Housekeeping is a submission-blocking risk carried too long."** **Agree; add two
   items to its list**: the Terms question (can one entry take all three tracks — nobody
   has read the document), and the fact that "top 3 shortlisted **publicly**" makes the
   README/video Phase-2 assets, so "housekeeping" undersells what the public repo is for.

**The §3 question "what single build most raises probability across all three?"** — the
grid mainnet proof (§8.10), *provided* items 2–5 land first; without them it decorates a
product whose front door still hands judges empty JSON.

**"What are we doing wrong that nobody has named?"** — §6. And one more, smaller: the
project's own evidence discipline stops at the door of its examples. The recorded runs
used a third-party wallet that drifted (§2); the fixture Venus account emptied (Stage-3
F12); the demo the judges will touch was never made judge-shaped. Evidence that rots is
this project's one native failure mode, and the §8.3 demo wallet is the fix because it
is the first input Docket *owns*.

---

*Written read-only: no repo file other than this one was created or modified; no
transaction sent, no funds moved, no deploy touched. Hires were free-tier HTTP only
(8 charged of the 20/hour allowance; the two error-path probes are un-charged by design,
`routes.py:879`).*
