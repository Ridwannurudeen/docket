"""The ledger, and the failures it has to survive to be worth anything.

A paired run is believable because the record was written before the outcome was known and
could not be revised afterwards. These tests attack that: a second claim on a slot, a crash
between start and finish, inputs that move while an arm runs, and an operator who would
rather their attempt counted for speed than not.
"""

import json
from pathlib import Path

import pytest

import docket.advantage.v3.spec as spec_module
from docket.advantage.v3 import runner
from docket.advantage.v3.spec import PairedSpec, lock_inputs, save

from test_advantage_v3_spec import _input_record, _valid, _write_inputs  # noqa: F401


@pytest.fixture(autouse=True)
def _register_the_minimal_test_protocol_validator(monkeypatch):
    """Spec id ``t`` isolates ledger mechanics from any one family's truth schema. The
    production ids still require their own explicit validator — this only exists so these
    tests attack the ledger rather than re-testing input validation."""
    monkeypatch.setitem(
        spec_module.INPUT_VALIDATORS,
        "t",
        lambda _spec, _body, _cases, _repo_root: None,
    )


@pytest.fixture
def locked(tmp_path: Path):
    """A spec whose inputs are genuinely frozen, in a throwaway repo root."""
    stage_one = PairedSpec(**_valid())
    record = _input_record(stage_one)
    _write_inputs(tmp_path, stage_one, (json.dumps(record) + "\n").encode())
    save(stage_one, tmp_path / "spec.json", repo_root=tmp_path)
    spec = lock_inputs(stage_one, repo_root=tmp_path)
    save(spec, tmp_path / "spec.json", repo_root=tmp_path)
    return spec, tmp_path / "runs", tmp_path


def test_a_run_cannot_open_against_unlocked_inputs(tmp_path: Path):
    """The whole apparatus is worthless if an arm can run before the cases are frozen."""
    stage_one = PairedSpec(**_valid())
    with pytest.raises(ValueError, match="no locked inputs"):
        runner.open_run(stage_one, tmp_path / "runs", repo_root=tmp_path)


def test_a_primary_slot_is_claimed_once_and_never_again(locked):
    """No scored retry, enforced by the data rather than by discipline.

    A second run of a case whose first answer disappointed cannot be recorded, so it cannot
    reach the report. That is the difference between a stopping rule and a promise.
    """
    spec, runs, root = locked
    runner.open_run(spec, runs, repo_root=root)
    runner.claim_slot(spec, runs, case_id="case-1", arm="manual", repo_root=root)
    runner.terminate_slot(
        spec,
        runs,
        case_id="case-1",
        arm="manual",
        outcome=runner.SUCCEEDED,
        repo_root=root,
        raw_output={"answer": "first"},
    )
    with pytest.raises(ValueError, match="already claimed"):
        runner.claim_slot(spec, runs, case_id="case-1", arm="manual", repo_root=root)


def test_an_attempt_has_exactly_one_ending(locked):
    spec, runs, root = locked
    runner.claim_slot(spec, runs, case_id="case-1", arm="agent", repo_root=root)
    runner.terminate_slot(
        spec,
        runs,
        case_id="case-1",
        arm="agent",
        outcome=runner.FAILED,
        repo_root=root,
        failure={"kind": "timeout", "message": "no response"},
    )
    with pytest.raises(ValueError, match="already terminated"):
        runner.terminate_slot(
            spec,
            runs,
            case_id="case-1",
            arm="agent",
            outcome=runner.SUCCEEDED,
            repo_root=root,
            raw_output={"answer": "better on reflection"},
        )


def test_a_crash_between_start_and_finish_becomes_an_interruption_with_null_timings(
    locked,
):
    """The process that knew the finish time is gone. A plausible number here would be
    indistinguishable from a measured one, so both stay null and the detection time — which
    IS known — is what gets recorded."""
    spec, runs, root = locked
    runner.claim_slot(spec, runs, case_id="case-2", arm="manual", repo_root=root)

    closed = runner.recover_interrupted(spec, runs)
    assert len(closed) == 1
    event = closed[0]
    assert event["outcome"] == runner.INTERRUPTED
    assert event["finished_at"] is None
    assert event["elapsed_ns"] is None
    assert event["detected_at"] is not None
    assert event["eligible_for_speed"] is False
    # And it stays closed: recovering twice does not invent a second interruption.
    assert runner.recover_interrupted(spec, runs) == []


def test_an_interrupted_slot_is_never_reopened(locked):
    spec, runs, root = locked
    runner.claim_slot(spec, runs, case_id="case-3", arm="agent", repo_root=root)
    runner.recover_interrupted(spec, runs)
    with pytest.raises(ValueError, match="already claimed"):
        runner.claim_slot(spec, runs, case_id="case-3", arm="agent", repo_root=root)


