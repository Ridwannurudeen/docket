import asyncio
import base64
import hashlib
import json
import sqlite3
import threading
import time
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from eth_account import Account
from eth_account.messages import encode_typed_data
from fastapi.testclient import TestClient

from docket.agents.pancake import doctor
from docket.api import create_app
from docket.api import routes
from docket.api.routes import FREE_TIER_HIRES
from docket.hire import catalogue
from docket.hire.catalogue import SERVICES, USDT_TOKEN, PaidStockAdmission, get_service
from docket.hire.x402 import (
    B402_NETWORK,
    B402_RELAYER,
    TRANSFER_WITH_AUTHORIZATION_TYPES,
    build_challenge,
)
from docket.store import Store

PAY_TO = "0x" + "11" * 20
WALLET = "0x451871A1753903FB8fdd64a6B838E95aB8D5B80f"


def _stub_report(address, **kwargs):
    """Stands in for `doctor.report`, including how it rejects an address it cannot read:
    web3 raises ValueError on a non-hex string, and the allowance depends on that shape."""
    if not address.startswith("0x"):
        raise ValueError(
            f"when sending a str, it must be a hex string. Got: {address!r}"
        )
    return {"address": address, "positions": [], "positions_held": 0}


@pytest.fixture(autouse=True)
def stub_the_work(monkeypatch):
    """No test here touches an RPC or waits 30 seconds for one. `_run_range_doctor` calls
    `doctor.report` through the module attribute, so replacing it covers every hire."""
    monkeypatch.setattr(doctor, "report", _stub_report)


class FixtureFacilitator:
    def __init__(self, *, settle_error=None, network="eip155:56"):
        self.calls = []
        self.settle_error = settle_error
        self.network = network

    def verify(self, envelope):
        self.calls.append(("verify", envelope))
        payer = envelope["paymentPayload"]["payload"]["authorization"]["from"]
        return {"isValid": True, "payer": payer}

    def settle(self, envelope):
        self.calls.append(("settle", envelope))
        if self.settle_error is not None:
            raise self.settle_error
        payer = envelope["paymentPayload"]["payload"]["authorization"]["from"]
        return {
            "success": True,
            "payer": payer,
            "transaction": "0xdry-run-transaction",
            "network": self.network,
        }


def _client(
    tmp_path,
    monkeypatch,
    *,
    name="free",
    pay_to=None,
    facilitator=None,
    facilitator_kind=None,
    admit_range=False,
    canary_token=None,
):
    db_path = tmp_path / f"{name}.sqlite3"
    if pay_to is None:
        monkeypatch.delenv("DOCKET_PAY_TO", raising=False)
    else:
        monkeypatch.setenv("DOCKET_PAY_TO", pay_to)
    if facilitator_kind is None:
        monkeypatch.delenv("DOCKET_FACILITATOR_KIND", raising=False)
    else:
        monkeypatch.setenv("DOCKET_FACILITATOR_KIND", facilitator_kind)
    if canary_token is None:
        monkeypatch.delenv("DOCKET_CANARY_TOKEN_FILE", raising=False)
    else:
        token_file = tmp_path / f"{name}.token"
        token_file.write_text(canary_token, encoding="ascii")
        monkeypatch.setenv("DOCKET_CANARY_TOKEN_FILE", str(token_file))
    if admit_range:
        monkeypatch.setitem(
            SERVICES,
            "range-doctor",
            replace(
                get_service("range-doctor"),
                admission=PaidStockAdmission(True, True, True, True),
            ),
        )
        store = Store(db_path)
        run_id = store.begin_canary_run("range-doctor", "http://testserver")
        store.finish_canary_run(
            run_id,
            verdict="passed",
            checks=[
                {
                    "leg": "complete_human_result",
                    "checked": "the complete paid hire chain",
                    "status": "passed",
                    "observed": {"settlement_amount": "0.50"},
                    "evidence": {"replay_status": 409},
                }
            ],
        )
    # No snapshot is ingested: hiring must not depend on one.
    return TestClient(create_app(db_path, facilitator=facilitator))


def _authorization(
    acct,
    *,
    to=PAY_TO,
    value=5 * 10**17,
    nonce="0x" + "03" * 32,
    resource="http://testserver/hire/range-doctor",
):
    challenge = build_challenge(get_service("range-doctor"), PAY_TO, resource=resource)
    domain = {
        "name": "B402",
        "version": "1",
        "chainId": 56,
        "verifyingContract": B402_RELAYER,
    }
    msg = {
        "token": USDT_TOKEN,
        "from": acct.address,
        "to": to,
        "value": str(value),
        "validAfter": 0,
        "validBefore": int(time.time()) + 300,
        "nonce": nonce,
    }
    sig = acct.sign_message(
        encode_typed_data(domain, TRANSFER_WITH_AUTHORIZATION_TYPES, msg)
    )
    payment = {
        "x402Version": 2,
        "resource": challenge["resource"],
        "accepted": challenge["accepts"][0],
        "payload": {"signature": sig.signature.hex(), "authorization": msg},
    }
    return base64.b64encode(json.dumps(payment).encode()).decode()


def _sha256_of_canonical_json(obj) -> str:
    blob = json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "0x" + hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _seed_payment_state(db_path, *, nonce, stale, status="settling"):
    assert status in {"verified", "output_ready", "settling"}
    store = Store(db_path)
    request = {"wallet": WALLET}
    result = {"address": WALLET, "assessment": "stored result"}
    payment_id = f"payment-{nonce}"
    reserved, _ = store.reserve_payment(
        nonce=nonce,
        payment_id=payment_id,
        service_id="range-doctor",
        payer="0x" + "22" * 20,
        recipient=PAY_TO,
        asset=USDT_TOKEN,
        amount=str(5 * 10**17),
        resource="http://testserver/hire/range-doctor",
        input_hash=_sha256_of_canonical_json(request),
    )
    assert reserved is True
    if status in {"output_ready", "settling"}:
        store.record_payment_output(
            payment_id,
            output_hash=_sha256_of_canonical_json(result),
            result=result,
        )
    if status == "settling":
        assert store.begin_payment_settlement(payment_id) is True
    age_seconds = routes.SETTLEMENT_RECONCILE_STALE_SECONDS + (60 if stale else -60)
    updated_at = datetime.now(timezone.utc) - timedelta(seconds=age_seconds)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "UPDATE hire_payments SET updated_at = ? WHERE nonce = ?",
            (updated_at.isoformat(), nonce),
        )
    return store, request, result


def test_the_catalogue_tells_a_stranger_what_to_send(tmp_path, monkeypatch):
    body = _client(tmp_path, monkeypatch).get("/hire").json()
    listed = {svc["id"]: svc for svc in body["services"]}
    assert "range-doctor" in listed
    svc = listed["range-doctor"]
    assert svc["what_you_get"] and svc["typical_seconds"] > 0
    assert svc["price_display"] == "0.50 USDT"
    assert svc["price_atomic"] == 5 * 10**17
    assert svc["asset"] == USDT_TOKEN
    assert svc["paid_stock"] is False
    assert svc["stock_status"] == "candidate"
    assert set(svc["admission"]) == {
        "fresh_paired_benchmark",
        "cold_canary",
        "decision_grade_presenter",
        "true_settlement",
    }
    assert svc["input_schema"]["wallet"]["required"] is True


def test_unknown_facilitator_kind_stops_startup(tmp_path, monkeypatch):
    monkeypatch.setenv("DOCKET_FACILITATOR_KIND", "unknown")

    with pytest.raises(RuntimeError, match="b402 or generic"):
        create_app(tmp_path / "bad-facilitator.sqlite3")


