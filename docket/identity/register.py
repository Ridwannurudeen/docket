"""Build ERC-8004 registration documents and unsigned BSC transactions.

This module has one command: ``plan``. It reads BSC state to estimate a registration
and prints the transaction fields for the owner. It has no transaction-submission path.
"""

import argparse
import json
from decimal import Decimal

from eth_abi import decode
from hexbytes import HexBytes
from web3 import HTTPProvider, Web3

from ..hire.catalogue import Service, get_service

CHAIN_ID = 56
RPC_URL = "https://bsc-dataseed.bnbchain.org"
IDENTITY_REGISTRY = Web3.to_checksum_address(
    "0x8004A169FB4a3325136EB29fA0ceB6D2e539a432"
)
IDENTITY_REGISTRY_ID = IDENTITY_REGISTRY.lower()
REGISTRATION_BASE_URL = "https://docket.gudman.xyz/agents"
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


def build_registration_json(service: Service) -> dict:
    if service.id not in CATEGORY_SERVICE_IDS:
        raise ValueError(f"{service.id!r} is not a category service")
    endpoint = f"https://docket.gudman.xyz/hire/{service.id}"
    return {
        "type": "https://eips.ethereum.org/EIPS/eip-8004#registration-v1",
        "name": service.name,
        "description": service.what_you_get,
        "services": [
            {
                "name": service.id,
                "description": service.what_you_get,
                "protocol": "Web",
                "endpoint": endpoint,
            }
        ],
        "x402Support": True,
    }


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


def main(argv: list[str] | None = None, *, w3=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    plan = commands.add_parser("plan", help="print one unsigned registration plan")
    plan.add_argument("--service", choices=CATEGORY_SERVICE_IDS, required=True)
    plan.add_argument("--from", dest="from_address", required=True)
    args = parser.parse_args(argv)

    service = get_service(args.service)
    if service is None:
        raise ValueError(f"unknown service {args.service!r}")
    token_uri = f"{REGISTRATION_BASE_URL}/{service.id}.registration.json"
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
                "registration": build_registration_json(service),
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
