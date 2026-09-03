"""A grid that runs, level by level, inside a session the owner granted.

**There are no resting orders here, and the word "order" is used with that caveat
attached everywhere it appears.** PancakeSwap V2 is a constant-product AMM. It holds no
order book, so nothing can be placed on it and left to fill. A "grid order" in this
module is a *level*: a price, a side and a size, held by Docket, which fires one bounded
swap the first time an observation of the pool's own quote crosses it. Until that
observation the level exists only in Docket's state; nothing is on chain, nothing is
reserved, and cancelling costs no gas. Every user-facing summary this module produces
says so in its own words, because a buyer who believes their capital is sitting on an
exchange has been told something untrue.

What that buys, and what it costs. A level fires at whatever the pool quotes when the
crossing is observed, not at the level's own price — the difference between the two is
the depth the level asked the pool for, and it is bounded by `max_slippage_bps` and by
the `min_output` written into the calldata rather than left to the router. And a level
can be crossed and uncrossed between two observations without firing at all, which an
order book would have filled. That is the honest trade and it is on the record.

The arithmetic is not restated here. `plan.py` already derives the ladder, sides it and
picks the one level an observation fires, and it is tested against hand-checked numbers;
this module holds the *lifecycle* around it — the reference the sides were computed
against, the fills, the spend against a cap, and the four ways a grid stops.

**pause, cancel, revoke, expire — four different things.**

- `paused` stops new firing and changes nothing else. Levels stay open, the session keeps
  its funds, and clearing the flag resumes exactly where it stopped. It is the reversible
  one, and it is what `SessionPolicy.emergency_pause` reaches.
- `cancelled` retires every remaining level permanently. No level fires again, but the
  session still holds whatever it holds: cancelling is a decision about the strategy, not
  about the money, and sweeping funds on a cancel would take an action the owner did not
  ask for.
- `revoked` is the terminal one. The session is swept back to the owner and no level is
  ever evaluated again.
- Expiry past `expires_at` reaches the revoke path on its own, without waiting for
  anybody: a session that outlives the spec that justified it is the failure the expiry
  exists to prevent, so an expired grid asks to be swept rather than merely stopping.

`stop_price` is the fifth and it maps onto `cancelled`: an observation at or beyond it
retires the remaining levels and fires nothing. It is a shutdown threshold, not a stop
order — the same caveat as above applies, and it too is only as fast as observation is.
"""

from dataclasses import dataclass, field, replace

from web3 import Web3

from ...execution.intent import ActionIntent, commit
from ...execution.simulate import (
    PANCAKE_V2_ROUTER,
    SWAP_SIGNATURE,
    simulate,
    swap_calldata,
)
from ...hire.receipts import canonical_hash
from ...jobs.executors.base import PreparedCall
from ..yield_router.router import MOVE_ASSETS
from .plan import GridLevel, build_plan, next_action

SWAP_SELECTOR = "0x" + Web3.keccak(text=SWAP_SIGNATURE)[:4].hex()
POLICY_VERSION = "grid-lifecycle/1"
# The one rule this build sides levels by, and a closed set so a second one has to be
# added deliberately rather than typed into a request body.
DIRECTION_RULES = frozenset({"buy_below_sell_above"})
# How long a drafted swap stays valid. Long enough to be mined, short enough that a
# transaction stuck in the mempool expires rather than filling at a price nobody looked
# at. Same figure the Stage 2 operator uses, for the same reason.
DEADLINE_S = 600
# A V2 token-to-token swap costs well under this. A ceiling, not an estimate — the
# simulation supplies the estimate and refuses if it exceeds this.
GAS_CEILING = 300_000
# What Docket will trade in either direction. One list, shared with the yield router,
# because two allowlists over the same three BSC assets is one list that goes stale.
GRID_ASSETS = MOVE_ASSETS

NO_RESTING_ORDERS = (
    "PancakeSwap V2 is an automated market maker and holds no order book, so nothing "
    "here is placed on an exchange and left to fill. Each level is a price Docket "
    "watches; the first observation that crosses it fires one bounded swap at whatever "
    "the pool quotes at that moment. Between two observations a level can be crossed "
    "and uncrossed without firing. Cancelling costs no gas because nothing was ever "
    "resting on chain."
)
STOP_IS_NOT_A_STOP_ORDER = (
    "stop_price is a shutdown threshold Docket evaluates against its own observations, "
    "not a stop order held by a venue. It retires the remaining levels; it does not "
    "sell anything, and it is only as fast as the next observation."
)


