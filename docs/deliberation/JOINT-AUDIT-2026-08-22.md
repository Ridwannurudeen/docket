# Docket — Joint Audit, Claude + Codex (2026-08-22)

**18 days to the Sep 9 submission. Judging Sep 9–23. This is the reconciled verdict of seven
seats, and the plan the owner asked for: what to build, change, cut and reframe so Docket
fits what BNB, TermiX and PancakeSwap each published they want.**

## 0. How this audit was run, and what it is worth

| Seat | What it did | Budget |
|---|---|---|
| **Codex** `gpt-5.6-sol` @ **xhigh** — auditor of record | Full tree audit against its own win spec and the verbatim rubrics | 350,349 tokens |
| **Codex** `gpt-5.6-sol` @ medium | Same brief, independent run | 158,055 tokens |
| **Claude** (Fable 5, this session) | VPS access, live-site probes, git/CI state, on-chain verification of competitor claims, reconciliation | — |
| Opus 5 — TermiX judge simulation | Hired every service live; scored the 30/30/20/20 rubric | 166k tokens, 58 tool calls |
| Opus 5 — PancakeSwap judge simulation | Live hire of the controlled position; decision-impact artifact; field research | 208k, 72 calls |
| Opus 5 — BNB main-track + field scan | Cold human journey; 16-query GitHub sweep of entrants; on-chain competitor check | 262k, 109 calls |
| Opus 5 — security/correctness review | The 66 unaudited commits on `main..HEAD`; history hygiene; ops fragility | 221k, 88 calls |

**Codex sandbox disclosure.** Codex's `-s read-only` and `workspace-write` sandboxes both failed
before every command today (`windows sandbox: helper_unknown_error: apply deny-read ACLs`);
Codex refused to fabricate and returned nothing. Both Codex runs above were re-run under
`--sandbox danger-full-access` with an explicit no-write instruction. The working tree was
hashed before and after each run (`git status --porcelain` + SHA-1 over `git ls-files`):
**identical both times, HEAD `fdf02cf` unchanged**, and the exec logs contain only read
commands plus two `python -c "…report()"` calls. The seat reports are saved verbatim in
`docs/deliberation/2026-08-22-seats/`.

**Every number in §1–§3 was verified by Claude this session** (command or `file:line` given)
unless marked *[seat]*, meaning an agent or Codex verified it and Claude did not re-run it.

Baseline state, verified: HEAD `fdf02cf` (Aug 17) on `docs/deliberation-round2`, in sync with
origin; **no commit in five days**; `main` (the default branch) is `0fb9c77` (Aug 11), **66
commits stale, no README on it**; repo **private**. Production `docket.gudman.xyz` runs
`534af82`, 6 commits behind HEAD (none of the six touch the hire path or web layer *[seat]*).
`./.venv/Scripts/python.exe -m pytest -q` → **1209 passed, 1 failed** (51s); the failure is the
date-armed capture test (§3 F9). Hackathon page re-fetched today: unchanged since Aug 14 —
Phase 2 still `[REDACTED]`, no weights published.

---

## 1. Bottom line

| Track | Codex xhigh | Codex medium | Claude seats | **Joint verdict** |
|---|---|---|---|---|
| **TermiX 1st** ($6k) | Red, salvageable | Not competitive; recoverable | 48/100 as a judge would score it today | **Behind the plan of record. Recoverable only if a real paid hire lands this week.** |
| **PancakeSwap** (1,000 CAKE) | Amber; best recoverable path | Strongest recoverable track | Winnable; under-evidenced; field looks under-contested | **Most winnable of the three. The decisive artifact (owner decision on the live position) can start today.** |
| **BNB shortlist / single $30k winner** | Red; not credible without sacrificing the other two | Risks failing eligibility | Shortlist ~12% as-is, ~25% with identities, ~40% with four fixes | **Eligibility is failed on the plain reading today. Clear the gate in a capped lane; do not chase first place.** (The $30,000 goes to ONE winner plus adoption — it is not a pool to share; see §11.) |

Every seat that ranked across tracks — both Codex runs and Claude — reached the same ordering
independently: **PancakeSwap > TermiX > BNB**; the four single-track Opus seats each scored one
track and their scores are consistent with it. That convergence is the finding. It matches the owner's own Aug-14 priority ruling (TermiX and
PancakeSwap primary, BNB secondary), so no strategy change is recommended — only execution.

### The five facts that decide it