def test_a_hire_returns_a_receipt_the_caller_can_recompute(tmp_path, monkeypatch):
    """The receipt is only worth something if its holder can check it without Docket."""
    payload = {"wallet": WALLET, "limit": 3}
    body = (
        _client(tmp_path, monkeypatch).post("/hire/range-doctor", json=payload).json()
    )

    receipt = body["receipt"]
    assert receipt["service"] == "range-doctor"
    assert receipt["input_hash"] == _sha256_of_canonical_json(payload)
    assert receipt["output_hash"] == _sha256_of_canonical_json(body["result"])
    assert receipt["payment"]["status"] == "free_tier"
    assert body["result"]["address"] == WALLET
    assert body["result"]["measured_value"]["this_run_seconds"] >= 0
    assert body["result"]["measured_value"]["paired_manual_seconds"] is None
    assert (
        body["result"]["measured_value"]["benchmark_unavailable_reason"]
        == "The v3 paired family v3-05-range-doctor has locked inputs but has not run."
    )


def test_declared_range_economics_require_one_exact_position(tmp_path, monkeypatch):
    """One wallet-level value must never be copied onto however many NFTs are returned."""
    resp = _client(tmp_path, monkeypatch).post(
        "/hire/range-doctor",
        json={"wallet": WALLET, "declared_position_value_usd": 10_000},
    )

    assert resp.status_code == 422
    error = resp.json()["error"]
    assert error["code"] == "invalid_field"
    assert "token_id" in error["message"]


def test_range_hire_passes_the_exact_frozen_pool_bytes_to_the_doctor(monkeypatch):
    captured = {}

    def record(address, **kwargs):
        captured["address"] = address
        captured.update(kwargs)
        return {"address": address, "positions": [], "positions_held": 0}

    monkeypatch.setattr(doctor, "report", record)
    pools_raw = b'[{"id":"0xpool"}]\n'
    tokens_raw = b'{"tokens":[]}\n'

    def snapshot(url, raw):
        return {
            "url": url,
            "observed_at": "2026-08-21T12:00:00Z",
            "attempt_ordinal": 1,
            "sha256": hashlib.sha256(raw).hexdigest(),
            "body_base64": base64.b64encode(raw).decode(),
        }

    SERVICES["range-doctor"].run(
        {
            "wallet": WALLET,
            "position_manager": "0x46A15B0b27311cedF172AB29E4f4766fbE7F4364",
            "token_id": 7,
            "observation_block": 123,
            "declared_position_value_usd": 10_000,
            "estimated_recenter_cost_usd": 25,
            "decision_horizon_days": 30,
            "source_refs": [{"kind": "pool_truth", "ref": "frozen.json"}],
            "pool_snapshot": snapshot(
                "https://explorer.pancakeswap.com/pools", pools_raw
            ),
            "token_list_snapshot": snapshot(
                "https://tokens.pancakeswap.finance/list", tokens_raw
            ),
        }
    )

    assert captured["pool_rows"] == [{"id": "0xpool"}]
    assert captured["token_allowlist"] == set()
    assert (
        captured["source_evidence"]["pools"]["sha256"]
        == hashlib.sha256(pools_raw).hexdigest()
    )
    assert captured["decision_horizon_days"] == 30


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


def test_the_allowance_applies_even_without_a_payment_route(tmp_path, monkeypatch):
    free = _client(tmp_path, monkeypatch, name="free-limited")
    for _ in range(FREE_TIER_HIRES):
        assert (
            free.post("/hire/range-doctor", json={"wallet": WALLET}).status_code == 200
        )

    exhausted = free.post("/hire/range-doctor", json={"wallet": WALLET})

    assert exhausted.status_code == 429
    assert exhausted.json()["error"]["code"] == "hire_rate_limited"


def test_a_free_request_at_the_cap_returns_429_with_a_payment_challenge(
    tmp_path, monkeypatch
):
    metered = _client(
        tmp_path,
        monkeypatch,
        name="metered",
        pay_to=PAY_TO,
        facilitator=FixtureFacilitator(),
        admit_range=True,
    )
    for _ in range(FREE_TIER_HIRES):
        assert (
            metered.post("/hire/range-doctor", json={"wallet": WALLET}).status_code
            == 200
        )

    resp = metered.post("/hire/range-doctor", json={"wallet": WALLET})
    assert resp.status_code == 429
    assert int(resp.headers["Retry-After"]) > 0
    body = resp.json()
    assert body["x402Version"] == 2
    assert body["accepts"][0]["payTo"] == PAY_TO
    assert body["error"]["code"] == "free_tier_exhausted"


def test_a_valid_payment_settles_at_the_free_cap_without_refunding_free_work(
    tmp_path, monkeypatch
):
    facilitator = FixtureFacilitator()
    metered = _client(
        tmp_path,
        monkeypatch,
        name="paid-at-free-cap",
        pay_to=PAY_TO,
        facilitator=facilitator,
        admit_range=True,
    )
    request = {"wallet": WALLET}
    for _ in range(FREE_TIER_HIRES):
        assert metered.post("/hire/range-doctor", json=request).status_code == 200

    paid = metered.post(
        "/hire/range-doctor",
        json=request,
        headers={"X-PAYMENT": _authorization(Account.create())},
    )
    free_after_payment = metered.post("/hire/range-doctor", json=request)

    assert paid.status_code == 200
    assert paid.json()["receipt"]["payment"]["status"] == "settled"
    assert [name for name, _ in facilitator.calls] == ["verify", "settle"]
    assert free_after_payment.status_code == 429
    assert int(free_after_payment.headers["Retry-After"]) > 0