class GridRefused(ValueError):
    """A spec that cannot be run as written. Raised at validation, never at fire time."""


@dataclass(frozen=True)
class Fill:
    """One level that actually traded, read back off the chain rather than assumed."""

    level: int | None
    side: str
    amount_in: int
    amount_out: int
    tx_hash: str
    block: int

    def as_record(self) -> dict:
        return {
            "level": self.level,
            "side": self.side,
            "amount_in": str(self.amount_in),
            "amount_out": str(self.amount_out),
            "tx_hash": self.tx_hash,
            "block": self.block,
        }


@dataclass(frozen=True)
class GridSpec:
    """Everything a grid is, before any of it has been observed.

    Prices are integers of quote-token atomic units per one whole base token, the same
    convention `plan.py` documents: USDT at 18 decimals on BSC means 600 USDT/WBNB is
    `600 * 10**18`.

    `amount_per_level_atomic` and `total_cap_atomic` are both in the quote token. A buy
    level spends that directly; a sell level sells what it is worth in the base token at
    that level's own price, so every level puts the same value to work rather than the
    same quantity.
    """

    base: str
    quote: str
    price_lower: int
    price_upper: int
    levels: int
    amount_per_level_atomic: int
    total_cap_atomic: int
    expires_at: int
    max_slippage_bps: int
    stop_price: int | None = None
    direction_rule: str = "buy_below_sell_above"
    # Needed to size a sell level, which converts a quote-denominated notional into base
    # at that level's price. 18 for WBNB and for USDT on BSC; stated rather than probed
    # so a spec hashes to the same digest without a network read.
    base_decimals: int = 18

    def __post_init__(self) -> None:
        object.__setattr__(self, "base", Web3.to_checksum_address(self.base))
        object.__setattr__(self, "quote", Web3.to_checksum_address(self.quote))

    def validate(self) -> "GridSpec":
        """Every refusal, before a single network call. Returns self so it can chain.

        The allowlist check is first because it is the only one whose failure means the
        request named an asset Docket does not trade at all, and reporting a band error
        on a token that was never eligible tells the caller to fix the wrong thing.
        """
        for name, token in (("base", self.base), ("quote", self.quote)):
            if token not in GRID_ASSETS:
                raise GridRefused(
                    f"grid: {name} {token} is not on this build's asset allowlist of "
                    f"{sorted(GRID_ASSETS)}"
                )
        if self.base == self.quote:
            raise GridRefused(
                "grid: base and quote are the same token, so there is nothing to trade"
            )
        if self.direction_rule not in DIRECTION_RULES:
            raise GridRefused(
                f"grid: direction_rule {self.direction_rule!r} is not one of "
                f"{sorted(DIRECTION_RULES)}"
            )
        for name in (
            "price_lower",
            "price_upper",
            "levels",
            "amount_per_level_atomic",
            "total_cap_atomic",
            "expires_at",
            "max_slippage_bps",
            "base_decimals",
        ):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool):
                raise GridRefused(
                    f"grid: {name} must be an integer, got {value!r}. These are atomic "
                    "units and unix seconds; a float is a figure that rounds differently "
                    "on another machine."
                )
        if self.price_lower <= 0:
            raise GridRefused("grid: price_lower must be a positive price")
        if self.price_upper <= self.price_lower:
            raise GridRefused(
                f"grid: price_upper {self.price_upper} is not above price_lower "
                f"{self.price_lower}"
            )
        if self.levels < 2:
            raise GridRefused("grid: a grid needs at least two levels — its two ends")
        if self.amount_per_level_atomic <= 0:
            raise GridRefused("grid: amount_per_level_atomic must be positive")
        if self.total_cap_atomic < self.amount_per_level_atomic:
            raise GridRefused(
                f"grid: total_cap_atomic {self.total_cap_atomic} is below one level's "
                f"{self.amount_per_level_atomic}, so no level could ever fire"
            )
        if not 0 < self.max_slippage_bps <= 500:
            raise GridRefused(
                f"grid: max_slippage_bps {self.max_slippage_bps} is outside 1..500. Zero "
                "would refuse every fill and 500 is the intent ceiling."
            )
        if self.expires_at <= 0:
            raise GridRefused("grid: expires_at must be a unix second")
        if self.stop_price is not None:
            if not isinstance(self.stop_price, int) or isinstance(
                self.stop_price, bool
            ):
                raise GridRefused("grid: stop_price must be an integer price or None")
            if self.stop_price <= 0:
                raise GridRefused("grid: stop_price must be a positive price")
            if self.price_lower <= self.stop_price <= self.price_upper:
                raise GridRefused(
                    f"grid: stop_price {self.stop_price} sits inside the band "
                    f"[{self.price_lower}, {self.price_upper}]. A shutdown threshold "
                    "inside the band retires the grid the first time it trades."
                )
        return self

    def level_prices(self) -> tuple[int, ...]:
        """The ladder, as arithmetic and nothing else.

        Floor division over the whole span rather than a repeated step, so the last
        level lands exactly on `price_upper` and no level carries the accumulated error
        of the ones before it.
        """
        span = self.price_upper - self.price_lower
        return tuple(
            self.price_lower + span * index // (self.levels - 1)
            for index in range(self.levels)
        )

    @property
    def spec_hash(self) -> str:
        return canonical_hash(self.as_record())

    def as_record(self) -> dict:
        return {
            "base": self.base,
            "quote": self.quote,
            "price_lower": str(self.price_lower),
            "price_upper": str(self.price_upper),
            "levels": self.levels,
            "amount_per_level_atomic": str(self.amount_per_level_atomic),
            "total_cap_atomic": str(self.total_cap_atomic),
            "expires_at": self.expires_at,
            "max_slippage_bps": self.max_slippage_bps,
            "stop_price": None if self.stop_price is None else str(self.stop_price),
            "direction_rule": self.direction_rule,
            "base_decimals": self.base_decimals,
            "level_prices": [str(price) for price in self.level_prices()],
            "no_resting_orders": NO_RESTING_ORDERS,
        }


