"""The whole move: out of one PancakeSwap v3 position, across, and into another.

`router.py` compares pools and says whether moving pays for itself. It drafts one swap
leg and says, in `NOT_BUILT`, that the rest of the move is the caller's. This module is
the rest of the move — the ordered transactions that take a concentrated position out of
one pool and open the equivalent one in another, each fully built, each bounded, and each
carrying what the chain said about it.

**Nothing here signs and nothing here sends.** `plan_full_route` returns calldata and a
disclosure. `docket/sessions/executor.py` is the only thing that broadcasts.

**The sequence, and why it is that sequence.**

0. **A precondition, not a step.** `approve(session, tokenId)` on the position manager is
   signed by the owner and is *not* in the list this returns. Every call here is broadcast
   from the session key, and a session cannot approve itself for a token it does not own —
   an owner-signed call sitting in the batch would be signed by the wrong account and
   revert at what looks like the route's own first step. The approval is read before
   anything is built (`getApproved` and `isApprovedForAll`) and a session that has not
   been granted it gets `NftApprovalRequired`, naming exactly what the owner must sign.
1. `decreaseLiquidity` — burn the position's liquidity back into the manager's own
   accounting, with non-zero `amount0Min`/`amount1Min` derived from the pool's live price
   rather than left at zero. A zero minimum on a withdrawal is the same defect as a zero
   `amountOutMin` on a swap: it accepts whatever a manipulated tick hands back.
2. `collect` — move the tokens, and any fees the position had accrued, to the **session**.
   The session is the recipient because it is the account that swaps, approves and mints
   next; the funds transit it and `revoke` sweeps whatever is left back to the owner.
3. Swap legs — at most three, all through the V2 router the rest of Docket uses, each
   quoted live and floored at `min_output`. One leg per held token that the destination
   pool does not hold, then one balancing leg to reach the ratio the destination band
   needs at its current tick.
4. `approve(NPM, amount)` for each destination token, for **exactly** the amount the mint
   will pull. Never an unlimited approval, and never a rounded-up one.
5. `mint` into the destination pool with a tick band of `band_width_ticks` either side of
   the pool's current tick, aligned outward to the pool's own spacing, and
   `recipient = owner`. The position lands in the owner's wallet, not the session's, so
   the session's revocation cannot strand it.
6. A verification read spec: which log identifies the new token id, and the exact
   `positions(tokenId)` call that reads it back.

**What the plan is honest about.** The amounts the mint asks for are the conservative
floors of every step before it, not the expected outputs, so the session is holding at
least that much when the mint runs and the call cannot revert for want of a token. What
that leaves behind is dust in the session, which `revoke` sweeps. Fee rates are one 24h
observation annualised, not a forecast. Impermanent loss is not modelled anywhere in the
break-even. And the switching cost is the caller's own figure — this module reads no BNB
price and does not invent one.

**A route resumes from the chain.** The position's liquidity is read live rather than
taken from the caller's snapshot. A run interrupted after the collect leaves the session
holding the tokens and the position at zero liquidity, so the withdrawal steps are skipped
and the plan continues from the session's own balances — and every leg is estimated live
rather than deferred, because by then the session really does hold what it is spending.
"""

from dataclasses import dataclass, field
from decimal import ROUND_FLOOR, Decimal, getcontext

from web3 import Web3

from ...execution.simulate import PANCAKE_V2_ROUTER, swap_calldata
from ...hire.receipts import canonical_hash
from ...jobs.executors.base import PreparedCall
from ..pancake.pools import net_fee_apr
from .router import (
    BREAK_EVEN_METHOD,
    COST_COVERS,
    HORIZON_DAYS,
    MOVE_ASSETS,
    NET_VS_GROSS,
    RATE_DENOMINATOR,
    RATE_WINDOW,
    Candidate,
    _candidate,
    _quotable,
    break_even,
)

NPM = Web3.to_checksum_address("0x46A15B0b27311cedF172AB29E4f4766fbE7F4364")
POLICY_VERSION = "yield-migration/1"
DEADLINE_S = 600
UINT128_MAX = 2**128 - 1
Q96 = 2**96
MIN_TICK = -887272
MAX_TICK = 887272
# PancakeSwap V3's own fee tiers and their spacings, which are not Uniswap's — 2500
# replaces 3000. An unlisted tier is refused rather than guessed: a band aligned to the
# wrong spacing is a mint that reverts, and one aligned to a *narrower* guess is a band
# the pool silently widens.
TICK_SPACINGS = {100: 1, 500: 10, 2500: 50, 10000: 200}
# What this build is willing to hold and route through. The router's own list, shared
# rather than restated.
ROUTABLE_ASSETS = MOVE_ASSETS

TRANSFER_TOPIC = "0x" + Web3.keccak(text="Transfer(address,address,uint256)").hex()
INCREASE_LIQUIDITY_TOPIC = (
    "0x" + Web3.keccak(text="IncreaseLiquidity(uint256,uint128,uint256,uint256)").hex()
)
ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"

