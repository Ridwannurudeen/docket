"""The Range Keeper: when a PancakeSwap v3 range is worth resetting, and the exact calls.

The Range Doctor reads a position and states what it read. The Keeper is the same
arithmetic asked a different question — not "where does this position sit" but "has it
sat there long enough, and does resetting it pay for itself" — and it answers with
calldata rather than a link. Every number `diagnose` produced is reused rather than
recomputed: a keeper that derived its own fee rate would eventually disagree with the
doctor about the same position, and the day it did is the day neither could be trusted.

**Nothing in this module signs or sends.** It builds bytes and returns them. There is no
key here, no signer, no submitter, and no method that puts a transaction on a wire —
`docket/sessions/executor.py` is the only thing in Docket that does, and it re-simulates
every call at send time rather than trusting a preflight taken at evaluation.

**Every call here is one a session may send, and the batch contains nothing else.** The
ERC-721 approval a session needs over the position NFT can only be made by the NFT's
holder, so it is never in `prepared`: the executor reads `getApproved` and
`isApprovedForAll` before building anything and refuses with the approval the owner has to
make. A list of calls that mixed the two would be handed to a loop that sends all of them
from the session, and the owner's would revert.

**The new position NFT goes to the owner.** `mint`'s recipient is the wallet that owns the
old one, never Docket and never the session. The session is the recipient of `collect` and
of the swap, because the tokens have to pass through the address that funds the mint —
that transit is the only moment Docket's session touches the assets, and what bounds it is
the exact approvals below plus the session policy `docket/sessions/policy.py` applies
before every send. Fee residue swept by `collect` and any surplus the swap leaves over the
mint's floor stay in the session until the owner revokes it, which sweeps them back.

**A recentred range needs a swap, and the batch contains it.** A position that left its
range holds one token only: below the range it is all token0, above it all token1. A range
drawn around the current tick needs both sides, so part of the inventory has to be traded
between the `collect` and the `mint`. That leg is built here, through the same
PancakeSwap V2 router and the same `swap_calldata` builder the rest of Docket's execution
plane uses (`docket/execution/simulate.py`) rather than a second copy of either. Its
`amountOutMin` is the caller's live router quote less the policy's slippage bound, and the
mint is sized against that floor — so the amounts the mint asks the position manager to
pull are amounts the swap is contractually obliged to have delivered.

`swap_plan` decides whether a leg is needed at all and which way it runs. A position whose
two sides are already within the slippage bound of equal value needs no trade, and none is
emitted; the reason travels in the plan either way.

**Ticks are integers here, always.** `tickmath` is float64 and says of itself that it
must never be used to build a transaction. Nothing below calls it: the new bounds are
computed by integer division against the pool's own tick spacing, and the spacing comes
from the fee tier through a map read off the v3 factory rather than transcribed from
documentation.
"""

from dataclasses import dataclass
from datetime import datetime

from web3 import Web3

from ...jobs.executors.base import PreparedCall
from ...execution.simulate import PANCAKE_V2_ROUTER, swap_calldata
from ...jobs.executors.bounds import APPROVE_ABI, BSC_CHAIN_ID, parse_expiry
from . import doctor
from .positions import NPM

# PancakeSwap v3 fee tier to tick spacing, read from the v3 factory's own
# `feeAmountTickSpacing(uint24)` at 0x0BFbCF9fa4f9C56B0F40a671Ad40E0805A091865 on BSC
# mainnet at block 119,695,563 (chain 56, 2026-09-03). The factory answered 0 for 3000
# and 20000 — Uniswap's 0.3% tier is not enabled here, and a position cannot exist in a
# tier the factory never opened, so an unknown fee is refused rather than guessed at.
TICK_SPACING_BY_FEE = {100: 1, 500: 10, 2500: 50, 10000: 200}
# The v3 tick bounds. A range drawn past either of them is a mint that reverts.
MIN_TICK = -887272
MAX_TICK = 887272
MAX_UINT128 = 2**128 - 1

# Gas ceilings, not estimates, in the sense `venus/guard.py` uses the word: each is above
# what the call has been observed to cost, so a cost projection built from them overstates
# the cost of acting. Overstating is the conservative direction here — it makes the
# benefit test harder to pass, never easier.
DECREASE_LIQUIDITY_GAS = 250_000
COLLECT_GAS = 200_000
MINT_GAS = 600_000
APPROVE_GAS = 60_000
SWAP_GAS = 300_000
# PancakeSwap V2 charges 25bps on every exact-input swap. The v3 pool the position lives
# in charges its own fee tier instead, which is why the two venues are costed apart: a
# reset priced at a 0.01% tier and then executed on V2 was costed at a fortieth of what it
# paid.
V2_FEE_BPS = 25
# Everything a session sends for one reset: the three position-manager calls, the router
# leg, and the three ERC-20 approvals in front of them. The owner-signed ERC-721 approval
# is not counted — the owner pays for it from their own wallet, and charging it to the
# session's cost model would double-count it.
REBALANCE_GAS_UNITS = (
    DECREASE_LIQUIDITY_GAS + COLLECT_GAS + MINT_GAS + SWAP_GAS + 3 * APPROVE_GAS
)
# A v3 pool stores sqrt(price) as Q64.96, so squaring one costs 2**192 of scale.
Q192 = 2**192

