# Docket — PancakeSwap partner-challenge audit (1,000 CAKE, one winner)

Audited 2026-08-22 against repo `<repo>`, branch `docs/deliberation-round2`, HEAD `fdf02cf`. Live host `https://docket.gudman.xyz`. Read-only; nothing in the repo was modified.

Judged against the published brief (BRIEFING-V2.md §1.3) and the governing plan (CODEX-WIN-SPEC-2026-08-14.md §2).

**Bottom line.** Docket is *eligible* and unusually honest, but as of today it does not close the loop the win spec names. The four named requirements score: (a) controlled position, reproducible through Sep 23 — **POSITION YES, REPRODUCIBILITY NO (see §0)**; (b) human result with dollar consequence and break-even — **CONDITIONALLY DONE, but only if the caller supplies two numbers Docket does not have**; (c) preregistered decision-impact artifact — **EXISTS BUT IS POST-HOC, AND ITS STRONGEST MEASURE FOUND ZERO EFFECT**; (d) fixed-window live record state→diagnosis→**owner decision**→later state — **MISSING THE OWNER-DECISION LIMB, AND NOT PUBLISHED ANYWHERE A JUDGE CAN SEE IT**.

---

## 0. 🔴 The finding that outranks everything else: reproducibility is already broken

**`observation_block` — the only mechanism Docket offers for reproducing a diagnosis — does not work on the live host for any block older than about forty seconds.**

VERIFIED by direct probe against `https://docket.gudman.xyz/hire/range-doctor`, every call identical but for the block:

| `observation_block` | Age at call | Result |
|---|---|---|
| `117430240` | ~a few blocks | **HTTP 200**, diagnosed |
| `117430200` | ~48 blocks (~36 s) | **HTTP 502 PrunedStateError** |
| `117430100` | ~148 blocks | **HTTP 502 PrunedStateError** |
| `117429900` | ~348 blocks | **HTTP 502 PrunedStateError** |
| `117428342` | ~6 minutes — **the block the live hire itself returned at 13:00:23Z** | **HTTP 502 PrunedStateError** |

Error body, verbatim:
```json
{"error":{"code":"service_failed","message":"range-doctor could not complete: PrunedStateError:
https://bsc-dataseed.binance.org no longer holds the state for this block:
{'code': -32000, 'message': 'missing trie node'}. This is a pruned endpoint, not an empty
result — an archive node is required to read it."}}
```

Control: the same request with no `observation_block` returns HTTP 200 and diagnoses at latest.

**Why this is the top finding.** Win-spec requirement (a) is not "a controlled position" — it is "a Docket-controlled, still-open V3 LP position that **remains reproducible through Sep 23**." A judge scoring on Sep 20 who tries to reproduce the Aug 22 out-of-range diagnosis gets a 502. They can only re-run "latest", which by then shows a different position state, different tick, different pool figures — and therefore cannot check anything the submission claims. The evidence-integrity story, which is Docket's single strongest differentiator, has a hole in exactly the place a careful judge will push.

It also means the **entire daily LP record is unverifiable by a third party.** Every one of its 8 lines was written at a block that is now pruned. A reader can see what Docket says it observed; nobody can check it against the chain. `lp_record.py`'s premise — "a position observed every day from the day it was funded is a record" — holds only if the record can be audited, and today it cannot.

**This is the same blocker as §3.2.** Archive access is one purchase that unblocks three separate requirements: (a) reproducibility through Sep 23, the `v3-01` Range sampler's block-0 log sweep, and third-party verification of the LP record. That makes buying it the highest-leverage spend available, and it reorders the recommendations in §6 accordingly.

**Credit where due:** the error handling here is exemplary. It names the endpoint, quotes the raw JSON-RPC error, distinguishes "pruned, not empty", and names the remedy. That is precisely the behaviour the tool's design philosophy promises, and it is why this was findable in one command. But an honestly-reported broken feature is still a broken feature, and the submission must not cite `observation_block` as evidence of reproducibility while it returns 502 for everything but the last half-minute.

Deployment lag: `git log --oneline 534af82..HEAD | wc -l` → **6**. The live site is 6 commits behind HEAD.

---

## 1. The live hire

### 1.1 What a judge gets with the obvious request

