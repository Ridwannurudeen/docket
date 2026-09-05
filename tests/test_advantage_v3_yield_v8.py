"""The human-versus-agent Yield family: registration, capture wiring and calibration key.

v3-06 registered a disclosed Codex-assisted baseline and made no human claim. This family
puts a human operator on the manual arm, so the tests below check exactly the two things a
reader would otherwise take on trust: that the registration says so, and that its
calibration key is not the one a seat has already answered for v3-02 or v3-06.
"""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from docket.advantage.v3 import calibration, capture, runner, scoring
from docket.advantage.v3 import spec as spec_module

ROOT = spec_module.REPO_ROOT
SPEC_PATH = ROOT / "docket/advantage/v3/specs/v3-08-yield-router.json"
CALIBRATION_PATH = ROOT / "docket/advantage/v3/sources/yield-v8-calibration-set.json"
PRIOR_SETS = (
    ROOT / "docket/advantage/v3/sources/yield-v2-calibration-set.json",
    ROOT / "docket/advantage/v3/sources/yield-v6-assisted-calibration-set.json",
)
RUNBOOK_PATH = ROOT / "docs/runbooks/yield-v3-08-run.md"
RANGE_RUNBOOK_PATH = ROOT / "docs/runbooks/range-v3-07-run.md"
HEALTH_RUNBOOK_PATH = ROOT / "docs/runbooks/health-v3-09-run.md"
SPEC = spec_module.load(SPEC_PATH, repo_root=ROOT)


def _constructor_record() -> dict:
    record = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    record.pop("stage_one_protocol_hash")
    record.pop("spec_hash")
    return record


def test_v8_is_a_new_family_with_a_human_operator_on_the_manual_arm():
    assert SPEC.spec_id == "v3-08-yield-router"
    assert spec_module.is_yield_family(SPEC)
    assert SPEC.inputs_ref == "docket/advantage/v3/inputs/08-yield-cases.json"
    assert SPEC.inputs_sha256 == ""
    assert SPEC.n_planned == 3
    assert SPEC.protocol_correction is None
    assert SPEC.successor_provenance is None
    assert SPEC.pilot_provenance is None
    assert SPEC.arms["agent"]["display_name"] == "Deployed Yield Router"
    assert SPEC.arms["manual"]["display_name"] == "Human operator"
    assert "human operator" in SPEC.claim.lower()
    assert SPEC.execution_protocol["arm_identities"] == (
        spec_module.YIELD_V8_ARM_IDENTITIES
    )
    assert SPEC.execution_protocol["arm_identities"]["manual"]["human"] is True
    assert (
        SPEC.execution_protocol["arm_identities"]["agent"]["settled_payment_assumed"]
        is False
    )


def test_both_registered_hashes_verify_from_the_committed_bytes():
    record = json.loads(SPEC_PATH.read_text(encoding="utf-8"))

    assert record["stage_one_protocol_hash"] == SPEC.stage_one_protocol_hash
    assert record["spec_hash"] == SPEC.spec_hash


def test_v8_capture_schedule_is_hash_bound_and_later_than_its_predecessors():
    assert SPEC.case_selection["source_capture_attempts"] == [
        "2026-09-06T12:00:00Z",
        "2026-09-06T12:01:00Z",
        "2026-09-06T12:02:00Z",
    ]
    assert spec_module.yield_capture_attempts(SPEC) == (
        datetime(2026, 9, 6, 12, 0, tzinfo=UTC),
        datetime(2026, 9, 6, 12, 1, tzinfo=UTC),
        datetime(2026, 9, 6, 12, 2, tzinfo=UTC),
    )
    assert capture.registered_schedule(SPEC) == {
        "first_attempt_at": "2026-09-06T12:00:00Z",
        "pools_url": spec_module.YIELD_SOURCE_URLS["pools"],
        "token_list_url": spec_module.YIELD_SOURCE_URLS["token_list"],
    }
    assert [
        slot.attempt_ordinal for slot in runner.registered_capture_schedule(SPEC)
    ] == [
        1,
        2,
        3,
    ]


@pytest.mark.parametrize(
    ("path", "value"),
    (
        (("case_selection", "source_capture_attempts", 0), "2026-09-06T11:59:00Z"),
        (("inputs_ref",), "docket/advantage/v3/inputs/02-yield-cases.json"),
    ),
)
def test_v8_refuses_a_mutated_registration(path, value):
    record = _constructor_record()
    target = record
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value

    with pytest.raises(ValueError):
        spec_module.PairedSpec(**record)


def test_v8_cannot_be_relabelled_as_a_correction_or_a_successor():
    record = _constructor_record()
    record["protocol_correction"] = {
        "status": "corrected_before_input_lock",
        "supersedes_stage_one_protocol_hash": SPEC.stage_one_protocol_hash,
        "reason": "x",
    }

    with pytest.raises(ValueError, match="carries none of the three provenance"):
        spec_module.PairedSpec(**record)


