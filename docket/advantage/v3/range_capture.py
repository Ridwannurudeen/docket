"""Capture a registered enumerable Range frame from one archive RPC.

The collector has one endpoint, one attempt per JSON-RPC request and no fallback. Every
contract read is an ``eth_call`` at the registered observation block. It writes only after
the complete frame has been assembled and never replaces an existing artifact.
"""

import argparse
import json
import os
import re
import sys
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib import resources
from pathlib import Path

import httpx
from eth_abi import decode as abi_decode
from eth_abi import encode as abi_encode
from eth_abi.exceptions import DecodingError, EncodingError
from web3 import Web3

from ...agents.pancake.positions import (
    FACTORY,
    FACTORY_ABI,
    FARM_OWNER_ABI,
    MASTER_CHEF_V3,
    NPM,
    NPM_ABI,
    OWNER_ABI,
    POOL_ABI,
    USER_POSITION_OWNER_INDEX,
    ZERO_ADDRESS,
)
from .spec import (
    PairedSpec,
    _range_conflict_exclusion,
    _range_successor_frame,
    load,
    range_sample_indices,
)

ADDRESS = re.compile(r"0x[0-9a-fA-F]{40}")
DATA = re.compile(r"0x(?:[0-9a-fA-F]{2})+")
HASH = re.compile(r"0x[0-9a-fA-F]{64}")
QUANTITY = re.compile(r"0x(?:0|[1-9a-fA-F][0-9a-fA-F]*)")
RPC_TIMEOUT_SECONDS = 30.0
# Each registered enumerable family derives its own 1,024 indices from its own
# stage-one protocol hash, so a frame collected for one family can never validate
# against another. Naming them here keeps the collector refusing anything else.
SPEC_IDS = ("v3-05-range-doctor", "v3-07-range-doctor")

ENUMERABLE_ABI = [
    {
        "name": "totalSupply",
        "type": "function",
        "stateMutability": "view",
        "inputs": [],
        "outputs": [{"name": "", "type": "uint256"}],
    },
    {
        "name": "tokenByIndex",
        "type": "function",
        "stateMutability": "view",
        "inputs": [{"name": "index", "type": "uint256"}],
        "outputs": [{"name": "", "type": "uint256"}],
    },
]


class RangeCaptureRefused(RuntimeError):
    """The registered frame could not be observed exactly, so nothing is written."""


@dataclass(frozen=True)
class ContractFunction:
    name: str
    input_types: tuple[str, ...]
    output_types: tuple[str, ...]
    selector: str


def _function(abi: list[dict], name: str) -> ContractFunction:
    matches = [
        entry
        for entry in abi
        if entry.get("type") == "function" and entry.get("name") == name
    ]
    if len(matches) != 1:
        raise RuntimeError(
            f"Range capture ABI does not define exactly one {name} function"
        )
    entry = matches[0]
    input_types = tuple(item["type"] for item in entry["inputs"])
    output_types = tuple(item["type"] for item in entry["outputs"])
    signature = f"{name}({','.join(input_types)})"
    selector = "0x" + Web3.keccak(text=signature)[:4].hex()
    return ContractFunction(name, input_types, output_types, selector)


TOTAL_SUPPLY = _function(ENUMERABLE_ABI, "totalSupply")
TOKEN_BY_INDEX = _function(ENUMERABLE_ABI, "tokenByIndex")
OWNER_OF = _function(OWNER_ABI, "ownerOf")
USER_POSITION_INFOS = _function(FARM_OWNER_ABI, "userPositionInfos")
POSITIONS = _function(NPM_ABI, "positions")
GET_POOL = _function(FACTORY_ABI, "getPool")
SLOT0 = _function(POOL_ABI, "slot0")