def test_inputs_that_move_while_an_arm_runs_are_retained_as_tamper_not_discarded(
    locked,
):
    """The detection is the finding. Dropping the attempt would drop it."""
    spec, runs, root = locked
    runner.claim_slot(spec, runs, case_id="case-4", arm="agent", repo_root=root)
    # The inputs change under the running arm.
    (root / spec.inputs_ref).write_bytes(b'{"smuggled": true}\n')

    event = runner.terminate_slot(
        spec,
        runs,
        case_id="case-4",
        arm="agent",
        outcome=runner.SUCCEEDED,
        repo_root=root,
        raw_output={"answer": "looks fine"},
    )
    assert event["outcome"] == runner.INPUT_TAMPER  # not the success it claimed
    assert event["eligible_for_speed"] is False
    assert "digest mismatch" in event["failure"]["message"]


def test_only_a_successful_primary_can_contribute_a_duration(locked):
    """Eligibility is derived, never supplied. An operator who can mark their own attempt
    eligible chooses which durations enter the comparison."""
    spec, runs, root = locked
    for index, outcome in enumerate(
        (runner.SUCCEEDED, runner.FAILED, runner.TIMED_OUT, runner.BLOCKED_CONTRACT),
        start=5,
    ):
        case = f"case-{index}"
        runner.claim_slot(spec, runs, case_id=case, arm="manual", repo_root=root)
        event = runner.terminate_slot(
            spec,
            runs,
            case_id=case,
            arm="manual",
            outcome=outcome,
            repo_root=root,
        )
        assert event["eligible_for_speed"] is (outcome == runner.SUCCEEDED), outcome


def test_a_blocked_service_contract_is_not_recorded_as_a_failure(locked):
    """A service that cannot accept the registered request has not failed the task. Calling
    it a failure would understate the agent and hide a gap that is ours to close."""
    spec, runs, root = locked
    runner.claim_slot(spec, runs, case_id="case-9", arm="agent", repo_root=root)
    event = runner.terminate_slot(
        spec,
        runs,
        case_id="case-9",
        arm="agent",
        outcome=runner.BLOCKED_CONTRACT,
        repo_root=root,
        failure={
            "kind": "blocked_service_contract",
            "message": "the endpoint exposes no observation_block input",
        },
    )
    assert event["outcome"] == runner.BLOCKED_CONTRACT
    assert event["outcome"] != runner.FAILED


def test_every_record_cites_all_three_identities(locked):
    """One hash alone can be true about a run that never happened under the others."""
    spec, runs, root = locked
    runner.open_run(spec, runs, repo_root=root)
    runner.claim_slot(spec, runs, case_id="case-10", arm="manual", repo_root=root)
    for event in runner.read_events(runner.ledger_path(spec, runs)):
        if event["kind"] in (runner.RUN_OPENED, runner.STARTED):
            assert event["stage_one_protocol_hash"] == spec.stage_one_protocol_hash
            assert event["spec_hash"] == spec.spec_hash
            assert event["inputs_sha256"] == spec.inputs_sha256


def test_the_ledger_is_append_only_and_never_rewrites_an_earlier_event(locked):
    spec, runs, root = locked
    runner.claim_slot(spec, runs, case_id="case-11", arm="manual", repo_root=root)
    before = runner.ledger_path(spec, runs).read_text(encoding="utf-8")
    runner.terminate_slot(
        spec,
        runs,
        case_id="case-11",
        arm="manual",
        outcome=runner.SUCCEEDED,
        repo_root=root,
        raw_output={"a": 1},
    )
    after = runner.ledger_path(spec, runs).read_text(encoding="utf-8")
    assert after.startswith(before)  # only grew


def test_a_half_written_final_line_is_reported_rather_than_skipped(locked):
    """That is what a crash mid-append looks like. Skipping it would turn a visible
    interruption into an attempt that never appears."""
    spec, runs, root = locked
    runner.claim_slot(spec, runs, case_id="case-12", arm="manual", repo_root=root)
    path = runner.ledger_path(spec, runs)
    with path.open("a", encoding="utf-8") as handle:
        handle.write('{"kind": "attempt_termi')
    with pytest.raises(ValueError, match="interrupted mid-append"):
        runner.read_events(path)


def test_source_queries_are_logged_before_the_answer_that_used_them_exists(locked):
    """The manual arm's sources are its working. Curated afterwards, they become the set
    that happens to support the answer given."""
    spec, runs, root = locked
    runner.claim_slot(spec, runs, case_id="case-13", arm="manual", repo_root=root)
    runner.record_source_query(
        spec,
        runs,
        case_id="case-13",
        arm="manual",
        request={"url": "https://example.invalid/pool"},
        response_summary={"status": 200, "body_sha256": "0xabc"},
    )
    kinds = [e["kind"] for e in runner.read_events(runner.ledger_path(spec, runs))]
    assert kinds.index(runner.SOURCE_QUERY) < len(kinds)
    assert runner.TERMINATED not in kinds  # the answer does not exist yet


def test_an_unknown_event_kind_or_outcome_is_refused(locked):
    spec, runs, root = locked
    with pytest.raises(ValueError, match="unknown event kind"):
        runner.append_event(runner.ledger_path(spec, runs), {"kind": "looks_fine"})
    runner.claim_slot(spec, runs, case_id="case-14", arm="manual", repo_root=root)
    with pytest.raises(ValueError, match="unknown outcome"):
        runner.terminate_slot(
            spec,
            runs,
            case_id="case-14",
            arm="manual",
            outcome="mostly_worked",
            repo_root=root,
        )
