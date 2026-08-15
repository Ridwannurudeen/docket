"""The deterministic half of v3, from raw arm outputs to published scores.

The evaluator sees only a registered projection and opaque A/B labels. These tests attack
the choices that would otherwise be made after the outputs exist: hash bytes, polarity,
case order, replacement sheets, missing failures, speed denominators and Warden's gates.
"""

import hashlib
import json
from pathlib import Path

import pytest

import docket.advantage.v3.spec as spec_module
from docket.advantage.v3 import runner, scoring
from docket.advantage.v3.spec import PairedSpec, load, lock_inputs, save
from docket.hire.receipts import canonical_hash

from test_advantage_v3_spec import SPECS_DIR, _input_record, _source_ref


def _locked_family(tmp_path: Path, monkeypatch, spec_id: str):
    """One real registered protocol with synthetic bytes and no family-truth distraction."""
    registered = load(SPECS_DIR / f"{spec_id}.json")
    body = registered._stage_one_body() | {"inputs_ref": "inputs.json"}
    stage_one = PairedSpec(**body)
    monkeypatch.setitem(
        spec_module.INPUT_VALIDATORS,
        spec_id,
        lambda _spec, _body, _cases, _repo_root: None,
    )
    inputs = _input_record(stage_one)
    if spec_id == "v3-03-warden-security":
        # Warden's calibration classes are checked against the vendor's published list, so
        # even an envelope built to avoid family truth carries the snapshot that names it.
        inputs["vendor_snapshot"] = _source_ref(
            tmp_path,
            "evidence/vendor.json",
            b'{"classes":["class-0","class-1","class-2","class-3"]}\n',
        )
    path = tmp_path / stage_one.inputs_ref
    path.write_text(json.dumps(inputs, sort_keys=True) + "\n", encoding="utf-8")
    spec_path = tmp_path / "specs" / f"{spec_id}.json"
    save(stage_one, spec_path, repo_root=tmp_path)
    locked = lock_inputs(stage_one, repo_root=tmp_path)
    save(locked, spec_path, repo_root=tmp_path)
    return locked, inputs


def _append_attempt(
    spec,
    ledger: Path,
    case_id: str,
    arm: str,
    *,
    outcome: str = runner.SUCCEEDED,
    elapsed_seconds: float = 40,
    output=None,
    cost=None,
):
    header = {
        "stage_one_protocol_hash": spec.stage_one_protocol_hash,
        "spec_hash": spec.spec_hash,
        "inputs_sha256": spec.inputs_sha256,
        "inputs_ref": spec.inputs_ref,
    }
    slot = runner.slot_id(spec.spec_id, case_id, arm)
    runner.append_event(
        ledger,
        {
            "kind": runner.STARTED,
            "slot": slot,
            "spec_id": spec.spec_id,
            "case_id": case_id,
            "arm": arm,
            "attempt_kind": runner.PRIMARY,
            "started_at": "2026-09-01T00:00:00+00:00",
            "started_monotonic_ns": 1,
            "case_binding": {},
            **header,
        },
    )
    runner.append_event(
        ledger,
        {
            "kind": runner.TERMINATED,
            "slot": slot,
            "spec_id": spec.spec_id,
            "case_id": case_id,
            "arm": arm,
            "attempt_kind": runner.PRIMARY,
            "outcome": outcome,
            "finished_at": "2026-09-01T00:10:00+00:00",
            "finished_monotonic_ns": 1 + int(elapsed_seconds * 1_000_000_000),
            "elapsed_ns": int(elapsed_seconds * 1_000_000_000),
            "eligible_for_speed": outcome == runner.SUCCEEDED,
            "output_sha256": None if output is None else canonical_hash(output),
            "raw_output": output,
            "failure": None if outcome == runner.SUCCEEDED else {"kind": outcome},
            "cost": cost,
            "receipt": None,
            **header,
        },
    )


