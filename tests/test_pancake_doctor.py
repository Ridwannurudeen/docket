import json
import re

import httpx
import pytest

from docket.agents.pancake.doctor import RATE_LIMITATION, diagnose, report
from docket.agents.pancake.pools import PoolClient

# Every fixture below is a real reading taken from BSC mainnet on 2026-08-08:
# token 7087132 (staked in MasterChefV3) in the QQQB/USDT 0.01% pool.
POSITION = {
    "token_id": 7087132,
    "staked": True,
    "token0": "0x205812CdBed920aFf76C6580abD681a46D11efc7",
    "token1": "0x55d398326f99059fF775485246999027B3197955",
    "fee": 100,
    "tick_lower": 65452,
    "tick_upper": 66052,
    "liquidity": 125256614773376725006,
    "tokens_owed0": 0,
    "tokens_owed1": 0,
    "block_number": 114739953,
    "observation_time": "2026-08-08T12:00:00+00:00",
}
POOL = {
    "address": "0xe531fcb1F5a195de7608B9F4f9518544C2cdB693",
    "tick": 65821,
    "sqrt_price_x96": 2128637418868180723784745824244,
    "liquidity": 21740148071633644244142639,
    "block_number": 114740301,
    "observation_time": "2026-08-08T12:01:00+00:00",
}
ROW = {
    "id": "0xe531fcb1f5a195de7608b9f4f9518544c2cdb693",
    "feeTier": 100,
    "token0": {"symbol": "QQQB", "id": "0x205812cdbed920aff76c6580abd681a46d11efc7"},
    "token1": {"symbol": "USDT", "id": "0x55d398326f99059ff775485246999027b3197955"},
    "tvlUSD": "3306485.2014337434",
    "volumeUSD24h": "38737134.0108538",
    "feeUSD24h": "3873.71340108392",
    "protocolFeeUSD24h": "1278.40200556144",
}
STATS = {"row": ROW, "plausible": True, "reason": "ok"}


def test_in_range_position_reports_in_range_and_a_positive_pool_apr():
    d = diagnose(POSITION, POOL, STATS)
    assert d["status"] == "in_range"
    assert d["in_range"] is True
    # Tick 65821 sits 61.5% of the way from 65452 to 66052.
    assert d["range_position_pct"] == pytest.approx((65821 - 65452) / 600)
    assert d["pool_net_apr"] == pytest.approx(
        (3873.71340108392 - 1278.40200556144) * 365 / 3306485.2014337434
    )
    assert d["as_of_block"] == 114740301
    # The stale-fee caveat travels with every diagnosis, including the 0/0 case,
    # because 0/0 reads as "no fees owed" when it means "not written since".
    assert any("not current uncollected fees" in f for f in d["findings"])


def test_one_position_supplies_decision_facts_and_recomputable_economics():
    """Percentage, percentage points and dollars are different units and all stay named."""
    value = 10_000.0
    cost = 25.0
    d = diagnose(
        POSITION,
        POOL,
        STATS,
        declared_position_value_usd=value,
        estimated_recenter_cost_usd=cost,
    )

    gross = 3873.71340108392 * 365 / 3306485.2014337434
    net = (3873.71340108392 - 1278.40200556144) * 365 / 3306485.2014337434
    gap = gross - net
    assert d["decision"] == (
        "Position 7087132 is inside its range and can currently earn pool fees."
    )
    assert d["verifiable_facts"] == {
        "pair": "QQQB/USDT",
        "position_id": 7087132,
        "token0": POSITION["token0"],
        "token1": POSITION["token1"],
        "current_tick": 65821,
        "lower_tick": 65452,
        "upper_tick": 66052,
        "bsc_block": 114740301,
        "observation_time": "2026-08-08T12:01:00+00:00",
    }
    economics = d["economic_consequence"]
    assert economics["gross_apr"] == pytest.approx(gross)
    assert economics["net_apr"] == pytest.approx(net)
    assert economics["overstatement_relative"] == pytest.approx(gap / net)
    assert economics["overstatement_percentage_points"] == pytest.approx(gap * 100)
    assert economics["declared_position_value_usd"] == value
    assert economics["annual_gross_usd"] == pytest.approx(value * gross)
    assert economics["annual_net_usd"] == pytest.approx(value * net)
    assert economics["annual_overstatement_usd"] == pytest.approx(value * gap)
    # Named for what they are: the pool's rate, and that rate applied to a declared
    # notional. Neither is this position's earnings, which depend on its share of the
    # liquidity active at the traded tick.
    assert economics["pool_net_apr_if_in_range"] == pytest.approx(net)
    assert economics["pool_rate_at_declared_value_usd"] == pytest.approx(value * net)
    assert economics["unavailable_reason"] is None

    conditional = d["conditional_actions"]
    assert {action["kind"] for action in conditional["actions"]} == {"wait", "recenter"}
    assert conditional["estimated_recenter_cost_usd"] == cost
    assert conditional["cost_only_break_even_days"] == pytest.approx(
        cost / (value * net / 365)
    )
    assert conditional["unavailable_reason"] is None