def test_v8_uses_the_registered_yield_input_validator_and_family_salt():
    assert spec_module.INPUT_VALIDATORS[SPEC.spec_id] is (
        spec_module._validate_yield_inputs
    )
    protocol = scoring._family(SPEC)
    assert protocol["fields"] == scoring.YIELD_FIELDS
    assert protocol["family_salt"] == "yield-v8-blinding"
    assert "yield-v8-blinding" in SPEC.scoring["randomisation"]


def test_the_packaged_family_id_resolves_for_the_capture_unit(tmp_path, capsys):
    """The systemd unit passes the bare family id, not a path.

    The clock is set past the last registered attempt so the refusal happens before any
    request is made: this test must never reach the network.
    """
    resolved = capture._resolve_spec("v3-08-yield-router")

    assert Path(resolved).name == "v3-08-yield-router.json"

    code = capture.main(
        ["v3-08-yield-router", str(tmp_path / "capture")],
        now=datetime(2026, 9, 6, 13, 0, tzinfo=UTC),
    )

    assert code == 2
    assert "the registered capture opened at 2026-09-06T12:00:00Z" in (
        capsys.readouterr().out
    )


def _cases(path: Path) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))["cases"]


def test_v8_calibration_key_is_bound_recomputable_and_covers_the_gates():
    body = json.loads(CALIBRATION_PATH.read_text(encoding="utf-8"))

    assert set(body) == {"authored_at", "spec_id", "cases"}
    assert body["spec_id"] == SPEC.spec_id
    assert len(body["cases"]) == 8
    assert [case["case_id"] for case in body["cases"]] == [
        f"y8-cal-{ordinal:02d}" for ordinal in range(1, 9)
    ]
    gates = [case["expected"]["current_first_failed_gate"] for case in body["cases"]]
    assert None in gates
    assert len(set(gates)) >= 3
    for case in body["cases"]:
        computed = spec_module._computed_calibration_truth(SPEC, case["input"])
        assert spec_module._calibration_truth_matches(case["expected"], computed)


def test_v8_calibration_inputs_share_no_case_with_v2_or_v6():
    def keys(path):
        return {
            json.dumps(
                [
                    case["input"]["allowlist"],
                    case["input"]["current_pool"],
                    case["input"]["destination_pool"],
                ],
                sort_keys=True,
            )
            for case in _cases(path)
        }

    mine = keys(CALIBRATION_PATH)

    assert len(mine) == 8
    for prior in PRIOR_SETS:
        assert not mine & keys(prior)


def test_v8_calibration_prompt_withholds_the_answers():
    prompt = json.loads(
        calibration.derive_prompt(SPEC, CALIBRATION_PATH.read_bytes(), "seat-a").decode(
            "utf-8"
        )
    )

    assert prompt["prompt_version"] == "v3.calibration-prompt.v5"
    assert (
        "current_first_failed_gate, destination_first_failed_gate"
        in (prompt["instruction"])
    )
    assert all("expected" not in case for case in prompt["cases"])


def test_v8_runbook_names_the_registered_moment_and_the_one_family_per_day_rule():
    runbook = " ".join(RUNBOOK_PATH.read_text(encoding="utf-8").split())

    assert "2026-09-06T12:00:00Z" in runbook
    assert "docket-v3-yield-v8-capture.timer" in runbook
    assert "One family per day." in runbook
    # MAJOR-3: the rule is about the adapters, so a calibration seat counts too.
    assert "Calibration seats are seats." in runbook
    assert "A capture is neither an arm nor a seat" in runbook
    assert "Seat-a is unavailable until Sep 7" in runbook
    assert "seat-a" in runbook
    assert "| Sep 8 | Stage 3, both calibration seats | Operator |" in runbook
    assert "| Sep 8 | Stage 4, bind and lock | Operator |" in runbook
    shared_calendar = (
        "`v3-07` owns Sep 7; `v3-08` owns Sep 8; "
        "`v3-09` may own Sep 9."
    )
    for path in (RANGE_RUNBOOK_PATH, RUNBOOK_PATH, HEALTH_RUNBOOK_PATH):
        text = " ".join(path.read_text(encoding="utf-8").split())
        assert shared_calendar in text
        assert "| Sep 7 | v3-08 calibration seats and lock |" not in text
    # The capture is the one unmovable stage, so it never waits on a seat.
    assert runbook.index("## 2. Registered source capture") < runbook.index(
        "## 3. Calibrate both evaluator seats"
    )
    assert "capture on the registered moment regardless of seat availability" in (
        runbook
    )
