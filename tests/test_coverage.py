from docket.coverage import coverage_report, render_markdown
from docket.store import Store


def _seed(store: Store) -> int:
    sid = store.begin_snapshot(chain_id=56, expected=6)
    rows = [
        {
            "agent_id": "56:r:1",
            "token_id": "1",
            "chain_id": 56,
            "name": "Ave.ai Trading Agent",
            "supported_protocols": [],
            "total_feedbacks": 0,
        },
        {
            "agent_id": "56:r:2",
            "token_id": "2",
            "chain_id": 56,
            "name": "Ave.ai Research Agent",
            "supported_protocols": [],
            "total_feedbacks": 0,
        },
        {
            "agent_id": "56:r:3",
            "token_id": "3",
            "chain_id": 56,
            "name": "Agent #3",
            "supported_protocols": [],
            "total_feedbacks": 0,
        },
        {
            "agent_id": "56:r:4",
            "token_id": "4",
            "chain_id": 56,
            "name": "SOLVENT",
            "description": "glass-box trader",
            "supported_protocols": ["A2A"],
            "total_feedbacks": 2,
            "x402_supported": True,
        },
        {
            "agent_id": "56:r:5",
            "token_id": "5",
            "chain_id": 56,
            "name": "Scout",
            "description": "finds pools",
            "supported_protocols": ["MCP"],
            "total_feedbacks": 0,
        },
    ]
    store.upsert_agents(rows, sid)
    store.finish_snapshot(sid, sampled=5)
    return sid


def _seed_probes(store: Store, sid: int) -> None:
    """Four resolved endpoints across three agents, each probed once."""
    store.upsert_endpoints(
        [
            {"agent_id": "56:r:4", "kind": "a2a", "url": "https://a.example/a2a"},
            {"agent_id": "56:r:4", "kind": "mcp", "url": "https://a.example/mcp"},
            {"agent_id": "56:r:5", "kind": "a2a", "url": "https://b.example/a2a"},
            {"agent_id": "56:r:3", "kind": "a2a", "url": "http://127.0.0.1/admin"},
            {"agent_id": "56:r:4", "kind": "web", "url": "https://a.example"},
        ],
        sid,
    )
    probes = [
        ("56:r:4", "https://a.example/a2a", "responded", 200, "10:00:00"),
        ("56:r:4", "https://a.example/mcp", "responded", 404, "10:00:01"),
        ("56:r:5", "https://b.example/a2a", "timeout", None, "10:00:02"),
        ("56:r:3", "http://127.0.0.1/admin", "blocked", None, "10:00:03"),
    ]
    store.record_liveness(
        [
            {
                "snapshot_id": sid,
                "agent_id": agent_id,
                "url": url,
                "observed_at": f"2026-08-07T{stamp}+00:00",
                "outcome": outcome,
                "status_code": status,
                "elapsed_ms": 10,
                "detail": None,
            }
            for agent_id, url, outcome, status, stamp in probes
        ]
    )


def test_report_counts_are_generated_from_the_store(tmp_path):
    store = Store(tmp_path / "d.sqlite3")
    sid = _seed(store)
    rep = coverage_report(store, sid)
    assert rep["sampled"] == 5
    assert rep["expected"] == 6
    assert rep["dropped"] == 1  # partial coverage stated, not hidden
    assert rep["complete"] is False
    assert rep["with_feedback"] == 1
    assert rep["callable"] == 2
    assert rep["placeholder_name"] == 1
    assert rep["distinct_publishers"] == 4  # the two Ave.ai rows collapse to one


def test_top_publisher_share_is_reported(tmp_path):
    store = Store(tmp_path / "d.sqlite3")
    sid = _seed(store)
    rep = coverage_report(store, sid)
    top = rep["top_publishers"][0]
    assert top["publisher"] == "ave.ai"
    assert top["count"] == 2
    assert round(top["share_pct"], 1) == 40.0


def test_markdown_states_partial_coverage_explicitly(tmp_path):
    store = Store(tmp_path / "d.sqlite3")
    sid = _seed(store)
    md = render_markdown(coverage_report(store, sid))
    assert "partial" in md.lower()
    assert "5" in md and "6" in md


