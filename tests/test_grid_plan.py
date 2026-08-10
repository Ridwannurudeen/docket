"""The grid itself: arithmetic a reader can redo on paper.

Nothing here touches a network or a chain, and the plan hash is what makes that worth
something — the same inputs produce the same levels and the same digest on any machine,
so an intent that commits to a level can be checked against a plan somebody else
rebuilt. A grid whose levels drifted between runs would make every commitment built on
it unverifiable.
"""

import inspect
import re

import pytest

from docket.agents.grid import plan as plan_module
from docket.agents.grid.plan import SIDE_RULES, GridPlan, build_plan, next_action
from docket.api.models import BANNED_FIELD_NAMES

USDT = "0x55d398326f99059fF775485246999027B3197955"
WBNB = "0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c"
E18 = 10**18


def _plan(**overrides) -> GridPlan:
    """Five levels from 500 to 700 USDT per WBNB, referenced at 620."""
    fields = {
        "lower": 500 * E18,
        "upper": 700 * E18,
        "levels": 5,
        "size_per_level": 25 * E18,
        "base": WBNB,
        "quote": USDT,
        "base_decimals": 18,
        "reference": 620 * E18,
    }
    fields.update(overrides)
    return build_plan(**fields)


# ------------------------------------------------------------------- the levels


def test_the_levels_are_ordered_and_evenly_spaced_to_the_wei():
    prices = [level.price for level in _plan().levels]
    assert prices == [500 * E18, 550 * E18, 600 * E18, 650 * E18, 700 * E18]
    assert prices == sorted(prices)


def test_spacing_that_does_not_divide_evenly_is_still_exact_and_lands_on_both_ends():
    """Integer arithmetic throughout, so a range that does not divide by the gaps still
    starts at `lower` and ends at `upper` rather than drifting a wei off either."""
    grid = _plan(lower=100, upper=200, levels=7, size_per_level=1000, reference=150)
    prices = [level.price for level in grid.levels] + [grid.reference]
    assert min(prices) >= 100 and max(prices) <= 200
    assert grid.levels[0].price == 100
    assert grid.levels[-1].price == 200
    assert [level.price for level in grid.levels] == [100, 116, 133, 166, 183, 200]


def test_two_levels_is_the_smallest_grid_and_it_is_the_two_ends():
    grid = _plan(levels=2)
    assert [level.price for level in grid.levels] == [500 * E18, 700 * E18]


# --------------------------------------------------------------------- the sides


def test_levels_below_the_reference_buy_and_levels_above_it_sell():
    grid = _plan()
    sides = {level.price: level.side for level in grid.levels}
    assert sides[500 * E18] == "buy"
    assert sides[550 * E18] == "buy"
    assert sides[600 * E18] == "buy"
    assert sides[650 * E18] == "sell"
    assert sides[700 * E18] == "sell"


def test_a_buy_waits_for_the_price_to_fall_to_it_and_a_sell_for_it_to_rise():
    grid = _plan()
    buy = next(level for level in grid.levels if level.price == 550 * E18)
    assert buy.condition.kind == "price_at_or_below"
    assert buy.condition.threshold == 550 * E18
    sell = next(level for level in grid.levels if level.price == 650 * E18)
    assert sell.condition.kind == "price_at_or_above"


def test_a_level_landing_exactly_on_the_reference_is_dropped_and_counted():
    """It has no side. A buy there fires the instant the plan is built, which is a market
    order wearing a grid level's clothes, so it is left out and the count says so."""
    grid = _plan(reference=600 * E18)
    assert [level.price for level in grid.levels] == [
        500 * E18,
        550 * E18,
        650 * E18,
        700 * E18,
    ]
    assert grid.skipped_at_reference == 1
    assert _plan().skipped_at_reference == 0


def test_the_level_indexes_survive_a_dropped_level_so_a_filled_set_still_means_something():
    grid = _plan(reference=600 * E18)
    assert [level.index for level in grid.levels] == [0, 1, 3, 4]


# ---------------------------------------------------------------------- the size


def test_a_buy_spends_the_quote_token_and_a_sell_spends_the_base_token():
    grid = _plan()
    buy = next(level for level in grid.levels if level.side == "buy")
    assert (buy.token_in, buy.token_out) == (USDT, WBNB)
    sell = next(level for level in grid.levels if level.side == "sell")
    assert (sell.token_in, sell.token_out) == (WBNB, USDT)


def test_a_buy_commits_the_stated_size_and_a_sell_commits_what_that_is_worth_there():
    """One size, stated in the quote token. A sell level converts it at that level's own
    price, so every level commits the same value rather than the same quantity."""
    grid = _plan()
    buy = next(level for level in grid.levels if level.price == 550 * E18)
    assert buy.size == 25 * E18
    sell = next(level for level in grid.levels if level.price == 650 * E18)
    assert sell.size == 25 * E18 * E18 // (650 * E18)
    assert sell.size == 38461538461538461  # 25/650 WBNB, floored to the wei


