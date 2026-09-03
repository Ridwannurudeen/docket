"""The pinned Venus borrower family: registration, collector, lock and scoring.

The collector never runs against the real archive here. A fake JSON-RPC transport answers
the exact registered calls, so the whole Sep 8 sequence — collect, write, assemble, lock —
is exercised now rather than on the morning it has to work.
"""

import hashlib
import json
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import httpx
import pytest
from eth_abi import decode as abi_decode
from eth_abi import encode as abi_encode

from docket.advantage.v3 import (
    assemble,
    calibration,
    orchestrator,
    runner,
    scoring,
    venus_capture,
)
from docket.advantage.v3.range_capture import RangeCaptureRefused
from docket.advantage.v3.spec import (
    E18,
    HEALTH_STATUSES,
    HEALTH_STRATA,
    HEALTH_VTOKENS,
    RANGE_CONTROLLED_WALLETS,
    _health_frame,
    health_account_truth,
    health_selected_accounts,
    is_health_family,
    load,
    lock_inputs,
)
from docket.advantage.v3.venus_capture import (
    GET_ACCOUNT_LIQUIDITY,
    GET_ACCOUNT_SNAPSHOT,
    GET_ASSETS_IN,
    GET_UNDERLYING_PRICE,
    MARKETS,
    ORACLE,
    VenusCaptureRefused,
    collect_frame,
    collect_from_environment,
    main,
)
from docket.agents.venus import guard, markets
from docket.hire import catalogue
from docket.hire.receipts import canonical_hash

ROOT = Path(__file__).resolve().parents[1]
SPEC_PATH = ROOT / "docket/advantage/v3/specs/v3-09-health-guard.json"
CALIBRATION_SET = ROOT / "docket/advantage/v3/sources/health-v9-calibration-set.json"
SPEC = load(SPEC_PATH)
FRAME = _health_frame(SPEC)
ENDPOINT = "https://archive.invalid/health"
ORACLE_ADDRESS = "0x1111111111111111111111111111111111111111"
CONFLICT_WALLET = next(iter(RANGE_CONTROLLED_WALLETS))
VUSDC, VUSDT = HEALTH_VTOKENS

# One account per registered stratum, plus the experiment party's own wallet, which the
# collector has to drop before it reads a single balance.
SHORTFALL_ACCOUNT = "0x00000000000000000000000000000000000000a1"
HEADROOM_ACCOUNT = "0x00000000000000000000000000000000000000b2"
NO_BORROW_ACCOUNT = "0x00000000000000000000000000000000000000c3"
ACCOUNTS = {
    SHORTFALL_ACCOUNT: {
        "entered": [VUSDC],
        "liquidity": 0,
        "shortfall": 200 * E18,
        "snapshots": {VUSDC: (0, 1000 * E18, 1000 * E18, E18)},
    },
    HEADROOM_ACCOUNT: {
        "entered": [VUSDC, VUSDT],
        "liquidity": 500 * E18,
        "shortfall": 0,
        "snapshots": {
            VUSDC: (0, 1000 * E18, 300 * E18, E18),
            VUSDT: (0, 500 * E18, 0, E18),
        },
    },
    NO_BORROW_ACCOUNT: {
        "entered": [VUSDT],
        "liquidity": 800 * E18,
        "shortfall": 0,
        "snapshots": {VUSDT: (0, 1000 * E18, 0, E18)},
    },
}
COLLATERAL_FACTOR = {VUSDC: 8 * 10**17, VUSDT: 8 * 10**17}
PRICE = {VUSDC: E18, VUSDT: E18}


def _borrow_log(vtoken: str, account: str) -> dict:
    word = account[2:].rjust(64, "0")
    return {
        "address": vtoken,
        "topics": [FRAME["borrow_topic"]],
        "data": "0x" + word + "0" * 64 * 3,
    }


