"""Tick and price conversions for PancakeSwap v3 ranges.

Display-grade, not consensus-grade. The pool itself works in 256-bit fixed point;
everything here runs in float64 and will disagree with the contract in the last
few digits. It is for telling a human where their range sits, and must never be
used to build a transaction — a mint or swap sized off these numbers would be
off by more than the fee tier it was meant to earn.

Everything downstream reads a range in ticks rather than price because ticks are
log-spaced: the midpoint of a range in tick space is its geometric midpoint in
price, which is what a concentrated position is actually centred on.
"""

import math

# A v3 pool stores sqrt(price) as a Q64.96 fixed-point integer.
Q96 = 2**96
TICK_BASE = 1.0001


def tick_to_price(tick: int, dec0: int, dec1: int) -> float:
    """Price of token0 in token1, adjusted for both decimals.

    The raw 1.0001^tick is a ratio of *base units*. Skipping the decimal
    adjustment on a 6dp/18dp pair silently reports a price off by 1e12.
    """
    return TICK_BASE**tick * 10 ** (dec0 - dec1)


def price_to_tick(price: float, dec0: int, dec1: int) -> int:
    """Inverse of `tick_to_price`, floored to the tick that contains the price."""
    raw = math.log(price / 10 ** (dec0 - dec1)) / math.log(TICK_BASE)
    return _snap(raw)


def in_range(tick_lower: int, tick_upper: int, current_tick: int) -> bool:
    """Whether a position is earning fees right now.

    Upper-exclusive, matching the pool: at exactly `tick_upper` the position
    holds only token1 and earns nothing.
    """
    return tick_lower <= current_tick < tick_upper


def range_position_pct(tick_lower: int, tick_upper: int, current_tick: int) -> float:
    """Where the current tick sits across the range: 0.0 at the lower bound, 1.0 at the upper.

    Clamped, so an out-of-range position reads as pinned to the edge it left
    rather than as a meaningless negative. A zero-width range reports 1.0: with
    the upper bound exclusive, no tick is ever inside it.
    """
    width = tick_upper - tick_lower
    if width <= 0:
        return 1.0
    return min(1.0, max(0.0, (current_tick - tick_lower) / width))


def sqrt_price_x96_to_tick(sqrt_price_x96: int) -> int:
    """Recover the tick from a pool's `slot0.sqrtPriceX96`."""
    price = (sqrt_price_x96 / Q96) ** 2
    return _snap(math.log(price) / math.log(TICK_BASE))


def _snap(raw: float) -> int:
    """Floor to a tick, but land on the exact integer when float error is all that
    separates us from it — a price built from tick N comes back as N - 1e-9, and a
    bare floor would report the position one tick lower than the pool has it."""
    nearest = round(raw)
    if abs(raw - nearest) < 1e-6:
        return int(nearest)
    return math.floor(raw)
