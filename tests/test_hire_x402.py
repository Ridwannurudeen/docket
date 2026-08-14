import base64
import json
import time

import httpx
from eth_account import Account
from eth_account.messages import encode_typed_data

from docket.hire.catalogue import U_TOKEN, get_service
from docket.hire.x402 import (
    BSC_CHAIN_ID,
    EIP3009_TYPES,
    FacilitatorClient,
    OK,
    build_challenge,
    facilitator_envelope,
    parse_payment_header,
    verify_payment,
)

PAY_TO = "0x" + "11" * 20
RESOURCE = "https://d/hire/range-doctor"
PRICE = 5 * 10**17


def _payment(
    acct,
    *,
    to=PAY_TO,
    value=PRICE,
    valid_after=0,
    valid_before=None,
    chain_id=BSC_CHAIN_ID,
    signing_asset=U_TOKEN,
    nonce="0x" + "02" * 32,
):
    challenge = build_challenge(get_service("range-doctor"), PAY_TO, resource=RESOURCE)
    requirements = challenge["accepts"][0]
    authorization = {
        "from": acct.address,
        "to": to,
        "value": str(value),
        "validAfter": str(valid_after),
        "validBefore": str(valid_before or int(time.time()) + 300),
        "nonce": nonce,
    }
    domain = {
        "name": "United Stables",
        "version": "1",
        "chainId": chain_id,
        "verifyingContract": signing_asset,
    }
    signature = acct.sign_message(
        encode_typed_data(domain, EIP3009_TYPES, authorization)
    ).signature.hex()
    return (
        {
            "x402Version": 2,
            "resource": challenge["resource"],
            "accepted": requirements,
            "payload": {"signature": signature, "authorization": authorization},
        },
        requirements,
        challenge["resource"],
    )


def _verify(payment, requirements, resource, *, now=None):
    return verify_payment(
        payment,
        expected_requirements=requirements,
        expected_resource=resource,
        now=now,
    )


def test_challenge_declares_the_current_exact_bsc_payment_requirements():
    """The current v2 schema uses `amount` and a top-level resource object; the legacy
    `maxAmountRequired` offer must not return under a v2 label."""
    challenge = build_challenge(get_service("range-doctor"), PAY_TO, resource=RESOURCE)

    assert challenge["x402Version"] == 2
    assert challenge["resource"]["url"] == RESOURCE
    offer = challenge["accepts"][0]
    assert offer["scheme"] == "exact"
    assert offer["network"] == "eip155:56"
    assert offer["amount"] == str(PRICE)
    assert "maxAmountRequired" not in offer
    assert offer["asset"] == U_TOKEN
    assert offer["payTo"] == PAY_TO
    assert offer["maxTimeoutSeconds"] == 300
    assert offer["extra"] == {
        "assetTransferMethod": "eip3009",
        "name": "United Stables",
        "version": "1",
    }


def test_one_canonical_exact_authorization_verifies_and_exposes_its_nonce():
    payment, requirements, resource = _payment(Account.create())
    verified, reason = _verify(payment, requirements, resource)

    assert reason == OK
    assert verified is not None
    assert verified.nonce == "0x" + "02" * 32
    assert verified.payment_id.startswith("0x")


def test_exact_price_rejects_both_short_payment_and_overpayment():
    """`exact` means equality. Accepting an overpayment would silently restore the old
    minimum-price behavior and make the published flat 0.50 $U offer false."""
    for value in (PRICE - 1, PRICE + 1):
        payment, requirements, resource = _payment(Account.create(), value=value)
        verified, reason = _verify(payment, requirements, resource)
        assert verified is None
        assert "exact amount" in reason


def test_asset_domain_and_current_authorization_window_are_checked():
    """A signature over another contract or a future validAfter is not spendable under
    the advertised $U authorization, even when every visible payment field matches."""
    other_asset = "0x" + "22" * 20
    payment, requirements, resource = _payment(
        Account.create(), signing_asset=other_asset
    )
    verified, reason = _verify(payment, requirements, resource)
    assert verified is None
    assert "signature" in reason

    now = int(time.time())
    payment, requirements, resource = _payment(
        Account.create(), valid_after=now + 10, valid_before=now + 300
    )
    verified, reason = _verify(payment, requirements, resource, now=now)
    assert verified is None
    assert "not valid yet" in reason


def test_offer_resource_recipient_chain_nonce_and_expiry_are_bound():
    acct = Account.create()
    cases = [
        ({"to": "0x" + "33" * 20}, "recipient"),
        ({"chain_id": 1}, "signature"),
        ({"nonce": "0x1234"}, "nonce"),
        ({"valid_before": int(time.time()) - 10}, "expired"),
    ]
    for kwargs, expected_reason in cases:
        payment, requirements, resource = _payment(acct, **kwargs)
        verified, reason = _verify(payment, requirements, resource)
        assert verified is None
        assert expected_reason in reason

    payment, requirements, resource = _payment(acct)
    payment["resource"] = {**resource, "url": "https://d/hire/another-service"}
    verified, reason = _verify(payment, requirements, resource)
    assert verified is None
    assert "resource" in reason


def test_tampering_with_the_authorization_fails_recovery():
    payment, requirements, resource = _payment(Account.create())
    payment["payload"]["authorization"]["value"] = str(PRICE - 1)
    requirements = {**requirements, "amount": str(PRICE - 1)}
    payment["accepted"] = requirements

    verified, reason = _verify(payment, requirements, resource)
    assert verified is None
    assert "signature" in reason


def test_header_is_read_from_either_supported_spelling():
    blob = base64.b64encode(json.dumps({"a": 1}).encode()).decode()
    assert parse_payment_header({"x-payment": blob}) == {"a": 1}
    assert parse_payment_header({"payment-signature": blob}) == {"a": 1}
    assert parse_payment_header({}) is None


def test_malformed_header_returns_none_rather_than_raising():
    assert parse_payment_header({"x-payment": "not-base64!!"}) is None


def test_facilitator_client_posts_the_verified_v2_envelope_without_retry(monkeypatch):
    """The dry-run adapter proves the official `/verify` and `/settle` envelope while
    leaving the concrete facilitator URL and live authorization to the owner."""
    payment, requirements, _ = _payment(Account.create())
    envelope = facilitator_envelope(payment, requirements)
    calls = []

    def fake_post(url, *, json, timeout):
        calls.append((url, json, timeout))
        body = (
            {"isValid": True, "payer": payment["payload"]["authorization"]["from"]}
            if url.endswith("/verify")
            else {
                "success": True,
                "payer": payment["payload"]["authorization"]["from"],
                "transaction": "0xdry-run-transaction",
                "network": "eip155:56",
            }
        )
        return httpx.Response(200, json=body, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx, "post", fake_post)
    client = FacilitatorClient("https://facilitator.invalid")

    assert client.verify(envelope)["isValid"] is True
    assert client.settle(envelope)["success"] is True
    assert [call[0] for call in calls] == [
        "https://facilitator.invalid/verify",
        "https://facilitator.invalid/settle",
    ]
    assert all(call[1] == envelope for call in calls)