def test_dollars_and_break_even_degrade_when_no_values_were_declared():
    """The explorer supplies pool dollars, not this NFT's value or a recenter transaction cost."""
    d = diagnose(POSITION, POOL, STATS)

    economics = d["economic_consequence"]
    assert economics["gross_apr"] is not None
    assert economics["annual_overstatement_usd"] is None
    assert "declared_position_value_usd" in economics["unavailable_reason"]
    conditional = d["conditional_actions"]
    assert conditional["estimated_recenter_cost_usd"] is None
    assert conditional["cost_only_break_even_days"] is None
    assert "estimated_recenter_cost_usd" in conditional["unavailable_reason"]


def test_missing_protocol_fee_data_refuses_every_derived_economic_figure():
    """Absent protocol fees are unknown, not zero; net must not silently become gross."""
    row = {**ROW, "protocolFeeUSD24h": None}
    d = diagnose(POSITION, POOL, {"row": row, "plausible": True, "reason": "ok"})

    assert d["pool_net_apr"] is None
    economics = d["economic_consequence"]
    for field in (
        "gross_apr",
        "net_apr",
        "overstatement_relative",
        "overstatement_percentage_points",
        "annual_overstatement_usd",
    ):
        assert economics[field] is None
    assert "protocolFeeUSD24h" in economics["unavailable_reason"]


def test_tick_below_the_lower_bound_reports_zero_fees_earned():
    d = diagnose(POSITION, {**POOL, "tick": 65000}, STATS)
    assert d["status"] == "out_of_range_below"
    assert d["in_range"] is False
    assert d["range_position_pct"] == 0.0
    assert any("65000" in f and "65452" in f and "no fees" in f for f in d["findings"])
    # The pool rate is still reported, but as a rate this position is not earning.
    assert d["pool_net_apr"] > 0
    assert any("not earning" in f for f in d["findings"])


def test_tick_at_or_above_the_upper_bound_reports_zero_fees_earned():
    # 66052 exactly: the upper bound is exclusive, so this is already out of range.
    d = diagnose(POSITION, {**POOL, "tick": 66052}, STATS)
    assert d["status"] == "out_of_range_above"
    assert d["in_range"] is False
    assert d["range_position_pct"] == 1.0
    assert any("66052" in f and "no fees" in f for f in d["findings"])


def test_zero_liquidity_reports_closed_with_no_rebalance_action():
    d = diagnose({**POSITION, "liquidity": 0}, POOL, STATS)
    assert d["status"] == "closed"
    assert d["in_range"] is False
    assert d["actions"] == []
    assert any("liquidity is 0" in f for f in d["findings"])


def test_pool_that_failed_the_plausibility_gate_reports_the_reason_not_an_apr():
    # The real refusal from the live top-25 on 2026-08-08.
    reason = "token0 COSA is not on PancakeSwap's token allowlist"
    d = diagnose(POSITION, POOL, {"row": ROW, "plausible": False, "reason": reason})
    assert d["status"] == "in_range"
    assert d["pool_net_apr"] is None
    assert any(reason in f for f in d["findings"])
    assert not any("annualised" in f for f in d["findings"])