def _range_output(service_name: str = "Range Doctor") -> dict:
    return {
        "position": {"token_id": 7, "summary": f"{service_name} read the exact NFT"},
        "observation": {"block": 123, "time": "2026-08-21T12:00:00Z"},
        "range": {"status": "in_range", "ticks": [-10, 0, 10]},
        "pool_evidence": {"source": "frozen row", "request_id": "remove-me"},
        "rates": {"gross_apr": 0.2, "net_apr": 0.15},
        "dollars": {"annual_overstatement_usd": 500},
        "action": {"decision": "WAIT"},
        "coverage": {"positions_held": 1, "scan_complete": True},
        "limitations": "One 24-hour observation, not a forecast.",
        "sources": [{"url": "https://example.test/source", "sha256": "a" * 64}],
        "receipt": {"service": "range-doctor", "price": "0.50"},
        "presentation": {"format": "markdown"},
    }


def _complete_range_ledger(spec, inputs: dict, ledger: Path, *, failed=None):
    failed = failed or set()
    for index, case in enumerate(inputs["cases"]):
        for arm in ("manual", "agent"):
            identity = (case["case_id"], arm)
            outcome = runner.FAILED if identity in failed else runner.SUCCEEDED
            _append_attempt(
                spec,
                ledger,
                case["case_id"],
                arm,
                outcome=outcome,
                elapsed_seconds=100 if arm == "manual" else 40,
                output=None if outcome != runner.SUCCEEDED else _range_output(),
                cost={
                    "amount": "0.50" if arm == "agent" else "0",
                    "unit": "$U",
                    "note": "recorded direct cost",
                },
            )


def _score_sheet(spec, bundle: dict, score_by_arm: dict, *, seat_id: str) -> bytes:
    mapping = scoring.derive_blinding(
        spec, [case["case_id"] for case in _input_record(spec)["cases"]]
    )
    arm_by_label = {
        (case["case_label"], label): arm
        for case in mapping["cases"]
        for label, arm in case["arms"].items()
    }
    rows = []
    for case in bundle["cases"]:
        for output in case["outputs"]:
            if not output["judgment_required"]:
                continue
            arm = arm_by_label[(case["case_label"], output["arm_label"])]
            for criterion in spec.quality_rubric["criteria"]:
                rows.append(
                    {
                        "case_label": case["case_label"],
                        "arm_label": output["arm_label"],
                        "criterion": criterion["name"],
                        "score": score_by_arm[arm],
                        "rationale": f"The {arm} output meets score {score_by_arm[arm]}.",
                        "evidence_quote": f"quoted {arm} evidence",
                    }
                )
    sheet = {
        "spec_id": spec.spec_id,
        "spec_hash": spec.spec_hash,
        "evaluator_id": seat_id,
        "blinded_bundle_hash": canonical_hash(bundle),
        "scores": rows,
    }
    return (json.dumps(sheet, sort_keys=True) + "\n").encode()


def test_projection_keeps_only_registered_substance_and_replaces_the_service_literal(
    tmp_path, monkeypatch
):
    spec, _ = _locked_family(tmp_path, monkeypatch, "v3-01-range-doctor")
    raw = {
        "result": _range_output(),
        "receipt": {"service": "range-doctor"},
        "http_status": 200,
        "elapsed_ns": 5,
    }

    projected = scoring.normalise_output(spec, raw)

    assert list(projected) == [
        "position",
        "observation",
        "range",
        "pool_evidence",
        "rates",
        "dollars",
        "action",
        "coverage",
        "limitations",
        "sources",
    ]
    assert projected["position"]["summary"] == "[SERVICE] read the exact NFT"
    assert projected["limitations"] == "One 24-hour observation, not a forecast."
    assert "request_id" not in projected["pool_evidence"]
    assert "receipt" not in json.dumps(projected).lower()
    assert projected["sources"][0]["sha256"] == "a" * 64


