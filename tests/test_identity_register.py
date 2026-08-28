import ast
import json
import re
import tomllib
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from eth_abi import encode
from hexbytes import HexBytes
from web3 import Web3

from docket.hire.catalogue import SERVICES
from docket.identity import register
from docket.marketplace.registry import SERVICES as MARKETPLACE_SERVICES, get_record

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "docket" / "api" / "static" / "agents"
IDENTITY_EVIDENCE = ROOT / "docs" / "erc8004-category-identities.json"
SERVICE_IDS = ("range-doctor", "grid-operator", "yield-router", "health-guard")
SENDER = "0xE4fe23FB57dbb9AC2f685ea29B6b9A1409A0d359"
DOCUMENT_TIME = datetime(2026, 8, 28, 10, 44, 53, tzinfo=timezone.utc)
IDENTITY_FACTS = {
    fact["service_id"]: fact
    for fact in json.loads(IDENTITY_EVIDENCE.read_text(encoding="utf-8"))["services"]
}


def _document_clock() -> datetime:
    return DOCUMENT_TIME


def _signature(entry: dict) -> str:
    return (
        entry["name"] + "(" + ",".join(item["type"] for item in entry["inputs"]) + ")"
    )


class _RegisterCall:
    def __init__(self, token_uri: str) -> None:
        self.token_uri = token_uri
        self.estimated_with = None
        self.built_with = None

    def estimate_gas(self, transaction: dict) -> int:
        self.estimated_with = transaction
        return 163_334

    def build_transaction(self, transaction: dict) -> dict:
        self.built_with = transaction
        return {
            **transaction,
            "to": register.IDENTITY_REGISTRY,
            "value": 0,
            "data": "0xf2c298be" + "00" * 64,
        }


class _Functions:
    def __init__(self) -> None:
        self.call = None

    def register(self, token_uri: str) -> _RegisterCall:
        self.call = _RegisterCall(token_uri)
        return self.call


class _Eth:
    def __init__(self, chain_id: int = 56) -> None:
        self.chain_id = chain_id
        self.gas_price = 50_000_000
        self.functions = _Functions()
        self.contract_args = None
        self.nonce_args = None

    def contract(self, *, address: str, abi: list):
        self.contract_args = (address, abi)
        return type("Contract", (), {"functions": self.functions})()

    def get_transaction_count(self, address: str, block_identifier: str) -> int:
        self.nonce_args = (address, block_identifier)
        return 7


class _W3:
    def __init__(self, chain_id: int = 56) -> None:
        self.eth = _Eth(chain_id)


class _HTTPGet:
    def __init__(self, status_code: int, content: bytes) -> None:
        self.status_code = status_code
        self.content = content
        self.calls = []

    def __call__(self, url: str, *, timeout: float, follow_redirects: bool):
        self.calls.append((url, timeout, follow_redirects))
        return type(
            "Response",
            (),
            {"status_code": self.status_code, "content": self.content},
        )()


class _ExplodingW3:
    def __getattribute__(self, name):
        raise AssertionError(f"a refused CLI action touched Web3 ({name})")


def test_registration_documents_are_generated_from_the_catalogue():
    for service_id in SERVICE_IDS:
        service = SERVICES[service_id]
        record = get_record(service_id)
        agent_id = IDENTITY_FACTS[service_id]["agent_id"]
        generated = register.build_registration_json(
            service, clock=_document_clock, agent_id=agent_id
        )
        assert record is not None
        assert set(generated) == {
            "type",
            "name",
            "description",
            "url",
            "image",
            "active",
            "version",
            "agent_type",
            "categories",
            "tags",
            "skills",
            "services",
            "hireUrl",
            "x402Support",
            "supportedTrust",
            "registrations",
            "documentation",
            "limitations",
            "updatedAt",
        }
        assert generated["name"] == service.name
        assert generated["description"] == service.what_you_get
        assert generated["url"] == f"https://docket.gudman.xyz/services/{service.id}"
        assert generated["image"].startswith("data:image/svg+xml;base64,")
        assert generated["active"] is True
        assert generated["version"] == "0.1.0"
        assert generated["agent_type"] == record.category.value
        assert generated["categories"] == [record.category.value]
        assert generated["tags"] == [service.id, "bsc", "erc-8004"]
        assert generated["skills"] == [
            {
                "id": service.id,
                "name": service.name,
                "description": service.what_you_get,
            }
        ]
        assert generated["services"] == [
            {
                "name": service.id,
                "description": service.what_you_get,
                "protocol": "Web",
                "endpoint": f"https://docket.gudman.xyz/services/{service.id}",
            }
        ]
        assert generated["hireUrl"] == f"https://docket.gudman.xyz/hire/{service.id}"
        assert generated["x402Support"] is True
        assert generated["supportedTrust"] == ["reputation"]
        assert generated["registrations"] == [
            {
                "agentId": agent_id,
                "agentRegistry": (
                    "eip155:56:0x8004a169fb4a3325136eb29fa0ceb6d2e539a432"
                ),
            }
        ]
        assert generated["documentation"] == "https://docket.gudman.xyz/llms.txt"
        assert generated["limitations"] == record.limitations
        assert generated["updatedAt"] == "2026-08-28T10:44:53Z"

        document = register.render_registration_document(
            service, clock=_document_clock, agent_id=agent_id
        )
        assert document == register.render_registration_document(
            service, clock=_document_clock, agent_id=agent_id
        )
        assert (
            STATIC.joinpath(f"{service_id}.registration.json").read_bytes() == document
        )