# PancakeSwap's v3 SwapRouter on BSC mainnet, 12,154 bytes of code at block 119,728,495.
# Identified rather than assumed: `factory()` answers 0x0BFbCF9f…091865, which is the same
# v3 factory `positions.py` reads pools from, and `WETH9()` answers WBNB.
V3_SWAP_ROUTER = Web3.to_checksum_address("0x1b81D678ffb9C0263b24A97847620C99d213eB14")
# The deployed router carries Uniswap's shape of the struct, with the deadline INSIDE it,
# rather than PancakeSwap's SmartRouter shape which drops the deadline and hashes to
# 0x04e45aaf. Both were checked against the runtime bytecode at that block and only this
# one is present here; encoding the other would name a function this router does not have.
EXACT_INPUT_SINGLE_SIGNATURE = (
    "exactInputSingle((address,address,uint24,address,uint256,uint256,uint256,uint160))"
)
# No price limit: the floor is `amountOutMinimum`, which the router enforces by reverting.
# A second bound expressed as a sqrt price would have to agree with the first, and the one
# that disagreed would be the one nobody read.
NO_SQRT_PRICE_LIMIT = 0
V3_ROUTER_ABI = [
    {
        "name": "exactInputSingle",
        "type": "function",
        "stateMutability": "payable",
        "inputs": [
            {
                "name": "params",
                "type": "tuple",
                "components": [
                    {"name": "tokenIn", "type": "address"},
                    {"name": "tokenOut", "type": "address"},
                    {"name": "fee", "type": "uint24"},
                    {"name": "recipient", "type": "address"},
                    {"name": "deadline", "type": "uint256"},
                    {"name": "amountIn", "type": "uint256"},
                    {"name": "amountOutMinimum", "type": "uint256"},
                    {"name": "sqrtPriceLimitX96", "type": "uint160"},
                ],
            }
        ],
        "outputs": [{"name": "amountOut", "type": "uint256"}],
    }
]
# The two reads that say whether the session may already touch this NFT. Checked before a
# batch is built rather than approved inside it: an ERC-721 approval can only be made by
# the token's holder, so it is never the session's to send and must not travel in a list
# of calls a session executes.
NPM_APPROVAL_ABI = [
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
]
# How far ahead the fee recovery is projected. Thirty days is the catalogue's own default
# decision horizon for the Range Doctor's break-even, so the two answers are commensurable.
# It is stated in the evidence rather than left implicit: a recovery figure without its
# window is not a figure.
PROJECTION_DAYS = 30
# What fraction of the position has to change sides to fund a range drawn around the
# current tick. A position that left its range holds one token only, and a symmetric band
# needs both, so half of it is traded. An approximation, and labelled as one.
SWAP_FRACTION = 0.5
WEI_PER_BNB = 10**18

PROJECTION_LIMITATION = (
    "The projected recovery applies the pool's observed net 24h fee rate to a "
    "caller-declared notional over a fixed window. It is not a forecast, not this "
    f"position's measured earnings, and not a claim that the {PROJECTION_DAYS}-day window "
    "will look like the 24 hours it was annualised from. A v3 position earns in proportion "
    "to its share of the liquidity active at the traded tick, which no read here measures, "
    "so a wide range earns less than the pool rate and a tight one earns more."
)
COST_LIMITATION = (
    "The execution cost is gas ceilings priced at the gas price supplied to this "
    "evaluation and converted at a caller-declared BNB price, plus a swap charge modelled "
    "as the pool's own fee tier and the policy's slippage bound applied to half the "
    "notional. It excludes the impermanent loss that closing the old position converts "
    "from unrealised into realised, and it excludes any price impact beyond the slippage "
    "bound."
)
SWAP_NOTE = (
    "A range drawn around the current tick holds both tokens and a position that left its "
    "range holds one, so the inventory is rebalanced to equal value by one exact-input "
    "swap between the collect and the mint. The leg is part of the batch. The venue is "
    "chosen rather than assumed: PancakeSwap V2 is quoted first and used only when its "
    "quote is within the policy's slippage bound of the price the position's own v3 pool "
    "is trading at, because a pair that exists on V2 in name can be thin enough there to "
    "lose most of a position. Where V2 falls short the leg is routed through PancakeSwap's "
    "v3 SwapRouter into the very pool the position was minted in. Either way the floor is "
    "amountOutMinimum, which the router enforces by reverting, and the mint is sized "
    "against that floor rather than against a quote — so every amount the position manager "
    "is asked to pull is one the swap was obliged to deliver."
)

