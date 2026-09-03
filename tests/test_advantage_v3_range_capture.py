import base64
import hashlib
import json
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

import httpx
import pytest
from eth_abi import decode as abi_decode
from eth_abi import encode as abi_encode

from docket.advantage.v3.range_capture import (
    GET_POOL,
    OWNER_OF,
    POSITIONS,
    SLOT0,
    TOKEN_BY_INDEX,
    TOTAL_SUPPLY,
    USER_POSITION_INFOS,
    JsonRpcClient,
    RangeCaptureRefused,
    collect_frame,
    collect_from_environment,
    main,
    resolve_spec,
)
from docket.advantage.v3.spec import (
    YIELD_SOURCE_URLS,
    _range_conflict_exclusion,
    _range_successor_frame,
    _range_successor_source_frame,
    load,
    range_sample_indices,
)
from docket.agents.pancake.positions import FACTORY, MASTER_CHEF_V3, NPM, ZERO_ADDRESS

ROOT = Path(__file__).parents[1]
SPEC_PATH = ROOT / "docket" / "advantage" / "v3" / "specs" / "v3-05-range-doctor.json"
ENDPOINT = "https://archive.invalid/private-key-is-not-output"
NORMAL_OWNER = "0x1111111111111111111111111111111111111111"
FARM_BENEFICIARY = "0x2222222222222222222222222222222222222222"
TOKEN0 = "0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
TOKEN1 = "0xbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
POOL = "0xcccccccccccccccccccccccccccccccccccccccc"
OPERATOR = "0xdddddddddddddddddddddddddddddddddddddddd"