1. **Nobody can pay.** Every service serves `paid_stock: false`; an `X-PAYMENT` header returns a
   free result with `payment.status: "not_for_sale"` and **no 402 is ever issued** *[seat]*.
   Three of the four admission limbs are **hardcoded literals** —
   `docket/hire/catalogue.py:117` `RANGE_ADMISSION = PaidStockAdmission(False, False, True, False)`
   — and `fresh_paired_benchmark` is defined as the v3 Range family having run. TermiX scores 30%
   on "TermiX will hire from your marketplace and evaluate the results", and its own win-spec gate
   (settlement by Aug 20) passed with settlement never attempted. **By the plan's own rule, TermiX
   first place is now "unlikely" unless this lands in days, not weeks.**
2. **The registered Aug 21 12:00Z Yield capture failed and wrote nothing.** VPS:
   `docket-v3-capture.service` started `14:00:00 CEST`, exited `14:00:06` with status 2
   (`CaptureRefused`), 1.297 s CPU over 6 s wall; `/var/lib/docket/v3-capture/` is empty; the
   journal is volatile (no `/var/log/journal`) and rotated, so the refusal text is gone. The box
   runs at **load average 25.9 on 8 cores with 702 MB free RAM**, and `capture.py` checks its
   **5-second tolerance after importing the whole package** (`capture.py:53`, check at `:186-198`,
   reached from `main()` at `:441` only after `load(_resolve_spec(...))`). Under that load the
   process could not reach the check inside five seconds. The spec says a missed moment must be
   recommitted (`v3-02-yield-router.json` `case_selection`). **All three v3 families therefore still
   have `inputs_sha256: ""` and zero runs**, and the served `/advantage/v3.json` honestly says
   `registered_waiting_for_inputs: 3`.
3. **Reproducibility is broken as deployed.** `POST /hire/range-doctor` with
   `observation_block` = head−60 returns 200; **head−200 (about ten minutes old) returns 502
   `PrunedStateError … an archive node is required`** (verified 13:22Z). So the eight-line LP
   record is not third-party-checkable, "reproducible through Sep 23" is false, and the v3-01
   Range family — which requires archive-readable state at a pinned block and a block-0 Transfer-log
   sweep — cannot lock. The error message is honest; the product claim is not yet true.
   **One purchase (a BSC archive RPC) sits under three gaps.**
4. **The controlled position went out of range on Aug 22.** LP record: in range every day Aug
   15–21; `2026-08-22T06:03Z` block 117372750 "below its range and currently earns no pool
   fees"; still below at 13:22Z. This is the first real, unengineered
   `state → diagnosis → owner decision → later state` event — the exact artifact Codex's win spec
   names for PancakeSwap — and **the record has no owner-decision field** (`lp_record.py:20`,
   backlog entry 8). Every day it stays unrecorded converts preregistration into retrofit.
5. **Zero of the four scored BNB categories has a BSC identity**, and the field is crowded.
   `GET /services` → `agent_id: null` for range-doctor, grid-operator, yield-router, health-guard,
   warden-scan; BNB's gate reads "Agents surfaced on your marketplace must be live on BSC." A
   GitHub sweep found **28 public main-track entrants**, six with live four-category sites
   *[seat]*. Claude verified on 8004scan that rival `san-npm/agripinaa` registered four BSC
   mainnet identities (`269703–269706`, created 2026-08-18, four distinct owners, placeholder
   names, score 0, endpoint unverified) — it clears the gate with hollow registrations. Docket,
   with the deepest agents in the field, does not clear it at all, and is the one entrant nobody
   can see because the repo is private.

---

## 2. The calendar against the plan of record

`CODEX-WIN-SPEC-2026-08-14.md §3` governs. Measured today:

| Spec date | Gate | Status |
|---|---|---|
| Aug 16 | Grid mainnet yes/no | **No decision recorded anywhere in the tree.** Per the spec's own rule the default is CUT: no submitter work, no volume claim. The owner can override; until then this is the standing state. |
| Aug 17–20 | Exact-once $0.50 settlement; "a stranger pays once" | **Not attempted.** No facilitator configured, no settled receipt. |
| Aug 21 | Registered Yield capture | **Failed** (§1 fact 2). |
| Aug 21–23 | Warden evaluation, Yield inputs, v3 runner | Runner and calibration driver landed Aug 17 (1210 tests, mutation-verified) but **zero real seat runs, zero orchestrator runs against a real endpoint**. |
| Aug 17–22 | — | **Zero commits.** Production 6 behind. |

The build did not stop for lack of quality — the Aug 15–17 work is the most rigorous in the
repo. It stopped on the items that need the owner (funding, config, a facilitator, archive
access, a decision). §8 lists those, dated.

---

## 3. Findings not in any prior assessment, ranked