def test_registration_document_adds_the_minted_identity_without_changing_its_url():
    service = SERVICES["range-doctor"]
    generated = register.build_registration_json(
        service, clock=_document_clock, agent_id=311_253
    )
    assert generated["url"] == "https://docket.gudman.xyz/services/range-doctor"
    assert generated["registrations"] == [
        {
            "agentId": 311_253,
            "agentRegistry": ("eip155:56:0x8004a169fb4a3325136eb29fa0ceb6d2e539a432"),
        }
    ]


def test_bound_service_identities_match_committed_chain_evidence():
    evidence = json.loads(IDENTITY_EVIDENCE.read_text(encoding="utf-8"))
    facts = {fact["service_id"]: fact for fact in evidence["services"]}
    solvent = json.loads(
        (ROOT / "docket" / "advantage" / "experiments" / "02-trading.json").read_text(
            encoding="utf-8"
        )
    )

    assert evidence["chain_id"] == 56
    assert evidence["registry"] == register.IDENTITY_REGISTRY_ID
    assert set(facts) == set(SERVICE_IDS)

    for service_id, record in MARKETPLACE_SERVICES.items():
        if record.agent_id is None:
            continue
        assert record.agent_id == record.agent_id.lower()
        assert re.fullmatch(r"56:0x[0-9a-f]{40}:[0-9]+", record.agent_id)
        chain_id, registry, token_id = record.agent_id.split(":")
        assert chain_id == str(evidence["chain_id"])
        assert registry == evidence["registry"]

        if service_id == "solvent-signal":
            recorded_agent = solvent["agent_arm"]["output"]["result"]["agent"]
            assert token_id == recorded_agent["erc8004_agent_id"]
            assert record.registration_uri is None
            continue

        fact = facts[service_id]
        assert int(token_id) == fact["agent_id"]
        assert fact["owner"] == evidence["owner"]
        assert re.fullmatch(r"0x[0-9a-f]{40}", fact["owner"])
        assert fact["mint_block"] > 0
        assert re.fullmatch(r"0x[0-9a-f]{64}", fact["transaction_hash"])
        assert record.registration_uri == fact["token_uri"]
        assert fact["token_uri"].endswith(f"/registrations/{service_id}.json")

        document = json.loads(
            STATIC.joinpath(f"{service_id}.registration.json").read_text(
                encoding="utf-8"
            )
        )
        assert document["registrations"] == [
            {
                "agentId": fact["agent_id"],
                "agentRegistry": (
                    f"eip155:{evidence['chain_id']}:{evidence['registry']}"
                ),
            }
        ]


def test_identity_abi_matches_the_observed_contract_surface():
    artifact = json.loads((ROOT / "abis" / "IdentityRegistry.json").read_text())
    functions = {
        _signature(entry) for entry in artifact if entry.get("type") == "function"
    }
    events = {_signature(entry) for entry in artifact if entry.get("type") == "event"}
    assert functions == {"register(string)", "tokenURI(uint256)", "ownerOf(uint256)"}
    assert events == {
        "Transfer(address,address,uint256)",
        "MetadataUpdate(uint256)",
        "Registered(uint256,string,address)",
        "MetadataSet(uint256,string,string,bytes)",
    }
    assert register.IDENTITY_ABI == artifact


def test_build_register_tx_estimates_and_builds_an_unsigned_bsc_transaction():
    w3 = _W3()
    token_uri = "https://docket.gudman.xyz/registrations/range-doctor.json"
    tx = register.build_register_tx(w3, token_uri=token_uri, from_address=SENDER)

    call = w3.eth.functions.call
    assert w3.eth.contract_args == (register.IDENTITY_REGISTRY, register.IDENTITY_ABI)
    assert call.token_uri == token_uri
    assert call.estimated_with == {"from": SENDER}
    assert call.built_with == {
        "from": SENDER,
        "nonce": 7,
        "chainId": 56,
        "gas": 163_334,
        "gasPrice": 50_000_000,
    }
    assert w3.eth.nonce_args == (SENDER, "pending")
    assert tx["data"].startswith("0xf2c298be")
    assert tx["to"] == register.IDENTITY_REGISTRY

    with pytest.raises(ValueError, match="BSC mainnet"):
        register.build_register_tx(
            _W3(chain_id=97), token_uri=token_uri, from_address=SENDER
        )