class FakeArchive:
    def __init__(
        self,
        spec,
        *,
        header_updates=None,
        malformed_selector=None,
        duplicate_second=False,
        zero_pool=False,
        state_block_hash=None,
    ):
        self.spec = spec
        self.frame = _range_successor_frame(spec)
        self.conflict_wallet = next(iter(_range_conflict_exclusion(spec)[0]))
        self.conflict_token = next(iter(_range_conflict_exclusion(spec)[1]))
        self.total_supply = 4_908_719
        self.indices = range_sample_indices(spec, self.total_supply)
        self.token_ids = {
            row["index"]: (self.conflict_token if ordinal == 0 else 8_000_000 + ordinal)
            for ordinal, row in enumerate(self.indices)
        }
        if duplicate_second:
            self.token_ids[self.indices[1]["index"]] = self.conflict_token
        self.ordinal_by_token = {
            token_id: ordinal
            for ordinal, row in enumerate(self.indices)
            for token_id in [self.token_ids[row["index"]]]
        }
        self.header_updates = header_updates or {}
        self.malformed_selector = malformed_selector
        self.zero_pool = zero_pool
        self.state_block_hash = state_block_hash or self.frame["observation_block_hash"]
        self.requests = []

    def __call__(self, request):
        body = json.loads(request.content)
        self.requests.append(body)
        method = body["method"]
        if method == "eth_blockNumber":
            result = hex(self.frame["observation_block"] + 100)
        elif method == "eth_getBlockByNumber":
            timestamp = int(
                datetime.fromisoformat(
                    self.frame["observation_time"].replace("Z", "+00:00")
                ).timestamp()
            )
            result = {
                "number": hex(self.frame["observation_block"]),
                "hash": self.frame["observation_block_hash"],
                "timestamp": hex(timestamp),
            } | self.header_updates
        elif method == "eth_call":
            block_reference = body["params"][1]
            if (
                isinstance(block_reference, dict)
                and block_reference.get("blockHash") != self.state_block_hash
            ):
                return httpx.Response(
                    200,
                    json={
                        "jsonrpc": "2.0",
                        "id": body["id"],
                        "error": {"code": -32001, "message": "block not found"},
                    },
                )
            result = self._eth_call(body["params"])
        else:
            raise AssertionError(f"unexpected JSON-RPC method {method}")
        return httpx.Response(
            200, json={"jsonrpc": "2.0", "id": body["id"], "result": result}
        )

    def _eth_call(self, params):
        assert len(params) == 2
        assert params[1] == {
            "blockHash": self.frame["observation_block_hash"],
            "requireCanonical": True,
        }
        call = params[0]
        selector = call["data"][:10]
        if selector == self.malformed_selector:
            return "0x00"
        functions = {
            TOTAL_SUPPLY.selector: TOTAL_SUPPLY,
            TOKEN_BY_INDEX.selector: TOKEN_BY_INDEX,
            OWNER_OF.selector: OWNER_OF,
            USER_POSITION_INFOS.selector: USER_POSITION_INFOS,
            POSITIONS.selector: POSITIONS,
            GET_POOL.selector: GET_POOL,
            SLOT0.selector: SLOT0,
        }
        function = functions.get(selector)
        if function is None:
            raise AssertionError(f"unexpected selector {selector}")
        raw_arguments = bytes.fromhex(call["data"][10:])
        arguments = (
            abi_decode(function.input_types, raw_arguments, strict=True)
            if function.input_types
            else ()
        )
        values = self._result(function, call["to"].lower(), arguments)
        return "0x" + abi_encode(function.output_types, values).hex()

    def _result(self, function, target, arguments):
        if function is TOTAL_SUPPLY:
            assert target == NPM.lower()
            return (self.total_supply,)
        if function is TOKEN_BY_INDEX:
            assert target == NPM.lower()
            return (self.token_ids[arguments[0]],)
        token_id = arguments[0] if arguments else None
        ordinal = self.ordinal_by_token.get(token_id)
        if function is OWNER_OF:
            assert target == NPM.lower()
            owner = (
                self.conflict_wallet
                if ordinal == 1
                else MASTER_CHEF_V3
                if ordinal in {2, 3}
                else NORMAL_OWNER
            )
            return (owner,)
        if function is USER_POSITION_INFOS:
            assert target == MASTER_CHEF_V3.lower()
            assert ordinal in {2, 3}
            beneficiary = self.conflict_wallet if ordinal == 2 else FARM_BENEFICIARY
            return (100, 0, -100, 100, 0, 0, beneficiary, 0, 0)
        if function is POSITIONS:
            assert target == NPM.lower()
            assert ordinal is not None and ordinal >= 3
            liquidity = 0 if ordinal == 4 else 1_000
            return (
                0,
                OPERATOR,
                TOKEN0,
                TOKEN1,
                500,
                -100,
                100,
                liquidity,
                0,
                0,
                0,
                0,
            )
        if function is GET_POOL:
            assert target == FACTORY.lower()
            assert arguments == (TOKEN0, TOKEN1, 500)
            return (ZERO_ADDRESS if self.zero_pool else POOL,)
        if function is SLOT0:
            assert target == POOL
            return (1, 0, 0, 0, 0, 0, True)
        raise AssertionError(f"unhandled function {function.name}")


def _spec():
    return load(SPEC_PATH)


def _client(archive):
    return httpx.Client(transport=httpx.MockTransport(archive))


def _snapshot(body, *, url, observed_at):
    raw = json.dumps(body, separators=(",", ":")).encode()
    return {
        "url": url,
        "observed_at": observed_at,
        "attempt_ordinal": 1,
        "sha256": hashlib.sha256(raw).hexdigest(),
        "body_base64": base64.b64encode(raw).decode(),
    }


def _locked_source(path, kind):
    raw = path.read_bytes()
    return {"kind": kind, "ref": path.name, "sha256": hashlib.sha256(raw).hexdigest()}


