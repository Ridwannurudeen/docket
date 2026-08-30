"""The x402 boundary Docket can prove without sending a transaction.

The local half validates the generic v2 payment, the exact BSC/USDT offer, the live
B402 RelayerV3 authorization domain and type, both ends of its time window, and the
signature. The persistent hire path separately binds the recovered nonce and payment
id to the request and result before it asks a facilitator to settle.

The external half selects either the generic v2 envelope or B402's smaller request
body and posts it once to ``/verify`` and once to ``/settle``. Production settlement
stays disabled unless the owner supplies and enables a facilitator. A response records
that boundary; it does not establish chain finality.
"""

import base64
import json
import os
import re
import secrets
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import httpx
from eth_account import Account
from eth_account.messages import encode_typed_data
from web3 import HTTPProvider, Web3

from .catalogue import USDT_TOKEN, Service, get_service
from .receipts import canonical_hash

OK = "ok"
X402_VERSION = 2
BSC_CHAIN_ID = 56
NETWORK = "eip155:56"
B402_NETWORK = "bsc"
SCHEME = "exact"
MAX_TIMEOUT_SECONDS = 300
ASSET_TRANSFER_METHOD = "b402-relayer"
GENERIC_FACILITATOR = "generic"
B402_FACILITATOR = "b402"
FACILITATOR_KINDS = {GENERIC_FACILITATOR, B402_FACILITATOR}
B402_RELAYER = "0xE1Af7DaEa624bA3B5073f24A6Ea5531434D82d88"
EIP712_DOMAINS = {
    USDT_TOKEN.lower(): {
        "name": "B402",
        "version": "1",
        "chainId": BSC_CHAIN_ID,
        "verifyingContract": B402_RELAYER,
    }
}
TRANSFER_WITH_AUTHORIZATION_TYPES = {
    "TransferWithAuthorization": [
        {"name": "token", "type": "address"},
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
ERC20_PREFLIGHT_ABI = [
    {
        "inputs": [],
        "name": "decimals",
        "outputs": [{"type": "uint8"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [{"type": "address"}],
        "name": "balanceOf",
        "outputs": [{"type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [{"type": "address"}, {"type": "address"}],
        "name": "allowance",
        "outputs": [{"type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
]
B402_PREFLIGHT_ABI = [
    {
        "inputs": [{"type": "address"}],
        "name": "whitelistedTokens",
        "outputs": [{"type": "bool"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "paused",
        "outputs": [{"type": "bool"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "eip712Domain",
        "outputs": [
            {"type": "bytes1"},
            {"type": "string"},
            {"type": "string"},
            {"type": "uint256"},
            {"type": "address"},
            {"type": "bytes32"},
            {"type": "uint256[]"},
        ],
        "stateMutability": "view",
        "type": "function",
    },
]


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON constant {value}")


@dataclass(frozen=True)
class VerifiedPayment:
    payer: str
    nonce: str
    payment_id: str


class PreflightConfigurationError(ValueError):
    """The owner preflight is missing or contradicts required public settings."""


class Facilitator(Protocol):
    def verify(self, envelope: dict) -> dict: ...

    def settle(self, envelope: dict) -> dict: ...


class FacilitatorClient:
    """One-attempt HTTP adapter for a configured facilitator API."""

    def __init__(
        self,
        base_url: str,
        *,
        kind: str = GENERIC_FACILITATOR,
        timeout_seconds: float = 10.0,
    ) -> None:
        if kind not in FACILITATOR_KINDS:
            raise ValueError(
                f"unsupported facilitator kind {kind!r}; expected b402 or generic"
            )
        self.base_url = base_url.rstrip("/")
        self.kind = kind
        self.timeout_seconds = timeout_seconds

    def _post(self, path: str, envelope: dict) -> dict:
        response = httpx.post(
            f"{self.base_url}{path}", json=envelope, timeout=self.timeout_seconds
        )
        try:
            body = response.json()
        except ValueError:
            response.raise_for_status()
            raise ValueError(f"facilitator {path} response must be JSON") from None
        if not isinstance(body, dict):
            raise ValueError(f"facilitator {path} response must be a JSON object")
        if response.is_error:
            error = body.get("error")
            code = error.get("code") if isinstance(error, dict) else None
            message = error.get("message") if isinstance(error, dict) else None
            if self.kind == B402_FACILITATOR and code in {
                "signature_error",
                "nonce_error",
                "payment_verification_error",
                "validation_error",
            }:
                reason = f"{code}: {message}" if message else str(code)
                if path == "/verify":
                    return {"isValid": False, "invalidReason": reason}
                return {"success": False, "errorReason": reason}
            response.raise_for_status()
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
                    "relayerContract": B402_RELAYER,
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
            payload = json.loads(
                base64.b64decode(raw, validate=True),
                parse_constant=_reject_json_constant,
            )
        except (ValueError, TypeError, RecursionError):
            return None
        return payload if isinstance(payload, dict) else None
    return None


def facilitator_envelope(
    payment_payload: dict,
    requirements: dict,
    *,
    kind: str = GENERIC_FACILITATOR,
) -> dict:
    """Build one generic-v2 or B402 facilitator request body."""
    if kind == GENERIC_FACILITATOR:
        return {
            "x402Version": X402_VERSION,
            "paymentPayload": payment_payload,
            "paymentRequirements": requirements,
        }
    if kind == B402_FACILITATOR:
        return {
            "paymentPayload": {
                "token": requirements["asset"],
                "payload": payment_payload["payload"],
            },
            "paymentRequirements": {
                "network": B402_NETWORK,
                "relayerContract": B402_RELAYER,
            },
        }
    raise ValueError(f"unsupported facilitator kind {kind!r}; expected b402 or generic")


def build_signed_payment(
    account,
    requirements: dict,
    resource: dict,
    *,
    now: int | None = None,
    nonce: str | None = None,
) -> dict:
    """Sign the canonical B402 authorization carried in a generic v2 payment header."""
    checked_at = int(time.time()) if now is None else now
    authorization = {
        "token": requirements["asset"],
        "from": account.address,
        "to": requirements["payTo"],
        "value": str(requirements["amount"]),
        "validAfter": checked_at,
        "validBefore": checked_at + int(requirements["maxTimeoutSeconds"]),
        "nonce": nonce or "0x" + secrets.token_hex(32),
    }
    domain = EIP712_DOMAINS.get(str(requirements["asset"]).lower())
    if domain is None:
        raise ValueError(f"unsupported asset domain: {requirements['asset']}")
    signature = Web3.to_hex(
        account.sign_message(
            encode_typed_data(domain, TRANSFER_WITH_AUTHORIZATION_TYPES, authorization)
        ).signature
    )
    return {
        "x402Version": X402_VERSION,
        "resource": resource,
        "accepted": requirements,
        "payload": {"authorization": authorization, "signature": signature},
    }


def verify_payment(
    payment: dict,
    *,
    expected_requirements: dict,
    expected_resource: dict,
    now: int | None = None,
) -> tuple[VerifiedPayment | None, str]:
    """Validate one exact B402 PaymentPayload; first failure wins."""
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
        token = str(authorization["token"])
        recipient = str(authorization["to"])
        value = int(authorization["value"])
        valid_after = int(authorization["validAfter"])
        valid_before = int(authorization["validBefore"])
        nonce = str(authorization["nonce"])
        amount = int(expected_requirements["amount"])
        asset = str(expected_requirements["asset"])
        pay_to = str(expected_requirements["payTo"])
    except (KeyError, TypeError, ValueError):
        return None, "malformed authorization: expected canonical B402 fields"

    if set(authorization) != {
        "token",
        "from",
        "to",
        "value",
        "validAfter",
        "validBefore",
        "nonce",
    }:
        return None, "malformed authorization: fields are not canonical B402"
    if expected_requirements.get("network") != NETWORK:
        return None, f"wrong chain: payment requirements are not for {NETWORK}"
    try:
        max_timeout_seconds = int(expected_requirements["maxTimeoutSeconds"])
    except (KeyError, TypeError, ValueError):
        return (
            None,
            "malformed payment requirements: maxTimeoutSeconds must be an integer",
        )
    if max_timeout_seconds <= 0:
        return (
            None,
            "malformed payment requirements: maxTimeoutSeconds must be positive",
        )
    if recipient.lower() != pay_to.lower():
        return None, f"wrong recipient: authorization names {recipient}, not {pay_to}"
    if token.lower() != asset.lower():
        return None, f"wrong token: authorization names {token}, not {asset}"
    if value != amount:
        return (
            None,
            f"wrong exact amount: authorization names {value}, price is {amount}",
        )
    if NONCE.fullmatch(nonce) is None:
        return None, "malformed nonce: expected one 32-byte hex value"

    checked_at = int(time.time()) if now is None else now
    if valid_after > checked_at:
        return (
            None,
            f"not valid yet: validAfter {valid_after} is after now ({checked_at})",
        )
    if valid_before < checked_at:
        return (
            None,
            f"expired: validBefore {valid_before} is before now ({checked_at})",
        )
    if valid_before > checked_at + max_timeout_seconds:
        return (
            None,
            "authorization expiry exceeds the advertised maxTimeoutSeconds",
        )

    domain_fields = EIP712_DOMAINS.get(asset.lower())
    if domain_fields is None:
        return None, f"unsupported asset domain: {asset}"
    try:
        recovered = Account.recover_message(
            encode_typed_data(
                domain_fields, TRANSFER_WITH_AUTHORIZATION_TYPES, authorization
            ),
            signature=signature,
        )
    except Exception:
        return None, "signature could not be recovered for the advertised B402 domain"
    if recovered.lower() != payer.lower():
        return None, f"signature recovers {recovered}, not the declared payer {payer}"

    try:
        payment_id = canonical_hash(payment)
    except (TypeError, ValueError, RecursionError):
        return None, "malformed payment: identity requires finite JSON values"
    return VerifiedPayment(
        payer=recovered, nonce=nonce.lower(), payment_id=payment_id
    ), OK


def payment_preflight(
    environment,
    *,
    now: int | None = None,
    web3=None,
    facilitator=None,
) -> dict:
    """Read prerequisites and verify one signed authorization without settling it."""
    names = (
        "DOCKET_CANARY_PRIVATE_KEY_FILE",
        "DOCKET_BSC_RPC_URL",
        "DOCKET_FACILITATOR_URL",
        "DOCKET_PAYMENT_TOKEN",
        "DOCKET_B402_RELAYER_CONTRACT",
        "DOCKET_PAY_TO",
        "DOCKET_CANARY_BASE_URL",
    )
    missing_configuration = [name for name in names if not environment.get(name)]
    if missing_configuration:
        raise PreflightConfigurationError(
            "missing preflight configuration: " + ", ".join(missing_configuration)
        )
    if environment.get("DOCKET_FACILITATOR_KIND") != B402_FACILITATOR:
        raise PreflightConfigurationError(
            "DOCKET_FACILITATOR_KIND must be b402 for payment preflight"
        )

    token_address = str(environment["DOCKET_PAYMENT_TOKEN"])
    relayer_address = str(environment["DOCKET_B402_RELAYER_CONTRACT"])
    if token_address.lower() != USDT_TOKEN.lower():
        raise PreflightConfigurationError(
            "DOCKET_PAYMENT_TOKEN must name the supported BSC USDT contract"
        )
    if relayer_address.lower() != B402_RELAYER.lower():
        raise PreflightConfigurationError(
            "DOCKET_B402_RELAYER_CONTRACT must name the live RelayerV3 proxy"
        )

    try:
        private_key = (
            Path(str(environment["DOCKET_CANARY_PRIVATE_KEY_FILE"]))
            .read_text(encoding="ascii")
            .strip()
        )
        account = Account.from_key(private_key)
    except (OSError, UnicodeError, ValueError):
        raise PreflightConfigurationError(
            "DOCKET_CANARY_PRIVATE_KEY_FILE did not contain a usable private key"
        ) from None

    if web3 is None:
        web3 = Web3(
            HTTPProvider(
                str(environment["DOCKET_BSC_RPC_URL"]),
                request_kwargs={"timeout": 10.0},
            )
        )
    token = web3.eth.contract(
        address=web3.to_checksum_address(token_address), abi=ERC20_PREFLIGHT_ABI
    )
    relayer = web3.eth.contract(
        address=web3.to_checksum_address(relayer_address), abi=B402_PREFLIGHT_ABI
    )
    payer = web3.to_checksum_address(account.address)
    pay_to = web3.to_checksum_address(str(environment["DOCKET_PAY_TO"]))
    relayer_checksum = web3.to_checksum_address(relayer_address)

    service = get_service(
        str(environment.get("DOCKET_CANARY_SERVICE_ID") or "range-doctor")
    )
    balance = int(token.functions.balanceOf(payer).call())
    allowance = int(token.functions.allowance(payer, relayer_checksum).call())
    decimals = int(token.functions.decimals().call())
    whitelisted = bool(relayer.functions.whitelistedTokens(token_address).call())
    paused = bool(relayer.functions.paused().call())
    domain = relayer.functions.eip712Domain().call()
    relayer_code = bytes(web3.eth.get_code(relayer_checksum))

    fields = domain[0]
    fields_value = (
        int.from_bytes(fields, "big") if isinstance(fields, bytes) else int(fields)
    )
    observed_domain = {
        "fields": fields_value,
        "name": str(domain[1]),
        "version": str(domain[2]),
        "chainId": int(domain[3]),
        "verifyingContract": str(domain[4]),
    }
    expected_domain = EIP712_DOMAINS[USDT_TOKEN.lower()]
    domain_ok = (
        bool(relayer_code)
        and observed_domain["fields"] == 15
        and observed_domain["name"] == expected_domain["name"]
        and observed_domain["version"] == expected_domain["version"]
        and observed_domain["chainId"] == expected_domain["chainId"]
        and observed_domain["verifyingContract"].lower()
        == str(expected_domain["verifyingContract"]).lower()
        and bytes(domain[5]) == b"\x00" * 32
        and list(domain[6]) == []
    )

    resource_url = (
        str(environment["DOCKET_CANARY_BASE_URL"]).rstrip("/") + f"/hire/{service.id}"
    )
    challenge = build_challenge(service, pay_to, resource=resource_url)
    payment = build_signed_payment(
        account,
        challenge["accepts"][0],
        challenge["resource"],
        now=now,
    )
    envelope = facilitator_envelope(
        payment, challenge["accepts"][0], kind=B402_FACILITATOR
    )
    if facilitator is None:
        facilitator = FacilitatorClient(
            str(environment["DOCKET_FACILITATOR_URL"]), kind=B402_FACILITATOR
        )
    verification = facilitator.verify(envelope)
    facilitator_ok = (
        verification.get("isValid") is True
        and str(verification.get("payer", "")).lower() == account.address.lower()
    )
    facilitator_observed = (
        "accepted"
        if facilitator_ok
        else str(
            verification.get("invalidReason")
            or verification.get("errorReason")
            or "payer or validity mismatch"
        )
    )

    checks = {
        "balance": {
            "ok": decimals == 18 and balance >= service.price_atomic,
            "atomic": str(balance),
            "required_atomic": str(service.price_atomic),
            "decimals": decimals,
        },
        "allowance": {
            "ok": allowance >= service.price_atomic,
            "atomic": str(allowance),
            "required_atomic": str(service.price_atomic),
            "spender": B402_RELAYER,
        },
        "whitelist": {
            "ok": whitelisted and not paused,
            "whitelisted": whitelisted,
            "relayer_paused": paused,
        },
        "domain": {
            "ok": domain_ok,
            "observed": observed_domain,
            "expected": expected_domain,
            "relayer_has_code": bool(relayer_code),
        },
        "facilitator_verify": {
            "ok": facilitator_ok,
            "observed": facilitator_observed,
        },
    }
    missing = [name for name, check in checks.items() if not check["ok"]]
    return {
        "ready": not missing,
        "payer": account.address,
        "price_display": service.price_display,
        "amount_atomic": str(service.price_atomic),
        "token": USDT_TOKEN,
        "relayer": B402_RELAYER,
        "facilitator": str(environment["DOCKET_FACILITATOR_URL"]),
        "checks": checks,
        "missing": missing,
        "settlement_attempted": False,
    }


def main(argv: list[str] | None = None) -> int:
    """Run the owner-facing read-only payment preflight."""
    arguments = sys.argv[1:] if argv is None else argv
    if arguments != ["preflight"]:
        print("usage: python -m docket.hire.x402 preflight")
        return 2
    try:
        report = payment_preflight(os.environ)
    except PreflightConfigurationError as exc:
        print(json.dumps({"ready": False, "error": str(exc)}))
        return 2
    except Exception as exc:
        print(
            json.dumps(
                {
                    "ready": False,
                    "error": f"{type(exc).__name__}: preflight could not complete",
                    "settlement_attempted": False,
                }
            )
        )
        return 2
    print(json.dumps(report, indent=2))
    return 0 if report["ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