# Minimal fragments rather than the full artifacts. Each signature below is the exact
# string the selector is keccak'd from, and `tests/test_yield_migration.py` recomputes
# every one of them: a transcribed selector that nobody recomputes is a call to a
# function that may not exist.
ERC20_ABI = [
    {
        "name": "approve",
        "type": "function",
        "stateMutability": "nonpayable",
        "inputs": [
            {"name": "spender", "type": "address"},
            {"name": "amount", "type": "uint256"},
        ],
        "outputs": [{"name": "", "type": "bool"}],
    },
    {
        "name": "balanceOf",
        "type": "function",
        "stateMutability": "view",
        "inputs": [{"name": "account", "type": "address"}],
        "outputs": [{"name": "", "type": "uint256"}],
    },
]
NPM_WRITE_ABI = [
    {
        "name": "approve",
        "type": "function",
        "stateMutability": "nonpayable",
        "inputs": [
            {"name": "to", "type": "address"},
            {"name": "tokenId", "type": "uint256"},
        ],
        "outputs": [],
    },
    {
        "name": "decreaseLiquidity",
        "type": "function",
        "stateMutability": "payable",
        "inputs": [
            {
                "name": "params",
                "type": "tuple",
                "components": [
                    {"name": "tokenId", "type": "uint256"},
                    {"name": "liquidity", "type": "uint128"},
                    {"name": "amount0Min", "type": "uint256"},
                    {"name": "amount1Min", "type": "uint256"},
                    {"name": "deadline", "type": "uint256"},
                ],
            }
        ],
        "outputs": [
            {"name": "amount0", "type": "uint256"},
            {"name": "amount1", "type": "uint256"},
        ],
    },
    {
        "name": "collect",
        "type": "function",
        "stateMutability": "payable",
        "inputs": [
            {
                "name": "params",
                "type": "tuple",
                "components": [
                    {"name": "tokenId", "type": "uint256"},
                    {"name": "recipient", "type": "address"},
                    {"name": "amount0Max", "type": "uint128"},
                    {"name": "amount1Max", "type": "uint128"},
                ],
            }
        ],
        "outputs": [
            {"name": "amount0", "type": "uint256"},
            {"name": "amount1", "type": "uint256"},
        ],
    },
    {
        "name": "mint",
        "type": "function",
        "stateMutability": "payable",
        "inputs": [
            {
                "name": "params",
                "type": "tuple",
                "components": [
                    {"name": "token0", "type": "address"},
                    {"name": "token1", "type": "address"},
                    {"name": "fee", "type": "uint24"},
                    {"name": "tickLower", "type": "int24"},
                    {"name": "tickUpper", "type": "int24"},
                    {"name": "amount0Desired", "type": "uint256"},
                    {"name": "amount1Desired", "type": "uint256"},
                    {"name": "amount0Min", "type": "uint256"},
                    {"name": "amount1Min", "type": "uint256"},
                    {"name": "recipient", "type": "address"},
                    {"name": "deadline", "type": "uint256"},
                ],
            }
        ],
        "outputs": [
            {"name": "tokenId", "type": "uint256"},
            {"name": "liquidity", "type": "uint128"},
            {"name": "amount0", "type": "uint256"},
            {"name": "amount1", "type": "uint256"},
        ],
    },
    {
        "name": "getApproved",
        "type": "function",
        "stateMutability": "view",
        "inputs": [{"name": "tokenId", "type": "uint256"}],
        "outputs": [{"name": "", "type": "address"}],
    },
    {
        "name": "isApprovedForAll",
        "type": "function",
        "stateMutability": "view",
        "inputs": [
            {"name": "owner", "type": "address"},
            {"name": "operator", "type": "address"},
        ],
        "outputs": [{"name": "", "type": "bool"}],
    },
    {
        "name": "positions",
        "type": "function",
        "stateMutability": "view",
        "inputs": [{"name": "tokenId", "type": "uint256"}],
        "outputs": [
            {"name": "nonce", "type": "uint96"},
            {"name": "operator", "type": "address"},
            {"name": "token0", "type": "address"},
            {"name": "token1", "type": "address"},
            {"name": "fee", "type": "uint24"},
            {"name": "tickLower", "type": "int24"},
            {"name": "tickUpper", "type": "int24"},
            {"name": "liquidity", "type": "uint128"},
            {"name": "feeGrowthInside0LastX128", "type": "uint256"},
            {"name": "feeGrowthInside1LastX128", "type": "uint256"},
            {"name": "tokensOwed0", "type": "uint128"},
            {"name": "tokensOwed1", "type": "uint128"},
        ],
    },
]
SELECTORS = {
    "erc20.approve": "approve(address,uint256)",
    "npm.approve": "approve(address,uint256)",
    "npm.getApproved": "getApproved(uint256)",
    "npm.isApprovedForAll": "isApprovedForAll(address,address)",
    "npm.decreaseLiquidity": "decreaseLiquidity((uint256,uint128,uint256,uint256,uint256))",
    "npm.collect": "collect((uint256,address,uint128,uint128))",
    "npm.mint": (
        "mint((address,address,uint24,int24,int24,uint256,uint256,uint256,uint256,"
        "address,uint256))"
    ),
    "npm.positions": "positions(uint256)",
}

_erc20 = Web3().eth.contract(abi=ERC20_ABI)
_npm = Web3().eth.contract(abi=NPM_WRITE_ABI)

GAS_CEILINGS = {
    "npm.approve": 120_000,
    "npm.decreaseLiquidity": 400_000,
    "npm.collect": 300_000,
    "swap": 300_000,
    "erc20.approve": 120_000,
    "npm.mint": 800_000,
}

PROTOCOL_RISK = (
    "Every call in this route is to PancakeSwap's own V3 position manager and V2 router "
    "on BSC, at the addresses this repository pins. The destination pool is a smart "
    "contract Docket does not audit and cannot vouch for; the plausibility gate the "
    "eligible set was drawn through checks reported numbers, not code. A concentrated "
    "position earns nothing while the price is outside its band, and the band this route "
    "opens is a fixed number of ticks around one observation — it is not managed after "
    "the mint by anything in this plan."
)
ASSUMPTIONS = (
    "Fee rates on both sides are one 24h observation annualised by x365, not a forecast: "
    "a quiet day reads as a permanently poor pool and a busy one as a fortune.",
    "Impermanent loss is not modelled anywhere in this break-even. Moving realises "
    "whatever the position being left is holding, and the new band takes on its own.",
    "The switching cost is the caller's own figure. Docket reads no BNB price here and "
    "does not invent one, so a break-even is only as good as that input.",
    "Uncollected fees are collected by step 3 and are not forecast: `tokensOwed0/1` on "
    "the position manager is stale until the position is touched, so the amount that "
    "arrives is whatever the collect returns, and no figure for it is published here.",
    "The mint asks for the conservative floor of every step before it, not the expected "
    "output, so the call cannot revert for want of a token. The difference stays in the "
    "session as dust until the session is revoked and swept back to the owner.",
    "Prices move between planning and execution. Every leg carries its own floor and a "
    f"{DEADLINE_S}-second deadline, so a stale plan fails rather than filling at a price "
    "nobody looked at.",
)


class MigrationRefused(ValueError):
    """A move that cannot be built as asked. Raised before any calldata exists."""


class NftApprovalRequired(MigrationRefused):
    """The one authority the session cannot grant itself, and does not yet hold.

    Separate from every other refusal because the remedy is a signature from the owner
    rather than a different request, and because the executor turns `detail` into the
    exact thing the browser has to ask them for.
    """

    def __init__(self, message: str, *, detail: dict) -> None:
        super().__init__(message)
        self.detail = detail


# ------------------------------------------------------------------ tick arithmetic


def sqrt_ratio_x96_at_tick(tick: int) -> int:
    """sqrt(1.0001**tick) as a Q64.96 integer.

    Computed in `Decimal` at 80 significant digits rather than in float64, because
    `pancake/tickmath.py` says in its own first line that its float arithmetic must never
    be used to build a transaction and this is a transaction. It is not computed the way
    the pool computes it: the on-chain `TickMath` is a fixed-point binary exponentiation
    with its own rounding, and the two disagree in the last digits — measured against the
    published constants, by 1 wei at the minimum tick and by a relative 3e-20 at the
    maximum. Nothing here is compared to a contract read for equality; these numbers size
    a floor that then has basis points of slippage subtracted from it, so a discrepancy
    twenty orders of magnitude below the haircut cannot change an outcome.
    """
    if not MIN_TICK <= tick <= MAX_TICK:
        raise MigrationRefused(f"tick {tick} is outside {MIN_TICK}..{MAX_TICK}")
    context = getcontext()
    previous = context.prec
    context.prec = 80
    try:
        ratio = (Decimal("1.0001") ** Decimal(int(tick))).sqrt() * (Decimal(2) ** 96)
        return int(ratio.to_integral_value(rounding=ROUND_FLOOR))
    finally:
        context.prec = previous