class FakeArchive:
    """Answers exactly the registered reads, and nothing else."""

    def __init__(self, *, header_updates=None, logs=None, unlisted_market=False):
        self.header_updates = header_updates or {}
        self.logs = (
            logs
            if logs is not None
            else [
                _borrow_log(VUSDC, SHORTFALL_ACCOUNT),
                _borrow_log(VUSDC, CONFLICT_WALLET),
                _borrow_log(VUSDT, HEADROOM_ACCOUNT),
                _borrow_log(VUSDT, NO_BORROW_ACCOUNT),
                _borrow_log(VUSDC, HEADROOM_ACCOUNT),
            ]
        )
        self.unlisted_market = unlisted_market
        self.log_windows = []

    def __call__(self, request):
        body = json.loads(request.content)
        method = body["method"]
        if method == "eth_blockNumber":
            result = hex(FRAME["observation_block"] + 10)
        elif method == "eth_getBlockByNumber":
            timestamp = 1788393599
            result = {
                "number": hex(FRAME["observation_block"]),
                "hash": FRAME["observation_block_hash"],
                "timestamp": hex(timestamp),
            } | self.header_updates
        elif method == "eth_getLogs":
            result = self._logs(body["params"][0])
        elif method == "eth_call":
            assert body["params"][1] == {
                "blockHash": FRAME["observation_block_hash"],
                "requireCanonical": True,
            }
            result = self._eth_call(body["params"][0])
        else:  # pragma: no cover - a method nobody registered
            raise AssertionError(f"unexpected JSON-RPC method {method}")
        return httpx.Response(
            200, json={"jsonrpc": "2.0", "id": body["id"], "result": result}
        )

    def _logs(self, query):
        assert query["address"] == list(HEALTH_VTOKENS)
        assert query["topics"] == [FRAME["borrow_topic"]]
        start = int(query["fromBlock"], 16)
        end = int(query["toBlock"], 16)
        assert end - start + 1 == FRAME["enumeration_chunk_blocks"]
        self.log_windows.append((start, end))
        return self.logs if start == FRAME["enumeration_from_block"] else []

    def _eth_call(self, call):
        selector = call["data"][:10]
        target = call["to"].lower()
        functions = {
            GET_ASSETS_IN.selector: GET_ASSETS_IN,
            GET_ACCOUNT_LIQUIDITY.selector: GET_ACCOUNT_LIQUIDITY,
            MARKETS.selector: MARKETS,
            ORACLE.selector: ORACLE,
            GET_ACCOUNT_SNAPSHOT.selector: GET_ACCOUNT_SNAPSHOT,
            GET_UNDERLYING_PRICE.selector: GET_UNDERLYING_PRICE,
        }
        function = functions.get(selector)
        assert function is not None, f"unexpected selector {selector}"
        raw = bytes.fromhex(call["data"][10:])
        arguments = (
            abi_decode(function.input_types, raw, strict=True)
            if function.input_types
            else ()
        )
        values = self._result(function, target, arguments)
        return "0x" + abi_encode(function.output_types, values).hex()

    def _result(self, function, target, arguments):
        if function is ORACLE:
            assert target == FRAME["comptroller"]
            return (ORACLE_ADDRESS,)
        if function is GET_UNDERLYING_PRICE:
            assert target == ORACLE_ADDRESS
            return (PRICE[arguments[0].lower()],)
        if function is MARKETS:
            assert target == FRAME["comptroller"]
            listed = not self.unlisted_market
            return (listed, COLLATERAL_FACTOR[arguments[0].lower()], True)
        account = arguments[0].lower()
        if function is GET_ASSETS_IN:
            assert target == FRAME["comptroller"]
            return (ACCOUNTS[account]["entered"],)
        if function is GET_ACCOUNT_LIQUIDITY:
            assert target == FRAME["comptroller"]
            state = ACCOUNTS[account]
            return (0, state["liquidity"], state["shortfall"])
        assert function is GET_ACCOUNT_SNAPSHOT
        return ACCOUNTS[account]["snapshots"][target]


def _client(archive) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(archive))


def _collect(**kwargs) -> dict:
    archive = FakeArchive(**kwargs)
    with _client(archive) as client:
        return collect_frame(SPEC, venus_capture.JsonRpcClient(ENDPOINT, client=client))


