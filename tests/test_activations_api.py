"""The activation routes, driven through the shipped application with real signatures."""

from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest
from eth_account import Account
from eth_account.messages import encode_defunct
from fastapi.testclient import TestClient

from docket.agents.pancake import doctor
from docket.api import create_app
from docket.hire.catalogue import SERVICES, get_service
from docket.jobs.auth import action_message, create_message
from docket.store import Store
from tests.test_jobs_service import POLICY

OWNER = Account.from_key("0x" + "31" * 32)
STRANGER = Account.from_key("0x" + "32" * 32)


@pytest.fixture(autouse=True)
def stub_the_work(monkeypatch):
    """No test here touches an RPC. `_run_range_doctor` reaches `doctor.report` through
    the module attribute, so replacing it covers every activation that runs."""
    monkeypatch.setattr(
        doctor,
        "report",
        lambda address, **kwargs: {"address": address, "positions": []},
    )
    monkeypatch.setitem(
        SERVICES,
        "range-doctor",
        replace(
            get_service("range-doctor"), run=lambda payload: {"read": payload["wallet"]}
        ),
    )


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.delenv("DOCKET_PAY_TO", raising=False)
    monkeypatch.delenv("DOCKET_SESSION_KEY_FILE", raising=False)
    return TestClient(create_app(tmp_path / "activations.sqlite3"))


def _sign(account, message: str) -> str:
    return "0x" + account.sign_message(
        encode_defunct(text=message)
    ).signature.hex().removeprefix("0x")


def _create(
    client, account=OWNER, *, service_id="range-doctor", kind="one_shot", **extra
):
    nonce = client.get(
        f"/api/activations/nonce?owner={account.address}&service_id={service_id}"
    ).json()
    body = {
        "service_id": service_id,
        "kind": kind,
        "owner": account.address,
        "nonce": nonce["nonce"],
        "owner_signature": _sign(account, nonce["message"]),
        "inputs": {"wallet": account.address},
    }
    body.update(extra)
    return client.post("/api/activations", json=body)


def _act(client, activation, action, account=OWNER, **extra):
    body = {
        "nonce": activation["auth_nonce"],
        "owner_signature": _sign(
            account,
            action_message(
                activation["activation_id"], action, activation["auth_nonce"]
            ),
        ),
    }
    body.update(extra)
    return client.post(
        f"/api/activations/{activation['activation_id']}/{action}", json=body
    )


# -- the nonce ----------------------------------------------------------------


def test_the_nonce_route_issues_the_exact_message_to_sign(client):
    response = client.get(
        f"/api/activations/nonce?owner={OWNER.address}&service_id=range-doctor"
    )

    body = response.json()
    assert response.status_code == 200
    assert body["message"] == create_message("range-doctor", body["nonce"])
    assert body["expires_in_seconds"] == 600


def test_the_nonce_route_serves_a_nonce_without_a_service_and_says_what_is_missing(
    client,
):
    body = client.get(f"/api/activations/nonce?owner={OWNER.address}").json()

    assert body["message"] is None
    assert "call again with &service_id=" in body["sign"]


def test_the_nonce_route_needs_an_owner(client):
    response = client.get("/api/activations/nonce")

    assert response.status_code == 422
    assert response.json()["error_code"] == "missing_field"


def test_the_nonce_route_is_not_read_as_an_activation_id(client):
    """Declared before `/{activation_id}` on purpose. If the order slipped, a caller
    asking for a nonce would be told no such activation exists."""
    assert (
        client.get(f"/api/activations/nonce?owner={OWNER.address}").status_code == 200
    )


# -- creating -----------------------------------------------------------------


def test_a_signed_create_returns_the_whole_activation(client):
    response = _create(client)

    body = response.json()
    assert response.status_code == 201
    assert body["state"] == "authorized"
    assert body["category"] == "rebalancing"
    assert body["owner"] == OWNER.address
    assert body["quote"]["payment_scheme"] == "free_tier"
    assert body["next_action"]["kind"] == "none"
    assert [event["to_state"] for event in body["events"]] == [
        "awaiting_wallet",
        "authorized",
    ]


