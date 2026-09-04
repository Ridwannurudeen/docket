"""The activation routes, driven through the shipped application with real signatures."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta

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
    binds = str(extra.get("tx_hash") or extra.get("payment_id") or "")
    body = {
        "nonce": activation["auth_nonce"],
        "owner_signature": _sign(
            account,
            action_message(
                activation["activation_id"], action, activation["auth_nonce"], binds
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
    assert (
        client.get(
            f"/api/activations?owner={OWNER.address}&state=completed"
        ).json()["total"]
        == 0
    )


def test_the_listing_will_not_enumerate_the_whole_site(client):
    """Without an owner this route is a directory of who is running what."""
    _create(client)

    unfiltered = client.get("/api/activations")

    assert unfiltered.status_code == 422
    assert unfiltered.json()["error_code"] == "missing_field"
    assert client.get("/api/activations?state=authorized").status_code == 422


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


def test_the_api_needs_no_master_password_to_create_a_persistent_activation(client):
    """The architecture, from the outside: the web process holds no key, so it cannot
    mint one and does not need to. It records the request and the tick does the rest."""
    response = _create(client, kind="persistent", policy=POLICY)

    body = response.json()
    assert response.status_code == 201
    assert body["state"] == "awaiting_session"
    assert body["session"] is None
    assert body["next_action"] == {
        "kind": "wait",
        "detail": {
            "reason": "session being created",
            "poll_seconds": 5,
            "nft_approvals": [],
        },
    }


def test_every_route_serves_with_no_session_key_file_configured(client, monkeypatch):
    """The whole API surface, with the master password absent. Nothing in the web process
    may need it: if one route did, an operator who had not installed the file would find
    that out from a 500 in front of a user."""
    monkeypatch.delenv("DOCKET_SESSION_KEY_FILE", raising=False)
    created = _create(client, kind="persistent", policy=POLICY).json()
    one_shot = _create(client).json()

    assert client.get(f"/api/activations?owner={OWNER.address}").status_code == 200
    assert client.get(f"/api/activations/{created['activation_id']}").status_code == 200
    assert (
        client.get(
            f"/api/activations/{created['activation_id']}/prepared"
        ).status_code
        == 200
    )
    assert (
        client.get(f"/api/activations/nonce?owner={OWNER.address}").status_code == 200
    )
    assert _act(client, created, "pause").status_code == 409
    # The failed pause spent the nonce, so the next call reads the fresh one.
    created = client.get(f"/api/activations/{created['activation_id']}").json()
    assert _act(client, created, "revoke").status_code == 200
    assert _act(client, one_shot, "approve").status_code == 200


def test_a_persistent_activation_with_a_master_password_asks_the_owner_to_fund_it(
    tmp_path, monkeypatch
):
    key_file = tmp_path / "sessions.key"
    key_file.write_text("a-test-master-password\n", encoding="utf-8")
    monkeypatch.setenv("DOCKET_SESSION_KEY_FILE", str(key_file))
    monkeypatch.delenv("DOCKET_PAY_TO", raising=False)
    client = TestClient(create_app(tmp_path / "persistent.sqlite3"))

    body = _create(client, kind="persistent", policy=POLICY).json()

    assert body["state"] == "awaiting_session"
    assert body["next_action"]["kind"] == "wait"
    assert body["session"] is None
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
    past = (datetime.now(UTC) - timedelta(minutes=1)).isoformat()
    created = _create(
        client, kind="persistent", policy={**POLICY, "expires_at": past}
    ).json()

    response = _act(client, created, "pause")

    assert response.status_code == 409
    assert response.json()["error_code"] == "expired"
    read_back = client.get(f"/api/activations/{created['activation_id']}").json()
    # `revoking`, not `expired`: the web process cannot sweep, and the state that means
    # "your money is back" is only reachable from a reading that says it is.
    assert read_back["state"] == "revoking"
    assert read_back["next_action"]["detail"]["closing_to"] == "expired"


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


def test_the_signed_message_binds_the_evidence_the_call_carries(client, tmp_path):
    """A signature over "approve this activation" alone would authorise approving it
    against any transaction hash substituted into the body afterwards."""
    created = _create(client).json()
    unbound = _sign(
        OWNER,
        action_message(created["activation_id"], "approve", created["auth_nonce"]),
    )

    response = client.post(
        f"/api/activations/{created['activation_id']}/approve",
        json={
            "nonce": created["auth_nonce"],
            "owner_signature": unbound,
            "payment_id": "pay_substituted",
        },
    )

    # A readable signature over a different sentence recovers to a different address, so
    # it is reported as somebody else's signature rather than as an unreadable one.
    assert response.status_code == 403
    assert response.json()["error_code"] == "not_owner"


def test_a_signature_replayed_after_a_failed_call_is_still_stale(client):
    """The nonce is spent when it is presented, not when the work succeeds. Otherwise a
    call that failed would leave its signature live for a second attempt."""
    created = _create(client).json()
    assert _act(client, created, "pause").status_code == 409

    replayed = _act(client, created, "cancel")

    assert replayed.status_code == 409
    assert replayed.json()["error_code"] == "stale_nonce"
    assert (
        client.get(f"/api/activations/{created['activation_id']}").json()["auth_nonce"]
        != created["auth_nonce"]
    )


def test_an_owner_may_not_hold_more_open_activations_than_the_cap(client):
    for _ in range(5):
        assert _create(client).status_code == 201

    refused = _create(client)

    assert refused.status_code == 422
    assert refused.json()["error_code"] == "too_many_activations"

    # Finishing one frees the slot: the cap is on what is open, not on what was ever made.
    listed = client.get(f"/api/activations?owner={OWNER.address}").json()
    _act(client, listed["activations"][0], "cancel")
    assert _create(client).status_code == 201


def test_an_oversized_inputs_or_policy_is_refused_before_it_is_stored(client):
    response = _create(client, inputs={"wallet": OWNER.address, "pad": "x" * 20_000})

    assert response.status_code == 413
    assert response.json()["error_code"] == "invalid_json"

    padded = {**POLICY, "note": "y" * 9_000}
    assert _create(client, kind="persistent", policy=padded).status_code == 413


def test_a_policy_field_of_the_wrong_type_is_a_422_and_never_a_500(client):
    for policy in (
        {**POLICY, "contract_allowlist": "0xnot-a-list"},
        {**POLICY, "per_action_limit_atomic": []},
        {**POLICY, "max_slippage_bps": {"bad": 1}},
        {**POLICY, "expires_at": 1234},
        {**POLICY, "emergency_pause": "yes"},
        {**POLICY, "total_cap_atomic": {"0x1": "not-a-number"}},
    ):
        response = _create(client, kind="persistent", policy=policy)

        assert response.status_code == 422, policy
        assert response.json()["error_code"] == "policy_violation"


def test_nft_approvals_must_be_a_list_of_objects(client):
    for approvals in ("0xnope", [1, 2], [{"contract": "0x1"}]):
        response = _create(
            client, kind="persistent", policy=POLICY, nft_approvals=approvals
        )

        assert response.status_code in (409, 422), approvals
        assert response.json()["error_code"] == "policy_violation"


# -- policy defaults ----------------------------------------------------------


def test_policy_defaults_returns_a_skeleton_a_browser_can_send_back(client):
    """A browser cannot know which contracts a rebalancing session must call, so it asks
    rather than guessing or being refused for guessing wrong."""
    response = client.get("/api/activations/policy-defaults?service_id=range-doctor")

    body = response.json()
    assert response.status_code == 200
    assert body["category"] == "rebalancing"
    assert body["you_must_add"] == ["expires_at"]
    assert body["policy"]["contract_allowlist"]
    assert body["policy"]["function_allowlist"]
    assert body["policy"]["token_allowlist"]

    created = _create(
        client,
        kind="persistent",
        policy={**body["policy"], "expires_at": POLICY["expires_at"]},
    )

    assert created.status_code == 201


def test_policy_defaults_needs_a_service_it_declares_a_category_for(client):
    assert client.get("/api/activations/policy-defaults").status_code == 422
    assert (
        client.get(
            "/api/activations/policy-defaults?service_id=solvent-signal"
        ).status_code
        == 404
    )
    assert (
        client.get("/api/activations/policy-defaults?service_id=nope").status_code == 404
    )


def test_a_persistent_create_may_omit_the_allowlists_entirely(client):
    """The failure Lane C hit: a browser that cannot compose an allowlist was refused
    after its nonce had already been spent."""
    response = _create(
        client, kind="persistent", policy={"expires_at": POLICY["expires_at"]}
    )

    body = response.json()
    assert response.status_code == 201
    assert body["policy"]["policy_source"] == "docket_defaults"
    assert body["policy"]["contract_allowlist"]


def test_a_malformed_policy_does_not_cost_the_caller_its_signature(client):
    """Validated before the nonce is spent, so the same nonce is still good for the
    corrected request and the owner does not have to sign twice for one mistake."""
    nonce = client.get(
        f"/api/activations/nonce?owner={OWNER.address}&service_id=range-doctor"
    ).json()
    body = {
        "service_id": "range-doctor",
        "kind": "persistent",
        "owner": OWNER.address,
        "nonce": nonce["nonce"],
        "owner_signature": _sign(OWNER, nonce["message"]),
        "inputs": {"wallet": OWNER.address},
        "policy": {"expires_at": POLICY["expires_at"], "max_slippage_bps": 99_999},
    }

    refused = client.post("/api/activations", json=body)
    assert refused.status_code == 422
    assert refused.json()["error_code"] == "policy_violation"

    body["policy"] = {"expires_at": POLICY["expires_at"]}
    assert client.post("/api/activations", json=body).status_code == 201


# -- bodies that used to reach a 500 ------------------------------------------


def test_an_nft_approvals_field_that_is_not_a_list_is_a_422_not_a_500(client):
    """`tuple(5)` is a TypeError, and a 500 for a body the caller could fix is the wrong
    answer to a typo. Refused before the nonce is spent, like every other body error."""
    for approvals in (5, True, {"contract": "0x1"}, "0xnope"):
        response = _create(
            client, kind="persistent", policy=POLICY, nft_approvals=approvals
        )

        assert response.status_code == 422, approvals
        assert response.json()["error_code"] == "policy_violation"
        assert set(response.json()) == {"error_code", "message"}


def test_a_non_string_tx_hash_or_payment_id_is_a_422_before_the_nonce_is_spent(client):
    created = _create(client).json()

    for field, value in (("tx_hash", 5), ("payment_id", {"id": 1}), ("tx_hash", True)):
        response = client.post(
            f"/api/activations/{created['activation_id']}/approve",
            json={
                "nonce": created["auth_nonce"],
                "owner_signature": "0x" + "00" * 65,
                field: value,
            },
        )

        assert response.status_code == 422, (field, value)
        assert response.json()["error_code"] == "missing_field"

    # The nonce was never spent, so the corrected call still works.
    assert _act(client, created, "cancel").status_code == 200


def test_a_body_carrying_both_tx_hash_and_payment_id_is_refused(client):
    """Only one of the two is bound into the signed message. The other would travel
    unsigned, and the unsigned one is the one a middle would edit."""
    created = _create(client).json()

    response = client.post(
        f"/api/activations/{created['activation_id']}/approve",
        json={
            "nonce": created["auth_nonce"],
            "owner_signature": _sign(
                OWNER,
                action_message(
                    created["activation_id"], "approve", created["auth_nonce"], "0xabc"
                ),
            ),
            "tx_hash": "0xabc",
            "payment_id": "pay_1",
        },
    )

    assert response.status_code == 422
    assert response.json()["error_code"] == "missing_field"
    assert "not both" in response.json()["message"]


def test_the_signed_message_is_exactly_what_the_documentation_says(client):
    """One string, single spaces, values verbatim. A message that differs by one
    character does not verify, so the rule is pinned here as well as documented."""
    created = _create(client).json()
    aid = created["activation_id"]
    nonce = created["auth_nonce"]

    assert action_message(aid, "approve", nonce) == (
        f"Docket activation {aid} approve {nonce}"
    )
    assert action_message(aid, "approve", nonce, "0xAbC") == (
        f"Docket activation {aid} approve {nonce} 0xAbC"
    )
    # Verbatim: a hash is not lowercased or checksummed before it is signed or checked.
    response = client.post(
        f"/api/activations/{aid}/approve",
        json={
            "nonce": nonce,
            "owner_signature": _sign(
                OWNER, action_message(aid, "approve", nonce, "0xabc")
            ),
            "tx_hash": "0xAbC",
        },
    )
    assert response.status_code == 403


def test_the_policy_defaults_carry_the_v3_swap_router_for_every_position_category(
    client,
):
    """Lane D2's migration route and Lane D1's thin-pair swaps both send it; a default
    that omitted it refused every route the executor drafts."""
    from docket.jobs.executors.allowlists import V3_SWAP_ROUTER
    from docket.sessions.spend import EXACT_INPUT_SINGLE

    for service_id in ("range-doctor", "yield-router"):
        body = client.get(
            f"/api/activations/policy-defaults?service_id={service_id}"
        ).json()

        assert V3_SWAP_ROUTER in body["policy"]["contract_allowlist"], service_id
        assert EXACT_INPUT_SINGLE in body["policy"]["function_allowlist"], service_id
        assert "0x0c49ccbe" in body["policy"]["function_allowlist"], service_id
        assert "0xfc6f7865" in body["policy"]["function_allowlist"], service_id
        assert "0x88316456" in body["policy"]["function_allowlist"], service_id


def test_the_health_factor_defaults_carry_the_venus_underlying_map(client):
    body = client.get(
        "/api/activations/policy-defaults?service_id=health-guard"
    ).json()

    assert body["category"] == "health_factor"
    assert body["token_hints"]["underlying"]
