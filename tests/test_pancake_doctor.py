import json
import re

import httpx
import pytest

from docket.agents.pancake.doctor import diagnose, report
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
}
POOL = {
    "address": "0xe531fcb1F5a195de7608B9F4f9518544C2cdB693",
    "tick": 65821,
    "sqrt_price_x96": 2128637418868180723784745824244,
    "liquidity": 21740148071633644244142639,
    "block_number": 114740301,
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
        (POSITION, POOL, {"row": ROW, "plausible": False, "reason": "tvl $500 is below"}),
        (POSITION, POOL, None),
        (POSITION, None, None),
    ]
    for position, pool, stats in cases:
        d = diagnose(position, pool, stats)
        text = json.dumps({"findings": d["findings"], "actions": d["actions"]})
        banned = re.findall(r"\b(safe|safety|safest|recommended|guaranteed|best)\b", text, re.I)
        assert banned == [], f"endorsement language leaked from {d['status']}: {banned}"


class _StubReader:
    """A `PositionReader` with the network taken out, recording how it was called."""

    def __init__(self, read: dict) -> None:
        self._read = read
        self.calls: list[tuple] = []

    def wallet_positions(self, address, *, limit=None, include_closed=False):
        self.calls.append((address, limit, include_closed))
        # `scan_complete` defaults true here so a fixture that does not care about
        # truncation reads as a finished scan rather than an unknown one.
        return {"scan_complete": True, **self._read}

    def pool_state(self, token0, token1, fee):
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
        out = report("0xwallet", reader=reader, pools=client, limit=2, include_closed=True)

    assert reader.calls == [("0xwallet", 2, True)]
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
    coverage = out["coverage"]
    assert "all 21" in coverage
    assert "every one of the 21 is closed" in coverage
    assert "no position to diagnose" in coverage


def test_a_truncated_empty_result_refuses_to_call_the_unread_positions_closed():
    """Bounded and empty is not the same claim as complete and empty."""
    reader = _StubReader(
        {
            "positions": [],
            "positions_held": 40,
            "positions_examined": 30,
            "closed_skipped": 30,
            "scan_complete": False,
        }
    )
    with _pool_client() as client:
        out = report("0xwallet", reader=reader, pools=client)

    coverage = out["coverage"]
    assert "of the 40 position NFTs this wallet holds, 30 were read" in coverage
    assert "whether the rest are open is unknown" in coverage
    assert "raise `limit`" in coverage


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
    assert "1 hold liquidity and are diagnosed below, and 2 are closed" in out["coverage"]