VERIFIED. `POST https://docket.gudman.xyz/hire/range-doctor` with body `{"wallet":"0xe55816904796341bf8535e25f6c8b647927fc946"}` → **HTTP 200, 7,904 bytes, 24.1 s wall** (first call; a second full call ran in 6.4 s — the endpoint's own `measured_value.this_run_seconds` was 4.42 s, so ~2–20 s is network/RPC outside the measured span).

Decision line, verbatim:

> "Position 7141050 is below its range and currently earns no pool fees."

Coverage line, verbatim:

> "all 1 of this wallet's position NFTs were read: 1 hold liquidity and are diagnosed below, and 0 are closed."

Facts returned: pair `USDT/WBNB`, position id `7141050`, current tick `-65443`, bounds `[-65200, -63193)`, BSC block `117428342`, observation time `2026-08-22T13:00:23+00:00`, pool `0x172fcD41E0913e95784454622d1c3724f546f849`. `scan_complete: true`, `stopped_by: null`, `target_found: true`.

**But the dollar consequence and the break-even came back `null`:**

```
declared_position_value_usd: null      annual_gross_usd: null
annual_net_usd: null                   annual_overstatement_usd: null
pool_rate_at_declared_value_usd: null  cost_only_break_even_days: null
estimated_recenter_cost_usd: null      within_horizon: null
```

with `unavailable_reason: "declared_position_value_usd was not supplied for this exact token_id; Docket has no trusted first-party source for this NFT's USD value"` and `"estimated_recenter_cost_usd was not supplied by the caller; declared_position_value_usd was not supplied by the caller"`.

**This is the single biggest judging risk in the entry.** A PancakeSwap judge who does the natural thing — POST a wallet — receives a diagnosis with no money in it. The win spec's requirement (b) ("a human result showing position state, **dollar consequence**, net-versus-gross rate, **switching cost/break-even** and exact next action") is not met by the default call. It is met only by a caller who already knows the answer to two of the questions.

### 1.2 What it gets with the full request

VERIFIED. `POST /hire/range-doctor` with `{"wallet":"0xe558…","token_id":7141050,"declared_position_value_usd":50.55,"estimated_recenter_cost_usd":1.00,"decision_horizon_days":30}` → HTTP 200, 6.4 s. Now complete:

| Field | Value |
|---|---|
| `gross_apr` | 1.03207 |
| `net_apr` | 0.69146 |
| `overstatement_relative` | 0.49260 (49.26%) |
| `overstatement_percentage_points` | 34.06 |
| `annual_gross_usd` | 52.171 |
| `annual_net_usd` | 34.953 |
| `annual_overstatement_usd` | 17.218 |
| `pool_net_apr_if_in_range` | **0.0** (because out of range) |
| `pool_rate_at_declared_value_usd` | **0.0** |
| `cost_only_break_even_days` | **10.442** |
| `decision_horizon_days` / `within_horizon` | 30 / **true** |
| `fee_usd_24h` / `protocol_fee_usd_24h` / `tvl_usd` | 33,774.85 / 11,146.65 / 11,944,712.39 |

Findings, verbatim (this is the strongest prose in the entry):

> "current tick -65431 is below the position's lower bound -65200, so this position has earned no fees since the price left its range"
> "below its range the position holds only USDT — the swap out of WBNB already happened, on the way down through the range"
> "the pool charged $33,775 of fees over 24h against $11,944,712 of TVL and $11,147 of that went to the protocol, leaving 69.1% — that is one day's net fee take annualised, not a forecast and not an expected return"
> "this position is not earning any part of that 69.1% rate while it sits outside its range"
> "positions() reports tokensOwed0=0 and tokensOwed1=0 — the figures written when the position was last touched on-chain, not current uncollected fees; those need a collect() simulation this build does not run, so 0 here means 'not written since', not 'nothing owed'"

Conditional actions: two, `recenter` and `wait`, each carrying its belief and its cost, each with a real PancakeSwap deep link (`https://pancakeswap.finance/liquidity/7141050?chain=bsc`).

### 1.3 Is the dollar consequence real, or a fixed-notional proxy?

VERIFIED: **it is a fixed-notional proxy, and the code says so explicitly.**

`docket/agents/pancake/doctor.py:476-483`:
```python
"annual_gross_usd": declared_position_value_usd * gross,
"annual_net_usd": declared_position_value_usd * net,
"annual_overstatement_usd": declared_position_value_usd * gap,
"pool_rate_at_declared_value_usd": (
    declared_position_value_usd * net if status == "in_range" else 0.0
),
```
`declared_position_value_usd` comes from the caller (`doctor.py:395-398`, `declared_position_value_source: "caller"`). `gross`/`net` are pool-wide (`doctor.py:471-474`: `gross = fee * 365 / tvl`, `net = net_fee_apr(row)`), read from PancakeSwap's own explorer top-pools row.

`RATE_LIMITATION` (`doctor.py:44-55`) is unusually candid and is returned inside every diagnosis:

> "…the pool rate is not this position's rate: a v3 position earns in proportion to its share of the liquidity active at the traded tick, which this read does not measure, so a wide range earns less than the pool rate and a tight one earns more. The figures below apply the pool's rate to a declared notional and are labelled that way; they are a **fixed-notional proxy, not this position's earnings**."

`pool_net_apr_if_in_range` and `pool_rate_at_declared_value_usd` are the two fields added to keep an out-of-range position from being credited with the pool rate: both are hard-set to `0.0` when `status != "in_range"` (`doctor.py:461`, `doctor.py:479-481`). That is correct and is the right conservative choice.

### 1.4 Is the *real* concentrated-position earnings figure computed anywhere?

VERIFIED: **no. Nowhere in the repo.**

- `grep -n "feeGrowth\|collect\|tokensOwed" docket/agents/pancake/positions.py` → `feeGrowthInside0LastX128` / `feeGrowthInside1LastX128` appear **only** at `positions.py:138-139` as ABI field declarations. They are decoded and never consumed by any calculation.
- `grep -rn "feeGrowthInside\|feeGrowthGlobal" --include=*.py docket/` (excluding `build/`) returns only those two ABI lines. No `feeGrowthGlobal`, no `ticks()` read, no `collect()` static call, no active-liquidity-at-tick computation exists.
- `positions.py:19-22` states the gap in its own docstring: "`tokensOwed0/1` is stale… Current uncollected fees need a `collect()` simulation."

So Docket's *only* money figure for an LP is `declared_notional × pool_APR`. That is exactly the metric the brief's phrase "smarter liquidity management" invites a competitor to beat with a real one.

### 1.5 Element-by-element against win-spec (b) and the TermiX eight-part hire

| Required element | Status |
|---|---|
| 1. Decision sentence | ✅ present, verbatim above |
| 2. Verifiable facts (pair, id, tick, bounds, block, time) | ✅ all six present |
| 3. Economic consequence: gross, net, overstatement %/pp, dollar effect at declared value | ⚠️ **caller-conditional** — nulls on the default call |
| 4. Conditional actions with assumptions + cost + deep link | ✅ present; break-even is caller-conditional |
| 5. Coverage (held/examined/closed-skipped/complete) | ✅ present, never `[]` for this wallet |
| 6. Measured value ($0.50, this-run time, paired manual time, quality, report link) | ❌ `paired_manual_seconds: null`, `quality_result: null`, `report_url: null`, with `benchmark_unavailable_reason: "The preregistered v3 paired report has not run…"` |
| 7. Proof: settled tx/payment id, nonce, input hash, output hash, delivery time | ⚠️ input/output hash and `delivered_at` present; **`payment: {"status":"free_tier"}`** — no settlement |
| 8. Primary limitation, one prominent sentence | ✅ `primary_limitation` at top level |

VERIFIED from `GET /hire`: **`paid_stock: false` for all six services** including `range-doctor`. VERIFIED from `GET /canary` (latest id 8, `2026-08-22T04:21:31Z`): overall `verdict: "not_yet_exercised"`; legs `fresh_browser_surface`, `snapshot_age_surface`, `free_verified_example` **passed**; legs `controlled_live_lp`, `exact_0_50_settlement`, `complete_human_result`, `proof_binding`, `rejected_replay` all **`not_yet_exercised`**. Admission limbs: `{"fresh_paired_benchmark": false, "cold_canary": false, "decision_grade_presenter": true, "true_settlement": false}`.

**Judge-facing note:** the *PancakeSwap* judge does not care about $0.50 settlement — the brief says nothing about payments. Settlement is a TermiX requirement that the win spec folded into the same hire. For CAKE purposes, elements 3, 4 and 6 are what matter, and 3/4 are caller-conditional while 6 is empty.

### 1.6 Presentation

VERIFIED. `GET https://docket.gudman.xyz/` returns **464 bytes of JSON** with no mention of PancakeSwap, Range Doctor, or the controlled position. There is a JS service runner at `/service` (HTTP 200, 3,961 bytes, `text/html`; its noscript body names the `curl -X POST /hire/range-doctor` call), an HTML advantage report at `/advantage` and `/advantage/v2`. But **there is no Pancake hero route**: `GET /pancake` → 404, `GET /lp-record` → 404. A CAKE judge arriving at the domain sees an ERC-8004 registry API.

VERIFIED: `GET /skill.md` (26,300 bytes, YAML frontmatter `name: docket`) and `GET /llms.txt` (57,301 bytes) both exist and both mention PancakeSwap — but only twice each, and framed as "one of Docket's services", not as the hero.

---

## 2. The structural no-key / no-signing safety claim

VERIFIED — the claim holds, with one precisely-bounded exception.

```
grep -rniE "private_key|privatekey|PRIVKEY|\.sign|sign_transaction|sendTransaction|send_raw|
  raw_transaction|eth_sendRaw|approve|from_key|LocalAccount|Account\.|mnemonic|seed_phrase|
  build_transaction|transact\(" docket/agents/pancake/ docket/agents/yield_router/
→ NO MATCHES
```

`grep -rnoE "eth_[a-zA-Z]+" docket/agents/pancake/` → the only RPC method named in source is **`eth_call`** (`positions.py:3`). `positions.py:3` docstring: "Read-only by construction. Every call in this module is an `eth_call`". `doctor.py:1-7` states the same for the doctor: "loads no key, builds no transaction and asks for no approval. Every action it emits terminates at a link into PancakeSwap's own interface."

`grep -rniE "private_key|\.sign|sign_transaction|send_raw_transaction|eth_sendRaw|Account\.|from_key" docket/execution/` → the only hits are `authority.py:206/255` (`self.signature` / `selector` — a *function signature string*, not a cryptographic one) and `authority.py:641/644/712/730` (`account.spendInfos`, `account.canExecute`, `KeyStore.isValidKey` — all read calls). **No signing path exists in `docket/execution/` either.**

**The one exception, stated precisely.** `docket/agents/yield_router/router.py` imports `swap_calldata` and `PANCAKE_V2_ROUTER` from `docket.execution.simulate`, and `commit` from `docket.execution.intent` (`router.py:37-38`). At `router.py:348-395` it *builds* PancakeSwap V2 `swapExactTokensForTokens` calldata against router `0x10ED43C718714eb63d5aA57B78B54704E256024E`, computes `calldata_hash = commit(calldata)` (keccak-256, `intent.py:59-66`), and returns it inside a `MoveAction` dataclass. **It never signs it, never sends it, and holds no key.** `intent.py:59` `commit()` is a pure hash. `router.py:99-108`: `NOT_BUILT` = "This is the swap leg only… The remaining step is theirs"; `PREVIEW_REASON` = "This is a preview. It holds no session, no signer and no submitter, and there is no method on it that sends anything."

So the accurate sentence for a judge is: *Range Doctor emits only sentences and PancakeSwap links; Yield Router additionally drafts unsigned calldata and its keccak commitment as a preview object, with no signer or submitter anywhere in the process.* Do **not** say "no code path builds a transaction" — that is false of `yield_router`, and a judge who greps will find `swap_calldata` in three seconds. Say "no code path signs or submits one", which is true and greppable.

**`tickmath.py` is display-grade and is used only for display.** VERIFIED. `tickmath.py:4-8` docstring: "Display-grade, not consensus-grade… must never be used to build a transaction — a mint or swap sized off these numbers would be off by more than the fee tier it was meant to earn." `grep -rn "tickmath\|range_position_pct\|in_range(" --include=*.py docket/ tests/` → the only production consumers are `doctor.py:35` (import), `doctor.py:89` (`in_range`), `doctor.py:96` (`range_position_pct`), `doctor.py:182` (output field). `tick_to_price`, `price_to_tick` and `sqrt_price_x96_to_tick` have **no production caller at all** — only `tests/test_pancake_tickmath.py`. Nothing in `router.py` (the only module that sizes calldata) imports `tickmath`; `router.py:341-348` sizes from `reader.amounts_out()`, a live router quote. **No tickmath number reaches a transaction.** That is a clean answer, and worth stating explicitly in the submission because it is the exact question a security-minded judge asks.

---

## 3. The decision-impact artifact

**It exists — and it is stronger and weaker than expected.**

VERIFIED: `docket/advantage/v2/decision_impact.py` (230 lines) implements exactly the three measures the win spec names — `ranking_reversals()` (`:37`), `dollars_at_notionals()` (`:103`), `break_even_shift()` (`:149`). It is wired into the served report at `docket/advantage/v2/report.py:568` (`"decision_impact": decision_impact_section()`) and `report.py:579-593`. VERIFIED live: `GET https://docket.gudman.xyz/advantage/v2.json` (382,833 bytes) contains a populated `decision_impact` block.

**Three problems, in descending severity.**

🔴 **(i) It is post-hoc, not preregistered.** The served block's own first field:
```
registration_state: "post_hoc"
registration_note: "These three measures were written after the run they read, against the
same frozen snapshot, so their outcome was already knowable when the questions were fixed.
They are published on that footing and not as pre-registered findings. The experiments above
are registered; this section is not."
```
A test enforces the admission (`tests/test_decision_impact.py:147` `test_the_decision_impact_analysis_admits_it_is_post_hoc`). The win spec requirement (c) is for a **preregistered** artifact. This is the honest version of the wrong thing — and honesty is worth something, but it does not satisfy (c).

🔴 **(ii) The strongest measure found zero effect.** Live values:
```
ranking_reversals: numerator 0, denominator 231, value 0.0
best_pool_changes: {changes: false, gross_best == net_best == 0x6dafbf0a… (WBNB/TUT)}
```
Zero of 231 pool pairs reorder between the gross and net rankings, and the single best pool is identical under both. The module's own docstring calls reversals "the strongest of the three, because it needs no assumption about position size" — and it came back empty. The served `finding` says so plainly: "on the decision of which pool to be in, subtracting the protocol's cut changes nothing here."

That is a real result and Docket reports it correctly. But it means the headline "49.3% overstatement" **does not change which pool an LP picks.** The win-spec loop is "finds a live Pancake LP mistake, quantifies the money at stake, and gives the LP a safer decision" — and the measured decision impact on pool choice is nil.

🟡 **(iii) What survives is the weaker two-thirds, and it is decent:**
```
dollars_at_notionals: $10,000 → median annual overstatement $126.78, max $10,179.89 (n=22)
                      $100,000 → median $1,267.82, max $101,798.93
break_even_shift ($10,000 notional, $25 switching cost, n_moves=231):
  median_days_later_than_gross_implies = 8.302
  max_days_later_than_gross_implies = 80,682.15
```
"The real payback arrives a median 8.30 days later than the published gross figures imply" is a genuinely usable LP-facing sentence and should be the Pancake headline, replacing "49.3%".

**The underlying v2 run.** VERIFIED `docket/advantage/v2/runs/01-liquidity-arithmetic.json`: `corpus_id "liquidity-bsc-v3-top-2026-08-11"`, `dataset_sha256 f60b68ed…c015d5`, `n_pools_in_snapshot 28`, `n_planned 22`, `gross_gap_relative median 0.49265 (min 0.47136, max 0.51538)`, `pools_where_gross_gap_exceeds_rounding_gap 22/22 = 1.0`, source `https://explorer.pancakeswap.com/api/cached/pools/v3/bsc/list/top`, fetched `2026-08-11T06:27:12Z`. The finding is solid. Its known weakness (FABLE-AUDIT via the win spec) is that spec and run entered git together, so provenance is self-attested.

### 3.1 The Range sampler

VERIFIED: **it does not exist.** `ls docket/advantage/v3/` → `assemble.py, calibration.py, calibration_driver.py, capture.py, orchestrator.py, page.py, report.py, runner.py, scoring.py, spec.py, sources/, specs/`. No sampler module. `grep -rn "sampler\|def sample" --include=*.py docket/advantage/` → **one hit, and it is a comment**: `spec.py:104` "…so without this the sampler could draw Docket's own demonstration LP".

VERIFIED live: `GET /advantage/v3.json` → `summary: {n_families: 3, states: {registered_waiting_for_inputs: 3}}`, `refuted: []`, `not_refuted: []`. **All three v3 families, including `v3-01-range-doctor`, are `registered_waiting_for_inputs`. No v3 result exists.** There is no `docket/advantage/v3/runs/` directory.

### 3.2 The archive-access blocker (AUDIT-BACKLOG entry 13)

VERIFIED at `docs/deliberation/AUDIT-BACKLOG.md:441-490`, status "OPEN FOR CODEX". The blocker is named at line ~479: "**Not urgent only because Range is blocked on archive access.**"

The reason is structural and severe. `v3-01-range-doctor.json` `case_selection.chosen_by` requires: "From block 0 through that observation block, read **every** ERC-721 Transfer log emitted by PancakeSwap v3 NPM `0x46A15B0b27311cedF172AB29E4f4766fbE7F4364` and MasterChefV3 `0x556B9306565093C855AEA9AE92A594704c2Cd59e`; the distinct non-zero recipients are the complete candidate-wallet frame… If any log or enumeration range cannot complete, input lock fails and this protocol must be recommitted before another block is used."

A block-0-to-head `eth_getLogs` sweep of two high-traffic BSC contracts, plus a per-candidate `positions()` enumeration at a historical block, is not servable by public BSC dataseeds (which prune). This requires a paid archive node. **Registered on Aug 21 as `2026-08-21T12:00:00Z`, and the sampler that would consume it was never written.** With 18 days left, `v3-01` as registered is not achievable without buying archive access, and the case-selection protocol cannot be relaxed without a re-registration and a new `stage_one_protocol_hash`.

Also still open from entry 13 and directly Pancake-relevant:
- 🔴 "Entry 6's schema/producer mismatch" — the validator reconciles conflicted closed rows against `closed_skipped`, but no real reader mode emits that shape (`positions.py:478`).
- 🔴 "Entry 8: **no owner-decision field**, so it is not yet the registered `state → diagnosis → owner decision → later state`." — this is win-spec requirement (d), named as open in Docket's own backlog.

VERIFIED from entry 14 (`AUDIT-BACKLOG.md:492-533`): "**Production is nine commits behind `HEAD`.** Everything in this audit's remediation — exclusive capture writes, the calibration digest check, `still_held`, the fifth registration correction — **is not deployed**." Independently confirmed from the repo side: `git log --oneline 534af82..HEAD | wc -l` → **6** (the gap has narrowed from 9 to 6, or the backlog counted from a different HEAD).

---

## 4. The Yield family and the failed Aug 21 capture

### 4.1 What the spec says must happen on a missed moment

VERIFIED, `docket/advantage/v3/specs/v3-02-yield-router.json`, `case_selection.chosen_by`:

> "At 2026-08-21T12:00:00Z request the top-pools URL and then the token-list URL. If both are not HTTP 200, repeat that ordered pair at exactly +60 seconds and, once more, +120 seconds. Freeze the first scheduled attempt where both succeed; **otherwise input lock fails and this protocol must be recommitted before another time is used.**"

and `case_selection.excluded`: "…a service unable to consume the frozen snapshots makes input lock invalid. **No later pool or snapshot replaces it.**"

So the answer is unambiguous: **a missed moment cannot be quietly retried.** The protocol must be *recommitted* — a new registered moment written into git, producing a new `stage_one_protocol_hash`, **before** that moment arrives. Anything else files a later universe under a registered time, which is the exact failure the whole design exists to prevent. `capture.py:10-12` states the same: "It does not decide when to run, how many times to try, or which attempt to keep — the registration decided all of that before any of it existed."

### 4.2 Why exit 2 with nothing written

VERIFIED code path. `capture.py:436-448`: `main()` returns **2** from exactly two places, both `except CaptureRefused`. `write_capture()` is called *after* `run_registered_capture()` returns — so a `CaptureRefused` raised inside `run_registered_capture` means **no file of any kind is created**, which matches the reported "nothing written".

The refusal that fits the reported conditions is `capture.py:196-202`:
```python
if now > scheduled + timedelta(seconds=LATE_TOLERANCE_S):
    raise CaptureRefused(
        f"the registered capture opened at {…} and it is now {now.isoformat()}, past the "
        f"{LATE_TOLERANCE_S}s tolerance. A late capture is not the registered attempt…")
```
`LATE_TOLERANCE_S = 5` (`capture.py:51`). `now` is set at `capture.py:174` — `started = now or datetime.now(timezone.utc)` — which runs **after** `argparse`, after `_resolve_spec()`, and critically after `from .spec import load` plus `spec.load()` itself. `spec.py` is 2,568 lines and the module imports `httpx`; the service `ExecStart` is a cold `python -m docket.advantage.v3.capture`.

**INFERRED (not verified — I have no host timing data):** on a host at load 25 with 8 cores, cold interpreter start + import of `httpx` + import and parse of a 2,568-line `spec.py` + `load()` of a large JSON spec plausibly exceeds 5 s of wall time between systemd firing at `12:00:00Z` and line 174 executing. The result is `now > scheduled + 5s` → `CaptureRefused` → exit 2, zero bytes written. That is consistent with everything reported, but the alternative refusal path (`_resolve_spec` failing to find the family id, `capture.py:426-428`, also exit 2 and also writes nothing) cannot be excluded from here. **The host's `journalctl -u docket-v3-capture` message text settles it in one command and should be read before any fix is designed** — the two causes need different repairs.

Note the design tension: `capture.py:63-66` asserts `LATE_TOLERANCE_S + 2 * REQUEST_TIMEOUT_S < 60` (5 + 50 = 55). The 5-second budget is not arbitrary — it is what leaves room for two 25 s timeouts inside one registered minute. Widening `LATE_TOLERANCE_S` alone would break that assert. The fix must remove the *startup* cost, not enlarge the tolerance.

### 4.3 What must change so a recommitted moment cannot miss the same way

Ranked, all in `docket/advantage/v3/capture.py` + `deploy/systemd/docket-v3-capture.{service,timer}`:

**A. Pre-arm: start early, sleep to the moment.** Today `capture.py:189-195` *refuses* an early start:
```python
if now < scheduled:
    raise CaptureRefused(f"the registered capture opens at {…} and it is now {…}. "
        "Capturing early would freeze a different observation window…")
```
Change this to: if `scheduled - now` is positive and within a bounded lead (e.g. ≤ 15 minutes), `sleep(delay)` to the moment instead of raising; keep the refusal for anything earlier than the lead. All imports, spec parsing, and `httpx.Client` construction then happen *before* the clock matters, and the 5 s tolerance is measured against a warm process. Set the timer `OnCalendar` to fire ~5 minutes before the recommitted moment. **This is the actual fix** — it converts a cold-start race into a warm sleep, and it is the mechanism the task brief itself suggests.

**B. `main()` does not pass `journal=`.** 🔴 **NEW FINDING, VERIFIED.** `capture.py:439` calls `run_registered_capture(spec)` with no `journal` argument. `run_registered_capture` accepts `journal: Path | None = None` (`capture.py:159`) and only persists per-attempt at `capture.py:245-246`:
```python
if journal is not None:
    write_attempt(record | {"_bodies": bodies_this}, journal)
```
So entry 13's remediation — "each attempt is persisted as it completes rather than held in memory until the end" — **is inert in the only entry point production runs.** A crash after a successful fetch still loses both the bytes and the history, after the window has closed. Fix: `run_registered_capture(spec, journal=Path(args.out))`. Exit test: kill the process between attempt 1 and 2 under a stubbed clock; `attempt-01.json` and `attempt-01.pools.raw.json` must exist on disk.

**C. Warm the network path too.** Even with (A), the first `httpx` request pays DNS + TLS. Pre-resolve and pre-connect during the lead window (a HEAD or a throwaway GET to each host well before the moment), so attempt 1 at `+0s` is a warm-socket request. Exit test: instrument attempt-1 elapsed and assert it is under a threshold in a rehearsal run against the real URLs at a non-registered time.

**D. Reduce cold-start cost regardless.** `_resolve_spec` + `load` pull in a 2,568-line module. Under (A) this stops mattering, but a rehearsal that measures `import`→`started` elapsed on the actual host and records it is what turns "should be fine" into evidence.

**E. Deploy first.** Per entry 14 and the 6-commit gap, the exclusive-write and journal fixes are **not on the host**. Recommitting a moment before deploying repeats the failure with better code sitting in git.

**F. Flag but do not act on:** `docket-v3-capture.service:16` sets `ExecStart=/opt/docket/.venv/bin/python …` while its own comment two lines above says "The deployed venv lives at `/opt/docket-venvs/<commit>` while `/opt/docket/docket` is the PREVIOUS release's source tree". Whether `/opt/docket/.venv` symlinks to the current release is **not verifiable from this session** — it is a host fact. If it does not, the capture runs against a registration that is not the deployed one, which is the exact hazard the comment warns about. **Check on the host before recommitting.**

**G. Rehearse the recommitted moment.** Before writing the new registered time into git, run the whole unit end-to-end at a throwaway moment against the real URLs, on the real host, under real load. Exit test: `capture-attempts.json` + `pools.raw.json` + `token-list.raw.json` all created, `captured: true`, and every observation inside its own minute per `_observations_outside`.

### 4.4 The recommit itself

The new moment must be chosen to leave room for the *rest* of the family. `v3-02` still needs: the locked input envelope built from the frozen bytes, five sampled pools, the manual arm run by a blinded operator, the agent arm run against `/hire/yield-router`, then blind scoring. The build order in the win spec put paired execution at Sep 1–4 and scoring at Sep 5. **A recommitted capture moment later than ~Aug 27 leaves no slack.** Recommit for ~Aug 25–26 UTC, after the deploy in (E) and the rehearsal in (G).

Note also `v3-02`'s `execution_protocol.agent_endpoint` is `https://docket.gudman.xyz/hire/yield-router` and `agent_request_contract` requires the endpoint to "consume those exact snapshots… return their exact source identities and the complete partition, and emit MOVE or STAY."

VERIFIED from `GET /hire`: `/hire/yield-router`'s `input_schema` is `[pool, wallet, token_in, token_out, amount, cap, position_size_usd, switching_cost_usd, horizon_days, pool_snapshot, token_list_snapshot]`. **`pool_snapshot` and `token_list_snapshot` are PRESENT** — so the endpoint can be fed frozen bytes and will not silently fetch a later live universe. (`source_refs` is absent from yield-router's schema; it is a `range-doctor` field, and `v3-02` does not appear to require it separately, since the two snapshot objects carry URL, observation time and bare SHA-256 themselves.)

