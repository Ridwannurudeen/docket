# Stage 2 — The Action Kernel and Grid Operator

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Steps use `- [ ]`.

**Goal:** Build the plane that lets an agent *act* on BNB Chain inside authority the user granted and the chain enforces — then use it to ship Grid Operator, stocking BNB's empty Grid Trading category and routing real PancakeSwap volume.

**Why this vertical:** it is the highest-leverage single build in the roadmap. One implementation supplies (1) BNB's missing Grid category, (2) real PancakeSwap volume rather than advice, (3) the Altana session-key rider, and (4) the action primitive Range Keeper / Yield Router / Health Guard all reuse.

**Verified this session, build against these:**
- BSC mainnet block 115,155,027. PancakeSwap **V2 Router** `0x10ED43C718714eb63d5aA57B78B54704E256024E` (21,936 bytes), **V2 Factory** `0xcA143Ce32Fe78f1f7019d7d551a6402fC5350c73`, **USDT** `0x55d398326f99059fF775485246999027B3197955` (18 decimals on BSC), **WBNB** `0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c`. All live.
- Altana sessions (re-read from source today): `grantSession` with `permissions.calls` (contract-level `{to}`, method-level `{signature}`, or AND-combined), `permissions.spend` (`{limit, period, token}`), and `expiry` (unix seconds). Session key registered by default. `revokeSession` is gated `onlyKeyOwnerOrValidator` and is **monotonic — a revoked key cannot be reactivated**. Critically: *"Permissions are enforced onchain. A session that tries to call a contract outside its allowlist, or spend beyond its cap, reverts at validation time. There is no off-chain trust assumption."*
- The repo currently contains **zero** session/Altana code. This is a from-scratch plane.

## Global Constraints — read these twice, this stage touches money

- **Docket never holds the owner key.** Ever. The user grants a scoped session; the owner key stays with the owner.
- **A server-side spend check is NOT safety.** Caps, allowlists and expiry must be enforced **on-chain** by the session authority. Docket's own checks are a convenience layer that may only ever be *more* restrictive, never the thing standing between a bug and a user's funds.
- **Range Doctor stays structurally read-only.** It gains no key, no signer, no execution path. Its diagnosis becomes an *input* to the planner. This preserves the "cannot move funds" property that is our clearest safety claim and PancakeSwap's stated requirement.
- **A call allowlist plus a spend cap is necessary but insufficient.** A permitted swap can still be executed at a terrible price. Every autonomous action additionally carries a **semantic intent**: the condition that must hold, exact target + calldata commitment, max input, **min output**, route, slippage bound, deadline, gas ceiling, and a unique nonce. An action whose live simulation disagrees with its intent must not be submitted.
- **No new dependencies without explicit approval.** If the Altana SDK is TypeScript-only and cannot be driven from Python, STOP and report — do not invent a substitute authority and call it equivalent.
- **Nothing on mainnet without the user's explicit go.** Build and test against simulation and testnet. The single tiny mainnet proof is a separate, user-approved step (Task 6) — present the exact command, amount, and cost first, and never re-fire a value-moving call to "check" it.
- Existing contracts stay green: no-verdict, drift (llms.txt covers every OpenAPI path), home-ordering, denominators-on-rates.
- Repo `docket`, branch `feat/stage2-action-kernel`. `./.venv/Scripts/python`. Do NOT push, do NOT deploy. Fable 5 audits before merge. No attribution/Co-Authored-By.

## File Structure
```
docket/execution/__init__.py
docket/execution/intent.py      # ActionIntent: condition, target, calldata commitment, bounds, nonce
docket/execution/authority.py   # SessionAuthority interface + AltanaSessionAuthority (or documented gap)
docket/execution/simulate.py    # preflight: eth_call/estimateGas against the executing account
docket/execution/state.py       # draft→simulated→authorized→active→submitted→confirmed|failed (+paused/expired/revoked)
docket/execution/receipts.py    # binds observations, policy version, sim result, tx hash, before/after, cap consumed
docket/agents/grid/__init__.py
docket/agents/grid/plan.py      # deterministic grid: levels, size/level, triggers — pure
docket/agents/grid/operator.py  # observe → match level → build intent → simulate → submit
tests/test_execution_intent.py
tests/test_execution_state.py
tests/test_grid_plan.py
tests/test_grid_operator.py
```

---

### Task 1: ActionIntent — the semantic commitment

**Files:** create `docket/execution/{__init__,intent}.py`, `tests/test_execution_intent.py`

`ActionIntent` is a frozen record: `intent_id`, `condition` (a declarative predicate over observations, e.g. `price_below(pair, x)`), `chain_id`, `target`, `selector`, `calldata_hash`, `token_in`, `token_out`, `max_input`, `min_output`, `route`, `slippage_bps`, `deadline`, `gas_ceiling`, `nonce`, `policy_version`, `evidence_block`.

Requirements, each with a test:
- Construction **raises** if: `min_output` is zero or absent (never accept "any output"), `max_input` is zero, `slippage_bps` exceeds a hard ceiling (e.g. 500 = 5%), `deadline` is in the past, `gas_ceiling` is zero, or `chain_id` is not 56.
- `calldata_hash` must match the calldata actually built for the same parameters — a helper `commit(calldata) -> hash` plus a `matches(calldata)` check, so a submitted transaction can be proven to be the authorized one.
- `nonce` uniqueness is the caller's responsibility but `ActionIntent` exposes a stable `idempotency_key`.
- No verdict vocabulary anywhere in the record.