# Minimal fragments rather than the full periphery artifact, the way `positions.py` writes
# them. Every signature below was checked against the deployed NonfungiblePositionManager
# 0x46A15B0b27311cedF172AB29E4f4766fbE7F4364 on BSC mainnet at block 119,695,550 by
# searching its runtime bytecode for the four-byte selector of the canonical signature; the
# selectors are re-derived from these fragments by keccak in `tests/test_pancake_keeper.py`
# so a typo in a type cannot survive.
#
#   decreaseLiquidity((uint256,uint128,uint256,uint256,uint256))  0x0c49ccbe
#   collect((uint256,address,uint128,uint128))                    0xfc6f7865
#   mint((address,address,uint24,int24,int24,uint256,uint256,
#         uint256,uint256,address,uint256))                       0x88316456
#   approve(address,uint256)                                      0x095ea7b3
#
# The signatures are PancakeSwap v3 periphery's `INonfungiblePositionManager`, which is
# Uniswap v3 periphery's interface unchanged in these three members.
NPM_WRITE_ABI = [
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
]
# `approve(address,uint256)` is one signature and two different functions. On an ERC-20 the
# second argument is an amount; on the position manager, which is an ERC-721, it is a token
# id. They share the selector 0x095ea7b3, so a policy that allowlists a selector without
# also pinning the contract it may be sent to has allowed both. Every check in this package
# that reads a selector reads the pair.
DECREASE_SIGNATURE = "decreaseLiquidity((uint256,uint128,uint256,uint256,uint256))"
COLLECT_SIGNATURE = "collect((uint256,address,uint128,uint128))"
MINT_SIGNATURE = (
    "mint((address,address,uint24,int24,int24,uint256,uint256,uint256,uint256,"
    "address,uint256))"
)

# Public: the rebalancing executor builds a zero-minimum decreaseLiquidity probe from
# the same fragments, so the bytes it quotes with and the bytes it offers are encoded
# by one encoder rather than two.
npm_encoder = Web3().eth.contract(abi=NPM_WRITE_ABI)
npm_approval_reader = Web3().eth.contract(abi=NPM_APPROVAL_ABI)
v3_router_encoder = Web3().eth.contract(abi=V3_ROUTER_ABI)
_erc20_encoder = Web3().eth.contract(abi=APPROVE_ABI)


def selector(signature: str) -> str:
    """The four-byte selector of a canonical signature, `0x`-prefixed."""
    return "0x" + Web3.keccak(text=signature)[:4].hex()


@dataclass(frozen=True)
class KeeperPolicy:
    """What the owner permitted before anybody looked at the position.

    `band_width_ticks` is the half-width of the new range in ticks, so the band spans
    twice it. `None` keeps the width the position already has, which is the answer that
    changes least about a position whose owner chose its width deliberately.
    """

    out_of_range_minutes: int
    min_net_benefit_multiple: float
    max_slippage_bps: int
    max_gas_price_wei: int
    max_notional_usd: float
    band_width_ticks: int | None
    expires_at: str

    def validate(self) -> None:
        if not isinstance(self.out_of_range_minutes, int) or isinstance(
            self.out_of_range_minutes, bool
        ):
            raise ValueError("out_of_range_minutes must be a whole number of minutes")
        if self.out_of_range_minutes <= 0:
            raise ValueError(
                "out_of_range_minutes must be positive: a threshold of zero fires on a "
                "position that has been outside its range for no observed time at all, "
                "which is ordinary price movement rather than a condition"
            )
        if (
            not isinstance(self.min_net_benefit_multiple, (int, float))
            or isinstance(self.min_net_benefit_multiple, bool)
            or self.min_net_benefit_multiple < 1
        ):
            raise ValueError(
                "min_net_benefit_multiple must be at least 1: below it the policy "
                "authorises a reset whose projected recovery does not cover its own cost"
            )
        if (
            not isinstance(self.max_slippage_bps, int)
            or isinstance(self.max_slippage_bps, bool)
            or not 0 < self.max_slippage_bps <= 1000
        ):
            raise ValueError(
                "max_slippage_bps must be between 1 and 1000: zero would floor every "
                "minimum at the quote itself and revert on the first wei of movement, and "
                "more than 10% is a bound that bounds nothing"
            )
        if (
            not isinstance(self.max_gas_price_wei, int)
            or isinstance(self.max_gas_price_wei, bool)
            or self.max_gas_price_wei <= 0
        ):
            raise ValueError("max_gas_price_wei must be a positive number of wei")
        if (
            not isinstance(self.max_notional_usd, (int, float))
            or isinstance(self.max_notional_usd, bool)
            or self.max_notional_usd <= 0
        ):
            raise ValueError("max_notional_usd must be a positive USD figure")
        if self.band_width_ticks is not None and (
            not isinstance(self.band_width_ticks, int)
            or isinstance(self.band_width_ticks, bool)
            or self.band_width_ticks <= 0
        ):
            raise ValueError(
                "band_width_ticks must be a positive half-width in ticks, or None to keep "
                "the width the position already has"
            )
        parse_expiry(self.expires_at)

    def as_record(self) -> dict:
        return {
            "out_of_range_minutes": self.out_of_range_minutes,
            "min_net_benefit_multiple": self.min_net_benefit_multiple,
            "max_slippage_bps": self.max_slippage_bps,
            "max_gas_price_wei": str(self.max_gas_price_wei),
            "max_notional_usd": self.max_notional_usd,
            "band_width_ticks": self.band_width_ticks,
            "expires_at": self.expires_at,
        }


@dataclass(frozen=True)
class KeeperDecision:
    """What the keeper concluded, the range it would draw, and the arithmetic behind both.

    `new_tick_lower` and `new_tick_upper` are populated whenever a range could be drawn at
    all — including on an `alert`, so a reader can see the range that was refused rather
    than only that something was.
    """

    kind: str
    summary: str
    evidence: dict
    new_tick_lower: int | None
    new_tick_upper: int | None


