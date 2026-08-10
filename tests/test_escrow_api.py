"""The escrow rail on both doors.

`/escrow` is static and needs no chain, so it is tested directly. `/escrow/job/{id}`
reads chain, so the reader is replaced rather than the network being called: a test that
depends on a live job is a test that fails when somebody else settles it.
"""

import pytest
from fastapi.testclient import TestClient

from docket.api import create_app
from docket.escrow import constants as c
from docket.escrow.chain import JobNotFound
from docket.store import Store

JOB = {
    "job_id": 4242,
    "chain_id": 56,
    "status": "SUBMITTED",
    "client": "0x000000000000000000000000000000000000C11e",
    "provider": "0x000000000000000000000000000000000000B0b0",
    "budget_atomic": "10000000000000000",
    "budget_display": "0.01 $U",
    "expired_at": 1786000000,
    "submitted_at": 1785000000,
    "policy": c.POLICY,
    "disputed": False,
    "settle_at": 1785604800,
    "settle_ready": True,
    "dispute_window_seconds": c.DISPUTE_WINDOW_S,
    "read_at_block": 115000000,
    "read_at_timestamp": 1786000001,
}


@pytest.fixture
def client(tmp_path, monkeypatch):
    db = tmp_path / "t.sqlite3"
    store = Store(db)
    sid = store.begin_snapshot(chain_id=56, expected=0)
    store.finish_snapshot(sid, sampled=0, expected=0)

    class _Reader:
        def job_state(self, job_id):
            if job_id == 500001:
                raise ConnectionError("every endpoint failed")
            if job_id != 4242:
                raise JobNotFound("no such job")
            return dict(JOB, job_id=job_id)

    monkeypatch.setattr("docket.api.routes.JobReader", lambda *a, **kw: _Reader())
    return TestClient(create_app(db, snapshot_id=sid))


def test_escrow_terms_state_the_window_in_seconds_and_in_words(client):
    body = client.get("/escrow").json()
    assert body["dispute_window_seconds"] == 604800
    assert "7 day" in body["dispute_window_plain"].lower()
    assert body["chain_id"] == 56
    assert body["contracts"]["router"] == c.ROUTER
    assert body["payment_token"]["address"] == c.PAYMENT_TOKEN


def test_escrow_terms_say_what_docket_does_not_do(client):
    """A buyer must not have to infer custody from silence."""
    body = client.get("/escrow").json()
    text = " ".join(body["docket_does_not"]).lower()
    assert "key" in text
    assert "custody" in text or "hold" in text


def test_escrow_terms_carry_the_ordered_call_sequence(client):
    steps = client.get("/escrow").json()["hire_sequence"]
    assert [s["function"] for s in steps] == [
        "createJob",
        "registerJob",
        "setBudget",
        "approve",
        "fund",
    ]
    assert all("note" in s for s in steps)


def test_escrow_terms_name_the_buyers_lever_and_not_the_voters_one(client):
    """voteReject is restricted to whitelisted voters; pointing a buyer at it would
    produce a confusing revert and nothing else."""
    body = client.get("/escrow").json()
    assert "dispute" in body["buyer_lever"]["function"]
    assert "voteReject" not in client.get("/escrow").text


def test_job_state_is_served_for_a_real_job(client):
    body = client.get("/escrow/job/4242").json()
    assert body["status"] == "SUBMITTED"
    assert body["settle_ready"] is True
    assert body["settle_at"] == 1785604800


def test_an_unknown_job_returns_the_structured_error_not_a_500(client):
    resp = client.get("/escrow/job/999999999")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"]


def test_an_unreachable_node_is_not_reported_as_a_missing_job(client):
    """404 tells a caller their job does not exist. If the truth is that Docket could not
    reach a node, that is a different and worse untruth than saying nothing."""
    resp = client.get("/escrow/job/500001")
    assert resp.status_code == 502
    assert resp.json()["error"]["code"] == "chain_unreachable"


def test_llms_txt_documents_the_escrow_paths(client):
    """The existing drift guard requires every OpenAPI path to appear in llms.txt; this
    states the intent directly so a failure names the cause."""
    body = client.get("/llms.txt").text
    assert "/escrow" in body
    assert "/escrow/job/" in body
