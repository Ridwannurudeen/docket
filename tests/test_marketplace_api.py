"""The six marketplace routes, driven through a TestClient with no network at all.

Every test builds the router over a context whose registry client, chain reader and HTTP
sender are fakes, so a route that reached the real network would fail rather than pass
slowly. One test goes the other way and asserts the real `create_app` registers all six
paths, because a router nobody mounted is a set of tests about nothing.
"""

import json

import pytest
from eth_account import Account
from eth_account.messages import encode_defunct
from fastapi import FastAPI
from fastapi.testclient import TestClient

from docket.api import create_app
from docket.api.marketplace_api import (
    LOOKUP_ATTEMPTS,
    MarketplaceContext,
    marketplace_router,
)
from docket.marketplace.external import LEVELS, listing_from_registry
from docket.store import Store

REGISTRY = "0x8004a169fb4a3325136eb29fa0ceb6d2e539a432"
AGENT = f"56:{REGISTRY}:43129"
OWNER = Account.from_key("0x" + "33" * 32)
TOOLS_RESULT = json.dumps(
    {"jsonrpc": "2.0", "id": 1, "result": {"tools": [{"name": "t"}]}}
)


def _card(
    token: str, name: str, description: str, endpoint: str, kind: str = "mcp"
) -> dict:
    return {
        "agent_id": f"56:{REGISTRY}:{token}",
        "token_id": token,
        "chain_id": 56,
        "name": name,
        "description": description,
        "owner_address": OWNER.address.lower(),
        "services": {kind: {"endpoint": endpoint}},
    }


HEYANON = _card(
    "43129",
    "Venus powered by HeyAnon",
    "Validates collateral ratios and checks borrow limits.",
    "https://mcp.example/venus",
)
GRID = _card(
    "999",
    "Grid Planner",
    "Places a grid of orders inside a band.",
    "https://a2a.example/grid",
    kind="a2a",
)


class _FakeRegistry:
    """Stands in for `Scan8004Client`. Records every query so a test can assert on it."""

    queries: list = []
    fetched: list = []
    rows: list = [GRID]

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return None

    def search_agents(
        self, chain_id, *, query=None, owner_address=None, limit=100, offset=0
    ):
        type(self).queries.append(query)
        return list(type(self).rows), len(type(self).rows)

    def get_agent(self, chain_id, token_id):
        type(self).fetched.append(token_id)
        for row in (HEYANON, GRID):
            if row["token_id"] == token_id:
                return row
        raise LookupError(token_id)


def _rpc(agent_id):
    return {
        "agent_id": agent_id,
        "chain_id": 56,
        "token_id": agent_id.split(":")[-1],
        "registry": REGISTRY,
        "owner": OWNER.address,
        "token_uri": "ipfs://card",
        "rpc_url": "https://bsc-dataseed.example",
        "detail": None,
        "outcome": "owned",
    }


def _http(endpoint, *, now):
    body = TOOLS_RESULT if endpoint.get("json_body") else "{}"
    return {
        "snapshot_id": None,
        "agent_id": endpoint.get("agent_id"),
        "url": endpoint["url"],
        "observed_at": now,
        "outcome": "responded",
        "status_code": 200,
        "elapsed_ms": 7,
        "detail": None,
        "body": body,
        "content_type": "application/json",
        "truncated": False,
    }


@pytest.fixture
def client(tmp_path):
    _FakeRegistry.queries = []
    _FakeRegistry.fetched = []
    _FakeRegistry.rows = [GRID]
    db = tmp_path / "d.sqlite3"
    store = Store(db)
    store.upsert_external_listing(listing_from_registry(HEYANON).to_json())
    app = FastAPI()
    app.include_router(
        marketplace_router(
            MarketplaceContext(
                db_path=db,
                spend_probe=lambda peer: None,
                probe_attempts=20,
                probe_window_seconds=3600,
                seed_path=None,
                search_client=_FakeRegistry,
                rpc=_rpc,
                http=_http,
            )
        )
    )
    return TestClient(app)