def test_a_b_assignment_uses_the_registered_text_then_raw_seed_bytes(
    tmp_path, monkeypatch
):
    spec, inputs = _locked_family(tmp_path, monkeypatch, "v3-01-range-doctor")
    case_ids = [case["case_id"] for case in inputs["cases"]]

    derived = scoring.derive_blinding(spec, case_ids)
    expected_seed = hashlib.sha256(
        spec.stage_one_protocol_hash.encode()
        + spec.inputs_sha256.encode()
        + b"range-blinding"
    ).digest()

    assert derived["seed_sha256"] == expected_seed.hex()
    assert derived["family_salt"] == "range-blinding"
    for case in derived["cases"]:
        case_id = case["case_id"]
        arm_digest = hashlib.sha256(expected_seed + case_id.encode() + b"arm").digest()
        order_digest = hashlib.sha256(
            expected_seed + case_id.encode() + b"order"
        ).digest()
        assert case["arm_digest"] == arm_digest.hex()
        assert case["order_digest"] == order_digest.hex()
        assert case["arms"]["A"] == ("agent" if arm_digest[-1] % 2 == 0 else "manual")
    assert [case["order_digest"] for case in derived["cases"]] == sorted(
        case["order_digest"] for case in derived["cases"]
    )


def test_bundle_exposes_truth_under_opaque_labels_but_withholds_mapping_and_raw_outputs(
    tmp_path, monkeypatch
):
    spec, inputs = _locked_family(tmp_path, monkeypatch, "v3-01-range-doctor")
    ledger = tmp_path / "runs" / f"{spec.spec_id}.jsonl"
    failed = {(inputs["cases"][0]["case_id"], "agent")}
    _complete_range_ledger(spec, inputs, ledger, failed=failed)

    bundle = scoring.build_blinded_bundle(spec, ledger, repo_root=tmp_path)

    assert (
        bundle["normalisation_version"]
        == spec.execution_protocol["normalisation_version"]
    )
    assert all(case["reference"]["truth"] is not None for case in bundle["cases"])
    assert all("case_id" not in case["reference"] for case in bundle["cases"])
    assert "raw_output" not in json.dumps(bundle)
    assert "range-doctor" not in json.dumps(bundle["cases"]).lower()
    assert all("case_id" not in case for case in bundle["cases"])
    automatic = [
        output
        for case in bundle["cases"]
        for output in case["outputs"]
        if not output["judgment_required"]
    ]
    assert automatic == [
        {
            "arm_label": automatic[0]["arm_label"],
            "judgment_required": False,
            "automatic_scores": {
                criterion["name"]: 0 for criterion in spec.quality_rubric["criteria"]
            },
            "outcome": runner.FAILED,
        }
    ]


def test_a_success_record_with_an_empty_answer_is_a_zero_not_a_speed_pair(
    tmp_path, monkeypatch
):
    spec, inputs = _locked_family(tmp_path, monkeypatch, "v3-01-range-doctor")
    malformed_case = inputs["cases"][0]["case_id"]
    ledger = tmp_path / "runs" / f"{spec.spec_id}.jsonl"
    _complete_range_ledger(spec, inputs, ledger)
    events = runner.read_events(ledger)
    terminal = next(
        event
        for event in events
        if event["kind"] == runner.TERMINATED
        and event["case_id"] == malformed_case
        and event["arm"] == "agent"
    )
    terminal["raw_output"] = {}
    terminal["output_sha256"] = canonical_hash({})
    ledger.write_text(
        "".join(json.dumps(event, sort_keys=True) + "\n" for event in events),
        encoding="utf-8",
    )

    bundle = scoring.build_blinded_bundle(spec, ledger, repo_root=tmp_path)
    attempts = scoring.primary_attempts(spec, ledger, repo_root=tmp_path)
    mapping = scoring.derive_blinding(
        spec, [case["case_id"] for case in inputs["cases"]]
    )
    assigned = next(
        case for case in mapping["cases"] if case["case_id"] == malformed_case
    )
    blinded_case = next(
        case for case in bundle["cases"] if case["case_label"] == assigned["case_label"]
    )
    arm_label = next(label for label, arm in assigned["arms"].items() if arm == "agent")
    output = next(
        output for output in blinded_case["outputs"] if output["arm_label"] == arm_label
    )

    assert output["outcome"] == "malformed_output"
    assert output["judgment_required"] is False
    assert all(score == 0 for score in output["automatic_scores"].values())
    assert (
        scoring.speed_metrics(spec, attempts)["n_complete_pairs"] == spec.n_planned - 1
    )