def amounts_for_liquidity(
    liquidity: int, sqrt_price: int, sqrt_lower: int, sqrt_upper: int
) -> tuple[int, int]:
    """How much of each token a given liquidity is worth at a given price.

    The three-branch form, not the in-range one with the out-of-range cases bolted on: a
    position whose price has left its band holds exactly one token, and computing the
    other side as a small positive number would put a minimum on a withdrawal that can
    never be met. Floor division throughout, so every amount errs downward — which is the
    safe direction for a figure about to become a minimum.
    """
    if sqrt_lower > sqrt_upper:
        sqrt_lower, sqrt_upper = sqrt_upper, sqrt_lower
    if liquidity <= 0:
        return 0, 0
    if sqrt_price <= sqrt_lower:
        return _amount0(liquidity, sqrt_lower, sqrt_upper), 0
    if sqrt_price < sqrt_upper:
        return (
            _amount0(liquidity, sqrt_price, sqrt_upper),
            _amount1(liquidity, sqrt_lower, sqrt_price),
        )
    return 0, _amount1(liquidity, sqrt_lower, sqrt_upper)


def _amount0(liquidity: int, sqrt_a: int, sqrt_b: int) -> int:
    return (liquidity * Q96 * (sqrt_b - sqrt_a)) // (sqrt_b * sqrt_a)


def _amount1(liquidity: int, sqrt_a: int, sqrt_b: int) -> int:
    return (liquidity * (sqrt_b - sqrt_a)) // Q96


def align_band(tick: int, band_width_ticks: int, spacing: int) -> tuple[int, int]:
    """A band of `band_width_ticks` either side of `tick`, aligned outward to `spacing`.

    Outward on both sides rather than rounded to nearest: rounding inward would hand back
    a band narrower than the one that was asked for, which is a different position from
    the one the caller reasoned about. The result is clamped to the tick range and is
    always at least one spacing wide, because a zero-width band holds no liquidity.
    """
    if spacing <= 0:
        raise MigrationRefused(f"tick spacing {spacing} is not positive")
    if band_width_ticks <= 0:
        raise MigrationRefused(
            f"band_width_ticks {band_width_ticks} is not positive: a band with no width "
            "is a position that is out of range the moment it opens"
        )
    lower = _floor_to(tick - band_width_ticks, spacing)
    upper = _ceil_to(tick + band_width_ticks, spacing)
    lower = max(lower, _ceil_to(MIN_TICK, spacing))
    upper = min(upper, _floor_to(MAX_TICK, spacing))
    if upper <= lower:
        upper = lower + spacing
    return lower, upper


