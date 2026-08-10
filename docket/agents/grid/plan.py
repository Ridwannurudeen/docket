"""The grid, as arithmetic. No network, no chain, no clock.

A grid is the one strategy that does not need an opinion. The user says the band, how
many levels, and how much to commit at each; everything after that is division. That is
exactly why it is the right first thing to let an agent execute — there is no judgement
for the agent to get wrong, only arithmetic to get exactly right, and the arithmetic can
be checked by hand.

Two decisions worth stating, because both could reasonably have gone the other way.

**Prices are integers of quote-token atomic units per one whole base token.** USDT at
18 decimals on BSC means 600 USDT/WBNB is `600 * 10**18`. Spacing uses floor division
over the whole span rather than a repeated step, so the last level lands exactly on
`upper` instead of a few wei short of it, and no level depends on the accumulated error
of the ones before it.

**`size_per_level` is stated once, in the quote token.** A buy commits it directly. A
sell commits what it is worth at that level's own price, so every level puts the same
value to work rather than the same quantity — which is what a grid is for. The
conversion floors, so a sell level is always for slightly less than the stated value and
never slightly more.

A level landing exactly on the reference price is dropped rather than assigned a side.
Either side there fires the moment the plan is built, which is a market order wearing a
grid level's clothes; `skipped_at_reference` says it happened.
"""

from dataclasses import dataclass

from web3 import Web3

from ...execution.intent import Condition
from ...hire.receipts import canonical_hash

# One rule, and a closed set so a second one has to be added deliberately: levels under
# the reference buy, levels over it sell.
SIDE_RULES = frozenset({"buy_below_sell_above"})
# This build has been exercised against 18-decimal tokens. The bound is a sanity check
# rather than a discovery: a base token with no decimals would floor every level's size
# to whole tokens, and anything worth less than one of them to nothing at all.
MIN_BASE_DECIMALS = 1
MAX_BASE_DECIMALS = 36


def _whole(value, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"grid: {name} must be an integer of atomic units, got {value!r}")
    return value


@dataclass(frozen=True)
class GridLevel:
    """One price the grid acts at, and everything that action needs except its bounds.

    `index` is the level's position in the requested ladder and survives a dropped
    level, so a caller's set of filled levels keeps meaning the same thing.
    """

    index: int
    price: int
    side: str
    token_in: str
    token_out: str
    size: int
    condition: Condition

    def as_record(self) -> dict:
        return {
            "index": self.index,
            "price": str(self.price),
            "side": self.side,
            "token_in": self.token_in,
            "token_out": self.token_out,
            "size": str(self.size),
            "condition": {
                "kind": self.condition.kind,
                "subject": self.condition.subject,
                "threshold": str(self.condition.threshold),
            },
        }


@dataclass(frozen=True)
class GridPlan:
    lower: int
    upper: int
    requested_levels: int
    size_per_level: int
    base: str
    quote: str
    base_decimals: int
    reference: int
    side_rule: str
    levels: tuple[GridLevel, ...]
    skipped_at_reference: int

    @property
    def plan_hash(self) -> str:
        """SHA-256 over the whole plan, inputs and derived levels alike.

        Covering the levels and not only the inputs is the point: it is the levels an
        intent commits to, and a change in how they are derived has to change the digest
        even when every input a user typed is identical.
        """
        return canonical_hash(self._body())

    def _body(self) -> dict:
        return {
            "lower": str(self.lower),
            "upper": str(self.upper),
            "requested_levels": self.requested_levels,
            "size_per_level": str(self.size_per_level),
            "base": self.base,
            "quote": self.quote,
            "base_decimals": self.base_decimals,
            "reference": str(self.reference),
            "side_rule": self.side_rule,
            "levels": [level.as_record() for level in self.levels],
            "skipped_at_reference": self.skipped_at_reference,
        }

    def as_record(self) -> dict:
        return self._body() | {"plan_hash": self.plan_hash}


