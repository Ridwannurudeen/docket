"""Capture a registered Venus borrower frame from one archive RPC.

Same discipline as `range_capture`, for the same reason: one endpoint, one attempt per
JSON-RPC request, no fallback, and a single first-write artifact produced only after the
complete frame has been assembled. The transport, the ABI call helper and the first-write
writer are imported from that module rather than copied, so a fix to either collector's
retry behaviour cannot land in only one of them.

What is different is the population. A PancakeSwap position is enumerable from the NFT
contract; a Venus borrower is not enumerable from anything, so the registration names a
public rule instead — the `Borrow` logs of two registered vTokens over a registered block
window ending at the pinned observation block. Venus's VToken declares
``Borrow(address borrower, uint borrowAmount, uint accountBorrows, uint totalBorrows)``
with no indexed parameter, so the borrower is the first 32-byte data word and never a
topic; the registered topic is checked here against the keccak of the registered signature
rather than trusted as a pasted constant.

Those two vTokens bound where a borrower is *found*. Every market the account has actually
entered is then read, because `guard.assess` weighs all of them and the cross-check against
Venus's own liquidity figure is only meaningful over the same set.
"""

import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping

import httpx
from web3 import Web3

from ...agents.venus.markets import (
    COMPTROLLER_ABI,
    ORACLE_ABI,
    UNITROLLER,
    VTOKEN_ABI,
)
from .range_capture import (
    HASH,
    JsonRpcClient,
    RangeCaptureRefused,
    _address,
    _contract_call,
    _function,
    _quantity,
    resolve_spec,
    write_frame,
)
from .spec import (
    PairedSpec,
    _health_conflict_exclusion,
    _health_frame,
    health_account_truth,
    load,
)

# Each registered Health family pins its own observation block and enumeration window, so a
# frame collected for one can never validate against another. Naming them here keeps the
# collector refusing anything else.
SPEC_IDS = ("v3-09-health-guard",)


class VenusCaptureRefused(RangeCaptureRefused):
    """The registered Venus frame could not be observed exactly, so nothing is written.

    A subclass rather than a separate hierarchy because the shared transport raises the
    parent: one ``except`` in `main` then covers a refusal from either layer, and a reader
    of a traceback can still tell which layer refused.
    """


GET_ASSETS_IN = _function(COMPTROLLER_ABI, "getAssetsIn")
GET_ACCOUNT_LIQUIDITY = _function(COMPTROLLER_ABI, "getAccountLiquidity")
MARKETS = _function(COMPTROLLER_ABI, "markets")
ORACLE = _function(COMPTROLLER_ABI, "oracle")
GET_ACCOUNT_SNAPSHOT = _function(VTOKEN_ABI, "getAccountSnapshot")
GET_UNDERLYING_PRICE = _function(ORACLE_ABI, "getUnderlyingPrice")


def _header(rpc: JsonRpcClient, frame: dict, accounting: dict[str, int]) -> None:
    accounting["eth_blockNumber"] += 1
    head = _quantity(rpc.call("eth_blockNumber", []), "eth_blockNumber result")
    observation_block = frame["observation_block"]
    if head < observation_block:
        raise VenusCaptureRefused("the archive RPC head precedes the registered block")
    accounting["eth_getBlockByNumber"] += 1
    block = rpc.call("eth_getBlockByNumber", [hex(observation_block), False])
    if not isinstance(block, dict):
        raise VenusCaptureRefused("eth_getBlockByNumber returned no block object")
    number = _quantity(block.get("number"), "registered block number")
    timestamp = _quantity(block.get("timestamp"), "registered block timestamp")
    block_hash = block.get("hash")
    try:
        observed_time = (
            datetime.fromtimestamp(timestamp, timezone.utc)
            .isoformat()
            .replace("+00:00", "Z")
        )
    except (OverflowError, OSError, ValueError):
        raise VenusCaptureRefused(
            "registered block timestamp is outside the supported range"
        ) from None
    if (
        number != observation_block
        or not isinstance(block_hash, str)
        or HASH.fullmatch(block_hash) is None
        or block_hash.lower() != frame["observation_block_hash"]
        or observed_time != frame["observation_time"]
    ):
        raise VenusCaptureRefused(
            "the archive RPC block header differs from the registered block"
        )


