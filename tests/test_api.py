from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from docket.api import create_app
from docket.api.routes import _snapshot_age_seconds
from docket.store import Store

PUBLIC_HOST = "https://docket.gudman.xyz"
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
        [
            {
                "agent_id": AGENT["agent_id"],
                "kind": "a2a",
                "url": "https://a.example/a2a",
            }
        ],
        sid,
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


def test_application_factory_honors_the_configured_database(tmp_path, monkeypatch):
    configured_db = tmp_path / "configured" / "agents.sqlite3"
    working_directory = tmp_path / "working"
    working_directory.mkdir()
    monkeypatch.chdir(working_directory)
    monkeypatch.setenv("DOCKET_DB", str(configured_db))

    create_app()

    assert configured_db.exists()
    assert not (working_directory / "data" / "agents.sqlite3").exists()


def test_health_names_the_snapshot_it_serves(client):
    body = client.get("/health").json()
    assert body["status"] == "ok"
    assert body["snapshot_id"] == 1
    assert body["snapshot_captured_at"]
    assert body["snapshot_age_seconds"] >= 0


def test_snapshot_age_never_turns_bad_or_future_time_into_freshness():
    future = (datetime.now(timezone.utc) + timedelta(minutes=1)).isoformat()

    assert _snapshot_age_seconds("not-a-timestamp") is None
    assert _snapshot_age_seconds("2026-08-15T12:00:00") is None
    assert _snapshot_age_seconds(future) is None


def test_root_points_an_agent_at_its_documentation(client):
    body = client.get("/").json()
    for key in ("llms_txt", "openapi", "stats", "agents"):
        assert key in body


def test_stats_never_reports_a_number_without_coverage(client):
    body = client.get("/stats").json()
    cov = body["coverage"]
    assert cov["sampled"] == 2 and cov["expected"] == 2 and cov["dropped"] == 0
    assert cov["complete"] is True and cov["snapshot_id"] == 1
    assert cov["snapshot_age_seconds"] >= 0
    assert body["with_feedback"] == 1
    assert "probe_method" in body and body["probe_method"]


def test_both_responded_rates_carry_their_own_denominator(client):
    body = client.get("/stats").json()
    # 1 endpoint evaluated and requested, 1 responded -> 100% either way, NOT 50% of the 2 agents.
    assert body["endpoints_evaluated"] == 1
    assert body["endpoints_attempted"] == 1
    assert body["endpoints_responded"] == 1
    assert body["responded_pct_of_attempted"] == 100.0
    assert body["responded_pct_of_evaluated"] == 100.0


def test_a_blocked_target_is_evaluated_but_never_attempted(tmp_path):
    """The live bug: /stats divided responses by every observation, including the ones an SSRF
    refusal or a dead hostname meant no request was ever issued for."""
    db = tmp_path / "blocked.sqlite3"
    store = Store(db)
    sid = store.begin_snapshot(chain_id=56, expected=1)
    store.upsert_agents([AGENT], sid)
    store.record_liveness(
        [
            {
                "snapshot_id": sid,
                "agent_id": AGENT["agent_id"],
                "url": url,
                "observed_at": "2026-08-07T10:00:00+00:00",
                "outcome": outcome,
                "status_code": 200 if outcome == "responded" else None,
                "elapsed_ms": None,
                "detail": None,
            }
            for url, outcome in (
                ("https://a.example/a2a", "responded"),
                ("npm://some-package", "blocked"),
                ("https://gone.example/a2a", "unresolved"),
            )
        ]
    )
    store.finish_snapshot(sid, sampled=1, expected=1)
    body = TestClient(create_app(db, snapshot_id=sid)).get("/stats").json()
    assert body["endpoints_evaluated"] == 3
    assert body["endpoints_attempted"] == 1  # blocked and unresolved reached no host
    assert body["responded_pct_of_attempted"] == 100.0
    assert body["responded_pct_of_evaluated"] == 33.333
    for retired in ("endpoints_probed", "responded_pct_of_probed"):
        assert retired not in body


def test_every_coverage_object_names_the_population_it_was_drawn_from(tmp_path):
    """`filter` says which subset of the snapshot a response describes. `population` says what
    the snapshot itself was swept from — the question 506 of 506 could not answer before."""
    db = tmp_path / "population.sqlite3"
    store = Store(db)
    sid = store.begin_snapshot(chain_id=56, expected=1, population="min_feedbacks>=1")
    store.upsert_agents([AGENT], sid)
    store.finish_snapshot(sid, sampled=1, expected=1)
    client = TestClient(create_app(db, snapshot_id=sid))
    for path in ("/stats", "/agents", f"/agents/{AGENT['agent_id']}"):
        cov = client.get(path).json()["coverage"]
        assert cov["population"] == "min_feedbacks>=1", path


def test_a_snapshot_with_no_recorded_population_serves_null_not_a_guess(client):
    assert client.get("/stats").json()["coverage"]["population"] is None


