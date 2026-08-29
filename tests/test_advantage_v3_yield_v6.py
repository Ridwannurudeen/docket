import hashlib
import json
from copy import deepcopy
from datetime import datetime, timezone

import pytest

from docket.advantage.v3 import spec as spec_module


ROOT = spec_module.REPO_ROOT
SPEC_PATH = ROOT / "docket/advantage/v3/specs/v3-06-yield-router-assisted.json"
PRIOR_SPEC_PATH = ROOT / "docket/advantage/v3/specs/v3-02-yield-router.json"
CALIBRATION_PATH = (
    ROOT / "docket/advantage/v3/sources/yield-v6-assisted-calibration-set.json"
)
PRIOR_LEDGER_PATH = ROOT / "docket/advantage/v3/runs/v3-02-yield-router.jsonl"
RUNBOOK_PATH = ROOT / "docs/runbooks/yield-v3-06-assisted-run.md"
RANGE_RUNBOOK_PATH = ROOT / "docs/runbooks/range-v3-05-run.md"


def _constructor_record() -> dict:
    record = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    record.pop("stage_one_protocol_hash")
    record.pop("spec_hash")
    return record


def test_v6_is_a_distinct_public_codex_assisted_stage_one_registration():
    spec = spec_module.load(SPEC_PATH, repo_root=ROOT)

    assert spec.spec_id == "v3-06-yield-router-assisted"
    assert spec.inputs_ref.endswith("06-yield-assisted-cases.json")
    assert spec.inputs_sha256 == ""
    assert spec.protocol_correction is None
    assert spec_module.is_yield_family(spec)
    assert spec.arms["agent"]["display_name"] == "Deployed Yield Router"
    assert spec.arms["manual"]["display_name"] == "Codex-assisted baseline"
    assert "deployed Yield Router" in spec.claim
    assert "Codex-assisted baseline" in spec.claim
    assert "human" not in spec.claim.lower()
    assert "manual" not in spec.claim.lower()


def test_v6_capture_schedule_is_hash_bound_and_future_dated():
    spec = spec_module.load(SPEC_PATH, repo_root=ROOT)

    assert spec.case_selection["source_capture_attempts"] == [
        "2026-09-03T12:00:00Z",
        "2026-09-03T12:01:00Z",
        "2026-09-03T12:02:00Z",
    ]
    assert spec_module.yield_capture_attempts(spec) == (
        datetime(2026, 9, 3, 12, 0, tzinfo=timezone.utc),
        datetime(2026, 9, 3, 12, 1, tzinfo=timezone.utc),
        datetime(2026, 9, 3, 12, 2, tzinfo=timezone.utc),
    )

    changed = _constructor_record()
    changed["case_selection"]["source_capture_attempts"][0] = "2026-09-03T11:59:00Z"
    with pytest.raises(ValueError, match="capture schedule"):
        spec_module.PairedSpec(**changed)


def test_v6_readiness_is_unscored_canonical_and_separate_from_official_inputs():
    spec = spec_module.load(SPEC_PATH, repo_root=ROOT)
    readiness = spec.execution_protocol["baseline_readiness"]

    assert readiness["required_before_primary"] is True
    assert readiness["scored"] is False
    assert readiness["expected_output"] == spec_module._yield_readiness_output(
        readiness["fixture"]
    )
    assert readiness["expected_output"]["decision"] == {
        "move_or_stay": "MOVE",
        "destination_pool_id": "0x0000000000000000000000000000000000000012",
        "rule": (
            "Highest eligible net APR; lowercase pool-address ascending tie-break; "
            "MOVE only for a positive delta recovered within 30 days"
        ),
    }

    changed = _constructor_record()
    changed["execution_protocol"]["baseline_readiness"]["fixture"][
        "official_input_ref"
    ] = "docket/advantage/v3/inputs/06-yield-assisted-cases.json"
    with pytest.raises(ValueError, match="self-contained"):
        spec_module.PairedSpec(**changed)