def tick_spacing(fee: int) -> int:
    """The pool's tick spacing for a fee tier, or a refusal naming the tier."""
    spacing = TICK_SPACING_BY_FEE.get(int(fee))
    if spacing is None:
        raise ValueError(
            f"fee tier {fee} has no tick spacing in the map read from the v3 factory "
            f"({sorted(TICK_SPACING_BY_FEE)}); a range aligned to a guessed spacing is a "
            "mint that reverts"
        )
    return spacing


def align_range(centre: int, half_width: int, spacing: int) -> tuple[int, int]:
    """A band of `2 * half_width` ticks around `centre`, snapped outward to the spacing.

    Snapped outward rather than to the nearest tick so the band never comes back narrower
    than the caller asked for. Integer arithmetic throughout: Python's floor division
    floors towards negative infinity, which is what a tick below zero needs, and nothing
    here goes through `tickmath`, whose float path its own docstring bans from
    transaction sizing.
    """
    lower = ((centre - half_width) // spacing) * spacing
    upper = -((-(centre + half_width)) // spacing) * spacing
    # Clamped *inwards*: the nearest multiple of the spacing that is still a tick the pool
    # will hold. Snapping outward here — the right direction everywhere else in this
    # function — would put the bound one spacing past the end of the tick range and mint
    # against a range that cannot exist.
    lower = max(lower, -((-MIN_TICK) // spacing) * spacing)
    upper = min(upper, (MAX_TICK // spacing) * spacing)
    if upper <= lower:
        # Only reachable for a band pinned against a bound. One spacing is the narrowest
        # range the pool will hold.
        upper = lower + spacing
    return lower, upper


def out_of_range_minutes(
    history: list[dict], *, now: datetime, in_range: bool
) -> float:
    """How long the position has been observed outside its range, in minutes.

    Only observed time counts. `history` holds prior observations, each
    `{"observed_at": iso8601, "in_range": bool}`; the trailing run of out-of-range ones
    dates the departure, and the run stops at the first observation that saw the position
    inside. A position that was in range at the last observation and is outside now has
    been outside for no *observed* time, and this returns 0.0 rather than inventing a
    departure moment between two reads.
    """
    if in_range:
        return 0.0
    ordered = sorted(history, key=lambda entry: parse_expiry(entry["observed_at"]))
    since: datetime | None = None
    for entry in reversed(ordered):
        if entry.get("in_range"):
            break
        since = parse_expiry(entry["observed_at"])
    if since is None:
        return 0.0
    return max(0.0, (now - since).total_seconds() / 60.0)


def evaluate(
    position: dict,
    pool: dict,
    pool_stats: dict,
    policy: KeeperPolicy,
    *,
    history: list[dict],
    now: datetime,
    gas_price_wei: int,
    bnb_usd: float,
) -> KeeperDecision:
    """Whether this position has been outside its range long enough to be worth resetting.

    Pure, the way `doctor.diagnose` is pure: every input arrives in an argument, so every
    branch is reachable from a fixture and none of them needs a network.

    The fee rate, the range status and the dollar consequence are `diagnose`'s, not a
    second derivation of them. What is added here is the two questions `diagnose` does not
    ask: how long the position has been out, and whether the recovery projected from that
    rate over a stated window exceeds the cost of acting by the multiple the owner set.

    The notional is read off `position["declared_position_value_usd"]`, and its absence is
    an `alert` rather than a guess — Docket has no trusted first-party source for a
    position NFT's USD value, which is the same reason `diagnose` refuses to invent one.
    """
    policy.validate()
    if position.get("staked"):
        # MasterChefV3 holds the NFT, so `NPM.ownerOf` names the farm and there is no
        # approval the owner can make that lets a session touch it. "Unstake first" is the
        # only useful answer; drafting a batch nobody could authorise is not.
        return KeeperDecision(
            kind="alert",
            summary=(
                f"Position {position['token_id']}'s NFT is held by MasterChefV3, so it is "
                "staked in a farm and no session can be authorised over it. Unstake from "
                "MasterChefV3 first and the watch picks it up on its next pass."
            ),
            evidence={
                "policy": policy.as_record(),
                "staked": True,
                "token_id": position["token_id"],
            },
            new_tick_lower=None,
            new_tick_upper=None,
        )
    inventory = position.get("session_inventory") or {}
    # A batch that closed the position and then stopped leaves liquidity at zero and the
    # tokens in the session. `diagnose` reads that as `closed`, which is true of the NFT
    # and wrong about the money: the reset is half done, and the half left is the half
    # that matters. Restarting it would burn nothing and mint nothing.
    resuming = position["liquidity"] == 0 and bool(
        int(inventory.get("token0") or 0) or int(inventory.get("token1") or 0)
    )
    diagnosis = doctor.diagnose(
        # A resumed batch already burnt the position, so `diagnose` would read it as
        # `closed` and quote no pool rate at all. The rate that matters here is the one the
        # REPLACEMENT will earn, which is the pool's — so the diagnosis is taken against
        # the range as it stood, with a placeholder liquidity that only decides whether the
        # position counts as closed. Every other figure in it is the real one.
        dict(position, liquidity=1) if resuming else position,
        pool,
        pool_stats,
        declared_position_value_usd=position.get("declared_position_value_usd"),
        estimated_recenter_cost_usd=None,
        decision_horizon_days=PROJECTION_DAYS,
    )
    status = diagnosis["status"]
    economics = diagnosis["economic_consequence"]
    tick = diagnosis["verifiable_facts"]["current_tick"]
    # `unknown_pool` and `closed` say nothing about whether the position was outside a
    # range, so neither is counted as time outside one. Reading them as "out" would date a
    # departure from an observation that observed no price at all.
    placed = status in doctor.RANGE_STATUSES
    observed_minutes = out_of_range_minutes(
        history, now=now, in_range=not placed or diagnosis["in_range"]
    )

    new_lower = new_upper = None
    spacing_reason = None
    if tick is not None:
        try:
            spacing = tick_spacing(position["fee"])
        except ValueError as exc:
            spacing_reason = str(exc)
        else:
            half = policy.band_width_ticks
            if half is None:
                half = max(
                    spacing, (position["tick_upper"] - position["tick_lower"]) // 2
                )
            new_lower, new_upper = align_range(tick, half, spacing)

    evidence = {
        "diagnosis": diagnosis,
        "policy": policy.as_record(),
        "observed_at": diagnosis["observed_at"],
        "block": diagnosis["as_of_block"],
        "time_out_of_range": {
            "observed_minutes": observed_minutes,
            "threshold_minutes": policy.out_of_range_minutes,
            "prior_observations": len(history),
            "method": (
                "the trailing run of prior observations that saw the position outside its "
                "range dates the departure; a run of length zero means the departure has "
                "not been observed yet and no elapsed time is claimed"
            ),
        },
        "new_range": {
            "tick_lower": new_lower,
            "tick_upper": new_upper,
            "centred_on_tick": tick,
            "tick_spacing": None
            if new_lower is None
            else tick_spacing(position["fee"]),
            "unavailable_reason": spacing_reason
            or (None if tick is not None else "no pool tick could be read"),
        },
        "swap_note": SWAP_NOTE,
    }

    if resuming:
        evidence["resuming"] = {
            "session_inventory": {
                "token0": str(int(inventory.get("token0") or 0)),
                "token1": str(int(inventory.get("token1") or 0)),
            },
            "reason": (
                "this position's liquidity is zero and the session still holds inventory "
                "from a batch that stopped after the collect, so the reset continues from "
                "the swap rather than beginning again — there is nothing left to burn"
            ),
        }
    elif status not in doctor.RANGE_STATUSES or diagnosis["in_range"]:
        evidence["economics"] = _no_economics(
            f"the position is {status}, so no reset is due and none is priced"
        )
        return KeeperDecision(
            kind="noop",
            summary=diagnosis["decision"],
            evidence=evidence,
            new_tick_lower=new_lower,
            new_tick_upper=new_upper,
        )

    if not resuming and observed_minutes < policy.out_of_range_minutes:
        evidence["economics"] = _no_economics(
            f"the position has been observed outside its range for "
            f"{observed_minutes:.1f} minutes, below the {policy.out_of_range_minutes} "
            "the policy requires, so no reset is priced"
        )
        return KeeperDecision(
            kind="noop",
            summary=(
                f"Position {position['token_id']} is outside its range and has been "
                f"observed there for {observed_minutes:.1f} of the "
                f"{policy.out_of_range_minutes} minutes the policy waits for."
            ),
            evidence=evidence,
            new_tick_lower=new_lower,
            new_tick_upper=new_upper,
        )

    refusals = []
    expiry = parse_expiry(policy.expires_at)
    if now >= expiry:
        refusals.append(f"the policy expired at {policy.expires_at}")
    if gas_price_wei > policy.max_gas_price_wei:
        refusals.append(
            f"the gas price is {gas_price_wei} wei, above the policy ceiling of "
            f"{policy.max_gas_price_wei}"
        )
    if new_lower is None:
        refusals.append(
            evidence["new_range"]["unavailable_reason"] or "no new range could be drawn"
        )
    notional = economics["declared_position_value_usd"]
    if notional is None:
        refusals.append(
            "declared_position_value_usd was not supplied for this token id, and Docket "
            "has no trusted first-party source for this NFT's USD value"
        )
    elif notional > policy.max_notional_usd:
        refusals.append(
            f"the declared notional ${notional:,.2f} is above the policy's "
            f"${policy.max_notional_usd:,.2f} ceiling"
        )
    if bnb_usd <= 0:
        # Without it the gas leg of the cost is zero, and a reset that cost nothing would
        # clear any benefit multiple. A missing price has to refuse, not discount.
        refusals.append(
            "bnb_usd was not supplied, so the gas cost of a reset cannot be converted into "
            "dollars and no benefit multiple is computed against it"
        )
    rate = economics["net_apr"]
    if rate is None:
        refusals.append(
            f"no net fee rate is quotable: {economics['unavailable_reason']}"
        )
    elif rate <= 0:
        refusals.append(
            "the observed net fee rate is not positive, so nothing is recovered"
        )

    if refusals:
        evidence["economics"] = _no_economics("; ".join(refusals))
        return KeeperDecision(
            kind="alert",
            summary=(
                f"Position {position['token_id']} has been outside its range for "
                f"{observed_minutes:.1f} minutes and no reset is offered: "
                + "; ".join(refusals)
                + "."
            ),
            evidence=evidence,
            new_tick_lower=new_lower,
            new_tick_upper=new_upper,
        )

    economics_record = _economics(
        notional=notional,
        rate=rate,
        fee=position["fee"],
        policy=policy,
        gas_price_wei=gas_price_wei,
        bnb_usd=bnb_usd,
    )
    evidence["economics"] = economics_record
    multiple = economics_record["net_benefit_multiple"]
    if multiple < policy.min_net_benefit_multiple:
        return KeeperDecision(
            kind="alert",
            summary=(
                f"Position {position['token_id']} has been outside its range for "
                f"{observed_minutes:.1f} minutes. Resetting it into ticks "
                f"[{new_lower}, {new_upper}) projects "
                f"${economics_record['projected_recovery_usd']:,.2f} of fees over "
                f"{PROJECTION_DAYS} days against ${economics_record['total_cost_usd']:,.2f} "
                f"of execution cost, a multiple of {multiple:.2f} against the "
                f"{policy.min_net_benefit_multiple:.2f} the policy requires, so no reset "
                "is offered."
            ),
            evidence=evidence,
            new_tick_lower=new_lower,
            new_tick_upper=new_upper,
        )

    return KeeperDecision(
        kind="action",
        summary=(
            f"Position {position['token_id']} has been outside its range for "
            f"{observed_minutes:.1f} minutes, past the {policy.out_of_range_minutes} the "
            f"policy waits for. Resetting it into ticks [{new_lower}, {new_upper}) "
            f"projects ${economics_record['projected_recovery_usd']:,.2f} of fees over "
            f"{PROJECTION_DAYS} days against ${economics_record['total_cost_usd']:,.2f} of "
            f"execution cost, a multiple of {multiple:.2f} against the "
            f"{policy.min_net_benefit_multiple:.2f} the policy requires."
        ),
        evidence=evidence,
        new_tick_lower=new_lower,
        new_tick_upper=new_upper,
    )


def _no_economics(reason: str) -> dict:
    return {
        "projected_recovery_usd": None,
        "total_cost_usd": None,
        "net_benefit_multiple": None,
        "unavailable_reason": reason,
        "projection_limitation": PROJECTION_LIMITATION,
        "cost_limitation": COST_LIMITATION,
    }


def _economics(
    *,
    notional: float,
    rate: float,
    fee: int,
    policy: KeeperPolicy,
    gas_price_wei: int,
    bnb_usd: float,
) -> dict:
    """Projected fee recovery against the whole cost of acting, both shown in full."""
    recovery = notional * rate * PROJECTION_DAYS / 365
    gas_wei = REBALANCE_GAS_UNITS * gas_price_wei
    gas_usd = gas_wei / WEI_PER_BNB * bnb_usd
    swap_notional = notional * SWAP_FRACTION
    # V2's 25bps, not the v3 tier: the leg is quoted on V2 first, and pricing a reset at
    # a 0.01% tier that is then executed against a 0.25% venue understates it fortyfold.
    # `_prepare` re-tests this against the shortfall the venue actually quotes.
    swap_usd = swap_notional * (V2_FEE_BPS + policy.max_slippage_bps) / 10_000
    total = gas_usd + swap_usd
    return {
        "declared_notional_usd": notional,
        "declared_notional_source": "caller",
        "net_apr": rate,
        "projection_days": PROJECTION_DAYS,
        "projected_recovery_usd": recovery,
        "gas_units": REBALANCE_GAS_UNITS,
        "gas_price_wei": str(gas_price_wei),
        "gas_wei": str(gas_wei),
        "bnb_usd": bnb_usd,
        "bnb_usd_source": "caller",
        "gas_cost_usd": gas_usd,
        "swap_notional_usd": swap_notional,
        "swap_fraction": SWAP_FRACTION,
        "pool_fee_tier": fee,
        "swap_fee_bps_assumed": V2_FEE_BPS,
        "swap_cost_usd": swap_usd,
        "total_cost_usd": total,
        "net_benefit_multiple": None if total <= 0 else recovery / total,
        "required_multiple": policy.min_net_benefit_multiple,
        "unavailable_reason": None,
        "projection_limitation": PROJECTION_LIMITATION,
        "cost_limitation": COST_LIMITATION,
    }


def swap_plan(
    burn0: int, burn1: int, *, sqrt_price_x96: int, slippage_bps: int
) -> dict:
    """Whether closing this position leaves an inventory a centred range can be minted
    from, and if not, which side has to be sold and how much of it.

    A range drawn around the current tick wants equal value on both sides. The value of
    the token0 leg in token1 terms is `amount0 * sqrtP**2 / 2**192` — the pool's own
    price, in integers, with no float anywhere in it, which is why nothing here goes
    through `tickmath` (whose docstring bans its float path from transaction sizing).

    A position already balanced to within the slippage bound needs no trade at all, and
    none is planned: paying a fee and a spread to move an amount smaller than the bound
    the mint already tolerates is a cost with nothing bought by it. Everything else sells
    the heavier side down to half the total value, which reduces to selling exactly half
    of a one-sided position — the shape a keeper actually meets, because it only fires on
    a position that has left its range.
    """
    if slippage_bps <= 0:
        raise ValueError("slippage_bps must be positive to size a swap against")
    value1_of_token0 = burn0 * sqrt_price_x96 * sqrt_price_x96 // Q192
    total = value1_of_token0 + burn1
    imbalance = abs(value1_of_token0 - burn1)
    plan = {
        "needed": False,
        "token_in": None,
        "amount_in": 0,
        "value1_of_token0": value1_of_token0,
        "value1_of_token1": burn1,
        "total_value1": total,
        "imbalance_value1": imbalance,
        "slippage_bps": slippage_bps,
        "reason": "",
    }
    if total <= 0:
        plan["reason"] = (
            "the closed position releases nothing, so there is no inventory to rebalance"
        )
        return plan
    if imbalance * 10_000 <= total * slippage_bps:
        plan["reason"] = (
            f"the two sides differ by {imbalance} of {total} in token1 terms, inside the "
            f"{slippage_bps}bps the policy already tolerates, so no leg is emitted"
        )
        return plan
    if value1_of_token0 > burn1:
        amount_in = (value1_of_token0 - total // 2) * Q192 // (
            sqrt_price_x96 * sqrt_price_x96
        )
        token_in = "token0"
    else:
        amount_in = burn1 - total // 2
        token_in = "token1"
    held = burn0 if token_in == "token0" else burn1
    amount_in = min(amount_in, held)
    if amount_in <= 0:
        plan["reason"] = (
            "the surplus side rounds to nothing at this price, so no leg is emitted"
        )
        return plan
    plan.update(
        {
            "needed": True,
            "token_in": token_in,
            "amount_in": amount_in,
            "reason": (
                f"{token_in} carries {imbalance} more of the {total} total value than the "
                f"other side, so {amount_in} atomic units of it are sold to bring the two "
                "to equal value"
            ),
        }
    )
    return plan


def _unsimulated() -> dict:
    """The simulation slot of a call nobody has put to the chain yet.

    Filled in rather than omitted, so a `PreparedCall` that reached a signer without ever
    being simulated says so in the field a reader looks at rather than by the field's
    absence.
    """
    return {
        "ok": None,
        "gas_estimate": None,
        "revert_reason": None,
        "observed_at": None,
        "block": None,
    }


def _floor(amount: int, slippage_bps: int) -> int:
    return int(amount) * (10_000 - slippage_bps) // 10_000


def rebalance_calls(
    position: dict,
    *,
    new_tick_lower: int,
    new_tick_upper: int,
    recipient: str,
    session: str,
    deadline: int,
    amounts: dict,
) -> list[PreparedCall]:
    """The exact calls that close one position and open its replacement. Signs nothing.

    Seven calls, in the order they must land — five where the inventory needs no trade,
    and five where a stopped batch is being resumed and there is nothing left to close.
    Every one of them is the session's to send; see the module docstring for why the
    owner's ERC-721 approval is not among them.

    `decreaseLiquidity` and `collect` first. `collect`'s recipient is the session and not
    the owner: the tokens have to be held by the address that funds the swap and the mint,
    and routing them to the owner first would need a second owner signature to send them
    back. `mint`'s recipient is the owner, so the new position NFT is the owner's from the
    block it exists in — Docket never holds it.

    Between them, the router leg: an exact-amount approval and one exact-input swap, at
    whichever venue `amounts["swap"]["venue"]` names. `v2` is
    `swapExactTokensForTokens` through `docket/execution/simulate.py::swap_calldata`,
    the same builder and the same router the rest of Docket's execution plane uses. `v3`
    is `exactInputSingle` into the very pool the position was minted in, for pairs whose
    V2 market is too thin to trade through — the executor chooses, and records why.

    `deadline` is one instant shared by every call in the batch: the position manager and
    both routers each refuse a call that arrives after it, so the batch either lands
    inside its own window or is refused in the block after it.

    `amounts`, in atomic units:

      * `burn0` / `burn1` — the quoted output of `decreaseLiquidity`, or the inventory the
        session already holds when `resume` is set.
      * `max_slippage_bps` — the bound every minimum below is derived from.
      * `resume` — truthy to skip the close entirely: the position is already burnt and
        its tokens are already in the session.
      * `swap` — `None` where the inventory is already balanced, otherwise
        `{"venue", "token_in", "amount_in", "min_output"}`. The floor is passed in rather
        than derived here because only the caller knows which venue quoted it and how.

    The amounts the mint asks for are derived here, so the floor the swap is held to and
    the amount the mint pulls cannot drift apart: the mint desires exactly the swap's
    `min_output`, which is the least it may deliver without reverting.
    """
    slippage = int(amounts["max_slippage_bps"])
    if not 0 < slippage <= 1000:
        raise ValueError(
            f"max_slippage_bps {slippage} is outside 1..1000; a floor computed from it "
            "would either revert on the first wei of movement or bound nothing"
        )
    token_id = int(position["token_id"])
    liquidity = int(position["liquidity"])
    resume = bool(amounts.get("resume"))
    if liquidity <= 0 and not resume:
        raise ValueError(
            f"position {token_id} holds no liquidity, so there is nothing to decrease and "
            "no reset to build"
        )
    if new_tick_upper <= new_tick_lower:
        raise ValueError(
            f"the new range [{new_tick_lower}, {new_tick_upper}) is empty, and a mint "
            "against it reverts"
        )
    owner = Web3.to_checksum_address(recipient)
    session_address = Web3.to_checksum_address(session)
    token0 = Web3.to_checksum_address(position["token0"])
    token1 = Web3.to_checksum_address(position["token1"])
    burn0 = int(amounts["burn0"])
    burn1 = int(amounts["burn1"])

    swap = amounts.get("swap")
    if swap is None:
        desired0, desired1 = burn0, burn1
    else:
        side = swap["token_in"]
        if side not in ("token0", "token1"):
            raise ValueError(
                f"swap token_in {side!r} is neither token0 nor token1, so no route can be "
                "built from it"
            )
        venue = swap["venue"]
        if venue not in ("v2", "v3"):
            raise ValueError(
                f"swap venue {venue!r} is neither v2 nor v3, and no other venue has a "
                "builder here"
            )
        amount_in = int(swap["amount_in"])
        min_output = int(swap["min_output"])
        held = burn0 if side == "token0" else burn1
        if not 0 < amount_in <= held:
            raise ValueError(
                f"the swap sells {amount_in} atomic units of {side} and the inventory "
                f"holds {held}; a leg cannot spend what the session does not have"
            )
        if min_output <= 0:
            raise ValueError(
                "a swap with a floor of 0 accepts any output at all, which is the one "
                "thing no action in this package is allowed to do"
            )
        if side == "token0":
            desired0, desired1 = burn0 - amount_in, burn1 + min_output
            route = (token0, token1)
        else:
            desired0, desired1 = burn0 + min_output, burn1 - amount_in
            route = (token1, token0)

    calls: list[PreparedCall] = []
    if not resume:
        calls.extend(
            [
                PreparedCall(
                    to=NPM,
                    data=npm_encoder.encode_abi(
                        "decreaseLiquidity",
                        args=[
                            (
                                token_id,
                                liquidity,
                                _floor(burn0, slippage),
                                _floor(burn1, slippage),
                                deadline,
                            )
                        ],
                    ),
                    value_atomic="0",
                    chain_id=BSC_CHAIN_ID,
                    gas_ceiling=DECREASE_LIQUIDITY_GAS,
                    deadline=deadline,
                    purpose="session_closes_position",
                    simulation=_unsimulated(),
                ),
                PreparedCall(
                    to=NPM,
                    data=npm_encoder.encode_abi(
                        "collect",
                        args=[(token_id, session_address, MAX_UINT128, MAX_UINT128)],
                    ),
                    value_atomic="0",
                    chain_id=BSC_CHAIN_ID,
                    gas_ceiling=COLLECT_GAS,
                    deadline=deadline,
                    purpose="session_collects_to_fund_the_swap_and_the_mint",
                    simulation=_unsimulated(),
                ),
            ]
        )
    if swap is not None:
        target = PANCAKE_V2_ROUTER if venue == "v2" else V3_SWAP_ROUTER
        if venue == "v2":
            data = "0x" + swap_calldata(
                amount_in=amount_in,
                min_output=min_output,
                route=route,
                recipient=session_address,
                deadline=deadline,
            ).hex()
        else:
            data = v3_router_encoder.encode_abi(
                "exactInputSingle",
                args=[
                    (
                        route[0],
                        route[1],
                        int(position["fee"]),
                        session_address,
                        deadline,
                        amount_in,
                        min_output,
                        NO_SQRT_PRICE_LIMIT,
                    )
                ],
            )
        calls.extend(
            [
                PreparedCall(
                    to=route[0],
                    data=_erc20_encoder.encode_abi("approve", args=[target, amount_in]),
                    value_atomic="0",
                    chain_id=BSC_CHAIN_ID,
                    gas_ceiling=APPROVE_GAS,
                    deadline=deadline,
                    purpose=f"session_approves_{venue}_router_exact",
                    simulation=_unsimulated(),
                ),
                PreparedCall(
                    to=target,
                    data=data,
                    value_atomic="0",
                    chain_id=BSC_CHAIN_ID,
                    gas_ceiling=SWAP_GAS,
                    deadline=deadline,
                    purpose=f"session_balances_the_inventory_on_{venue}",
                    simulation=_unsimulated(),
                ),
            ]
        )
    calls.extend(
        [
            PreparedCall(
                to=token0,
                data=_erc20_encoder.encode_abi("approve", args=[NPM, desired0]),
                value_atomic="0",
                chain_id=BSC_CHAIN_ID,
                gas_ceiling=APPROVE_GAS,
                deadline=deadline,
                purpose="session_approves_token0_exact",
                simulation=_unsimulated(),
            ),
            PreparedCall(
                to=token1,
                data=_erc20_encoder.encode_abi("approve", args=[NPM, desired1]),
                value_atomic="0",
                chain_id=BSC_CHAIN_ID,
                gas_ceiling=APPROVE_GAS,
                deadline=deadline,
                purpose="session_approves_token1_exact",
                simulation=_unsimulated(),
            ),
            PreparedCall(
                to=NPM,
                data=npm_encoder.encode_abi(
                    "mint",
                    args=[
                        (
                            token0,
                            token1,
                            int(position["fee"]),
                            int(new_tick_lower),
                            int(new_tick_upper),
                            desired0,
                            desired1,
                            _floor(desired0, slippage),
                            _floor(desired1, slippage),
                            owner,
                            deadline,
                        )
                    ],
                ),
                value_atomic="0",
                chain_id=BSC_CHAIN_ID,
                gas_ceiling=MINT_GAS,
                deadline=deadline,
                purpose="session_mints_replacement_to_owner",
                simulation=_unsimulated(),
            ),
        ]
    )
    return calls