def test_the_registration_is_a_new_family_with_a_human_arm_and_a_pinned_block():
    assert is_health_family(SPEC)
    assert SPEC.category == "health factor"
    assert SPEC.protocol_correction is None
    assert SPEC.successor_provenance is None
    assert SPEC.pilot_provenance is None
    assert SPEC.n_planned == 3
    assert SPEC.inputs_sha256 == ""
    assert SPEC.arms["manual"]["display_name"] == "Human operator"
    assert "human operator" in SPEC.claim.lower()
    assert "no health factor" in SPEC.claim.lower()
    assert "health-v9-blinding" in SPEC.scoring["randomisation"]
    assert FRAME["observation_block"] == 119627412
    assert len(FRAME["block_pin_endpoints"]) >= 2
    assert (
        FRAME["enumeration_to_block"] - FRAME["enumeration_from_block"] + 1
    ) % FRAME["enumeration_chunk_blocks"] == 0
    assert [row["name"] for row in FRAME["strata"]] == list(HEALTH_STRATA)
    assert sorted(FRAME["status_vocabulary"]) == sorted(HEALTH_STATUSES)


def test_both_registered_hashes_verify_from_the_committed_bytes():
    record = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    rebuilt = load(SPEC_PATH)

    assert record["stage_one_protocol_hash"] == rebuilt.stage_one_protocol_hash
    assert record["spec_hash"] == rebuilt.spec_hash


def test_the_registered_topic_is_the_keccak_of_the_registered_signature():
    from web3 import Web3

    assert FRAME["borrow_topic"] == (
        "0x" + Web3.keccak(text=FRAME["borrow_event"]).hex()
    )
    assert FRAME["borrower_data_word"] == 0


def test_the_collector_reads_the_registered_frame_and_drops_the_conflicted_wallet():
    frame = _collect()

    assert frame["complete"] is True
    assert frame["conflict_exclusions"] == [CONFLICT_WALLET]
    assert [row["account"] for row in frame["accounts"]] == sorted(ACCOUNTS)
    assert frame["borrow_log_count"] == 5
    assert {row["status"] for row in frame["accounts"]} == set(HEALTH_STRATA)
    for row in frame["accounts"]:
        assert {name: row[name] for name in health_account_truth(row)} == (
            health_account_truth(row)
        )
        assert [market["vtoken"] for market in row["markets"]] == row["entered_markets"]
    windows = (
        FRAME["enumeration_to_block"] - FRAME["enumeration_from_block"] + 1
    ) // FRAME["enumeration_chunk_blocks"]
    assert frame["rpc_call_accounting"]["eth_getLogs"] == windows


def test_the_collector_refuses_a_block_header_that_is_not_the_registered_one():
    with pytest.raises(RangeCaptureRefused, match="differs from the registered block"):
        _collect(header_updates={"timestamp": hex(1788393598)})


def test_the_collector_refuses_a_log_the_registered_event_cannot_produce():
    bad = _borrow_log(VUSDC, SHORTFALL_ACCOUNT)
    bad["topics"] = [FRAME["borrow_topic"], FRAME["borrow_topic"]]

    with pytest.raises(RangeCaptureRefused, match="topics the registered event"):
        _collect(logs=[bad])


def test_the_collector_refuses_a_market_the_comptroller_does_not_list():
    with pytest.raises(RangeCaptureRefused, match="does not list a market"):
        _collect(unlisted_market=True)


def test_the_collector_refuses_a_window_that_names_no_borrower():
    with pytest.raises(RangeCaptureRefused, match="named no borrower"):
        _collect(logs=[])


def test_the_collector_refuses_without_the_archive_endpoint(tmp_path):
    with pytest.raises(VenusCaptureRefused, match="DOCKET_ARCHIVE_RPC is required"):
        collect_from_environment(SPEC, environment={})

    with pytest.raises(VenusCaptureRefused, match="DOCKET_ARCHIVE_RPC is required"):
        collect_from_environment(SPEC, environment={"DOCKET_ARCHIVE_RPC": "  "})

    code = main(["v3-09-health-guard", str(tmp_path / "frame.json")], environment={})

    assert code == 2
    assert not (tmp_path / "frame.json").exists()


def test_the_collector_refuses_an_existing_output_and_another_family(tmp_path, capsys):
    output = tmp_path / "frame.json"
    output.write_text("{}\n", encoding="utf-8")

    code = main(
        ["v3-09-health-guard", str(output)],
        environment={"DOCKET_ARCHIVE_RPC": ENDPOINT},
    )

    assert code == 2
    assert "first-write" in capsys.readouterr().err
    assert output.read_text(encoding="utf-8") == "{}\n"

    with _client(FakeArchive()) as client:
        rpc = venus_capture.JsonRpcClient(ENDPOINT, client=client)
        with pytest.raises(RangeCaptureRefused, match="can use this collector"):
            collect_frame(
                load(ROOT / "docket/advantage/v3/specs/v3-08-yield-router.json"), rpc
            )