**F1 — The capture failure is a design class, not one bug.** Three independent causes, all
live: (a) wall-clock tolerance checked after imports on a 3× oversubscribed host; (b) volatile
journald, so the one line that explained the refusal is gone; (c) `main()` never passes
`journal=` so per-attempt persistence — the Aug 16 remediation — is inert in production
(`capture.py:445` vs `:158`). The timer fires *at* the moment with `Persistent=false`,
`Restart=no`. **Fix (both Codex runs agree):** fire the timer ≥10 min early, import and write an
`armed` record, then sleep inside the process to each registered slot; keep the strict late
refusal; persist refusals to `/var/lib/docket`; `Restart=on-failure` bounded; enable persistent
journald for the judging window (`mkdir /var/log/journal` + `Storage=persistent`); test the
installed systemd command, not only injected functions. The date-armed test must inject its
clock.

**F2 — Archive access is the highest-leverage single purchase.** It unblocks: third-party
verification of every LP-record line, the "reproducible through Sep 23" claim, and the v3-01
Range lock. Trap *[seat]*: `positions.py:250-259` re-raises on pruned state **without failing
over**, so the archive URL must be first in the RPC list. Decide by Aug 23 (Codex xhigh); if not
bought, v3-01 must be recommitted to a narrower, still-preregistered frame (the
`RANGE-REPLACEMENT-DRYRUN-2026-08-15.md` three-stratum design) before any case is drawn.

**F3 — The facilitator is unresolved, and it is the single largest unknown for TermiX.**
`x402.py` builds the v2 `/verify` + `/settle` envelope for the `eip3009` scheme on `$U`
(`0xcE24…6666`), which is exactly what BNB Chain's B402 facilitator advertises. But the
hostnames in B402's README (`facilitator.b402.ai`, `facilitator.b402.network`) are **NXDOMAIN
from the VPS today**; `b402.ai` is live and redirects to `www.b402.ai` with `dashboard.b402.ai`
and `b402scan.ai`. Binance's Agentic Wallet added x402 on BNB Chain on 2026-07-13 (secondary
source). **Day-1 task:** obtain the live facilitator base URL (and whether `$U` is still whitelisted
and a key is needed) from the B402 dashboard, then run one controlled preflight. If no facilitator
settles `$U`, `true_settlement` can never be true and the paid hire is unclosable at any price —
that must be known this week, not discovered on Aug 31.

**F4 — The default hire returns no money.** `POST /hire/range-doctor {"wallet": …}` returns a
correct decision, tick, bounds, block, gross/net APR and 49.26% overstatement — and **every
dollar field `null`** (`declared_position_value_usd` not supplied). Only a caller who already
knows `declared_position_value_usd` and `estimated_recenter_cost_usd` gets
`annual_overstatement_usd: 17.22`, `cost_only_break_even_days: 10.44`. Codex's element 3 is
half-met, and the run form exposes eleven fields with no example *[seat]*. **Fix:** a prefilled
"Try the verified example" (token 7141050, $50.55, $1.00) on the form and in the canary config;
collapse the seven reproducibility fields behind "Advanced". Do **not** add a price feed — the
abstention is correct.

**F5 — The decision-impact artifact exists, is honest, and its strongest measure found nothing.**
Live `/advantage/v2.json` → `registration_state: "post_hoc"`, `ranking_reversals: 0 / 231`
(the best pool is identical under gross and net). What survives: median annual overstatement
**$126.78 at $10k notional (n=22)** and real payback arriving **a median 8.30 days later** than
the gross figure implies. **The "49.3%" headline does not change which pool an LP picks; retire
it as the Pancake headline and lead with the payback-delay and dollar figures.** The fixed-window
live record (F1 of §1 fact 4) is what turns "arithmetic is wrong" into "an LP made a safer
decision".

**F6 — Two structural safety and positioning wins Docket has never stated.** PancakeSwap's own
eight first-party agent skills (`pancakeswap/pancakeswap-ai`) are **plan-only and terminate at a
deep link** — "This skill does not execute transactions" *[seat]* — i.e. PancakeSwap ships Range
Doctor's architecture. And PancakeSwap's BSC V3 subgraph has reported `hasIndexingErrors: true`
and been **stale since 2026-04-28** while still answering queries *[seat]*; Docket reads the live
explorer API and SHA-pins the bytes (`pools.py:29`). Say both in the submission. The wedge
nobody ships — per-position, tick-aware V3 fee economics — is exactly what `positions.py:19-22`
admits Docket does not compute; PancakeSwap publishes the `collect()` static-call reference
(`collect-fees/references/fetch-v3-positions.mjs`) to match. 2–3 days; do it only after the
owner-decision record and settlement are in.