**Still unverified:** whether the endpoint *returns* the exact source identities and the complete included/excluded partition the harness must validate — that needs an actual call with base64 payloads, which this audit did not construct. Confirm before the moment is recommitted, because "a service that fetches a later live universe is not the registered arm and blocks the experiment."

---

## 5. Competitive positioning

All findings here are from a parallel web-research pass with live URL verification on 2026-08-22. Sources are named inline.

### 5.1 Is there a "PancakeSwap-compatible" shape Docket should match?

**There is a convention, but no gate.** VERIFIED: `https://github.com/pancakeswap/pancakeswap-ai` is real (created 2026-02-27; `main` last committed 2026-03-25; 47 stars, 86 forks; mirrored at `https://pancakeswap.ai/`). It is a **Claude Code plugin marketplace**, not a PancakeSwap-invented schema — three nested manifests:

- `.claude-plugin/marketplace.json` at the root
- `packages/plugins/<plugin>/.claude-plugin/plugin.json`
- `skills/<name>/SKILL.md` — uppercase, YAML frontmatter with `name`, `slug`, `description`, `homepage`, `allowed-tools`, `model`, `license`, `metadata.author`, `metadata.version`, `metadata.openclaw`

Eight skills ship: `swap-planner`, `liquidity-planner`, `collect-fees`, `swap-integration`, `farming-planner`, `harvest-rewards`, `hub-swap-planner`, `hub-api-integration`. Agent discovery entry point is `https://raw.githubusercontent.com/pancakeswap/pancakeswap-ai/main/AGENTS.md`, described as "the machine-readable index for AI agents".

