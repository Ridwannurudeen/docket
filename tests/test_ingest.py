import ast
import inspect
import textwrap

import httpx
import pytest

import docket.ingest as ingest_module
from docket.ingest import ingest_bsc, ingest_targeted
from docket.scan8004 import Scan8004Client
from docket.store import Store

REGISTRY_TOTAL = (
    247_278  # what an unfiltered query reports; the filtered one must not say this
)
REGISTRY_ADDRESS = "0x8004a169fb4a3325136eb29fa0ceb6d2e539a432"
OWNED_AGENT_ID = f"56:{REGISTRY_ADDRESS}:2"


def _row(token: int) -> dict:
    return {
        "agent_id": f"56:0xreg:{token}",
        "token_id": str(token),
        "chain_id": 56,
        "name": f"Agent #{token}",
        "supported_protocols": [],
        "total_feedbacks": 0,
        "total_score": 0.0,
    }


def _paged_handler(total: int, page_size: int, grow_by: int = 0):
    """Serves `total` rows page by page; `grow_by` simulates the registry growing mid-sweep."""
    state = {"total": total, "calls": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        state["calls"] += 1
        offset = int(request.url.params["offset"])
        limit = int(request.url.params["limit"])
        if state["calls"] == 2:
            state["total"] += grow_by
        items = [_row(t) for t in range(offset, min(offset + limit, total))]
        return httpx.Response(200, json={"items": items, "total": state["total"]})

    return handler


def test_ingests_every_page_and_records_coverage(tmp_path):
    store = Store(tmp_path / "d.sqlite3")
    client = Scan8004Client(
        transport=httpx.MockTransport(_paged_handler(250, 100)), pace=False
    )
    result = ingest_bsc(store, client)
    assert result["sampled"] == 250
    assert result["expected"] == 250
    assert result["dropped"] == 0
    assert store.agent_count(result["snapshot_id"]) == 250
    assert result["stop_reason"] == "exhausted"
    assert store.snapshot(result["snapshot_id"])["stop_reason"] == "exhausted"


def test_exhaustion_is_assigned_only_after_the_pagination_loop_does_not_break():
    """`exhausted` used to be the pre-loop default, so a new unclassified `break` would
    silently inherit the only promotable reason. The loop's no-break branch must assign it,
    and any break that forgot its classification must be rejected before finalization.
    """
    source = textwrap.dedent(inspect.getsource(ingest_module._sweep))
    function = ast.parse(source).body[0]
    stop_default = next(
        node
        for node in function.body
        if isinstance(node, ast.AnnAssign)
        and isinstance(node.target, ast.Name)
        and node.target.id == "stop_reason"
    )
    assert ast.literal_eval(stop_default.value) is None

    loop = next(node for node in function.body if isinstance(node, ast.While))
    assert any(
        isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "stop_reason"
            for target in node.targets
        )
        and ast.literal_eval(node.value) == "exhausted"
        for node in loop.orelse
    )

    guard = function.body[function.body.index(loop) + 1]
    assert isinstance(guard, ast.If)
    assert isinstance(guard.test, ast.Compare)
    assert isinstance(guard.test.left, ast.Name)
    assert guard.test.left.id == "stop_reason"
    assert len(guard.test.ops) == 1 and isinstance(guard.test.ops[0], ast.Is)
    assert len(guard.test.comparators) == 1
    assert ast.literal_eval(guard.test.comparators[0]) is None
    assert any(isinstance(node, ast.Raise) for node in guard.body)


def test_growth_during_sweep_is_reported_as_dropped_not_hidden(tmp_path):
    store = Store(tmp_path / "d.sqlite3")
    # 250 rows are servable, but the API's reported total grows to 300 mid-sweep.
    client = Scan8004Client(
        transport=httpx.MockTransport(_paged_handler(250, 100, grow_by=50)), pace=False
    )
    result = ingest_bsc(store, client)
    assert result["sampled"] == 250
    assert result["expected"] == 300
    assert result["dropped"] == 50  # surfaced, never silently rounded away


def test_ratcheted_expected_is_persisted_to_the_snapshot_row(tmp_path):
    store = Store(tmp_path / "d.sqlite3")
    client = Scan8004Client(
        transport=httpx.MockTransport(_paged_handler(250, 100, grow_by=50)), pace=False
    )
    result = ingest_bsc(store, client)
    row = store.snapshot(result["snapshot_id"])
    # begin_snapshot recorded the first page's 250. A reader that trusts the stored row would
    # otherwise compute dropped=0 and publish "complete" while the API had claimed 300.
    assert row["expected"] == 300
    assert row["sampled"] == 250