def _floor_to(value: int, spacing: int) -> int:
    return (value // spacing) * spacing


def _ceil_to(value: int, spacing: int) -> int:
    return -((-value) // spacing) * spacing


# ------------------------------------------------------------------ the plan


@dataclass(frozen=True)
class ReadSpec:
    """One `eth_call` a third party runs to check that the move landed."""

    target: str
    data: str
    function: str
    identified_by: str
    note: str

    def as_record(self) -> dict:
        return {
            "target": self.target,
            "data": self.data,
            "function": self.function,
            "identified_by": self.identified_by,
            "note": self.note,
        }


@dataclass(frozen=True)
class MigrationPlan:
    """Every transaction of the move, in order, with the case for making it."""

    calls: tuple[PreparedCall, ...]
    verification: ReadSpec
    disclosure: dict
    source_token_id: int
    destination_pool: str
    tick_lower: int
    tick_upper: int
    # Gross atomic outflow from the session over the whole batch, keyed by token address:
    # every swap leg's input plus what the mint pulls. It is what a session spend cap is a
    # cap on, and it is computed where the calls are built rather than inferred later by
    # something that would have to decode the calldata to guess at it.
    session_spend: dict[str, str] = field(default_factory=dict)
    # The same figures split per call and in batch order. `SessionPolicy.allows` runs once
    # per call, so this is the shape it can actually be checked against; the batch total
    # above stays for the disclosure, where a reader wants one number.
    session_spend_by_call: tuple[dict, ...] = ()
    evidence: dict = field(default_factory=dict)

    @property
    def plan_hash(self) -> str:
        return canonical_hash(self.as_record())

    @property
    def simulation_ok(self) -> bool:
        return all(call.simulation["ok"] for call in self.calls)

    def as_record(self) -> dict:
        return {
            "source_token_id": self.source_token_id,
            "destination_pool": self.destination_pool,
            "tick_lower": self.tick_lower,
            "tick_upper": self.tick_upper,
            "calls": [call.to_dict() for call in self.calls],
            "session_spend": self.session_spend,
            "session_spend_by_call": [dict(entry) for entry in self.session_spend_by_call],
            "verification": self.verification.as_record(),
            "disclosure": self.disclosure,
            "evidence": self.evidence,
        }


def _simulation(
    reader,
    *,
    sender: str | None,
    target: str,
    calldata: bytes,
    gas_ceiling: int,
    block: int,
    observed_at: str,
    deferred: tuple[str, ...] = (),
    extra_checks: tuple[str, ...] = (),
) -> dict:
    """Run what can be run at this block, and name what cannot and why.

    A call whose precondition is created by an earlier call in the same route cannot be
    preflighted before that call lands. Recording it as passing would be a claim about a
    state nobody observed; recording it as failing would condemn a sound route. So the
    checks that ran are listed, the ones that could not are listed with the reason, and
    `ok` reports only the first list. A reader can tell the two apart without reading
    this docstring, which is the point.
    """
    checks = list(extra_checks)
    if sender is None:
        return {
            "ok": True,
            "gas_estimate": None,
            "revert_reason": None,
            "observed_at": observed_at,
            "block": block,
            "checks": checks,
            "deferred": list(deferred),
        }
    checks.append("eth_call")
    try:
        reader.call(sender, target, calldata)
    except Exception as exc:
        return {
            "ok": False,
            "gas_estimate": None,
            "revert_reason": f"{type(exc).__name__}: {exc}",
            "observed_at": observed_at,
            "block": block,
            "checks": checks,
            "deferred": list(deferred),
        }
    checks.append("eth_estimateGas")
    try:
        gas = int(reader.estimate_gas(sender, target, calldata))
    except Exception as exc:
        return {
            "ok": False,
            "gas_estimate": None,
            "revert_reason": f"{type(exc).__name__}: {exc}",
            "observed_at": observed_at,
            "block": block,
            "checks": checks,
            "deferred": list(deferred),
        }
    if gas > gas_ceiling:
        return {
            "ok": False,
            "gas_estimate": gas,
            "revert_reason": f"estimated {gas} gas, above the ceiling of {gas_ceiling}",
            "observed_at": observed_at,
            "block": block,
            "checks": checks,
            "deferred": list(deferred),
        }
    return {
        "ok": True,
        "gas_estimate": gas,
        "revert_reason": None,
        "observed_at": observed_at,
        "block": block,
        "checks": checks,
        "deferred": list(deferred),
    }


def _nft_approval(reader, *, owner: str, session: str, token_id: int) -> bool:
    """Whether the session may already move this position NFT.

    Both forms count, because both are things the owner may have signed: `getApproved`
    for this one token id, and `isApprovedForAll` for the whole collection. A read that
    does not answer is `False` — refusing a route because a node was quiet costs the
    owner one signature they may not need, and assuming an approval nobody read costs
    them a batch that reverts halfway through.
    """
    if not hasattr(reader, "call"):
        return False
    session = Web3.to_checksum_address(session)
    for name, args in (
        ("getApproved", [int(token_id)]),
        ("isApprovedForAll", [Web3.to_checksum_address(owner), session]),
    ):
        try:
            raw = bytes(reader.call(owner, NPM, _encode(_npm, name, args)))
        except Exception:
            continue
        if not raw:
            continue
        if name == "getApproved":
            if Web3.to_checksum_address("0x" + raw[-20:].hex()) == session:
                return True
        elif int.from_bytes(raw[-32:], "big"):
            return True
    return False


def position_liquidity(reader, token_id: int, *, owner: str) -> int | None:
    """The live liquidity of one position, or `None` when the read did not answer.

    Read rather than remembered. A route that has already burned its position and been
    interrupted before the mint has to be resumable, and the only thing that knows how
    far it got is the chain.
    """
    if not hasattr(reader, "call"):
        return None
    try:
        raw = bytes(
            reader.call(owner, NPM, _encode(_npm, "positions", [int(token_id)]))
        )
    except Exception:
        return None
    if len(raw) < 12 * 32:
        return None
    return int.from_bytes(raw[7 * 32 : 8 * 32], "big")


def _balance_of(reader, *, token: str, account: str) -> int | None:
    if not hasattr(reader, "call"):
        return None
    try:
        raw = bytes(
            reader.call(account, token, _encode(_erc20, "balanceOf", [account]))
        )
    except Exception:
        return None
    return int.from_bytes(raw[-32:], "big") if raw else None


def _pool_tokens(pool: dict) -> tuple[str, str]:
    try:
        return (
            Web3.to_checksum_address((pool.get("token0") or {}).get("id")),
            Web3.to_checksum_address((pool.get("token1") or {}).get("id")),
        )
    except (TypeError, ValueError):
        raise MigrationRefused(
            f"destination pool {pool.get('id')!r} does not name both of its tokens as "
            "addresses, so nothing can be routed into it"
        ) from None


def match_current_pool(position: dict, universe) -> dict | None:
    """The explorer row for the pool this position is already in, or nothing.

    Matched on both token addresses and the fee tier rather than on a pool id the caller
    supplied, so the current rate cannot be quoted against a pool the position is not in.
    A position whose pool did not clear the eligible set has no row here and the
    disclosure says the current rate is unavailable rather than reporting it as zero.
    """
    want = {str(position["token0"]).lower(), str(position["token1"]).lower()}
    for row in universe.included:
        try:
            sides = {
                str((row.get("token0") or {}).get("id")).lower(),
                str((row.get("token1") or {}).get("id")).lower(),
            }
        except AttributeError:
            continue
        if sides == want and int(row.get("feeTier") or 0) == int(position["fee"]):
            return row
    return None


def plan_full_route(
    current_position: dict,
    destination_pool: dict,
    *,
    universe,
    reader,
    owner: str,
    session: str,
    position_size_usd: float,
    switching_cost_usd: float,
    horizon_days: int = HORIZON_DAYS,
    max_slippage_bps: int = 50,
    band_width_ticks: int = 1_000,
    now: int,
) -> MigrationPlan:
    """The ordered transactions that move one v3 position into another pool.

    `reader` supplies five reads and nothing else: `block_number()`, `pool_state(token0,
    token1, fee)`, `amounts_out(amount_in, route)`, `call(sender, target, calldata)` and
    `estimate_gas(sender, target, calldata)`. It is injected so a test can drive the whole
    route without a node, and so the failover the rest of Docket uses is the caller's
    choice rather than this module's.

    Four refusals before any bytes exist, and each one is a route that would otherwise
    fail somewhere less obvious:

    - a position the farm holds. `MasterChefV3` owns a staked NFT, so `approve` from the
      owner reverts and the whole route dies at step 1. Withdrawing from the farm first is
      not built here, and refusing plainly is better than a plan that cannot run.
    - a destination that is not in the eligible set the comparison was drawn from. The
      set is the allowlist, exactly as `plan_move` treats it.
    - an asset off the move allowlist on either side.
    - a fee tier whose spacing this build does not know.
    """
    owner = Web3.to_checksum_address(owner)
    session = Web3.to_checksum_address(session)
    if owner == session:
        raise MigrationRefused(
            "owner and session are the same address. The whole point of the session is "
            "that it holds a bounded authority the owner can revoke; one address cannot "
            "be both sides of that."
        )
    if current_position.get("staked"):
        raise MigrationRefused(
            f"position {current_position.get('token_id')} is staked in MasterChefV3, "
            "which owns the NFT. The owner cannot approve a token they do not hold, so "
            "this route would fail at its first call. Withdraw it from the farm first — "
            "that step is not built here."
        )
    token_id = int(current_position["token_id"])
    # Live, not remembered. A route that burned its position and was interrupted before
    # the mint has to be resumable, and the only thing that knows how far it got is the
    # chain: the caller's snapshot of the position is as old as whenever it was read.
    onchain = position_liquidity(reader, token_id, owner=owner)
    liquidity = int(current_position["liquidity"]) if onchain is None else onchain
    resuming = liquidity <= 0
    if resuming and onchain is None:
        raise MigrationRefused(
            f"position {token_id} holds no liquidity, so there is nothing to move"
        )

    destination_id = str(destination_pool.get("id") or "?")
    eligible = {str(row.get("id") or "?"): row for row in universe.included}
    if destination_id not in eligible:
        raise MigrationRefused(
            f"{destination_id} is not in the eligible set this comparison was drawn from "
            f"({len(eligible)} pools from {universe.source} at {universe.observed_at}), "
            "so it is not a destination this build routes to"
        )
    destination_pool = eligible[destination_id]
    dest0, dest1 = _pool_tokens(destination_pool)
    source0 = Web3.to_checksum_address(current_position["token0"])
    source1 = Web3.to_checksum_address(current_position["token1"])
    for name, token in (
        ("destination token0", dest0),
        ("destination token1", dest1),
        ("position token0", source0),
        ("position token1", source1),
    ):
        if token not in ROUTABLE_ASSETS:
            raise MigrationRefused(
                f"{name} {token} is not on this build's move allowlist of "
                f"{sorted(ROUTABLE_ASSETS)}"
            )
    fee = int(destination_pool.get("feeTier") or 0)
    if fee not in TICK_SPACINGS:
        raise MigrationRefused(
            f"destination pool {destination_id} reports fee tier {fee}, which is not one "
            f"of PancakeSwap V3's {sorted(TICK_SPACINGS)}. A band aligned to a guessed "
            "spacing is a mint that reverts."
        )
    if max_slippage_bps <= 0 or max_slippage_bps > 500:
        raise MigrationRefused(
            f"max_slippage_bps {max_slippage_bps} is outside 1..500; zero would refuse "
            "every fill and 500 is the intent ceiling this repository already enforces"
        )

    source_state = reader.pool_state(source0, source1, int(current_position["fee"]))
    dest_state = reader.pool_state(dest0, dest1, fee)
    for label, state in (("source", source_state), ("destination", dest_state)):
        if state.get("address") is None or state.get("sqrt_price_x96") is None:
            raise MigrationRefused(
                f"the {label} pool could not be read: the factory names no deployment for "
                "that pair and fee, so there is no price to size this route against"
            )
    block = int(dest_state["block_number"])
    observed_at = str(dest_state["observation_time"])

    # ---- step 1-3: out of the current position, or straight past it when it is out
    if resuming:
        # The position is already burned. Whatever the collect paid out is sitting in the
        # session, so the route continues from what the session actually holds rather than
        # from what a withdrawal was going to produce. Balances, not arithmetic: after an
        # interrupted run the two are not the same number.
        removed0 = _balance_of(reader, token=source0, account=session) or 0
        removed1 = _balance_of(reader, token=source1, account=session) or 0
        floor0, floor1 = removed0, removed1
        if floor0 <= 0 and floor1 <= 0:
            raise MigrationRefused(
                f"position {token_id} holds no liquidity and the session holds neither of "
                "its tokens, so there is nothing left to move and nothing to resume from"
            )
    else:
        sqrt_lower = sqrt_ratio_x96_at_tick(int(current_position["tick_lower"]))
        sqrt_upper = sqrt_ratio_x96_at_tick(int(current_position["tick_upper"]))
        removed0, removed1 = amounts_for_liquidity(
            liquidity, int(source_state["sqrt_price_x96"]), sqrt_lower, sqrt_upper
        )
        floor0 = removed0 * (10_000 - max_slippage_bps) // 10_000
        floor1 = removed1 * (10_000 - max_slippage_bps) // 10_000
        if floor0 <= 0 and floor1 <= 0:
            raise MigrationRefused(
                f"position {token_id} prices to nothing on either side at the pool's "
                "current tick once slippage is allowed, so there is no minimum this "
                "withdrawal could insist on and it is refused rather than sent with zeros"
            )

    # The session's authority over the NFT is a precondition, not a step. Every call this
    # function returns is executed from the session key, so an owner-signed approval
    # sitting in the list would be signed by the session — which does not own the NFT, so
    # the call reverts and the route dies at what looks like its own first step. The
    # approval is read instead, and a session that has not been granted it is a refusal
    # naming exactly what the owner has to sign.
    approved = _nft_approval(reader, owner=owner, session=session, token_id=token_id)
    if not approved:
        raise NftApprovalRequired(
            f"the session {session} is not approved for position NFT {token_id}. The "
            "owner signs that approval themselves — it is the one authority the session "
            "cannot grant itself — and nothing in this route can run until they have",
            detail={
                "contract": NPM,
                "token_id": token_id,
                "session": session,
                "owner": owner,
                "function": SELECTORS["npm.approve"],
                "note": (
                    "approve(session, tokenId) on the position manager, scoped to this "
                    "one token id. setApprovalForAll would hand the session every "
                    "position the owner holds and is not what this route needs"
                ),
            },
        )

    calls: list[PreparedCall] = []

    def slot() -> int:
        """One deadline per call, each a window further out than the one before it.

        They are mined in order, so a later call carrying the earlier one's deadline is a
        call that expires while it is still waiting its turn — and an eight-call route
        sharing one ten-minute window is a route whose tail cannot land.
        """
        return now + DEADLINE_S * (len(calls) + 1)

    deadline = slot()
    if not resuming:
        decrease = _encode(
            _npm, "decreaseLiquidity", [(token_id, liquidity, floor0, floor1, deadline)]
        )
        calls.append(
            PreparedCall(
                to=NPM,
                data="0x" + decrease.hex(),
                value_atomic="0",
                gas_ceiling=GAS_CEILINGS["npm.decreaseLiquidity"],
                deadline=deadline,
                purpose=(
                    f"burn all {liquidity} liquidity of position {token_id}, insisting on "
                    f"at least {floor0} of token0 and {floor1} of token1 — the amounts "
                    f"the pool's own tick prices that liquidity at, less "
                    f"{max_slippage_bps}bps"
                ),
                simulation=_simulation(
                    reader,
                    sender=owner,
                    target=NPM,
                    calldata=decrease,
                    gas_ceiling=GAS_CEILINGS["npm.decreaseLiquidity"],
                    block=block,
                    observed_at=observed_at,
                    extra_checks=(
                        "simulated from the owner, who is authorised for this token id "
                        "in their own right; the session holds the same authority "
                        "through the approval this route required before building",
                    ),
                ),
            )
        )

    deadline = slot()
    collect = _encode(_npm, "collect", [(token_id, session, UINT128_MAX, UINT128_MAX)])
    if not resuming:
        calls.append(
            PreparedCall(
                to=NPM,
                data="0x" + collect.hex(),
                value_atomic="0",
                gas_ceiling=GAS_CEILINGS["npm.collect"],
                deadline=deadline,
                purpose=(
                    f"collect everything the position now owes — the burned liquidity and any "
                    f"fees it had accrued — to the session {session}, which is the account "
                    "that swaps, approves and mints next. Revoking the session sweeps whatever "
                    "is left of it back to the owner"
                ),
                simulation=_simulation(
                    reader,
                    sender=None,
                    target=NPM,
                    calldata=collect,
                    gas_ceiling=GAS_CEILINGS["npm.collect"],
                    block=block,
                    observed_at=observed_at,
                    deferred=(
                        "eth_call and eth_estimateGas: collect returns nothing until call 2 "
                        "has burned the liquidity into the manager's accounting",
                    ),
                ),
            )
        )

    # ---- step 4: swap legs
    tick_lower, tick_upper = align_band(
        int(dest_state["tick"]), band_width_ticks, TICK_SPACINGS[fee]
    )
    legs, holdings, leg_records = _swap_legs(
        {source0: floor0, source1: floor1},
        destination=(dest0, dest1),
        reader=reader,
        recipient=session,
        deadline=slot,
        max_slippage_bps=max_slippage_bps,
        block=block,
        observed_at=observed_at,
        dest_state=dest_state,
        band=(tick_lower, tick_upper),
        deferred=not resuming,
        calls=calls,
    )

    desired0 = holdings.get(dest0, 0)
    desired1 = holdings.get(dest1, 0)
    if desired0 <= 0 and desired1 <= 0:
        raise MigrationRefused(
            "after every leg this route holds nothing the destination pool takes, so "
            "there is no mint to make"
        )

    # ---- step 5: exact-amount approvals
    for token, amount in ((dest0, desired0), (dest1, desired1)):
        if amount <= 0:
            continue
        deadline = slot()
        approve = _encode(_erc20, "approve", [NPM, amount])
        calls.append(
            PreparedCall(
                to=token,
                data="0x" + approve.hex(),
                value_atomic="0",
                gas_ceiling=GAS_CEILINGS["erc20.approve"],
                deadline=deadline,
                purpose=(
                    f"approve the position manager for exactly {amount} of {token} — the "
                    "amount the mint below pulls, and not one wei more. Never unlimited"
                ),
                simulation=_simulation(
                    reader,
                    sender=session,
                    target=token,
                    calldata=approve,
                    gas_ceiling=GAS_CEILINGS["erc20.approve"],
                    block=block,
                    observed_at=observed_at,
                    extra_checks=(
                        "an ERC-20 approval sets an allowance and needs no balance, so "
                        "this is a live check rather than a deferred one",
                    ),
                ),
            )
        )

    # ---- step 6: mint
    deadline = slot()
    min0 = desired0 * (10_000 - max_slippage_bps) // 10_000
    min1 = desired1 * (10_000 - max_slippage_bps) // 10_000
    mint = _encode(
        _npm,
        "mint",
        [
            (
                dest0,
                dest1,
                fee,
                tick_lower,
                tick_upper,
                desired0,
                desired1,
                min0,
                min1,
                owner,
                deadline,
            )
        ],
    )
    calls.append(
        PreparedCall(
            to=NPM,
            data="0x" + mint.hex(),
            value_atomic="0",
            gas_ceiling=GAS_CEILINGS["npm.mint"],
            deadline=deadline,
            purpose=(
                f"mint into {destination_id} over ticks [{tick_lower}, {tick_upper}] — "
                f"{band_width_ticks} either side of the pool's tick {dest_state['tick']}, "
                f"aligned outward to its spacing of {TICK_SPACINGS[fee]} — with the new "
                f"NFT going to the OWNER {owner}, not the session. Revoking the session "
                "cannot strand a position it never held"
            ),
            simulation=_simulation(
                reader,
                sender=None,
                target=NPM,
                calldata=mint,
                gas_ceiling=GAS_CEILINGS["npm.mint"],
                block=block,
                observed_at=observed_at,
                deferred=(
                    "eth_call and eth_estimateGas: the session holds neither token and "
                    "has granted no allowance until calls 3 to 5 have landed",
                ),
            ),
        )
    )

    verification = ReadSpec(
        target=NPM,
        data="0x" + _encode(_npm, "positions", [0]).hex(),
        function=SELECTORS["npm.positions"],
        identified_by=(
            f"the new token id is topics[1] of the IncreaseLiquidity log "
            f"({INCREASE_LIQUIDITY_TOPIC} in topics[0]) emitted by the position manager "
            "in the mint's own receipt — the event's one indexed parameter. The same id "
            f"is topics[3] of the ERC-721 Transfer log ({TRANSFER_TOPIC} in topics[0]) "
            f"from {ZERO_ADDRESS} to the owner, where from and to take topics[1] and "
            "topics[2]"
        ),
        note=(
            "The calldata above carries token id 0 as a placeholder. Substitute the id "
            "read off the mint receipt into its last 32 bytes and eth_call it against the "
            "position manager: token0, token1, fee, tickLower, tickUpper and liquidity "
            "come back, and they either match this plan's destination and band or they "
            "do not. That check needs nothing from Docket"
        ),
    )

    # What actually leaves the session over the batch. A token that is both swapped out of
    # and minted with is counted in both, because both amounts really do leave — and a
    # spend cap is a cap on what leaves, not on the net position change.
    spend: dict[str, int] = {}
    for leg in leg_records:
        spend[leg["token_in"]] = spend.get(leg["token_in"], 0) + int(leg["amount_in"])
    for token, amount in ((dest0, desired0), (dest1, desired1)):
        if amount > 0:
            spend[token] = spend.get(token, 0) + amount
    session_spend = {token: str(amount) for token, amount in sorted(spend.items())}
    # One mapping per call, in batch order, because the policy engine charges per call
    # and not per batch: handing it the batch total once and applying it to all eight
    # calls charged eight times the real spend against the session cap.
    by_call = _spend_by_call(calls, legs=leg_records, mint=(dest0, desired0, dest1, desired1))

    disclosure = _disclosure(
        current_position=current_position,
        destination_pool=destination_pool,
        universe=universe,
        calls=calls,
        position_size_usd=position_size_usd,
        switching_cost_usd=switching_cost_usd,
        horizon_days=horizon_days,
        max_slippage_bps=max_slippage_bps,
        tick_lower=tick_lower,
        tick_upper=tick_upper,
        dest_state=dest_state,
        removed=(removed0, removed1),
        floors=(floor0, floor1),
        desired=(desired0, desired1),
        legs=leg_records,
        session_spend=session_spend,
        resuming=resuming,
        owner=owner,
        session=session,
    )
    return MigrationPlan(
        calls=tuple(calls),
        session_spend=session_spend,
        session_spend_by_call=by_call,
        verification=verification,
        disclosure=disclosure,
        source_token_id=token_id,
        destination_pool=destination_id,
        tick_lower=tick_lower,
        tick_upper=tick_upper,
        evidence={
            "block": block,
            "observed_at": observed_at,
            "source_pool": source_state["address"],
            "destination_pool_address": dest_state["address"],
            "policy_version": POLICY_VERSION,
            "universe": universe.as_record(),
        },
    )


def _encode(contract, name: str, args: list) -> bytes:
    return bytes.fromhex(contract.encode_abi(name, args=args)[2:])


def _swap_legs(
    holdings: dict,
    *,
    destination: tuple[str, str],
    reader,
    recipient: str,
    deadline,
    max_slippage_bps: int,
    block: int,
    observed_at: str,
    dest_state: dict,
    band: tuple[int, int],
    deferred: bool,
    calls: list,
) -> tuple[list[PreparedCall], dict, list[dict]]:
    """At most three legs: one per stranded token, then one to reach the band's ratio.

    Every leg is quoted live and floored, and the holdings carried forward are the
    floors rather than the quotes. Planning on the floor is what makes the mint below
    safe: whatever the legs actually return is at least this, so the mint asks for an
    amount the session is certainly holding.

    `deadline` is the caller's slot function rather than a number, and legs are appended
    to the caller's own list, so each one lands in the batch position it will be mined
    in and takes the deadline that position earns. `deferred` says whether the session is
    still waiting on a collect for the tokens these legs spend: when it is not — a
    resumed route, where the session already holds them — the legs are estimated live.
    """
    dest0, dest1 = destination
    records: list[dict] = []
    working = dict(holdings)

    for token in list(working):
        if token in (dest0, dest1) or working[token] <= 0:
            continue
        call, gained, record = _one_leg(
            token,
            dest0,
            working[token],
            reader=reader,
            recipient=recipient,
            deadline=deadline(),
            max_slippage_bps=max_slippage_bps,
            block=block,
            observed_at=observed_at,
            deferred=deferred,
            sender=None if deferred else recipient,
            why=(
                f"{token} is neither side of the destination pool, so the whole holding "
                f"is routed into {dest0} before the balance is struck"
            ),
        )
        calls.append(call)
        records.append(record)
        working[token] = 0
        working[dest0] = working.get(dest0, 0) + gained

    have0 = working.get(dest0, 0)
    have1 = working.get(dest1, 0)
    target0, target1 = _band_split(
        have0, have1, sqrt_price=int(dest_state["sqrt_price_x96"]), band=band
    )
    if have0 > target0 and target1 > have1:
        amount = have0 - target0
        call, gained, record = _one_leg(
            dest0,
            dest1,
            amount,
            reader=reader,
            recipient=recipient,
            deadline=deadline(),
            max_slippage_bps=max_slippage_bps,
            block=block,
            observed_at=observed_at,
            deferred=deferred,
            sender=None if deferred else recipient,
            why=(
                "the destination band at its current tick needs more token1 than this "
                "route is holding, so the surplus token0 is swapped across"
            ),
        )
        calls.append(call)
        records.append(record)
        working[dest0] = target0
        working[dest1] = have1 + gained
    elif have1 > target1 and target0 > have0:
        amount = have1 - target1
        call, gained, record = _one_leg(
            dest1,
            dest0,
            amount,
            reader=reader,
            recipient=recipient,
            deadline=deadline(),
            max_slippage_bps=max_slippage_bps,
            block=block,
            observed_at=observed_at,
            deferred=deferred,
            sender=None if deferred else recipient,
            why=(
                "the destination band at its current tick needs more token0 than this "
                "route is holding, so the surplus token1 is swapped across"
            ),
        )
        calls.append(call)
        records.append(record)
        working[dest1] = target1
        working[dest0] = have0 + gained
    return calls, working, records


def _one_leg(
    token_in: str,
    token_out: str,
    amount: int,
    *,
    reader,
    recipient: str,
    deadline: int,
    max_slippage_bps: int,
    block: int,
    observed_at: str,
    deferred: bool,
    sender: str | None,
    why: str,
) -> tuple[PreparedCall, int, dict]:
    route = (token_in, token_out)
    quoted = int(reader.amounts_out(amount, route)[-1])
    min_output = quoted * (10_000 - max_slippage_bps) // 10_000
    if min_output <= 0:
        raise MigrationRefused(
            f"the router quotes {quoted} out for {amount} of {token_in} into {token_out}, "
            f"which leaves no floor at all once {max_slippage_bps}bps of slippage is "
            "allowed. No leg is sent without a floor"
        )
    calldata = swap_calldata(
        amount_in=amount,
        min_output=min_output,
        route=route,
        recipient=recipient,
        deadline=deadline,
    )
    call = PreparedCall(
        to=PANCAKE_V2_ROUTER,
        data="0x" + calldata.hex(),
        value_atomic="0",
        gas_ceiling=GAS_CEILINGS["swap"],
        deadline=deadline,
        purpose=f"swap {amount} of {token_in} into {token_out}: {why}",
        simulation=_simulation(
            reader,
            sender=sender,
            target=PANCAKE_V2_ROUTER,
            calldata=calldata,
            gas_ceiling=GAS_CEILINGS["swap"],
            block=block,
            observed_at=observed_at,
            deferred=(
                (
                    "eth_call and eth_estimateGas: the session holds this token only "
                    "after the collect above has landed",
                )
                if deferred
                else ()
            ),
            extra_checks=(
                f"router.getAmountsOut quoted {quoted} out for {amount} in, floored at "
                f"{min_output}",
            ),
        ),
    )
    return (
        call,
        min_output,
        {
            "token_in": token_in,
            "token_out": token_out,
            "amount_in": str(amount),
            "quoted_out": str(quoted),
            "min_out": str(min_output),
            "reason": why,
        },
    )


def _band_split(
    have0: int, have1: int, *, sqrt_price: int, band: tuple[int, int]
) -> tuple[int, int]:
    """How the total should be split between the two tokens for this band.

    Both sides are valued in token1 at the pool's own current price, which is the only
    price this function has and is the one the mint will be made at. The split is the
    ratio the band's liquidity formula asks for at that price; a band entirely above the
    price wants token0 alone and one entirely below wants token1 alone, and both come out
    of the same arithmetic rather than as special cases.
    """
    lower, upper = band
    sqrt_a = sqrt_ratio_x96_at_tick(lower)
    sqrt_b = sqrt_ratio_x96_at_tick(upper)
    unit0, unit1 = amounts_for_liquidity(Q96, sqrt_price, sqrt_a, sqrt_b)
    # Everything in token1 units: value(token0) = amount0 * price, price = (sqrtP/Q96)**2.
    price_num = sqrt_price * sqrt_price
    total = have0 * price_num // (Q96 * Q96) + have1
    unit0_value = unit0 * price_num // (Q96 * Q96)
    denominator = unit0_value + unit1
    if denominator <= 0 or total <= 0:
        return have0, have1
    target1 = total * unit1 // denominator
    target0_value = total - target1
    target0 = target0_value * Q96 * Q96 // price_num if price_num > 0 else 0
    return target0, target1


def _spend_by_call(calls, *, legs: list[dict], mint: tuple) -> tuple[dict, ...]:
    """What each call in the batch spends out of the session, in batch order.

    Derived from what this module built rather than from the calldata, because this is
    the side that knows: a swap spends its own input, a mint pulls both desired amounts,
    and everything else — the withdrawal, the collect, the allowances — moves nothing out.
    An approval is authorisation and not a spend; charging one would bill the session
    twice for the same tokens, once for permitting the mint and once for the mint.
    """
    dest0, desired0, dest1, desired1 = mint
    remaining = list(legs)
    out: list[dict] = []
    for call in calls:
        if call.to == PANCAKE_V2_ROUTER and remaining:
            leg = remaining.pop(0)
            out.append({leg["token_in"]: leg["amount_in"]})
        elif call.selector == "0x88316456":
            out.append(
                {
                    token: str(amount)
                    for token, amount in ((dest0, desired0), (dest1, desired1))
                    if amount > 0
                }
            )
        else:
            out.append({})
    return tuple(out)


def _disclosure(
    *,
    current_position: dict,
    destination_pool: dict,
    universe,
    calls: list[PreparedCall],
    position_size_usd: float,
    switching_cost_usd: float,
    horizon_days: int,
    max_slippage_bps: int,
    tick_lower: int,
    tick_upper: int,
    dest_state: dict,
    removed: tuple[int, int],
    floors: tuple[int, int],
    desired: tuple[int, int],
    legs: list[dict],
    session_spend: dict,
    resuming: bool,
    owner: str,
    session: str,
) -> dict:
    """Everything a reader needs to disagree with this route before signing any of it."""
    current_row = match_current_pool(current_position, universe)
    baseline = (
        net_fee_apr(current_row)
        if current_row is not None and _quotable(current_row)
        else None
    )
    proposed = _candidate(destination_pool, baseline)
    current = (
        _candidate(current_row, baseline)
        if current_row is not None
        else Candidate(
            pool_id="unavailable",
            pair="?/?",
            fee_tier=int(current_position["fee"]),
            net_fee_apr=0.0,
            gross_fee_apr=0.0,
            fee_usd_24h=0.0,
            protocol_fee_usd_24h=0.0,
            tvl_usd=0.0,
            volume_usd_24h=0.0,
            turnover=0.0,
            net_fee_apr_delta=None,
        )
    )
    payback = break_even(
        current,
        proposed,
        position_size_usd=position_size_usd,
        switching_cost_usd=switching_cost_usd,
        horizon_days=horizon_days,
    )
    estimated = [
        call.simulation["gas_estimate"]
        for call in calls
        if call.simulation["gas_estimate"] is not None
    ]
    unestimated = len(calls) - len(estimated)
    tvl = float(destination_pool.get("tvlUSD") or 0)
    share = position_size_usd / tvl if tvl > 0 else None
    return {
        "current_apr": {
            "pool_id": current.pool_id,
            "net_fee_apr": None if current_row is None else current.net_fee_apr,
            "gross_fee_apr": None if current_row is None else current.gross_fee_apr,
            "unavailable_reason": (
                None
                if current_row is not None
                else (
                    "the pool this position sits in is not in the eligible set, so no "
                    "rate for it was observed and none is invented here"
                )
            ),
        },
        "proposed_apr": {
            "pool_id": proposed.pool_id,
            "net_fee_apr": proposed.net_fee_apr,
            "gross_fee_apr": proposed.gross_fee_apr,
            "net_vs_gross": NET_VS_GROSS,
        },
        "rate_window": RATE_WINDOW,
        "rate_denominator": RATE_DENOMINATOR,
        "data_timestamp": {
            "pool_statistics_observed_at": universe.observed_at,
            "pool_statistics_source": universe.source,
            "chain_observed_at": dest_state["observation_time"],
            "chain_block": dest_state["block_number"],
        },
        "liquidity_and_capacity": {
            "destination_tvl_usd": tvl,
            "position_size_usd": position_size_usd,
            "share_of_pool": share,
            "destination_volume_usd_24h": proposed.volume_usd_24h,
            "turnover": proposed.turnover,
            "note": (
                "share_of_pool is this position against the destination's whole reported "
                "TVL. A position that is a large fraction of a pool earns a large "
                "fraction of its fees and also moves its price when it is opened; both "
                "effects are outside the rates above"
            ),
        },
        "protocol_risk": PROTOCOL_RISK,
        "estimated_gas": {
            "sum_of_estimates": sum(estimated),
            "calls_estimated": len(estimated),
            "calls_not_estimated": unestimated,
            "note": (
                "the sum of the gas estimates that could be taken at this block. Calls "
                "whose preconditions are created by earlier calls in this route cannot be "
                "estimated before those land, and each says so on its own simulation "
                "record; their ceilings are published beside them instead"
            ),
            # Keyed by batch position. Truncating the purpose collided the moment two
            # calls opened with the same words — the two exact-amount approvals do — and
            # a collision silently dropped one of them from the published ceilings.
            "ceilings": {
                str(index): {"to": call.to, "gas_ceiling": call.gas_ceiling}
                for index, call in enumerate(calls)
            },
        },
        "nft_approval_precondition": (
            "The session must already be approved for this position NFT before any of "
            "this runs. That approval is the owner's own signature and is not in the "
            "sequence below: every call here is broadcast from the session key, and a "
            "session cannot approve itself for a token it does not own. This route reads "
            "the approval before it builds and refuses to build without it."
        ),
        "resumed_from_chain": resuming,
        "resume_note": (
            "the position was already burned when this route was planned, so the "
            "withdrawal steps are absent and the amounts below are the session's own "
            "balances rather than a projection of what a withdrawal would return"
            if resuming
            else "the position still holds liquidity, so this route starts by withdrawing it"
        ),
        "session_spend_atomic": dict(session_spend),
        "session_spend_note": (
            "gross atomic outflow from the session over the whole batch: every swap "
            "leg's input plus what the mint pulls. A token that is both swapped out of "
            "and minted with is counted twice, because both amounts really do leave the "
            "session — and a spend cap is a cap on what leaves, not on the net change"
        ),
        "slippage": {
            "max_slippage_bps": max_slippage_bps,
            "applied_to": (
                "the withdrawal minimums, every swap leg's floor, and the mint's "
                "amount0Min/amount1Min. No step in this route carries a zero minimum"
            ),
            "legs": legs,
        },
        "expected_payback_period_days": payback["days_to_recover"],
        "minimum_holding_period_days": payback["days_to_recover"],
        "holding_period_note": (
            "the minimum holding period is the payback period and is the same number: "
            "leaving before it means the switching cost was never recovered, so moving "
            "cost more than staying"
        ),
        "break_even": payback,
        "break_even_method": BREAK_EVEN_METHOD.format(horizon=horizon_days),
        "cost_covers": COST_COVERS,
        "transaction_sequence": [
            {"step": index + 1, "to": call.to, "purpose": call.purpose}
            for index, call in enumerate(calls)
        ],
        "position": {
            "token_id": int(current_position["token_id"]),
            "removed_amount0": str(removed[0]),
            "removed_amount1": str(removed[1]),
            "withdrawal_floor0": str(floors[0]),
            "withdrawal_floor1": str(floors[1]),
            "mint_amount0_desired": str(desired[0]),
            "mint_amount1_desired": str(desired[1]),
            "destination_tick": dest_state["tick"],
            "tick_lower": tick_lower,
            "tick_upper": tick_upper,
            "owner_receives_the_new_position": owner,
            "session_holds_the_funds_in_transit": session,
        },
        "assumptions_that_could_invalidate_this": list(ASSUMPTIONS),
    }


class BscMigrationReader:
    """The five reads `plan_full_route` needs, over the failover the rest of Docket uses.

    Composed rather than inherited: `PositionReader` already knows how to find a pool and
    read its slot0 through per-call failover, and `BscQuoteReader` already knows how to
    quote the V2 router. Reimplementing either here would be the second copy that goes
    stale, which is the reason `escrow/chain.py::Rpc` exists in the first place.
    """

    def __init__(self, positions=None, quotes=None, rpc=None) -> None:
        from ...escrow.chain import Rpc
        from ...execution.simulate import BscQuoteReader
        from ..pancake.positions import PositionReader

        self._rpc = rpc if rpc is not None else Rpc()
        self._positions = positions if positions is not None else PositionReader()
        self._quotes = quotes if quotes is not None else BscQuoteReader(rpc=self._rpc)

    def block_number(self) -> int:
        return self._quotes.block_number()

    def amounts_out(self, amount_in: int, route) -> list[int]:
        return self._quotes.amounts_out(amount_in, route)

    def estimate_gas(self, sender: str, target: str, calldata: bytes) -> int:
        return self._quotes.estimate_gas(sender, target, calldata)

    def pool_state(self, token0: str, token1: str, fee: int) -> dict:
        return self._positions.pool_state(token0, token1, fee)

    def call(self, sender: str, target: str, calldata: bytes) -> bytes:
        return self._rpc(
            lambda w3: w3.eth.call(
                {
                    "from": Web3.to_checksum_address(sender),
                    "to": Web3.to_checksum_address(target),
                    "data": calldata,
                }
            )
        )