@dataclass(frozen=True)
class GridState:
    """What has happened to this grid so far. Everything else is derived from it.

    `reference_price` is the observation the sides were computed against, recorded on
    the first evaluation and fixed thereafter. It lives here rather than on the spec
    because it is an observation, not a parameter — and because a grid whose sides
    re-derived themselves against every new observation would never fire anything: a
    level below the current price only becomes a buy once "current" stops moving with it.
    """

    open_levels: tuple[int, ...] = ()
    fills: tuple[Fill, ...] = ()
    spent_atomic: int = 0
    paused: bool = False
    cancelled: bool = False
    revoked: bool = False
    reference_price: int | None = None

    @property
    def filled_levels(self) -> tuple[int, ...]:
        return tuple(fill.level for fill in self.fills if fill.level is not None)

    def as_record(self) -> dict:
        return {
            "open_levels": list(self.open_levels),
            "fills": [fill.as_record() for fill in self.fills],
            "spent_atomic": str(self.spent_atomic),
            "paused": self.paused,
            "cancelled": self.cancelled,
            "revoked": self.revoked,
            "reference_price": (
                None if self.reference_price is None else str(self.reference_price)
            ),
        }


@dataclass(frozen=True)
class GridDecision:
    """One observation, and the at-most-one thing it caused."""

    kind: str
    reason: str
    observation: dict
    level: GridLevel | None = None
    prepared: PreparedCall | None = None
    state: GridState | None = None
    evidence: dict = field(default_factory=dict)

    def as_record(self) -> dict:
        return {
            "kind": self.kind,
            "reason": self.reason,
            "observation": self.observation,
            "level": None if self.level is None else self.level.as_record(),
            "prepared": None if self.prepared is None else self.prepared.to_dict(),
            "state": None if self.state is None else self.state.as_record(),
            "evidence": self.evidence,
            "no_resting_orders": NO_RESTING_ORDERS,
        }


DECISION_KINDS = frozenset({"noop", "fire", "alert", "cancel", "revoke"})


def _observation_record(observation, spec: GridSpec) -> dict:
    return {
        "price": str(int(observation.price)),
        "block_number": int(observation.block_number),
        "source": observation.source,
        "pair": f"{spec.base}/{spec.quote}",
        "units": (
            "atomic units of the quote token for one whole base token, as the router "
            "quotes it — an execution price for that size, fee included, not a mid price"
        ),
    }


