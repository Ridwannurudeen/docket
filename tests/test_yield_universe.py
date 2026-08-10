"""The set a "highest available APR" claim is allowed to be about.

The honesty problem with routing to the highest yield is not the arithmetic, it is the
universe. "The highest APR" over an unstated set is a claim nobody can check and nobody
can falsify. Over a stated, reproducible one it is a fact.

So these tests hold three properties. Nothing is dropped in silence — every row that goes
in comes out on one side or the other, and every exclusion carries the reason. The set is
deterministic, in the source's own order, because an order this module chose would be a
ranking Docket does not publish. And the set describes itself: its size, its source, the
time it was observed and the thresholds it was gated on, so the claim it bounds can be
reproduced by somebody holding the same snapshot.
"""

import re

import pytest

from docket.api.models import BANNED_FIELD_NAMES
from docket.agents.yield_router.universe import (
    MAX_TURNOVER,
    MIN_TVL,
    UNIVERSE_BOUND,
    Exclusion,
    eligible_pools,
)

USDT = "0x55d398326f99059ff775485246999027b3197955"
USDC = "0x8ac76a51cc950d9822d68b83fe1ad97b32cd580d"
WBNB = "0xbb4cdb9cbd36b01bd1cbaebf2de08d9173bc095c"
ALLOWLIST = {USDT, USDC, WBNB}
OBSERVED = "2026-08-10T00:00:00Z"
SOURCE = "explorer.pancakeswap.com/api/cached/pools/v3/bsc/list/top"


def _pool(pool_id="0xaaa", **overrides):
    row = {
        "id": pool_id,
        "feeTier": 500,
        "token0": {"symbol": "USDT", "id": USDT},
        "token1": {"symbol": "USDC", "id": USDC},
        "tvlUSD": "1000000",
        "volumeUSD24h": "500000",
        "feeUSD24h": "250",
        "protocolFeeUSD24h": "82",
    }
    row.update(overrides)
    return row


def _universe(pools=None, allowlist=None):
    return eligible_pools(
        _pool() if pools is None else pools,
        ALLOWLIST if allowlist is None else allowlist,
        source=SOURCE,
        observed_at=OBSERVED,
    )


# --------------------------------------------------------------------- inclusion


def test_a_pool_that_clears_every_gate_is_included_unchanged():
    """Rows travel as served. A coerced copy is a row a reader cannot check against the
    source they were pointed at."""
    row = _pool()
    universe = _universe([row])
    assert universe.included == (row,)
    assert universe.excluded == ()


def test_the_gate_is_the_one_that_already_exists_rather_than_a_second_copy():
    """`pools.is_plausible` runs first and its reasons are carried verbatim, so this
    module cannot develop a different opinion about the same row."""
    universe = _universe([_pool(tvlUSD="500")])
    assert universe.included == ()
    assert "below the" in universe.excluded[0].reason
    assert universe.excluded[0].gate == "is_plausible"


# --------------------------------------------------------------------- exclusion


@pytest.mark.parametrize(
    "overrides,fragment",
    [
        ({"token0": {"symbol": "COSA", "id": "0xdeadbeef"}}, "allowlist"),
        ({"tvlUSD": "500"}, "below the"),
        ({"volumeUSD24h": "999999999999"}, "not plausible"),
        ({"feeUSD24h": None}, "fee"),
        ({"protocolFeeUSD24h": None}, "protocol"),
    ],
)
def test_every_excluded_pool_carries_the_reason_it_was_excluded(overrides, fragment):
    universe = _universe([_pool(**overrides)])
    assert universe.included == ()
    excluded = universe.excluded[0]
    assert isinstance(excluded, Exclusion)
    assert fragment in excluded.reason.lower()
    assert excluded.pool_id == "0xaaa"


def test_a_pool_missing_its_fee_figure_is_excluded_rather_than_quoted_at_zero():
    """`net_fee_apr` reads an absent fee as zero, so a row with no fee data would publish
    a 0% pool instead of an unquotable one — a figure that looks measured and is not."""
    universe = _universe([_pool(feeUSD24h=None)])
    assert "cannot be computed" in universe.excluded[0].reason
    assert universe.excluded[0].gate == "fee_data"