def test_v6_provenance_matches_the_published_failed_v3_02_primary():
    spec = spec_module.load(SPEC_PATH, repo_root=ROOT)
    provenance = spec.successor_provenance
    prior = spec_module.load(PRIOR_SPEC_PATH, repo_root=ROOT)
    events = [
        json.loads(line)
        for line in PRIOR_LEDGER_PATH.read_text(encoding="utf-8").splitlines()
    ]
    terminal = [event for event in events if event["kind"] == "attempt_terminated"]

    assert provenance == {
        "status": "distinct_successor_after_failed_primary",
        "prior_spec_id": "v3-02-yield-router",
        "prior_stage_one_protocol_hash": prior.stage_one_protocol_hash,
        "prior_spec_hash": prior.spec_hash,
        "prior_ledger_ref": "docket/advantage/v3/runs/v3-02-yield-router.jsonl",
        "reason": spec_module.YIELD_SUCCESSOR_REASON,
    }
    assert hashlib.sha256(PRIOR_LEDGER_PATH.read_bytes()).hexdigest() == (
        "b69e61e72c460b89c54dae65eb0f1ba66402391bfc28942dccb4aacf6fb84610"
    )
    assert len(terminal) == 1
    assert terminal[0]["slot"] == (
        "v3-02-yield-router::yield-01-916f992d::manual::primary"
    )
    assert terminal[0]["outcome"] == "failed"
    assert terminal[0]["failure"]["kind"] == "invoke_error"
    assert terminal[0]["elapsed_ns"] == 11219000000


def test_v6_calibration_is_a_new_eight_case_successor_bound_artifact():
    body = json.loads(CALIBRATION_PATH.read_text(encoding="utf-8"))
    spec = spec_module.load(SPEC_PATH, repo_root=ROOT)

    assert body["spec_id"] == spec.spec_id
    assert len(body["cases"]) == 8
    assert len({case["case_id"] for case in body["cases"]}) == 8
    assert all(case["case_id"].startswith("y6-cal-") for case in body["cases"])
    for case in body["cases"]:
        computed = spec_module._computed_calibration_truth(spec, case["input"])
        assert spec_module._calibration_truth_matches(case["expected"], computed)


def test_existing_v3_02_record_serializes_without_a_new_field_or_hash_change():
    original = json.loads(PRIOR_SPEC_PATH.read_text(encoding="utf-8"))
    loaded = spec_module.load(PRIOR_SPEC_PATH, repo_root=ROOT)

    assert loaded.as_record() == original
    assert "successor_provenance" not in loaded.as_record()
    assert loaded.stage_one_protocol_hash == (
        "0x10d0fb31ea70c4bb31581952b99b6776d5f25d2c51bdf9543d47d07781266d3c"
    )
    assert loaded.spec_hash == (
        "0xad391e9aa3b039ee5e43397d488deb25893253d3376b08ff544c5651566395d9"
    )


@pytest.mark.parametrize(
    ("path", "value", "message"),
    [
        (("protocol_correction",), {}, "distinct successor"),
        (
            ("successor_provenance", "status"),
            "corrected_before_input_lock",
            "successor provenance",
        ),
        (
            ("arms", "manual", "display_name"),
            "Manual operator",
            "display names",
        ),
        (
            ("execution_protocol", "baseline_identity", "human_or_independent"),
            True,
            "baseline identity",
        ),
    ],
)
def test_v6_rejects_a_relabelled_or_mutated_successor(path, value, message):
    record = _constructor_record()
    target = record
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = deepcopy(value)

    with pytest.raises(ValueError, match=message):
        spec_module.PairedSpec(**record)


def test_v6_has_a_registered_yield_input_validator():
    assert (
        spec_module.INPUT_VALIDATORS["v3-06-yield-router-assisted"]
        is spec_module._validate_yield_inputs
    )


def test_v6_runbook_seeds_the_atomic_lock_file_before_saving_stage_two():
    runbook = RUNBOOK_PATH.read_text(encoding="utf-8")

    assert "temporary.write_bytes(path.read_bytes())" in runbook
    assert "save(locked, temporary, repo_root=root)" in runbook
    assert runbook.index("temporary.write_bytes(path.read_bytes())") < runbook.index(
        "save(locked, temporary, repo_root=root)"
    )


def test_v6_runbook_has_concrete_calibration_and_scoring_closeout_checks():
    runbook = RUNBOOK_PATH.read_text(encoding="utf-8")

    assert "verify_calibration_capture" in runbook
    assert "assemble_evaluator_calibration" in runbook
    assert "export_evaluation_sessions" in runbook
    assert "import_evaluation_submission" in runbook
    assert "publish_mapping" in runbook
    assert "report.report" in runbook


def test_v5_runbook_marks_completed_capture_and_lock_stages_historical():
    runbook = RANGE_RUNBOOK_PATH.read_text(encoding="utf-8")

    assert "Stages 0-3 are historical and must not be rerun" in runbook
    assert "assert_runnable(spec, repo_root=root)" in runbook
