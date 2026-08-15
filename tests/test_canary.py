import base64
import json
from datetime import datetime, timezone

import httpx

from docket.canary import (
    END_AT,
    HIRE_PRICE_ATOMIC,
    LEG_NAMES,
    main,
    run_from_environment,
)
from docket.hire.catalogue import U_TOKEN
from docket.hire.receipts import canonical_hash
from docket.hire.x402 import verify_payment
from docket.store import Store


NOW = datetime(2026, 8, 15, 12, 0, tzinfo=timezone.utc)
BASE_URL = "https://docket.example"
WALLET = "0x451871A1753903FB8fdd64a6B838E95aB8D5B80f"
TOKEN_ID = 7_087_132
PAY_TO = "0x" + "11" * 20


def _environment(tmp_path, *, controlled_lp=False, paid=False):
    environment = {
        "DOCKET_DB": str(tmp_path / "agents.sqlite3"),
        "DOCKET_CANARY_BASE_URL": BASE_URL,
        "DOCKET_CANARY_END_AT": END_AT.isoformat().replace("+00:00", "Z"),
    }
    if controlled_lp:
        environment.update(
            {
                "DOCKET_CANARY_WALLET": WALLET,
                "DOCKET_CANARY_TOKEN_ID": str(TOKEN_ID),
                "DOCKET_CANARY_POSITION_VALUE_USD": "10000",
                "DOCKET_CANARY_RECENTER_COST_USD": "25",
            }
        )
    if paid:
        key_file = tmp_path / "canary-key.txt"
        token_file = tmp_path / "canary-token.txt"
        key_file.write_text("0x" + "01" * 32, encoding="utf-8")
        token_file.write_text("owner-canary-token-fixture", encoding="utf-8")
        environment.update(
            {
                "DOCKET_CANARY_PRIVATE_KEY_FILE": str(key_file),
                "DOCKET_CANARY_TOKEN_FILE": str(token_file),
            }
        )
    return environment


def _public_response(request, store):
    latest = store.latest_canary_run("range-doctor")
    assert latest["verdict"] == "running", "HTTP started before the durable run row"
    if request.url.path == "/":
        return httpx.Response(
            200,
            headers={"content-type": "text/html; charset=utf-8"},
            text=(
                '<!doctype html><html><head><script type="module" '
                'src="/static/app.js?v=4"></script></head></html>'
            ),
            request=request,
        )
    if request.url.path == "/static/app.js":
        return httpx.Response(
            200,
            headers={"content-type": "text/javascript; charset=utf-8"},
            text="export const docket = true;",
            request=request,
        )
    if request.url.path == "/stats":
        return httpx.Response(
            200,
            json={
                "coverage": {
                    "snapshot_id": 19,
                    "captured_at": "2026-08-15T06:00:00+00:00",
                    "snapshot_age_seconds": 21_600,
                }
            },
            request=request,
        )
    if request.url.path == "/advantage/v2.json":
        return httpx.Response(
            200,
            json={
                "version": "v2",
                "summary": {"n_experiments": 1},
                "experiments": [
                    {
                        "experiment_id": "fixture",
                        "spec": {"spec_hash": "0xspec"},
                        "run": {"run_id": "fixture"},
                        "falsifier_result": {"checks": [], "refuted": False},
                    }
                ],
            },
            request=request,
        )
    raise AssertionError(f"unexpected request {request.method} {request.url}")


def _decision_grade_result():
    return {
        "decision": "Position 7087132 is inside its range and can earn fees.",
        "target_token_id": TOKEN_ID,
        "target_found": True,
        "positions_held": 1,
        "positions_examined": 1,
        "closed_skipped": 0,
        "open_skipped": 0,
        "scan_complete": True,
        "coverage": "All one of this wallet's position NFTs was read.",
        "primary_limitation": "One observation is not a forecast.",
        "positions": [
            {
                "diagnosis": {
                    "status": "in_range",
                    "decision": "Position 7087132 is inside its range and can earn fees.",
                    "verifiable_facts": {
                        "position_id": TOKEN_ID,
                        "current_tick": 65_821,
                        "lower_tick": 65_452,
                        "upper_tick": 66_052,
                        "bsc_block": 114_740_301,
                        "observation_time": "2026-08-15T11:59:00+00:00",
                    },
                    "economic_consequence": {
                        "declared_position_value_usd": 10_000.0,
                        "gross_apr": 0.42,
                        "net_apr": 0.28,
                        "annual_gross_usd": 4_200.0,
                        "annual_net_usd": 2_800.0,
                        "annual_overstatement_usd": 1_400.0,
                        "position_annual_fee_usd": 2_800.0,
                        "unavailable_reason": None,
                    },
                    "conditional_actions": {
                        "actions": [
                            {"kind": "wait", "text": "Wait if the range still fits."},
                            {
                                "kind": "recenter",
                                "text": "Recenter only if the stated cost is acceptable.",
                            },
                        ],
                        "estimated_recenter_cost_usd": 25.0,
                        "cost_only_break_even_days": 3.26,
                        "unavailable_reason": None,
                    },
                }
            }
        ],
        "measured_value": {
            "this_run_seconds": 1.25,
            "paired_manual_seconds": 12.5,
            "quality_result": {"decision_grade": True},
            "report_url": "/advantage/v3/range-doctor",
        },
    }


