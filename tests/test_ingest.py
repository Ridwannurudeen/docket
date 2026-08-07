import httpx

from docket.ingest import ingest_bsc
from docket.scan8004 import Scan8004Client
from docket.store import Store


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
    client = Scan8004Client(transport=httpx.MockTransport(_paged_handler(250, 100)), pace=False)
    result = ingest_bsc(store, client)
    assert result["sampled"] == 250
    assert result["expected"] == 250
    assert result["dropped"] == 0
    assert store.agent_count(result["snapshot_id"]) == 250


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
            raise AssertionError("sweep did not terminate: the stuck paginator was polled 6 times")
        return httpx.Response(200, json={"items": [_row(t) for t in range(10)], "total": 30})

    client = Scan8004Client(transport=httpx.MockTransport(handler), pace=False)
    result = ingest_bsc(store, client)  # no max_pages — liveness must come from the guard
    assert result["pages"] == 1
    assert result["sampled"] == 10
    assert result["dropped"] == 20


def test_max_pages_bounds_the_sweep(tmp_path):
    store = Store(tmp_path / "d.sqlite3")
    client = Scan8004Client(transport=httpx.MockTransport(_paged_handler(1000, 100)), pace=False)
    result = ingest_bsc(store, client, max_pages=2)
    assert result["pages"] == 2
    assert result["sampled"] == 200
    assert result["expected"] == 1000
    assert result["dropped"] == 800  # a bounded sweep states its own incompleteness


def test_duplicate_rows_across_pages_do_not_inflate_the_count(tmp_path):
    store = Store(tmp_path / "d.sqlite3")

    def handler(request: httpx.Request) -> httpx.Response:
        # Every page returns the same 10 rows — a pathological paginator.
        return httpx.Response(200, json={"items": [_row(t) for t in range(10)], "total": 30})

    client = Scan8004Client(transport=httpx.MockTransport(handler), pace=False)
    result = ingest_bsc(store, client, max_pages=3)
    assert store.agent_count(result["snapshot_id"]) == 10
    assert result["sampled"] == 10  # counted from the store, not from pages served
