import httpx

from docket.enrich import enrich_callable, extract_endpoints
from docket.scan8004 import Scan8004Client
from docket.store import Store

DETAIL = {
    "a2a_endpoint": "https://a.example/a2a",
    "mcp_server": "https://a.example/mcp",
    "agent_url": "https://a.example",
    "services": {"oasf": {"endpoint": "https://a.example/oasf"}},
}


def test_extract_endpoints_reads_every_shape():
    got = {(e["kind"], e["url"]) for e in extract_endpoints(DETAIL)}
    assert ("a2a", "https://a.example/a2a") in got
    assert ("mcp", "https://a.example/mcp") in got
    assert ("web", "https://a.example") in got
    assert ("service", "https://a.example/oasf") in got


def test_extract_endpoints_ignores_nulls_and_blanks():
    assert extract_endpoints({"a2a_endpoint": None, "mcp_server": "", "agent_url": "   "}) == []


def test_extract_endpoints_survives_unexpected_services_shapes():
    for services in (None, [], "nope", {"x": None}, {"x": {"endpoint": None}}, {"x": "str"}):
        assert isinstance(extract_endpoints({"services": services}), list)


def _store_with(agents, tmp_path):
    store = Store(tmp_path / "d.sqlite3")
    sid = store.begin_snapshot(chain_id=56, expected=None)
    store.upsert_agents(agents, sid)
    return store, sid


def test_only_declared_callable_agents_are_fetched(tmp_path):
    agents = [
        {"agent_id": "56:r:1", "token_id": "1", "chain_id": 56, "supported_protocols": ["A2A"]},
        {"agent_id": "56:r:2", "token_id": "2", "chain_id": 56, "supported_protocols": ["Web"]},
        {"agent_id": "56:r:3", "token_id": "3", "chain_id": 56, "supported_protocols": []},
        {"agent_id": "56:r:4", "token_id": "4", "chain_id": 56, "supported_protocols": ["MCP"]},
    ]
    store, sid = _store_with(agents, tmp_path)
    fetched = []

    def handler(request: httpx.Request) -> httpx.Response:
        fetched.append(str(request.url).rsplit("/", 1)[-1])
        return httpx.Response(200, json=DETAIL)

    client = Scan8004Client(transport=httpx.MockTransport(handler), pace=False)
    result = enrich_callable(store, client, sid)
    assert sorted(fetched) == ["1", "4"]  # Web-only and empty are not fetched
    assert result["considered"] == 2 and result["fetched"] == 2
    assert store.endpoint_count(sid) == 8  # 4 endpoints x 2 agents


def test_rerun_skips_already_enriched(tmp_path):
    agents = [
        {"agent_id": "56:r:1", "token_id": "1", "chain_id": 56, "supported_protocols": ["A2A"]}
    ]
    store, sid = _store_with(agents, tmp_path)
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(200, json=DETAIL)

    client = Scan8004Client(transport=httpx.MockTransport(handler), pace=False)
    enrich_callable(store, client, sid)
    second = enrich_callable(store, client, sid)
    assert calls["n"] == 1  # not re-fetched
    assert second["skipped_already_enriched"] == 1


def test_agent_with_no_endpoints_is_still_marked_enriched(tmp_path):
    agents = [
        {"agent_id": "56:r:1", "token_id": "1", "chain_id": 56, "supported_protocols": ["A2A"]}
    ]
    store, sid = _store_with(agents, tmp_path)
    client = Scan8004Client(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json={})), pace=False
    )
    result = enrich_callable(store, client, sid)
    assert result["with_endpoints"] == 0
    assert store.enriched_agent_ids(sid) == {"56:r:1"}  # so a re-run does not refetch it