def test_an_unfunded_canary_records_three_passes_and_never_greens_skipped_legs(
    tmp_path,
):
    environment = _environment(tmp_path)
    store = Store(environment["DOCKET_DB"])
    requests = []

    def handler(request):
        requests.append((request.method, request.url.path))
        return _public_response(request, store)

    outcome = run_from_environment(
        environment,
        now=NOW,
        transport=httpx.MockTransport(handler),
        store=store,
    )

    assert outcome.verdict == "not_yet_exercised"
    assert [check["leg"] for check in outcome.checks] == list(LEG_NAMES)
    assert [check["status"] for check in outcome.checks] == [
        "passed",
        "passed",
        "passed",
        "not_yet_exercised",
        "not_yet_exercised",
        "not_yet_exercised",
        "not_yet_exercised",
        "not_yet_exercised",
    ]
    assert requests == [
        ("GET", "/"),
        ("GET", "/static/app.js"),
        ("GET", "/stats"),
        ("GET", "/advantage/v2.json"),
    ]
    persisted = store.latest_canary_run("range-doctor")
    assert persisted["verdict"] == "not_yet_exercised"
    assert persisted["checks"] == outcome.checks
    assert persisted["target_url"] == BASE_URL
    assert outcome.checks[0]["observed"]["javascript_rendered"] is False
    assert outcome.checks[1]["observed"]["snapshot_age_seconds"] == 21_600


def test_a_complete_paid_canary_settles_once_proves_the_receipt_and_rejects_replay(
    tmp_path,
):
    environment = _environment(tmp_path, controlled_lp=True, paid=True)
    store = Store(environment["DOCKET_DB"])
    paid_headers = []
    result = _decision_grade_result()
    request_payload = {
        "wallet": WALLET,
        "token_id": TOKEN_ID,
        "declared_position_value_usd": 10_000.0,
        "estimated_recenter_cost_usd": 25.0,
    }

    def handler(request):
        if request.url.path != "/hire/range-doctor":
            return _public_response(request, store)
        payment_header = request.headers.get("x-payment")
        if payment_header is None:
            assert "x-docket-canary" not in request.headers
            return httpx.Response(
                200,
                json={
                    "result": result,
                    "receipt": {
                        "service": "range-doctor",
                        "input_hash": canonical_hash(request_payload),
                        "output_hash": canonical_hash(result),
                        "delivered_at": "2026-08-15T12:00:00+00:00",
                        "payment": {"status": "free_tier"},
                    },
                },
                request=request,
            )

        assert request.headers["x-docket-canary"] == "owner-canary-token-fixture"
        if payment_header == "invalid":
            return httpx.Response(
                402,
                json={
                    "x402Version": 2,
                    "resource": {
                        "url": str(request.url),
                        "description": "Range Doctor",
                        "mimeType": "application/json",
                    },
                    "accepts": [
                        {
                            "scheme": "exact",
                            "network": "eip155:56",
                            "amount": str(HIRE_PRICE_ATOMIC),
                            "asset": U_TOKEN,
                            "payTo": PAY_TO,
                            "maxTimeoutSeconds": 300,
                            "extra": {
                                "assetTransferMethod": "eip3009",
                                "name": "United Stables",
                                "version": "1",
                            },
                        }
                    ],
                    "error": {"code": "payment_invalid", "message": "fixture"},
                },
                request=request,
            )
        paid_headers.append(payment_header)
        payment = json.loads(base64.b64decode(payment_header, validate=True))
        verified, reason = verify_payment(
            payment,
            expected_requirements={
                "scheme": "exact",
                "network": "eip155:56",
                "amount": str(HIRE_PRICE_ATOMIC),
                "asset": U_TOKEN,
                "payTo": PAY_TO,
                "maxTimeoutSeconds": 300,
                "extra": {
                    "assetTransferMethod": "eip3009",
                    "name": "United Stables",
                    "version": "1",
                },
            },
            expected_resource={
                "url": str(request.url),
                "description": "Range Doctor",
                "mimeType": "application/json",
            },
            now=int(NOW.timestamp()),
        )
        assert verified is not None, reason
        authorization = payment["payload"]["authorization"]
        assert int(authorization["value"]) == HIRE_PRICE_ATOMIC
        assert authorization["to"] == PAY_TO
        if len(paid_headers) == 2:
            assert paid_headers[1] == paid_headers[0]
            return httpx.Response(
                409,
                json={
                    "error": {
                        "code": "authorization_replay",
                        "message": "already settled",
                    }
                },
                request=request,
            )
        receipt = {
            "service": "range-doctor",
            "input_hash": canonical_hash(request_payload),
            "output_hash": canonical_hash(result),
            "delivered_at": "2026-08-15T12:00:02+00:00",
            "payment": {
                "status": "settled",
                "amount": str(HIRE_PRICE_ATOMIC),
                "asset": U_TOKEN,
                "payer": authorization["from"],
                "recipient": PAY_TO,
                "nonce": authorization["nonce"],
                "payment_id": "0xpayment",
                "transaction_id": "0xsettlement",
                "network": "eip155:56",
            },
        }
        return httpx.Response(
            200, json={"result": result, "receipt": receipt}, request=request
        )

    outcome = run_from_environment(
        environment,
        now=NOW,
        transport=httpx.MockTransport(handler),
        store=store,
    )

    assert outcome.verdict == "passed"
    assert all(check["status"] == "passed" for check in outcome.checks)
    assert len(paid_headers) == 2
    durable = json.dumps(store.latest_canary_run("range-doctor")["checks"])
    assert "owner-canary-token-fixture" not in durable
    assert ("0x" + "01" * 32) not in durable
    assert paid_headers[0] not in durable
    assert '"authorization"' not in durable


