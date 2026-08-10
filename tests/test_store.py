import sqlite3
from pathlib import Path

from docket.store import Store

ROW = {
    "agent_id": "56:0x8004a169fb4a3325136eb29fa0ceb6d2e539a432:136384",
    "token_id": "136384",
    "chain_id": 56,
    "contract_address": "0x8004a169fb4a3325136eb29fa0ceb6d2e539a432",
    "owner_address": "0xe4fe23fb57dbb9ac2f685ea29b6b9a1409a0d359",
    "name": "Agent #136384",
    "description": None,
    "supported_protocols": [],
    "x402_supported": True,
    "is_verified": False,
    "total_feedbacks": 0,
    "total_score": 0.0,
    "created_at": "2026-06-16T15:03:30Z",
}


def test_snapshot_roundtrip(tmp_path: Path):
    store = Store(tmp_path / "d.sqlite3")
    sid = store.begin_snapshot(chain_id=56, expected=243421)
    assert store.upsert_agents([ROW], sid) == 1
    store.finish_snapshot(sid, sampled=1)
    assert store.agent_count(sid) == 1
    got = next(store.iter_agents(sid))
    assert got["agent_id"] == ROW["agent_id"]
    assert got["supported_protocols"] == []  # round-trips as a list, not a JSON string
    assert got["x402_supported"] is True  # round-trips as bool, not 0/1


def test_upsert_is_idempotent_and_updates(tmp_path: Path):
    store = Store(tmp_path / "d.sqlite3")
    sid = store.begin_snapshot(chain_id=56, expected=None)
    store.upsert_agents([ROW], sid)
    store.upsert_agents([{**ROW, "name": "SOLVENT", "total_feedbacks": 3}], sid)
    assert store.agent_count(sid) == 1  # no duplicate row
    got = next(store.iter_agents(sid))
    assert got["name"] == "SOLVENT"  # latest write wins
    assert got["total_feedbacks"] == 3


def test_upsert_refreshes_transferred_owner(tmp_path: Path):
    store = Store(tmp_path / "d.sqlite3")
    sid = store.begin_snapshot(chain_id=56, expected=None)
    store.upsert_agents([ROW], sid)
    new_owner = "0x1111111111111111111111111111111111111111"
    store.upsert_agents([{**ROW, "owner_address": new_owner}], sid)
    assert store.agent_count(sid) == 1
    got = next(store.iter_agents(sid))
    assert got["owner_address"] == new_owner  # ownership transfers; a stale owner breaks clustering


def test_token_id_coercion_handles_zero_and_null(tmp_path: Path):
    store = Store(tmp_path / "d.sqlite3")
    sid = store.begin_snapshot(chain_id=56, expected=None)
    absent = {**ROW, "agent_id": "absent"}
    del absent["token_id"]
    store.upsert_agents(
        [
            {**ROW, "agent_id": "zero", "token_id": 0},
            {**ROW, "agent_id": "null", "token_id": None},
            {**ROW, "agent_id": "text", "token_id": "257920"},
            absent,
        ],
        sid,
    )
    stored = {a["agent_id"]: a["token_id"] for a in store.iter_agents(sid)}
    assert stored["zero"] == "0"  # integer zero is a legitimate token id, not falsy-empty
    assert stored["null"] == ""  # not the literal string "None"
    assert stored["text"] == "257920"
    assert stored["absent"] == ""


def test_snapshot_records_partial_coverage(tmp_path: Path):
    store = Store(tmp_path / "d.sqlite3")
    sid = store.begin_snapshot(chain_id=56, expected=100)
    store.upsert_agents([ROW], sid)
    store.finish_snapshot(sid, sampled=1)
    with sqlite3.connect(tmp_path / "d.sqlite3") as conn:
        row = conn.execute(
            "SELECT expected, sampled, finished_at FROM snapshots WHERE id = ?", (sid,)
        ).fetchone()
    assert row[0] == 100 and row[1] == 1 and row[2] is not None


def test_snapshot_records_the_population_it_swept(tmp_path: Path):
    """`expected` states how many rows the query claimed. `population` states which query —
    without it, 506 of 506 reads as a whole-registry census."""
    store = Store(tmp_path / "d.sqlite3")
    filtered = store.begin_snapshot(chain_id=56, expected=506, population="min_feedbacks>=1")
    store.finish_snapshot(filtered, sampled=506)
    assert store.snapshot(filtered)["population"] == "min_feedbacks>=1"
    whole = store.begin_snapshot(chain_id=56, expected=9, population="all")
    assert store.snapshot(whole)["population"] == "all"


def test_registry_total_is_the_largest_total_any_sweep_recorded(tmp_path: Path):
    """The only chain-wide figure Docket holds. A filtered snapshot is unreadable without it:
    506 of 506 is complete, and complete is a fraction of a percent of the chain."""
    store = Store(tmp_path / "d.sqlite3")
    assert store.registry_total(56) is None  # nothing swept, nothing to claim
    full = store.begin_snapshot(chain_id=56, expected=247065, population="all")
    store.finish_snapshot(full, sampled=2000)
    crashed = store.begin_snapshot(chain_id=56, expected=247146, population="all")
    filtered = store.begin_snapshot(chain_id=56, expected=506, population="min_feedbacks>=1")
    store.finish_snapshot(filtered, sampled=506)
    # The crashed sweep's `expected` still counts: it is what the API answered when asked,
    # recorded before the sweep died, and it does not depend on the sweep finishing.
    assert store.registry_total(56) == 247146
    assert store.snapshot(crashed)["sampled"] is None
    assert store.registry_total(97) is None  # another chain's sweeps are not this chain's


