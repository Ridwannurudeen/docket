import base64
import json
import time

import httpx
from eth_account import Account
from eth_account.messages import encode_typed_data

from docket.hire.catalogue import USDT_TOKEN, get_service
from docket.hire.x402 import (
    B402_FACILITATOR,
    B402_NETWORK,
    B402_RELAYER,
    BSC_CHAIN_ID,
    EIP712_DOMAINS,
    GENERIC_FACILITATOR,
    TRANSFER_WITH_AUTHORIZATION_TYPES,
    FacilitatorClient,
    OK,
    build_signed_payment,
    build_challenge,
    facilitator_envelope,
    parse_payment_header,
    payment_preflight,
    verify_payment,
)

PAY_TO = "0x" + "11" * 20
RESOURCE = "https://d/hire/range-doctor"
PRICE = 5 * 10**17


class _Call:
    def __init__(self, value):
        self.value = value

    def call(self):
        return self.value


class _TokenFunctions:
    def __init__(self, balance, allowance):
        self.balance = balance
        self.allowed = allowance

    def decimals(self):
        return _Call(18)

    def balanceOf(self, payer):
        return _Call(self.balance)

    def allowance(self, payer, relayer):
        return _Call(self.allowed)


class _RelayerFunctions:
    def __init__(self, *, whitelisted, domain, paused=False):
        self.whitelisted = whitelisted
        self.domain = domain
        self.is_paused = paused

    def whitelistedTokens(self, token):
        return _Call(self.whitelisted)

    def paused(self):
        return _Call(self.is_paused)

    def eip712Domain(self):
        return _Call(self.domain)


class _Contract:
    def __init__(self, functions):
        self.functions = functions


class _FakeEth:
    def __init__(self, *, balance, allowance, whitelisted, domain, code=b"proxy"):
        self.token = _Contract(_TokenFunctions(balance, allowance))
        self.relayer = _Contract(
            _RelayerFunctions(whitelisted=whitelisted, domain=domain)
        )
        self.code = code

    def contract(self, *, address, abi):
        if address.lower() == USDT_TOKEN.lower():
            return self.token
        assert address.lower() == B402_RELAYER.lower()
        return self.relayer

    def get_code(self, address):
        assert address.lower() == B402_RELAYER.lower()
        return self.code


class _FakeWeb3:
    def __init__(self, **kwargs):
        self.eth = _FakeEth(**kwargs)

    @staticmethod
    def to_checksum_address(address):
        return address


class _VerifyOnlyFacilitator:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def verify(self, envelope):
        self.calls.append(envelope)
        return self.response


def _domain(*, name="B402", version="1", chain_id=56, relayer=B402_RELAYER):
    return (b"\x0f", name, version, chain_id, relayer, b"\x00" * 32, [])


def _preflight_environment(key_file):
    return {
        "DOCKET_CANARY_PRIVATE_KEY_FILE": str(key_file),
        "DOCKET_BSC_RPC_URL": "https://rpc.invalid",
        "DOCKET_FACILITATOR_URL": "https://facilitator.invalid/api/v1",
        "DOCKET_FACILITATOR_KIND": B402_FACILITATOR,
        "DOCKET_PAYMENT_TOKEN": USDT_TOKEN,
        "DOCKET_B402_RELAYER_CONTRACT": B402_RELAYER,
        "DOCKET_PAY_TO": PAY_TO,
        "DOCKET_CANARY_BASE_URL": "https://docket.invalid",
    }


