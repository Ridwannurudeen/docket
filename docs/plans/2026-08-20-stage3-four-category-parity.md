# Stage 3 — Four-Category Parity

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Steps use `- [ ]`.

**Goal:** Stock the last two empty shelves — Yield Optimisation and Health Factor Monitoring — so all four of BNB's categories carry a real service at comparable depth, each reusing the Stage 2 action kernel.

**Where we are:** rebalancing = 1 (Range Doctor), grid_trading = 1 (Grid Operator), yield_optimisation = 0, health_factor = 0. BNB's bar: *"Single-category submissions score poorly. All four, equally deep, is the bar."*

**Verified live this session — build against these, do not re-derive:**
- **Venus Unitroller** (comptroller proxy) `0xfD36E2c2a6789Db23113685031d7F16329158384` — 1,508 bytes, **52 markets** via `getAllMarkets()`. `getAccountLiquidity(address)` returns `(error, liquidity, shortfall)`.
- **Venus does NOT publish a health factor.** It publishes liquidity and shortfall in USD. Aave-style "health factor" is a *derived* ratio requiring per-market collateral factors and balances. **Report what Venus publishes; derive anything else only with the method stated inline.** Inventing a health-factor number Venus never produced is exactly the class of claim this project refuses.
- PancakeSwap pool client and plausibility gate already exist and are tested (`docket/agents/pancake/pools.py`) — Yield Router reuses them, it does not re-implement.
- The action kernel exists: `ActionIntent` (mandatory min-output + calldata commitment), the state machine, `SessionAuthority` with on-chain reads, and `SUBMITTER_CONTRACT`'s owner-key hazard warning. **Reuse it. Do not build a second execution path.**

## Global Constraints
- **Read → evidence → preview first; action second.** The preview is what stocks the shelf and what a judge can inspect with no wallet. Every service must be fully demoable with zero funds.
- **Conservative actions only.** Health Guard may build intents for **repay** and **supply-collateral** — never borrow, never withdraw. Yield Router may move only allowlisted assets among allowlisted destinations. Anything else is out of scope for this stage.
- **Never claim a counterfactual.** Health Guard must not say a liquidation was "prevented" — it observed a state, and an action changed a number. Same discipline as `responded` ≠ working agent.
- **Every rate keeps its denominator and window** (Stage 0 contract, test-enforced). Every derived figure states its method inline.
- No verdict vocabulary. No new dependencies. `./.venv/Scripts/python`. Repo `docket`, branch `feat/stage3-parity`. Do NOT push, do NOT deploy, **no transactions of any kind**. Fable 5 audits before merge.
- RPC/DNS here is flaky — use the failover list with retry, as `agents/pancake/positions.py` does.
- No attribution/Co-Authored-By. Stage by explicit filename.

## File Structure
```
docket/agents/venus/__init__.py
docket/agents/venus/markets.py    # comptroller + vToken reads, pure of interpretation
docket/agents/venus/guard.py      # position state, derived ratio w/ stated method, conservative intents
docket/agents/yield_router/__init__.py
docket/agents/yield_router/universe.py  # the explicit eligible pool set + why each was included/excluded
docket/agents/yield_router/router.py    # net-APR comparison, switching break-even, capped move intent
tests/test_venus_markets.py
tests/test_venus_guard.py
tests/test_yield_universe.py
tests/test_yield_router.py
```

---

### Task 1: Venus market reads

**Files:** `docket/agents/venus/{__init__,markets}.py`, `tests/test_venus_markets.py`

`VenusReader(rpc_urls=BSC_RPCS)` with:
- `.markets() -> list[Market]` — vToken address, underlying, symbol, decimals, collateral factor.
- `.account(address) -> AccountState` — per-market supplied/borrowed balances plus the comptroller's own `(error, liquidity, shortfall)`, each labelled with its source call and the block it was read at.
- Failover + retry across the RPC list; a clear error naming every endpoint tried if all fail.

`AccountState` must carry `liquidity_usd`, `shortfall_usd`, `as_of_block`, and per-market rows. It must NOT carry a field called `health_factor` — that word is reserved for Task 2's explicitly-derived, method-stated figure.

- [ ] Failing tests (hermetic, stubbed RPC): markets parse; an account with no position returns zeros and says so; all-RPCs-fail raises naming each. Then ONE live read against mainnet to prove the shapes, pasted into the report.
- [ ] Commit `feat(venus): comptroller and vToken reads with per-call provenance`.

