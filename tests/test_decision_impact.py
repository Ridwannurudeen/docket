"""Does the arithmetic error change a decision, or only a number?

The liquidity experiment proved gross overstates the rate an LP keeps by a median 49.3%. That
is a fact about a percentage. This module asks the harder question, and one of its three
answers is no — which is why the other two are worth anything.
"""

import json
from pathlib import Path

from docket.advantage.v2.decision_impact import (
    break_even_shift,
    dollars_at_notionals,
    ranking_reversals,
)

RUN = json.loads(
    (
        Path(__file__).resolve().parents[1]
        / "docket/advantage/v2/runs/01-liquidity-arithmetic.json"
    ).read_text(encoding="utf-8")
)
POOLS = RUN["pools"]


def test_a_reversal_needs_a_strict_disagreement_not_a_tie():
    """A tie in either ranking reorders nothing. Counting it would inflate the finding, and
    this is the measure the whole artifact leans on."""
    tied = [
        {"pool": "a", "gross_fee_apr": 0.10, "net_fee_apr": 0.05},
        {"pool": "b", "gross_fee_apr": 0.10, "net_fee_apr": 0.04},
    ]
    assert ranking_reversals(tied)["numerator"] == 0

    flipped = [
        {"pool": "a", "gross_fee_apr": 0.10, "net_fee_apr": 0.04},
        {"pool": "b", "gross_fee_apr": 0.09, "net_fee_apr": 0.06},
    ]
    result = ranking_reversals(flipped)
    assert result["numerator"] == 1
    assert result["reversed_pairs"][0]["gross_prefers"] == "a"
    assert result["reversed_pairs"][0]["net_prefers"] == "b"


def test_on_the_real_snapshot_the_ranking_does_not_change_and_that_is_published():
    """The finding that does NOT support the thesis.

    Over the 22 eligible pools, no pair reverses and the best pool is the same either way. So
    a provider choosing which pool to be in lands in the same place whether they read gross or
    net, and on that decision the error costs them nothing. Published because it is true, and
    because a decision-impact artifact that only reported the limbs that fired would be
    measuring its own conclusion.
    """
    result = ranking_reversals(POOLS)
    assert result["denominator"] == 231
    assert result["numerator"] == 0
    assert result["best_pool_changes"]["changes"] is False


def test_the_dollar_overstatement_is_real_and_scales_with_the_declared_notional():
    ten_k = dollars_at_notionals(POOLS, [10_000.0])["notionals"][0]
    hundred_k = dollars_at_notionals(POOLS, [100_000.0])["notionals"][0]

    assert ten_k["median_annual_overstatement_usd"] > 100
    # Linear in the notional, because that is all it is — arithmetic on a declared size.
    assert hundred_k["median_annual_overstatement_usd"] == (
        10 * ten_k["median_annual_overstatement_usd"]
    )
    assert "no wallet was read" in dollars_at_notionals(POOLS, [1.0])["what_this_measures"]


def test_reading_gross_makes_a_move_look_like_it_pays_back_sooner_than_it_does():
    """The optimistic error is the dangerous one: it is the one that talks somebody into
    acting. Positive days mean the real payback is later than the published figure implies."""
    shift = break_even_shift(POOLS, notional_usd=10_000.0, switching_cost_usd=25.0)
    assert shift["median_days_later_than_gross_implies"] > 0
    assert shift["n_pools"] == 22
    assert "not a forecast" in shift["what_it_does_not_measure"]


def test_break_even_refuses_to_divide_by_a_zero_rate():
    flat = [{"pool": "a", "gross_fee_apr": 0.0, "net_fee_apr": 0.0}]
    row = break_even_shift(flat, notional_usd=10_000.0, switching_cost_usd=25.0)["pools"][0]
    assert row["break_even_days_from_gross"] is None
    assert row["days_later_than_gross_implies"] is None


def test_a_pool_missing_either_rate_is_excluded_rather_than_assumed():
    """An absent net rate is unknown, not equal to gross."""
    partial = [
        {"pool": "a", "gross_fee_apr": 0.1, "net_fee_apr": None},
        {"pool": "b", "gross_fee_apr": 0.2, "net_fee_apr": 0.1},
    ]
    assert ranking_reversals(partial)["denominator"] == 0  # only one comparable pool
    assert dollars_at_notionals(partial, [1000.0])["notionals"][0]["n_pools"] == 1