def evaluate(
    state: GridState,
    observation,
    spec: GridSpec,
    *,
    reader,
    session_address: str,
    now: int,
) -> GridDecision:
    """One observation in, at most one bounded swap out.

    The order of the guards is the safety property, and it is deliberate: revocation is
    terminal so nothing below it can run; expiry reaches the revoke path even on a grid
    that is paused or cancelled, because a session outliving its spec is the thing the
    expiry exists to stop; cancellation retires the levels but leaves the funds alone;
    a pause is reversible and stops there; the stop price retires the levels; the cap
    refuses rather than trimming, because a size nobody asked for is not a smaller
    version of the one they did.

    Nothing below the simulation submits. The prepared call is returned with the
    chain's own answer attached, and a call the chain disagreed with comes back as an
    `alert` rather than as an action the loop could mistake for an approved one.
    """
    spec.validate()
    session_address = Web3.to_checksum_address(session_address)
    seen = _observation_record(observation, spec)
    price = int(observation.price)

    if state.revoked:
        return GridDecision(
            kind="noop",
            reason=(
                "this grid's session has been revoked: the funds were swept back to the "
                "owner and no level is evaluated again"
            ),
            observation=seen,
            state=state,
        )
    if now >= spec.expires_at:
        return GridDecision(
            kind="revoke",
            reason=(
                f"the grid expired at {spec.expires_at} and it is now {now}. The session "
                "is swept back to the owner rather than left holding funds under a spec "
                "that no longer justifies it."
            ),
            observation=seen,
            state=replace(state, revoked=True, open_levels=()),
        )
    if state.cancelled:
        return GridDecision(
            kind="noop",
            reason=(
                "this grid is cancelled: every remaining level is retired. The session "
                "still holds whatever it holds — cancelling is a decision about the "
                "strategy, not about the money, and revoke is what sweeps it"
            ),
            observation=seen,
            state=state,
        )
    if state.paused:
        return GridDecision(
            kind="noop",
            reason=(
                "this grid is paused: no level fires while the flag is set, the levels "
                "stay open, and clearing it resumes exactly here"
            ),
            observation=seen,
            state=state,
        )

    reference = state.reference_price if state.reference_price is not None else price
    working = (
        state
        if state.reference_price is not None
        else replace(state, reference_price=reference)
    )

    if spec.stop_price is not None and _stop_reached(spec, reference, price):
        return GridDecision(
            kind="cancel",
            reason=(
                f"the observed price {price} reached the shutdown threshold "
                f"{spec.stop_price}. Every remaining level is retired and nothing is "
                f"sent. {STOP_IS_NOT_A_STOP_ORDER}"
            ),
            observation=seen,
            state=replace(working, cancelled=True, open_levels=()),
        )

    plan = build_plan(
        lower=spec.price_lower,
        upper=spec.price_upper,
        levels=spec.levels,
        size_per_level=spec.amount_per_level_atomic,
        base=spec.base,
        quote=spec.quote,
        base_decimals=spec.base_decimals,
        reference=reference,
        side_rule=spec.direction_rule,
    )
    open_levels = tuple(
        level.index
        for level in plan.levels
        if level.index not in set(working.filled_levels)
    )
    working = replace(working, open_levels=open_levels)

    level = next_action(plan, price, working.filled_levels)
    if level is None:
        return GridDecision(
            kind="noop",
            reason=(
                f"no unfilled level is reached at {price}: the grid is waiting, which is "
                "what it does most of the time"
            ),
            observation=seen,
            state=working,
            evidence={
                "open_levels": list(open_levels),
                "reference_price": str(reference),
            },
        )

    committed = working.spent_atomic + spec.amount_per_level_atomic
    if committed > spec.total_cap_atomic:
        return GridDecision(
            kind="noop",
            reason=(
                f"level {level.index} would commit {spec.amount_per_level_atomic} against "
                f"a total cap of {spec.total_cap_atomic} with {working.spent_atomic} "
                "already committed. It is refused rather than trimmed to what is left: a "
                "size nobody asked for is not a smaller version of the one they did"
            ),
            observation=seen,
            level=level,
            state=working,
        )

    route = (level.token_in, level.token_out)
    quoted = int(reader.amounts_out(level.size, route)[-1])
    min_output = quoted * (10_000 - spec.max_slippage_bps) // 10_000
    if min_output <= 0:
        return GridDecision(
            kind="alert",
            reason=(
                f"level {level.index}: the router quotes {quoted} out for {level.size} in, "
                f"which leaves no floor at all once {spec.max_slippage_bps}bps of "
                "slippage is allowed. Nothing is sent without a floor"
            ),
            observation=seen,
            level=level,
            state=working,
        )

    deadline = now + DEADLINE_S
    calldata = swap_calldata(
        amount_in=level.size,
        min_output=min_output,
        route=route,
        recipient=session_address,
        deadline=deadline,
    )
    intent = ActionIntent(
        intent_id=f"{spec.spec_hash[:10]}-level-{level.index}-{len(working.fills)}",
        condition=level.condition,
        chain_id=56,
        target=PANCAKE_V2_ROUTER,
        selector=SWAP_SELECTOR,
        calldata_hash=commit(calldata),
        token_in=level.token_in,
        token_out=level.token_out,
        max_input=level.size,
        min_output=min_output,
        route=route,
        slippage_bps=spec.max_slippage_bps,
        deadline=deadline,
        gas_ceiling=GAS_CEILING,
        nonce=len(working.fills),
        policy_version=POLICY_VERSION,
        evidence_block=int(observation.block_number),
    )
    result = simulate(
        intent, calldata, reader=reader, sender=session_address, now_override=now
    )
    prepared = PreparedCall(
        to=PANCAKE_V2_ROUTER,
        data="0x" + calldata.hex(),
        value_atomic="0",
        gas_ceiling=GAS_CEILING,
        deadline=deadline,
        purpose=(
            f"grid level {level.index}: {level.side} at {level.price}, one "
            "PancakeSwap V2 exact-input swap. No order rests on chain — this is the "
            "swap the crossing fired"
        ),
        simulation={
            "ok": result.agrees,
            "gas_estimate": result.gas,
            "revert_reason": None if result.agrees else result.reason,
            "observed_at": seen["source"],
            "block": result.block_number if result.block_number is not None else 0,
            "expected_output": (
                None if result.expected_output is None else str(result.expected_output)
            ),
            "min_output": str(min_output),
            "checks": list(result.checks),
        },
    )
    evidence = {
        "intent": intent.as_record(),
        "intent_key": intent.idempotency_key,
        "reference_price": str(reference),
        "quoted_output": str(quoted),
        "min_output": str(min_output),
        "open_levels": list(open_levels),
        "no_resting_orders": NO_RESTING_ORDERS,
    }
    if not result.agrees:
        return GridDecision(
            kind="alert",
            reason=(
                f"level {level.index} was reached at {price}, and the chain disagreed "
                f"with the action drafted for it: {result.reason}. Nothing is sent"
            ),
            observation=seen,
            level=level,
            prepared=prepared,
            state=working,
            evidence=evidence,
        )
    return GridDecision(
        kind="fire",
        reason=(
            f"level {level.index} ({level.side} at {level.price}) was crossed at {price}. "
            f"One bounded swap of {level.size} is drafted with a floor of {min_output}; "
            f"{result.reason}"
        ),
        observation=seen,
        level=level,
        prepared=prepared,
        state=replace(working, spent_atomic=committed),
        evidence=evidence,
    )


