import json
from copy import deepcopy
from datetime import datetime, timezone

import pytest

from docket.advantage.v3 import capture, range_capture
from docket.advantage.v3 import spec as spec_module


ROOT = spec_module.REPO_ROOT
SPEC_PATH = ROOT / "docket/advantage/v3/specs/v3-07-range-doctor.json"
PRIOR_SPEC_PATH = ROOT / "docket/advantage/v3/specs/v3-05-range-doctor.json"
CALIBRATION_PATH = ROOT / "docket/advantage/v3/sources/range-v7-calibration-set.json"
RUNBOOK_PATH = ROOT / "docs/runbooks/range-v3-07-run.md"
DEPLOY = ROOT / "deploy"


def _constructor_record() -> dict:
    record = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    record.pop("stage_one_protocol_hash")
    record.pop("spec_hash")
    return record


def test_v7_is_a_distinct_human_versus_paid_hire_stage_one_registration():
    spec = spec_module.load(SPEC_PATH, repo_root=ROOT)

    assert spec.spec_id == "v3-07-range-doctor"
    assert spec.inputs_ref == "docket/advantage/v3/inputs/range-v7-positions.json"
    assert spec.inputs_sha256 == ""
    assert not (ROOT / spec.inputs_ref).exists()
    assert spec.protocol_correction is None
    assert spec.pilot_provenance is None
    assert spec_module.is_range_successor_family(spec)
    assert spec.n_planned == 3
    identities = spec.execution_protocol["arm_identities"]
    assert identities["manual"]["human"] is True
    assert identities["manual"]["independent"] is False
    assert identities["agent"]["free_tier"] is False
    assert identities["agent"]["authorization"] == "canary_authorized_x402_exact"
    assert "human operator" in spec.claim.lower()
    assert "settled" in spec.claim.lower()


def test_v7_provenance_matches_the_predecessor_record_it_names():
    spec = spec_module.load(SPEC_PATH, repo_root=ROOT)
    prior = spec_module.load(PRIOR_SPEC_PATH, repo_root=ROOT)

    assert spec.successor_provenance == {
        "status": "distinct_successor_after_terminal_incomplete_pair",
        "prior_spec_id": "v3-05-range-doctor",
        "prior_stage_one_protocol_hash": prior.stage_one_protocol_hash,
        "prior_spec_hash": prior.spec_hash,
        "prior_ledger_ref": "docket/advantage/v3/runs/v3-05-range-doctor.jsonl",
        "reason": spec_module.RANGE_SUCCESSOR_REASON,
    }
    # The predecessor's ledger is untracked evidence, so it is named rather than hashed:
    # this successor must not depend on a file a clean checkout does not carry.
    assert "interrupted" in spec.successor_provenance["reason"]
    assert (
        "v3-05-range-doctor::range-passing_gate_in_range-5223058::manual::primary"
        in spec.successor_provenance["reason"]
    )


def test_existing_v3_05_record_is_untouched_by_the_successor():
    original = json.loads(PRIOR_SPEC_PATH.read_text(encoding="utf-8"))
    loaded = spec_module.load(PRIOR_SPEC_PATH, repo_root=ROOT)

    assert loaded.as_record() == original
    assert "successor_provenance" not in loaded.as_record()
    assert loaded.protocol_correction is not None
    spec_module.assert_runnable(loaded, repo_root=ROOT)


def test_v7_frame_is_pinned_before_its_pool_truth_and_the_capture_is_future_dated():
    spec = spec_module.load(SPEC_PATH, repo_root=ROOT)
    frame = spec.case_selection["frame_definition"]

    assert frame["observation_block"] == 119531513
    assert frame["observation_time"] == "2026-09-02T11:59:59Z"
    assert frame["pool_truth_capture_attempts"] == [
        "2026-09-05T12:00:00Z",
        "2026-09-05T12:01:00Z",
        "2026-09-05T12:02:00Z",
    ]
    assert capture.registered_schedule(spec)["first_attempt_at"] == (
        "2026-09-05T12:00:00Z"
    )
    schedule = [slot.scheduled_at for slot in _capture_slots(spec)]
    assert schedule == [
        datetime(2026, 9, 5, 12, minute, tzinfo=timezone.utc) for minute in range(3)
    ]

    changed = _constructor_record()
    changed["case_selection"]["frame_definition"]["pool_truth_capture_attempts"] = [
        "2026-09-01T12:00:00Z",
        "2026-09-01T12:01:00Z",
        "2026-09-01T12:02:00Z",
    ]
    with pytest.raises(ValueError, match="captured after the pinned"):
        spec_module.PairedSpec(**changed)


