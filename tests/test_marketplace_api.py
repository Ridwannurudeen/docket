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
        """A search page, faithfully: 8004scan publishes `services` only on the per-agent
        card, so a row from here carries no endpoints at all."""
        type(self).queries.append(query)
        rows = [
            {key: value for key, value in row.items() if key != "services"}
            for row in type(self).rows
        ]
        return rows, len(rows)

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


def _app(db, *, rpc=_rpc, http=_http, search=_FakeRegistry, spend_probe=None):
    app = FastAPI()
    app.include_router(
        marketplace_router(
            MarketplaceContext(
                db_path=db,
                spend_probe=spend_probe or (lambda peer: None),
                probe_attempts=20,
                probe_window_seconds=3600,
                seed_path=None,
                search_client=search,
                rpc=rpc,
                http=http,
            )
        )
    )
    return app


@pytest.fixture
def client(tmp_path):
    _FakeRegistry.queries = []
    _FakeRegistry.fetched = []
    _FakeRegistry.rows = [GRID]
    db = tmp_path / "d.sqlite3"
    store = Store(db)
    store.upsert_external_listing(listing_from_registry(HEYANON).to_json())
    return TestClient(_app(db))


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
    assert body["error_code"] == "invalid_agent_id"


@pytest.mark.parametrize(
    "agent_id",
    ["abc", "56:0xreg:1", "1:" + REGISTRY + ":1", "9" * 200, "56:" + REGISTRY + ":abc"],
)
def test_a_malformed_agent_id_is_refused_before_anything_reads_it(client, agent_id):
    """`int("abc")` on an unvalidated path segment escaped as an unhandled ValueError and
    surfaced as a 500. One parser, applied on every route that takes an id."""
    for path, method in (
        (f"/api/agents/{agent_id}", client.get),
        (f"/api/agents/{agent_id}/verification", client.get),
    ):
        response = method(path)
        assert response.status_code == 422, path
        assert response.json()["error_code"] == "invalid_agent_id", path
    refused = client.post(f"/api/agents/{agent_id}/verify", json={})
    assert refused.status_code == 422
    assert refused.json()["error_code"] == "invalid_agent_id"
    assert _FakeRegistry.fetched == [], "nothing should be looked up for a malformed id"


def test_a_bare_token_id_resolves_to_the_same_listing_on_every_route(client):
    """One agent, two spellings. A route that normalised and one that did not would make a
    bare id a second row for the same agent."""
    client.post(f"/api/agents/{AGENT}/verify", json={})

    assert client.get("/api/agents/43129").json()["listing"]["agent_id"] == AGENT
    assert client.get("/api/agents/43129/verification").json()["agent_id"] == AGENT
    assert client.post("/api/agents/43129/verify", json={}).json()["agent_id"] == AGENT


@pytest.mark.parametrize("parameter", ["limit", "offset"])
def test_a_malformed_page_bound_is_refused_in_this_routers_own_error_shape(
    client, parameter
):
    """FastAPI would coerce these and answer its own nested envelope, which is the one
    shape a client reading `error_code` under /api/ cannot parse."""
    refused = client.get(f"/api/agents?{parameter}=banana")

    assert refused.status_code == 422
    assert set(refused.json()) == {"error_code", "message"}
    assert refused.json()["error_code"] == f"invalid_{parameter}"


def test_a_query_longer_than_the_bound_is_refused_rather_than_run(client):
    refused = client.get("/api/agents?q=" + "a" * 201)

    assert refused.status_code == 422
    assert refused.json()["error_code"] == "invalid_query"
    assert _FakeRegistry.queries == []


def test_a_wildcard_typed_into_the_search_box_is_not_a_wildcard(client):
    """`%` is a LIKE wildcard. Unescaped it matches every row, and a search that found
    everything reads as a search that found everything."""
    body = client.get("/api/agents?q=%25&limit=100").json()

    assert body["total"] == 0, "a literal percent must match nothing here"


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


def test_a_docket_tested_listing_serves_payment_tested_false_beside_its_level(client):
    """The condition on `docket_tested` hanging off `live`: every payload that carries the
    level carries the payment fact too, on its own, with the row that decided it. A client
    reading only the level would have to infer payment, and the inference a shop front
    invites is the flattering one."""
    verified = client.post(f"/api/agents/{AGENT}/verify", json={}).json()

    for payload in (
        verified["listing"]["verification"],
        client.get(f"/api/agents/{AGENT}").json()["listing"]["verification"],
        client.get(f"/api/agents/{AGENT}/verification").json()["verification"],
        next(
            item
            for item in client.get("/api/agents?limit=100").json()["items"]
            if item["agent_id"] == AGENT
        )["verification"],
    ):
        assert payload["level"] == "docket_tested"
        assert payload["payment_tested"] is False
        assert payload["payment_tested_evidence"]["level"] == "payment_tested"
        assert payload["payment_tested_evidence"]["ok"] is False
        assert (
            "without an x402 payment challenge"
            in (payload["payment_tested_evidence"]["detail"]["message"])
        )


def test_a_listing_with_nothing_observed_serves_the_boolean_with_no_row_behind_it(
    client,
):
    listing = client.get("/api/agents?q=grid").json()["items"][0]["verification"]

    assert listing["level"] is None
    assert listing["payment_tested"] is False
    assert listing["payment_tested_evidence"] is None