def test_liveness_figures_are_computed_from_probe_rows(tmp_path):
    store = Store(tmp_path / "d.sqlite3")
    sid = _seed(store)
    _seed_probes(store, sid)
    rep = coverage_report(store, sid)
    assert rep["endpoints_resolved"] == 5  # every kind enrichment found
    assert rep["endpoints_probeable"] == 4  # the web URL is not a probe target
    assert rep["endpoints_probed"] == 4
    assert rep["endpoints_responded"] == 2  # the 404 answered: the host is up
    assert rep["failed"] == 1
    assert rep["blocked"] == 1
    assert rep["agents_probed"] == 3
    assert rep["agents_responded"] == 1  # both responses belong to the same agent
    assert rep["liveness_observed_at"] == {
        "first": "2026-08-07T10:00:00+00:00",
        "last": "2026-08-07T10:00:03+00:00",
    }


def test_responded_pct_divides_by_probed_not_by_sampled(tmp_path):
    store = Store(tmp_path / "d.sqlite3")
    sid = _seed(store)
    _seed_probes(store, sid)
    rep = coverage_report(store, sid)
    assert rep["sampled"] == 5
    assert rep["responded_pct"] == 50.0  # 2 responded of 4 probed
    # 2 of 5 sampled agents would read as 40% — a liveness figure dressed up as a
    # registry-wide claim. The denominator must be what was actually probed.
    assert rep["responded_pct"] != round(100.0 * rep["endpoints_responded"] / rep["sampled"], 3)


def test_reprobing_an_endpoint_is_history_not_another_endpoint(tmp_path):
    store = Store(tmp_path / "d.sqlite3")
    sid = _seed(store)
    _seed_probes(store, sid)
    store.record_liveness(
        [
            {
                "snapshot_id": sid,
                "agent_id": "56:r:5",
                "url": "https://b.example/a2a",  # the one that timed out, probed again
                "observed_at": "2026-08-07T11:00:00+00:00",
                "outcome": "responded",
                "status_code": 200,
                "elapsed_ms": 90,
                "detail": None,
            }
        ]
    )
    rep = coverage_report(store, sid)
    assert rep["endpoints_probed"] == 4  # not 5
    assert rep["endpoints_responded"] == 3  # the latest observation of that endpoint wins
    assert rep["failed"] == 0
    assert rep["liveness_observed_at"]["last"] == "2026-08-07T11:00:00+00:00"


def test_markdown_liveness_section_states_the_probe_method(tmp_path):
    store = Store(tmp_path / "d.sqlite3")
    sid = _seed(store)
    _seed_probes(store, sid)
    md = render_markdown(coverage_report(store, sid))
    assert "single attempt" in md
    assert "8s timeout" in md
    assert "no redirects followed" in md
    assert "SSRF guard" in md
    assert "50.0% of probed endpoints responded" in md.replace("**", "")
    assert "not of the 5 agents in this snapshot" in md


def test_unresolved_is_reported_apart_from_blocked(tmp_path):
    """One is a refusal we made; the other is DNS failing us. Summed into one figure they
    would publish our own network trouble as a safety statistic."""
    store = Store(tmp_path / "d.sqlite3")
    sid = _seed(store)
    _seed_probes(store, sid)
    store.record_liveness(
        [
            {
                "snapshot_id": sid,
                "agent_id": "56:r:5",
                "url": "https://gone.example/a2a",
                "observed_at": "2026-08-07T10:00:04+00:00",
                "outcome": "unresolved",
                "status_code": None,
                "elapsed_ms": None,
                "detail": "could not resolve host",
            }
        ]
    )
    rep = coverage_report(store, sid)
    assert rep["unresolved"] == 1
    assert rep["blocked"] == 1  # unchanged: the loopback target is still a refusal
    assert rep["failed"] == 1  # unresolved was never attempted, so it is not a failure
    md = render_markdown(rep).replace("**", "")
    assert "Blocked by the SSRF guard — never contacted | 1" in md
    assert "the host did not resolve, so nothing was probed | 1" in md


def test_markdown_without_probes_says_so_instead_of_publishing_zero(tmp_path):
    store = Store(tmp_path / "d.sqlite3")
    sid = _seed(store)
    liveness = render_markdown(coverage_report(store, sid)).split("## Endpoint liveness", 1)[1]
    assert "No endpoints have been probed" in liveness
    assert "%" not in liveness  # an unprobed snapshot must not read as 0% liveness