def test_range_validity_rejects_wrong_token_block_source_or_coverage(
    tmp_path, monkeypatch
):
    spec, inputs = _locked_family(tmp_path, monkeypatch, "v3-01-range-doctor")
    snapshots = {
        "pools": {"url": "pools", "observed_at": "t1", "sha256": "a" * 64},
        "token_list": {
            "url": "tokens",
            "observed_at": "t2",
            "sha256": "b" * 64,
        },
    }
    pool_truth = tmp_path / "pool-truth.json"
    pool_truth.write_text(
        json.dumps(
            {
                "source_snapshots": {
                    name: value | {"attempt_ordinal": 1, "body_base64": "e30="}
                    for name, value in snapshots.items()
                }
            }
        ),
        encoding="utf-8",
    )
    source = {
        "kind": "pool_truth",
        "ref": pool_truth.name,
        "sha256": hashlib.sha256(pool_truth.read_bytes()).hexdigest(),
    }
    case = {
        "case_id": "range-1",
        "wallet": "0x" + "1" * 40,
        "token_id": 7,
        "observation_block": 123,
        "observation_time": "2026-08-21T12:00:00Z",
        "source_refs": [source],
        "truth": {
            "positions_held": 1,
            "positions_examined": 1,
            "closed_skipped": 0,
            "scan_complete": True,
        },
    }
    output = _range_output() | {
        "sources": snapshots | {"source_refs": [source]},
        "coverage": {
            "positions_held": 1,
            "positions_examined": 1,
            "closed_skipped": 0,
            "scan_complete": True,
        },
    }

    def valid(raw):
        return scoring._valid_completed_output(
            spec,
            {"outcome": runner.SUCCEEDED, "raw_output": raw},
            case,
            inputs=inputs,
            repo_root=tmp_path,
            vocabulary=None,
        )

    assert valid(output) is True
    for changed in (
        output | {"position": {"token_id": 8}},
        output | {"observation": {"block": 124, "time": case["observation_time"]}},
        output | {"sources": output["sources"] | {"pools": {"sha256": "c" * 64}}},
        output | {"coverage": output["coverage"] | {"scan_complete": False}},
    ):
        assert valid(changed) is False


def test_yield_validity_rejects_a_wrong_snapshot_or_incomplete_universe(
    tmp_path, monkeypatch
):
    spec, _inputs = _locked_family(tmp_path, monkeypatch, "v3-02-yield-router")
    sources = {
        "pools": {"url": "pools", "observed_at": "t1", "sha256": "a" * 64},
        "token_list": {
            "url": "tokens",
            "observed_at": "t2",
            "sha256": "b" * 64,
        },
    }
    inputs = {
        "source_snapshots": {
            name: value | {"attempt_ordinal": 1, "body_base64": "e30="}
            for name, value in sources.items()
        },
        "truth_manifest": {
            "raw_pool_ids": ["0xaaa", "0xbbb"],
            "included_pool_ids": ["0xaaa"],
            "excluded": [{"pool_id": "0xbbb", "first_failed_gate": "tvl_floor"}],
        },
    }
    case = {"case_id": "yield-1", "pool_id": "0xaaa"}
    output = {
        "sources": sources,
        "universe": {
            "included": [{"pool_id": "0xaaa"}],
            "excluded": [{"pool_id": "0xbbb", "first_failed_gate": "tvl_floor"}],
        },
        "rates": {"current": {"pool_id": "0xaaa"}, "candidates": [{}]},
        "scenario": [{"days": 1}],
        "decision": "STAY",
        "limitations": "bounded",
    }

    def valid(raw):
        return scoring._valid_completed_output(
            spec,
            {"outcome": runner.SUCCEEDED, "raw_output": raw},
            case,
            inputs=inputs,
            repo_root=tmp_path,
            vocabulary=None,
        )

    assert valid(output) is True
    assert (
        valid(output | {"sources": sources | {"pools": {"sha256": "c" * 64}}}) is False
    )
    assert (
        valid(
            output | {"universe": {"included": [{"pool_id": "0xaaa"}], "excluded": []}}
        )
        is False
    )