def _validate_as_registered_source(spec, frame, tmp_path):
    definition = _range_successor_frame(spec)
    attempt = datetime.fromisoformat(
        definition["pool_truth_capture_attempts"][0].replace("Z", "+00:00")
    )
    pools = [
        {
            "id": POOL,
            "token0": {"id": TOKEN0},
            "token1": {"id": TOKEN1},
            "feeTier": "500",
            "tvlUSD": "1000000",
            "volumeUSD24h": "100000",
            "feeUSD24h": "500",
            "protocolFeeUSD24h": "100",
        }
    ]
    token_list = {
        "tokens": [
            {"chainId": 56, "address": TOKEN0},
            {"chainId": 56, "address": TOKEN1},
        ]
    }
    pool_truth = {
        "capture_log": [
            {
                "attempt_ordinal": 1,
                "scheduled_at": definition["pool_truth_capture_attempts"][0],
                "pools_status": 200,
                "token_list_status": 200,
            }
        ],
        "source_snapshots": {
            "pools": _snapshot(
                pools,
                url=YIELD_SOURCE_URLS["pools"],
                observed_at=attempt.isoformat().replace("+00:00", "Z"),
            ),
            "token_list": _snapshot(
                token_list,
                url=YIELD_SOURCE_URLS["token_list"],
                observed_at=(attempt + timedelta(seconds=1))
                .isoformat()
                .replace("+00:00", "Z"),
            ),
        },
    }
    frame_path = tmp_path / "frame.json"
    truth_path = tmp_path / "truth.json"
    frame_path.write_text(json.dumps(frame), encoding="utf-8")
    truth_path.write_text(json.dumps(pool_truth), encoding="utf-8")
    return _range_successor_source_frame(
        spec,
        [
            _locked_source(frame_path, "enumerable_position_frame"),
            _locked_source(truth_path, "pool_truth"),
        ],
        tmp_path,
    )


def test_verified_function_selectors_match_installed_abi():
    assert TOTAL_SUPPLY.selector == "0x18160ddd"
    assert TOKEN_BY_INDEX.selector == "0x4f6ccce7"
    assert OWNER_OF.selector == "0x6352211e"
    assert USER_POSITION_INFOS.selector == "0x3b1acf74"
    assert POSITIONS.selector == "0x99fbab88"
    assert GET_POOL.selector == "0x1698ee82"
    assert SLOT0.selector == "0x3850c7bd"
    assert resolve_spec("v3-05-range-doctor") == SPEC_PATH
    assert resolve_spec(str(SPEC_PATH)) == SPEC_PATH


def test_cli_captures_complete_pinned_first_write_frame(tmp_path, capsys):
    spec = _spec()
    archive = FakeArchive(spec)
    client = _client(archive)
    output = tmp_path / "frame.json"

    assert (
        main(
            ["v3-05-range-doctor", str(output)],
            environment={"DOCKET_ARCHIVE_RPC": ENDPOINT},
            client=client,
        )
        == 0
    )
    frame = json.loads(output.read_text(encoding="utf-8"))
    assert frame["sample_size"] == 1_024
    assert len(frame["rows"]) == 1_024
    assert frame["complete"] is True
    assert set(frame["rows"][0]) == {
        "sample_ordinal",
        "derivation_counter",
        "index",
        "token_id",
        "owner",
        "staking_beneficiary",
    }
    assert set(frame["rows"][1]) == set(frame["rows"][0])
    assert set(frame["rows"][2]) == set(frame["rows"][0])
    assert frame["rows"][2]["staking_beneficiary"] == archive.conflict_wallet
    assert frame["rows"][3]["staking_beneficiary"] == FARM_BENEFICIARY
    assert frame["rows"][3]["pool_id"] == POOL
    assert frame["rows"][3]["current_tick"] == 0
    assert "pool_id" not in frame["rows"][4]
    assert frame["rows"][4]["liquidity"] == 0
    assert frame["rpc_call_accounting"] == {
        "eth_blockNumber": 1,
        "eth_getBlockByNumber": 1,
        "totalSupply": 1,
        "tokenByIndex": 1_024,
        "ownerOf": 1_024,
        "userPositionInfos": 2,
        "positions": 1_021,
        "getPool": 1,
        "slot0": 1,
        "eth_getLogs": 0,
        "total": 3_076,
    }
    method_counts = Counter(request["method"] for request in archive.requests)
    assert set(method_counts) == {
        "eth_blockNumber",
        "eth_getBlockByNumber",
        "eth_call",
    }
    assert method_counts["eth_call"] == 3_074
    block_tag = {
        "blockHash": _range_successor_frame(spec)["observation_block_hash"],
        "requireCanonical": True,
    }
    assert all(
        request["params"][1] == block_tag
        for request in archive.requests
        if request["method"] == "eth_call"
    )

    _, positions, conflicts, validated_frame = _validate_as_registered_source(
        spec, frame, tmp_path
    )
    assert validated_frame == frame
    assert len(positions) == 1_020
    assert len(conflicts) == 3

    before = len(archive.requests)
    assert (
        main(
            ["v3-05-range-doctor", str(output)],
            environment={"DOCKET_ARCHIVE_RPC": ENDPOINT},
            client=client,
        )
        == 2
    )
    assert len(archive.requests) == before
    assert ENDPOINT not in capsys.readouterr().err