def test_create_app_registers_all_six_marketplace_paths(tmp_path):
    db = tmp_path / "wired.sqlite3"
    store = Store(db)
    sid = store.begin_snapshot(chain_id=56, expected=1)
    store.upsert_agents(
        [
            {
                "agent_id": "56:0xreg:1",
                "token_id": "1",
                "chain_id": 56,
                "name": "x",
                "supported_protocols": [],
                "total_feedbacks": 0,
            }
        ],
        sid,
    )
    store.finish_snapshot(sid, sampled=1, expected=1)
    wired = TestClient(create_app(db, snapshot_id=sid))

    paths = set(wired.get("/openapi.json").json()["paths"])
    assert {
        "/api/agents",
        "/api/agents/{agent_id}",
        "/api/agents/{agent_id}/verification",
        "/api/agents/{agent_id}/verify",
        "/api/providers/claim",
        "/api/providers/listings",
    } <= paths


def test_create_app_loads_the_committed_seed_into_an_empty_table(tmp_path):
    """The census ships with the wheel, so a fresh deployment has a shelf before anybody
    runs a sweep."""
    db = tmp_path / "seeded.sqlite3"
    store = Store(db)
    sid = store.begin_snapshot(chain_id=56, expected=1)
    store.upsert_agents(
        [
            {
                "agent_id": "56:0xreg:1",
                "token_id": "1",
                "chain_id": 56,
                "name": "x",
                "supported_protocols": [],
                "total_feedbacks": 0,
            }
        ],
        sid,
    )
    store.finish_snapshot(sid, sampled=1, expected=1)
    seeded = TestClient(create_app(db, snapshot_id=sid))

    body = seeded.get("/api/agents?limit=100").json()
    assert body["total"] >= 8
    assert set(body["listings_by_level"]) <= set(LEVELS) | {"unverified"}


def test_a_page_the_store_fills_is_answered_without_touching_the_registry(client):
    """The registry is asked only when the store cannot fill the page that was requested.
    A full page from the store is an answer, and asking anyway would relay every keystroke
    onto somebody else's index."""
    body = client.get("/api/agents?q=collateral&limit=1").json()

    assert body["total"] == 1
    assert body["items"][0]["agent_id"] == AGENT
    assert body["registry_lookup"]["attempted"] is False
    assert _FakeRegistry.queries == []


def test_a_query_the_store_cannot_fill_is_completed_from_the_registry_and_cached(
    client,
):
    first = client.get("/api/agents?q=grid").json()

    assert first["registry_lookup"]["attempted"] is True
    assert first["registry_lookup"]["hydrated"] == 1
    assert _FakeRegistry.queries == ["grid"]
    assert [item["agent_id"] for item in first["items"]] == [f"56:{REGISTRY}:999"]
    assert first["items"][0]["category"] == "grid_trading"


def test_a_hydrated_listing_carries_no_level_and_is_not_hireable(client):
    body = client.get("/api/agents?q=grid").json()
    hydrated = body["items"][0]

    assert hydrated["verification"]["level"] is None
    assert hydrated["verification"]["evidence"] == []
    assert hydrated["hireable"] is False


def test_hydration_never_overwrites_a_listing_that_carries_evidence(client):
    client.post(f"/api/agents/{AGENT}/verify", json={})
    _FakeRegistry.rows = [HEYANON]
    client.get("/api/agents?q=venus")

    body = client.get(f"/api/agents/{AGENT}").json()
    assert body["listing"]["verification"]["level"] == "docket_tested"


def test_the_category_filter_only_accepts_the_four_official_categories(client):
    refused = client.get("/api/agents?category=arbitrage")

    assert refused.status_code == 422
    assert refused.json()["error_code"] == "invalid_category"
    assert "rebalancing" in refused.json()["message"]