def test_decode_registration_extracts_the_registered_event_and_refuses_absence():
    agent_id = 136_384
    registered = {
        "address": register.IDENTITY_REGISTRY,
        "topics": [
            HexBytes(Web3.keccak(text="Registered(uint256,string,address)")),
            HexBytes(agent_id.to_bytes(32, "big")),
            HexBytes(bytes.fromhex("00" * 12 + SENDER[2:])),
        ],
        "data": HexBytes(encode(["string"], ["https://solvent.gudman.xyz"])),
    }
    decoded = register.decode_registration(
        {
            "logs": [
                {"address": register.IDENTITY_REGISTRY, "topics": [], "data": b""},
                registered,
            ]
        }
    )
    assert decoded == {
        "agent_id": agent_id,
        "token_uri": "https://solvent.gudman.xyz",
        "owner": SENDER,
    }

    with pytest.raises(ValueError, match="Registered event"):
        register.decode_registration({"logs": []})


def test_bind_agent_id_uses_the_marketplace_canonical_form():
    assert register.bind_agent_id("range-doctor", 136_384) == (
        "56:0x8004a169fb4a3325136eb29fa0ceb6d2e539a432:136384"
    )
    with pytest.raises(ValueError, match="category service"):
        register.bind_agent_id("solvent-signal", 136_384)


def test_plan_cli_prints_an_unsigned_costed_plan_and_refuses_other_actions(capsys):
    w3 = _W3()
    committed = STATIC.joinpath("range-doctor.registration.json").read_bytes()
    http_get = _HTTPGet(200, committed)
    result = register.main(
        ["plan", "--service", "range-doctor", "--from", SENDER],
        w3=w3,
        http_get=http_get,
    )
    assert result == 0
    output = json.loads(capsys.readouterr().out)
    assert output["registration"] == register.build_registration_json(
        SERVICES["range-doctor"], clock=_document_clock, agent_id=311_253
    )
    assert output["token_uri"] == (
        "https://docket.gudman.xyz/registrations/range-doctor.json"
    )
    assert output["unsigned_transaction"]["data"].startswith("0xf2c298be")
    assert output["gas_estimate"] == 163_334
    assert output["gas_price_wei"] == 50_000_000
    assert output["bnb_cost"] == format(
        Decimal(163_334 * 50_000_000) / Decimal(10**18), "f"
    )
    assert http_get.calls == [
        ("https://docket.gudman.xyz/registrations/range-doctor.json", 30.0, False)
    ]

    with pytest.raises(SystemExit):
        register.main(
            ["send", "--service", "range-doctor", "--from", SENDER],
            w3=_ExplodingW3(),
        )
    with pytest.raises(SystemExit):
        register.main(
            [
                "plan",
                "--service",
                "range-doctor",
                "--from",
                SENDER,
                "--sign",
            ],
            w3=_ExplodingW3(),
        )


@pytest.mark.parametrize(
    ("status_code", "alter_body", "message"),
    ((404, False, "HTTP 404"), (200, True, "SHA-256")),
)
def test_plan_preflight_refuses_missing_or_changed_documents_before_web3(
    status_code, alter_body, message, capsys
):
    committed = STATIC.joinpath("range-doctor.registration.json").read_bytes()
    body = committed + b" " if alter_body else committed
    with pytest.raises(ValueError, match=message):
        register.main(
            ["plan", "--service", "range-doctor", "--from", SENDER],
            w3=_ExplodingW3(),
            http_get=_HTTPGet(status_code, body),
        )
    assert capsys.readouterr().out == ""


def test_identity_package_and_static_documents_are_declared_for_the_wheel():
    with (ROOT / "pyproject.toml").open("rb") as handle:
        project = tomllib.load(handle)["tool"]["setuptools"]
    assert "docket.identity" in project["packages"]
    assert "static/agents/*.registration.json" in project["package-data"]["docket.api"]


def test_identity_module_has_no_signing_or_broadcast_surface():
    tree = ast.parse(Path(register.__file__).read_text(encoding="utf-8"))
    forbidden = {
        "sign_transaction",
        "send_transaction",
        "send_raw_transaction",
        "transact",
    }
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            assert node.module != "eth_account"
        if isinstance(node, ast.Import):
            assert all(alias.name != "eth_account" for alias in node.names)
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Attribute):
                assert node.func.attr not in forbidden
            if isinstance(node.func, ast.Name):
                assert node.func.id not in forbidden
