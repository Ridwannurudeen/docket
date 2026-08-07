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