def test_stats_carries_the_registry_total_the_snapshot_is_a_slice_of(tmp_path):
    """`complete: true` on 506 of 506 is true and says nothing about scale. The registry total
    is the figure that makes the filtered snapshot readable, so it is served, not narrated."""
    db = tmp_path / "slice.sqlite3"
    store = Store(db)
    swept = store.begin_snapshot(chain_id=56, expected=247065, population="all")
    store.finish_snapshot(swept, sampled=2000)
    sid = store.begin_snapshot(chain_id=56, expected=1, population="min_feedbacks>=1")
    store.upsert_agents([AGENT], sid)
    store.finish_snapshot(sid, sampled=1, expected=1)

    body = TestClient(create_app(db, snapshot_id=sid)).get("/stats").json()
    assert body["registry_total"] == 247065
    assert body["coverage"]["complete"] is True
    assert (
        body["coverage"]["expected"] == 1
    )  # complete against its own query, not the chain
    assert body["registry_total"] > body["coverage"]["expected"]


def test_registry_total_equal_to_the_snapshot_means_no_wider_measurement(client):
    """The fixture's only sweep IS the served snapshot, so the largest total recorded is that
    snapshot's own. The figure is still reported — it is a real record — and it is the human
    page that declines to print a slice comparison when there is no wider sweep behind it."""
    body = client.get("/stats").json()
    assert body["registry_total"] == body["coverage"]["expected"] == 2


def test_the_served_snapshot_is_the_newest_COMPLETE_one(tmp_path):
    """Resolution defaults to a snapshot that finished. Taking the newest row instead would,
    the moment a refresh loop runs, serve a sweep still being written as the whole capture —
    every count understated and `complete` computed against an `expected` nothing reached."""
    db = tmp_path / "sweeps.sqlite3"
    store = Store(db)
    done = store.begin_snapshot(chain_id=56, expected=2)
    store.upsert_agents([AGENT, QUIET], done)
    store.finish_snapshot(done, sampled=2, expected=2)
    crashed = store.begin_snapshot(chain_id=56, expected=2)
    store.upsert_agents([AGENT], crashed)  # one page in, then the sweep died

    client = TestClient(create_app(db))
    assert client.get("/health").json()["snapshot_id"] == done
    assert client.get("/stats").json()["coverage"]["snapshot_id"] == done
    assert client.get("/agents").json()["total"] == 2  # not the crashed sweep's 1
    # Naming it explicitly is still honoured: an operator may inspect a partial sweep.
    assert (
        TestClient(create_app(db, snapshot_id=crashed)).get("/agents").json()["total"]
        == 1
    )


def test_only_an_unfinished_sweep_reports_no_snapshot_rather_than_serving_it(tmp_path):
    db = tmp_path / "crashed.sqlite3"
    store = Store(db)
    store.upsert_agents([AGENT], store.begin_snapshot(chain_id=56, expected=2))
    resp = TestClient(create_app(db)).get("/stats")
    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == "no_snapshot"
    assert "complete" in resp.json()["error"]["message"]  # says why, not just that


def test_agents_list_is_filterable_and_states_coverage(client):
    body = client.get("/agents").json()
    assert body["total"] == 2 and len(body["items"]) == 2
    assert body["coverage"]["snapshot_id"] == 1
    only = client.get("/agents", params={"has_feedback": "true"}).json()
    assert only["total"] == 1
    assert only["items"][0]["agent_id"] == AGENT["agent_id"]
    callable_only = client.get("/agents", params={"declares_callable": "true"}).json()
    assert callable_only["total"] == 1


def test_agents_are_filterable_and_labelled_by_name_family_not_publisher(client):
    """The key is the first token of a name the agent chose for itself. Serving it as
    `publisher` claimed Docket had read minter provenance off chain; it never had."""
    body = client.get("/agents").json()
    # QUIET's name is registry-generated and it declares no owner, so it has no family.
    assert {item["name_family"] for item in body["items"]} == {"solvent", "unknown"}
    assert "publisher" not in body["items"][0]
    narrowed = client.get("/agents", params={"name_family": "solvent"}).json()
    assert narrowed["total"] == 1
    assert narrowed["items"][0]["agent_id"] == AGENT["agent_id"]
    assert narrowed["coverage"]["filter"] == "name_family=solvent"
    stats = client.get("/stats").json()
    assert stats["distinct_name_families"] == 2
    assert {row["name_family"] for row in stats["top_name_families"]} == {
        "solvent",
        "unknown",
    }
    for retired in ("distinct_publishers", "top_publishers"):
        assert retired not in stats


def test_the_retired_publisher_filter_is_refused_not_silently_ignored(client):
    """FastAPI drops unknown query parameters, so `?publisher=x` answered a caller who asked
    for one slice with the ENTIRE snapshot and `filter: null` — a narrower request served
    wider, with nothing in the response saying so. llms.txt taught clients that parameter, so
    this reaches real callers; it is refused by name instead."""
    resp = client.get("/agents", params={"publisher": "solvent"})
    assert resp.status_code == 422
    err = resp.json()["error"]
    assert err["code"] == "invalid_query_parameter"
    assert "publisher" in err["message"]
    assert (
        "name_family" in err["message"]
    )  # names the replacement, not just the mistake
    # Refused even when it would have changed nothing, so a client cannot learn the wrong name
    # from a request that happened to work.
    assert (
        client.get("/agents", params={"publisher": "nothing-matches-this"}).status_code
        == 422
    )
    assert client.get("/agents", params={"name_family": "solvent"}).status_code == 200


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