def _capture_slots(spec):
    from docket.advantage.v3 import runner

    return runner.registered_capture_schedule(spec)


def test_v7_cannot_reuse_the_predecessor_frame_because_the_draw_is_hash_derived():
    """The 1,024 indices come from the stage-one hash, so no frame is transferable."""
    spec = spec_module.load(SPEC_PATH, repo_root=ROOT)
    prior = spec_module.load(PRIOR_SPEC_PATH, repo_root=ROOT)
    committed = json.loads(
        (ROOT / "docket/advantage/v3/sources/range-v5-enumerable-frame.json").read_text(
            encoding="utf-8"
        )
    )
    total_supply = committed["total_supply"]

    assert spec.stage_one_protocol_hash != prior.stage_one_protocol_hash
    successor = spec_module.range_sample_indices(spec, total_supply)
    predecessor = spec_module.range_sample_indices(prior, total_supply)
    assert [row["index"] for row in successor] != [row["index"] for row in predecessor]
    assert [row["index"] for row in predecessor] == [
        row["index"] for row in committed["rows"]
    ]


def test_v7_prior_exposure_removes_the_predecessor_cases_from_selection_only():
    spec = spec_module.load(SPEC_PATH, repo_root=ROOT)
    exposure = spec.case_selection["prior_exposure_exclusion"]

    assert exposure["token_ids"] == [1056809, 1653348, 5223058]
    assert set(exposure["token_ids"]) == spec_module.RANGE_PRIOR_EXPOSURE_TOKEN_IDS
    assert exposure["prior_spec_id"] == "v3-05-range-doctor"
    assert "5223058" in exposure["disclosure"]
    assert "interrupted" in exposure["disclosure"]

    positions = [
        {
            "token_id": token_id,
            "pool_gate_passes": True,
            "range_status": "in_range",
        }
        for token_id in (5223058, 1056809, 1653348, 4242424)
    ]
    strata = [row["name"] for row in spec.case_selection["frame_definition"]["strata"]]
    passing_in_range = [
        row
        for row in positions
        if spec_module._range_successor_stratum(row) == strata[0]
    ]
    assert len(passing_in_range) == 4
    selected = spec_module.range_selected_positions(
        spec,
        positions
        + [
            {
                "token_id": 99,
                "pool_gate_passes": True,
                "range_status": "above_range",
            },
            {
                "token_id": 98,
                "pool_gate_passes": False,
                "range_status": "in_range",
            },
        ],
    )
    assert [row["token_id"] for row in selected] == [4242424, 99, 98]


def test_v7_prior_exposure_list_cannot_be_padded_or_shortened():
    for token_ids in ([1056809, 1653348, 5223058, 4242], [1653348, 5223058]):
        changed = _constructor_record()
        changed["case_selection"]["prior_exposure_exclusion"]["token_ids"] = token_ids
        with pytest.raises(ValueError, match="prior-exposure token ids"):
            spec_module.PairedSpec(**changed)


@pytest.mark.parametrize(
    ("path", "value", "message"),
    [
        (
            ("protocol_correction",),
            {
                "status": "corrected_before_input_lock",
                "supersedes_stage_one_protocol_hash": (
                    spec_module.RANGE_PRIOR_STAGE_ONE_PROTOCOL_HASH
                ),
                "reason": "relabelled",
            },
            "distinct successor",
        ),
        (
            ("successor_provenance", "status"),
            "corrected_before_input_lock",
            "successor provenance",
        ),
        (
            ("successor_provenance", "prior_spec_id"),
            "v3-01-range-doctor",
            "successor provenance",
        ),
        (
            ("execution_protocol", "arm_identities", "manual", "human"),
            False,
            "arm identities",
        ),
        (
            ("execution_protocol", "arm_identities", "agent", "free_tier"),
            True,
            "arm identities",
        ),
        (
            ("pilot_provenance",),
            {"status": "pilot_informed"},
            "successor provenance alone",
        ),
        (
            ("inputs_ref",),
            "docket/advantage/v3/inputs/range-v5-positions.json",
            "inputs_ref",
        ),
    ],
)
def test_v7_rejects_a_relabelled_or_mutated_successor(path, value, message):
    record = _constructor_record()
    target = record
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = deepcopy(value)

    with pytest.raises(ValueError, match=message):
        spec_module.PairedSpec(**record)


