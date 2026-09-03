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

**The new position NFT goes to the owner.** `mint`'s recipient is the wallet that owns
the old one, never Docket and never the session. The session is the recipient of
`collect` alone, because the tokens have to pass through the address that funds the mint
— that transit is the only moment Docket's session touches the assets, and it is bounded
by the ERC-20 approvals below and by the session's own on-chain caps.

**A recentred range needs a swap, and this module does not build one.** A position that
left its range holds one token only: below the range it is all token0, above it all
token1. A range drawn around the current tick needs both sides, so roughly half the
inventory has to be traded before `mint` can be funded. `evaluate` prices that trade into
the cost it compares against the projected fee recovery — the decision is made on the
real cost of acting — but `rebalance_calls` emits the position-manager calls only and
takes the post-swap inventory as an input. The swap leg belongs to the execution plane
that owns Docket's router path; naming it as a prerequisite is honest, and building a
second copy of it here would be the copy that goes stale.

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
# The three position-manager calls plus the two ERC-20 approvals a session must send. The
# owner-signed ERC-721 approval is not counted: the owner pays for it from their own
# wallet, and charging it to the session's cost model would double-count it.
REBALANCE_GAS_UNITS = DECREASE_LIQUIDITY_GAS + COLLECT_GAS + MINT_GAS + 2 * APPROVE_GAS
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
SWAP_PREREQUISITE = (
    "A range drawn around the current tick holds both tokens, and a position that left its "
    "range holds one. Roughly half the inventory has to be traded before mint can be "
    "funded. That trade is priced into the cost below and is not among the calls this "
    "module builds; the amounts handed to rebalance_calls are the inventory expected at "
    "mint time, after it."
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
    diagnosis = doctor.diagnose(
        position,
        pool,
        pool_stats,
        declared_position_value_usd=position.get("declared_position_value_usd"),
        estimated_recenter_cost_usd=None,
        decision_horizon_days=PROJECTION_DAYS,
    )
    status = diagnosis["status"]
    economics = diagnosis["economic_consequence"]
    tick = diagnosis["verifiable_facts"]["current_tick"]
    observed_minutes = out_of_range_minutes(
        history, now=now, in_range=diagnosis["in_range"]
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
        "swap_prerequisite": SWAP_PREREQUISITE,
    }

    if status not in ("out_of_range_below", "out_of_range_above"):
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

    if observed_minutes < policy.out_of_range_minutes:
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
    swap_usd = swap_notional * (fee / 1_000_000 + policy.max_slippage_bps / 10_000)
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
        "swap_cost_usd": swap_usd,
        "total_cost_usd": total,
        "net_benefit_multiple": None if total <= 0 else recovery / total,
        "required_multiple": policy.min_net_benefit_multiple,
        "unavailable_reason": None,
        "projection_limitation": PROJECTION_LIMITATION,
        "cost_limitation": COST_LIMITATION,
    }


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

    Six calls, in the order they must land.

    The first is the owner's. `approve(session, tokenId)` on the position manager is
    ERC-721, and only the token's owner may make it — a session key cannot grant itself
    authority over an NFT it does not hold. It carries `purpose: "owner_signs"` so nothing
    downstream mistakes it for something the session can send.

    Then `decreaseLiquidity` and `collect`, both from the session under that approval.
    `collect`'s recipient is the session and not the owner: the tokens have to be held by
    the address that funds the mint, and routing them to the owner first would need a
    second owner signature to send them back. `mint`'s recipient is the owner, so the new
    position NFT is the owner's from the block it exists in — Docket never holds it.

    `amounts` states what the caller expects to be holding, in atomic units:
    `burn0`/`burn1` are the quoted output of `decreaseLiquidity`, `desired0`/`desired1`
    the inventory at mint time (after the swap this module does not build), and
    `max_slippage_bps` the bound every minimum below is derived from. The collect maxima
    are the uint128 ceiling on purpose: `collect` sweeps whatever is owed, and a maximum
    below that would leave fees behind in the position being closed.
    """
    slippage = int(amounts["max_slippage_bps"])
    if not 0 < slippage <= 1000:
        raise ValueError(
            f"max_slippage_bps {slippage} is outside 1..1000; a floor computed from it "
            "would either revert on the first wei of movement or bound nothing"
        )
    token_id = int(position["token_id"])
    liquidity = int(position["liquidity"])
    if liquidity <= 0:
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
    desired0 = int(amounts["desired0"])
    desired1 = int(amounts["desired1"])

    return [
        PreparedCall(
            to=NPM,
            data=_erc20_encoder.encode_abi("approve", args=[session_address, token_id]),
            value_atomic=0,
            chain_id=BSC_CHAIN_ID,
            gas_ceiling=APPROVE_GAS,
            deadline=deadline,
            # ERC-721 approve, not ERC-20: the second argument is this NFT's id, not an
            # amount, and only its owner can make the call.
            purpose="owner_signs",
            simulation=_unsimulated(),
        ),
        PreparedCall(
            to=NPM,
            data=npm_encoder.encode_abi(
                "decreaseLiquidity",
                args=[
                    (
                        token_id,
                        liquidity,
                        _floor(amounts["burn0"], slippage),
                        _floor(amounts["burn1"], slippage),
                        deadline,
                    )
                ],
            ),
            value_atomic=0,
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
            value_atomic=0,
            chain_id=BSC_CHAIN_ID,
            gas_ceiling=COLLECT_GAS,
            deadline=deadline,
            purpose="session_collects_to_fund_mint",
            simulation=_unsimulated(),
        ),
        PreparedCall(
            to=token0,
            data=_erc20_encoder.encode_abi("approve", args=[NPM, desired0]),
            value_atomic=0,
            chain_id=BSC_CHAIN_ID,
            gas_ceiling=APPROVE_GAS,
            deadline=deadline,
            purpose="session_approves_token0_exact",
            simulation=_unsimulated(),
        ),
        PreparedCall(
            to=token1,
            data=_erc20_encoder.encode_abi("approve", args=[NPM, desired1]),
            value_atomic=0,
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
            value_atomic=0,
            chain_id=BSC_CHAIN_ID,
            gas_ceiling=MINT_GAS,
            deadline=deadline,
            purpose="session_mints_replacement_to_owner",
            simulation=_unsimulated(),
        ),
    ]