**F7 — Registering identities alone will still 404 on the site.** The served snapshot is a
`min_feedbacks>=1` sweep (`ingest.py:138-160`), so freshly minted agents never enter it —
SOLVENT's own bound identity already returns `agent_not_found` *[seat]*. G1 needs an
owned-agent allowlist in the sweep plus a restart. Registration itself is `register(string)` on
`0x8004A169FB4a3325136EB29fA0ceB6D2e539a432`, ~163k gas ≈ 0.0000082 BNB each *[seat]*; it has
been done once from this environment (agent 136384). No registration code exists in the tree.

**F8 — The hire route blocks the whole site.** `routes.py:1046 async def hire` is the only async
handler and performs blocking httpx/RPC/sqlite work on the event loop; measured *[seat]*: `/health`
0.33 s idle, **5.52 s during a 6 s hire**. A hung upstream on `warden-scan` costs up to 61 s of
total outage. And `_spend_allowance` runs only when `payment_available`
(`routes.py:1369-1371`), so with every service at `paid_stock=False` **there is no rate limit on
`POST /hire/*`**, including the open relay into `warden.gudman.xyz`. Fix: `run_in_threadpool`
(or make the handler sync), `--workers 2`, allowance on every hire, nginx `limit_req`. The seat's
sub-finding that `X-Forwarded-For` is spoofable is **withdrawn for production**: uvicorn walks the
header right-to-left and the live nginx appends `$remote_addr`, so the real client IP wins.

**F9 — Presentation defects a judge meets in the first minute.** CI is **permanently red** from
Aug 22 (`tests/test_advantage_v3_capture.py:279-284` asserts "Capturing early" against the real
clock; `ci.yml` covers `docs/**`). `README.md:40` says `b883e3f` is deployed while
`docs/operational-evidence.md` says `534af82` *[Codex]*. `claims-to-evidence.md` carries stale v3
hashes *[Codex]*. CTAs read "Open preview" / "Price after admission" / "Paid-stock status"
(`app.js:335-344`, `:478-480`) *[seat]*. Footer links and `/services/{id}` dump raw JSON
*[seat]*. `index.html:6` metadata still claims every service has a recorded run *[Codex]*. The
staleness line shows a green "Complete snapshot" dot beside a seven-digit second count
(`app.js:262-289`) *[seat]*. The deliberation tree contains admissions of a hash-bound false
statement and an invented hash suffix, ~102 absolute `<user-home>` paths across 14 files, and four
lines publishing the VPS IP with a root-SSH recipe (`docs/plans/2026-08-06-phase0-foundations.md:470-473`)
*[seat]*. None of it is a secret (history scan: no keys, tokens, mnemonics in 1,981 objects; `data/`
never committed *[seat]*), but all of it is sponsor-facing the moment the repo flips.

**F10 — DNS-rebinding SSRF in the liveness probe.** `netguard.check_url` resolves and classifies,
then httpx resolves again (`netguard.py:62-89`, `liveness.py:72-89`); a TTL-0 attacker record
passes the guard and the probe connects to loopback, publishing `status_code`/`elapsed_ms` on
`/agents/{id}` as an oracle *[seat, reproduced]*. Fires only during an ingest sweep — which is
exactly what the BNB lane schedules. Pin the vetted address into the connect.

**F11 — What is better than the team says.** Hire results are genuinely real-time, block-stamped
BSC reads across all four categories — best in the field *[seat]*. `/escrow` documents a complete
ERC-8183 sequence against real mainnet contracts and appears in no navigation *[seat]*. The paid
code path — durable nonce binding, distinct terminal states, no-charge on empty result,
de-admission checked after the run, one settle attempt — answers three of Codex's four
track-losing failures **in code** (`routes.py:1146-1334`) *[seat]*; there is no
`verified_unsettled` anywhere anymore. And `min_feedbacks>=1` over a ~293k registry that is
two-thirds bulk mints is a **spam filter, not a coverage gap** — roughly 10–15 genuine
four-category agents exist on BSC mainnet *[seat]*. Docket should publish that count and method;
nobody in the field is saying it.

---

## 4. Alignment, sponsor by sponsor

### TermiX — "Does hiring an agent here beat doing it yourself, and can you prove it with numbers?"