def test_a_create_signed_by_nobody_is_a_bad_signature(client):
    nonce = client.get(
        f"/api/activations/nonce?owner={OWNER.address}&service_id=range-doctor"
    ).json()

    response = client.post(
        "/api/activations",
        json={
            "service_id": "range-doctor",
            "kind": "one_shot",
            "owner": OWNER.address,
            "nonce": nonce["nonce"],
            "owner_signature": "0x" + "00" * 65,
            "inputs": {"wallet": OWNER.address},
        },
    )

    assert response.status_code == 401
    assert response.json()["error_code"] == "bad_signature"


def test_a_create_signed_by_somebody_else_does_not_recover_to_the_named_owner(client):
    nonce = client.get(
        f"/api/activations/nonce?owner={OWNER.address}&service_id=range-doctor"
    ).json()

    response = client.post(
        "/api/activations",
        json={
            "service_id": "range-doctor",
            "kind": "one_shot",
            "owner": OWNER.address,
            "nonce": nonce["nonce"],
            "owner_signature": _sign(STRANGER, nonce["message"]),
            "inputs": {"wallet": OWNER.address},
        },
    )

    assert response.status_code == 401
    assert response.json()["error_code"] == "bad_signature"


def test_a_create_nonce_cannot_be_spent_twice(client):
    nonce = client.get(
        f"/api/activations/nonce?owner={OWNER.address}&service_id=range-doctor"
    ).json()
    body = {
        "service_id": "range-doctor",
        "kind": "one_shot",
        "owner": OWNER.address,
        "nonce": nonce["nonce"],
        "owner_signature": _sign(OWNER, nonce["message"]),
        "inputs": {"wallet": OWNER.address},
    }

    assert client.post("/api/activations", json=body).status_code == 201
    replayed = client.post("/api/activations", json=body)

    assert replayed.status_code == 409
    assert replayed.json()["error_code"] == "stale_nonce"


def test_a_create_for_a_service_with_no_category_is_not_found(client):
    response = _create(client, service_id="solvent-signal")

    assert response.status_code == 404
    assert response.json()["error_code"] == "service_not_found"


def test_a_create_missing_a_required_input_names_the_field(client):
    response = _create(client, inputs={})

    assert response.status_code == 422
    assert response.json()["error_code"] == "missing_field"
    assert "wallet" in response.json()["message"]


def test_a_create_missing_its_own_fields_is_refused_in_the_activation_error_shape(
    client,
):
    response = client.post("/api/activations", json={"service_id": "range-doctor"})

    assert response.status_code == 422
    assert set(response.json()) == {"error_code", "message"}
    assert response.json()["error_code"] == "missing_field"


def test_a_create_with_an_unknown_kind_is_refused(client):
    response = _create(client, kind="subscription")

    assert response.status_code == 422
    assert response.json()["error_code"] == "missing_field"


def test_a_body_that_is_not_json_is_refused(client):
    response = client.post(
        "/api/activations",
        content=b"{not json",
        headers={"content-type": "application/json"},
    )

    assert response.status_code == 400
    assert response.json()["error_code"] == "invalid_json"


# -- reading ------------------------------------------------------------------


def test_an_activation_can_be_read_back_and_listed_by_its_owner(client):
    created = _create(client).json()
    _create(client, STRANGER)

    assert (
        client.get(f"/api/activations/{created['activation_id']}").json()["state"]
        == "authorized"
    )
    listed = client.get(f"/api/activations?owner={OWNER.address}").json()
    assert listed["total"] == 1
    assert listed["activations"][0]["activation_id"] == created["activation_id"]
    assert client.get("/api/activations").json()["total"] == 2
    assert client.get("/api/activations?state=completed").json()["total"] == 0


def test_an_unknown_activation_is_a_404_in_the_activation_error_shape(client):
    response = client.get("/api/activations/act_000000000000000000000000")

    assert response.status_code == 404
    assert response.json() == {
        "error_code": "activation_not_found",
        "message": "No activation 'act_000000000000000000000000'.",
    }


def test_a_page_outside_its_bounds_is_refused(client):
    assert client.get("/api/activations?limit=0").status_code == 422
    assert client.get("/api/activations?limit=nine").status_code == 422
    assert client.get("/api/activations?offset=-1").status_code == 422


# -- mutating -----------------------------------------------------------------


def test_approving_a_free_tier_activation_runs_it_and_rotates_the_nonce(client):
    created = _create(client).json()

    response = _act(client, created, "approve")

    body = response.json()
    assert response.status_code == 200
    assert body["state"] == "completed"
    assert body["result"] == {"read": OWNER.address}
    assert body["auth_nonce"] != created["auth_nonce"]
    assert body["receipts"][0]["payment"] is None