**But PancakeSwap explicitly disclaims any compatibility requirement.** From its own agent guide (`https://docs.pancakeswap.finance/trading-tools/building-trading-agents-on-pancakeswap-v3.md`): *"PancakeSwap requires **no integration** for this to work. V3 pools and farms are permissionless smart contracts — your agent calls them directly, the same way the PancakeSwap front end does."* The only PancakeSwap-side list that matters is pool-level (MasterChefV3 `pid` registration for farms), not agent-level.

VERIFIED: `https://docs.pancakeswap.finance/llms.txt` → HTTP 200, 357,433 bytes; `/llms-full.txt` → HTTP 200. But `https://pancakeswap.ai/llms.txt`, `https://pancakeswap.finance/llms.txt` and `https://developer.pancakeswap.finance/llms.txt` all **404** — so there is no agent-facing `llms.txt` contract to conform to either. NOT FOUND: any first-party PancakeSwap MCP server (`kukapay/pancakeswap-poolspy-mcp` is third-party and must not be described as official).

**Actionable:** Docket already serves `/skill.md` with YAML frontmatter (`name: docket`, `description: …`) — VERIFIED, 26,300 bytes. Matching PancakeSwap's fuller frontmatter shape (add `slug`, `allowed-tools`, `metadata.version`, `homepage`, `license`) and publishing a `SKILL.md` in the same convention is **cheap, legible signalling to a judge who works on that repo daily**. It buys recognition, not compatibility. Half a day at most; do it, but do not mistake it for integration work.