def test_v7_has_a_registered_range_input_validator_and_blinding_salt():
    from docket.advantage.v3 import scoring

    assert (
        spec_module.INPUT_VALIDATORS["v3-07-range-doctor"]
        is spec_module._validate_range_successor_inputs
    )
    assert scoring.FAMILY_PROTOCOLS["v3-07-range-doctor"]["family_salt"] == (
        "range-v7-blinding"
    )
    spec = spec_module.load(SPEC_PATH, repo_root=ROOT)
    assert scoring._family(spec)["family_salt"] == "range-v7-blinding"


def test_v7_collector_accepts_only_the_registered_enumerable_families():
    assert range_capture.SPEC_IDS == ("v3-05-range-doctor", "v3-07-range-doctor")


def test_v7_calibration_is_a_new_eight_case_key_bound_to_this_family():
    body = json.loads(CALIBRATION_PATH.read_text(encoding="utf-8"))
    spec = spec_module.load(SPEC_PATH, repo_root=ROOT)
    prior_body = json.loads(
        (ROOT / "docket/advantage/v3/sources/range-v5-calibration-set.json").read_text(
            encoding="utf-8"
        )
    )

    assert body["spec_id"] == spec.spec_id
    assert len(body["cases"]) == 8
    assert len({case["case_id"] for case in body["cases"]}) == 8
    assert all(case["case_id"].startswith("r7-cal-") for case in body["cases"])
    assert {case["expected"]["range_status"] for case in body["cases"]} == {
        "in_range",
        "above_range",
        "below_range",
    }
    for case in body["cases"]:
        computed = spec_module._computed_calibration_truth(spec, case["input"])
        assert spec_module._calibration_truth_matches(case["expected"], computed)
    # A key the seats have already answered would measure recall, not calibration.
    assert {
        json.dumps(case["input"], sort_keys=True) for case in body["cases"]
    }.isdisjoint(
        json.dumps(case["input"], sort_keys=True) for case in prior_body["cases"]
    )


def test_v7_deploy_units_are_tracked_and_name_the_registered_capture():
    service = (DEPLOY / "systemd/docket-v3-range-v7-capture.service").read_text(
        encoding="utf-8"
    )
    timer = (DEPLOY / "systemd/docket-v3-range-v7-capture.timer").read_text(
        encoding="utf-8"
    )
    release = (DEPLOY / "release.sh").read_text(encoding="utf-8")
    preflight = (DEPLOY / "preflight.sh").read_text(encoding="utf-8")

    assert "v3-07-range-doctor /var/lib/docket/v3-capture/range-v3-07" in service
    assert "OnCalendar=2026-09-05 11:50:00 UTC" in timer
    assert "AccuracySec=1s" in timer
    assert "Persistent=true" in timer
    assert "Unit=docket-v3-range-v7-capture.service" in timer
    for script in (release, preflight):
        assert "docket-v3-range-v7-capture.service" in script
        assert "docket-v3-range-v7-capture.timer" in script
    assert "refuse_range_v7_capture_window" in release
    assert release.count("refuse_range_v7_capture_window\n") == 2
    assert "2026-09-05T11:49:54Z" in release
    assert "2026-09-05T12:03:06Z" in release
    assert '"v3-07-range-doctor": "registered_waiting_for_inputs"' in release


def test_v7_runbook_stages_the_registration_capture_and_paid_arm_in_order():
    runbook = RUNBOOK_PATH.read_text(encoding="utf-8")

    assert "docket.advantage.v3.range_capture" in runbook
    assert "assemble lock-range" in runbook
    assert "--payment-header" in runbook
    assert "--canary-header" in runbook
    assert "export_evaluation_sessions" in runbook
    assert "import_evaluation_submission" in runbook
    assert "publish_mapping" in runbook
    assert "report.report" in runbook
    assert "complete_scored" not in runbook
    assert "expected_terminal = (" in runbook
    assert "'refuted' if family['falsifier_result']['refuted']" in runbook
    assert "assert family['state'] == expected_terminal" in runbook
    assert runbook.index("## 1. Collect the archive-pinned enumerable frame") < (
        runbook.index("## 3. Registered pool truth")
    )
    assert runbook.index("## 3. Registered pool truth") < runbook.index(
        "## 5. Bind and lock"
    )
    assert runbook.index("## 5. Bind and lock") < runbook.index(
        "## 6. Owner-only manual-arm handover"
    )
    assert runbook.index("## 6. Owner-only manual-arm handover") < runbook.index(
        "## 7. Run the three settled Range Doctor agent primaries"
    )
    assert (
        runbook.index("export_evaluation_sessions")
        < runbook.index("import_evaluation_submission")
        < runbook.index("publish_mapping")
        < runbook.index("report.report")
    )