def test_an_outage_never_serves_a_held_level_over_evidence_that_all_failed(tmp_path):
    """The blocker this test exists for. `verify_listing` holds the level through an
    outage, and writing that run onto the listing published `docket_tested`,
    `hireable: true`, over six `ok: false` rows, stamped with a fresh `verified_at` — the
    strongest claim in the vocabulary over the weakest evidence in it, dated now."""
    db = tmp_path / "outage.sqlite3"
    Store(db).upsert_external_listing(listing_from_registry(HEYANON).to_json())
    working = TestClient(_app(db, rpc=_rpc, http=_http))
    good = working.post(f"/api/agents/{AGENT}/verify", json={}).json()
    assert good["level"] == "docket_tested"
    earned_at = good["listing"]["verification"]["verified_at"]
    earned_evidence = good["listing"]["verification"]["evidence"]

    def down(agent_id):
        return {**_rpc(agent_id), "outcome": "rpc_unavailable", "owner": None}

    dark = TestClient(_app(db, rpc=down, http=_http))
    response = dark.post(f"/api/agents/{AGENT}/verify", json={}).json()

    assert response["chain_read_failed"] is True
    assert all(row["ok"] is False for row in response["evidence"])

    served = dark.get(f"/api/agents/{AGENT}").json()["listing"]
    assert served["verification"]["level"] == "docket_tested"
    assert served["hireable"] is True
    assert served["verification"]["evidence"] == earned_evidence
    assert served["verification"]["verified_at"] == earned_at
    assert served["verification"]["held_from_outage"] is True
    assert served["verification"]["held_at"] > earned_at
    # The attempt is not lost — it is where an attempt belongs.
    runs = dark.get(f"/api/agents/{AGENT}/verification").json()["runs"]
    assert any(run["level"] == "registered" and not run["ok"] for run in runs), (
        "the outage attempt must be recorded as a run"
    )

    # And the hold clears the moment the chain answers again, rather than sticking.
    recovered = working.post(f"/api/agents/{AGENT}/verify", json={}).json()
    assert recovered["chain_read_failed"] is False
    assert recovered["listing"]["verification"]["held_from_outage"] is False
    assert recovered["listing"]["verification"]["held_at"] is None
    assert recovered["listing"]["verification"]["verified_at"] > earned_at


def test_a_listing_found_on_a_search_page_has_its_card_read_before_it_is_verified(
    client,
):
    """A search page carries no endpoints. Verifying such a row would fail
    endpoint_detected for a reason about Docket's cache rather than about the agent."""
    hydrated = client.get("/api/agents?q=grid").json()["items"][0]
    assert hydrated["source"] == "registry_index_list"
    assert hydrated["endpoints"] == []

    verified = client.post(f"/api/agents/{hydrated['agent_id']}/verify", json={}).json()

    assert _FakeRegistry.fetched == ["999"], "exactly one card read"
    assert verified["listing"]["source"] == "registry_index"
    assert [row["kind"] for row in verified["listing"]["endpoints"]] == ["a2a"]
    assert verified["level"] == "live"


def test_a_verified_listing_outranks_one_docket_merely_found_in_an_index(client):
    """Level names do not sort into their own order — 'live' sorts before 'registered' —
    so ordering on the column put weaker listings above stronger ones."""
    client.post(f"/api/agents/{AGENT}/verify", json={})
    client.get("/api/agents?q=grid")

    items = client.get("/api/agents?limit=100").json()["items"]
    levels = [item["verification"]["level"] for item in items]

    assert levels[0] == "docket_tested"
    assert levels[-1] is None, "an unobserved listing sorts last, never first"


def test_the_verify_route_refuses_a_loopback_endpoint_without_connecting(
    tmp_path, monkeypatch
):
    """The guard, exercised through the real sender rather than a fake. A registry anyone
    can write to can name 127.0.0.1, and the refusal has to happen before a socket."""
    from docket.marketplace import verification as verification_module

    connections: list = []

    def refuse(*args, **kwargs):
        connections.append(args)
        raise AssertionError("a connection was opened to a blocked address")

    monkeypatch.setattr("httpx.Client.stream", refuse)

    db = tmp_path / "loopback.sqlite3"
    Store(db).upsert_external_listing(
        listing_from_registry(
            _card("777", "Local", "Grid agent.", "http://127.0.0.1:1/a2a", kind="a2a")
        ).to_json()
    )
    client = TestClient(
        _app(db, rpc=_rpc, http=verification_module.send, search=_FakeRegistry)
    )

    body = client.post(f"/api/agents/56:{REGISTRY}:777/verify", json={}).json()
    live = next(row for row in body["evidence"] if row["level"] == "live")

    assert body["level"] == "endpoint_detected"
    assert live["ok"] is False
    assert live["detail"]["attempts"][0]["outcome"] == "blocked"
    assert "loopback" in live["detail"]["attempts"][0]["detail"]
    assert connections == [], "the guard must refuse before any connection is opened"


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
    refused = TestClient(_app(db, spend_probe=lambda peer: 42)).post(
        f"/api/agents/{AGENT}/verify", json={}
    )

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
    rows = {row["level"]: row for row in verified["evidence"]}

    # The provider's sample ran and is published, under a name outside the ladder.
    provider = rows["provider_sample_ok"]
    assert provider["detail"]["raises_level"] is False
    assert provider["detail"]["request"]["body"] == {"account": "0x1"}
    # The level came from Docket's own sample, not theirs.
    assert rows["docket_tested"]["detail"]["sample_source"] == "docket_default_mcp"
    assert verified["level"] == "docket_tested"
    assert verified["listing"]["hireable"] is True