### 5.2 🟢 The strongest external validation Docket has: PancakeSwap's own skills are read-only planners

**All eight first-party skills are plan-only and hand off to a deep link.** VERIFIED verbatim from `liquidity-planner/SKILL.md`: *"This skill **does not execute transactions** — it plans liquidity provision. The output is a deep link URL…"*. `AGENTS.md` on `swap-planner`: "Does not execute transactions." The README's execution-model diagram shows only `[PLAN]` nodes.

**This is a direct endorsement of Range Doctor's architecture.** PancakeSwap's own reference implementation of a PancakeSwap agent does precisely what Range Doctor does: read state, compute, explain, and terminate at a deep link into the PancakeSwap UI where the human acts. The submission should say this explicitly and cite the repo — "Docket's read-only, deep-link-terminating design is the same one PancakeSwap ships in its own agent skills" is a far stronger framing than defending read-only as a limitation.

### 5.3 🔴 The counter-signal, and the honest read

Three facts cut the other way and must not be waved off:

1. **PancakeSwap's agent *documentation* is framed around unattended execution.** The guide's own words: "You describe a strategy; your agent executes it on-chain, unattended." It ships a worked **range rebalancer** — i.e. the executing version of exactly what Range Doctor diagnoses — plus a six-point guardrail checklist (scoped not-infinite approvals, `amount*Min` never 0, short deadlines, `multicall` atomicity, re-read state between txs, per-run value cap + price sanity check). There is also a **Reference Agent** spec (ERC-8183 order/intents settlement) that contains an explicit "Eng sign-off before featuring" line — **PancakeSwap has an internal bar for featuring an agent, and it is a guardrail bar, not an execution bar.**
2. **Sibling challenges in this cycle demand real execution.** Altana's requires "Real onchain transactions through a session key." The event-level requirement is that agents be "live on BSC."
3. **Altana ships executing PancakeSwap skills today.** VERIFIED: `https://skills.altana.network/skill/pancakeswap-liquidity` (v1.0.0, plays `add-liquidity`, `remove-liquidity`, `position-check`) and `/skill/pancakeswap-trading`. Safety is supplied by an on-chain session — "may: add and remove PancakeSwap liquidity; spend up to the cap you set / ✕ send funds anywhere else… Enforced by your Altana session, not by trust" — and each skill is fork-tested ("This version passed on July 21, 2026"). **That is the archetype of the execution-capable entry Docket would be judged against, and its safety story is genuinely good.**

**Honest synthesis: the discriminator is not execution-versus-analysis, it is whether the safety claim is *demonstrated* or merely *structural*.** The brief's own wording — "executing safe automated swaps… **without ever putting user funds at risk**" — makes execution optional and fund safety absolute. A read-only analytics agent is squarely inside the brief's third example ("researching market movements to find demand where creating PancakeSwap pools could improve liquidity efficiency"). Docket's structural claim (no key exists, §2) is *stronger in kind* than a session-scoped cap — a cap bounds losses, an absent key makes them impossible — and that argument should be made head-on rather than avoided.

**Where Docket loses to an Altana-style entry:** the execution entrant can show a transaction hash. Docket can show a diagnosis. Under §0 (reproducibility broken) and §3 (`ranking_reversals: 0/231`), Docket currently cannot show that its diagnosis *changed anything*. **That is the gap that decides this challenge**, and it is exactly what §6 #1 (record the owner decision) exists to close.

### 5.4 🟢 The field looks under-contested

**There is no public submission gallery.** VERIFIED: the hackathon submits via a Google Form (`https://forms.gle/9g9XPNFwnYaHAz9L8`), not DoraHacks or Devpost. Build 5 Aug – 9 Sep 2026; judging 9–23 Sep; winners announced **5 Nov 2026**. So no complete entrant list is obtainable and nobody can scout the field — including Docket's rivals.

Of seven self-declared "Build the Era" marketplace repos found on GitHub (all created Aug 2026), **five ignore the CAKE bounty entirely**; one (`ToanPham247/bnb-agent-studio`) uses PancakeSwap only as a price feed; one (`0xNexuz/eunomia`) has its PancakeSwap adapter **disabled**. Only `Lutviansyah/AgentEra` explicitly names it — "PancakeSwap (1,000 CAKE) — non-custodial swaps/yield" — and that is a pitch bullet, not a verified built capability.

**Read: the CAKE bounty is under-contested, and a genuinely PancakeSwap-native entry has a real chance.** Caveat this properly — GitHub search cannot see private repos or non-marketplace entrants, and affiliation is self-declared. Treat "under-contested" as a working hypothesis, not a fact.

Adjacent prior art exists and is worth knowing (no hackathon affiliation claimed): `ZeroxFactory/0xPools` (one-sided PCS V3 positions), `antonis-alm/guarded-pancakeswap-v3-lp`, `shoko0410/pancakeswap-v3-delta-neutral-lp`, `donnywin85/bsc-dex-spread-mcp` (paid MCP, $0.01 USDC/call).

### 5.5 🎯 The wedge, confirmed from outside

**Nobody ships per-position, tick-aware V3 fee economics.** PancakeSwap's own skills stop at pool-level `apr24h`; Altana's executable liquidity skill is **V2 only**, so concentrated-liquidity management is uncovered by both registries.

This is the same gap §1.4 found from inside the code — Docket quotes `declared_notional × pool_APR` and says so honestly. **It is now confirmed as the defensible differentiator under "smarter liquidity management", and it raises the priority of §6 #6.**

