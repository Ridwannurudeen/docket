import pytest
from fastapi.testclient import TestClient

from docket.api import create_app
from docket.store import Store

AGENT = {
    "agent_id": "56:0xreg:136384",
    "token_id": "136384",
    "chain_id": 56,
    "name": "SOLVENT",
    "description": "glass-box trader",
    "owner_address": "0xabc",
    "supported_protocols": ["A2A"],
    "x402_supported": True,
    "total_feedbacks": 3,
    "total_score": 12.0,
}
QUIET = {
    "agent_id": "56:0xreg:999",
    "token_id": "999",
    "chain_id": 56,
    "name": "Agent #999",
    "supported_protocols": [],
    "total_feedbacks": 0,
}


@pytest.fixture
def client(tmp_path):
    db = tmp_path / "d.sqlite3"
    store = Store(db)
    sid = store.begin_snapshot(chain_id=56, expected=2)
    store.upsert_agents([AGENT, QUIET], sid)
    store.upsert_endpoints(
        [{"agent_id": AGENT["agent_id"], "kind": "a2a", "url": "https://a.example/a2a"}], sid
    )
    store.record_liveness(
        [
            {
                "snapshot_id": sid,
                "agent_id": AGENT["agent_id"],
                "url": "https://a.example/a2a",
                "observed_at": "2026-08-07T10:00:00+00:00",
                "outcome": "responded",
                "status_code": 200,
                "elapsed_ms": 120,
                "detail": None,
            }
        ]
    )
    store.finish_snapshot(sid, sampled=2, expected=2)
    return TestClient(create_app(db, snapshot_id=sid))


def test_health_names_the_snapshot_it_serves(client):
    body = client.get("/health").json()
    assert body["status"] == "ok"
    assert body["snapshot_id"] == 1


def test_root_points_an_agent_at_its_documentation(client):
    body = client.get("/").json()
    for key in ("llms_txt", "openapi", "stats", "agents"):
        assert key in body


def test_stats_never_reports_a_number_without_coverage(client):
    body = client.get("/stats").json()
    cov = body["coverage"]
    assert cov["sampled"] == 2 and cov["expected"] == 2 and cov["dropped"] == 0
    assert cov["complete"] is True and cov["snapshot_id"] == 1
    assert body["with_feedback"] == 1
    assert "probe_method" in body and body["probe_method"]


def test_responded_pct_divides_by_probed_not_by_registry(client):
    body = client.get("/stats").json()
    # 1 endpoint probed, 1 responded -> 100% of probed, NOT 50% of the 2 agents.
    assert body["endpoints_probed"] == 1
    assert body["endpoints_responded"] == 1
    assert body["responded_pct_of_probed"] == 100.0


def test_agents_list_is_filterable_and_states_coverage(client):
    body = client.get("/agents").json()
    assert body["total"] == 2 and len(body["items"]) == 2
    assert body["coverage"]["snapshot_id"] == 1
    only = client.get("/agents", params={"has_feedback": "true"}).json()
    assert only["total"] == 1
    assert only["items"][0]["agent_id"] == AGENT["agent_id"]
    callable_only = client.get("/agents", params={"declares_callable": "true"}).json()
    assert callable_only["total"] == 1


def test_agent_detail_resolves_a_colon_bearing_id_and_carries_observations(client):
    body = client.get(f"/agents/{AGENT['agent_id']}").json()
    assert body["agent_id"] == AGENT["agent_id"]
    assert body["endpoints"] == ["https://a.example/a2a"]
    assert len(body["observations"]) == 1
    obs = body["observations"][0]
    assert obs["outcome"] == "responded" and obs["status_code"] == 200
    assert obs["observed_at"].startswith("2026-08-07")


def test_unknown_agent_returns_a_structured_actionable_error(client):
    resp = client.get("/agents/56:0xreg:404404")
    assert resp.status_code == 404
    err = resp.json()["error"]
    assert err["code"] == "agent_not_found"
    assert err["message"]  # tells the caller what to do


def test_limit_is_capped_and_offset_paginates(client):
    body = client.get("/agents", params={"limit": 5000}).json()
    assert body["limit"] == 100
    page2 = client.get("/agents", params={"limit": 1, "offset": 1}).json()
    assert len(page2["items"]) == 1 and page2["offset"] == 1


def test_bad_query_value_returns_the_structured_error_shape(client):
    resp = client.get("/agents", params={"limit": "banana"})
    assert resp.status_code == 422
    assert "error" in resp.json() and "code" in resp.json()["error"]


def test_openapi_is_served_so_an_agent_need_not_guess(client):
    spec = client.get("/openapi.json").json()
    assert "/agents" in spec["paths"] and "/stats" in spec["paths"]


def test_observation_is_filed_under_the_kind_that_was_probed(tmp_path):
    """A URL registered as both mcp and service was probed because it is mcp. Reporting the
    observation under `service` would misstate why the request was made — and on the live
    snapshot 35 of 35 probed endpoints carry a second `service` registration."""
    db = tmp_path / "kinds.sqlite3"
    store = Store(db)
    sid = store.begin_snapshot(chain_id=56, expected=1)
    store.upsert_agents([AGENT], sid)
    url = "https://a.example/mcp"
    store.upsert_endpoints(
        [
            {"agent_id": AGENT["agent_id"], "kind": "mcp", "url": url},
            {"agent_id": AGENT["agent_id"], "kind": "service", "url": url},
        ],
        sid,
    )
    store.record_liveness(
        [
            {
                "snapshot_id": sid,
                "agent_id": AGENT["agent_id"],
                "url": url,
                "observed_at": "2026-08-07T10:00:00+00:00",
                "outcome": "responded",
                "status_code": 200,
                "elapsed_ms": 90,
                "detail": None,
            }
        ]
    )
    store.finish_snapshot(sid, sampled=1, expected=1)
    client = TestClient(create_app(db, snapshot_id=sid))

    body = client.get(f"/agents/{AGENT['agent_id']}").json()
    assert body["endpoints"] == [url]
    assert body["observations"][0]["kind"] == "mcp"