class JsonRpcClient:
    """One-shot JSON-RPC transport whose errors never disclose its endpoint."""

    def __init__(self, endpoint: str, *, client: httpx.Client | None = None) -> None:
        endpoint = endpoint.strip()
        if not endpoint:
            raise RangeCaptureRefused("DOCKET_ARCHIVE_RPC is required")
        self._endpoint = endpoint
        self._client = client or httpx.Client()
        self._owns_client = client is None
        self._next_id = 1

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def call(self, method: str, params: list) -> object:
        request_id = self._next_id
        self._next_id += 1
        try:
            response = self._client.post(
                self._endpoint,
                json={
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "method": method,
                    "params": params,
                },
                timeout=RPC_TIMEOUT_SECONDS,
            )
        except httpx.HTTPError:
            raise RangeCaptureRefused(
                f"JSON-RPC transport failed during {method}"
            ) from None
        if response.status_code != 200:
            raise RangeCaptureRefused(
                f"JSON-RPC returned HTTP {response.status_code} during {method}"
            )
        try:
            body = response.json()
        except ValueError:
            raise RangeCaptureRefused(
                f"JSON-RPC returned non-JSON data during {method}"
            ) from None
        if (
            not isinstance(body, dict)
            or body.get("jsonrpc") != "2.0"
            or body.get("id") != request_id
            or "error" in body
            or "result" not in body
        ):
            raise RangeCaptureRefused(
                f"JSON-RPC returned an invalid response during {method}"
            )
        return body["result"]


def _quantity(value: object, context: str) -> int:
    if not isinstance(value, str) or QUANTITY.fullmatch(value) is None:
        raise RangeCaptureRefused(f"{context} is not a canonical hex quantity")
    return int(value, 16)


def _address(value: object, context: str, *, allow_zero: bool = False) -> str:
    if not isinstance(value, str) or ADDRESS.fullmatch(value) is None:
        raise RangeCaptureRefused(f"{context} is not a 20-byte address")
    lowered = value.lower()
    if not allow_zero and lowered == ZERO_ADDRESS:
        raise RangeCaptureRefused(f"{context} is the zero address")
    return lowered


def _contract_call(
    rpc: JsonRpcClient,
    accounting: dict[str, int],
    accounting_name: str,
    address: str,
    function: ContractFunction,
    arguments: tuple,
    block_tag: str | dict[str, str | bool],
    *,
    fixed_width: bool = True,
) -> tuple:
    """One registered read, decoded strictly.

    ``fixed_width`` is the length check: every Range read returns one 32-byte word per
    output, so a different length means a different ABI and the frame aborts. A dynamic
    return — Venus's ``getAssetsIn`` answers ``address[]`` — has no such width, so the
    caller turns the check off and only whole words are required.
    """
    try:
        encoded = abi_encode(function.input_types, arguments)
    except (TypeError, ValueError, EncodingError):
        raise RangeCaptureRefused(
            f"could not encode {function.name} arguments"
        ) from None
    accounting[accounting_name] += 1
    result = rpc.call(
        "eth_call",
        [{"to": address.lower(), "data": function.selector + encoded.hex()}, block_tag],
    )
    if not isinstance(result, str) or DATA.fullmatch(result) is None:
        raise RangeCaptureRefused(f"{function.name} returned malformed ABI bytes")
    raw = bytes.fromhex(result[2:])
    expected_length = 32 * len(function.output_types)
    if fixed_width and len(raw) != expected_length:
        raise RangeCaptureRefused(
            f"{function.name} returned {len(raw)} ABI bytes, expected {expected_length}"
        )
    if not fixed_width and (not raw or len(raw) % 32):
        raise RangeCaptureRefused(
            f"{function.name} returned {len(raw)} ABI bytes, not whole words"
        )
    try:
        return abi_decode(function.output_types, raw, strict=True)
    except (TypeError, ValueError, DecodingError):
        raise RangeCaptureRefused(
            f"{function.name} returned invalid ABI data"
        ) from None


