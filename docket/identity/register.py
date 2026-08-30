"""Build ERC-8004 registration documents and unsigned BSC transactions.

This module has one command: ``plan``. It reads BSC state to estimate a registration
and prints the transaction fields for the owner. It has no transaction-submission path.
"""

import argparse
import hashlib
import json
import tomllib
from collections.abc import Callable
from datetime import datetime, timezone
from decimal import Decimal
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

import httpx
from eth_abi import decode
from hexbytes import HexBytes
from web3 import HTTPProvider, Web3

from ..hire.catalogue import Service, get_service
from ..marketplace.registry import get_record

CHAIN_ID = 56
RPC_URL = "https://bsc-dataseed.bnbchain.org"
IDENTITY_REGISTRY = Web3.to_checksum_address(
    "0x8004A169FB4a3325136EB29fA0ceB6D2e539a432"
)
IDENTITY_REGISTRY_ID = IDENTITY_REGISTRY.lower()
REGISTRATION_BASE_URL = "https://docket.gudman.xyz/registrations"
REGISTRATION_DOCUMENT_DIR = (
    Path(__file__).resolve().parents[1] / "api" / "static" / "agents"
)
REGISTRATION_IMAGE = (
    "data:image/svg+xml;base64,"
    "PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHZpZXdCb3g9IjAgMCAxMjAgMTIw"
    "Ij48cmVjdCB3aWR0aD0iMTIwIiBoZWlnaHQ9IjEyMCIgcng9IjE4IiBmaWxsPSIjMGIxMjIwIi8+PHJl"
    "Y3QgeD0iMjQiIHk9IjI0IiB3aWR0aD0iNzIiIGhlaWdodD0iNzIiIHJ4PSIxMiIgZmlsbD0ibm9uZSIg"
    "c3Ryb2tlPSIjZjRmMWU4IiBzdHJva2Utd2lkdGg9IjgiLz48cGF0aCBkPSJNNDAgNDhoNDBNNDAgNjRo"
    "MjQiIHN0cm9rZT0iI2Y0ZjFlOCIgc3Ryb2tlLXdpZHRoPSI4IiBzdHJva2UtbGluZWNhcD0icm91bmQi"
    "Lz48Y2lyY2xlIGN4PSI3NiIgY3k9Ijc0IiByPSI3IiBmaWxsPSIjZjRiODYwIi8+PC9zdmc+"
)
CATEGORY_SERVICE_IDS = (
    "range-doctor",
    "grid-operator",
    "yield-router",
    "health-guard",
)