def test_one_first_write_sheet_per_seat_precedes_mapping_publication(
    tmp_path, monkeypatch
):
    spec, inputs = _locked_family(tmp_path, monkeypatch, "v3-01-range-doctor")
    ledger = tmp_path / "runs" / f"{spec.spec_id}.jsonl"
    _complete_range_ledger(spec, inputs, ledger)
    bundle = scoring.build_blinded_bundle(spec, ledger, repo_root=tmp_path)
    sheets_dir = tmp_path / "sheets"
    mapping_dir = tmp_path / "mappings"
    seats = [row["evaluator_id"] for row in spec.scoring["evaluator_roster"]]
    first_raw = _score_sheet(spec, bundle, {"agent": 3, "manual": 2}, seat_id=seats[0])

    first = scoring.ingest_score_sheet(spec, bundle, first_raw, sheets_dir)
    assert first["raw_sheet_sha256"] == hashlib.sha256(first_raw).hexdigest()
    assert first["score_sheet_hash"] == canonical_hash(json.loads(first_raw.decode()))
    with pytest.raises(ValueError, match="already submitted"):
        scoring.ingest_score_sheet(spec, bundle, first_raw, sheets_dir)
    with pytest.raises(ValueError, match="both score sheets"):
        scoring.publish_mapping(
            spec, bundle, sheets_dir, mapping_dir, repo_root=tmp_path
        )

    second_raw = _score_sheet(spec, bundle, {"agent": 3, "manual": 2}, seat_id=seats[1])
    second = scoring.ingest_score_sheet(spec, bundle, second_raw, sheets_dir)
    mapping = scoring.publish_mapping(
        spec, bundle, sheets_dir, mapping_dir, repo_root=tmp_path
    )

    assert mapping["blinded_bundle_hash"] == canonical_hash(bundle)
    assert mapping["score_sheets"] == [
        {
            "evaluator_id": first["evaluator_id"],
            "score_sheet_hash": first["score_sheet_hash"],
            "raw_sheet_sha256": first["raw_sheet_sha256"],
        },
        {
            "evaluator_id": second["evaluator_id"],
            "score_sheet_hash": second["score_sheet_hash"],
            "raw_sheet_sha256": second["raw_sheet_sha256"],
        },
    ]
    assert mapping["mapping_hash"] == canonical_hash(
        {key: value for key, value in mapping.items() if key != "mapping_hash"}
    )


def test_harness_exports_isolated_sessions_and_imports_the_first_sheet(
    tmp_path, monkeypatch
):
    spec, inputs = _locked_family(tmp_path, monkeypatch, "v3-01-range-doctor")
    runs = tmp_path / "runs"
    ledger = runs / f"{spec.spec_id}.jsonl"
    _complete_range_ledger(spec, inputs, ledger)
    harness = runner.ExperimentHarness(spec, runs, repo_root=tmp_path)

    sessions = harness.export_evaluation_sessions(tmp_path / "sessions")
    exported = json.loads(sessions[0].read_text(encoding="utf-8"))
    bundle = exported["bundle"]
    assert len(sessions) == len(spec.scoring["evaluator_roster"])
    assert "mapping" not in exported

    seat = spec.scoring["evaluator_roster"][0]["evaluator_id"]
    raw = _score_sheet(spec, bundle, {"agent": 3, "manual": 2}, seat_id=seat)
    artifact = harness.import_evaluation_submission(raw, tmp_path / "sheets")
    assert artifact["evaluator_id"] == seat


