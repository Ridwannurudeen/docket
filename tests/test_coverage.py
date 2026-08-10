from pathlib import Path

from docket.coverage import coverage_report, render_markdown
from docket.store import Store

PACKAGE = Path(__file__).resolve().parents[1] / "docket"
# The labels this rename retired. Kept as exact tokens rather than as the word "probed",
# which is still the right word for the method prose and the outcome vocabulary.
RETIRED_LABELS = ("endpoints_probed", "responded_pct_of_probed", "agents_probed")


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


def test_coverage_carries_the_population_the_snapshot_swept(tmp_path):
    store = Store(tmp_path / "d.sqlite3")
    sid = store.begin_snapshot(chain_id=56, expected=2, population="min_feedbacks>=1")
    store.upsert_agents([{"agent_id": "56:r:1", "token_id": "1", "chain_id": 56}], sid)
    store.finish_snapshot(sid, sampled=1)
    rep = coverage_report(store, sid)
    assert rep["population"] == "min_feedbacks>=1"
    md = render_markdown(rep)
    assert "min_feedbacks>=1" in md


def test_a_snapshot_that_never_recorded_its_population_says_unspecified(tmp_path):
    """Never guessed at. A pre-existing snapshot did not record which query it ran, and
    inventing "all" for it would publish a filtered slice as a whole-registry census."""
    store = Store(tmp_path / "d.sqlite3")
    sid = _seed(store)
    rep = coverage_report(store, sid)
    assert rep["population"] is None
    assert "unspecified" in render_markdown(rep)


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
    assert rep["endpoints_evaluated"] == 4
    assert rep["endpoints_attempted"] == 3  # the loopback target was blocked, never requested
    assert rep["endpoints_responded"] == 2  # the 404 answered: the host is up
    assert rep["failed"] == 1
    assert rep["blocked"] == 1
    assert rep["agents_attempted"] == 2  # the third agent's only endpoint was blocked
    assert rep["agents_responded"] == 1  # both responses belong to the same agent
    assert rep["liveness_observed_at"] == {
        "first": "2026-08-07T10:00:00+00:00",
        "last": "2026-08-07T10:00:03+00:00",
    }


def test_each_rate_is_named_for_its_own_denominator(tmp_path):
    store = Store(tmp_path / "d.sqlite3")
    sid = _seed(store)
    _seed_probes(store, sid)
    rep = coverage_report(store, sid)
    assert rep["sampled"] == 5
    assert rep["responded_pct_of_attempted"] == 66.667  # 2 responded of 3 requested
    assert rep["responded_pct_of_evaluated"] == 50.0  # 2 responded of 4 considered
    # 2 of 5 sampled agents would read as 40% — a liveness figure dressed up as a
    # registry-wide claim. Neither denominator is the snapshot.
    for rate in ("responded_pct_of_attempted", "responded_pct_of_evaluated"):
        assert rep[rate] != round(100.0 * rep["endpoints_responded"] / rep["sampled"], 3)


def _seed_outcomes(store: Store, sid: int, counts: dict[str, int]) -> None:
    """One observation per outcome per distinct URL, so nothing collapses in `_latest`."""
    rows = []
    for outcome, n in counts.items():
        for i in range(n):
            rows.append(
                {
                    "snapshot_id": sid,
                    "agent_id": f"56:r:{outcome}-{i}",
                    "url": f"https://{outcome}-{i}.example/a2a",
                    "observed_at": "2026-08-07T17:51:00+00:00",
                    "outcome": outcome,
                    "status_code": 200 if outcome == "responded" else None,
                    "elapsed_ms": None,
                    "detail": None,
                }
            )
    store.record_liveness(rows)


def test_attempted_counts_only_targets_an_http_request_reached(tmp_path):
    """The live snapshot 3 shape. 35 endpoints were considered; 21 of them — every blocked
    target and every name that would not resolve — never had a request issued at all, so a
    rate over 35 divides responses by endpoints nothing was ever sent to."""
    store = Store(tmp_path / "d.sqlite3")
    sid = _seed(store)
    _seed_outcomes(store, sid, {"responded": 13, "timeout": 1, "blocked": 10, "unresolved": 11})
    rep = coverage_report(store, sid)
    assert rep["endpoints_evaluated"] == 35
    assert rep["endpoints_attempted"] == 14
    assert rep["endpoints_attempted"] == (
        rep["endpoints_evaluated"] - rep["blocked"] - rep["unresolved"]
    )
    assert rep["endpoints_responded"] == 13
    assert rep["responded_pct_of_attempted"] == 92.857
    assert rep["responded_pct_of_evaluated"] == 37.143


def test_the_retired_probed_labels_survive_nowhere_in_the_package(tmp_path):
    """A wrong label must not live on as an alias. The old names promised a denominator of
    endpoints probed while counting endpoints nothing was ever sent to, so they are gone from
    the report, the response models, the agent-facing documents and the human pages alike."""
    store = Store(tmp_path / "d.sqlite3")
    sid = _seed(store)
    _seed_probes(store, sid)
    rep = coverage_report(store, sid)
    for label in RETIRED_LABELS:
        assert label not in rep
    for path in PACKAGE.rglob("*"):
        if path.suffix not in (".py", ".html", ".js", ".txt", ".md"):
            continue
        text = path.read_text(encoding="utf-8")
        for label in RETIRED_LABELS:
            assert label not in text, f"{path.name} still carries the retired label {label!r}"


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
    assert rep["endpoints_evaluated"] == 4  # not 5
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
    flat = md.replace("**", "")
    assert "66.667% of the 3 endpoints a request reached responded" in flat
    assert "50.0% of all 4 evaluated" in flat
    assert "not of the 5 agents in this snapshot" in flat


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