def _borrowers(
    rpc: JsonRpcClient, frame: dict, accounting: dict[str, int]
) -> tuple[list[str], int]:
    """Every distinct borrower named by the registered logs, and how many logs said so."""
    topic = frame["borrow_topic"]
    addresses = [str(value).lower() for value in frame["vtokens"]]
    chunk = frame["enumeration_chunk_blocks"]
    found: dict[str, None] = {}
    log_count = 0
    start = frame["enumeration_from_block"]
    while start <= frame["enumeration_to_block"]:
        end = min(start + chunk - 1, frame["enumeration_to_block"])
        accounting["eth_getLogs"] += 1
        logs = rpc.call(
            "eth_getLogs",
            [
                {
                    "fromBlock": hex(start),
                    "toBlock": hex(end),
                    "address": addresses,
                    "topics": [topic],
                }
            ],
        )
        if not isinstance(logs, list):
            raise VenusCaptureRefused("eth_getLogs returned no log array")
        for row in logs:
            if (
                not isinstance(row, dict)
                or str(row.get("address", "")).lower() not in addresses
                or not isinstance(row.get("topics"), list)
                or len(row["topics"]) != 1
                or str(row["topics"][0]).lower() != topic
            ):
                raise VenusCaptureRefused(
                    "a Borrow log carries topics the registered event cannot produce"
                )
            data = row.get("data")
            if (
                not isinstance(data, str)
                or not data.startswith("0x")
                or len(data) - 2 != 4 * 64
            ):
                raise VenusCaptureRefused(
                    "a Borrow log does not carry the registered four data words"
                )
            word = data[2 : 2 + 64]
            if word[:24] != "0" * 24:
                raise VenusCaptureRefused(
                    "a Borrow log's borrower word is not a padded 20-byte address"
                )
            found["0x" + word[24:].lower()] = None
            log_count += 1
        start = end + 1
    if not found:
        raise VenusCaptureRefused(
            "the registered enumeration window named no borrower at all"
        )
    return sorted(found), log_count


def _market_row(
    rpc: JsonRpcClient,
    accounting: dict[str, int],
    account: str,
    vtoken: str,
    oracle: str,
    block_reference,
    cache: dict,
) -> dict:
    if vtoken not in cache:
        listed, collateral_factor, _is_venus = _contract_call(
            rpc,
            accounting,
            "markets",
            UNITROLLER,
            MARKETS,
            (Web3.to_checksum_address(vtoken),),
            block_reference,
        )
        if listed is not True:
            raise VenusCaptureRefused(
                "the comptroller does not list a market the account has entered"
            )
        price = _contract_call(
            rpc,
            accounting,
            "getUnderlyingPrice",
            oracle,
            GET_UNDERLYING_PRICE,
            (Web3.to_checksum_address(vtoken),),
            block_reference,
        )[0]
        cache[vtoken] = (collateral_factor, price)
    collateral_factor, price = cache[vtoken]
    error, vtoken_balance, borrow_balance, exchange_rate = _contract_call(
        rpc,
        accounting,
        "getAccountSnapshot",
        vtoken,
        GET_ACCOUNT_SNAPSHOT,
        (Web3.to_checksum_address(account),),
        block_reference,
    )
    return {
        "vtoken": vtoken,
        "snapshot_error": error,
        "collateral_factor_mantissa": str(collateral_factor),
        "vtoken_balance": str(vtoken_balance),
        "borrow_balance": str(borrow_balance),
        "exchange_rate_mantissa": str(exchange_rate),
        "underlying_price_mantissa": str(price),
    }


