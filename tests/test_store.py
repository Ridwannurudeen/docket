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
