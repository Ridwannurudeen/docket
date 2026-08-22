# Docket Phase 1e — Range Doctor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Docket's first own agent — a read-only PancakeSwap liquidity adviser that tells an LP which of their positions are out of range, what fees are sitting uncollected, and whether the pool is still worth being in. It is the PancakeSwap bounty entry and the "yield" task in the Agent Advantage Report.

**Architecture:** Three pure layers over two verified data sources: a keyless PancakeSwap REST client for pool economics, an RPC reader for a wallet's on-chain v3 positions, and a pure analysis module that joins them. Nothing signs, nothing approves, nothing holds a key — the bounty asks for benefit *"without ever putting user funds at risk"*, and the cleanest way to satisfy that is to be structurally incapable of moving them.

**Tech Stack:** Python 3.11+, existing pins (`web3==7.16.0`, `httpx==0.28.1`). No new dependencies.

## Global Constraints

- **Read-only, structurally.** No private key is ever loaded, no transaction is ever built or signed, no token approval is ever requested. The agent's only outputs are analysis and deep links into PancakeSwap's own UI where the user acts themselves.
- Verified live 2026-08-08 — build against these, not against assumptions:
  - Pool data: `GET https://explorer.pancakeswap.com/api/cached/pools/v3/bsc/list/top` — **keyless**, HTTP 200, returns `feeTier`, `tvlUSD`, `volumeUSD24h`, `feeUSD24h`, `protocolFeeUSD24h`, `tick`, `sqrtPrice`, `liquidity`, `token0`/`token1` objects. `apr24h` appears on the `pools/list` route, not on `list/top`.
  - On-chain: NonfungiblePositionManager `0x46A15B0b27311cedF172AB29E4f4766fbE7F4364` on BSC — `totalSupply()` returned 4,818,515 and `positions(7087132)` returned fee 100, ticks 65452→66052, liquidity 125256614773376725006.
  - Factory `0x0BFbCF9fa4f9C56B0F40a671Ad40E0805A091865`, MasterChefV3 `0x556B9306565093C855AEA9AE92A594704c2Cd59e`.
- **RPC and DNS are unreliable on this machine** (reproduced repeatedly: `getaddrinfo failed` from Python, same host fine seconds later). Every network client tries a list of endpoints with retry before failing. Verified working order: `https://bsc-dataseed.binance.org`, `https://bsc-dataseed1.defibit.io`, `https://bsc-rpc.publicnode.com`, `https://binance.llamarpc.com`.
- **Pool data is polluted and must be filtered.** Verified in the live top-25: `COSA/BTCB` reports $26.7M TVL against $746 of 24h volume. Any ranking that does not gate on the PancakeSwap token allowlist (`https://tokens.pancakeswap.finance/pancakeswap-extended.json`) plus a sanity bound is worthless, and a judge will spot it immediately.
- **Two APR traps, both verified in the research and both easy to get wrong:**
  1. LPs do **not** receive the whole fee. Net fee APR is `(feeUSD24h - protocolFeeUSD24h) * 365 / tvlUSD`. Using gross `feeUSD24h` overstates yield by ~33%.
  2. A concentrated position earns the pool APR only while **in range**, and zero while out. Never quote pool APR as a position's yield.
- **No verdict language**, consistent with the rest of Docket: the agent reports observations and arithmetic ("out of range since tick 65452 < current 66100", "uncollected fees ≈ $12.40"), and frames advice as explicit conditional recommendations with their reasoning, never as "safe"/"good"/"recommended".
- Every number the agent emits carries the block number and timestamp it was computed at.
- No new dependencies. No Claude/Anthropic attribution; no Co-Authored-By. Stage by explicit filename. Do not push.
- Repo `.`, run with `./.venv/Scripts/python`.

## File Structure

```
docket/agents/__init__.py
docket/agents/pancake/pools.py      # keyless REST client + allowlist filter + net APR
docket/agents/pancake/positions.py  # RPC reader: a wallet's v3 positions
docket/agents/pancake/tickmath.py   # pure tick <-> price, in-range, amounts
docket/agents/pancake/doctor.py     # the analysis that joins pools + positions
tests/test_pancake_pools.py
tests/test_pancake_tickmath.py
tests/test_pancake_doctor.py
```

---

### Task 1: Tick math (pure, no I/O)

**Files:** Create `docket/agents/__init__.py`, `docket/agents/pancake/__init__.py`, `docket/agents/pancake/tickmath.py`, `tests/test_pancake_tickmath.py`