def test_failed_outputs_are_fixed_zeros_and_disagreements_are_published(
    tmp_path, monkeypatch
):
    spec, inputs = _locked_family(tmp_path, monkeypatch, "v3-01-range-doctor")
    failed_case = inputs["cases"][0]["case_id"]
    ledger = tmp_path / "runs" / f"{spec.spec_id}.jsonl"
    _complete_range_ledger(spec, inputs, ledger, failed={(failed_case, "agent")})
    bundle = scoring.build_blinded_bundle(spec, ledger, repo_root=tmp_path)
    sheets_dir = tmp_path / "sheets"
    seats = [row["evaluator_id"] for row in spec.scoring["evaluator_roster"]]
    first_raw = _score_sheet(spec, bundle, {"agent": 3, "manual": 2}, seat_id=seats[0])
    second = json.loads(
        _score_sheet(spec, bundle, {"agent": 3, "manual": 2}, seat_id=seats[1])
    )
    second["scores"][0]["score"] = 0
    second["scores"][0]["rationale"] = "The second seat found the anchor absent."
    second_raw = (json.dumps(second, sort_keys=True) + "\n").encode()
    scoring.ingest_score_sheet(spec, bundle, first_raw, sheets_dir)
    scoring.ingest_score_sheet(spec, bundle, second_raw, sheets_dir)
    mapping = scoring.publish_mapping(
        spec,
        bundle,
        sheets_dir,
        tmp_path / "mappings",
        repo_root=tmp_path,
    )

    quality = scoring.aggregate_rubric(
        spec, bundle, sheets_dir, mapping, repo_root=tmp_path
    )

    failed = next(
        row
        for row in quality["outputs"]
        if row["case_id"] == failed_case and row["arm"] == "agent"
    )
    assert failed["automatic_zero"] is True
    assert failed["total"] == 0
    assert all(value == 0 for value in failed["criteria"].values())
    assert quality["arms"]["agent"]["n_outputs"] == spec.n_planned
    assert quality["arms"]["manual"]["n_outputs"] == spec.n_planned
    assert quality["disagreements"][0]["gap"] >= 2
    assert len(quality["disagreements"][0]["seat_records"]) == 2

    tampered = json.loads(json.dumps(mapping))
    original_arms = tampered["cases"][0]["arms"]
    tampered["cases"][0]["arms"] = {
        "A": original_arms["B"],
        "B": original_arms["A"],
    }
    tampered["mapping_hash"] = canonical_hash(
        {key: value for key, value in tampered.items() if key != "mapping_hash"}
    )
    with pytest.raises(ValueError, match="deterministic assignment"):
        scoring.aggregate_rubric(spec, bundle, sheets_dir, tampered, repo_root=tmp_path)


def test_speed_requires_every_successful_pair_and_both_registered_thresholds(
    tmp_path, monkeypatch
):
    spec, inputs = _locked_family(tmp_path, monkeypatch, "v3-01-range-doctor")
    ledger = tmp_path / "runs" / f"{spec.spec_id}.jsonl"
    _complete_range_ledger(spec, inputs, ledger)
    attempts = scoring.primary_attempts(spec, ledger, repo_root=tmp_path)

    speed = scoring.speed_metrics(spec, attempts)

    assert speed["n_complete_pairs"] == spec.n_planned
    assert speed["median_seconds_saved"] == 60
    assert speed["median_agent_to_manual_ratio"] == 0.4
    assert speed["material"] is True

    attempts[(inputs["cases"][0]["case_id"], "agent")]["terminal"][
        "eligible_for_speed"
    ] = False
    incomplete = scoring.speed_metrics(spec, attempts)
    assert incomplete["n_complete_pairs"] == spec.n_planned - 1
    assert incomplete["complete_pairs_required"] is False
    assert incomplete["material"] is False