def test_every_response_carries_the_same_security_policy(client):
    expected = {
        "content-security-policy": (
            "default-src 'self'; base-uri 'none'; object-src 'none'; "
            "frame-ancestors 'none'; form-action 'self'; img-src 'self' data:; "
            "script-src 'self'; style-src 'self' "
            "'sha256-6rUoS78zt/PNQ8nNYAej0vxT3N4WfeWR+hzuvLTdgbM=' "
            "'sha256-JBSnR/xdx/11XiOtHyfG4Ek2qcx2LGkIYxA0HafpeV4='; connect-src 'self'"
        ),
        "x-frame-options": "DENY",
        "x-content-type-options": "nosniff",
        "referrer-policy": "strict-origin-when-cross-origin",
    }
    requests = (
        client.get("/", headers={"Accept": "text/html"}),
        client.get("/"),
        client.get("/missing"),
        client.get("/static/style.css"),
    )

    assert [response.status_code for response in requests] == [200, 200, 404, 200]
    for response in requests:
        assert {name: response.headers[name] for name in expected} == expected


def test_unhandled_errors_are_generic_logged_without_private_details(tmp_path, caplog):
    private_detail = "bearer docket-internal-only at C:\\private\\database.sqlite3"
    app = create_app(tmp_path / "unhandled.sqlite3")

    @app.get("/_test/unhandled")
    def unhandled():
        raise RuntimeError(private_detail)

    with caplog.at_level("ERROR", logger="docket.api.routes"):
        response = TestClient(app, raise_server_exceptions=False).get(
            "/_test/unhandled"
        )

    assert response.status_code == 500
    assert response.json() == {
        "error": {
            "code": "internal_server_error",
            "message": "The server could not complete this request. Retry.",
        }
    }
    assert private_detail not in response.text
    assert "RuntimeError" not in response.text
    assert response.headers["content-security-policy"].startswith("default-src 'self'")
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["referrer-policy"] == "strict-origin-when-cross-origin"
    records = [
        record for record in caplog.records if record.name == "docket.api.routes"
    ]
    assert len(records) == 1
    assert records[0].getMessage() == (
        "unexpected request failure: method=GET route=/_test/unhandled "
        "exception_type=RuntimeError"
    )
    assert private_detail not in records[0].getMessage()
    assert "docket-internal-only" not in caplog.text
    assert r"C:\private\database.sqlite3" not in caplog.text


@pytest.mark.parametrize("path", ["/docs", "/redoc"])
def test_external_interactive_docs_are_disabled_without_hiding_openapi(client, path):
    response = client.get(path)

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"
    assert client.get("/openapi.json").status_code == 200


def test_llms_txt_documents_every_path_the_spec_declares(client):
    """The doc cannot silently drift from the API: an agent told not to invent endpoints reads
    /llms.txt, so a path that exists but is undocumented is a path it will never call."""
    resp = client.get("/llms.txt")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/plain")
    body = resp.text
    for path in client.get("/openapi.json").json()["paths"]:
        assert path in body, f"/llms.txt does not document {path}"


def test_both_registry_figures_are_dated_and_reconciled(client):
    """247,278 (read by hand) and 247,146 (the largest total a sweep recorded) describe the
    same quantity four paragraphs apart. Undated and unreconciled they read as a contradiction,
    and a reader cannot tell which to quote — so each carries when it was taken, and the file
    says outright why they differ."""
    llms = client.get("/llms.txt").text
    assert "247,278" in llms and "247,146" in llms
    assert "not in conflict" in llms
    for path in ("/llms.txt", "/skill.md"):
        body = client.get(path).text
        assert "247,278" in body, path
        # The hand reading is dated wherever it appears, so it cannot be quoted as current.
        assert "2026-08-07" in body, path


def test_skill_md_is_served_as_markdown(client):
    resp = client.get("/skill.md")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/markdown")
    assert resp.text.strip()


def test_agent_facing_docs_name_the_public_host(client):
    """Both agent-facing docs once said no public deployment existed while being served from
    one. An evaluator agent reads that as 'nothing to call' and stops, so the claim is a
    correctness bug on the front door, not a typo."""
    for path in ("/llms.txt", "/skill.md"):
        body = client.get(path).text
        assert PUBLIC_HOST in body, f"{path} does not name the public host"
        assert "no public host" not in body, f"{path} still denies a public host"
        assert "no public deployment" not in body, (
            f"{path} still denies a public deployment"
        )


def test_cors_advertises_only_methods_that_are_actually_served(client):
    """Advertising a method we answer with 405 is the wrong kind of inconsistency here."""
    preflight = client.options(
        "/agents",
        headers={
            "Origin": "https://example.test",
            "Access-Control-Request-Method": "GET",
        },
    )
    advertised = {
        m.strip() for m in preflight.headers["access-control-allow-methods"].split(",")
    }
    for method in advertised:
        assert client.request(method, "/agents").status_code != 405


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
