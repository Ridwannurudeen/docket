"""The x402 v2 boundary Docket can prove without sending a transaction.

The local half validates the current generic v2 envelope, the exact BSC/$U offer,
the canonical EIP-3009 authorization domain and type, both ends of its time window,
and the signature. The persistent hire path separately binds the recovered nonce and
payment id to the request and result before it asks a facilitator to settle.

The external half is deliberately smaller than a compatibility claim. The adapter
posts the protocol's v2 request envelope once to ``/verify`` and once to ``/settle``.
No concrete facilitator URL is built in, and production settlement stays disabled
unless the owner supplies and enables one. Fixture responses prove Docket's state
machine; they do not prove a particular facilitator accepts $U, has funds, submitted
the authorization on chain, or that its reported transaction reached finality.
"""

import base64
import json
import re
import time
from dataclasses import dataclass
from typing import Protocol

import httpx
from eth_account import Account
from eth_account.messages import encode_typed_data

from .catalogue import U_TOKEN, Service
from .receipts import canonical_hash

OK = "ok"
X402_VERSION = 2
BSC_CHAIN_ID = 56
NETWORK = "eip155:56"
SCHEME = "exact"
MAX_TIMEOUT_SECONDS = 300
ASSET_TRANSFER_METHOD = "eip3009"
EIP712_DOMAINS = {U_TOKEN.lower(): {"name": "United Stables", "version": "1"}}
EIP3009_TYPES = {
    "TransferWithAuthorization": [
        {"name": "from", "type": "address"},
        {"name": "to", "type": "address"},
        {"name": "value", "type": "uint256"},
        {"name": "validAfter", "type": "uint256"},
        {"name": "validBefore", "type": "uint256"},
        {"name": "nonce", "type": "bytes32"},
    ]
}
HEADER_NAMES = ("x-payment", "payment-signature")
NONCE = re.compile(r"0x[0-9a-fA-F]{64}")


@dataclass(frozen=True)
class VerifiedPayment:
    payer: str
    nonce: str
    payment_id: str


class Facilitator(Protocol):
    def verify(self, envelope: dict) -> dict: ...

    def settle(self, envelope: dict) -> dict: ...


class FacilitatorClient:
    """One-attempt HTTP adapter for the generic current x402 v2 facilitator API."""

    def __init__(self, base_url: str, *, timeout_seconds: float = 10.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def _post(self, path: str, envelope: dict) -> dict:
        response = httpx.post(
            f"{self.base_url}{path}", json=envelope, timeout=self.timeout_seconds
        )
        response.raise_for_status()
        body = response.json()
        if not isinstance(body, dict):
            raise ValueError(f"facilitator {path} response must be a JSON object")
        return body

    def verify(self, envelope: dict) -> dict:
        return self._post("/verify", envelope)

    def settle(self, envelope: dict) -> dict:
        return self._post("/settle", envelope)


def build_challenge(service: Service, pay_to: str, *, resource: str) -> dict:
    """Publish the current v2 resource and exact PaymentRequirements shapes."""
    return {
        "x402Version": X402_VERSION,
        "resource": {
            "url": resource,
            "description": service.what_you_get,
            "mimeType": "application/json",
        },
        "accepts": [
            {
                "scheme": SCHEME,
                "network": NETWORK,
                "amount": str(service.price_atomic),
                "asset": service.asset,
                "payTo": pay_to,
                "maxTimeoutSeconds": MAX_TIMEOUT_SECONDS,
                "extra": {
                    "assetTransferMethod": ASSET_TRANSFER_METHOD,
                    **EIP712_DOMAINS.get(service.asset.lower(), {}),
                },
            }
        ],
    }


def parse_payment_header(headers) -> dict | None:
    """Return an attacker-controlled payment object, or ``None`` when it is malformed."""
    for name in HEADER_NAMES:
        raw = headers.get(name)
        if not raw:
            continue
        try:
            payload = json.loads(base64.b64decode(raw, validate=True))
        except (ValueError, TypeError):
            return None
        return payload if isinstance(payload, dict) else None
    return None


def facilitator_envelope(payment_payload: dict, requirements: dict) -> dict:
    """The request body shared by the current generic ``/verify`` and ``/settle`` APIs."""
    return {
        "x402Version": X402_VERSION,
        "paymentPayload": payment_payload,
        "paymentRequirements": requirements,
    }


def verify_payment(
    payment: dict,
    *,
    expected_requirements: dict,
    expected_resource: dict,
    now: int | None = None,
) -> tuple[VerifiedPayment | None, str]:
    """Validate one exact EIP-3009 PaymentPayload; first failure wins."""
    try:
        version = payment["x402Version"]
        resource = payment["resource"]
        accepted = payment["accepted"]
        payload = payment["payload"]
        signature = payload["signature"]
        authorization = payload["authorization"]
    except (KeyError, TypeError):
        return (
            None,
            "malformed payment: expected v2 resource, accepted and payload fields",
        )

    if version != X402_VERSION:
        return None, f"wrong x402 version: expected {X402_VERSION}"
    if resource != expected_resource:
        return None, "wrong resource: payment does not name this hire endpoint"
    if accepted != expected_requirements:
        return (
            None,
            "wrong payment requirements: offer, asset, amount or recipient changed",
        )

    try:
        payer = str(authorization["from"])
        recipient = str(authorization["to"])
        value = int(authorization["value"])
        valid_after = int(authorization["validAfter"])
        valid_before = int(authorization["validBefore"])
        nonce = str(authorization["nonce"])
        amount = int(expected_requirements["amount"])
        asset = str(expected_requirements["asset"])
        pay_to = str(expected_requirements["payTo"])
    except (KeyError, TypeError, ValueError):
        return None, "malformed authorization: expected canonical EIP-3009 fields"

    if set(authorization) != {
        "from",
        "to",
        "value",
        "validAfter",
        "validBefore",
        "nonce",
    }:
        return None, "malformed authorization: fields are not canonical EIP-3009"
    if expected_requirements.get("network") != NETWORK:
        return None, f"wrong chain: payment requirements are not for {NETWORK}"
    if recipient.lower() != pay_to.lower():
        return None, f"wrong recipient: authorization names {recipient}, not {pay_to}"
    if value != amount:
        return (
            None,
            f"wrong exact amount: authorization names {value}, price is {amount}",
        )
    if NONCE.fullmatch(nonce) is None:
        return None, "malformed nonce: expected one 32-byte hex value"

    checked_at = int(time.time()) if now is None else now
    if valid_after >= checked_at:
        return (
            None,
            f"not valid yet: validAfter {valid_after} is not before now ({checked_at})",
        )
    if valid_before <= checked_at:
        return (
            None,
            f"expired: validBefore {valid_before} is not after now ({checked_at})",
        )

    domain_fields = EIP712_DOMAINS.get(asset.lower())
    if domain_fields is None:
        return None, f"unsupported asset domain: {asset}"
    domain = {
        **domain_fields,
        "chainId": BSC_CHAIN_ID,
        "verifyingContract": asset,
    }
    try:
        recovered = Account.recover_message(
            encode_typed_data(domain, EIP3009_TYPES, authorization),
            signature=signature,
        )
    except Exception:
        return None, "signature could not be recovered for the advertised $U domain"
    if recovered.lower() != payer.lower():
        return None, f"signature recovers {recovered}, not the declared payer {payer}"

    return (
        VerifiedPayment(
            payer=recovered,
            nonce=nonce.lower(),
            payment_id=canonical_hash(payment),
        ),
        OK,
    )