def _payment(
    acct,
    *,
    to=PAY_TO,
    value=PRICE,
    valid_after=0,
    valid_before=None,
    chain_id=BSC_CHAIN_ID,
    signing_relayer=B402_RELAYER,
    nonce="0x" + "02" * 32,
):
    challenge = build_challenge(get_service("range-doctor"), PAY_TO, resource=RESOURCE)
    requirements = challenge["accepts"][0]
    authorization = {
        "token": USDT_TOKEN,
        "from": acct.address,
        "to": to,
        "value": str(value),
        "validAfter": valid_after,
        "validBefore": valid_before or int(time.time()) + 300,
        "nonce": nonce,
    }
    domain = {
        "name": "B402",
        "version": "1",
        "chainId": chain_id,
        "verifyingContract": signing_relayer,
    }
    signature = acct.sign_message(
        encode_typed_data(domain, TRANSFER_WITH_AUTHORIZATION_TYPES, authorization)
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
    assert offer["asset"] == USDT_TOKEN
    assert offer["payTo"] == PAY_TO
    assert offer["maxTimeoutSeconds"] == 300
    assert offer["extra"] == {
        "assetTransferMethod": "b402-relayer",
        "name": "B402",
        "version": "1",
        "chainId": BSC_CHAIN_ID,
        "verifyingContract": B402_RELAYER,
        "relayerContract": B402_RELAYER,
    }


def test_b402_terms_pin_the_live_token_relayer_and_domain():
    assert USDT_TOKEN == "0x55d398326f99059fF775485246999027B3197955"
    assert B402_RELAYER == "0xE1Af7DaEa624bA3B5073f24A6Ea5531434D82d88"
    assert EIP712_DOMAINS[USDT_TOKEN.lower()] == {
        "name": "B402",
        "version": "1",
        "chainId": 56,
        "verifyingContract": "0xE1Af7DaEa624bA3B5073f24A6Ea5531434D82d88",
    }
    assert [
        field["name"]
        for field in TRANSFER_WITH_AUTHORIZATION_TYPES["TransferWithAuthorization"]
    ] == [
        "token",
        "from",
        "to",
        "value",
        "validAfter",
        "validBefore",
        "nonce",
    ]


def test_one_canonical_exact_authorization_verifies_and_exposes_its_nonce():
    payment, requirements, resource = _payment(Account.create())
    verified, reason = _verify(payment, requirements, resource)

    assert reason == OK
    assert verified is not None
    assert verified.nonce == "0x" + "02" * 32
    assert verified.payment_id.startswith("0x")


def test_exact_price_rejects_both_short_payment_and_overpayment():
    """`exact` means equality. Accepting an overpayment would silently restore the old
    minimum-price behavior and make the published flat 0.50 USDT offer false."""
    for value in (PRICE - 1, PRICE + 1):
        payment, requirements, resource = _payment(Account.create(), value=value)
        verified, reason = _verify(payment, requirements, resource)
        assert verified is None
        assert "exact amount" in reason


def test_relayer_domain_and_current_authorization_window_are_checked():
    """A signature over another relayer or a future validAfter is not spendable under
    the advertised B402 authorization, even when every visible field matches."""
    other_relayer = "0x" + "22" * 20
    payment, requirements, resource = _payment(
        Account.create(), signing_relayer=other_relayer
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


def test_token_is_a_signed_canonical_authorization_field():
    payment, requirements, resource = _payment(Account.create())
    payment["payload"]["authorization"]["token"] = "0x" + "44" * 20

    verified, reason = _verify(payment, requirements, resource)
    assert verified is None
    assert "token" in reason


def test_b402_validity_window_includes_both_documented_boundaries():
    acct = Account.create()
    payment, requirements, resource = _payment(
        acct, valid_after=100, valid_before=200
    )

    assert _verify(payment, requirements, resource, now=100)[1] == OK
    assert _verify(payment, requirements, resource, now=200)[1] == OK


def test_shared_signer_emits_the_exact_b402_scalar_types_and_domain():
    acct = Account.create()
    challenge = build_challenge(
        get_service("range-doctor"), PAY_TO, resource=RESOURCE
    )
    payment = build_signed_payment(
        acct,
        challenge["accepts"][0],
        challenge["resource"],
        now=100,
        nonce="0x" + "05" * 32,
    )

    authorization = payment["payload"]["authorization"]
    assert authorization == {
        "token": USDT_TOKEN,
        "from": acct.address,
        "to": PAY_TO,
        "value": str(PRICE),
        "validAfter": 100,
        "validBefore": 400,
        "nonce": "0x" + "05" * 32,
    }
    assert _verify(
        payment, challenge["accepts"][0], challenge["resource"], now=100
    )[1] == OK


def test_header_is_read_from_either_supported_spelling():
    blob = base64.b64encode(json.dumps({"a": 1}).encode()).decode()
    assert parse_payment_header({"x-payment": blob}) == {"a": 1}
    assert parse_payment_header({"payment-signature": blob}) == {"a": 1}
    assert parse_payment_header({}) is None


def test_malformed_header_returns_none_rather_than_raising():
    assert parse_payment_header({"x-payment": "not-base64!!"}) is None


def test_facilitator_envelope_selects_b402_without_weakening_generic_v2():
    payment, requirements, _ = _payment(Account.create())

    generic = facilitator_envelope(
        payment, requirements, kind=GENERIC_FACILITATOR
    )
    assert generic == {
        "x402Version": 2,
        "paymentPayload": payment,
        "paymentRequirements": requirements,
    }

    b402 = facilitator_envelope(payment, requirements, kind=B402_FACILITATOR)
    assert b402 == {
        "paymentPayload": {
            "token": USDT_TOKEN,
            "payload": payment["payload"],
        },
        "paymentRequirements": {
            "network": B402_NETWORK,
            "relayerContract": B402_RELAYER,
        },
    }
    assert "x402Version" not in b402
    assert isinstance(
        b402["paymentPayload"]["payload"]["authorization"]["validAfter"], int
    )


def test_facilitator_client_posts_each_b402_call_once(monkeypatch):
    """The dry-run adapter proves the official `/verify` and `/settle` envelope while
    leaving the concrete facilitator URL and live authorization to the owner."""
    payment, requirements, _ = _payment(Account.create())
    envelope = facilitator_envelope(payment, requirements, kind=B402_FACILITATOR)
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
                "network": B402_NETWORK,
            }
        )
        return httpx.Response(200, json=body, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx, "post", fake_post)
    client = FacilitatorClient(
        "https://facilitator.invalid/api/v1", kind=B402_FACILITATOR
    )

    assert client.verify(envelope)["isValid"] is True
    assert client.settle(envelope)["success"] is True
    assert [call[0] for call in calls] == [
        "https://facilitator.invalid/api/v1/verify",
        "https://facilitator.invalid/api/v1/settle",
    ]
    assert all(call[1] == envelope for call in calls)


