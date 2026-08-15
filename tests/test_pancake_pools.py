import httpx
import pytest

from docket.agents.pancake.pools import (
    PoolClient,
    is_plausible,
    net_fee_apr,
    turnover,
)

# Shape verified live 2026-08-08 against explorer.pancakeswap.com.
GOOD = {
    "id": "0xpool",
    "feeTier": 500,
    "token0": {
        "symbol": "USDT",
        "id": "0x55d398326f99059ff775485246999027b3197955",
        "decimals": 18,
    },
    "token1": {
        "symbol": "USDC",
        "id": "0x8ac76a51cc950d9822d68b83fe1ad97b32cd580d",
        "decimals": 18,
    },
    "tvlUSD": "1000000",
    "volumeUSD24h": "500000",
    "feeUSD24h": "250",
    "protocolFeeUSD24h": "85",
}
# Verified real garbage: COSA/BTCB reported $26.7M TVL on $746 of 24h volume.
JUNK = {
    **GOOD,
    "token0": {"symbol": "COSA", "id": "0xdeadbeef", "decimals": 18},
    "tvlUSD": "26744017",
    "volumeUSD24h": "746",
    "feeUSD24h": "1",
    "protocolFeeUSD24h": "0",
}


def test_net_fee_apr_excludes_the_protocol_cut():
    """LPs keep roughly two thirds of fees; using gross overstates yield by ~33%."""
    apr = net_fee_apr(GOOD)
    assert apr == pytest.approx((250 - 85) * 365 / 1_000_000, rel=1e-9)
    gross = 250 * 365 / 1_000_000
    assert apr < gross


def test_net_fee_apr_is_zero_when_tvl_is_zero():
    assert net_fee_apr({**GOOD, "tvlUSD": "0"}) == 0.0


def test_turnover_is_volume_over_tvl():
    assert turnover(GOOD) == pytest.approx(0.5)


def test_allowlisted_pool_with_real_volume_is_plausible():
    allow = {GOOD["token0"]["id"], GOOD["token1"]["id"]}
    ok, reason = is_plausible(GOOD, allow)
    assert ok is True and reason == "ok"


def test_pool_with_unlisted_token_is_rejected():
    allow = {GOOD["token1"]["id"]}
    ok, reason = is_plausible(JUNK, allow)
    assert ok is False and "allowlist" in reason


def test_pool_below_min_tvl_is_rejected():
    allow = {GOOD["token0"]["id"], GOOD["token1"]["id"]}
    ok, reason = is_plausible({**GOOD, "tvlUSD": "500"}, allow)
    assert ok is False and "tvl" in reason


def test_absurd_turnover_is_rejected_as_implausible():
    allow = {GOOD["token0"]["id"], GOOD["token1"]["id"]}
    ok, reason = is_plausible({**GOOD, "volumeUSD24h": "999999999"}, allow)
    assert ok is False and "turnover" in reason


def test_top_pools_parses_the_live_response_shape():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[GOOD, JUNK])

    pools = PoolClient(transport=httpx.MockTransport(handler)).top_pools()
    assert len(pools) == 2 and pools[0]["id"] == "0xpool"


def test_snapshot_reads_preserve_the_exact_http_response_bytes():
    raw = b'[ {"id":"0xpool", "feeUSD24h":"250"} ]\n'

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=raw)

    rows, observed = PoolClient(
        transport=httpx.MockTransport(handler)
    ).top_pools_snapshot()
    assert rows == [{"id": "0xpool", "feeUSD24h": "250"}]
    assert observed == raw


def test_client_retries_transport_errors():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] < 3:
            raise httpx.ConnectError("getaddrinfo failed", request=request)
        return httpx.Response(200, json=[GOOD])

    pools = PoolClient(transport=httpx.MockTransport(handler)).top_pools()
    assert calls["n"] == 3 and len(pools) == 1