def test_registered_validator_rejects_outcome_data_on_conflict(tmp_path):
    spec = _spec()
    archive = FakeArchive(spec)
    with _client(archive) as client:
        frame = collect_from_environment(
            spec,
            environment={"DOCKET_ARCHIVE_RPC": ENDPOINT},
            client=client,
        )
    frame["rows"][0]["liquidity"] = 1
    with pytest.raises(ValueError, match="conflict was not recorded before outcome"):
        _validate_as_registered_source(spec, frame, tmp_path)


@pytest.mark.parametrize(
    "header_updates",
    [
        {"number": hex(_range_successor_frame(_spec())["observation_block"] + 1)},
        {"hash": "0x" + "00" * 32},
        {"timestamp": hex(1)},
    ],
)
def test_registered_block_header_mismatch_aborts_before_contract_calls(header_updates):
    spec = _spec()
    archive = FakeArchive(spec, header_updates=header_updates)
    with _client(archive) as client:
        with pytest.raises(RangeCaptureRefused, match="block header differs"):
            collect_from_environment(
                spec,
                environment={"DOCKET_ARCHIVE_RPC": ENDPOINT},
                client=client,
            )
    assert [request["method"] for request in archive.requests] == [
        "eth_blockNumber",
        "eth_getBlockByNumber",
    ]


def test_matching_header_with_different_state_block_refuses():
    spec = _spec()
    archive = FakeArchive(spec, state_block_hash="0x" + "00" * 32)

    with _client(archive) as client:
        with pytest.raises(RangeCaptureRefused, match="invalid response during eth_call"):
            collect_from_environment(
                spec,
                environment={"DOCKET_ARCHIVE_RPC": ENDPOINT},
                client=client,
            )

    assert archive.requests[1]["params"] == [
        hex(_range_successor_frame(spec)["observation_block"]),
        False,
    ]
    assert [request["method"] for request in archive.requests] == [
        "eth_blockNumber",
        "eth_getBlockByNumber",
        "eth_call",
    ]


def test_state_reads_use_registered_block_hash_reference_not_number():
    spec = _spec()
    archive = FakeArchive(spec)
    with _client(archive) as client:
        collect_from_environment(
            spec,
            environment={"DOCKET_ARCHIVE_RPC": ENDPOINT},
            client=client,
        )

    references = [
        request["params"][1]
        for request in archive.requests
        if request["method"] == "eth_call"
    ]
    assert references
    assert all(isinstance(reference, dict) for reference in references)
    assert {json.dumps(reference, sort_keys=True) for reference in references} == {
        json.dumps(
            {
                "blockHash": _range_successor_frame(spec)["observation_block_hash"],
                "requireCanonical": True,
            },
            sort_keys=True,
        )
    }


def test_state_read_reference_spells_require_canonical_exactly():
    spec = _spec()
    archive = FakeArchive(spec)
    with _client(archive) as client:
        collect_from_environment(
            spec,
            environment={"DOCKET_ARCHIVE_RPC": ENDPOINT},
            client=client,
        )

    reference = next(
        request["params"][1]
        for request in archive.requests
        if request["method"] == "eth_call"
    )
    assert set(reference) == {"blockHash", "requireCanonical"}
    assert reference["requireCanonical"] is True
    assert "requireCanonicalChain" not in reference