def test_a_spent_nonce_cannot_be_presented_again(client):
    created = _create(client).json()
    _act(client, created, "pause")

    replayed = _act(client, created, "pause")

    assert replayed.status_code == 409
    assert replayed.json()["error_code"] == "stale_nonce"


def test_a_signature_from_somebody_who_is_not_the_owner_is_not_owner(client):
    created = _create(client).json()

    response = _act(client, created, "cancel", account=STRANGER)

    assert response.status_code == 403
    assert response.json()["error_code"] == "not_owner"
    assert STRANGER.address in response.json()["message"]


def test_an_unreadable_signature_is_a_bad_signature(client):
    created = _create(client).json()

    response = client.post(
        f"/api/activations/{created['activation_id']}/cancel",
        json={"nonce": created["auth_nonce"], "owner_signature": "0xnot-a-signature"},
    )

    assert response.status_code == 401
    assert response.json()["error_code"] == "bad_signature"


def test_a_mutating_call_without_its_proof_names_what_is_missing(client):
    created = _create(client).json()

    response = client.post(
        f"/api/activations/{created['activation_id']}/cancel", json={}
    )

    assert response.status_code == 422
    assert response.json()["error_code"] == "missing_field"


def test_pausing_a_one_shot_activation_is_an_illegal_transition(client):
    created = _create(client).json()

    response = _act(client, created, "pause")

    assert response.status_code == 409
    assert response.json()["error_code"] == "illegal_transition"


def test_cancelling_a_one_shot_activation_refunds_it(client):
    created = _create(client).json()

    response = _act(client, created, "cancel")

    assert response.status_code == 200
    assert response.json()["state"] == "refunded"


def test_approving_a_completed_activation_is_refused(client):
    created = _create(client).json()
    completed = _act(client, created, "approve").json()

    response = _act(client, completed, "approve")

    assert response.status_code == 409
    assert response.json()["error_code"] == "illegal_transition"


def test_a_mutating_call_on_an_activation_that_does_not_exist_is_not_found(client):
    response = client.post(
        "/api/activations/act_000000000000000000000000/pause",
        json={"nonce": "n", "owner_signature": "0x" + "00" * 65},
    )

    assert response.status_code == 404
    assert response.json()["error_code"] == "activation_not_found"


# -- prepared calls -----------------------------------------------------------


def test_prepared_is_empty_for_an_activation_with_nothing_to_sign(client):
    created = _create(client).json()

    response = client.get(f"/api/activations/{created['activation_id']}/prepared")

    assert response.status_code == 200
    assert response.json() == {"calls": []}


def test_a_call_the_chain_refused_is_answered_as_simulation_failed(client, tmp_path):
    created = _create(client).json()
    store = Store(tmp_path / "activations.sqlite3")
    activation = store.get_activation(created["activation_id"])
    expected = activation.updated_at
    from docket.jobs.models import NextAction

    activation.next_action = NextAction(
        "sign_transaction",
        {
            "calls": [
                {
                    "to": "0x10ED43C718714eb63d5aA57B78B54704E256024E",
                    "data": "0x38ed1739",
                    "value_atomic": "0",
                    "chain_id": 56,
                    "gas_ceiling": 300000,
                    "deadline": 1,
                    "purpose": "recenter",
                    "simulation": {"ok": False, "revert_reason": "TOO_LITTLE_RECEIVED"},
                }
            ]
        },
    )
    store.save_activation(activation, expected_updated_at=expected)

    response = client.get(f"/api/activations/{created['activation_id']}/prepared")

    assert response.status_code == 409
    assert response.json()["error_code"] == "simulation_failed"
    assert "TOO_LITTLE_RECEIVED" in response.json()["message"]


# -- persistent ---------------------------------------------------------------


def test_a_persistent_activation_is_refused_where_no_master_password_is_installed(
    client,
):
    response = _create(client, kind="persistent", policy=POLICY)

    assert response.status_code == 503
    assert response.json()["error_code"] == "sessions_unavailable"