def test_a_non_decision_grade_free_preflight_fails_before_any_payment_material_is_read(
    tmp_path,
):
    environment = _environment(tmp_path, controlled_lp=True, paid=True)
    store = Store(environment["DOCKET_DB"])
    hire_headers = []

    def handler(request):
        if request.url.path != "/hire/range-doctor":
            return _public_response(request, store)
        hire_headers.append(dict(request.headers))
        return httpx.Response(
            200,
            json={
                "result": {
                    **_decision_grade_result(),
                    "target_found": False,
                    "positions": [],
                },
                "receipt": {"payment": {"status": "free_tier"}},
            },
            request=request,
        )

    outcome = run_from_environment(
        environment,
        now=NOW,
        transport=httpx.MockTransport(handler),
        store=store,
    )

    assert outcome.verdict == "failed"
    checks = {check["leg"]: check for check in outcome.checks}
    assert checks["controlled_live_lp"]["status"] == "failed"
    assert checks["exact_0_50_settlement"]["status"] == "not_yet_exercised"
    assert len(hire_headers) == 1
    assert "x-payment" not in hire_headers[0]
    assert "x-docket-canary" not in hire_headers[0]


def test_a_live_lp_with_only_the_owner_token_keeps_paid_legs_not_yet_exercised(
    tmp_path,
):
    environment = _environment(tmp_path, controlled_lp=True)
    environment["DOCKET_CANARY_TOKEN_FILE"] = str(tmp_path / "owner-token-not-read.txt")
    store = Store(environment["DOCKET_DB"])

    def handler(request):
        if request.url.path != "/hire/range-doctor":
            return _public_response(request, store)
        assert "x-payment" not in request.headers
        assert "x-docket-canary" not in request.headers
        return httpx.Response(
            200,
            json={
                "result": _decision_grade_result(),
                "receipt": {"payment": {"status": "free_tier"}},
            },
            request=request,
        )

    outcome = run_from_environment(
        environment,
        now=NOW,
        transport=httpx.MockTransport(handler),
        store=store,
    )

    assert outcome.verdict == "not_yet_exercised"
    assert [check["status"] for check in outcome.checks[3:]] == [
        "passed",
        "not_yet_exercised",
        "not_yet_exercised",
        "not_yet_exercised",
        "not_yet_exercised",
    ]
    assert outcome.checks[4]["evidence"]["reason"] == "owner_payment_material_absent"