def test_the_level_filter_only_accepts_the_six_levels(client):
    refused = client.get("/api/agents?level=audited")

    assert refused.status_code == 422
    assert refused.json()["error_code"] == "invalid_level"


def test_errors_on_this_prefix_are_flat_rather_than_the_nested_envelope(client):
    body = client.get("/api/agents/56:0xreg:not-a-token").json()

    assert set(body) == {"error_code", "message"}
    assert body["error_code"] == "listing_not_found"


def test_a_listing_docket_does_not_hold_is_fetched_once_and_cached(client):
    first = client.get(f"/api/agents/56:{REGISTRY}:999")

    assert first.status_code == 200
    assert _FakeRegistry.fetched == ["999"]
    client.get(f"/api/agents/56:{REGISTRY}:999")
    assert _FakeRegistry.fetched == ["999"], "the second read came from the store"


def test_the_registry_lookup_allowance_is_bounded_per_peer(client):
    for _ in range(LOOKUP_ATTEMPTS):
        client.get("/api/agents?q=nothing-matches-this")

    body = client.get("/api/agents?q=nothing-matches-this").json()
    assert body["registry_lookup"]["attempted"] is False
    assert "allowance" in body["registry_lookup"]["reason"]

    refused = client.get(f"/api/agents/56:{REGISTRY}:777")
    assert refused.status_code == 429
    assert refused.json()["error_code"] == "lookup_rate_limited"
    assert refused.headers["Retry-After"]


def test_verification_returns_the_block_and_every_recorded_run(client):
    client.post(f"/api/agents/{AGENT}/verify", json={})
    body = client.get(f"/api/agents/{AGENT}/verification").json()

    assert body["verification"]["level"] == "docket_tested"
    assert [run["level"] for run in body["runs"]] == list(reversed(LEVELS))
    assert body["hireable"] is True
    assert body["level_prerequisites"]["docket_tested"] == "live"


def test_verify_runs_the_ladder_and_updates_the_stored_listing(client):
    body = client.post(f"/api/agents/{AGENT}/verify", json={}).json()

    assert body["level"] == "docket_tested"
    assert body["previous_level"] is None
    assert body["chain_read_failed"] is False
    assert [row["level"] for row in body["evidence"]] == list(LEVELS)
    assert body["listing"]["hireable"] is True


def test_verify_refuses_a_body_that_is_not_an_empty_object(client):
    refused = client.post(f"/api/agents/{AGENT}/verify", json={"force": True})

    assert refused.status_code == 400
    assert refused.json()["error_code"] == "invalid_json"


def test_verify_refuses_an_agent_docket_holds_no_listing_for(client):
    refused = client.post(f"/api/agents/56:{REGISTRY}:12345/verify", json={})

    assert refused.status_code == 404
    assert refused.json()["error_code"] == "listing_not_found"


def test_verify_spends_the_shared_probe_allowance(tmp_path):
    db = tmp_path / "d.sqlite3"
    Store(db).upsert_external_listing(listing_from_registry(HEYANON).to_json())
    app = FastAPI()
    app.include_router(
        marketplace_router(
            MarketplaceContext(
                db_path=db,
                spend_probe=lambda peer: 42,
                probe_attempts=20,
                probe_window_seconds=3600,
                seed_path=None,
                search_client=_FakeRegistry,
                rpc=_rpc,
                http=_http,
            )
        )
    )
    refused = TestClient(app).post(f"/api/agents/{AGENT}/verify", json={})

    assert refused.status_code == 429
    assert refused.json()["error_code"] == "verify_rate_limited"
    assert refused.headers["Retry-After"] == "42"


def test_the_claim_route_mints_a_nonce_and_then_accepts_the_owner_signature(client):
    issued = client.post("/api/providers/claim", json={"agent_id": AGENT})
    assert issued.status_code == 201
    message = issued.json()["message"]
    assert message == f"Docket provider claim {AGENT} {issued.json()['nonce']}"

    signature = Account.sign_message(
        encode_defunct(text=message), private_key=OWNER.key
    ).signature.hex()
    accepted = client.post(
        "/api/providers/claim",
        json={
            "agent_id": AGENT,
            "nonce": issued.json()["nonce"],
            "signature": signature,
        },
    )

    assert accepted.status_code == 200
    assert accepted.json()["owner"] == OWNER.address


