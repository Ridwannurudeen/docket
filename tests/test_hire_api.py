import base64
import hashlib
import json
import time

import pytest
from eth_account import Account
from eth_account.messages import encode_typed_data
from fastapi.testclient import TestClient

from docket.agents.pancake import doctor
from docket.api import create_app
from docket.api.routes import FREE_TIER_HIRES
from docket.hire.catalogue import U_TOKEN, get_service

PAY_TO = "0x" + "11" * 20
WALLET = "0x451871A1753903FB8fdd64a6B838E95aB8D5B80f"


@pytest.fixture(autouse=True)
def stub_the_work(monkeypatch):
    """No test here touches an RPC or waits 30 seconds for one. `_run_range_doctor` calls
    `doctor.report` through the module attribute, so replacing it covers every hire."""
    monkeypatch.setattr(
        doctor,
        "report",
        lambda address, **kwargs: {"address": address, "positions": [], "positions_held": 0},
    )


def _client(tmp_path, monkeypatch, *, name="free", pay_to=None):
    if pay_to is None:
        monkeypatch.delenv("DOCKET_PAY_TO", raising=False)
    else:
        monkeypatch.setenv("DOCKET_PAY_TO", pay_to)
    # No snapshot is ingested: hiring must not depend on one.
    return TestClient(create_app(tmp_path / f"{name}.sqlite3"))


def _authorization(acct, *, to=PAY_TO, value=10**16):
    domain = {"name": "United Stables", "version": "1", "chainId": 56, "verifyingContract": U_TOKEN}
    types = {
        "TransferWithAuthorization": [
            {"name": "from", "type": "address"},
            {"name": "to", "type": "address"},
            {"name": "value", "type": "uint256"},
            {"name": "validAfter", "type": "uint256"},
            {"name": "validBefore", "type": "uint256"},
            {"name": "nonce", "type": "bytes32"},
        ]
    }
    msg = {
        "from": acct.address,
        "to": to,
        "value": value,
        "validAfter": 0,
        "validBefore": int(time.time()) + 300,
        "nonce": b"\x03" * 32,
    }
    sig = acct.sign_message(encode_typed_data(domain, types, msg))
    auth = {
        "domain": domain,
        "types": types,
        "message": {**msg, "nonce": "0x" + "03" * 32},
        "signature": sig.signature.hex(),
    }
    return base64.b64encode(json.dumps(auth).encode()).decode()


def _sha256_of_canonical_json(obj) -> str:
    blob = json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "0x" + hashlib.sha256(blob.encode("utf-8")).hexdigest()


def test_the_catalogue_tells_a_stranger_what_to_send(tmp_path, monkeypatch):
    body = _client(tmp_path, monkeypatch).get("/hire").json()
    listed = {svc["id"]: svc for svc in body["services"]}
    assert "range-doctor" in listed
    svc = listed["range-doctor"]
    assert svc["what_you_get"] and svc["typical_seconds"] > 0
    assert svc["price_display"] and svc["price_atomic"] and svc["asset"]
    assert svc["input_schema"]["wallet"]["required"] is True


def test_a_hire_returns_a_receipt_the_caller_can_recompute(tmp_path, monkeypatch):
    """The receipt is only worth something if its holder can check it without Docket."""
    payload = {"wallet": WALLET, "limit": 3}
    body = _client(tmp_path, monkeypatch).post("/hire/range-doctor", json=payload).json()

    receipt = body["receipt"]
    assert receipt["service"] == "range-doctor"
    assert receipt["input_hash"] == _sha256_of_canonical_json(payload)
    assert receipt["output_hash"] == _sha256_of_canonical_json(body["result"])
    assert receipt["payment"]["status"] == "free_tier"
    assert body["result"]["address"] == WALLET


def test_a_missing_required_field_is_named(tmp_path, monkeypatch):
    resp = _client(tmp_path, monkeypatch).post("/hire/range-doctor", json={"limit": 3})
    assert resp.status_code == 422
    err = resp.json()["error"]
    assert err["code"] == "missing_field"
    assert "wallet" in err["message"]


def test_an_unknown_service_is_a_structured_404(tmp_path, monkeypatch):
    resp = _client(tmp_path, monkeypatch).post("/hire/nope", json={"wallet": WALLET})
    assert resp.status_code == 404
    err = resp.json()["error"]
    assert err["code"] == "service_not_found"
    assert "/hire" in err["message"]


def test_the_allowance_exists_only_where_a_payment_route_does(tmp_path, monkeypatch):
    """With no DOCKET_PAY_TO there is nothing a 402 could ask for, so the free tier serves
    unmetered: a missing configuration must never be what stops a cold caller."""
    unmetered = _client(tmp_path, monkeypatch, name="unmetered")
    for _ in range(FREE_TIER_HIRES + 5):
        assert unmetered.post("/hire/range-doctor", json={"wallet": WALLET}).status_code == 200

    metered = _client(tmp_path, monkeypatch, name="metered", pay_to=PAY_TO)
    for _ in range(FREE_TIER_HIRES):
        assert metered.post("/hire/range-doctor", json={"wallet": WALLET}).status_code == 200

    resp = metered.post("/hire/range-doctor", json={"wallet": WALLET})
    assert resp.status_code == 402
    body = resp.json()
    assert body["x402Version"] == 2
    assert body["accepts"][0]["payTo"] == PAY_TO
    assert body["error"]["code"] == "free_tier_exhausted"


def test_a_verified_authorization_is_served_and_never_called_settled(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch, pay_to=PAY_TO)
    header = _authorization(Account.create())
    resp = client.post("/hire/range-doctor", json={"wallet": WALLET}, headers={"X-PAYMENT": header})
    assert resp.status_code == 200
    payment = resp.json()["receipt"]["payment"]
    assert payment["status"] == "verified_unsettled"
    assert "settlement" in payment


def test_no_hire_response_claims_a_settlement(tmp_path, monkeypatch):
    """The one overclaim this project must not make. "unpaid" and "prepaid" would fail too,
    which is the point: the whole family is banned, not one spelling."""
    client = _client(tmp_path, monkeypatch, pay_to=PAY_TO)
    svc = get_service("range-doctor")
    responses = [
        client.get("/hire"),
        client.post("/hire/range-doctor", json={"wallet": WALLET}),
        client.post(
            "/hire/range-doctor",
            json={"wallet": WALLET},
            headers={"X-PAYMENT": _authorization(Account.create())},
        ),
        client.post("/hire/range-doctor", json={"limit": 1}),
        client.post("/hire/nope", json={"wallet": WALLET}),
        client.post("/hire/range-doctor", content=b"not json"),
    ]
    for _ in range(FREE_TIER_HIRES):
        client.post("/hire/range-doctor", json={"wallet": WALLET})
    responses.append(client.post("/hire/range-doctor", json={"wallet": WALLET}))

    for resp in responses:
        assert "paid" not in resp.text.lower(), resp.text
    assert "paid" not in f"{svc.name} {svc.what_you_get}".lower()