def test_malformed_abi_aborts_without_retry():
    spec = _spec()
    archive = FakeArchive(spec, malformed_selector=OWNER_OF.selector)
    with _client(archive) as client:
        with pytest.raises(RangeCaptureRefused, match="ownerOf returned 1 ABI bytes"):
            collect_from_environment(
                spec,
                environment={"DOCKET_ARCHIVE_RPC": ENDPOINT},
                client=client,
            )
    owner_calls = [
        request
        for request in archive.requests
        if request["method"] == "eth_call"
        and request["params"][0]["data"].startswith(OWNER_OF.selector)
    ]
    assert len(owner_calls) == 1


def test_repeated_enumerable_token_aborts_before_second_owner_lookup():
    spec = _spec()
    archive = FakeArchive(spec, duplicate_second=True)
    with _client(archive) as client:
        with pytest.raises(RangeCaptureRefused, match="repeated token id"):
            collect_from_environment(
                spec,
                environment={"DOCKET_ARCHIVE_RPC": ENDPOINT},
                client=client,
            )
    selectors = [
        request["params"][0]["data"][:10]
        for request in archive.requests
        if request["method"] == "eth_call"
    ]
    assert selectors.count(TOKEN_BY_INDEX.selector) == 2
    assert selectors.count(OWNER_OF.selector) == 1


def test_zero_pool_for_positive_liquidity_fails_closed():
    spec = _spec()
    archive = FakeArchive(spec, zero_pool=True)
    with _client(archive) as client:
        with pytest.raises(
            RangeCaptureRefused, match="getPool result is the zero address"
        ):
            collect_from_environment(
                spec,
                environment={"DOCKET_ARCHIVE_RPC": ENDPOINT},
                client=client,
            )
    selectors = [
        request["params"][0]["data"][:10]
        for request in archive.requests
        if request["method"] == "eth_call"
    ]
    assert selectors.count(GET_POOL.selector) == 1
    assert SLOT0.selector not in selectors


def test_blank_endpoint_and_transport_failure_do_not_disclose_rpc(capsys, tmp_path):
    spec = _spec()
    with pytest.raises(RangeCaptureRefused, match="DOCKET_ARCHIVE_RPC is required"):
        collect_from_environment(spec, environment={"DOCKET_ARCHIVE_RPC": "  "})

    calls = 0

    def fail_transport(request):
        nonlocal calls
        calls += 1
        raise httpx.ConnectError(f"failed to connect to {request.url}", request=request)

    client = httpx.Client(transport=httpx.MockTransport(fail_transport))
    try:
        assert (
            main(
                [str(SPEC_PATH), str(tmp_path / "never-written.json")],
                environment={"DOCKET_ARCHIVE_RPC": ENDPOINT},
                client=client,
            )
            == 2
        )
    finally:
        client.close()
    assert calls == 1
    assert ENDPOINT not in capsys.readouterr().err


def test_collector_refuses_another_family_before_rpc():
    spec = load(
        ROOT / "docket" / "advantage" / "v3" / "specs" / "v3-01-range-doctor.json"
    )

    class NoRpc:
        def call(self, method, params):
            raise AssertionError((method, params))

    with pytest.raises(RangeCaptureRefused, match="only v3-05-range-doctor"):
        collect_frame(spec, NoRpc())


def test_json_rpc_rejects_protocol_mismatch_without_endpoint_disclosure():
    def wrong_id(request):
        body = json.loads(request.content)
        return httpx.Response(
            200,
            json={"jsonrpc": "2.0", "id": body["id"] + 1, "result": "0x1"},
        )

    with _client(wrong_id) as client:
        rpc = JsonRpcClient(ENDPOINT, client=client)
        with pytest.raises(RangeCaptureRefused, match="invalid response") as exc_info:
            rpc.call("eth_blockNumber", [])
    assert ENDPOINT not in str(exc_info.value)