**Interfaces:** `tick_to_price(tick, dec0, dec1) -> float`, `price_to_tick(price, dec0, dec1) -> int`, `in_range(tick_lower, tick_upper, current_tick) -> bool`, `range_position_pct(tick_lower, tick_upper, current_tick) -> float` (0.0 at the lower bound, 1.0 at the upper, clamped outside), `sqrt_price_x96_to_tick(sqrt_price_x96) -> int`.

**Why this is its own task:** it is the only part with real arithmetic risk, it is completely testable without a network, and everything downstream is wrong if it is wrong.

- [ ] **Step 1: Write `tests/test_pancake_tickmath.py`**

```python
import pytest

from docket.agents.pancake.tickmath import (
    in_range,
    range_position_pct,
    sqrt_price_x96_to_tick,
    tick_to_price,
)

# Verified live 2026-08-08: NPM position 7087132, fee tier 100, ticks 65452 -> 66052.
LOWER, UPPER = 65452, 66052


def test_tick_zero_is_price_one_for_equal_decimals():
    assert tick_to_price(0, 18, 18) == pytest.approx(1.0, rel=1e-9)


def test_price_grows_with_tick():
    assert tick_to_price(100, 18, 18) > tick_to_price(0, 18, 18)
    # 1.0001^tick is the definition; check one exact-ish point.
    assert tick_to_price(10000, 18, 18) == pytest.approx(1.0001**10000, rel=1e-6)


def test_decimals_are_applied():
    """token0 6dp / token1 18dp must not silently produce a 1e12 error."""
    assert tick_to_price(0, 6, 18) == pytest.approx(1e-12, rel=1e-9)


def test_in_range_is_inclusive_lower_exclusive_upper():
    assert in_range(LOWER, UPPER, LOWER) is True
    assert in_range(LOWER, UPPER, UPPER - 1) is True
    assert in_range(LOWER, UPPER, UPPER) is False      # upper bound is exclusive
    assert in_range(LOWER, UPPER, LOWER - 1) is False


def test_range_position_pct_endpoints_and_middle():
    assert range_position_pct(LOWER, UPPER, LOWER) == pytest.approx(0.0)
    assert range_position_pct(LOWER, UPPER, UPPER) == pytest.approx(1.0)
    mid = (LOWER + UPPER) // 2
    assert range_position_pct(LOWER, UPPER, mid) == pytest.approx(0.5, abs=0.01)


def test_range_position_pct_clamps_outside():
    assert range_position_pct(LOWER, UPPER, LOWER - 5000) == 0.0
    assert range_position_pct(LOWER, UPPER, UPPER + 5000) == 1.0


def test_zero_width_range_does_not_divide_by_zero():
    assert range_position_pct(100, 100, 100) in (0.0, 1.0)


def test_sqrt_price_roundtrips_to_the_tick_it_came_from():
    # 2**96 corresponds to price 1.0, i.e. tick 0.
    assert sqrt_price_x96_to_tick(2**96) == 0
```

- [ ] **Step 2: Write `tickmath.py`.** `tick_to_price` is `1.0001**tick * 10**(dec0 - dec1)`. `sqrt_price_x96_to_tick` is `floor(log((sqrt/2**96)**2) / log(1.0001))` — compute in floats but round carefully so exact powers land on the right integer. Guard the zero-width range. Docstring must state that these are display-grade conversions, not consensus-grade, and must not be used to build a transaction.

- [ ] **Step 3: Run** `./.venv/Scripts/python -m pytest tests/test_pancake_tickmath.py -q` → 8 passed.

- [ ] **Step 4: Commit** `git commit -m "feat(pancake): tick and price math for range analysis"`

---

### Task 2: Pool client with allowlist filtering and net APR

**Files:** Create `docket/agents/pancake/pools.py`, `tests/test_pancake_pools.py`

**Interfaces:** `PoolClient(base_url=PCS_API, transport=None)` with `.top_pools(chain="bsc", version="v3") -> list[dict]` and `.token_allowlist() -> set[str]` (lowercased addresses); pure functions `net_fee_apr(pool) -> float`, `turnover(pool) -> float` (`volumeUSD24h / tvlUSD`), `is_plausible(pool, allowlist, min_tvl=10_000, max_turnover=50.0) -> tuple[bool, str]`.

- [ ] **Step 1: Write `tests/test_pancake_pools.py`** (hermetic, `httpx.MockTransport`)