Critically, **PancakeSwap has published the reference implementation Docket would match** — `packages/plugins/pancakeswap-driver/skills/collect-fees/references/fetch-v3-positions.mjs`:
```js
const MAX_UINT128 = 2n ** 128n - 1n
client.simulateContract({
  address: POSITION_MANAGER, abi: nonfungiblePositionManagerABI, functionName: 'collect',
  args: [{ tokenId: id, recipient: WALLET, amount0Max: MAX_UINT128, amount1Max: MAX_UINT128 }],
  account: WALLET,
})
```
Its own comment — `// Differs from tokensOwed via position result` — is the same point `positions.py:19-22` already makes. **Building this and citing PancakeSwap's own code as the reference is an argument Docket can put in front of a judge.**

Two traps in that file Docket must copy exactly:
- **Staked positions collect against MasterChefV3, not the NPM.** For BSC that is `0x556B9306565093C855AEA9AE92A594704c2Cd59e`. Docket's output already carries a `staked` field (`staked: false` for 7141050, VERIFIED), so the branch is needed the moment a staked position appears.
- Enumeration is `balanceOf` → `tokenOfOwnerByIndex` → `multicall` for `positions(tokenId)`, concurrency capped at 5 with a 500 ms inter-batch delay for public RPC limits.

### 5.6 🟢 A trap Docket already avoids — and should say so

VERIFIED by live `_meta` query: **`https://thegraph.pancakeswap.com/exchange-v3-bsc` is stale since 2026-04-28 (block 95,193,923) and reports `hasIndexingErrors: true`** — ~117 days — while every sibling subgraph on the same host (`-eth`, `-arb`, `-base`, `masterchef-v3-bsc`) is current as of 2026-08-22. It still answers queries with plausible-looking data. **It fails silently.**

Docket does not use it. VERIFIED at `pools.py:29` — `PCS_API = "https://explorer.pancakeswap.com/api/cached"` — and `pools.py:32` `TOKEN_LIST_URL = "https://tokens.pancakeswap.finance/pancakeswap-extended.json"`. No subgraph appears anywhere in `pools.py`. Corroborated by `v2/runs/01-liquidity-arithmetic.json` (`pools_url`) and the live hire's `pools.checked: 35`. **Docket's data source is the current one, by luck or by judgement — either way it is now a point to make.**

This is worth a sentence in the submission: any competitor building BSC V3 position analytics off PancakeSwap's own subgraph is shipping four-month-old data without knowing it. Docket reads the live explorer API and SHA-pins the exact response bytes. Demonstrating that check — asserting `_meta.block.timestamp` freshness and `hasIndexingErrors == false` before trusting any subgraph — would itself be a credibility win, and it costs almost nothing.

One caveat to carry: the explorer API's own `apr24h` field is **swap-fees-only, decimal not percent, and excludes CAKE rewards**. Docket does not use `apr24h` — it computes gross and net itself from `feeUSD24h`, `protocolFeeUSD24h` and `tvlUSD` (`doctor.py:471-474`), which is the more defensible choice and should be stated as deliberate.

### 5.7 NOT FOUND — stated plainly

- **No published judging rubric, weights, or criteria for the PancakeSwap 1,000 CAKE challenge.** The entire published criterion is the one sentence in the brief.
- **No published winner list for any past PancakeSwap partner challenge.** The only prior bounty repo (`pancakeswap/Revelation-Hackathon-Bounties`, deadline May 2022) lists criteria but no winners, and is smart-contract-era — a weak precedent for agent judging.
- No X/Twitter thread, Devpost page or DoraHacks BUIDL specifically announcing a PancakeSwap-challenge entry.
- **No first-party PancakeSwap endpoint returning a position-level fee APR.** It must be composed: `collect()` simulation for realized uncollected fees, subgraph `feeGrowthInside*LastX128` deltas for historical earned, and PancakeSwap's own documented forward estimate `fee_next7d = fee_in × ΔL / (L_in + ΔL)` where `fee_in = f_t × V_7d × (T_in / T_7d)` — fee tier × 7-day volume × **fraction of the last 7 days the price spent inside your range**. That last term is the "active liquidity at tick" adjustment expressed as time-in-range, and it is the figure §1.4 found missing.

---

## 6. What would make this entry unmistakably first

Ranked by impact-per-day for the 18 days remaining (Aug 22 → Sep 9), highest first.

### 🥇 #1 — Record the owner decision on the Aug 22 out-of-range event. TODAY.

**Yes, the position going out of range on Aug 22 is an OPPORTUNITY, and it is the single most valuable thing that has happened to this entry.** It is a real, unengineered `state → diagnosis → owner decision → later state` event, on a Docket-controlled position, inside the observation window, with 32 days of runway to Sep 23 for the "later state" to accrue for free.

VERIFIED it is real: the live hire at `2026-08-22T13:00:23Z`, block `117428342`, returns `status: "out_of_range_below"`, tick `-65443` vs lower bound `-65200`. Owner-supplied: the daily record was in range on Aug 21 and reads out-of-range on Aug 22. So the record already holds the transition.

VERIFIED the limb is missing: `docket/agents/pancake/lp_record.py` writes `record_version`, `observed_at`, `wallet`, `token_id`, `observed`, `target_found`, `still_held`, `wallet_positions_held`, `report` — **and nothing else.** There is no owner-decision field. `AUDIT-BACKLOG.md` entry 13 says so in its own words: "Entry 8: no owner-decision field, so it is not yet the registered `state → diagnosis → owner decision → later state`."

**Every day of delay converts a preregistered decision into a retrofitted narrative.** A decision dated Aug 22, recorded before the price came back or did not, is evidence. The same decision recorded on Sep 5 with the outcome already visible is worthless, and a judge will read it that way.

What the owner must decide and record **now**, using the arithmetic already captured live:
- The position is out of range below; it earns **$0** while it stays there (`pool_net_apr_if_in_range: 0.0`).
- Recentering costs a declared **$1.00** and would break even in **10.44 days** at the observed net pool rate — **inside** the declared 30-day horizon (`within_horizon: true`).
- The counter-argument, which the tool itself supplies: recentering "turns this position's impermanent loss from unrealised into realised", and below range the position holds only USDT — the WBNB was already sold on the way down. Recentering locks that in.
- So the decision is a genuine judgement call, not a foregone conclusion. **That is what makes it good evidence.** Record whichever way it goes, with the reason, dated, before the outcome is known.

Files: `docket/agents/pancake/lp_record.py` (add an owner-decision field to the record schema and a CLI path to write one, e.g. an `--owner-decision` / decision-annotation entry appended as its own line with `record_version` bumped); the deployed JSONL at `/var/lib/docket/lp-record/controlled.jsonl`.

**Exit test:** `controlled.jsonl` contains a line dated `2026-08-22` carrying the decision (`wait` or `recenter`), the reason, the break-even and horizon it was decided against, and the block it was decided at — and a test asserts a decision line cannot be written with an `observed_at` later than the state it refers to.

**Caveat that must ship with it:** one position, one event, n=1. The record must repeat `lp_record.py`'s own line — "Nothing here interprets the sequence… Whether the owner acted, and whether acting turned out well, is not a claim this record makes or is able to support." Present it as an observation of a decision process, never as alpha.

### 🥈 #2 — Buy BSC archive access and repoint the reader. ~0.5 days.

Per §0. One paid BSC archive endpoint (Ankr, QuickNode, Chainstack and others sell them; low tens of dollars for the ~5 weeks that matter) unblocks **three** requirements at once:

1. **Requirement (a) reproducibility through Sep 23** — a judge can re-run the Aug 22 diagnosis at block `117428342` and get the same answer, which is the whole point of `observation_block` existing.
2. **The LP record becomes third-party auditable** — all 8 existing lines, and every line to Sep 23, can be checked against the chain rather than taken on Docket's word.
3. **`v3-01` Range's block-0 log sweep becomes possible at all** (§3.2), converting item #8 below from "publish why it didn't run" into a live option.

Files: `docket/agents/pancake/positions.py`. `PositionReader.__init__` takes `rpc_urls=BSC_RPCS` (`:223-224`) and fails over across them at `:241`, so wiring an archive endpoint is small — but `BSC_RPCS` is a **hardcoded module constant** (`:44-45`, `bsc-dataseed.binance.org` then `bsc-dataseed1.defibit.io`), not env-configurable, so this is a small code change plus deployment config, not pure config.