| Criterion (weight) | What they want | What Docket has today | Gap → fix |
|---|---|---|---|
| Value of services (30) | They hire; result must beat the alternative at a price | Decision-grade Range result in ~5 s, free; nothing for sale; dollar fields null by default | §1 fact 1 + F3 + F4: facilitator → one settled $0.50 hire → replay 409 → flip admission limbs → daily canary green |
| Proven advantage (30) | Agent Advantage Report, ≥3 paired tasks, outputs attached, ≥1 trading/stock/security | **Gate met by v1** (3 paired tasks incl. security) but n=1 each, the security task is a recorded loss, v1 quotes $0.01; v3 registered, zero runs | Run Warden first (only family with authored inputs: 12 held-out cases, 8-case key); recommit Yield (§5); decide Range via archive (F2). Never describe v2's null arms as human comparisons. |
| High-stakes & record (20) | Security weighted above general; trading needs win rate/window/risk | Warden: 1-of-4 vectors (v1), 14/31 (v2), **no precision figure anywhere**; SOLVENT halted; Grid zero volume | Warden is the lane; internal gate ≥90% recall & precision, zero critical survivor. If it misses, it stays beta and the 20% stays exposed — do not manufacture a trading record. |
| Marketplace quality (20) | Find, compare, hire without instructions | Works uncoached; comparison table renders but cells are paragraphs; no example input; raw-JSON dead ends; admission jargon on the buy button | F4, F9 (vocabulary, JSON content-negotiation, `job_summary` column), three uncoached cold sessions |

### PancakeSwap — "real benefit to traders or LPs … without ever putting user funds at risk"

| Their wording | Docket's answer | Gap → fix |
|---|---|---|
| "smarter liquidity management" | Range Doctor: live position state, net-vs-gross, conditional wait/recenter with deep links; structurally cannot move funds (no key, no signer — verified by grep *[seat]*) | Record the owner decision on the Aug 22 out-of-range event **today**; publish the fixed-window record and a Pancake hero route (`/` is 464 bytes of JSON naming no Pancake anything *[seat]*) |
| "finding better yields" | Yield Router: live pool comparison with TVL, 24h fees, protocol cut | Recommit the Yield capture (§5) |
| "without ever putting user funds at risk" | The only absolute in the brief, answered structurally — and PancakeSwap's own skills use the same plan-only design (F6) | State it in the greppable form and cite their repo |
| Proof of benefit | Post-hoc decision impact: 0/231 reversals; $126.78 median overstatement at $10k; +8.30 days payback | Re-headline (F5); archive access for reproducibility (F2); optional `collect()` position-level fees (F6) |

### BNB main track — "the marketplace itself, not a portfolio of agents"

| Criterion | Their wording | Docket today | Gap → fix |
|---|---|---|---|
| Hard gate | "Agents surfaced must be live on BSC" | 0/4 category identities; the bound one is halted and not in the snapshot | Four registrations + owned-agent allowlist + sweep + restart (F7). Do G1 **before** the public flip — the README's identity column reads `None` ×4 directly under the gate. |
| Functionality | land → category → understand → activate, no dead end, zero Studio knowledge | Cold hire works; 3 of 4 category forms demand a `wallet` a judge lacks (422 verified *[seat]*) while the hero promises "no wallet" | Prefill Docket's own demo wallet as `field.default` (F4); vocabulary (F9) |
| Data quality | "Real-time … beyond basic counts … genuinely informed call" | Hire plane: best-in-field live reads. Registry plane: snapshot 15 days old (33 at judging), no refresh, green "Complete" dot | 6-hourly refresh timer (sweep code exists; ~2 h), age term + population label, publish the "~15 real agents, here is how we counted" panel (F11) |
| Agent diversity | "All four, equally deep" | Four shelves stocked; only range-doctor has metrics/evidence (`registry.py:73/107/148` empty) | One recorded run for health-guard at minimum; "No run recorded yet" rendered on the card instead of a silent blank |
| Adoption (Phase 2) | "keep alive, drive users to, grow" | Inventory is a Python dict; no third party can list | Write the narrative and a read-only "how a third party would list" spec; do not build the platform |

---

## 5. The disagreements, resolved

**Yield: recommit or drop?** All seats: **recommit once.** Dropping it leaves v3 with two families
and v1 as the only three-task artifact. Dates differ — Codex xhigh says **Aug 25 12:00Z** with a
verified `armed` record by Aug 24 18:00Z; Codex medium says **Aug 26 12:00Z**. **Joint ruling:
Aug 26 12:00Z**, with a full-dress rehearsal of the *installed* unit against a throwaway spec on
**Aug 25 12:00Z** that must produce the `armed` record Codex xhigh requires. Reason: the fix is a
code change + tests + deploy (production is six commits behind) on a host at load 25, and the
rehearsal is the only way to satisfy "test the exact installed systemd command". If the Aug 25
rehearsal does not arm, drop Yield permanently and run v3 with Range + Warden. No third moment.