def test_warden_metrics_keep_failures_in_recall_reliability_and_critical_gates(
    tmp_path, monkeypatch
):
    spec, inputs = _locked_family(tmp_path, monkeypatch, "v3-03-warden-security")
    cases = []
    for index in range(12):
        hostile = index < 8
        critical = index < 2
        text = "Warden vector-2" if index == 1 else f"vector-{index + 1}"
        cases.append(
            {
                "case_id": f"case-{index + 1}",
                "payload_id": f"payload-{index + 1}",
                "text": text,
                "expected_verdict": "BLOCK" if hostile else "ALLOW",
                "labels": ["class-0"] if hostile else [],
                "evidence_spans": [],
                "hostile": hostile,
                "critical": critical,
                "survival_predicates": (
                    [{"kind": "literal", "pattern": text}] if critical else []
                ),
            }
        )
    inputs["cases"] = cases
    ledger = tmp_path / "runs" / f"{spec.spec_id}.jsonl"
    for case in cases:
        for arm in ("manual", "agent"):
            failed = arm == "agent" and case["case_id"] == "case-1"
            output = None
            if not failed:
                verdict = (
                    "ALLOW"
                    if not case["hostile"] or case["case_id"] == "case-2"
                    else "BLOCK"
                )
                output = {
                    "verdict": verdict,
                    "risk_level": "LOW" if verdict == "ALLOW" else "HIGH",
                    "threat_classes": ([] if verdict == "ALLOW" else case["labels"]),
                    "detections": [],
                    "sanitized_payload": None,
                    "recommendation": "Use the registered checks.",
                    "checks": {"fixture": True},
                }
            _append_attempt(
                spec,
                ledger,
                case["case_id"],
                arm,
                outcome=runner.FAILED if failed else runner.SUCCEEDED,
                elapsed_seconds=40 if arm == "agent" else 100,
                output=output,
            )
    attempts = scoring.primary_attempts(spec, ledger, repo_root=tmp_path)

    metrics = scoring.warden_metrics(spec, inputs, attempts)

    agent = metrics["arms"]["agent"]
    assert agent["recall"] == {"numerator": 6, "denominator": 8, "value": 0.75}
    assert agent["precision"] == {"numerator": 6, "denominator": 6, "value": 1.0}
    assert agent["successful_scans"] == {
        "numerator": 11,
        "denominator": 12,
        "value": 11 / 12,
    }
    assert {row["case_id"] for row in agent["critical_gate_failures"]} == {
        "case-1",
        "case-2",
    }
    assert metrics["gates"]["absolute_recall"] is False
    assert metrics["gates"]["all_agent_scans_succeeded"] is False
    assert metrics["gates"]["zero_critical_survivors"] is False

    speed = scoring.speed_metrics(spec, attempts, inputs=inputs, repo_root=tmp_path)
    assert speed["n_complete_pairs"] == 11
    attempts[("case-3", "agent")]["terminal"]["raw_output"]["verdict"] = "REWRITE"
    assert (
        scoring.speed_metrics(spec, attempts, inputs=inputs, repo_root=tmp_path)[
            "n_complete_pairs"
        ]
        == 10
    )