def _header(
    rpc: JsonRpcClient, frame_definition: dict, accounting: dict[str, int]
) -> None:
    accounting["eth_blockNumber"] += 1
    head = _quantity(rpc.call("eth_blockNumber", []), "eth_blockNumber result")
    observation_block = frame_definition["observation_block"]
    if head < observation_block:
        raise RangeCaptureRefused("the archive RPC head precedes the registered block")
    block_number_tag = hex(observation_block)
    accounting["eth_getBlockByNumber"] += 1
    block = rpc.call("eth_getBlockByNumber", [block_number_tag, False])
    if not isinstance(block, dict):
        raise RangeCaptureRefused("eth_getBlockByNumber returned no block object")
    number = _quantity(block.get("number"), "registered block number")
    timestamp = _quantity(block.get("timestamp"), "registered block timestamp")
    block_hash = block.get("hash")
    try:
        observed_time = (
            datetime.fromtimestamp(timestamp, UTC)
            .isoformat()
            .replace("+00:00", "Z")
        )
    except (OverflowError, OSError, ValueError):
        raise RangeCaptureRefused(
            "registered block timestamp is outside the supported range"
        ) from None
    if (
        number != observation_block
        or not isinstance(block_hash, str)
        or HASH.fullmatch(block_hash) is None
        or block_hash.lower() != frame_definition["observation_block_hash"]
        or observed_time != frame_definition["observation_time"]
    ):
        raise RangeCaptureRefused(
            "the archive RPC block header differs from the registered block"
        )


def collect_frame(spec: PairedSpec, rpc: JsonRpcClient) -> dict:
    """Read and return the complete registered enumerable frame."""
    if spec.spec_id not in SPEC_IDS:
        raise RangeCaptureRefused(
            f"only {' or '.join(SPEC_IDS)} can use this collector"
        )
    frame_definition = _range_successor_frame(spec)
    conflict_wallets, conflict_token_ids = _range_conflict_exclusion(spec)
    accounting = {
        "eth_blockNumber": 0,
        "eth_getBlockByNumber": 0,
        "totalSupply": 0,
        "tokenByIndex": 0,
        "ownerOf": 0,
        "userPositionInfos": 0,
        "positions": 0,
        "getPool": 0,
        "slot0": 0,
        "eth_getLogs": 0,
    }
    _header(rpc, frame_definition, accounting)
    block_reference = {
        "blockHash": frame_definition["observation_block_hash"],
        "requireCanonical": True,
    }
    total_supply = _contract_call(
        rpc, accounting, "totalSupply", NPM, TOTAL_SUPPLY, (), block_reference
    )[0]
    indices = range_sample_indices(spec, total_supply)
    rows = []
    token_ids = set()
    pool_by_position_key: dict[tuple[str, str, int], str] = {}
    tick_by_pool: dict[str, int] = {}
    for derived in indices:
        token_id = _contract_call(
            rpc,
            accounting,
            "tokenByIndex",
            NPM,
            TOKEN_BY_INDEX,
            (derived["index"],),
            block_reference,
        )[0]
        if token_id in token_ids:
            raise RangeCaptureRefused("tokenByIndex returned a repeated token id")
        token_ids.add(token_id)
        owner = _address(
            _contract_call(
                rpc,
                accounting,
                "ownerOf",
                NPM,
                OWNER_OF,
                (token_id,),
                block_reference,
            )[0],
            "ownerOf result",
        )
        beneficiary = None
        if owner == MASTER_CHEF_V3.lower():
            farm = _contract_call(
                rpc,
                accounting,
                "userPositionInfos",
                MASTER_CHEF_V3,
                USER_POSITION_INFOS,
                (token_id,),
                block_reference,
            )
            beneficiary = _address(
                farm[USER_POSITION_OWNER_INDEX], "MasterChef beneficiary"
            )
        row = derived | {
            "token_id": token_id,
            "owner": owner,
            "staking_beneficiary": beneficiary,
        }
        wallet = beneficiary if beneficiary is not None else owner
        if (
            token_id in conflict_token_ids
            or owner in conflict_wallets
            or wallet in conflict_wallets
        ):
            rows.append(row)
            continue
        position = _contract_call(
            rpc,
            accounting,
            "positions",
            NPM,
            POSITIONS,
            (token_id,),
            block_reference,
        )
        token0 = _address(position[2], "positions token0")
        token1 = _address(position[3], "positions token1")
        fee = position[4]
        tick_lower = position[5]
        tick_upper = position[6]
        liquidity = position[7]
        if token0 == token1 or tick_lower >= tick_upper:
            raise RangeCaptureRefused("positions returned an invalid pool tuple")
        row.update(
            {
                "liquidity": liquidity,
                "token0": token0,
                "token1": token1,
                "fee": fee,
                "tick_lower": tick_lower,
                "tick_upper": tick_upper,
            }
        )
        if liquidity > 0:
            position_key = (token0, token1, fee)
            pool_id = pool_by_position_key.get(position_key)
            if pool_id is None:
                pool_id = _address(
                    _contract_call(
                        rpc,
                        accounting,
                        "getPool",
                        FACTORY,
                        GET_POOL,
                        position_key,
                        block_reference,
                    )[0],
                    "getPool result",
                )
                pool_by_position_key[position_key] = pool_id
            current_tick = tick_by_pool.get(pool_id)
            if current_tick is None:
                current_tick = _contract_call(
                    rpc,
                    accounting,
                    "slot0",
                    pool_id,
                    SLOT0,
                    (),
                    block_reference,
                )[1]
                tick_by_pool[pool_id] = current_tick
            row.update({"pool_id": pool_id, "current_tick": current_tick})
        rows.append(row)
    accounting["total"] = sum(accounting.values())
    return {
        "chain_id": frame_definition["chain_id"],
        "position_manager": frame_definition["position_manager"].lower(),
        "observation_block": frame_definition["observation_block"],
        "observation_block_hash": frame_definition["observation_block_hash"],
        "observation_time": frame_definition["observation_time"],
        "total_supply": total_supply,
        "sample_size": frame_definition["sample_size"],
        "complete": True,
        "rows": rows,
        "rpc_call_accounting": accounting,
    }


