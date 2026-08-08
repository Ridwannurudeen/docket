import time

from eth_account import Account
from eth_account.messages import encode_typed_data

from docket.hire.catalogue import get_service
from docket.hire.x402 import OK, build_challenge, parse_payment_header, verify_authorization

PAY_TO = "0x" + "11" * 20
ASSET = "0xcE24439F2D9C6a2289F741120FE202248B666666"


def _signed(acct, *, to=PAY_TO, value=10**16, valid_before=None, chain_id=56):
    domain = {
        "name": "United Stables",
        "version": "1",
        "chainId": chain_id,
        "verifyingContract": ASSET,
    }
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
        "validBefore": valid_before or int(time.time()) + 300,
        "nonce": b"\x02" * 32,
    }
    sig = acct.sign_message(encode_typed_data(domain, types, msg))
    return {
        "domain": domain,
        "types": types,
        "message": {**msg, "nonce": "0x" + "02" * 32},
        "signature": sig.signature.hex(),
    }


def test_challenge_declares_the_verified_bsc_dialect():
    ch = build_challenge(
        get_service("range-doctor"), PAY_TO, resource="https://d/hire/range-doctor"
    )
    assert ch["x402Version"] == 2
    offer = ch["accepts"][0]
    assert offer["scheme"] == "exact"
    assert offer["network"] == "eip155:56"
    assert offer["payTo"] == PAY_TO
    assert offer["maxTimeoutSeconds"] <= 480  # Studio signers refuse longer windows
    assert "assetTransferMethod" in offer["extra"]


def test_valid_authorization_verifies():
    acct = Account.create()
    ok, reason = verify_authorization(_signed(acct), expected_to=PAY_TO, expected_value=10**16)
    assert ok is True and reason == OK


def test_wrong_recipient_is_rejected():
    acct = Account.create()
    auth = _signed(acct, to="0x" + "22" * 20)
    ok, reason = verify_authorization(auth, expected_to=PAY_TO, expected_value=10**16)
    assert ok is False and "recipient" in reason


def test_short_payment_is_rejected():
    acct = Account.create()
    auth = _signed(acct, value=1)
    ok, reason = verify_authorization(auth, expected_to=PAY_TO, expected_value=10**16)
    assert ok is False and "amount" in reason


def test_expired_authorization_is_rejected():
    acct = Account.create()
    auth = _signed(acct, valid_before=int(time.time()) - 10)
    ok, reason = verify_authorization(auth, expected_to=PAY_TO, expected_value=10**16)
    assert ok is False and "expired" in reason


def test_wrong_chain_is_rejected():
    """A signature valid on another chain must not buy anything here."""
    acct = Account.create()
    auth = _signed(acct, chain_id=1)
    ok, reason = verify_authorization(auth, expected_to=PAY_TO, expected_value=10**16)
    assert ok is False and "chain" in reason


def test_tampered_message_fails_recovery():
    acct = Account.create()
    auth = _signed(acct)
    auth["message"]["value"] = 10**18  # inflate after signing
    ok, reason = verify_authorization(auth, expected_to=PAY_TO, expected_value=10**18)
    assert ok is False


def test_header_is_read_from_either_spelling():
    import base64
    import json as _json

    blob = base64.b64encode(_json.dumps({"a": 1}).encode()).decode()
    assert parse_payment_header({"x-payment": blob}) == {"a": 1}
    assert parse_payment_header({"payment-signature": blob}) == {"a": 1}
    assert parse_payment_header({}) is None


def test_malformed_header_returns_none_rather_than_raising():
    assert parse_payment_header({"x-payment": "not-base64!!"}) is None