def test_b402_signature_error_response_is_parsed_without_retry(monkeypatch):
    calls = []

    def fake_post(url, *, json, timeout):
        calls.append((url, json, timeout))
        return httpx.Response(
            401,
            json={
                "error": {
                    "code": "signature_error",
                    "message": "Signature verification failed",
                }
            },
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(httpx, "post", fake_post)
    client = FacilitatorClient(
        "https://facilitator.invalid/api/v1", kind=B402_FACILITATOR
    )

    body = client.verify({"paymentPayload": {}})
    assert body == {
        "isValid": False,
        "invalidReason": "signature_error: Signature verification failed",
    }
    assert len(calls) == 1


def test_preflight_reads_every_prerequisite_and_only_verifies(tmp_path):
    account = Account.create()
    key_file = tmp_path / "payer.key"
    key_file.write_text(account.key.hex(), encoding="ascii")
    web3 = _FakeWeb3(
        balance=PRICE,
        allowance=PRICE,
        whitelisted=True,
        domain=_domain(),
    )
    facilitator = _VerifyOnlyFacilitator(
        {"isValid": True, "payer": account.address}
    )

    report = payment_preflight(
        _preflight_environment(key_file),
        now=100,
        web3=web3,
        facilitator=facilitator,
    )

    assert report["ready"] is True
    assert report["missing"] == []
    assert all(check["ok"] for check in report["checks"].values())
    assert report["checks"]["balance"]["atomic"] == str(PRICE)
    assert report["checks"]["allowance"]["atomic"] == str(PRICE)
    assert report["settlement_attempted"] is False
    assert len(facilitator.calls) == 1
    assert facilitator.calls[0]["paymentRequirements"] == {
        "network": B402_NETWORK,
        "relayerContract": B402_RELAYER,
    }
    rendered = json.dumps(report)
    assert account.key.hex() not in rendered
    assert "signature" not in rendered
    assert "authorization" not in rendered


def test_preflight_names_each_missing_payment_prerequisite(tmp_path):
    account = Account.create()
    key_file = tmp_path / "payer.key"
    key_file.write_text(account.key.hex(), encoding="ascii")
    web3 = _FakeWeb3(
        balance=PRICE - 1,
        allowance=PRICE - 1,
        whitelisted=False,
        domain=_domain(relayer="0x" + "77" * 20),
    )
    facilitator = _VerifyOnlyFacilitator(
        {
            "isValid": False,
            "invalidReason": "payment_verification_error: insufficient allowance",
        }
    )

    report = payment_preflight(
        _preflight_environment(key_file),
        now=100,
        web3=web3,
        facilitator=facilitator,
    )

    assert report["ready"] is False
    assert report["missing"] == [
        "balance",
        "allowance",
        "whitelist",
        "domain",
        "facilitator_verify",
    ]
    assert report["checks"]["facilitator_verify"]["observed"] == (
        "payment_verification_error: insufficient allowance"
    )