def test_a_database_predating_the_column_is_migrated_not_rejected(tmp_path: Path):
    """The live database was written before this column existed. Its rows cannot state a
    population they never recorded, so they read as None — unspecified, never guessed at."""
    path = tmp_path / "legacy.sqlite3"
    with sqlite3.connect(path) as conn:
        conn.executescript(
            """CREATE TABLE snapshots (
                   id INTEGER PRIMARY KEY AUTOINCREMENT,
                   chain_id INTEGER NOT NULL,
                   expected INTEGER,
                   sampled INTEGER,
                   started_at TEXT NOT NULL,
                   finished_at TEXT
               );
               INSERT INTO snapshots (chain_id, expected, sampled, started_at, finished_at)
               VALUES (56, 506, 506, '2026-08-07T17:50:23+00:00', '2026-08-07T17:51:02+00:00');"""
        )
    store = Store(path)
    assert store.snapshot(1)["population"] is None
    assert store.latest_complete_snapshot_id(56) == 1  # still readable, still servable
    fresh = store.begin_snapshot(chain_id=56, expected=1, population="all")
    assert store.snapshot(fresh)["population"] == "all"


def test_latest_complete_snapshot_skips_a_sweep_that_never_finished(tmp_path: Path):
    """A crashed or in-flight sweep is the newest ROW, and its counts are still moving. The
    live database carries exactly this: snapshot 2 was begun on 2026-08-07 and never closed."""
    store = Store(tmp_path / "d.sqlite3")
    first = store.begin_snapshot(chain_id=56, expected=10)
    store.finish_snapshot(first, sampled=10)
    crashed = store.begin_snapshot(chain_id=56, expected=10)
    assert store.latest_snapshot_id(56) == crashed  # the newest row, still the newest row
    assert store.latest_complete_snapshot_id(56) == first  # never the unfinished one

    third = store.begin_snapshot(chain_id=56, expected=10)
    store.finish_snapshot(third, sampled=10)
    assert store.latest_complete_snapshot_id(56) == third  # a later finish wins again


def test_latest_complete_snapshot_is_per_chain_and_none_when_nothing_finished(tmp_path: Path):
    store = Store(tmp_path / "d.sqlite3")
    store.begin_snapshot(chain_id=56, expected=10)
    assert store.latest_complete_snapshot_id(56) is None  # no finished sweep to serve
    other = store.begin_snapshot(chain_id=97, expected=4)
    store.finish_snapshot(other, sampled=4)
    assert store.latest_complete_snapshot_id(56) is None  # another chain's is not this chain's
    assert store.latest_complete_snapshot_id(97) == other


def test_endpoints_roundtrip_and_upsert_is_idempotent(tmp_path: Path):
    store = Store(tmp_path / "d.sqlite3")
    sid = store.begin_snapshot(chain_id=56, expected=None)
    rows = [
        {"agent_id": "56:r:1", "kind": "a2a", "url": "https://a.example/agent"},
        {"agent_id": "56:r:1", "kind": "mcp", "url": "https://a.example/mcp"},
    ]
    assert store.upsert_endpoints(rows, sid) == 2
    store.upsert_endpoints(rows, sid)  # same rows again
    assert store.endpoint_count(sid) == 2  # no duplicates
    kinds = {e["kind"] for e in store.iter_endpoints(sid)}
    assert kinds == {"a2a", "mcp"}
    assert [e["url"] for e in store.iter_endpoints(sid, kind="mcp")] == ["https://a.example/mcp"]


def test_enriched_agent_ids_reports_what_has_been_processed(tmp_path: Path):
    store = Store(tmp_path / "d.sqlite3")
    sid = store.begin_snapshot(chain_id=56, expected=None)
    store.upsert_endpoints([{"agent_id": "56:r:1", "kind": "a2a", "url": "https://a/x"}], sid)
    store.mark_enriched(["56:r:1", "56:r:2"], sid)  # r:2 had no endpoints at all
    assert store.enriched_agent_ids(sid) == {"56:r:1", "56:r:2"}


def test_liveness_rows_are_append_only_observations(tmp_path: Path):
    store = Store(tmp_path / "d.sqlite3")
    sid = store.begin_snapshot(chain_id=56, expected=None)
    obs = {
        "snapshot_id": sid,
        "agent_id": "56:r:1",
        "url": "https://a/x",
        "observed_at": "2026-08-07T10:00:00+00:00",
        "outcome": "responded",
        "status_code": 200,
        "elapsed_ms": 143,
        "detail": None,
    }
    assert store.record_liveness([obs]) == 1
    assert (
        store.record_liveness(
            [
                {
                    **obs,
                    "observed_at": "2026-08-07T11:00:00+00:00",
                    "outcome": "timeout",
                    "status_code": None,
                    "elapsed_ms": 8000,
                    "detail": "ReadTimeout",
                }
            ]
        )
        == 1
    )
    seen = list(store.iter_liveness(sid))
    assert len(seen) == 2  # history is kept, not overwritten
    assert {s["outcome"] for s in seen} == {"responded", "timeout"}