def test_unbounded_sweep_terminates_when_the_paginator_never_advances(tmp_path):
    store = Store(tmp_path / "d.sqlite3")
    state = {"calls": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        # The API ignores `offset` and serves the same non-empty page forever.
        state["calls"] += 1
        if state["calls"] > 5:
            raise AssertionError(
                "sweep did not terminate: the stuck paginator was polled 6 times"
            )
        return httpx.Response(
            200, json={"items": [_row(t) for t in range(10)], "total": 30}
        )

    client = Scan8004Client(transport=httpx.MockTransport(handler), pace=False)
    result = ingest_bsc(
        store, client
    )  # no max_pages — liveness must come from the guard
    assert result["pages"] == 1
    assert result["sampled"] == 10
    assert result["dropped"] == 20
    assert result["stop_reason"] == "not_advancing"
    assert store.latest_complete_snapshot_id() is None


def test_max_pages_bounds_the_sweep(tmp_path):
    store = Store(tmp_path / "d.sqlite3")
    client = Scan8004Client(
        transport=httpx.MockTransport(_paged_handler(1000, 100)), pace=False
    )
    result = ingest_bsc(store, client, max_pages=2)
    assert result["pages"] == 2
    assert result["sampled"] == 200
    assert result["expected"] == 1000
    assert result["dropped"] == 800  # a bounded sweep states its own incompleteness
    assert result["stop_reason"] == "max_pages"
    assert store.latest_complete_snapshot_id() is None


def test_duplicate_rows_across_pages_do_not_inflate_the_count(tmp_path):
    store = Store(tmp_path / "d.sqlite3")

    def handler(request: httpx.Request) -> httpx.Response:
        # Every page returns the same 10 rows — a pathological paginator.
        return httpx.Response(
            200, json={"items": [_row(t) for t in range(10)], "total": 30}
        )

    client = Scan8004Client(transport=httpx.MockTransport(handler), pace=False)
    result = ingest_bsc(store, client, max_pages=3)
    assert store.agent_count(result["snapshot_id"]) == 10
    assert result["sampled"] == 10  # counted from the store, not from pages served


def _filtered_handler(matching: int, page_size: int = 100, seen: list | None = None):
    """Serves `matching` rows, but only to requests carrying `min_feedbacks`.

    An unfiltered request gets the registry-wide total and no rows, so a sweep that drops the
    filter on any page — not just the first — corrupts its own accounting instead of passing.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        params = request.url.params
        if seen is not None:
            seen.append(dict(params))
        if "min_feedbacks" not in params:
            return httpx.Response(200, json={"items": [], "total": REGISTRY_TOTAL})
        offset = int(params["offset"])
        items = [_row(t) for t in range(offset, min(offset + page_size, matching))]
        return httpx.Response(200, json={"items": items, "total": matching})

    return handler


def test_targeted_sweep_sends_the_filter_on_every_page(tmp_path):
    store = Store(tmp_path / "d.sqlite3")
    seen: list[dict] = []
    client = Scan8004Client(
        transport=httpx.MockTransport(_filtered_handler(250, seen=seen)), pace=False
    )
    ingest_targeted(store, client, min_feedbacks=3)
    assert len(seen) > 1
    assert all(p["min_feedbacks"] == "3" for p in seen)
    assert [p["offset"] for p in seen] == ["0", "100", "200", "300"]


def test_targeted_sweep_accounts_against_the_filtered_total(tmp_path):
    store = Store(tmp_path / "d.sqlite3")
    client = Scan8004Client(
        transport=httpx.MockTransport(_filtered_handler(250)), pace=False
    )
    result = ingest_targeted(store, client)
    assert result["sampled"] == 250
    assert result["expected"] == 250  # the filtered query's total
    assert result["expected"] != REGISTRY_TOTAL  # never the registry's
    assert result["dropped"] == 0
    assert (
        result["min_feedbacks"] == 1
    )  # so the total can never be read as registry-wide


def test_targeted_sweep_surfaces_dropped_when_bounded(tmp_path):
    store = Store(tmp_path / "d.sqlite3")
    client = Scan8004Client(
        transport=httpx.MockTransport(_filtered_handler(250)), pace=False
    )
    result = ingest_targeted(store, client, max_pages=1)
    assert result["sampled"] == 100
    assert result["expected"] == 250
    assert (
        result["dropped"] == 150
    )  # a bounded filtered sweep states its own incompleteness


def test_targeted_sweep_persists_the_predicate_that_narrowed_it(tmp_path):
    """`min_feedbacks` was returned to the caller and then forgotten. Stored, it travels with
    every figure drawn from the snapshot, so a filtered total can never be read as a census."""
    store = Store(tmp_path / "d.sqlite3")
    client = Scan8004Client(
        transport=httpx.MockTransport(_filtered_handler(150)), pace=False
    )
    result = ingest_targeted(store, client, min_feedbacks=3)
    assert store.snapshot(result["snapshot_id"])["population"] == "min_feedbacks>=3"


def test_unfiltered_sweep_says_so_rather_than_leaving_it_blank(tmp_path):
    store = Store(tmp_path / "d.sqlite3")
    client = Scan8004Client(
        transport=httpx.MockTransport(_paged_handler(250, 100)), pace=False
    )
    result = ingest_bsc(store, client)
    assert store.snapshot(result["snapshot_id"])["population"] == "all"


def test_targeted_sweep_records_its_own_snapshot(tmp_path):
    store = Store(tmp_path / "d.sqlite3")
    client = Scan8004Client(
        transport=httpx.MockTransport(_filtered_handler(150)), pace=False
    )
    result = ingest_targeted(store, client)
    row = store.snapshot(result["snapshot_id"])
    assert row["chain_id"] == 56
    assert row["expected"] == 150
    assert row["sampled"] == 150
    assert row["finished_at"]
    assert store.agent_count(result["snapshot_id"]) == 150


def test_targeted_sweep_adds_a_zero_feedback_owned_agent_to_its_population(tmp_path):
    store = Store(tmp_path / "d.sqlite3")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/agents"):
            offset = int(request.url.params["offset"])
            items = [{**_row(1), "total_feedbacks": 1}] if offset == 0 else []
            return httpx.Response(200, json={"items": items, "total": 1})
        assert request.url.path.endswith("/agents/56/2")
        return httpx.Response(200, json={**_row(2), "agent_id": OWNED_AGENT_ID})

    client = Scan8004Client(transport=httpx.MockTransport(handler), pace=False)
    result = ingest_targeted(store, client, owned_agent_ids=(OWNED_AGENT_ID,))

    assert {row["agent_id"] for row in store.iter_agents(result["snapshot_id"])} == {
        "56:0xreg:1",
        OWNED_AGENT_ID,
    }
    assert result["sampled"] == result["expected"] == 2
    assert result["owned_agents_added"] == 1
    assert store.snapshot(result["snapshot_id"])["population"] == (
        f"min_feedbacks>=1 OR agent_id in ({OWNED_AGENT_ID})"
    )


def test_targeted_sweep_normalizes_an_uppercase_owned_registry_prefix(tmp_path):
    store = Store(tmp_path / "uppercase-prefix.sqlite3")
    supplied = f"56:0X{REGISTRY_ADDRESS[2:].upper()}:2"

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/agents"):
            return httpx.Response(200, json={"items": [], "total": 0})
        assert request.url.path.endswith("/agents/56/2")
        return httpx.Response(200, json={**_row(2), "agent_id": OWNED_AGENT_ID})

    client = Scan8004Client(transport=httpx.MockTransport(handler), pace=False)
    result = ingest_targeted(store, client, owned_agent_ids=(supplied,))

    assert [row["agent_id"] for row in store.iter_agents(result["snapshot_id"])] == [
        OWNED_AGENT_ID
    ]
    assert store.snapshot(result["snapshot_id"])["population"] == (
        f"min_feedbacks>=1 OR agent_id in ({OWNED_AGENT_ID})"
    )


def test_targeted_candidate_can_finish_without_becoming_current(tmp_path):
    store = Store(tmp_path / "d.sqlite3")
    client = Scan8004Client(
        transport=httpx.MockTransport(_filtered_handler(1)), pace=False
    )

    result = ingest_targeted(store, client, promote=False)

    row = store.snapshot(result["snapshot_id"])
    assert row["finished_at"]
    assert row["promoted_at"] is None
    assert store.latest_complete_snapshot_id() is None


def test_targeted_sweep_rejects_a_malformed_owned_agent_id_before_calling_the_api(
    tmp_path,
):
    store = Store(tmp_path / "d.sqlite3")
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(500)

    client = Scan8004Client(transport=httpx.MockTransport(handler), pace=False)
    with pytest.raises(ValueError, match="owned agent id"):
        ingest_targeted(store, client, owned_agent_ids=("56:not-an-address:2",))
    assert calls["n"] == 0


def test_targeted_sweep_refuses_an_owned_agent_detail_for_another_identity(tmp_path):
    store = Store(tmp_path / "d.sqlite3")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/agents"):
            return httpx.Response(200, json={"items": [], "total": 0})
        return httpx.Response(
            200,
            json={**_row(3), "agent_id": f"56:{REGISTRY_ADDRESS}:3"},
        )

    client = Scan8004Client(transport=httpx.MockTransport(handler), pace=False)
    with pytest.raises(ValueError, match="returned agent_id"):
        ingest_targeted(store, client, owned_agent_ids=(OWNED_AGENT_ID,))
    assert store.latest_complete_snapshot_id() is None


def test_targeted_sweep_does_not_promote_when_an_owned_agent_is_missing(tmp_path):
    store = Store(tmp_path / "d.sqlite3")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/agents"):
            return httpx.Response(200, json={"items": [], "total": 0})
        return httpx.Response(404, json={"error": "not found"})

    client = Scan8004Client(transport=httpx.MockTransport(handler), pace=False)
    with pytest.raises(httpx.HTTPStatusError):
        ingest_targeted(store, client, owned_agent_ids=(OWNED_AGENT_ID,))
    assert store.latest_complete_snapshot_id() is None
