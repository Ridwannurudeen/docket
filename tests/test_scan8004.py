import httpx
import pytest

from docket.scan8004 import API_BASE, Scan8004Client


def _client(handler) -> Scan8004Client:
    return Scan8004Client(transport=httpx.MockTransport(handler))


def test_list_agents_sends_snake_case_params_and_returns_total():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(dict(request.url.params))
        return httpx.Response(200, json={"items": [{"agent_id": "a"}], "total": 42})

    items, total = _client(handler).list_agents(56, limit=100, offset=200, min_feedbacks=1)
    assert items == [{"agent_id": "a"}]
    assert total == 42
    assert seen["chain_id"] == "56"
    assert seen["limit"] == "100"
    assert seen["offset"] == "200"
    assert seen["min_feedbacks"] == "1"
    assert seen["sort_by"] == "token_id"
    assert seen["sort_order"] == "asc"


def test_limit_is_capped_at_100():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["limit"] == "100"
        return httpx.Response(200, json={"items": [], "total": 0})

    _client(handler).list_agents(56, limit=5000)


def test_retries_transport_errors_then_succeeds():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] < 3:
            raise httpx.ConnectError("getaddrinfo failed", request=request)
        return httpx.Response(200, json={"items": [], "total": 0})

    items, total = _client(handler).list_agents(56)
    assert calls["n"] == 3 and items == [] and total == 0


def test_gives_up_after_max_attempts():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("getaddrinfo failed", request=request)

    with pytest.raises(httpx.ConnectError):
        _client(handler).list_agents(56)


def test_retries_429_then_succeeds():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, json={"detail": "slow down"})
        return httpx.Response(200, json={"items": [], "total": 7})

    _, total = _client(handler).list_agents(56)
    assert calls["n"] == 2 and total == 7


def test_api_base_is_the_internal_endpoint():
    assert API_BASE == "https://8004scan.io/api/v1"