def test_an_internal_runner_error_is_finalized_as_a_sanitized_failed_run(tmp_path):
    environment = _environment(tmp_path)
    store = Store(environment["DOCKET_DB"])

    def handler(request):
        raise RuntimeError("sensitive fixture detail that must not be stored")

    outcome = run_from_environment(
        environment,
        now=NOW,
        transport=httpx.MockTransport(handler),
        store=store,
    )

    assert outcome.verdict == "failed"
    assert [check["leg"] for check in outcome.checks] == list(LEG_NAMES)
    assert outcome.checks[0]["status"] == "failed"
    assert outcome.checks[0]["evidence"] == {"error_type": "RuntimeError"}
    durable = json.dumps(store.latest_canary_run("range-doctor"))
    assert '"verdict": "failed"' in durable
    assert "sensitive fixture detail" not in durable


def test_untrusted_public_metadata_cannot_break_or_poison_the_durable_record(tmp_path):
    environment = _environment(tmp_path)
    store = Store(environment["DOCKET_DB"])

    def handler(request):
        if request.url.path != "/stats":
            return _public_response(request, store)
        return httpx.Response(
            200,
            content=(
                b'{"coverage":{"snapshot_id":{"private_key":"reflected-secret"},'
                b'"captured_at":["not","a","timestamp"],'
                b'"snapshot_age_seconds":NaN}}'
            ),
            headers={"content-type": "application/json"},
            request=request,
        )

    outcome = run_from_environment(
        environment,
        now=NOW,
        transport=httpx.MockTransport(handler),
        store=store,
    )

    assert outcome.verdict == "failed"
    snapshot = outcome.checks[1]
    assert snapshot["status"] == "failed"
    assert snapshot["observed"] == {
        "snapshot_id": None,
        "captured_at": None,
        "snapshot_age_seconds": None,
    }
    durable = json.dumps(store.latest_canary_run("range-doctor"))
    assert "reflected-secret" not in durable
    assert '"verdict": "failed"' in durable


def test_an_active_window_configuration_error_records_failure_without_http(
    tmp_path,
):
    environment = _environment(tmp_path)
    environment["DOCKET_CANARY_END_AT"] = "not-a-timestamp"

    def handler(request):
        raise AssertionError(f"HTTP ran with invalid configuration: {request.url}")

    outcome = run_from_environment(
        environment,
        now=NOW,
        transport=httpx.MockTransport(handler),
    )

    assert outcome.verdict == "failed"
    assert [check["leg"] for check in outcome.checks] == list(LEG_NAMES)
    assert outcome.checks[0]["status"] == "failed"
    assert outcome.checks[0]["evidence"] == {
        "reason": "configuration_invalid",
        "error_type": "ValueError",
    }
    store = Store(environment["DOCKET_DB"])
    assert store.latest_canary_run("range-doctor")["verdict"] == "failed"


def test_the_exclusive_end_returns_zero_without_creating_history_or_opening_http(
    tmp_path, capsys
):
    environment = _environment(tmp_path)

    def handler(request):
        raise AssertionError(f"HTTP ran after the monitoring window: {request.url}")

    code = main(
        environment,
        now=END_AT,
        transport=httpx.MockTransport(handler),
    )

    assert code == 0
    assert not (tmp_path / "agents.sqlite3").exists()
    assert "window ended" in capsys.readouterr().out.lower()


def test_cli_exit_codes_distinguish_failure_from_work_not_yet_exercised(
    tmp_path, capsys
):
    not_yet_environment = _environment(tmp_path / "not-yet")
    not_yet_store = Store(not_yet_environment["DOCKET_DB"])

    def not_yet_handler(request):
        return _public_response(request, not_yet_store)

    not_yet = main(
        not_yet_environment,
        now=NOW,
        transport=httpx.MockTransport(not_yet_handler),
        store=not_yet_store,
    )

    failed_environment = _environment(tmp_path / "failed", controlled_lp=True)
    failed_store = Store(failed_environment["DOCKET_DB"])

    def failed_handler(request):
        if request.url.path == "/hire/range-doctor":
            return httpx.Response(502, json={"error": {"code": "upstream"}})
        return _public_response(request, failed_store)

    failed = main(
        failed_environment,
        now=NOW,
        transport=httpx.MockTransport(failed_handler),
        store=failed_store,
    )

    assert not_yet == 2
    assert failed == 1
    output = capsys.readouterr().out
    assert "not_yet_exercised" in output
    assert "failed" in output