def test_a_size_too_small_to_buy_anything_at_a_level_is_refused():
    with pytest.raises(ValueError):
        _plan(size_per_level=1, reference=1)


# ---------------------------------------------------------------- what is refused


@pytest.mark.parametrize(
    "overrides",
    [
        {"lower": 0},
        {"lower": -1},
        {"upper": 500 * E18},
        {"upper": 400 * E18},
        {"levels": 1},
        {"levels": 0},
        {"size_per_level": 0},
        {"reference": 0},
        {"base_decimals": 0},
        {"base_decimals": 40},
        {"base": USDT},
        {"lower": 500.5},
    ],
)
def test_a_grid_that_is_not_a_grid_is_refused(overrides):
    with pytest.raises(ValueError):
        _plan(**overrides)


def test_the_side_rule_is_a_closed_vocabulary():
    assert SIDE_RULES == frozenset({"buy_below_sell_above"})
    with pytest.raises(ValueError):
        _plan(side_rule="follow_the_trend")


# ------------------------------------------------------------------ next action


def test_a_price_below_the_band_yields_no_action():
    assert next_action(_plan(), 499 * E18) is None


def test_a_price_above_the_band_yields_no_action():
    assert next_action(_plan(), 701 * E18) is None


def test_a_price_exactly_at_the_reference_triggers_nothing():
    """Every buy sits below it and every sell above, so neither predicate holds. The grid
    is waiting, which is the state it spends most of its life in."""
    assert next_action(_plan(reference=620 * E18), 620 * E18) is None


def test_a_price_reaching_a_buy_level_returns_that_level():
    level = next_action(_plan(), 600 * E18)
    assert level is not None
    assert level.side == "buy" and level.price == 600 * E18


def test_a_price_that_fell_past_several_levels_returns_the_nearest_one_first():
    """The one it crossed first. Filling from the far end would take the best price
    available and leave the levels in between to fire on a lower one later."""
    grid = _plan()
    assert next_action(grid, 500 * E18).price == 600 * E18
    assert next_action(grid, 500 * E18, filled=(2,)).price == 550 * E18
    assert next_action(grid, 500 * E18, filled=(1, 2)).price == 500 * E18


def test_a_price_that_rose_past_several_sell_levels_mirrors_it():
    grid = _plan()
    assert next_action(grid, 700 * E18).price == 650 * E18
    assert next_action(grid, 700 * E18, filled=(3,)).price == 700 * E18


def test_a_filled_level_does_not_fire_again():
    grid = _plan()
    level = next_action(grid, 600 * E18)
    assert next_action(grid, 600 * E18, filled=(level.index,)) is None


def test_a_grid_with_everything_filled_yields_no_action():
    grid = _plan()
    assert next_action(grid, 520 * E18, filled=tuple(lv.index for lv in grid.levels)) is None


def test_a_price_that_is_not_a_whole_number_of_atomic_units_is_refused():
    with pytest.raises(ValueError):
        next_action(_plan(), 600.5)


# ------------------------------------------------------------------- the plan hash


def test_the_same_inputs_always_produce_the_same_plan_hash():
    assert _plan().plan_hash == _plan().plan_hash
    assert _plan().plan_hash.startswith("0x")
    assert len(_plan().plan_hash) == 66


@pytest.mark.parametrize(
    "overrides",
    [
        {"lower": 501 * E18},
        {"upper": 701 * E18},
        {"levels": 6},
        {"size_per_level": 26 * E18},
        {"reference": 621 * E18},
        {"base_decimals": 8},
    ],
)
def test_any_changed_input_is_a_different_plan(overrides):
    assert _plan(**overrides).plan_hash != _plan().plan_hash


def test_the_hash_covers_the_derived_levels_and_not_only_the_inputs():
    grid = _plan()
    record = grid.as_record()
    assert len(record["levels"]) == len(grid.levels)
    assert record["plan_hash"] == grid.plan_hash
    assert record["levels"][0]["price"] == str(500 * E18)


# ------------------------------------------------------------------------ purity


def test_this_module_cannot_reach_a_network():
    """Determinism is the product here. A plan that consulted anything would be a plan
    that could answer differently on the machine checking it."""
    source = inspect.getsource(plan_module)
    for reach in ("httpx", "requests", "HTTPProvider", "eth_call", ".eth.", "urllib"):
        assert reach not in source, reach


def test_no_side_or_field_name_carries_verdict_language():
    names = ["buy", "sell", *SIDE_RULES, *GridPlan.__dataclass_fields__]
    names += list(_plan().levels[0].__dataclass_fields__)
    for name in names:
        for word in BANNED_FIELD_NAMES:
            assert not re.search(rf"\b{re.escape(word)}\b", name.lower()), name