def _archive_endpoint(environment: Mapping[str, str] | None = None) -> str:
    source = os.environ if environment is None else environment
    endpoint = str(source.get("DOCKET_ARCHIVE_RPC") or "").strip()
    if not endpoint:
        raise RangeCaptureRefused("DOCKET_ARCHIVE_RPC is required")
    return endpoint


def collect_from_environment(
    spec: PairedSpec,
    *,
    environment: Mapping[str, str] | None = None,
    client: httpx.Client | None = None,
) -> dict:
    rpc = JsonRpcClient(_archive_endpoint(environment), client=client)
    try:
        return collect_frame(spec, rpc)
    finally:
        rpc.close()


def write_frame(frame: dict, path: Path) -> Path:
    """Atomically create the frame artifact without replacing prior evidence."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(frame, indent=2, sort_keys=True) + "\n").encode("utf-8")
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False
        ) as temporary:
            temporary_path = Path(temporary.name)
            temporary.write(raw)
            temporary.flush()
            os.fsync(temporary.fileno())
        try:
            os.link(temporary_path, path)
        except FileExistsError:
            raise RangeCaptureRefused(
                f"{path} already exists; evidence is first-write"
            ) from None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
    return path


def resolve_spec(reference: str) -> Path:
    candidate = Path(reference)
    try:
        if candidate.is_file():
            return candidate
    except OSError:
        pass
    if not reference or Path(reference).name != reference:
        raise RangeCaptureRefused(
            "the spec must be a readable path or packaged family id"
        )
    packaged = (
        resources.files("docket.advantage") / "v3" / "specs" / f"{reference}.json"
    )
    if packaged.is_file():
        return Path(str(packaged))
    raise RangeCaptureRefused("the requested specification is not installed")


def main(
    argv: list[str] | None = None,
    *,
    environment: Mapping[str, str] | None = None,
    client: httpx.Client | None = None,
) -> int:
    parser = argparse.ArgumentParser(
        description="Capture a registered enumerable Range frame."
    )
    parser.add_argument(
        "spec", help="an enumerable Range family id or its specification path"
    )
    parser.add_argument("out", help="first-write enumerable frame JSON path")
    args = parser.parse_args(argv)
    output = Path(args.out)
    try:
        spec = load(resolve_spec(args.spec))
        if output.exists():
            raise RangeCaptureRefused(
                f"{output} already exists; evidence is first-write"
            )
        frame = collect_from_environment(spec, environment=environment, client=client)
        write_frame(frame, output)
    except (OSError, ValueError, RangeCaptureRefused) as exc:
        print(f"range capture refused: {exc}", file=sys.stderr)
        return 2
    print(
        f"captured {len(frame['rows'])} rows at block {frame['observation_block']} "
        f"with {frame['rpc_call_accounting']['total']} read calls"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised through main()
    raise SystemExit(main())