def test_the_collector_writes_the_frame_once(tmp_path):
    output = tmp_path / "health-v9-enumerable-frame.json"
    archive = FakeArchive()
    with _client(archive) as client:
        code = main(
            ["v3-09-health-guard", str(output)],
            environment={"DOCKET_ARCHIVE_RPC": ENDPOINT},
            client=client,
        )

    assert code == 0
    written = json.loads(output.read_text(encoding="utf-8"))
    assert written["observation_block"] == FRAME["observation_block"]

    with _client(FakeArchive()) as client:
        again = main(
            ["v3-09-health-guard", str(output)],
            environment={"DOCKET_ARCHIVE_RPC": ENDPOINT},
            client=client,
        )

    assert again == 2
    assert json.loads(output.read_text(encoding="utf-8")) == written


def test_the_selection_takes_the_registered_lowest_hash_in_every_stratum():
    accounts = _collect()["accounts"]
    selected = health_selected_accounts(SPEC, accounts)

    assert [row["status"] for row in selected] == list(HEALTH_STRATA)
    for row, stratum in zip(selected, HEALTH_STRATA, strict=True):
        candidates = [item for item in accounts if item["status"] == stratum]
        assert row is min(
            candidates,
            key=lambda item: hashlib.sha256(
                (
                    f"{SPEC.stage_one_protocol_hash}|56|{FRAME['comptroller']}|"
                    f"{item['account']}|{stratum}"
                ).encode()
            ).hexdigest(),
        )


def test_an_empty_stratum_refuses_the_selection():
    accounts = [row for row in _collect()["accounts"] if row["status"] != "shortfall"]

    with pytest.raises(ValueError, match="stratum 'shortfall' is empty"):
        health_selected_accounts(SPEC, accounts)


def _calibration_bytes() -> bytes:
    return CALIBRATION_SET.read_bytes()


def _evaluator_calibration() -> list[dict]:
    shared = json.loads(_calibration_bytes().decode("utf-8"))["cases"]
    return [
        {
            "evaluator_id": seat["evaluator_id"],
            "model_build": f"stub-build-{index + 1}",
            "session_id": f"stub-session-{index + 1}",
            "rubric_anchor_hash": canonical_hash(SPEC.quality_rubric["criteria"]),
            "calibration_results": [
                {
                    "case_id": case["case_id"],
                    "input": case["input"],
                    "expected": case["expected"],
                    "submitted": case["expected"],
                }
                for case in shared
            ],
        }
        for index, seat in enumerate(SPEC.scoring["evaluator_roster"])
    ]


def _calibration_capture(root: Path) -> Path:
    shared = json.loads(_calibration_bytes().decode("utf-8"))["cases"]
    for row in _evaluator_calibration():
        request = calibration.open_attempt(
            SPEC,
            root,
            evaluator_id=row["evaluator_id"],
            model_build=row["model_build"],
            session_id=row["session_id"],
            calibration_set=_calibration_bytes(),
        )
        answer = {
            "evaluator_id": row["evaluator_id"],
            "results": [
                {"case_id": case["case_id"], "submitted": case["expected"]}
                for case in shared
            ],
        }
        calibration.record_response(
            SPEC,
            root,
            evaluator_id=row["evaluator_id"],
            attempt_ordinal=request["attempt_ordinal"],
            raw_response=json.dumps(answer, sort_keys=True).encode("utf-8"),
        )
    return root


def _stage(tmp_path: Path) -> tuple[Path, list[dict], dict]:
    repo_root = tmp_path / "repo"
    frame_path = (
        repo_root / "docket/advantage/v3/sources/health-v9-enumerable-frame.json"
    )
    frame_path.parent.mkdir(parents=True, exist_ok=True)
    frame = _collect()
    venus_capture.write_frame(frame, frame_path)
    source_refs = [
        {
            "kind": "venus_frame",
            "ref": frame_path.relative_to(repo_root).as_posix(),
            "sha256": hashlib.sha256(frame_path.read_bytes()).hexdigest(),
        }
    ]
    return repo_root, source_refs, frame