def test_yield_completeness_requires_the_exact_partition_and_frozen_sources(
    tmp_path, monkeypatch
):
    spec, locked_inputs = _locked_family(tmp_path, monkeypatch, "v3-02-yield-router")
    expected_sources = {
        "pools": {
            "url": "https://example.test/pools",
            "observed_at": "2026-08-21T12:00:01Z",
            "sha256": "a" * 64,
        },
        "token_list": {
            "url": "https://example.test/tokens",
            "observed_at": "2026-08-21T12:00:02Z",
            "sha256": "b" * 64,
        },
    }
    inputs = locked_inputs | {
        "source_snapshots": {
            name: value | {"attempt_ordinal": 1, "body_base64": "e30="}
            for name, value in expected_sources.items()
        },
        "truth_manifest": {
            "raw_pool_ids": ["0xaaa", "0xbbb"],
            "included_pool_ids": ["0xaaa"],
            "excluded": [{"pool_id": "0xbbb", "reason": "tvl_floor"}],
        },
    }
    output = {
        "sources": expected_sources,
        "universe": {
            "included_pool_ids": ["0xaaa"],
            "excluded": [{"pool_id": "0xbbb", "reason": "tvl_floor"}],
        },
        "rates": {},
        "scenario": {},
        "decision": "STAY",
        "limitations": "Bounded to the frozen response.",
    }
    ledger = tmp_path / "runs" / f"{spec.spec_id}.jsonl"
    for case in locked_inputs["cases"]:
        for arm in ("manual", "agent"):
            _append_attempt(
                spec,
                ledger,
                case["case_id"],
                arm,
                output=output,
                elapsed_seconds=100 if arm == "manual" else 40,
            )
    attempts = scoring.primary_attempts(spec, ledger, repo_root=tmp_path)

    complete = scoring.yield_completeness(spec, inputs, attempts)

    assert complete["n_complete_and_correct"] == spec.n_planned
    assert complete["complete_and_correct"] is True

    attempts[(locked_inputs["cases"][0]["case_id"], "agent")]["terminal"]["raw_output"][
        "sources"
    ] = expected_sources | {"pools": expected_sources["pools"] | {"sha256": "c" * 64}}
    changed = scoring.yield_completeness(spec, inputs, attempts)
    assert changed["n_complete_and_correct"] == spec.n_planned - 1
    assert changed["complete_and_correct"] is False


def test_a_blocked_service_contract_never_becomes_a_rubric_zero(tmp_path, monkeypatch):
    spec, inputs = _locked_family(tmp_path, monkeypatch, "v3-01-range-doctor")
    ledger = tmp_path / "runs" / f"{spec.spec_id}.jsonl"
    _complete_range_ledger(
        spec,
        inputs,
        ledger,
        failed={(inputs["cases"][0]["case_id"], "agent")},
    )
    events = runner.read_events(ledger)
    events[-1]["outcome"] = runner.BLOCKED_CONTRACT
    events[-1]["eligible_for_speed"] = False
    events[-1]["failure"] = {"kind": runner.BLOCKED_CONTRACT}
    ledger.write_text(
        "".join(json.dumps(event, sort_keys=True) + "\n" for event in events),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="blocked service contract"):
        scoring.build_blinded_bundle(spec, ledger, repo_root=tmp_path)


def test_a_manual_primary_cannot_be_relabelled_as_a_blocked_service_contract(
    tmp_path, monkeypatch
):
    spec, inputs = _locked_family(tmp_path, monkeypatch, "v3-01-range-doctor")
    ledger = tmp_path / "runs" / f"{spec.spec_id}.jsonl"
    _complete_range_ledger(spec, inputs, ledger)
    events = runner.read_events(ledger)
    manual = next(
        event
        for event in events
        if event["kind"] == runner.TERMINATED and event["arm"] == "manual"
    )
    manual["outcome"] = runner.BLOCKED_CONTRACT
    manual["eligible_for_speed"] = False
    ledger.write_text(
        "".join(json.dumps(event, sort_keys=True) + "\n" for event in events),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="only for an agent primary"):
        scoring.primary_attempts(spec, ledger, repo_root=tmp_path)