```python
import httpx
import pytest

from docket.agents.pancake.pools import (
    PoolClient,
    is_plausible,
    net_fee_apr,
    turnover,
)

# Shape verified live 2026-08-08 against explorer.pancakeswap.com.
GOOD = {
    "id": "0xpool", "feeTier": 500,
    "token0": {"symbol": "USDT", "id": "0x55d398326f99059ff775485246999027b3197955", "decimals": 18},
    "token1": {"symbol": "USDC", "id": "0x8ac76a51cc950d9822d68b83fe1ad97b32cd580d", "decimals": 18},
    "tvlUSD": "1000000", "volumeUSD24h": "500000",
    "feeUSD24h": "250", "protocolFeeUSD24h": "85",
}
# Verified real garbage: COSA/BTCB reported $26.7M TVL on $746 of 24h volume.
JUNK = {**GOOD, "token0": {"symbol": "COSA", "id": "0xdeadbeef", "decimals": 18},
        "tvlUSD": "26744017", "volumeUSD24h": "746", "feeUSD24h": "1", "protocolFeeUSD24h": "0"}


def test_net_fee_apr_excludes_the_protocol_cut():
    """LPs keep roughly two thirds of fees; using gross overstates yield by ~33%."""
    apr = net_fee_apr(GOOD)
    assert apr == pytest.approx((250 - 85) * 365 / 1_000_000, rel=1e-9)
    gross = 250 * 365 / 1_000_000
    assert apr < gross


def test_net_fee_apr_is_zero_when_tvl_is_zero():
    assert net_fee_apr({**GOOD, "tvlUSD": "0"}) == 0.0


def test_turnover_is_volume_over_tvl():
    assert turnover(GOOD) == pytest.approx(0.5)


def test_allowlisted_pool_with_real_volume_is_plausible():
    allow = {GOOD["token0"]["id"], GOOD["token1"]["id"]}
    ok, reason = is_plausible(GOOD, allow)
    assert ok is True and reason == "ok"


def test_pool_with_unlisted_token_is_rejected():
    allow = {GOOD["token1"]["id"]}
    ok, reason = is_plausible(JUNK, allow)
    assert ok is False and "allowlist" in reason


def test_pool_below_min_tvl_is_rejected():
    allow = {GOOD["token0"]["id"], GOOD["token1"]["id"]}
    ok, reason = is_plausible({**GOOD, "tvlUSD": "500"}, allow)
    assert ok is False and "tvl" in reason


def test_absurd_turnover_is_rejected_as_implausible():
    allow = {GOOD["token0"]["id"], GOOD["token1"]["id"]}
    ok, reason = is_plausible({**GOOD, "volumeUSD24h": "999999999"}, allow)
    assert ok is False and "turnover" in reason


def test_top_pools_parses_the_live_response_shape():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[GOOD, JUNK])

    pools = PoolClient(transport=httpx.MockTransport(handler)).top_pools()
    assert len(pools) == 2 and pools[0]["id"] == "0xpool"


def test_client_retries_transport_errors():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] < 3:
            raise httpx.ConnectError("getaddrinfo failed", request=request)
        return httpx.Response(200, json=[GOOD])

    pools = PoolClient(transport=httpx.MockTransport(handler)).top_pools()
    assert calls["n"] == 3 and len(pools) == 1
```

- [ ] **Step 2: Write `pools.py`.** Handle both list and `{"rows": [...]}` response shapes (the live route returns a bare list; sibling routes wrap). Coerce all numeric fields with `float(x or 0)` — they arrive as strings. Retry transport errors with backoff as in `docket/scan8004.py`; reuse that pattern rather than inventing a second one. `is_plausible` returns the reason string so a rejection can be shown rather than silently dropped.

- [ ] **Step 3: Run** `./.venv/Scripts/python -m pytest tests/test_pancake_pools.py -q` → 9 passed.

- [ ] **Step 4: Commit** `git commit -m "feat(pancake): pool client with allowlist gate and net fee APR"`

---

### Task 3: Position reader (RPC)

**Files:** Create `docket/agents/pancake/positions.py`

**Interfaces:** `PositionReader(rpc_urls=BSC_RPCS, w3=None)` with `.wallet_positions(address) -> list[dict]` (NPM-owned plus MasterChefV3-staked) and `.pool_state(token0, token1, fee) -> dict` (`{address, tick, sqrt_price_x96, liquidity}`). Each returned position carries `token_id`, `token0`, `token1`, `fee`, `tick_lower`, `tick_upper`, `liquidity`, `tokens_owed0/1`, and the `block_number` it was read at.