def test_a_stranger_signature_is_refused_with_403(client):
    stranger = Account.from_key("0x" + "44" * 32)
    issued = client.post("/api/providers/claim", json={"agent_id": AGENT}).json()
    signature = Account.sign_message(
        encode_defunct(text=issued["message"]), private_key=stranger.key
    ).signature.hex()

    refused = client.post(
        "/api/providers/claim",
        json={"agent_id": AGENT, "nonce": issued["nonce"], "signature": signature},
    )

    assert refused.status_code == 403
    assert refused.json()["error_code"] == "not_owner"


def test_a_reused_nonce_is_refused_with_409(client):
    issued = client.post("/api/providers/claim", json={"agent_id": AGENT}).json()
    signature = Account.sign_message(
        encode_defunct(text=issued["message"]), private_key=OWNER.key
    ).signature.hex()
    payload = {"agent_id": AGENT, "nonce": issued["nonce"], "signature": signature}
    client.post("/api/providers/claim", json=payload)

    refused = client.post("/api/providers/claim", json=payload)

    assert refused.status_code == 409
    assert refused.json()["error_code"] == "stale_nonce"


def test_a_listing_submission_writes_a_registered_listing_that_is_not_hireable(client):
    issued = client.post("/api/providers/claim", json={"agent_id": AGENT}).json()
    signature = Account.sign_message(
        encode_defunct(text=issued["message"]), private_key=OWNER.key
    ).signature.hex()

    created = client.post(
        "/api/providers/listings",
        json={
            "agent_id": AGENT,
            "nonce": issued["nonce"],
            "signature": signature,
            "capabilities": "Reads a Venus position and returns its health factor.",
            "category": "health_factor",
            "price": "0.50 USDT",
            "payment_method": "x402",
            "sample_input": {"account": "0x1"},
            "output_schema": {"type": "object", "required": ["health_factor"]},
        },
    )

    assert created.status_code == 201
    listing = created.json()["listing"]
    assert listing["verification"]["level"] == "registered"
    assert listing["capability_source"] == "provider_declared"
    assert listing["hireable"] is False
    assert "not hireable" in created.json()["next_step"]
    assert [row["url"] for row in listing["endpoints"]] == ["https://mcp.example/venus"]


def test_a_submission_without_a_signature_is_refused(client):
    refused = client.post(
        "/api/providers/listings", json={"agent_id": AGENT, "capabilities": "x"}
    )

    assert refused.status_code == 400
    assert refused.json()["error_code"] == "invalid_claim"


def test_a_declared_sample_from_a_provider_is_what_verification_sends(client):
    """The full two-sided loop: an owner claims, declares a sample, and Docket runs it."""
    issued = client.post("/api/providers/claim", json={"agent_id": AGENT}).json()
    signature = Account.sign_message(
        encode_defunct(text=issued["message"]), private_key=OWNER.key
    ).signature.hex()
    client.post(
        "/api/providers/listings",
        json={
            "agent_id": AGENT,
            "nonce": issued["nonce"],
            "signature": signature,
            "capabilities": "Reads a Venus position.",
            "category": "health_factor",
            "sample_input": {"account": "0x1"},
            "output_schema": {"type": "object", "required": ["result"]},
        },
    )

    verified = client.post(f"/api/agents/{AGENT}/verify", json={}).json()
    tested = next(
        row for row in verified["evidence"] if row["level"] == "docket_tested"
    )

    assert tested["detail"]["sample_source"] == "declared_sample"
    assert tested["detail"]["request"]["body"] == {"account": "0x1"}
    assert verified["level"] == "docket_tested"
    assert verified["listing"]["hireable"] is True