🔴 **Implementation trap, VERIFIED at `positions.py:250-259`.** The pruned-state branch **re-raises immediately and does not fail over**:
```python
if any(marker in text for marker in PRUNED_STATE_MARKERS):
    # Re-raise immediately rather than failing over. Every public
    # dataseed prunes, so trying the next one wastes time…
    raise PrunedStateError(...)
```
The reasoning is sound *while every endpoint is a pruning dataseed* — but it means an archive URL appended **after** the dataseeds would never be reached: the first URL raises `PrunedStateError` and aborts the whole call. **The archive endpoint must be first in the tuple**, or the marker branch must be changed to fail over while any untried URL remains and only raise `PrunedStateError` once all are exhausted. Getting this backwards produces the exact same 502 with an archive node paid for and idle. The `PrunedStateError` message itself stays as it is — it is correct, and it should still fire when no endpoint can serve the block.

**Exit test:** `POST /hire/range-doctor` with `{"wallet":"0xe558…","token_id":7141050,"observation_block":117428342}` returns HTTP 200 with `status: "out_of_range_below"`, tick `-65443`, bounds `[-65200, -63193)` — byte-for-byte the diagnosis this audit captured live at 13:00:23Z. Add it as a canary leg so a silent archive expiry is caught before a judge finds it.

**Cost of not doing it:** the submission cannot honestly claim reproducibility, and must instead disclose that its historical record is unverifiable — a large concession on the one axis where Docket is otherwise strongest.

### 🥉 #3 — Publish the LP record and a Pancake hero route. 1 day.

VERIFIED: `GET /lp-record` → 404, `GET /pancake` → 404, `GET /` → 464 bytes of JSON naming no Pancake anything. **The record exists only as a file on a VPS a judge cannot reach.** Requirement (d) is a "fixed-window live record" — a record no judge can read is not a record for judging purposes.

Files: `docket/api/routes.py` (add `GET /lp-record` serving the JSONL and `GET /pancake` serving an HTML hero page), `docket/api/` page templates alongside the existing `/advantage` HTML renderer.

The hero page should be the *whole* loop on one screen, in this order: the position and its state today → the diagnosis in the tool's own words → **the dated owner decision** → the state since → the decision-impact numbers from §3 → the safety statement from §2. Deep-link to PancakeSwap. No JSON.

**Exit test:** a fresh browser at `https://docket.gudman.xyz/pancake` with no wallet, no account and no JavaScript-dependent hire shows the full loop and the position id, and `GET /lp-record` returns every recorded day including the decision line.

### #4 — Make the default hire return money. 1 day.

The `{"wallet": "0x…"}` call returning `annual_overstatement_usd: null` is the highest-probability judging failure in the entry, because it is what a judge will actually type.

Two options; **take the second**:
1. Derive the position's USD value from a price feed — rejected, and correctly: `doctor.py:467-471` says "Docket has no trusted first-party source for this NFT's USD value", and inventing one would break the tool's whole epistemic stance.
2. **Keep the nulls, but make the response carry a ready-made request that fills them.** Add to the `unavailable_reason` path a `how_to_complete` object naming the exact fields and, for the controlled position, the exact declared values Docket publishes for it ($50.55 / $1.00 / 30 days) with a copyable request body. The judge gets one obvious next call instead of a dead end.

Files: `docket/agents/pancake/doctor.py` (`_economic_consequence` at `:467`, `_conditional_actions` at `:515`), `docket/hire/catalogue.py:899+` (`what_you_get` already explains this in prose at ~90 words — most judges will not read it).

**Exit test:** `POST /hire/range-doctor -d '{"wallet":"0xe558…"}'` returns, inside the same response, a complete request body that a judge can paste to get the dollar figures — and a test asserts the suggested body actually validates against `input_schema`.

### #5 — Re-headline the Pancake claim on the decision-impact numbers. 0.5 days.

The submission currently leads with "49.3% overstatement". The measured decision impact of that error on **pool choice is zero** (`ranking_reversals: 0/231`), and a competent judge who reads `/advantage/v2.json` will find that themselves. Lead with the two measures that did move, and disclose the null:

> "Reading PancakeSwap's published gross fee rate instead of the protocol-adjusted net rate does not change which pool an LP picks — 0 of 231 pool pairs reorder. It changes what the position is worth and when a move pays back: at a declared $10,000 the median pool overstates annual fees by $126.78, and across 231 candidate moves the real payback arrives a median **8.3 days later** than the gross figures imply."

Leading with the null and then the real effect is *more* credible than leading with the big percentage, and it is the kind of thing that separates a first place from a shortlist. Files: submission copy, `docket/advantage/v2/report.py:579-593` (the `finding` string already says this — promote it).

### #6 — Position-level fee earnings via `collect()` static-call simulation. 2–3 days.

This is the one substantive *capability* gap (§1.4), and §5.5 confirms from outside that it is **the** defensible wedge: PancakeSwap's own skills stop at pool-level `apr24h`, and Altana's executable liquidity skill is V2-only, so per-position tick-aware V3 economics is shipped by nobody. Every money figure Docket quotes is `declared_notional × pool_APR`; the tool says so honestly, but honesty about a proxy does not beat a competitor who computes the real number.

A `collect()` `eth_call` with `amount0Max/amount1Max = type(uint128).max` from the position owner's address returns actual uncollected fees — **read-only, no signing, no state change**, entirely consistent with the safety claim in §2.

**PancakeSwap has published the reference implementation** (§5.5): `packages/plugins/pancakeswap-driver/skills/collect-fees/references/fetch-v3-positions.mjs` in `pancakeswap/pancakeswap-ai`. Match it and cite it — "this is PancakeSwap's own method" is an argument that plays well with a PancakeSwap judge. Its own comment, `// Differs from tokensOwed via position result`, is the same point `positions.py:19-22` already makes.

Files: `docket/agents/pancake/positions.py` (add a `collect_simulation()` alongside the existing `_call` at `:230`, using the NPM ABI already declared at `:138-141`), `docket/agents/pancake/doctor.py` (`_economic_consequence` — add `uncollected_fees_usd` as a *measured* figure kept clearly distinct from the proxy).

**Two traps to copy exactly, from PancakeSwap's file:** a **staked** position's fees are collected against **MasterChefV3 `0x556B9306565093C855AEA9AE92A594704c2Cd59e`, not the NPM** — Docket's output already carries a `staked` field (`staked: false` for 7141050, VERIFIED), so the branch is needed the moment a staked position appears; and enumeration should cap concurrency at 5 with a ~500 ms inter-batch delay for public RPC limits.

**Stretch, only if the above lands early:** PancakeSwap's documented forward estimate `fee_next7d = fee_in × ΔL / (L_in + ΔL)` with `fee_in = f_t × V_7d × (T_in / T_7d)` — fee tier × 7-day volume × **fraction of the last 7 days spent in range**. That time-in-range term is the true "active liquidity at tick" adjustment the §1.4 gap names. It needs 7 days of tick history, so it is gated behind archive access (#2).

**Exit test:** for position 7141050 the simulated `collect()` returns values distinguishable from the stale `0/0` the position struct reports, and a test asserts the new field is labelled measured while `annual_*_usd` stay labelled proxy. **Risk:** this is the only item on this list that touches the RPC layer; if it slips, it slips — items #1–#5 must not wait on it.

### #7 — Deploy, then recommit the Yield capture. 1 day + a fixed moment.

Per §4.3: deploy the 6-commit gap, fix `main()`'s missing `journal=`, add the pre-arm sleep, rehearse on the host, then recommit for ~Aug 25–26. **Exit test:** the rehearsal at a throwaway moment writes all three files with `captured: true` under real host load.

Ordered below #1–#4 for the *PancakeSwap* judge specifically, because `v3-02` is the Yield family and the win spec is explicit that "Range Doctor remains the singular hero. Yield supplies calculations underneath it; it is not pitched as a second hero." For TermiX's 30% Proven Advantage it ranks much higher.

### #8 — Decide `v3-01` Range's fate in writing. 0.5 days.