- [ ] **Step 1:** Implement with an RPC failover list (constraint above) — try each endpoint twice before moving on, and raise a clear error naming every endpoint tried if all fail. Read unstaked positions via `NPM.balanceOf` → `tokenOfOwnerByIndex` → `positions(tokenId)`, and staked ones via `MasterChefV3.balanceOf`/`tokenOfOwnerByIndex` (NPM's `ownerOf` returns MasterChefV3 for staked NFTs, so wallets with farmed positions look empty if this is skipped). Resolve the pool via `Factory.getPool(token0, token1, fee)` then read `slot0()` and `liquidity()`.

- [ ] **Step 2:** Note in the docstring that `tokensOwed0/1` from `positions()` is stale — accurate uncollected fees require simulating `collect()`, which is a Phase 2 refinement. Report the stale value explicitly labelled as such rather than presenting it as current.

- [ ] **Step 3: Verify against live mainnet** (read-only): position 7087132 must return fee 100 and ticks 65452→66052 as verified above. Paste the real output into the report. There is no unit test for this module — it is thin I/O over verified contract calls, and a mocked test would only assert the mock.

- [ ] **Step 4: Commit** `git commit -m "feat(pancake): on-chain v3 position reader with RPC failover"`

---

### Task 4: The doctor

**Files:** Create `docket/agents/pancake/doctor.py`, `tests/test_pancake_doctor.py`

**Interfaces:** `diagnose(position, pool, pool_stats) -> dict` (pure) returning `{status, in_range, range_position_pct, pool_net_apr, findings: [...], actions: [...], as_of_block, computed_at}`, and `report(address, *, reader=None, pools=None) -> dict` orchestrating the whole thing.

**Statuses** (closed vocabulary, all descriptive): `in_range`, `out_of_range_below`, `out_of_range_above`, `closed` (zero liquidity), `unknown_pool`.

- [ ] **Step 1: Write `tests/test_pancake_doctor.py`** covering, with pure fixtures: an in-range position reports `in_range` and a positive pool APR; a position whose current tick sits below its lower bound reports `out_of_range_below` and a finding that it is earning zero fees; the same above; a zero-liquidity position reports `closed` and produces no rebalance action; a position in a pool that failed the plausibility gate reports the gate's reason rather than an APR; and — the honesty test — `diagnose` never emits the words `safe`, `recommended`, `guaranteed`, or `best` anywhere in its findings or actions.

- [ ] **Step 2: Write `doctor.py`.** Findings are factual statements with their inputs ("current tick 66100 is above the position's upper bound 66052, so this position has earned no fees since it left range"). Actions are conditional with the condition stated ("if you expect the price to stay near 66100, a range recentred on it would earn fees again — rebalancing costs gas and realises impermanent loss") and each carries a deep link to PancakeSwap's own position UI. Never emit a bare imperative.

- [ ] **Step 3: Run** `./.venv/Scripts/python -m pytest tests/test_pancake_doctor.py -q` → 6 passed. Full suite → 129 passed.

- [ ] **Step 4: Commit** `git commit -m "feat(pancake): range doctor diagnosis over live pool and position data"`

---

### Task 5: Real run

- [ ] **Step 1:** Run `report()` against a real wallet with live positions — start with `0x429898764b0c3d9345eca7d47fa5800696326ddd` (verified to hold position 7087132). Paste the real output verbatim into the report.
- [ ] **Step 2:** Sanity-check the arithmetic by hand for one position: recompute net fee APR from the raw pool fields and confirm it matches, and confirm the in-range verdict against the pool's current tick.
- [ ] **Step 3:** Record how many of the live top-25 pools the plausibility gate rejects and why — that number is itself evidence for the submission.
- [ ] **Step 4:** Commit any fixes the real run required.

---

## Self-review (done at write time)

- Spec coverage: this is the PancakeSwap bounty entry and the yield/LP task of the Agent Advantage Report. It is deliberately read-only, which is the cleanest possible answer to the bounty's "without ever putting user funds at risk".
- Both verified APR traps (protocol fee cut; in-range-only earning) are encoded as tests, not comments.
- The data-pollution gate is a test with the real `COSA/BTCB` numbers in it, so a regression that lets junk through fails loudly.
- Placeholders: none. Tasks 3 has no unit test by explicit reasoning (thin I/O over contract calls verified live) rather than by omission.