def test_the_allowance_map_evicts_its_oldest_window_at_the_hard_cap(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(routes, "MAX_ALLOWANCE_CLIENTS", 2)
    monkeypatch.delenv("DOCKET_PAY_TO", raising=False)
    app = create_app(tmp_path / "bounded-allowances.sqlite3")
    first = TestClient(app, client=("198.51.100.1", 50000))
    second = TestClient(app, client=("198.51.100.2", 50000))
    third = TestClient(app, client=("198.51.100.3", 50000))

    for _ in range(FREE_TIER_HIRES):
        assert (
            first.post("/hire/range-doctor", json={"wallet": WALLET}).status_code == 200
        )
    assert first.post("/hire/range-doctor", json={"wallet": WALLET}).status_code == 429

    assert second.post("/hire/range-doctor", json={"wallet": WALLET}).status_code == 200
    assert third.post("/hire/range-doctor", json={"wallet": WALLET}).status_code == 200

    assert first.post("/hire/range-doctor", json={"wallet": WALLET}).status_code == 200


def test_expired_allowance_windows_are_evicted_on_the_next_hire(tmp_path, monkeypatch):
    clock = [100.0]
    monkeypatch.setattr(routes.time, "monotonic", lambda: clock[0])
    monkeypatch.delenv("DOCKET_PAY_TO", raising=False)
    app = create_app(tmp_path / "expired-allowances.sqlite3")
    first = TestClient(app, client=("198.51.100.1", 50000))
    second = TestClient(app, client=("198.51.100.2", 50000))
    third = TestClient(app, client=("198.51.100.3", 50000))
    assert first.post("/hire/range-doctor", json={"wallet": WALLET}).status_code == 200
    assert second.post("/hire/range-doctor", json={"wallet": WALLET}).status_code == 200
    assert set(app.state.hire_allowances) == {"198.51.100.1", "198.51.100.2"}

    clock[0] += routes.FREE_TIER_WINDOW_S + 1
    assert third.post("/hire/range-doctor", json={"wallet": WALLET}).status_code == 200

    assert list(app.state.hire_allowances) == ["198.51.100.3"]


def test_a_request_docket_could_not_read_never_spends_the_allowance(
    tmp_path, monkeypatch
):
    """The shared-egress case. One client fumbling its wallet field must not lock out the next
    caller behind the same address, and an allowance charged for work that never ran is the same
    class of overclaim as a settlement that never happened."""
    client = _client(tmp_path, monkeypatch, pay_to=PAY_TO)
    for _ in range(FREE_TIER_HIRES * 2):
        unreadable = [
            client.post("/hire/range-doctor", json={"wallet": "not-an-address"}),
            client.post("/hire/range-doctor", json={"limit": 1}),
            client.post("/hire/nope", json={"wallet": WALLET}),
            client.post(
                "/hire/range-doctor",
                content=b"not json",
                headers={"content-type": "application/json"},
            ),
        ]
        assert [r.status_code for r in unreadable] == [422, 422, 404, 400]

    served = client.post("/hire/range-doctor", json={"wallet": WALLET})
    assert served.status_code == 200
    assert served.json()["receipt"]["payment"]["status"] == "free_tier"


def test_hire_rejects_a_browser_safelisted_content_type_before_work(
    tmp_path, monkeypatch
):
    work_calls = []
    monkeypatch.setitem(
        SERVICES,
        "range-doctor",
        replace(
            get_service("range-doctor"),
            run=lambda payload: work_calls.append(payload) or {"decision": "ran"},
        ),
    )
    app = create_app(tmp_path / "hire-media-type.sqlite3")

    response = TestClient(app).post(
        "/hire/range-doctor",
        content=json.dumps({"wallet": WALLET}),
        headers={
            "content-type": "text/plain",
            "origin": "https://attacker.invalid",
        },
    )

    assert response.status_code == 415
    assert response.json()["error"]["code"] == "unsupported_media_type"
    assert app.state.hire_allowances == {}
    assert work_calls == []


@pytest.mark.parametrize(
    "headers",
    (
        [],
        [
            ("content-type", "application/json"),
            ("content-type", "text/plain"),
        ],
    ),
)
def test_hire_requires_exactly_one_json_content_type(tmp_path, monkeypatch, headers):
    app = create_app(tmp_path / f"hire-content-types-{len(headers)}.sqlite3")

    response = TestClient(app).post(
        "/hire/range-doctor",
        content=json.dumps({"wallet": WALLET}),
        headers=headers,
    )

    assert response.status_code == 415
    assert response.json()["error"]["code"] == "unsupported_media_type"
    assert app.state.hire_allowances == {}


def test_cors_preflight_does_not_advertise_json_post_mutations(tmp_path, monkeypatch):
    client = TestClient(create_app(tmp_path / "cors-preflight.sqlite3"))

    response = client.options(
        "/hire/range-doctor",
        headers={
            "origin": "https://attacker.invalid",
            "access-control-request-method": "POST",
            "access-control-request-headers": "content-type",
        },
    )

    assert response.status_code == 400
    assert "POST" not in response.headers["access-control-allow-methods"]


def test_recovery_rejects_a_browser_safelisted_content_type_before_allowance(
    tmp_path, monkeypatch
):
    app = create_app(tmp_path / "recovery-media-type.sqlite3")

    response = TestClient(app).post(
        "/hire/range-doctor/recover",
        content="{}",
        headers={"content-type": "text/plain"},
    )

    assert response.status_code == 415
    assert response.json()["error"]["code"] == "unsupported_media_type"
    assert app.state.recovery_allowances == {}


def test_reconciliation_rejects_a_browser_safelisted_content_type_before_auth(
    tmp_path, monkeypatch
):
    app = create_app(tmp_path / "reconcile-media-type.sqlite3")

    response = TestClient(app).post(
        "/hire/range-doctor/reconcile",
        content="{}",
        headers={"content-type": "application/x-www-form-urlencoded"},
    )

    assert response.status_code == 415
    assert response.json()["error"]["code"] == "unsupported_media_type"


def test_hire_accepts_application_json_with_a_charset(tmp_path, monkeypatch):
    app = create_app(tmp_path / "hire-json-charset.sqlite3")

    response = TestClient(app).post(
        "/hire/range-doctor",
        content=json.dumps({"wallet": WALLET}),
        headers={"content-type": "application/json; charset=utf-8"},
    )

    assert response.status_code == 200


@pytest.mark.parametrize(
    "body",
    [
        b'{"wallet":"' + WALLET.encode() + b'","unexpected":NaN}',
        b'{"wallet":' + b"[" * 10_000 + b"0" + b"]" * 10_000 + b"}",
        b'{"wallet":"\\ud800"}',
    ],
)
def test_non_canonical_or_excessively_nested_json_is_a_client_error(
    tmp_path, monkeypatch, body
):
    app = create_app(tmp_path / f"invalid-json-{len(body)}.sqlite3")

    response = TestClient(app, raise_server_exceptions=False).post(
        "/hire/range-doctor",
        content=body,
        headers={"content-type": "application/json"},
    )

    assert len(body) <= routes.MAX_HIRE_REQUEST_BODY_BYTES
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_json"
    assert app.state.hire_allowances == {}


def test_a_declared_oversized_hire_body_is_rejected_before_allowance_or_work(
    tmp_path, monkeypatch
):
    work_calls = []
    monkeypatch.setitem(
        SERVICES,
        "range-doctor",
        replace(
            get_service("range-doctor"),
            run=lambda payload: work_calls.append(payload) or {"decision": "ran"},
        ),
    )
    app = create_app(tmp_path / "declared-body-limit.sqlite3")
    body = (
        b'{"wallet":"'
        + WALLET.encode()
        + b'","padding":"'
        + b"x" * routes.MAX_HIRE_REQUEST_BODY_BYTES
        + b'"}'
    )

    response = TestClient(app).post(
        "/hire/range-doctor",
        content=body,
        headers={"content-type": "application/json"},
    )

    assert response.status_code == 413
    assert response.json() == {
        "error": {
            "code": "request_body_too_large",
            "message": (
                f"JSON request bodies must not exceed "
                f"{routes.MAX_HIRE_REQUEST_BODY_BYTES} bytes."
            ),
        }
    }
    assert app.state.hire_allowances == {}
    assert work_calls == []


def test_a_chunked_oversized_hire_body_is_counted_without_content_length(
    tmp_path, monkeypatch
):
    work_calls = []
    monkeypatch.setitem(
        SERVICES,
        "range-doctor",
        replace(
            get_service("range-doctor"),
            run=lambda payload: work_calls.append(payload) or {"decision": "ran"},
        ),
    )
    app = create_app(tmp_path / "chunked-body-limit.sqlite3")
    body = (
        b'{"wallet":"'
        + WALLET.encode()
        + b'","padding":"'
        + b"x" * routes.MAX_HIRE_REQUEST_BODY_BYTES
        + b'"}'
    )
    chunks = (body[offset : offset + 65_536] for offset in range(0, len(body), 65_536))

    response = TestClient(app).post(
        "/hire/range-doctor",
        content=chunks,
        headers={"content-type": "application/json"},
    )

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "request_body_too_large"
    assert app.state.hire_allowances == {}
    assert work_calls == []


def test_actual_hire_body_size_wins_over_an_underreported_content_length(
    tmp_path, monkeypatch
):
    work_calls = []
    monkeypatch.setitem(
        SERVICES,
        "range-doctor",
        replace(
            get_service("range-doctor"),
            run=lambda payload: work_calls.append(payload) or {"decision": "ran"},
        ),
    )
    app = create_app(tmp_path / "underreported-body-limit.sqlite3")
    body = (
        b'{"wallet":"'
        + WALLET.encode()
        + b'","padding":"'
        + b"x" * routes.MAX_HIRE_REQUEST_BODY_BYTES
        + b'"}'
    )

    response = TestClient(app).post(
        "/hire/range-doctor",
        content=body,
        headers={
            "content-length": "1",
            "content-type": "application/json",
        },
    )

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "request_body_too_large"
    assert app.state.hire_allowances == {}
    assert work_calls == []


def test_a_chunked_hire_body_at_the_exact_limit_is_accepted(tmp_path, monkeypatch):
    app = create_app(tmp_path / "exact-body-limit.sqlite3")
    prefix = b'{"wallet":"' + WALLET.encode() + b'","padding":"'
    suffix = b'"}'
    body = (
        prefix
        + b"x" * (routes.MAX_HIRE_REQUEST_BODY_BYTES - len(prefix) - len(suffix))
        + suffix
    )
    chunks = (body[offset : offset + 65_536] for offset in range(0, len(body), 65_536))

    response = TestClient(app).post(
        "/hire/range-doctor",
        content=chunks,
        headers={"content-type": "application/json"},
    )

    assert len(body) == routes.MAX_HIRE_REQUEST_BODY_BYTES
    assert response.status_code == 200


def test_an_invalid_content_length_is_a_structured_client_error(tmp_path, monkeypatch):
    app = create_app(tmp_path / "invalid-content-length.sqlite3")

    response = TestClient(app).post(
        "/hire/range-doctor",
        content=b'{"wallet":"' + WALLET.encode() + b'"}',
        headers={
            "content-length": "not-a-decimal-length",
            "content-type": "application/json",
        },
    )

    assert response.status_code == 400
    assert response.json() == {
        "error": {
            "code": "invalid_content_length",
            "message": "Content-Length must be one non-negative decimal byte count.",
        }
    }
    assert app.state.hire_allowances == {}


def test_a_slow_hire_does_not_delay_concurrent_health(tmp_path, monkeypatch):
    observed = {}
    started = threading.Event()

    def slow_work(_payload):
        observed["started_at"] = time.monotonic()
        started.set()
        time.sleep(0.8)
        return {"decision": "slow fixture completed"}

    monkeypatch.setitem(
        SERVICES,
        "range-doctor",
        replace(get_service("range-doctor"), run=slow_work),
    )
    monkeypatch.delenv("DOCKET_PAY_TO", raising=False)
    app = create_app(tmp_path / "concurrent-health.sqlite3")

    async def exercise():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as client:
            hire = asyncio.create_task(
                client.post("/hire/range-doctor", json={"wallet": WALLET})
            )
            assert await asyncio.to_thread(started.wait, 1)
            health = await client.get("/health")
            health_completed_after = time.monotonic() - observed["started_at"]
            return await hire, health, health_completed_after

    hire, health, health_completed_after = asyncio.run(exercise())

    assert health.status_code == 200
    assert health_completed_after < 0.5
    assert hire.status_code == 200


def test_a_paid_preflight_settles_once_and_rejects_the_exact_replay(
    tmp_path, monkeypatch
):
    """The lifecycle crosses local verification, facilitator verification, work, durable
    output binding and settlement. Replaying the same authorization is rejected and never
    repeats either work or settlement."""
    work_calls = []

    def counted_report(address, **kwargs):
        work_calls.append(address)
        return _stub_report(address, **kwargs)

    monkeypatch.setattr(doctor, "report", counted_report)
    facilitator = FixtureFacilitator()
    client = _client(
        tmp_path,
        monkeypatch,
        name="settled",
        pay_to=PAY_TO,
        facilitator=facilitator,
        admit_range=True,
    )
    header = _authorization(Account.create())
    request = {"wallet": WALLET}

    first = client.post(
        "/hire/range-doctor", json=request, headers={"X-PAYMENT": header}
    )
    replay = client.post(
        "/hire/range-doctor", json=request, headers={"X-PAYMENT": header}
    )

    assert first.status_code == 200
    assert replay.status_code == 409
    assert replay.json()["error"]["code"] == "authorization_replay"
    receipt = first.json()["receipt"]
    payment = receipt["payment"]
    assert payment["status"] == "settled"
    assert payment["amount"] == str(5 * 10**17)
    assert payment["asset"] == USDT_TOKEN
    assert payment["nonce"] == "0x" + "03" * 32
    assert payment["payment_id"].startswith("0x")
    assert payment["transaction_id"] == "0xdry-run-transaction"
    assert receipt["input_hash"] == _sha256_of_canonical_json(request)
    assert receipt["output_hash"] == _sha256_of_canonical_json(first.json()["result"])
    assert [name for name, _ in facilitator.calls] == ["verify", "settle"]
    assert work_calls == [WALLET]


def test_a_paid_hire_settles_when_the_benchmark_report_fails(tmp_path, monkeypatch):
    facilitator = FixtureFacilitator()
    exception_message = (
        r"cannot read C:\opt\docket\docket\advantage\v3\runs\04-warden.jsonl"
    )
    client = _client(
        tmp_path,
        monkeypatch,
        name="report-failure",
        pay_to=PAY_TO,
        facilitator=facilitator,
        admit_range=True,
    )

    def fail_report():
        raise PermissionError(exception_message)

    monkeypatch.setattr(catalogue.report_snapshot, "get_report", fail_report)
    response = client.post(
        "/hire/range-doctor",
        json={"wallet": WALLET},
        headers={"X-PAYMENT": _authorization(Account.create(), nonce="0x" + "13" * 32)},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["result"]["address"] == WALLET
    assert body["result"]["measured_value"] | {"this_run_seconds": None} == {
        "this_run_seconds": None,
        "paired_manual_seconds": None,
        "quality_result": None,
        "report_url": None,
        "benchmark_state": None,
        "benchmark_unavailable_reason": (
            "The v3 benchmark report failed while resolving measured value "
            "(PermissionError)."
        ),
    }
    assert exception_message not in response.text
    assert body["receipt"]["payment"]["status"] == "settled"
    assert [name for name, _ in facilitator.calls] == ["verify", "settle"]


def test_a_facilitator_exception_never_leaks_public_details(tmp_path, monkeypatch):
    private_detail = r"credential leaked from C:\opt\facilitator\private.json"

    class FailingFacilitator(FixtureFacilitator):
        def verify(self, envelope):
            self.calls.append(("verify", envelope))
            raise PermissionError(private_detail)

    facilitator = FailingFacilitator()
    client = _client(
        tmp_path,
        monkeypatch,
        name="facilitator-exception",
        pay_to=PAY_TO,
        facilitator=facilitator,
        admit_range=True,
    )

    response = client.post(
        "/hire/range-doctor",
        json={"wallet": WALLET},
        headers={"X-PAYMENT": _authorization(Account.create(), nonce="0x" + "14" * 32)},
    )

    assert response.status_code == 502
    assert response.json() == {
        "error": {
            "code": "payment_verification_unavailable",
            "message": (
                "The configured facilitator could not verify the payment just now. "
                "No work ran and no charge was attempted."
            ),
        }
    }
    assert private_detail not in response.text
    assert "PermissionError" not in response.text
    assert [name for name, _ in facilitator.calls] == ["verify"]


def test_a_paid_service_exception_never_leaks_public_details(tmp_path, monkeypatch):
    private_detail = "upstream token=internal-only failed at /opt/docket/private"

    def fail(_payload):
        raise RuntimeError(private_detail)

    monkeypatch.setitem(
        SERVICES,
        "range-doctor",
        replace(get_service("range-doctor"), run=fail),
    )
    facilitator = FixtureFacilitator()
    client = _client(
        tmp_path,
        monkeypatch,
        name="paid-service-exception",
        pay_to=PAY_TO,
        facilitator=facilitator,
        admit_range=True,
    )

    response = client.post(
        "/hire/range-doctor",
        json={"wallet": WALLET},
        headers={"X-PAYMENT": _authorization(Account.create(), nonce="0x" + "15" * 32)},
    )

    assert response.status_code == 502
    assert response.json() == {
        "error": {
            "code": "service_failed",
            "message": "range-doctor could not complete this request. No settlement ran.",
        }
    }
    assert private_detail not in response.text
    assert "RuntimeError" not in response.text
    assert [name for name, _ in facilitator.calls] == ["verify"]


def test_a_paid_non_finite_result_never_settles_or_becomes_undeliverable(
    tmp_path, monkeypatch
):
    monkeypatch.setitem(
        SERVICES,
        "range-doctor",
        replace(
            get_service("range-doctor"),
            run=lambda _payload: {"decision": "complete", "score": float("nan")},
        ),
    )
    facilitator = FixtureFacilitator()
    nonce = "0x" + "28" * 32
    configured = _client(
        tmp_path,
        monkeypatch,
        name="paid-non-finite-result",
        pay_to=PAY_TO,
        facilitator=facilitator,
        admit_range=True,
    )
    client = TestClient(configured.app, raise_server_exceptions=False)

    response = client.post(
        "/hire/range-doctor",
        json={"wallet": WALLET},
        headers={"X-PAYMENT": _authorization(Account.create(), nonce=nonce)},
    )

    assert response.status_code == 502
    assert response.json()["error"] == {
        "code": "service_failed",
        "message": "range-doctor could not complete this request. No settlement ran.",
    }
    assert [name for name, _ in facilitator.calls] == ["verify"]
    payment = Store(tmp_path / "paid-non-finite-result.sqlite3").payment_by_nonce(nonce)
    assert payment["status"] == "failed_no_charge"
    assert payment["result_json"] is None
    assert payment["receipt_json"] is None


def test_a_free_non_finite_result_is_rejected_before_receipt_delivery(
    tmp_path, monkeypatch
):
    monkeypatch.setitem(
        SERVICES,
        "range-doctor",
        replace(
            get_service("range-doctor"),
            run=lambda _payload: {"decision": "complete", "score": float("inf")},
        ),
    )
    configured = _client(tmp_path, monkeypatch, name="free-non-finite-result")
    client = TestClient(configured.app, raise_server_exceptions=False)

    response = client.post("/hire/range-doctor", json={"wallet": WALLET})

    assert response.status_code == 502
    assert response.json()["error"] == {
        "code": "service_failed",
        "message": "range-doctor could not complete this request. Retry.",
    }


def test_a_free_service_exception_never_leaks_public_details(tmp_path, monkeypatch):
    private_detail = "rpc bearer internal-only failed at /opt/docket/private"

    def fail(_payload):
        raise RuntimeError(private_detail)

    monkeypatch.setitem(
        SERVICES,
        "range-doctor",
        replace(get_service("range-doctor"), run=fail),
    )
    response = _client(tmp_path, monkeypatch, name="free-service-exception").post(
        "/hire/range-doctor", json={"wallet": WALLET}
    )

    assert response.status_code == 502
    assert response.json() == {
        "error": {
            "code": "service_failed",
            "message": "range-doctor could not complete this request. Retry.",
        }
    }
    assert private_detail not in response.text
    assert "RuntimeError" not in response.text


def test_b402_configuration_maps_the_payment_and_accepts_its_network(
    tmp_path, monkeypatch
):
    facilitator = FixtureFacilitator(network=B402_NETWORK)
    client = _client(
        tmp_path,
        monkeypatch,
        name="b402-settled",
        pay_to=PAY_TO,
        facilitator=facilitator,
        facilitator_kind="b402",
        admit_range=True,
    )

    response = client.post(
        "/hire/range-doctor",
        json={"wallet": WALLET},
        headers={"X-PAYMENT": _authorization(Account.create())},
    )

    assert response.status_code == 200
    assert response.json()["receipt"]["payment"]["network"] == B402_NETWORK
    envelope = facilitator.calls[0][1]
    assert envelope["paymentRequirements"] == {
        "network": B402_NETWORK,
        "relayerContract": B402_RELAYER,
    }
    assert envelope["paymentPayload"]["token"] == USDT_TOKEN
    assert "x402Version" not in envelope


def test_a_malformed_paid_attempt_is_not_silently_served_as_a_preview(
    tmp_path, monkeypatch
):
    """A caller that supplied payment intended the paid path. Invalid payment bytes must
    fail before work instead of being silently reclassified as an unsigned preview."""
    work_calls = []

    def counted_report(address, **kwargs):
        work_calls.append(address)
        return _stub_report(address, **kwargs)

    monkeypatch.setattr(doctor, "report", counted_report)
    facilitator = FixtureFacilitator()
    client = _client(
        tmp_path,
        monkeypatch,
        name="malformed-payment",
        pay_to=PAY_TO,
        facilitator=facilitator,
        admit_range=True,
    )

    response = client.post(
        "/hire/range-doctor",
        json={"wallet": WALLET},
        headers={"X-PAYMENT": "not-base64-json"},
    )

    assert response.status_code == 402
    assert response.json()["error"]["code"] == "payment_invalid"
    assert facilitator.calls == []
    assert work_calls == []


def test_a_settled_replay_survives_an_app_restart(tmp_path, monkeypatch):
    """Exactly-once is a database property, not an in-memory promise: a new app instance
    rejects the spent authorization and never asks the facilitator to settle again."""
    facilitator = FixtureFacilitator()
    header = _authorization(Account.create(), nonce="0x" + "04" * 32)
    first_client = _client(
        tmp_path,
        monkeypatch,
        name="restart",
        pay_to=PAY_TO,
        facilitator=facilitator,
        admit_range=True,
    )
    first = first_client.post(
        "/hire/range-doctor", json={"wallet": WALLET}, headers={"X-PAYMENT": header}
    )
    first_client.close()

    second_client = _client(
        tmp_path,
        monkeypatch,
        name="restart",
        pay_to=PAY_TO,
        facilitator=facilitator,
        admit_range=True,
    )
    replay = second_client.post(
        "/hire/range-doctor", json={"wallet": WALLET}, headers={"X-PAYMENT": header}
    )

    assert first.status_code == 200
    assert replay.status_code == 409
    assert replay.json()["error"]["code"] == "authorization_replay"
    assert [name for name, _ in facilitator.calls] == ["verify", "settle"]


def test_a_nonce_cannot_be_rebound_to_another_input(tmp_path, monkeypatch):
    """The nonce is the replay boundary. Once payment is bound to one input, presenting
    that authorization for different work is rejected before the service runs."""
    facilitator = FixtureFacilitator()
    client = _client(
        tmp_path,
        monkeypatch,
        name="rebind",
        pay_to=PAY_TO,
        facilitator=facilitator,
        admit_range=True,
    )
    header = _authorization(Account.create(), nonce="0x" + "05" * 32)
    assert (
        client.post(
            "/hire/range-doctor",
            json={"wallet": WALLET},
            headers={"X-PAYMENT": header},
        ).status_code
        == 200
    )

    rebound = client.post(
        "/hire/range-doctor",
        json={"wallet": WALLET, "limit": 1},
        headers={"X-PAYMENT": header},
    )
    assert rebound.status_code == 409
    assert rebound.json()["error"]["code"] == "authorization_replay"
    assert [name for name, _ in facilitator.calls] == ["verify", "settle"]


def test_an_empty_result_is_never_settled(tmp_path, monkeypatch):
    """Facilitator verification is not value delivery. Empty raw JSON fails the human-
    readable result gate, records a no-charge terminal state and never calls `/settle`."""
    facilitator = FixtureFacilitator()
    monkeypatch.setitem(
        SERVICES,
        "range-doctor",
        replace(
            get_service("range-doctor"),
            admission=PaidStockAdmission(True, True, True, True),
            run=lambda _payload: {},
        ),
    )
    client = _client(
        tmp_path,
        monkeypatch,
        name="empty",
        pay_to=PAY_TO,
        facilitator=facilitator,
        admit_range=True,
    )
    header = _authorization(Account.create(), nonce="0x" + "06" * 32)

    empty = client.post(
        "/hire/range-doctor",
        json={"wallet": WALLET},
        headers={"X-PAYMENT": header},
    )
    replay = client.post(
        "/hire/range-doctor",
        json={"wallet": WALLET},
        headers={"X-PAYMENT": header},
    )
    recovery = client.post(
        "/hire/range-doctor/recover",
        json={"wallet": WALLET},
        headers={"X-PAYMENT": header},
    )

    assert empty.status_code == 502
    assert empty.json()["error"]["code"] == "empty_result"
    assert replay.status_code == 409
    assert replay.json()["error"]["code"] == "authorization_spent"
    assert recovery.status_code == 409
    assert recovery.json()["error"]["code"] == "payment_not_recoverable"
    assert [name for name, _ in facilitator.calls] == ["verify"]


def test_an_unknown_settlement_outcome_is_never_retried_automatically(
    tmp_path, monkeypatch
):
    """A transport failure after `/settle` may hide a successful transfer. The durable
    `settlement_unknown` state refuses replay rather than risking a second settlement."""
    facilitator = FixtureFacilitator(
        settle_error=httpx.ReadTimeout("fixture lost the settle response")
    )
    client = _client(
        tmp_path,
        monkeypatch,
        name="unknown",
        pay_to=PAY_TO,
        facilitator=facilitator,
        admit_range=True,
    )
    header = _authorization(Account.create(), nonce="0x" + "07" * 32)

    first = client.post(
        "/hire/range-doctor",
        json={"wallet": WALLET},
        headers={"X-PAYMENT": header},
    )
    replay = client.post(
        "/hire/range-doctor",
        json={"wallet": WALLET},
        headers={"X-PAYMENT": header},
    )

    assert first.status_code == 502
    assert first.json()["error"]["code"] == "settlement_unknown"
    assert replay.status_code == 409
    assert [name for name, _ in facilitator.calls] == ["verify", "settle"]


def test_a_settled_result_can_be_recovered_without_repeating_work_or_settlement(
    tmp_path, monkeypatch
):
    work_calls = []

    def counted_report(address, **kwargs):
        work_calls.append(address)
        return _stub_report(address, **kwargs)

    monkeypatch.setattr(doctor, "report", counted_report)
    facilitator = FixtureFacilitator()
    client = _client(
        tmp_path,
        monkeypatch,
        name="recover-settled",
        pay_to=PAY_TO,
        facilitator=facilitator,
        admit_range=True,
    )
    request = {"wallet": WALLET}
    header = _authorization(Account.create(), nonce="0x" + "09" * 32)
    first = client.post(
        "/hire/range-doctor", json=request, headers={"X-PAYMENT": header}
    )

    recovered = client.post(
        "/hire/range-doctor/recover",
        json=request,
        headers={"X-PAYMENT": header},
    )

    assert recovered.status_code == 200
    assert recovered.json() == first.json()
    assert work_calls == [WALLET]
    assert [name for name, _ in facilitator.calls] == ["verify", "settle"]


@pytest.mark.parametrize(
    "tampered_field",
    (
        "service",
        "input_hash",
        "output_hash",
        "payment_payer",
        "payment_status",
        "transaction_id",
        "stored_transaction_id",
        "non_finite_result",
        "non_utf8_result",
    ),
)
def test_payment_recovery_refuses_a_receipt_not_bound_to_the_stored_row(
    tmp_path, monkeypatch, tampered_field
):
    token = "operator-recovery-token"
    suffix = {
        "service": "21",
        "input_hash": "22",
        "output_hash": "23",
        "payment_payer": "24",
        "payment_status": "25",
        "transaction_id": "26",
        "stored_transaction_id": "27",
        "non_finite_result": "29",
        "non_utf8_result": "30",
    }[tampered_field]
    nonce = "0x" + suffix * 32
    name = f"tampered-receipt-{tampered_field}"
    db_path = tmp_path / f"{name}.sqlite3"
    facilitator = FixtureFacilitator()
    client = _client(
        tmp_path,
        monkeypatch,
        name=name,
        pay_to=PAY_TO,
        facilitator=facilitator,
        admit_range=True,
        canary_token=token,
    )
    first = client.post(
        "/hire/range-doctor",
        json={"wallet": WALLET},
        headers={"X-PAYMENT": _authorization(Account.create(), nonce=nonce)},
    )
    assert first.status_code == 200
    receipt = first.json()["receipt"]
    if tampered_field == "stored_transaction_id":
        with sqlite3.connect(db_path) as conn:
            conn.execute(
                "UPDATE hire_payments SET transaction_id = NULL WHERE nonce = ?",
                (nonce,),
            )
    elif tampered_field in {"non_finite_result", "non_utf8_result"}:
        result_json = (
            '{"decision":"done","score":NaN}'
            if tampered_field == "non_finite_result"
            else '{"decision":"\\ud800"}'
        )
        with sqlite3.connect(db_path) as conn:
            conn.execute(
                "UPDATE hire_payments SET result_json = ? WHERE nonce = ?",
                (result_json, nonce),
            )
    elif tampered_field.startswith("payment_"):
        receipt["payment"][tampered_field.removeprefix("payment_")] = "tampered"
    elif tampered_field == "transaction_id":
        receipt["payment"]["transaction_id"] = "0xtampered"
    else:
        receipt[tampered_field] = "tampered"
    if tampered_field not in {
        "stored_transaction_id",
        "non_finite_result",
        "non_utf8_result",
    }:
        with sqlite3.connect(db_path) as conn:
            conn.execute(
                "UPDATE hire_payments SET receipt_json = ? WHERE nonce = ?",
                (json.dumps(receipt), nonce),
            )

    recovered = client.post(
        "/hire/range-doctor/recover",
        json={"nonce": nonce},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert recovered.status_code == 500
    assert recovered.json()["error"] == {
        "code": "payment_record_incomplete",
        "message": (
            "The stored payment result is incomplete and cannot be delivered."
            if tampered_field in {"non_finite_result", "non_utf8_result"}
            else "The stored payment receipt is incomplete and cannot be delivered."
        ),
    }
    assert Store(db_path).payment_by_nonce(nonce)["operator_recovered_at"] is None


def test_operator_recovery_uses_the_canary_bearer_and_records_the_access(
    tmp_path, monkeypatch
):
    facilitator = FixtureFacilitator()
    token = "operator-recovery-token"
    nonce = "0x" + "0e" * 32
    client = _client(
        tmp_path,
        monkeypatch,
        name="operator-recovery",
        pay_to=PAY_TO,
        facilitator=facilitator,
        admit_range=True,
        canary_token=token,
    )
    request = {"wallet": WALLET}
    header = _authorization(Account.create(), nonce=nonce)
    first = client.post(
        "/hire/range-doctor", json=request, headers={"X-PAYMENT": header}
    )

    def fail_if_called(*args, **kwargs):
        raise AssertionError("operator recovery re-verified the buyer signature")

    monkeypatch.setattr(routes, "verify_payment", fail_if_called)

    recovered = client.post(
        "/hire/range-doctor/recover",
        json={"nonce": nonce},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert recovered.status_code == 200
    assert recovered.json() == first.json()
    stored = Store(tmp_path / "operator-recovery.sqlite3").payment_by_nonce(nonce)
    assert stored["operator_recovered_at"] is not None
    assert [name for name, _ in facilitator.calls] == ["verify", "settle"]


def test_operator_recovery_rejects_the_wrong_bearer(tmp_path, monkeypatch):
    facilitator = FixtureFacilitator()
    token = "operator-recovery-token"
    nonce = "0x" + "0f" * 32
    client = _client(
        tmp_path,
        monkeypatch,
        name="operator-recovery-wrong-token",
        pay_to=PAY_TO,
        facilitator=facilitator,
        admit_range=True,
        canary_token=token,
    )
    assert (
        client.post(
            "/hire/range-doctor",
            json={"wallet": WALLET},
            headers={"X-PAYMENT": _authorization(Account.create(), nonce=nonce)},
        ).status_code
        == 200
    )

    response = client.post(
        "/hire/range-doctor/recover",
        json={"nonce": nonce},
        headers={"Authorization": "Bearer wrong-token"},
    )

    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"
    assert response.json()["error"]["code"] == "operator_unauthorized"
    stored = Store(tmp_path / "operator-recovery-wrong-token.sqlite3").payment_by_nonce(
        nonce
    )
    assert stored["operator_recovered_at"] is None


def test_buyer_recovery_without_an_operator_token_keeps_the_signed_window(
    tmp_path, monkeypatch
):
    facilitator = FixtureFacilitator()
    nonce = "0x" + "10" * 32
    client = _client(
        tmp_path,
        monkeypatch,
        name="expired-buyer-recovery",
        pay_to=PAY_TO,
        facilitator=facilitator,
        admit_range=True,
    )
    request = {"wallet": WALLET}
    header = _authorization(Account.create(), nonce=nonce)
    assert (
        client.post(
            "/hire/range-doctor", json=request, headers={"X-PAYMENT": header}
        ).status_code
        == 200
    )
    payment = json.loads(base64.b64decode(header))
    expired_at = int(payment["payload"]["authorization"]["validBefore"])
    original_verify = routes.verify_payment

    def verify_after_expiry(payment_payload, **kwargs):
        return original_verify(payment_payload, now=expired_at + 1, **kwargs)

    monkeypatch.setattr(routes, "verify_payment", verify_after_expiry)

    response = client.post(
        "/hire/range-doctor/recover",
        json=request,
        headers={"X-PAYMENT": header},
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "payment_invalid"
    assert "expired" in response.json()["error"]["message"]


def test_payment_recovery_has_a_separate_peer_address_bound(tmp_path, monkeypatch):
    monkeypatch.setattr(routes, "RECOVERY_ATTEMPTS", 2)
    client = _client(tmp_path, monkeypatch, name="bounded-recovery")
    header = _authorization(Account.create(), nonce="0x" + "12" * 32)
    request = {"wallet": WALLET}

    first = client.post(
        "/hire/range-doctor/recover",
        json=request,
        headers={"X-PAYMENT": header},
    )
    second = client.post(
        "/hire/range-doctor/recover",
        json=request,
        headers={"X-PAYMENT": header},
    )
    limited = client.post(
        "/hire/range-doctor/recover",
        json=request,
        headers={"X-PAYMENT": header},
    )

    assert first.status_code == second.status_code == 404
    assert limited.status_code == 429
    assert limited.json()["error"]["code"] == "recovery_rate_limited"
    assert int(limited.headers["Retry-After"]) > 0


def test_payment_recovery_rejects_a_tampered_signature(tmp_path, monkeypatch):
    work_calls = []

    def counted_report(address, **kwargs):
        work_calls.append(address)
        return _stub_report(address, **kwargs)

    monkeypatch.setattr(doctor, "report", counted_report)
    facilitator = FixtureFacilitator()
    client = _client(
        tmp_path,
        monkeypatch,
        name="recover-tampered-signature",
        pay_to=PAY_TO,
        facilitator=facilitator,
        admit_range=True,
    )
    request = {"wallet": WALLET}
    header = _authorization(Account.create(), nonce="0x" + "0d" * 32)
    assert (
        client.post(
            "/hire/range-doctor",
            json=request,
            headers={"X-PAYMENT": header},
        ).status_code
        == 200
    )
    payment = json.loads(base64.b64decode(header))
    signature = payment["payload"]["signature"]
    payment["payload"]["signature"] = signature[:-1] + (
        "0" if signature[-1] != "0" else "1"
    )
    tampered_header = base64.b64encode(json.dumps(payment).encode()).decode()

    response = client.post(
        "/hire/range-doctor/recover",
        json=request,
        headers={"X-PAYMENT": tampered_header},
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "payment_invalid"
    assert work_calls == [WALLET]
    assert [name for name, _ in facilitator.calls] == ["verify", "settle"]


def test_payment_recovery_refuses_a_different_request_body(tmp_path, monkeypatch):
    facilitator = FixtureFacilitator()
    client = _client(
        tmp_path,
        monkeypatch,
        name="recover-mismatch",
        pay_to=PAY_TO,
        facilitator=facilitator,
        admit_range=True,
    )
    header = _authorization(Account.create(), nonce="0x" + "0c" * 32)
    assert (
        client.post(
            "/hire/range-doctor",
            json={"wallet": WALLET},
            headers={"X-PAYMENT": header},
        ).status_code
        == 200
    )

    response = client.post(
        "/hire/range-doctor/recover",
        json={"wallet": WALLET, "limit": 1},
        headers={"X-PAYMENT": header},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "authorization_mismatch"
    assert [name for name, _ in facilitator.calls] == ["verify", "settle"]


def test_an_unknown_settlement_result_can_be_recovered_without_retry(
    tmp_path, monkeypatch
):
    work_calls = []

    def counted_report(address, **kwargs):
        work_calls.append(address)
        return _stub_report(address, **kwargs)

    monkeypatch.setattr(doctor, "report", counted_report)
    facilitator = FixtureFacilitator(
        settle_error=httpx.ReadTimeout("fixture lost the settle response")
    )
    client = _client(
        tmp_path,
        monkeypatch,
        name="recover-unknown",
        pay_to=PAY_TO,
        facilitator=facilitator,
        admit_range=True,
    )
    request = {"wallet": WALLET}
    header = _authorization(Account.create(), nonce="0x" + "0a" * 32)
    first = client.post(
        "/hire/range-doctor", json=request, headers={"X-PAYMENT": header}
    )

    recovered = client.post(
        "/hire/range-doctor/recover",
        json=request,
        headers={"PAYMENT-SIGNATURE": header},
    )
    recovered_again = client.post(
        "/hire/range-doctor/recover",
        json=request,
        headers={"X-PAYMENT": header},
    )

    assert first.status_code == 502
    assert recovered.status_code == 200
    body = recovered.json()
    assert body["result"]["address"] == WALLET
    assert body["receipt"]["payment"]["status"] == "settlement_unknown"
    assert body["receipt"]["input_hash"] == _sha256_of_canonical_json(request)
    assert body["receipt"]["output_hash"] == _sha256_of_canonical_json(body["result"])
    assert recovered_again.json() == body
    stored = Store(tmp_path / "recover-unknown.sqlite3").payment_by_nonce(
        "0x" + "0a" * 32
    )
    assert stored["receipt"] == body["receipt"]
    assert work_calls == [WALLET]
    assert [name for name, _ in facilitator.calls] == ["verify", "settle"]


def test_payment_recovery_refuses_an_unknown_nonce_without_running_work(
    tmp_path, monkeypatch
):
    work_calls = []

    def counted_report(address, **kwargs):
        work_calls.append(address)
        return _stub_report(address, **kwargs)

    monkeypatch.setattr(doctor, "report", counted_report)
    facilitator = FixtureFacilitator()
    client = _client(
        tmp_path,
        monkeypatch,
        name="recover-missing",
        pay_to=PAY_TO,
        facilitator=facilitator,
        admit_range=True,
    )
    header = _authorization(Account.create(), nonce="0x" + "0b" * 32)

    response = client.post(
        "/hire/range-doctor/recover",
        json={"wallet": WALLET},
        headers={"X-PAYMENT": header},
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "payment_not_found"
    assert work_calls == []
    assert facilitator.calls == []


def test_operator_reconciles_a_stale_settlement_without_any_external_call(
    tmp_path, monkeypatch
):
    token = "operator-reconcile-token"
    nonce = "0x" + "12" * 32
    db_path = tmp_path / "reconcile-stale.sqlite3"
    facilitator = FixtureFacilitator()
    client = _client(
        tmp_path,
        monkeypatch,
        name="reconcile-stale",
        facilitator=facilitator,
        canary_token=token,
    )
    store, request, result = _seed_payment_state(db_path, nonce=nonce, stale=True)

    def fail_if_called(*args, **kwargs):
        raise AssertionError("reconciliation performed an external action")

    monkeypatch.setattr(routes, "verify_payment", fail_if_called)
    monkeypatch.setitem(
        SERVICES,
        "range-doctor",
        replace(get_service("range-doctor"), run=fail_if_called),
    )

    response = client.post(
        "/hire/range-doctor/reconcile",
        json={"nonce": nonce},
        headers={"Authorization": f"Bearer {token}"},
    )
    recovered = client.post(
        "/hire/range-doctor/recover",
        json={"nonce": nonce},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["result"] == result
    assert body["receipt"]["service"] == "range-doctor"
    assert body["receipt"]["input_hash"] == _sha256_of_canonical_json(request)
    assert body["receipt"]["output_hash"] == _sha256_of_canonical_json(result)
    assert body["receipt"]["payment"] == {
        "status": "settlement_unknown",
        "asset": USDT_TOKEN,
        "amount": str(5 * 10**17),
        "payer": "0x" + "22" * 20,
        "recipient": PAY_TO,
        "nonce": nonce,
        "payment_id": f"payment-{nonce}",
        "resource": "http://testserver/hire/range-doctor",
        "evidence": (
            "operator reconciled a stale settling state without making another external "
            "call; prior settlement outcome remains unknown"
        ),
    }
    assert recovered.status_code == 200
    assert recovered.json() == body
    stored = store.payment_by_nonce(nonce)
    assert stored["status"] == "settlement_unknown"
    assert stored["receipt"] == body["receipt"]
    assert stored["transaction_id"] is None
    assert stored["network"] is None
    assert stored["operator_recovered_at"] is not None
    assert facilitator.calls == []


@pytest.mark.parametrize("status", ("verified", "output_ready"))
def test_operator_closes_a_stale_pre_settlement_state_without_external_work(
    tmp_path, monkeypatch, status
):
    token = "operator-reconcile-token"
    nonce = "0x" + ("17" if status == "verified" else "18") * 32
    db_path = tmp_path / f"reconcile-{status}.sqlite3"
    facilitator = FixtureFacilitator()
    client = _client(
        tmp_path,
        monkeypatch,
        name=f"reconcile-{status}",
        facilitator=facilitator,
        canary_token=token,
    )
    store, _, result = _seed_payment_state(
        db_path, nonce=nonce, stale=True, status=status
    )

    def fail_if_called(*args, **kwargs):
        raise AssertionError("pre-settlement reconciliation performed external work")

    monkeypatch.setattr(routes, "verify_payment", fail_if_called)
    monkeypatch.setitem(
        SERVICES,
        "range-doctor",
        replace(get_service("range-doctor"), run=fail_if_called),
    )

    response = client.post(
        "/hire/range-doctor/reconcile",
        json={"nonce": nonce},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "payment": {
            "status": "failed_no_charge",
            "previous_status": status,
            "service": "range-doctor",
            "nonce": nonce,
            "payment_id": f"payment-{nonce}",
            "charge_attempted": False,
            "result_delivered": False,
        }
    }
    stored = store.payment_by_nonce(nonce)
    assert stored["status"] == "failed_no_charge"
    assert stored.get("result") == (result if status == "output_ready" else None)
    assert stored["transaction_id"] is None
    assert stored["network"] is None
    assert stored["receipt_json"] is None
    assert facilitator.calls == []


@pytest.mark.parametrize(
    ("headers", "expected_code"),
    (
        ({}, "operator_unauthorized"),
        ({"Authorization": "Bearer wrong-token"}, "operator_unauthorized"),
    ),
)
def test_settlement_reconciliation_requires_the_operator_bearer(
    tmp_path, monkeypatch, headers, expected_code
):
    token = "operator-reconcile-token"
    nonce = "0x" + "13" * 32
    db_path = tmp_path / "reconcile-auth.sqlite3"
    client = _client(
        tmp_path,
        monkeypatch,
        name="reconcile-auth",
        canary_token=token,
    )
    store, _, _ = _seed_payment_state(db_path, nonce=nonce, stale=True)

    response = client.post(
        "/hire/range-doctor/reconcile", json={"nonce": nonce}, headers=headers
    )

    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"
    assert response.json()["error"]["code"] == expected_code
    assert store.payment_by_nonce(nonce)["status"] == "settling"


@pytest.mark.parametrize("status", ("verified", "output_ready", "settling"))
def test_operator_cannot_reconcile_an_active_payment_state(
    tmp_path, monkeypatch, status
):
    token = "operator-reconcile-token"
    nonce = "0x" + "14" * 32
    db_path = tmp_path / "reconcile-fresh.sqlite3"
    client = _client(
        tmp_path,
        monkeypatch,
        name="reconcile-fresh",
        canary_token=token,
    )
    store, _, _ = _seed_payment_state(db_path, nonce=nonce, stale=False, status=status)

    response = client.post(
        "/hire/range-doctor/reconcile",
        json={"nonce": nonce},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "settlement_still_active"
    stored = store.payment_by_nonce(nonce)
    assert stored["status"] == status
    assert stored["receipt_json"] is None


def test_facilitator_verification_reason_is_not_exposed(tmp_path, monkeypatch):
    private_reason = "signature lookup failed against internal node 10.0.0.4"

    class RejectingFacilitator(FixtureFacilitator):
        def verify(self, envelope):
            self.calls.append(("verify", envelope))
            payer = envelope["paymentPayload"]["payload"]["authorization"]["from"]
            return {
                "isValid": False,
                "payer": payer,
                "invalidReason": private_reason,
            }

    facilitator = RejectingFacilitator()
    nonce = "0x" + "15" * 32
    client = _client(
        tmp_path,
        monkeypatch,
        name="private-verification-reason",
        pay_to=PAY_TO,
        facilitator=facilitator,
        admit_range=True,
    )

    response = client.post(
        "/hire/range-doctor",
        json={"wallet": WALLET},
        headers={"X-PAYMENT": _authorization(Account.create(), nonce=nonce)},
    )

    assert response.status_code == 402
    assert response.json()["error"] == {
        "code": "payment_not_verified",
        "message": (
            "The facilitator rejected the payment. No work ran and no charge was attempted."
        ),
    }
    assert private_reason not in response.text
    assert (
        Store(tmp_path / "private-verification-reason.sqlite3").payment_by_nonce(nonce)
        == {}
    )
    assert [name for name, _ in facilitator.calls] == ["verify"]


def test_settlement_failure_reason_is_private_but_durably_recorded(
    tmp_path, monkeypatch
):
    private_reason = "relayer key alias prod-7 is unavailable"

    class RefusingFacilitator(FixtureFacilitator):
        def settle(self, envelope):
            self.calls.append(("settle", envelope))
            return {"success": False, "errorReason": private_reason}

    facilitator = RefusingFacilitator()
    nonce = "0x" + "16" * 32
    client = _client(
        tmp_path,
        monkeypatch,
        name="private-settlement-reason",
        pay_to=PAY_TO,
        facilitator=facilitator,
        admit_range=True,
    )

    response = client.post(
        "/hire/range-doctor",
        json={"wallet": WALLET},
        headers={"X-PAYMENT": _authorization(Account.create(), nonce=nonce)},
    )

    assert response.status_code == 502
    assert response.json()["error"] == {
        "code": "settlement_failed",
        "message": (
            "The facilitator did not settle this authorization. No result was delivered."
        ),
    }
    assert private_reason not in response.text
    stored = Store(tmp_path / "private-settlement-reason.sqlite3").payment_by_nonce(
        nonce
    )
    assert stored["status"] == "settlement_failed"
    assert stored["error"] == private_reason
    assert [name for name, _ in facilitator.calls] == ["verify", "settle"]


def test_de_admission_after_verification_prevents_settlement(tmp_path, monkeypatch):
    """A canary can fail while paid work is in flight. The request must re-read the shared
    gate after producing value and close without settlement or delivery."""
    db_path = tmp_path / "admission-race.sqlite3"

    class DeAdmittingFacilitator(FixtureFacilitator):
        def verify(self, envelope):
            verification = super().verify(envelope)
            Store(db_path).begin_canary_run("range-doctor", "https://docket.example")
            return verification

    facilitator = DeAdmittingFacilitator()
    client = _client(
        tmp_path,
        monkeypatch,
        name="admission-race",
        pay_to=PAY_TO,
        facilitator=facilitator,
        admit_range=True,
    )
    header = _authorization(Account.create(), nonce="0x" + "08" * 32)

    response = client.post(
        "/hire/range-doctor",
        json={"wallet": WALLET},
        headers={"X-PAYMENT": header},
    )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "service_de_admitted"
    assert [name for name, _ in facilitator.calls] == ["verify"]
    payment = Store(db_path).payment_by_nonce("0x" + "08" * 32)
    assert payment["status"] == "failed_no_charge"


def test_unadmitted_services_never_offer_or_consume_payment(tmp_path, monkeypatch):
    """Research, preview and beta entries stay runnable examples, but their catalogue
    records and receipts cannot imply that passing an authorization bought them."""
    facilitator = FixtureFacilitator()
    client = _client(
        tmp_path,
        monkeypatch,
        pay_to=PAY_TO,
        facilitator=facilitator,
    )
    header = _authorization(Account.create(), nonce="0x" + "08" * 32)

    body = client.post(
        "/hire/range-doctor",
        json={"wallet": WALLET},
        headers={"X-PAYMENT": header},
    ).json()
    catalogue = {row["id"]: row for row in client.get("/hire").json()["services"]}

    assert body["receipt"]["payment"] == {
        "status": "not_for_sale",
        "stock_status": "candidate",
        "authorization_used": False,
    }
    assert facilitator.calls == []
    assert all(row["paid_stock"] is False for row in catalogue.values())
    assert catalogue["grid-operator"]["stock_status"] == "preview"
    assert catalogue["health-guard"]["stock_status"] == "preview"
    assert catalogue["solvent-signal"]["stock_status"] == "research"
    assert catalogue["warden-scan"]["stock_status"] == "beta"