def test_diagnosis_never_uses_the_language_of_endorsement():
    """A gate that only filters fabrications must never read as an endorsement.

    Every branch is swept, because the temptation to reassure is strongest in
    the branches that carry bad news. Word-boundary matched on purpose:
    "safety" and "safest" slip past a naive substring check while carrying
    exactly the claim being banned.
    """
    cases = [
        (POSITION, POOL, STATS),
        (POSITION, {**POOL, "tick": 65000}, STATS),
        (POSITION, {**POOL, "tick": 66052}, STATS),
        ({**POSITION, "liquidity": 0}, POOL, STATS),
        (
            POSITION,
            POOL,
            {"row": ROW, "plausible": False, "reason": "tvl $500 is below"},
        ),
        (POSITION, POOL, None),
        (POSITION, None, None),
    ]
    for position, pool, stats in cases:
        d = diagnose(position, pool, stats)
        text = json.dumps({"findings": d["findings"], "actions": d["actions"]})
        banned = re.findall(
            r"\b(safe|safety|safest|recommended|guaranteed|best)\b", text, re.I
        )
        assert banned == [], f"endorsement language leaked from {d['status']}: {banned}"


class _StubReader:
    """A `PositionReader` with the network taken out, recording how it was called."""

    def __init__(self, read: dict) -> None:
        self._read = read
        self.calls: list[tuple] = []
        self.observation_blocks: list[int | None] = []

    def wallet_positions(
        self,
        address,
        *,
        limit=None,
        include_closed=False,
        token_id=None,
        observation_block=None,
    ):
        self.calls.append((address, limit, include_closed, token_id))
        self.observation_blocks.append(observation_block)
        # `scan_complete` defaults true here so a fixture that does not care about
        # truncation reads as a finished scan rather than an unknown one.
        return {
            "scan_complete": True,
            "stopped_by": None,
            "open_skipped": 0,
            "observation_block": 114739953,
            "observation_time": "2026-08-08T12:00:00+00:00",
            **self._read,
        }

    def pool_state(self, token0, token1, fee, *, observation_block=None):
        return POOL