### Task 2: Health Guard

**Files:** `docket/agents/venus/guard.py`, `tests/test_venus_guard.py`

- `assess(account_state) -> dict` returning: Venus's own liquidity/shortfall verbatim; a **derived** `collateral_ratio` (or equivalent) with `method` stating the exact formula and inputs used; `status` from a closed vocabulary — `no_position`, `borrowing_with_headroom`, `shortfall` (Venus reports shortfall > 0, i.e. liquidatable now); and the block.
- `plan_actions(account_state, policy) -> list[ActionIntent]` — **repay** or **supply-collateral** intents only, built through the Stage 2 `ActionIntent` (so they inherit min-output/commitment/caps). Each action states its condition, its cost, and what it does and does not guarantee.
- A `preview(address)` path that runs the whole thing read-only with no session and no submission.

Tests: a healthy account produces no actions; a shortfall account produces a repay intent whose amount is bounded by policy; the derived ratio's `method` string is present and non-empty; **no output anywhere contains "prevented", "safe", or "protected"** (add to the banned scan).

- [ ] Failing tests → implement → commit `feat(venus): health guard reporting Venus's own numbers and deriving the rest openly`.

### Task 3: Yield universe

**Files:** `docket/agents/yield_router/{__init__,universe.py}`, `tests/test_yield_universe.py`

The honesty problem with "routes to the highest APR" is the *universe*. Define it explicitly:
- `eligible_pools(pools, allowlist) -> (included, excluded)` where every exclusion carries its reason (not allowlisted / below min TVL / implausible turnover / missing fee data), reusing `pools.is_plausible`.
- The returned set states its size and the source snapshot/time, so "highest available APR" always means "highest within this stated, reproducible set" — never an unbounded claim.

Tests: an excluded pool always carries a reason; the included set is deterministic for fixed input; the universe descriptor names its source and time.

- [ ] Failing tests → implement → commit `feat(yield): an explicit eligible universe where every exclusion states its reason`.

### Task 4: Yield Router

**Files:** `docket/agents/yield_router/router.py`, `tests/test_yield_router.py`

- `compare(current, universe) -> list[Candidate]` — each with net fee APR (protocol cut subtracted, the Stage 1e discipline), TVL, turnover, and the denominator/window on every rate.
- `break_even(current, candidate, position_size, gas_estimate) -> dict` — days to recover the switching cost. **A candidate with a higher APR but a break-even beyond the stated horizon must be shown with that fact, not filtered out silently.**
- `plan_move(...) -> list[ActionIntent]` — capped, allowlisted, via the kernel.
- `preview(...)` — full comparison with no wallet.

Tests: net APR ≠ gross (regression against the ~⅓ overstatement); break-even is computed and shown; a higher-APR-but-worse-after-costs candidate is present in output and labelled; no ranking language that implies a Docket recommendation (ordering is by an explicitly named observed metric, and the payload says which).

- [ ] Failing tests → implement → commit `feat(yield): net-APR comparison with switching break-even stated`.

### Task 5: Stock the shelves

**Files:** `docket/hire/catalogue.py`, `docket/marketplace/registry.py`, tests

Register `health-guard` (category `health_factor`) and `yield-router` (category `yield_optimisation`) as hireable services with marketplace records: what you get, price, typical seconds, input schema, evidence refs, and honest `limitations` — Venus-only and no health factor published by the protocol for one; a stated pool universe and no execution guarantee for the other. Both `agent_id` unbound (nothing is registered on-chain yet) and must render as such.

After this: **all four categories show ≥1 service.**

- [ ] Tests asserting `category_counts()` is 1/1/1/1 and that both new records state limitations and unbound identity → commit `feat(marketplace): stock yield and health factor, completing four-category parity`.

---

## After all tasks
Full suite green; Fable 5 audits before merge, with attention to: does anything claim a health factor Venus doesn't publish? does any "highest APR" claim escape its stated universe? do both new services reuse the kernel rather than forking a second execution path? is every preview genuinely wallet-free?

## Self-review
- The four categories reach parity on the axis that is actually checkable — read depth, evidence, preview, and kernel-backed intents — rather than by four shallow labels.
- Venus's missing health factor is treated as a fact to disclose, not a gap to paper over with an invented number.
- The yield universe is the honest core of "routes to the highest APR": the claim is bounded by a set the reader can reproduce.