# The top-level abis/ directory is not installed with the wheel. This fragment is kept
# byte-for-byte equivalent to abis/IdentityRegistry.json by test_identity_register.py.
IDENTITY_ABI = [
    {
        "inputs": [{"internalType": "string", "name": "agentURI", "type": "string"}],
        "name": "register",
        "outputs": [{"internalType": "uint256", "name": "agentId", "type": "uint256"}],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "inputs": [{"internalType": "uint256", "name": "tokenId", "type": "uint256"}],
        "name": "tokenURI",
        "outputs": [{"internalType": "string", "name": "", "type": "string"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [{"internalType": "uint256", "name": "tokenId", "type": "uint256"}],
        "name": "ownerOf",
        "outputs": [{"internalType": "address", "name": "", "type": "address"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "anonymous": False,
        "inputs": [
            {
                "indexed": True,
                "internalType": "address",
                "name": "from",
                "type": "address",
            },
            {
                "indexed": True,
                "internalType": "address",
                "name": "to",
                "type": "address",
            },
            {
                "indexed": True,
                "internalType": "uint256",
                "name": "tokenId",
                "type": "uint256",
            },
        ],
        "name": "Transfer",
        "type": "event",
    },
    {
        "anonymous": False,
        "inputs": [
            {
                "indexed": False,
                "internalType": "uint256",
                "name": "_tokenId",
                "type": "uint256",
            }
        ],
        "name": "MetadataUpdate",
        "type": "event",
    },
    {
        "anonymous": False,
        "inputs": [
            {
                "indexed": True,
                "internalType": "uint256",
                "name": "agentId",
                "type": "uint256",
            },
            {
                "indexed": False,
                "internalType": "string",
                "name": "agentURI",
                "type": "string",
            },
            {
                "indexed": True,
                "internalType": "address",
                "name": "owner",
                "type": "address",
            },
        ],
        "name": "Registered",
        "type": "event",
    },
    {
        "anonymous": False,
        "inputs": [
            {
                "indexed": True,
                "internalType": "uint256",
                "name": "agentId",
                "type": "uint256",
            },
            {
                "indexed": True,
                "internalType": "string",
                "name": "indexedMetadataKey",
                "type": "string",
            },
            {
                "indexed": False,
                "internalType": "string",
                "name": "metadataKey",
                "type": "string",
            },
            {
                "indexed": False,
                "internalType": "bytes",
                "name": "metadataValue",
                "type": "bytes",
            },
        ],
        "name": "MetadataSet",
        "type": "event",
    },
]

REGISTERED_TOPIC = Web3.keccak(text="Registered(uint256,string,address)")


def build_registration_json(
    service: Service,
    *,
    clock: Callable[[], datetime],
    agent_id: int | None = None,
) -> dict:
    if service.id not in CATEGORY_SERVICE_IDS:
        raise ValueError(f"{service.id!r} is not a category service")
    record = get_record(service.id)
    if record is None or record.category is None:
        raise ValueError(f"{service.id!r} has no marketplace category record")
    updated_at = clock()
    if updated_at.tzinfo is None or updated_at.utcoffset() is None:
        raise ValueError(
            "registration document clock must return a timezone-aware datetime"
        )
    try:
        project_version = version("docket")
    except PackageNotFoundError:
        with (
            Path(__file__)
            .resolve()
            .parents[2]
            .joinpath("pyproject.toml")
            .open("rb") as handle
        ):
            project_version = tomllib.load(handle)["project"]["version"]
    registrations = []
    if agent_id is not None:
        bind_agent_id(service.id, agent_id)
        registrations.append(
            {
                "agentId": agent_id,
                "agentRegistry": f"eip155:{CHAIN_ID}:{IDENTITY_REGISTRY_ID}",
            }
        )
    service_url = f"https://docket.gudman.xyz/services/{service.id}"
    return {
        "type": "https://eips.ethereum.org/EIPS/eip-8004#registration-v1",
        "name": service.name,
        "description": service.what_you_get,
        "url": service_url,
        "image": REGISTRATION_IMAGE,
        "active": True,
        "version": project_version,
        "agent_type": record.category.value,
        "categories": [record.category.value],
        "tags": [service.id, "bsc", "erc-8004"],
        "skills": [
            {
                "id": service.id,
                "name": service.name,
                "description": service.what_you_get,
            }
        ],
        "services": [
            {
                "name": service.id,
                "description": service.what_you_get,
                "protocol": "Web",
                "endpoint": service_url,
            }
        ],
        "hireUrl": f"https://docket.gudman.xyz/hire/{service.id}",
        "x402Support": True,
        "supportedTrust": ["reputation"],
        "registrations": registrations,
        "documentation": "https://docket.gudman.xyz/llms.txt",
        "limitations": record.limitations,
        "updatedAt": (
            updated_at.astimezone(timezone.utc)
            .isoformat(timespec="seconds")
            .replace("+00:00", "Z")
        ),
    }


def render_registration_document(
    service: Service,
    *,
    clock: Callable[[], datetime],
    agent_id: int | None = None,
) -> bytes:
    document = build_registration_json(service, clock=clock, agent_id=agent_id)
    return (
        json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode()


def preflight_registration(
    token_uri: str,
    committed_document: bytes,
    *,
    http_get=httpx.get,
) -> None:
    try:
        response = http_get(token_uri, timeout=30.0, follow_redirects=False)
    except httpx.HTTPError as exc:
        raise ValueError(
            f"registration preflight refused: GET {token_uri} failed: {exc}"
        ) from exc
    if response.status_code != 200:
        raise ValueError(
            f"registration preflight refused: GET {token_uri} returned HTTP "
            f"{response.status_code}, not 200"
        )
    committed_sha256 = hashlib.sha256(committed_document).hexdigest()
    served_sha256 = hashlib.sha256(response.content).hexdigest()
    if served_sha256 != committed_sha256:
        raise ValueError(
            f"registration preflight refused: GET {token_uri} returned SHA-256 "
            f"{served_sha256}, not committed SHA-256 {committed_sha256}"
        )


def build_register_tx(w3, *, token_uri: str, from_address: str) -> dict:
    if w3.eth.chain_id != CHAIN_ID:
        raise ValueError(f"registration planning requires BSC mainnet chain {CHAIN_ID}")
    sender = Web3.to_checksum_address(from_address)
    registry = w3.eth.contract(address=IDENTITY_REGISTRY, abi=IDENTITY_ABI)
    registration = registry.functions.register(token_uri)
    gas = registration.estimate_gas({"from": sender})
    gas_price = int(w3.eth.gas_price)
    nonce = w3.eth.get_transaction_count(sender, "pending")
    return dict(
        registration.build_transaction(
            {
                "from": sender,
                "nonce": nonce,
                "chainId": CHAIN_ID,
                "gas": gas,
                "gasPrice": gas_price,
            }
        )
    )


def decode_registration(receipt) -> dict:
    for log in receipt.get("logs", []):
        topics = log["topics"]
        if (
            str(log["address"]).lower() != IDENTITY_REGISTRY_ID
            or len(topics) != 3
            or HexBytes(topics[0]) != REGISTERED_TOPIC
        ):
            continue
        agent_id = int.from_bytes(HexBytes(topics[1]), "big")
        owner = Web3.to_checksum_address("0x" + HexBytes(topics[2])[-20:].hex())
        (token_uri,) = decode(["string"], HexBytes(log["data"]))
        return {"agent_id": agent_id, "token_uri": token_uri, "owner": owner}
    raise ValueError("receipt contains no IdentityRegistry Registered event")


def bind_agent_id(service_id: str, agent_id: int) -> str:
    if service_id not in CATEGORY_SERVICE_IDS:
        raise ValueError(f"{service_id!r} is not a category service")
    if not isinstance(agent_id, int) or isinstance(agent_id, bool) or agent_id < 0:
        raise ValueError("agent_id must be a non-negative integer")
    return f"{CHAIN_ID}:{IDENTITY_REGISTRY_ID}:{agent_id}"


def main(argv: list[str] | None = None, *, w3=None, http_get=httpx.get) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    plan = commands.add_parser("plan", help="print one unsigned registration plan")
    plan.add_argument("--service", choices=CATEGORY_SERVICE_IDS, required=True)
    plan.add_argument("--from", dest="from_address", required=True)
    args = parser.parse_args(argv)

    service = get_service(args.service)
    if service is None:
        raise ValueError(f"unknown service {args.service!r}")
    token_uri = f"{REGISTRATION_BASE_URL}/{service.id}.json"
    document = REGISTRATION_DOCUMENT_DIR.joinpath(
        f"{service.id}.registration.json"
    ).read_bytes()
    preflight_registration(token_uri, document, http_get=http_get)
    session = (
        w3
        if w3 is not None
        else Web3(HTTPProvider(RPC_URL, request_kwargs={"timeout": 30}))
    )
    transaction = build_register_tx(
        session, token_uri=token_uri, from_address=args.from_address
    )
    unsigned = {
        key: (
            value.hex()
            if isinstance(value, HexBytes)
            else "0x" + value.hex()
            if isinstance(value, bytes)
            else value
        )
        for key, value in transaction.items()
    }
    gas = int(transaction["gas"])
    gas_price = int(transaction["gasPrice"])
    print(
        json.dumps(
            {
                "service_id": service.id,
                "registration": json.loads(document),
                "token_uri": token_uri,
                "unsigned_transaction": unsigned,
                "gas_estimate": gas,
                "gas_price_wei": gas_price,
                "bnb_cost": format(Decimal(gas * gas_price) / Decimal(10**18), "f"),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