def collect_frame(spec: PairedSpec, rpc: JsonRpcClient) -> dict:
    """Read and return the complete registered Venus borrower frame."""
    if spec.spec_id not in SPEC_IDS:
        raise VenusCaptureRefused(
            f"only {' or '.join(SPEC_IDS)} can use this collector"
        )
    frame = _health_frame(spec)
    conflicted = _health_conflict_exclusion(spec)
    expected_topic = "0x" + Web3.keccak(text=frame["borrow_event"]).hex()
    if frame["borrow_topic"] != expected_topic:
        raise VenusCaptureRefused(
            "the registered Borrow topic is not the keccak of the registered signature"
        )
    accounting = {
        "eth_blockNumber": 0,
        "eth_getBlockByNumber": 0,
        "eth_getLogs": 0,
        "getAssetsIn": 0,
        "getAccountLiquidity": 0,
        "markets": 0,
        "oracle": 0,
        "getAccountSnapshot": 0,
        "getUnderlyingPrice": 0,
    }
    _header(rpc, frame, accounting)
    block_reference = {
        "blockHash": frame["observation_block_hash"],
        "requireCanonical": True,
    }
    borrowers, log_count = _borrowers(rpc, frame, accounting)
    oracle = _address(
        _contract_call(
            rpc, accounting, "oracle", UNITROLLER, ORACLE, (), block_reference
        )[0],
        "comptroller oracle",
    )
    cache: dict = {}
    accounts = []
    exclusions = []
    for account in borrowers:
        # Membership is decided before any balance is read, so a conflicted wallet never
        # reaches a status, a ratio or a stratum.
        if account in conflicted:
            exclusions.append(account)
            continue
        entered = [
            _address(value, "getAssetsIn entry")
            for value in _contract_call(
                rpc,
                accounting,
                "getAssetsIn",
                UNITROLLER,
                GET_ASSETS_IN,
                (Web3.to_checksum_address(account),),
                block_reference,
                fixed_width=False,
            )[0]
        ]
        if len(set(entered)) != len(entered):
            raise VenusCaptureRefused("getAssetsIn returned a repeated market")
        error_code, liquidity, shortfall = _contract_call(
            rpc,
            accounting,
            "getAccountLiquidity",
            UNITROLLER,
            GET_ACCOUNT_LIQUIDITY,
            (Web3.to_checksum_address(account),),
            block_reference,
        )
        markets = [
            _market_row(
                rpc, accounting, account, vtoken, oracle, block_reference, cache
            )
            for vtoken in entered
        ]
        row = {
            "account": account,
            "entered_markets": entered,
            "error_code": error_code,
            "liquidity_usd": str(liquidity),
            "shortfall_usd": str(shortfall),
            "oracle": oracle,
            "complete": error_code == 0
            and all(market["snapshot_error"] == 0 for market in markets),
            "markets": markets,
        }
        accounts.append(row | health_account_truth(row))
    if not accounts:
        raise VenusCaptureRefused(
            "every enumerated borrower was an experiment-party wallet, so the frame has "
            "no account this family may draw from"
        )
    accounting["total"] = sum(accounting.values())
    return {
        "chain_id": frame["chain_id"],
        "comptroller": str(frame["comptroller"]).lower(),
        "vtokens": [str(value).lower() for value in frame["vtokens"]],
        "borrow_event": frame["borrow_event"],
        "borrow_topic": frame["borrow_topic"],
        "borrow_log_count": log_count,
        "enumeration_from_block": frame["enumeration_from_block"],
        "enumeration_to_block": frame["enumeration_to_block"],
        "observation_block": frame["observation_block"],
        "observation_block_hash": frame["observation_block_hash"],
        "observation_time": frame["observation_time"],
        "complete": True,
        "accounts": accounts,
        "conflict_exclusions": sorted(exclusions),
        "rpc_call_accounting": accounting,
    }


def _archive_endpoint(environment: Mapping[str, str] | None = None) -> str:
    source = os.environ if environment is None else environment
    endpoint = str(source.get("DOCKET_ARCHIVE_RPC") or "").strip()
    if not endpoint:
        raise VenusCaptureRefused("DOCKET_ARCHIVE_RPC is required")
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


def main(
    argv: list[str] | None = None,
    *,
    environment: Mapping[str, str] | None = None,
    client: httpx.Client | None = None,
) -> int:
    parser = argparse.ArgumentParser(
        description="Capture a registered Venus borrower frame."
    )
    parser.add_argument("spec", help="a Health family id or its specification path")
    parser.add_argument("out", help="first-write borrower frame JSON path")
    args = parser.parse_args(argv)
    output = Path(args.out)
    try:
        spec = load(resolve_spec(args.spec))
        if output.exists():
            raise VenusCaptureRefused(
                f"{output} already exists; evidence is first-write"
            )
        frame = collect_from_environment(spec, environment=environment, client=client)
        write_frame(frame, output)
    except (OSError, ValueError, RangeCaptureRefused) as exc:
        print(f"venus capture refused: {exc}", file=sys.stderr)
        return 2
    print(
        f"captured {len(frame['accounts'])} accounts from "
        f"{frame['borrow_log_count']} Borrow logs at block "
        f"{frame['observation_block']} with "
        f"{frame['rpc_call_accounting']['total']} read calls"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised through main()
    raise SystemExit(main())