def test_a_persistent_activation_with_a_master_password_asks_the_owner_to_fund_it(
    tmp_path, monkeypatch
):
    key_file = tmp_path / "sessions.key"
    key_file.write_text("a-test-master-password\n", encoding="utf-8")
    monkeypatch.setenv("DOCKET_SESSION_KEY_FILE", str(key_file))
    monkeypatch.delenv("DOCKET_PAY_TO", raising=False)
    client = TestClient(create_app(tmp_path / "persistent.sqlite3"))

    body = _create(client, kind="persistent", policy=POLICY).json()

    assert body["state"] == "authorized"
    assert body["next_action"]["kind"] == "fund_session"
    assert set(body["session"]) == {"address", "funded_atomic", "spent_atomic"}
    assert body["policy"]["max_slippage_bps"] == 100
    assert body["expires_at"] == POLICY["expires_at"]


def test_a_persistent_activation_with_an_unbounded_policy_is_a_policy_violation(
    tmp_path, monkeypatch
):
    key_file = tmp_path / "sessions.key"
    key_file.write_text("a-test-master-password\n", encoding="utf-8")
    monkeypatch.setenv("DOCKET_SESSION_KEY_FILE", str(key_file))
    client = TestClient(create_app(tmp_path / "unbounded.sqlite3"))

    response = _create(
        client, kind="persistent", policy={**POLICY, "token_allowlist": []}
    )

    assert response.status_code == 422
    assert response.json()["error_code"] == "policy_violation"


def test_a_persistent_activation_without_a_policy_is_a_policy_violation(
    tmp_path, monkeypatch
):
    key_file = tmp_path / "sessions.key"
    key_file.write_text("a-test-master-password\n", encoding="utf-8")
    monkeypatch.setenv("DOCKET_SESSION_KEY_FILE", str(key_file))
    client = TestClient(create_app(tmp_path / "nopolicy.sqlite3"))

    response = _create(client, kind="persistent")

    assert response.status_code == 409
    assert response.json()["error_code"] == "policy_violation"


def test_an_expired_policy_closes_the_activation_and_answers_expired(
    tmp_path, monkeypatch
):
    """`validate()` parses `expires_at` but does not require it to be in the future, so a
    policy can be created already expired. The first call after that closes it."""
    key_file = tmp_path / "sessions.key"
    key_file.write_text("a-test-master-password\n", encoding="utf-8")
    monkeypatch.setenv("DOCKET_SESSION_KEY_FILE", str(key_file))
    client = TestClient(create_app(tmp_path / "expired.sqlite3"))
    past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    created = _create(
        client, kind="persistent", policy={**POLICY, "expires_at": past}
    ).json()

    response = _act(client, created, "pause")

    assert response.status_code == 409
    assert response.json()["error_code"] == "expired"
    read_back = client.get(f"/api/activations/{created['activation_id']}").json()
    assert read_back["state"] == "expired"


def test_an_owner_is_the_same_owner_however_the_wallet_spells_it(client):
    """A nonce taken with a lowercase address and a create sent with a checksummed one
    are the same person. Storing both as typed would answer `stale_nonce` to a wallet
    that did nothing wrong."""
    nonce = client.get(
        f"/api/activations/nonce?owner={OWNER.address.lower()}&service_id=range-doctor"
    ).json()

    response = client.post(
        "/api/activations",
        json={
            "service_id": "range-doctor",
            "kind": "one_shot",
            "owner": OWNER.address,
            "nonce": nonce["nonce"],
            "owner_signature": _sign(OWNER, nonce["message"]),
            "inputs": {"wallet": OWNER.address},
        },
    )

    assert response.status_code == 201
    assert (
        client.get(f"/api/activations?owner={OWNER.address.lower()}").json()["total"]
        == 1
    )


def test_the_nonce_route_refuses_an_owner_that_is_not_an_address(client):
    response = client.get("/api/activations/nonce?owner=not-an-address")

    assert response.status_code == 422
    assert response.json()["error_code"] == "missing_field"


def test_registering_the_router_leaves_every_existing_route_working(client):
    """One `include_router` line above the static mount, and nothing else moved."""
    assert client.get("/services").status_code == 200
    assert client.get("/categories").status_code == 200
    assert client.get("/llms.txt").status_code == 200
    assert client.get("/static/style.css").status_code == 200
    # The rest of the API keeps its own error envelope; only these routes use the other.
    assert set(client.get("/agents/nope").json()) == {"error"}