def test_the_assembled_envelope_passes_the_real_input_lock(tmp_path):
    """The whole Sep 8 sequence, six days early: collect, write, assemble, lock."""
    repo_root, source_refs, frame = _stage(tmp_path)
    envelope = assemble.assemble_health_envelope(
        SPEC,
        source_refs,
        repo_root=repo_root,
        calibration_dir=_calibration_capture(tmp_path / "calibration"),
        calibration_set=_calibration_bytes(),
        evaluator_calibration=_evaluator_calibration(),
    )
    assemble.write_envelope(SPEC, envelope, repo_root=repo_root)
    locked = lock_inputs(SPEC, repo_root=repo_root)

    assert locked.runnable
    assert locked.stage_one_protocol_hash == SPEC.stage_one_protocol_hash
    assert [case["selection_stratum"] for case in envelope["cases"]] == list(
        HEALTH_STRATA
    )
    assert envelope["selection_manifest"]["conflict_exclusions"] == [CONFLICT_WALLET]
    assert len(envelope["selection_manifest"]["eligible_accounts"]) == len(
        frame["accounts"]
    )
    for case in envelope["cases"]:
        assert case["trigger_shortfall_usd"] == E18
        assert case["observation_block"] == FRAME["observation_block"]
        assert set(case["truth"]) == set(health_account_truth(frame["accounts"][0]))


def _locked_envelope(tmp_path):
    repo_root, source_refs, frame = _stage(tmp_path)
    envelope = assemble.assemble_health_envelope(
        SPEC,
        source_refs,
        repo_root=repo_root,
        calibration_dir=_calibration_capture(tmp_path / "calibration"),
        calibration_set=_calibration_bytes(),
        evaluator_calibration=_evaluator_calibration(),
    )
    return repo_root, envelope, frame


def _relock(repo_root: Path, envelope: dict):
    path = repo_root / SPEC.inputs_ref
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(
        (json.dumps(envelope, indent=2, sort_keys=True) + "\n").encode("utf-8")
    )
    return lock_inputs(replace(SPEC, inputs_sha256=""), repo_root=repo_root)


