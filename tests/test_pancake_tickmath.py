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
    assert in_range(LOWER, UPPER, UPPER) is False  # upper bound is exclusive
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