**Range (v3-01): archive or recommit?** Joint ruling: **buy archive access by Aug 23** (Pancake
seat #2, Codex xhigh #3). It is the only item that closes three gaps at once. If the owner declines,
recommit to the three-stratum frame the same day.

**The paid hero.** All seats keep **Range Doctor** as the hero TermiX must meet first. But Warden
is the only v3 family whose inputs exist, so **run Warden first** (Aug 24–26) to prove the
orchestrator and calibration path on a real endpoint before Range's and Yield's single-shot arms.

**BNB lane timing.** Codex medium: Aug 29–30. Codex xhigh: Sep 3–4, cut entirely if P0 is red.
BNB seat: four "nearly free" items wrongly cut. **Joint ruling:** identities + allowlist + sweep on
**Aug 29–30**, capped at two days (registration needs owner transactions and lead time, and the
README cannot go public with `None` ×4). Adopt the three cheap BNB-seat items into the *primary*
lane because they serve TermiX identically: refresh timer (~2 h), buy-button vocabulary (~0.5 d),
adoption narrative (prose, no code). Health-guard recorded run only if Sep 5 has slack.

**Security seat vs. production.** H2.2 (XFF spoofing) withdrawn for production (F8). H1 (blocking
hire) and H2.1 (no rate limit) stand and go into the Aug 22–23 work because a TermiX judge hiring
while a BNB judge browses is the likeliest way to meet a dead site.

---

## 6. Dated build order, Aug 22 → Sep 9

Each line is a hard exit; slipping one does not move the next.

| Date | Work | Exit |
|---|---|---|
| **Aug 22 (today)** | **Owner records the decision on position 7141050** (wait / recenter, rationale, time) — even as a signed text line bound to the Aug 22 observation digest, to be migrated into the schema tomorrow. Add the LP/payment values to `/etc/docket/docket-canary.conf`. Resolve the B402 facilitator URL and `$U` support (F3). Decide archive access (F2). Fix the date-armed test; push so CI is green. | Decision exists with a timestamp before the position changes; canary legs `controlled_live_lp` stop reading `not_yet_exercised`; facilitator answer known (yes/no). |
| **Aug 23** | Owner-decision event in `lp_record.py` (append-only, digest-bound). Archive RPC first in the list; verify a head−1000 pinned hire returns 200. `hire` off the event loop + allowance on every hire + nginx `limit_req`. Deploy HEAD. | Pinned hire on yesterday's block returns 200; `/health` < 0.5 s during a hire; production = HEAD. |
| **Aug 24** | Capture redesign (F1): pre-arm timer, sleep-to-moment, `journal=` wired, refusals persisted, persistent journald, `Restart=on-failure`. Recommit `v3-02` for Aug 26 12:00Z. Install. | Suite green; unit rehearsed with a future moment on a scratch spec. |
| **Aug 25** | 12:00Z **dress rehearsal** of the installed capture unit → `armed` record. Start Warden: lock `inputs/03-security-heldout.json`, run two real evaluator seats through `calibration_driver.py` (7/8 floor). Controlled preflight of one `$0.50` settlement against the facilitator. | `armed` record written before the moment; both seats calibrated; one settled receipt with tx id. |
| **Aug 26** | 12:00Z **official Yield capture**; validate and lock. Flip Range's admission limbs only if settlement + replay-409 + non-empty result all passed; canary goes green. Lock Range cases (archive path) or register the recommit. | `inputs_sha256` non-empty for Yield and Range; `paid_stock: true` for range-doctor; daily canary verdict passes. |
| **Aug 27–28** | Worked-example prefill + "Advanced" fold (F4); vocabulary, JSON content-negotiation, `job_summary` column, age/population labels (F9); reconcile README / claims table / manifests; redact VPS-IP lines and Windows paths in a new commit (no history rewrite); add the PancakeSwap-skills and stale-subgraph sentences; re-headline Pancake on F5. **Merge to `main`.** | Clean clone → wheel → smoke passes; all public claims agree; `main` = HEAD. |
| **Aug 29–30** | **BNB lane, capped:** four `register(string)` transactions (owner), owned-agent allowlist, one complete targeted sweep, 6-hourly refresh timer, restart; reverse agent→service links; pin the netguard connect address (F10) before the sweep. **Flip the repo public.** | `GET /services` shows four non-null `agent_id`s that resolve on `/agents/{id}`; `snapshot_age_seconds < 21600`; repo public with README on the default branch. |
| **Aug 31** | Uncoached cold rehearsal ×3 (sample, paid hire, replay, Range/Yield/Warden, mobile, clean install). | No repeated dead end; findings fixed same day. |
| **Sep 1–4** | Execute all preregistered paired arms, manual-first; preserve every failure. | Every scheduled primary terminal; no replacement cases, no scored retries. |
| **Sep 5** | Blind scoring, both sheets and mappings published, v3 report and page, fixed-window LP record with later-state observations, claims audit. | `/advantage/v3.json` shows no family `registered_waiting_for_inputs`. |
| **Sep 6** | Freeze: exact tested deployment, source/wheel/evidence hashes, fresh canary. | Release SHA = CI = production = `main`. |
| **Sep 7–8** | Demo rehearsal (one-minute Range hire, Pancake loop, TermiX report, BNB identities); submission package for owner review. | — |
| **Sep 9** | Submit **only on explicit owner approval**. Monitoring continues through Sep 23. | — |

## 7. Cut, unchanged from the win spec, plus two additions

Grid mainnet execution and any volume claim (default stands, no decision recorded); Altana;
SOLVENT revival; Venus-borrow wallet and Health evidence beyond one recorded run; Yield execution
drafting; provider-onboarding platform; Agent Studio / Bedrock; second chain; trust scoring; visual
redesign; full-registry crawl. **Added:** no git history rewrite (it breaks every commit-pinned
evidence claim for a secrecy gain the public hostnames already negate); no `collect()`
position-level fee work until the owner-decision record and one settled hire exist.

## 8. Owner-only actions, dated

| By | Action |
|---|---|
| **Aug 22** | Record the decision on position 7141050 (wait or recenter) in writing, now. Provide the canary LP values and the payment key file path. Approve buying a BSC archive RPC (NodeReal/QuickNode-class; ~1 day of lead). Register on `dashboard.b402.ai` and obtain the facilitator URL. Confirm the Grid default (cut) or override it. |
| **Aug 25** | Approve the controlled `$0.50` settlement preflight (real `$U` moves once). |
| **Aug 26** | Approve flipping Range to paid stock if the three exits passed. |
| **Aug 29** | Approve and fund four `register(string)` transactions (~0.00003 BNB total plus whatever URI hosting needs). |
| **Aug 30** | Approve the public flip (after `main` is merged and redactions landed). |
| **Sep 9** | Approve the submission. |
| **Through Sep 23** | Keep the shared box's other services from starving this one; at load 25 on 8 cores with 700 MB free, a judging-window outage is the single ops risk nobody on this list can code around. |

## 9. Evidence buckets

**Verified by Claude this session** — VPS unit timestamps, exit status, load, memory, journald
mode, LP record (8 lines, Aug 22 flip), canary exit and config, deployed commit, git/branch/visibility
state, pytest result, pruned-state 502 at head−200, `/stats` age, `/advantage/v2.json`
decision-impact figures, competitor agents 269703–269706 and 269223/269228 on 8004scan,
B402 hostnames NXDOMAIN and `b402.ai` live, uvicorn 0.49.0 proxy-header semantics,
`routes.py:1046` async handler and `:1369-1371` allowance gating, `catalogue.py:117` admission
literals, the three v3 specs' `inputs_sha256` and case-selection text, the hackathon page.

**Verified by a seat, not re-run by Claude** — marked *[seat]* / *[Codex]* above: the 8-element
hire presenter walk-through, the 28-entrant GitHub sweep, the register selector and gas figure,
the `/health`-during-hire timing, the DNS-rebind reproduction, the history scan, the PancakeSwap
skills and subgraph findings, the documentation contradictions.

**Believed, not verified by anyone** — the exact refusal text of the Aug 21 run (journal rotated;
timing fits the late branch, an early fire at 11:59:59.x would also exit at +6 s); whether `$U`
is still whitelisted on the live B402 facilitator; whether two real evaluator seats can pass
7/8; whether Warden can clear 90% recall on the held-out set (priors: 1/4 and 14/31 say no);
DoraHacks and X were unsearchable, so the field may be larger than 28.

## 10. Still open

`AUDIT-BACKLOG.md` entries 13–16 remain **OPEN FOR CODEX**; this audit did not close them. The
four Opus seat reports and both Codex outputs are in `docs/deliberation/2026-08-22-seats/`
(absolute local paths stripped, VPS address redacted). Nothing in the repository was modified by
any seat; this file and that directory are the only additions, uncommitted.

---

## 11. Addendum — the ChatGPT Pro audit, compared (same day)

The owner supplied a separate audit from ChatGPT Pro (`2026-08-22-seats/CHATGPT-PRO.md`,
verbatim). Codex ruled on it at xhigh (`CODEX-ON-CHATGPT.md`, 181k tokens, tree unchanged) and
Claude verified its checkable claims. **Joint ruling: it changes no verdict, date or priority;
it corrects one label and adds four things worth adopting, all prose or small config. Followed
literally, most of its build plan would hurt.**

**What it could not do.** ChatGPT had no repository access (404 — the repo is private) and says
so plainly. Every statement it makes about Docket's code, stack or flows is a hypothesis; it
recommends a Next.js/PostgreSQL/Agent-SDK architecture for a FastAPI/SQLite system it never saw.

**Verified by Claude, and adopted:**

1. **The $30,000 is a single winner, not a pool.** Hackathon page: "🥇 Winner: $30,000
   equivalent, plus official adoption." §1's label is corrected above. The owner's framing of
   "sharing the 30k" does not match the rules.
2. **The rules do not require a public repository.** The only wording is "Your submission must
   be functional and publicly accessible during judging." Our Aug-14 documents called the public
   flip a "hard eligibility gate"; it is not. **Keep the flip on Aug 30 anyway** — TermiX hires
   through coding agents that read code, BNB is buying something to adopt, and a claims-to-evidence
   table nobody can open is worth nothing — but it is a credibility gate, not an eligibility one.
3. **The arXiv study is real and directly corroborates Docket's thesis.**
   [arXiv 2606.26028](https://arxiv.org/abs/2606.26028), *Can Trustless Agents Be Trusted? An
   Empirical Study of the ERC-8004 Decentralized AI Agent Ecosystem* (v1 2026-06-24): on BSC,
   **4%** of registrations expose a valid registration file with a live endpoint, **59.2%** of
   reviewers show coordinated Sybil behaviour, and **77.9%** of rated agents keep no valid feedback
   after Sybil filtering (ChatGPT wrote 72.3% — misquoted). A second preprint,
   [arXiv 2606.12128](https://arxiv.org/html/2606.12128v1), measures ERC-8004 operational
   readiness. **Cite both, once, with the caveat "preprint", next to Docket's own measured
   0.205%-with-feedback / 8-of-31-served-200 figures** — in `README.md` and the homepage's data
   panel. Prose only.
4. **"Hire by evidence, not promises."** Better than any line Docket currently leads with; it is
   exactly the fact-plane posture. Adopt as the tagline (prose).

**Adopted with a change of form (Codex's ruling):**

- The **Manifest → Verifier → Receipt** trio is a good *description* of what Docket already has
  (service schemas, liveness probes, hash-bound receipts) and is the right shape for the
  "how a third party would list" page §4 asked for. Write it into `docs/architecture.md`; do not
  build a manifest platform.
- A closed **evidence-modality field** on service cards — `live_read` / `preview` /
  `historical` / `paired_benchmark` / `replay` — answers ChatGPT's "never blend testnet, fork,
  backtest and mainnet" and the BNB seat's declared-vs-measured gap in one small model change.
  Fold into the Aug 27–28 vocabulary pass (`docket/marketplace/models.py`, `docket/api/models.py`).
- Its **Judge Mode** idea — one preset task per category, a replay of a previously recorded real
  run, a system-health panel — is F4's worked-example prefill plus the canary and LP record made
  visible. Adopt the *replay* and *health panel* as UI polish only if Aug 28 has slack.
- Its **three-minute demo script** is a good template for the Sep 7–8 rehearsal once "execute"
  steps are replaced by Docket's actual read-only flow.

**Rejected, with the rule each one breaks:**

| ChatGPT proposal | Why not |
|---|---|
| "Docket Verified" badge; composite score for ranking; "Why Docket ranked this agent here"; default "Recommend" mode | `tests/test_web.py:10` bans `trusted`, `verified agent`, `recommended`, `trust score`, `safety rating`, `endorsed`; `tests/test_api_contract.py:43` bans verdict field names on every model. Docket serves observations, not verdicts — that is the thesis, and the suite enforces it. A readiness *ladder* is fine only as observed stage names, never as a badge. |
| RangePilot that executes; four live *actors*; LiquidationShield that repays; GridPilot on the Infinity limit-order hook | Range Doctor's fund-safety claim is structural (no key, no signer) and PancakeSwap's own skills use the same plan-only design (F6). Grid execution, Venus execution and four-actor parity are on the governing cut list (win spec §6). The Infinity hook is real and is the right *post-hackathon* shape for a Pancake-native grid; not now. |
| ERC-8183 escrow as the judge-facing hire rail | Mainnet dispute window is 7 days with no early accept (`/escrow` documents it); a TermiX judge's visit is minutes. x402 is the immediate rail; ERC-8183 stays the documented scheduled rail. |
| Builder onboarding as a 15-step platform | Explicitly cut (§7); narrative + read-only listing spec instead. |
| Replace the preregistered Range/Yield/Warden families with new Grid/Liquidation A/B tasks | Would discard git-preregistered specs for unregistered ones and ignore every real exit (settlement, capture, archive, owner decision, deploy). |
| Its Aug 22 → Sep 9 calendar | Assumes a team and a rebuild; one builder has 18 days. §6 stands. |
| Its proposed submission language | Claims managed execution, scoped permissions and ERC-8183 receipts Docket does not have. Overclaim is the one failure class this project polices hardest. |

**Net:** the ChatGPT audit is a competent sponsor-side framing document written blind. Its value
is two rule corrections, one citation, one tagline and one small field — about a day of prose.
Its plan is not Docket's plan.