Per §3.1–§3.2: the Range sampler does not exist, and the registered case-selection needs a block-0 archive sweep of two BSC contracts that public dataseeds cannot serve. With 18 days left, either buy archive access **now** or **publish the reason `v3-01` did not run** and lean on the controlled-position record (#1) plus the re-headlined decision-impact artifact (#5) instead.

The second is the better use of 18 days, and it is defensible *if written down*. An unrun registered experiment that is explained is a limitation; an unrun registered experiment that is silent is the thing a judge finds and stops trusting the rest over. **Exit test:** `/advantage/v3.json` or the hero page states, for `v3-01`, why it is still `registered_waiting_for_inputs` and what would have been required.

### #9 — State the safety claim in the greppable form. 0.25 days.

Per §2: say "no code path signs or submits a transaction; Range Doctor builds none at all; Yield Router drafts unsigned calldata as a preview object with no signer and no submitter anywhere in the process" — not "no code path builds a transaction", which `router.py:348` falsifies. Add the `tickmath.py` point explicitly: display-grade math is used only for display, and the only module that sizes a call (`router.py:341-348`) sizes from a live router quote, never from `tickmath`. **Exit test:** a reader can `grep swap_calldata` and find the submission already told them about it.

### #10 — Two cheap signalling wins from §5. 0.5 days total.

**(a) Match PancakeSwap's `SKILL.md` frontmatter shape.** Docket already serves `/skill.md` with `name` and `description`. PancakeSwap's convention (§5.1) adds `slug`, `homepage`, `allowed-tools`, `model`, `license`, `metadata.author`, `metadata.version`. Matching it costs an hour and makes Docket legible to a judge who reads that repo daily. It buys **recognition, not compatibility** — PancakeSwap explicitly requires no integration — so do not oversell it in the submission.

**(b) Say that Docket reads the live explorer API, not the stale subgraph.** Per §5.6, `thegraph.pancakeswap.com/exchange-v3-bsc` is 117 days stale with `hasIndexingErrors: true` while its siblings are current, and it fails silently. Docket reads `explorer.pancakeswap.com/api/cached` (`pools.py:29`) and SHA-pins the response bytes. One sentence in the submission, plus optionally a freshness assertion demo. **Exit test:** the hero page states the data source and its observation time, and a reader can match that SHA against the pinned corpus.

**Frame both as what they are — presentation, not capability.** Neither moves a judging criterion on its own; they are cheap because they are cheap.

---

## What I would tell the owner in one paragraph

The Aug 22 out-of-range event is the best thing that has happened to this entry and it has a shelf life measured in days: record the owner's decision today, dated, with the $1.00 cost and 10.44-day break-even already captured, before anyone knows whether the price came back. Then buy an archive endpoint — one purchase fixes reproducibility through Sep 23, makes the whole LP record auditable, and reopens `v3-01`. Then publish the record and a Pancake hero page, because a record living only on a VPS filesystem is not evidence a judge can weigh. Those three things, in that order, convert Docket from "an honest tool that reports a percentage" into "an agent that found a live LP mistake, priced it, and changed what the owner did" — which is the loop the win spec names and the one the CAKE brief rewards. Everything else on the list is optional by comparison.

---

## Verified vs believed — index

**VERIFIED (command or file:line given in the body above).** `observation_block` returns `PrunedStateError` for every block older than ~40 blocks, including the block the live hire itself just used (§0, five probes); `BSC_RPCS` hardcoded at `positions.py:44-45` and the non-failing-over pruned branch at `positions.py:250-259`; live hire behaviour and both response bodies (§1.1–§1.2); the fixed-notional proxy and `RATE_LIMITATION` (`doctor.py:44-55`, `:461`, `:476-483`); absence of any position-level fee computation (`grep feeGrowth` → ABI declarations only at `positions.py:138-139`); no key/sign/send in `agents/pancake/`, `agents/yield_router/` or `docket/execution/`; the `router.py:348-395` calldata-drafting exception and `NOT_BUILT`/`PREVIEW_REASON` at `router.py:99-108`; `tickmath.py` used only for display (`doctor.py:35/89/96/182`, no `router.py` import); `paid_stock: false` for all six services and the five `not_yet_exercised` canary legs; `decision_impact.py` exists, is served at `/advantage/v2.json`, is `registration_state: "post_hoc"`, and reports `ranking_reversals 0/231`, `$126.78` median overstatement at $10k, `+8.30` median break-even days; all three v3 families `registered_waiting_for_inputs`; no Range sampler (`grep sampler` → one comment at `spec.py:104`); the spec's recommit requirement and `capture.py`'s refusal paths (`:189-202`, `:436-448`); `main()` omits `journal=` (`capture.py:439` vs `:245-246`); `LATE_TOLERANCE_S = 5` and the `<60s` assert (`capture.py:51`, `:63-66`); `git log 534af82..HEAD` → 6 commits; `/pancake` and `/lp-record` → 404; `/` is 464 bytes of JSON with no Pancake mention; `lp_record.py` has no owner-decision field; `AUDIT-BACKLOG.md:441-533` entries 13 and 14.

**VERIFIED EXTERNALLY (§5, live URLs fetched 2026-08-22).** `pancakeswap/pancakeswap-ai` exists, is a Claude Code plugin marketplace with 8 `SKILL.md` skills, and **all of them are plan-only / deep-link** (`liquidity-planner/SKILL.md` verbatim); PancakeSwap's agent guide states "PancakeSwap requires **no integration** for this to work"; `docs.pancakeswap.finance/llms.txt` → 200 while `pancakeswap.ai/llms.txt`, `pancakeswap.finance/llms.txt` and `developer.pancakeswap.finance/llms.txt` all 404; no first-party PancakeSwap MCP server exists; Altana ships **executing** PancakeSwap Trading + Liquidity skills (V2 only) behind revocable on-chain sessions; the hackathon submits via a Google Form with no public gallery (build to Sep 9, judging Sep 9–23, winners Nov 5); `thegraph.pancakeswap.com/exchange-v3-bsc` is stale at block 95,193,923 / 2026-04-28 with `hasIndexingErrors: true` while `-eth`/`-arb`/`-base`/`masterchef-v3-bsc` are current; `fetch-v3-positions.mjs` in the PancakeSwap repo is the `collect()`-simulation reference implementation and routes staked positions through MasterChefV3; `pools.py:29/32` confirm Docket reads the explorer API and token list, never a subgraph.

**BELIEVED / UNVERIFIED.**
- **"The CAKE bounty is under-contested"** (§5.4) is a working hypothesis, not a fact. It rests on 7 self-declared GitHub repos found by keyword search; private repos, non-marketplace entrants and anyone who did not describe themselves that way are invisible. Only `Lutviansyah/AgentEra` names the bounty, and its claim was not verified as built.
- No judging rubric or past-winner list exists for the PancakeSwap challenge (§5.7) — the inference that "demonstrated bounded execution" is the discriminator is read off sibling-challenge criteria and PancakeSwap's own guardrail docs, not off any published PancakeSwap weighting.
- The exact pruning depth in §0: I bracketed it between ~40 blocks (works) and ~48 blocks (pruned) with four probes; I did not bisect it, and BSC dataseed retention may vary by node and over time. The conclusion — anything older than ~a minute is unreadable — is robust to that imprecision.
- The exit-2 root cause being *specifically* the >5 s cold-start overrun rather than `_resolve_spec` failing. Both are exit 2 and both write nothing. **Read `journalctl -u docket-v3-capture` before designing the fix.**
- Host load 25 on 8 cores at the capture moment — owner-supplied, not observed here.
- The daily record having 8 lines, and reading in-range on Aug 21 — owner-supplied. I verified the Aug 22 out-of-range state independently via the live hire.
- Whether `/opt/docket/.venv` on the host points at the current release (§4.3 F).
- Whether `/hire/yield-router` *returns* the exact source identities and complete partition `v3-02` requires (§4.4). Its schema **does** accept `pool_snapshot` and `token_list_snapshot` (verified); the response shape under frozen bytes was not exercised.
- The `AUDIT-BACKLOG` "nine commits behind" vs my measured 6 — both are point-in-time; the host may have been redeployed between.