- [ ] Failing tests → implement → suite green → commit `feat(execution): action intent with mandatory min-output and calldata commitment`.

### Task 2: The state machine

**Files:** `docket/execution/state.py`, `tests/test_execution_state.py`

States: `draft → simulated → authorized → active → submitted → confirmed | failed`, with `paused`, `expired`, `revoked` reachable from every pre-submission state. Illegal transitions raise. `submitted → authorized` is impossible (no un-sending). A `revoked` or `expired` intent can never reach `submitted` — test each explicitly. Every transition records a timestamp and a reason.

- [ ] Failing tests (including an exhaustive illegal-transition matrix) → implement → suite green → commit `feat(execution): action state machine with no path back from submitted`.

### Task 3: Session authority

**Files:** `docket/execution/authority.py`, tests

Define a `SessionAuthority` protocol: `grant(permissions, expiry) -> SessionRef`, `status(ref) -> {valid, expiry, remaining_cap, revoked}`, `revoke(ref)`, `can_execute(intent) -> (bool, reason)`.

Then implement `AltanaSessionAuthority` against the verified API — `grantSession` with `permissions.calls` (allowlist the V2 router + the two tokens' `approve`), `permissions.spend` (`{limit, period, token}`), `expiry`; `revokeSession` for teardown.

**Hard requirement:** `can_execute` reads authority state from the **chain**, not from local memory. If the Altana SDK cannot be driven from this Python codebase, do NOT fake it: implement the protocol, write the tests against a stub, and **report the integration gap explicitly** with what a TypeScript sidecar or alternative would require. An honest gap beats a fabricated capability — and this is exactly the claim a judge will probe.

- [ ] Tests (a revoked session refuses; an expired session refuses; an out-of-allowlist target refuses; a cap-exceeding amount refuses) → implement → suite green → commit `feat(execution): session authority with on-chain enforced limits`.

### Task 4: Grid plan (pure, no I/O)

**Files:** `docket/agents/grid/{__init__,plan.py}`, `tests/test_grid_plan.py`

A grid is deterministic and user-specified: `lower`, `upper`, `levels`, `size_per_level`, `token_pair`, `side_rule`. `build_plan(...)` returns ordered price levels and, for a given observed price, `next_action(plan, price, filled) -> level | None`. Pure — no network, no chain.

Tests: level spacing is exact and reproducible; a price outside [lower, upper] yields no action; an already-filled level does not re-fire; the same inputs always produce the identical plan hash (determinism is what makes the intent commitment meaningful).

- [ ] Failing tests → implement → suite green → commit `feat(grid): deterministic grid plan with a stable plan hash`.

### Task 5: Grid Operator + marketplace record

**Files:** `docket/agents/grid/operator.py`, `docket/marketplace/registry.py`, `docket/hire/catalogue.py`, tests

Wire it: observe price (reuse `agents/pancake/pools.py`) → `next_action` → build `ActionIntent` → `simulate` → require the simulation to agree with the intent's bounds → `authority.can_execute` → submit. Any disagreement aborts and records why.

Register a `grid-operator` service in the catalogue and a marketplace `ServiceRecord` in category `grid_trading` — **which finally stocks that shelf**. It must state its limitations plainly: V2 exact-input swaps only, mainnet, requires a granted session, and that a confirmed transaction proves execution and **not** benefit.

Add a **preview/dry-run mode** that produces the full plan + intents + simulation with **no session and no submission**, so a zero-knowledge judge can see the whole mechanism without a wallet. This is what makes the category demoable before anyone funds anything.

- [ ] Tests (dry-run produces intents and never submits; a simulation mismatch aborts; a missing session yields a typed error, not a crash) → implement → suite green → commit `feat(grid): grid operator with dry-run preview, stocking the grid category`.

### Task 6: The mainnet proof — USER-GATED, DO NOT EXECUTE

Prepare, do not run. Produce a written runbook at `docs/runbooks/grid-mainnet-proof.md` containing: the exact session grant (allowlist, cap, expiry), the tiny amount, the expected gas cost, the precise commands, the six things to verify (session registered → intent simulated → one confirmed swap → cap decremented on-chain → revoke → post-revoke attempt rejected), the rollback, and the BscScan links to check each. Present it to the user and STOP.

- [ ] Write the runbook → commit `docs(grid): the mainnet proof runbook, pending user approval`.

---

## After all tasks
Full suite green. Fable 5 audits before merge, with specific attention to: is any cap enforced only server-side? can an intent be submitted whose simulation disagreed? can a revoked session still act? is the dry-run genuinely incapable of submitting?

## Self-review
- The read-only guarantee survives: execution is a separate package; Range Doctor is untouched and still has no signer.
- The mandatory `min_output` and calldata commitment are what stop "permitted but terrible" trades — the gap a plain allowlist leaves open.
- Dry-run exists so the category is demoable and judgeable without funds, which is also what makes Task 6 a proof rather than the product.
- If Altana can't be driven from Python, the plan's honest failure mode is a reported gap, not a server-side cap wearing a session's clothes.