def _stop_reached(spec: GridSpec, reference: int, price: int) -> bool:
    """Whether an observation has passed the shutdown threshold.

    `validate` already refuses a threshold inside the band, so it sits on exactly one
    side of it and the direction of the comparison follows from which side that is.
    """
    if spec.stop_price is None:
        return False
    if spec.stop_price < spec.price_lower:
        return price <= spec.stop_price
    return price >= spec.stop_price


TRANSFER_TOPIC = "0x" + Web3.keccak(text="Transfer(address,address,uint256)").hex()


def _topic_hex(topic) -> str:
    if isinstance(topic, (bytes, bytearray)):
        return "0x" + bytes(topic).hex()
    return str(topic).lower()


def _topic_address(topic) -> str:
    return Web3.to_checksum_address("0x" + _topic_hex(topic)[-40:])


def _log_value(data) -> int:
    if isinstance(data, (bytes, bytearray)):
        return int.from_bytes(bytes(data)[-32:], "big")
    text = str(data)
    return (
        int(text[2:] if text.startswith("0x") else text, 16) if text.strip("0x") else 0
    )


def detect_fills(receipts, spec: GridSpec, *, recipient: str) -> tuple[Fill, ...]:
    """Read what actually moved out of transaction receipts, rather than assuming it.

    A drafted swap is a claim about what a transaction would do; the ERC-20 `Transfer`
    logs are what it did. The two are compared by whoever holds both — this returns the
    second, so a fill recorded here can contradict the level that was supposed to have
    caused it and be seen doing so.

    `recipient` is required and is the session address the swap named. Without it the
    side is undecidable: in a V2 swap the pool is a sender of one token and a receiver
    of the other exactly as the trader is, and a buy seen from the pool's side is
    indistinguishable from a sell seen from the trader's. Deriving the side from a
    `side` field on the record would be trusting the claim this function exists to check.

    `level` comes from a `level` key on the receipt, which the loop writes when it fires
    one; a receipt without it yields a fill with `level=None` rather than an invented
    index. A receipt whose logs show neither token moving to or from the recipient is
    not a fill and is skipped — never turned into a zero-valued one.
    """
    recipient = Web3.to_checksum_address(recipient)
    tokens = {spec.base: "base", spec.quote: "quote"}
    fills: list[Fill] = []
    for receipt in receipts:
        moved: dict[str, list[tuple[str, str, int]]] = {"base": [], "quote": []}
        for log in receipt.get("logs") or ():
            topics = list(log.get("topics") or ())
            if len(topics) < 3 or _topic_hex(topics[0]) != TRANSFER_TOPIC:
                continue
            try:
                token = Web3.to_checksum_address(log.get("address"))
            except (TypeError, ValueError):
                continue
            side = tokens.get(token)
            if side is None:
                continue
            moved[side].append(
                (
                    _topic_address(topics[1]),
                    _topic_address(topics[2]),
                    _log_value(log.get("data")),
                )
            )

        received = _first(moved, recipient, position=1)
        sent = _first(moved, recipient, position=0)
        if received is None or sent is None or received[0] == sent[0]:
            continue
        side = "buy" if received[0] == "base" else "sell"
        fills.append(
            Fill(
                level=receipt.get("level"),
                side=side,
                amount_in=sent[1],
                amount_out=received[1],
                tx_hash=_tx_hash(receipt),
                block=int(
                    receipt.get("blockNumber") or receipt.get("block_number") or 0
                ),
            )
        )
    return tuple(fills)