def test_the_lock_refuses_a_tampered_derived_block(tmp_path):
    repo_root, envelope, _frame = _locked_envelope(tmp_path)
    frame_path = repo_root / envelope["selection_manifest"]["source_refs"][0]["ref"]
    frame = json.loads(frame_path.read_text(encoding="utf-8"))
    frame["accounts"][0]["collateral_ratio"] = "1"
    frame_path.write_text(
        json.dumps(frame, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    envelope["selection_manifest"]["source_refs"][0]["sha256"] = hashlib.sha256(
        frame_path.read_bytes()
    ).hexdigest()

    with pytest.raises(ValueError, match="contradicts the guard formula"):
        _relock(repo_root, envelope)


def test_the_lock_refuses_a_market_row_out_of_getassetsin_order(tmp_path):
    repo_root, envelope, _frame = _locked_envelope(tmp_path)
    frame_path = repo_root / envelope["selection_manifest"]["source_refs"][0]["ref"]
    frame = json.loads(frame_path.read_text(encoding="utf-8"))
    row = next(item for item in frame["accounts"] if len(item["markets"]) > 1)
    row["markets"].reverse()
    frame_path.write_text(
        json.dumps(frame, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    envelope["selection_manifest"]["source_refs"][0]["sha256"] = hashlib.sha256(
        frame_path.read_bytes()
    ).hexdigest()

    with pytest.raises(ValueError, match="must follow getAssetsIn"):
        _relock(repo_root, envelope)


def test_the_lock_refuses_an_experiment_party_wallet_in_the_frame(tmp_path):
    repo_root, envelope, _frame = _locked_envelope(tmp_path)
    frame_path = repo_root / envelope["selection_manifest"]["source_refs"][0]["ref"]
    frame = json.loads(frame_path.read_text(encoding="utf-8"))
    intruder = deepcopy(frame["accounts"][0])
    intruder["account"] = CONFLICT_WALLET
    frame["accounts"].append(intruder)
    frame_path.write_text(
        json.dumps(frame, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    envelope["selection_manifest"]["source_refs"][0]["sha256"] = hashlib.sha256(
        frame_path.read_bytes()
    ).hexdigest()

    with pytest.raises(ValueError, match="experiment-party wallet reached"):
        _relock(repo_root, envelope)


def test_the_lock_refuses_a_case_trigger_the_registration_did_not_fix(tmp_path):
    repo_root, envelope, _frame = _locked_envelope(tmp_path)
    envelope["cases"][0]["trigger_shortfall_usd"] = 2 * E18

    with pytest.raises(ValueError, match="Health case contradicts its frozen frame"):
        _relock(repo_root, envelope)


class FakeVenusReader:
    """Just enough of `VenusReader` for `HealthGuardPreview.preview` to run.

    The response shape is taken from the real preview rather than typed out here: a
    hand-written fixture that drifted from `guard.assess` would let the projection pass a
    test while failing the deployed service.
    """

    def __init__(self, address: str, block: int) -> None:
        self.address = address
        self.block = block

    def underlying_of(self, vtoken: str) -> str:
        return {
            catalogue.VENUS_VUSDT.lower(): catalogue.VENUS_USDT,
            catalogue.VENUS_VUSDC.lower(): catalogue.VENUS_USDC,
        }[vtoken.lower()]

    def account(self, address: str) -> markets.AccountState:
        row = markets.MarketPosition(
            vtoken=catalogue.VENUS_VUSDC,
            symbol="vUSDC",
            collateral_factor_mantissa=8 * 10**17,
            snapshot_error=0,
            vtoken_balance=1000 * E18,
            borrow_balance=1000 * E18,
            exchange_rate_mantissa=E18,
            underlying_price_mantissa=E18,
            as_of_block=self.block,
        )
        return markets.AccountState(
            address=address,
            error_code=0,
            liquidity_usd=0,
            shortfall_usd=200 * E18,
            markets_listed=52,
            rows=(row,),
            oracle=ORACLE_ADDRESS,
            as_of_block=self.block,
            reads=("comptroller.getAccountLiquidity",),
        )


def _preview_body(account: str, block: int) -> dict:
    """Exactly what `/hire/health-guard` returns, produced by the real preview class."""
    policy = guard.GuardPolicy(
        markets=(
            guard.MarketPolicy(
                vtoken=catalogue.VENUS_VUSDT,
                underlying=catalogue.VENUS_USDT,
                max_repay=catalogue.GUARD_CAP,
                max_supply=0,
            ),
            guard.MarketPolicy(
                vtoken=catalogue.VENUS_VUSDC,
                underlying=catalogue.VENUS_USDC,
                max_repay=0,
                max_supply=catalogue.GUARD_CAP,
            ),
        ),
        trigger_shortfall_usd=catalogue.GUARD_TRIGGER_USD,
    )
    preview = guard.HealthGuardPreview(
        reader=FakeVenusReader(account, block), policy=policy
    )
    return preview.preview(account)


def _case(account: str, block: int) -> dict:
    return {
        "case_id": "health-shortfall-00000000",
        "account": account,
        "observation_block": block,
        "truth": {"status": "shortfall"},
    }


def test_the_projection_fills_every_registered_health_field():
    block = FRAME["observation_block"]
    projection = scoring.normalise_output(
        SPEC,
        _preview_body(SHORTFALL_ACCOUNT, block),
        case=_case(SHORTFALL_ACCOUNT, block),
    )

    assert tuple(projection) == scoring.HEALTH_FIELDS
    assert all(scoring._has_substance(value) for value in projection.values())
    assert projection["venus"]["publishes_health_factor"] is False
    assert projection["derived_ratio"]["collateral_ratio_is_derived"] is True
    assert projection["cross_check"]["exactly_equal"] is True


def test_a_valid_output_needs_the_registered_account_at_the_registered_block():
    block = FRAME["observation_block"]
    case = _case(SHORTFALL_ACCOUNT, block)
    terminal = {
        "outcome": "succeeded",
        "raw_output": _preview_body(SHORTFALL_ACCOUNT, block),
    }

    assert scoring._valid_completed_output(SPEC, terminal, case, vocabulary=None)

    later = {
        "outcome": "succeeded",
        "raw_output": _preview_body(SHORTFALL_ACCOUNT, block + 1),
    }
    other = {
        "outcome": "succeeded",
        "raw_output": _preview_body(HEADROOM_ACCOUNT, block),
    }

    assert not scoring._valid_completed_output(SPEC, later, case, vocabulary=None)
    assert not scoring._valid_completed_output(SPEC, other, case, vocabulary=None)


def test_the_family_protocol_is_registered_for_scoring():
    protocol = scoring._family(SPEC)

    assert protocol["fields"] == scoring.HEALTH_FIELDS
    assert protocol["family_salt"] == "health-v9-blinding"
    assert (
        protocol["normalisation_version"]
        == (SPEC.execution_protocol["normalisation_version"])
    )


def test_the_calibration_prompt_names_the_health_answer_fields():
    prompt = json.loads(
        calibration.derive_prompt(SPEC, _calibration_bytes(), "seat-a").decode("utf-8")
    )

    assert prompt["prompt_version"] == "v3.calibration-prompt.v5"
    assert (
        "weighted_collateral_usd, borrowed_usd, collateral_ratio"
        in (prompt["instruction"])
    )
    assert "Venus publishes no health factor" in prompt["instruction"]
    assert all("expected" not in case for case in prompt["cases"])


def test_the_preview_the_endpoint_returns_projects_cleanly():
    """The projection is exercised against the real preview object, not a fixture."""
    block = FRAME["observation_block"]
    body = _preview_body(SHORTFALL_ACCOUNT, block)

    assert set(body) >= {"address", "account", "assessment"}
    assert body["assessment"]["status"] == "shortfall"
    assert body["assessment"]["venus"]["publishes_health_factor"] is False
    assert body["submitted"] is False

    projection = scoring.normalise_output(
        SPEC, body, case=_case(SHORTFALL_ACCOUNT, block)
    )

    assert projection["derived_ratio"]["collateral_ratio"] == (
        body["assessment"]["collateral_ratio"]
    )
    assert projection["cross_check"] == body["assessment"]["cross_check"]


def _hire(response_body, payload):
    def post(url, *, json, headers, timeout, client=None):
        assert url == SPEC.execution_protocol["agent_endpoint"]
        return httpx.Response(200, json=response_body)

    return orchestrator.hire_agent(SPEC, payload, hire=post)


def _receipted(result: dict, payload: dict) -> dict:
    return {
        "result": result,
        "receipt": {
            "service": "health-guard",
            "input_hash": runner.canonical_hash(payload),
            "output_hash": runner.canonical_hash(result),
            "payment": {"status": "free_tier"},
        },
    }


def _payload(account: str, block: int) -> dict:
    return {
        "wallet": account,
        "trigger_shortfall_usd": E18,
        "observation_block": block,
        "source_refs": [{"kind": "venus_frame", "ref": "x", "sha256": "0" * 64}],
    }


def test_an_answer_at_the_registered_block_is_not_blocked():
    block = FRAME["observation_block"]
    payload = _payload(SHORTFALL_ACCOUNT, block)
    result = _preview_body(SHORTFALL_ACCOUNT, block)

    outcome = _hire(_receipted(result, payload), payload)

    assert "failure" not in outcome
    assert outcome["raw_output"] == result


def test_an_answer_at_a_later_block_is_a_blocked_service_contract():
    block = FRAME["observation_block"]
    payload = _payload(SHORTFALL_ACCOUNT, block)
    result = _preview_body(SHORTFALL_ACCOUNT, block + 1)

    outcome = _hire(_receipted(result, payload), payload)

    assert outcome["forced_outcome"] == runner.BLOCKED_CONTRACT
    assert outcome["failure"]["kind"] == runner.BLOCKED_CONTRACT
    assert str(block) in outcome["failure"]["message"]


def test_an_answer_about_another_account_is_a_blocked_service_contract():
    block = FRAME["observation_block"]
    payload = _payload(SHORTFALL_ACCOUNT, block)
    result = _preview_body(HEADROOM_ACCOUNT, block)

    outcome = _hire(_receipted(result, payload), payload)

    assert outcome["forced_outcome"] == runner.BLOCKED_CONTRACT
    assert SHORTFALL_ACCOUNT in outcome["failure"]["message"]


def _locked_case(tmp_path):
    repo_root, envelope, frame = _locked_envelope(tmp_path)
    assemble.write_envelope(SPEC, envelope, repo_root=repo_root)
    locked = lock_inputs(SPEC, repo_root=repo_root)
    return repo_root, locked, envelope, frame


def test_the_agent_payload_carries_the_registered_account_block_and_source(tmp_path):
    repo_root, locked, envelope, _frame = _locked_case(tmp_path)
    inputs = json.loads((repo_root / locked.inputs_ref).read_text(encoding="utf-8"))
    case = inputs["cases"][0]

    payload = runner._agent_payload(locked, inputs, case, repo_root)

    assert payload == {
        "wallet": case["account"],
        "trigger_shortfall_usd": E18,
        "observation_block": FRAME["observation_block"],
        "source_refs": envelope["selection_manifest"]["source_refs"],
    }


def test_the_manual_reveal_hands_over_the_pinned_rows_and_withholds_the_truth(tmp_path):
    repo_root, locked, _envelope, frame = _locked_case(tmp_path)
    inputs = json.loads((repo_root / locked.inputs_ref).read_text(encoding="utf-8"))
    case = inputs["cases"][0]
    row = next(
        item for item in frame["accounts"] if item["account"] == case["account"]
    )

    revealed = runner._manual_reveal(locked, inputs, case, repo_root)

    assert "truth" not in revealed
    assert revealed["account"] == case["account"]
    assert revealed["observation_block"] == FRAME["observation_block"]
    assert revealed["frame_ref"].endswith(f"#accounts/{case['account']}")
    # The raw figures are handed over; every derived field is withheld, because deriving
    # them is the task.
    assert revealed["account_state"]["markets"] == row["markets"]
    assert revealed["account_state"]["liquidity_usd"] == row["liquidity_usd"]
    for derived in ("status", "collateral_ratio", "exactly_equal", "difference_usd"):
        assert derived not in revealed["account_state"]


def test_a_frame_row_that_left_every_enumeration_market_still_locks(tmp_path):
    """A borrower who repaid and called exitMarket inside the window is real history.

    Venus auto-enters a market on borrow and lets an account leave once nothing is owed, so
    `getAssetsIn` can legitimately be empty at the pinned block. The frame is first-write
    with no registered recovery, and `case_selection.excluded` names no such condition, so
    refusing it at lock would destroy the collection over a rule nobody registered.
    """
    repo_root, envelope, _frame = _locked_envelope(tmp_path)
    frame_path = repo_root / envelope["selection_manifest"]["source_refs"][0]["ref"]
    frame = json.loads(frame_path.read_text(encoding="utf-8"))
    departed = {
        "account": "0x00000000000000000000000000000000000000d4",
        "entered_markets": [],
        "error_code": 0,
        "liquidity_usd": "0",
        "shortfall_usd": "0",
        "oracle": ORACLE_ADDRESS,
        "complete": True,
        "markets": [],
    }
    departed.update(health_account_truth(departed))
    assert departed["status"] == "no_position"
    frame["accounts"] = sorted(
        frame["accounts"] + [departed], key=lambda row: row["account"]
    )
    frame["rpc_call_accounting"]["getAssetsIn"] += 1
    frame["rpc_call_accounting"]["getAccountLiquidity"] += 1
    frame["rpc_call_accounting"]["total"] += 2
    frame_path.write_text(
        json.dumps(frame, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    envelope["selection_manifest"]["source_refs"][0]["sha256"] = hashlib.sha256(
        frame_path.read_bytes()
    ).hexdigest()
    envelope["selection_manifest"]["eligible_accounts"] = [
        {
            name: row[name]
            for name in ("account", "status", "collateral_ratio", "exactly_equal")
        }
        for row in frame["accounts"]
    ]

    locked = _relock(repo_root, envelope)

    assert locked.runnable
    # It is published in the eligible manifest and fills no stratum on its own merits.
    assert departed["account"] in {
        row["account"] for row in envelope["selection_manifest"]["eligible_accounts"]
    }
    assert departed["account"] not in {case["account"] for case in envelope["cases"]}


def test_the_lock_refuses_call_accounting_the_registered_method_cannot_produce(tmp_path):
    repo_root, envelope, _frame = _locked_envelope(tmp_path)
    frame_path = repo_root / envelope["selection_manifest"]["source_refs"][0]["ref"]
    frame = json.loads(frame_path.read_text(encoding="utf-8"))
    frame["rpc_call_accounting"] = dict.fromkeys(frame["rpc_call_accounting"], 0)
    frame_path.write_text(
        json.dumps(frame, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    envelope["selection_manifest"]["source_refs"][0]["sha256"] = hashlib.sha256(
        frame_path.read_bytes()
    ).hexdigest()

    with pytest.raises(ValueError, match="RPC call accounting"):
        _relock(repo_root, envelope)