def build_plan(
    *,
    lower: int,
    upper: int,
    levels: int,
    size_per_level: int,
    base: str,
    quote: str,
    base_decimals: int,
    reference: int,
    side_rule: str = "buy_below_sell_above",
) -> GridPlan:
    """The ladder, derived once and thereafter fixed."""
    for name, value in (
        ("lower", lower),
        ("upper", upper),
        ("levels", levels),
        ("size_per_level", size_per_level),
        ("base_decimals", base_decimals),
        ("reference", reference),
    ):
        _whole(value, name)
    if side_rule not in SIDE_RULES:
        raise ValueError(f"grid: side_rule {side_rule!r} is not one of {sorted(SIDE_RULES)}")
    if lower <= 0:
        raise ValueError("grid: lower must be a positive price")
    if upper <= lower:
        raise ValueError(f"grid: upper {upper} is not above lower {lower}")
    if levels < 2:
        raise ValueError("grid: a grid needs at least two levels — its two ends")
    if size_per_level <= 0:
        raise ValueError("grid: size_per_level must be positive")
    if reference <= 0:
        raise ValueError("grid: reference must be a positive price — it is what sides the levels")
    if not MIN_BASE_DECIMALS <= base_decimals <= MAX_BASE_DECIMALS:
        raise ValueError(
            f"grid: base_decimals {base_decimals} is outside "
            f"{MIN_BASE_DECIMALS}..{MAX_BASE_DECIMALS}"
        )

    base = Web3.to_checksum_address(base)
    quote = Web3.to_checksum_address(quote)
    if base == quote:
        raise ValueError("grid: base and quote are the same token, so there is nothing to trade")

    subject = f"{base}/{quote}"
    span = upper - lower
    built: list[GridLevel] = []
    skipped = 0
    for index in range(levels):
        price = lower + span * index // (levels - 1)
        if price == reference:
            skipped += 1
            continue
        if price < reference:
            side, token_in, token_out = "buy", quote, base
            size = size_per_level
            kind = "price_at_or_below"
        else:
            side, token_in, token_out = "sell", base, quote
            # What `size_per_level` of the quote token is worth in base at this level.
            size = size_per_level * 10**base_decimals // price
            kind = "price_at_or_above"
        if size <= 0:
            raise ValueError(
                f"grid: level {index} at {price} would commit nothing — {size_per_level} of "
                "the quote token floors to zero of the base token at that price"
            )
        built.append(
            GridLevel(
                index=index,
                price=price,
                side=side,
                token_in=token_in,
                token_out=token_out,
                size=size,
                condition=Condition(kind=kind, subject=subject, threshold=price),
            )
        )

    return GridPlan(
        lower=lower,
        upper=upper,
        requested_levels=levels,
        size_per_level=size_per_level,
        base=base,
        quote=quote,
        base_decimals=base_decimals,
        reference=reference,
        side_rule=side_rule,
        levels=tuple(built),
        skipped_at_reference=skipped,
    )


def next_action(plan: GridPlan, price: int, filled=()) -> GridLevel | None:
    """The one level this observation fires, or nothing.

    At most one side can ever be triggered: every buy sits below the reference and every
    sell above it, so a price cannot satisfy both. Among the levels of that side which
    the price has reached, the answer is the one nearest the reference — the first one it
    crossed. Taking the far one instead would fill at the best price on offer and leave
    the levels in between waiting for a price they have already passed.

    Nothing is remembered between calls. `filled` is the caller's record of which levels
    have already fired, which keeps this function a function.
    """
    _whole(price, "price")
    if not plan.lower <= price <= plan.upper:
        return None
    already = set(filled)
    reached = [
        level
        for level in plan.levels
        if level.index not in already and level.condition.holds(price)
    ]
    if not reached:
        return None
    if reached[0].side == "buy":
        return max(reached, key=lambda level: level.price)
    return min(reached, key=lambda level: level.price)