def _first(moved: dict, address: str, *, position: int):
    """The first transfer of either token whose `from` (0) or `to` (1) is this address."""
    for side in ("base", "quote"):
        for transfer in moved[side]:
            if transfer[position] == address:
                return side, transfer[2]
    return None


def _tx_hash(receipt) -> str:
    raw = receipt.get("transactionHash") or receipt.get("transaction_hash") or ""
    if isinstance(raw, (bytes, bytearray)):
        return "0x" + bytes(raw).hex()
    return str(raw)


def pause(state: GridState) -> GridState:
    """Stop firing, keep everything. Reversible; a revoked grid cannot be paused."""
    if state.revoked:
        raise GridRefused("a revoked grid holds nothing to pause")
    return replace(state, paused=True)


def resume(state: GridState) -> GridState:
    """Clear the pause. A cancelled or revoked grid has no levels left to resume."""
    if state.cancelled or state.revoked:
        raise GridRefused(
            "resume only clears a pause; a cancelled or revoked grid has retired its "
            "levels and there is nothing to resume into"
        )
    return replace(state, paused=False)


def cancel(state: GridState) -> GridState:
    """Retire every remaining level. The session keeps its funds until revoke."""
    if state.revoked:
        raise GridRefused("a revoked grid has already retired every level")
    return replace(state, cancelled=True, open_levels=())


def revoke(state: GridState) -> GridState:
    """Terminal. The session is swept back to the owner and nothing runs again."""
    return replace(state, revoked=True, cancelled=True, paused=False, open_levels=())


def record_fills(state: GridState, fills) -> GridState:
    """Add observed fills. The cap is not touched here, and that is deliberate.

    `spent_atomic` moves when a level fires, not when it fills: the commitment is made
    the moment the swap is sent, and counting it again on the way back would let a grid
    fire twice against a cap it had already used. It is carried in the quote token, so
    a sell's base-denominated `amount_in` could not be added to it anyway — the level's
    stated notional is what the cap was written about, and that is what `evaluate` adds.
    """
    return replace(state, fills=state.fills + tuple(fills))