def _pool_client() -> PoolClient:
    """A `PoolClient` served the one row the fixtures use, plus its allowlist."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "tokens.pancakeswap.finance":
            return httpx.Response(
                200,
                json={
                    "tokens": [
                        {"chainId": 56, "address": ROW["token0"]["id"]},
                        {"chainId": 56, "address": ROW["token1"]["id"]},
                    ]
                },
            )
        return httpx.Response(200, json=[ROW])

    return PoolClient(transport=httpx.MockTransport(handler))


def test_report_counts_the_closed_positions_it_left_out():
    """A short list must not be able to pass for the whole wallet."""
    reader = _StubReader(
        {
            "positions": [POSITION],
            "positions_held": 155,
            "positions_examined": 40,
            "closed_skipped": 39,
        }
    )
    with _pool_client() as client:
        out = report("0xwallet", reader=reader, pools=client)

    assert out["positions_held"] == 155
    assert out["positions_examined"] == 40
    assert out["closed_skipped"] == 39
    assert len(out["positions"]) == 1
    assert out["positions"][0]["diagnosis"]["status"] == "in_range"


def test_report_can_use_the_frozen_pool_bytes_without_a_live_pool_client():
    reader = _StubReader(
        {
            "positions": [POSITION],
            "positions_held": 1,
            "positions_examined": 1,
            "closed_skipped": 0,
        }
    )
    sources = {
        "pools": {"sha256": "a" * 64},
        "token_list": {"sha256": "b" * 64},
    }

    out = report(
        "0xwallet",
        reader=reader,
        pool_rows=[ROW],
        token_allowlist={ROW["token0"]["id"], ROW["token1"]["id"]},
        source_evidence=sources,
    )

    assert out["sources"] == sources
    assert out["positions"][0]["pool"]["address"].lower() == ROW["id"]


def test_report_passes_the_bounds_through_to_the_reader():
    reader = _StubReader(
        {
            "positions": [{**POSITION, "liquidity": 0}],
            "positions_held": 4,
            "positions_examined": 2,
            "closed_skipped": 0,
        }
    )
    with _pool_client() as client:
        out = report(
            "0xwallet", reader=reader, pools=client, limit=2, include_closed=True
        )

    assert reader.calls == [("0xwallet", 2, True, None)]
    # `include_closed` reaches the diagnosis: the closed position is reported, not dropped.
    assert out["positions"][0]["diagnosis"]["status"] == "closed"
    assert out["positions"][0]["pool"] is None


def test_an_empty_result_says_which_empty_it_is():
    """`[]` is the most misleading thing this agent can return.

    A wallet holding nothing, a wallet holding only closed positions, and a wallet whose open
    positions were never reached all produce the same empty list. The live evidence wallet is
    the second of those — 21 held, 21 read, all 21 closed — and a reader given `[]` with no
    sentence could reasonably conclude their positions were fine.
    """
    reader = _StubReader(
        {
            "positions": [],
            "positions_held": 21,
            "positions_examined": 21,
            "closed_skipped": 21,
            "scan_complete": True,
        }
    )
    with _pool_client() as client:
        out = report("0xwallet", reader=reader, pools=client)

    assert out["positions"] == []
    assert out["scan_complete"] is True
    assert out["decision"] == (
        "All 21 PancakeSwap v3 positions in this wallet are closed; none currently earns "
        "pool fees."
    )
    assert out["observation"] == {
        "bsc_block": 114739953,
        "observation_time": "2026-08-08T12:00:00+00:00",
    }
    coverage = out["coverage"]
    assert "all 21" in coverage
    assert "every one of the 21 is closed" in coverage
    assert "no position to diagnose" in coverage
    assert "no active position was available" in out["primary_limitation"].lower()


def test_a_truncated_empty_result_refuses_to_call_the_unread_positions_closed():
    """Bounded and empty is not the same claim as complete and empty."""
    reader = _StubReader(
        {
            "positions": [],
            "positions_held": 40,
            "positions_examined": 30,
            "closed_skipped": 30,
            "scan_complete": False,
            "stopped_by": "limit",
        }
    )
    with _pool_client() as client:
        out = report("0xwallet", reader=reader, pools=client)

    coverage = out["coverage"]
    assert "of the 40 position NFTs this wallet holds, 30 were read" in coverage
    assert "whether the rest are open is unknown" in coverage
    assert "raise `limit`" in coverage
    assert "No position decision is possible" in out["decision"]
    assert "unread positions are unknown" in out["primary_limitation"]


def test_the_remedy_matches_the_bound_that_actually_stopped_the_read():
    """Two bounds stop a scan and only one of them is the caller's to move.

    Telling somebody to raise `limit` when the work ceiling truncated the read is an
    instruction that cannot work, and a caller who follows it and sees no change learns the
    wrong thing about their own wallet.
    """
    base = {
        "positions": [],
        "positions_held": 90,
        "positions_examined": 30,
        "closed_skipped": 30,
        "scan_complete": False,
    }
    with _pool_client() as client:
        by_ceiling = report(
            "0xwallet",
            reader=_StubReader(base | {"stopped_by": "max_examined"}),
            pools=client,
        )["coverage"]
        by_limit = report(
            "0xwallet", reader=_StubReader(base | {"stopped_by": "limit"}), pools=client
        )["coverage"]

    assert "raising `limit` will not reach further" in by_ceiling
    assert "examines at most 30 position NFTs" in by_ceiling
    assert "raise `limit` to return more" in by_limit
    assert "will not reach further" not in by_limit


def test_a_wallet_with_no_positions_at_all_is_its_own_sentence():
    reader = _StubReader(
        {
            "positions": [],
            "positions_held": 0,
            "positions_examined": 0,
            "closed_skipped": 0,
            "scan_complete": True,
        }
    )
    with _pool_client() as client:
        out = report("0xwallet", reader=reader, pools=client)

    assert out["coverage"] == (
        "This wallet holds no PancakeSwap v3 position NFTs, directly or staked."
    )


def test_every_report_carries_a_coverage_sentence_even_when_it_found_something():
    reader = _StubReader(
        {
            "positions": [POSITION],
            "positions_held": 3,
            "positions_examined": 3,
            "closed_skipped": 2,
            "scan_complete": True,
        }
    )
    with _pool_client() as client:
        out = report("0xwallet", reader=reader, pools=client)

    assert "all 3 of this wallet's position NFTs were read" in out["coverage"]
    assert (
        "1 hold liquidity and are diagnosed below, and 2 are closed" in out["coverage"]
    )


def test_pancake_headline_leads_with_generated_dollars_and_payback(monkeypatch):
    decision_impact = {
        "registration_state": "post_hoc",
        "dollars_at_notionals": {
            "notionals": [
                {
                    "notional_usd": 43_210.0,
                    "n_pools": 17,
                    "median_annual_overstatement_usd": 654.32,
                }
            ]
        },
        "break_even_shift": {
            "n_moves": 88,
            "median_days_later_than_gross_implies": 9.75,
        },
        "ranking_reversals": {"numerator": 4, "denominator": 136},
    }
    monkeypatch.setattr(
        "docket.advantage.v2.report.decision_impact_section",
        lambda: decision_impact,
    )
    monkeypatch.setattr(
        "docket.agents.pancake.doctor._DECISION_IMPACT_SECTION", None
    )
    reader = _StubReader(
        {
            "positions": [POSITION],
            "positions_held": 1,
            "positions_examined": 1,
            "closed_skipped": 0,
        }
    )

    with _pool_client() as client:
        out = report("0xwallet", reader=reader, pools=client)

    headline = out["pancake_headline"]
    assert headline == {
        "statement": (
            "At a declared $43,210 fixed notional, the median annual fee overstatement "
            "across 17 eligible pools is $654.32. Across 88 candidate moves, real payback "
            "arrives a median 9.75 days later than gross implies. Ranking reversals were "
            "4/136. Registration state: post_hoc."
        ),
        "fixed_notional_usd": 43_210.0,
        "n_pools": 17,
        "median_annual_overstatement_usd": 654.32,
        "n_candidate_moves": 88,
        "median_payback_delay_days": 9.75,
        "ranking_reversals": {"numerator": 4, "denominator": 136},
        "registration_state": "post_hoc",
    }
    statement = headline["statement"]
    assert statement.index("$654.32") < statement.index("9.75 days later")
    assert statement.index("9.75 days later") < statement.index("4/136")
    assert (
        out["positions"][0]["diagnosis"]["economic_consequence"]["limitation"]
        == RATE_LIMITATION
    )


def test_reports_reuse_the_unchanged_frozen_decision_impact_headline(monkeypatch):
    from docket.advantage.v2.report import decision_impact_section

    calls = 0

    def counted_decision_impact_section():
        nonlocal calls
        calls += 1
        return decision_impact_section()

    monkeypatch.setattr(
        "docket.advantage.v2.report.decision_impact_section",
        counted_decision_impact_section,
    )
    monkeypatch.setattr(
        "docket.agents.pancake.doctor._DECISION_IMPACT_SECTION", None
    )
    reader = _StubReader(
        {
            "positions": [],
            "positions_held": 0,
            "positions_examined": 0,
            "closed_skipped": 0,
        }
    )
    report_kwargs = {
        "reader": reader,
        "pool_rows": [ROW],
        "token_allowlist": {ROW["token0"]["id"], ROW["token1"]["id"]},
        "source_evidence": {},
    }

    first = report("0xwallet", **report_kwargs)["pancake_headline"]
    second = report("0xwallet", **report_kwargs)["pancake_headline"]

    assert calls == 1
    assert second == first
    assert first["statement"] == (
        "At a declared $10,000 fixed notional, the median annual fee overstatement "
        "across 22 eligible pools is $126.78. Across 231 candidate moves, real payback "
        "arrives a median 8.30 days later than gross implies. Ranking reversals were "
        "0/231. Registration state: post_hoc."
    )


def test_no_field_claims_the_pool_rate_is_this_position_s_earnings():
    """The report used to publish `position_fee_apr`, and that name was a claim it could
    not support.

    A v3 position earns in proportion to its share of the liquidity active at the traded
    tick. This read never measures that, so a full-range position was being credited with
    the pool-wide rate it demonstrably does not earn. The number is still worth showing —
    it is what the pool paid, applied to a notional the caller declared — but only under a
    name that says so, and beside a limitation that says why it is not the same thing.
    """
    from pathlib import Path

    from docket.agents.pancake import doctor

    source = Path(doctor.__file__).read_text(encoding="utf-8")
    for retired in ("position_fee_apr", "position_annual_fee_usd"):
        assert retired not in source, f"{retired} asserts earnings it does not measure"

    limitation = doctor.RATE_LIMITATION.lower()
    assert "not this position's rate" in limitation
    assert "active at the traded tick" in limitation
    assert "fixed-notional proxy" in limitation
