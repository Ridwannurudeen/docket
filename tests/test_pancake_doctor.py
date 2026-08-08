import json
import re

import pytest

from docket.agents.pancake.doctor import diagnose

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