def test_a_pool_missing_the_protocol_cut_is_excluded_rather_than_overstated_by_a_third():
    """LPs keep 66-68% of the fee. Subtracting an absent protocol cut as zero overstates
    the yield by about a third, which is the exact overstatement Stage 1e was about."""
    universe = _universe([_pool(protocolFeeUSD24h=None)])
    reason = universe.excluded[0].reason.lower()
    assert "protocol" in reason
    assert "overstate" in reason


def test_a_pool_reporting_a_fee_of_zero_is_kept_because_zero_is_a_measurement():
    """Absent and zero are different claims. A quiet pool really did earn nothing, and
    excluding it would hide the low end of the set the comparison is bounded by."""
    universe = _universe([_pool(feeUSD24h="0", protocolFeeUSD24h="0")])
    assert len(universe.included) == 1


def test_nothing_is_dropped_in_silence():
    pools = [_pool("0xaaa"), _pool("0xbbb", tvlUSD="10"), _pool("0xccc", feeUSD24h=None)]
    universe = _universe(pools)
    accounted = [row["id"] for row in universe.included]
    accounted += [row.pool_id for row in universe.excluded]
    assert sorted(accounted) == ["0xaaa", "0xbbb", "0xccc"]


# ----------------------------------------------------------------- the descriptor


def test_the_included_set_is_deterministic_and_keeps_the_source_order():
    """An order this module chose would be a ranking, and Docket publishes none. The
    source's order is the source's claim, not Docket's."""
    pools = [_pool("0xccc"), _pool("0xaaa"), _pool("0xbbb")]
    first = _universe(pools)
    second = _universe(pools)
    assert [row["id"] for row in first.included] == ["0xccc", "0xaaa", "0xbbb"]
    assert first.as_record() == second.as_record()


def test_the_universe_names_the_source_and_the_moment_it_was_observed():
    record = _universe([_pool()]).as_record()
    assert record["source"] == SOURCE
    assert record["observed_at"] == OBSERVED


def test_the_universe_states_its_own_size_on_both_sides():
    universe = _universe([_pool("0xaaa"), _pool("0xbbb", tvlUSD="10")])
    record = universe.as_record()
    assert record["size"] == 1
    assert record["considered"] == 2
    assert record["excluded_count"] == 1


def test_the_thresholds_the_set_was_gated_on_travel_with_it():
    """A set nobody can reproduce is a set nobody can check the claim against."""
    record = _universe([_pool()]).as_record()
    assert record["min_tvl_usd"] == MIN_TVL
    assert record["max_turnover"] == MAX_TURNOVER
    assert record["allowlist_size"] == len(ALLOWLIST)


def test_the_universe_says_what_highest_is_allowed_to_mean():
    record = _universe([_pool()]).as_record()
    assert record["bound"] == UNIVERSE_BOUND
    lowered = UNIVERSE_BOUND.lower()
    assert "within" in lowered
    assert "not" in lowered


def test_an_empty_universe_is_a_real_answer_and_says_so():
    universe = _universe([_pool(tvlUSD="1")])
    assert universe.included == ()
    assert universe.as_record()["size"] == 0
    assert "no pool" in universe.as_record()["bound_note"].lower()


def test_the_descriptor_carries_every_exclusion_so_the_gate_can_be_audited():
    record = _universe([_pool("0xbbb", tvlUSD="10")]).as_record()
    assert record["excluded"][0]["pool_id"] == "0xbbb"
    assert record["excluded"][0]["reason"]
    assert record["excluded"][0]["gate"] == "is_plausible"


def test_no_string_the_universe_publishes_carries_verdict_language():
    record = _universe([_pool("0xaaa"), _pool("0xbbb", tvlUSD="10")]).as_record()

    def strings(value):
        if isinstance(value, str):
            return [value]
        if isinstance(value, dict):
            return [s for k, v in value.items() for s in strings(k) + strings(v)]
        if isinstance(value, list):
            return [s for v in value for s in strings(v)]
        return []

    for text in strings(record):
        for word in BANNED_FIELD_NAMES:
            assert not re.search(rf"\b{re.escape(word)}\b", text.lower()), (
                f"the universe carries verdict language {word!r} in {text[:70]!r}"
            )
