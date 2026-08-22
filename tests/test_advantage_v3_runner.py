"""The ledger, and the failures it has to survive to be worth anything.

A paired run is believable because the record was written before the outcome was known and
later edits are detectable. These tests attack that: a second claim on a slot, a crash
between start and finish, inputs that move while an arm runs, and an operator who would
rather their attempt counted for speed than not.
"""

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest

import docket.advantage.v3.spec as spec_module
from docket.advantage.v3 import runner
from docket.advantage.v3.spec import PairedSpec, load, lock_inputs, save

from test_advantage_v3_spec import (  # noqa: F401
    SPECS_DIR,
    _input_record,
    _valid,
    _write_inputs,
)


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


def _slot(spec, root, case_id, arm):
    return next(
        slot
        for slot in runner.scheduled_slots(spec, repo_root=root)
        if slot.case_id == case_id and slot.arm == arm
    )


def test_a_run_cannot_open_against_unlocked_inputs(tmp_path: Path):
    """The whole apparatus is worthless if an arm can run before the cases are frozen."""
    stage_one = PairedSpec(**_valid())
    with pytest.raises(ValueError, match="no locked inputs"):
        runner.open_run(stage_one, tmp_path / "runs", repo_root=tmp_path)


def test_registered_capture_harness_preserves_exact_http_bytes(tmp_path):
    spec = load(SPECS_DIR / "v3-02-yield-router.json")
    slot = runner.registered_capture_schedule(spec)[0]
    raw = {
        "pools": b'[ {"id":"0xpool"} ]\n',
        "token_list": b'{"tokens":[]}\n',
    }

    def serve(request):
        name = "token_list" if "tokens.pancakeswap" in request.url.host else "pools"
        return runner.httpx.Response(200, content=raw[name])

    event = runner.capture_due_sources(
        spec,
        tmp_path / "captures",
        now=slot.scheduled_at + timedelta(seconds=1),
        client=runner.httpx.Client(transport=runner.httpx.MockTransport(serve)),
    )

    assert event["attempt_ordinal"] == 1
    for name in ("pools", "token_list"):
        snapshot = event["source_snapshots"][name]
        assert snapshot["sha256"] == hashlib.sha256(raw[name]).hexdigest()


def test_registered_capture_schedule_keeps_range_boundary_and_recommits_yield():
    range_spec = load(SPECS_DIR / "v3-01-range-doctor.json")
    yield_spec = load(SPECS_DIR / "v3-02-yield-router.json")

    assert [
        slot.scheduled_at.isoformat().replace("+00:00", "Z")
        for slot in runner.registered_capture_schedule(range_spec)
    ] == ["2026-08-21T12:00:00Z"]
    assert [
        slot.scheduled_at.isoformat().replace("+00:00", "Z")
        for slot in runner.registered_capture_schedule(yield_spec)
    ] == [
        "2026-08-26T12:00:00Z",
        "2026-08-26T12:01:00Z",
        "2026-08-26T12:02:00Z",
    ]


def test_primary_schedule_and_case_bindings_come_only_from_locked_inputs(locked):
    spec, runs, root = locked
    slots = runner.scheduled_slots(spec, repo_root=root)

    assert [(slot.case_id, slot.arm) for slot in slots] == [
        *((f"case-{number}", "manual") for number in range(1, 6)),
        *((f"case-{number}", "agent") for number in range(1, 6)),
    ]
    forged = replace(slots[0], case_id="operator-chosen")
    with pytest.raises(ValueError, match="locked schedule"):
        runner.claim_slot(spec, runs, slot=forged, repo_root=root)


def test_concurrent_claimers_cannot_both_win_the_same_primary(locked):
    spec, runs, root = locked
    slot = runner.scheduled_slots(spec, repo_root=root)[0]

    def claim():
        return runner.claim_slot(spec, runs, slot=slot, repo_root=root)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = [future for future in (pool.submit(claim), pool.submit(claim))]
    outcomes = []
    for future in results:
        try:
            outcomes.append(future.result()["kind"])
        except ValueError:
            outcomes.append("refused")

    assert sorted(outcomes) == [runner.STARTED, "refused"]
    starts = [
        event
        for event in runner.read_events(runner.ledger_path(spec, runs))
        if event["kind"] == runner.STARTED
    ]
    assert len(starts) == 1


def test_registered_timeout_overrides_a_late_manual_submission(locked, monkeypatch):
    spec, runs, root = locked
    slot = runner.scheduled_slots(spec, repo_root=root)[0]
    ticks = iter((1, 1 + spec.timing["timeout_seconds"] * 1_000_000_000 + 1))
    monkeypatch.setattr(runner.time, "monotonic_ns", lambda: next(ticks))

    runner.claim_slot(spec, runs, slot=slot, repo_root=root)
    terminal = runner.terminate_slot(
        spec,
        runs,
        slot=slot,
        repo_root=root,
        raw_output={"answer": "submitted after the deadline"},
    )

    assert terminal["outcome"] == runner.TIMED_OUT
    assert terminal["eligible_for_speed"] is False


def test_blocked_service_contract_can_only_be_derived_for_an_agent_slot(locked):
    spec, runs, root = locked
    manual = runner.scheduled_slots(spec, repo_root=root)[0]
    runner.claim_slot(spec, runs, slot=manual, repo_root=root)
    with pytest.raises(ValueError, match="agent slot"):
        runner._terminate_slot(
            spec,
            runs,
            slot=manual,
            repo_root=root,
            failure={"kind": runner.BLOCKED_CONTRACT, "message": "fixture"},
            forced_outcome=runner.BLOCKED_CONTRACT,
        )
    runner.terminate_slot(
        spec, runs, slot=manual, repo_root=root, raw_output={"answer": "done"}
    )
    harness = runner.ExperimentHarness(spec, runs, repo_root=root)
    for _ in range(spec.n_planned - 1):
        harness.reveal_manual_case()
        harness.submit_manual({"answer": "done"})
    terminal = harness.run_agent(
        client=runner.httpx.Client(
            transport=runner.httpx.MockTransport(
                lambda _request: runner.httpx.Response(422, json={"error": "shape"})
            )
        )
    )
    assert terminal["outcome"] == runner.BLOCKED_CONTRACT


def test_harness_reveals_locked_manual_cases_in_registered_order(locked):
    spec, runs, root = locked
    harness = runner.ExperimentHarness(spec, runs, repo_root=root)
    harness.start()

    first = harness.reveal_manual_case()
    assert first == {"case_id": "case-1"}
    terminal = harness.submit_manual({"answer": "one"})
    assert terminal["outcome"] == runner.SUCCEEDED
    assert harness.reveal_manual_case() == {"case_id": "case-2"}


def test_harness_invokes_the_registered_paid_endpoint_after_the_manual_block(locked):
    spec, runs, root = locked
    observed = {}

    def serve(request):
        observed["url"] = str(request.url)
        observed["body"] = json.loads(request.content)
        observed["payment"] = request.headers["X-PAYMENT"]
        observed["timeout"] = request.extensions["timeout"]["read"]
        result = {"answer": "agent"}
        return runner.httpx.Response(
            200,
            json={
                "result": result,
                "receipt": {
                    "service": "test-service",
                    "input_hash": runner.canonical_hash(observed["body"]),
                    "output_hash": runner.canonical_hash(result),
                    "payment": {
                        "status": "settled",
                        "amount": "5",
                        "asset": "0xasset",
                    },
                },
            },
        )

    client = runner.httpx.Client(transport=runner.httpx.MockTransport(serve))
    harness = runner.ExperimentHarness(spec, runs, repo_root=root)
    harness.start()
    for _ in range(spec.n_planned):
        harness.reveal_manual_case()
        harness.submit_manual({"answer": "manual"})

    terminal = harness.run_agent({"X-PAYMENT": "signed"}, client=client)

    assert terminal["outcome"] == runner.SUCCEEDED
    assert observed == {
        "url": spec.execution_protocol["agent_endpoint"],
        "body": {},
        "payment": "signed",
        "timeout": spec.timing["timeout_seconds"],
    }
    assert terminal["receipt"]["payment"]["status"] == "settled"


def test_harness_accepts_the_current_free_tier_receipt_without_inventing_cost(locked):
    spec, runs, root = locked
    result = {"answer": "agent"}

    def serve(request):
        payload = json.loads(request.content)
        return runner.httpx.Response(
            200,
            json={
                "result": result,
                "receipt": {
                    "service": "test-service",
                    "input_hash": runner.canonical_hash(payload),
                    "output_hash": runner.canonical_hash(result),
                    "payment": {"status": "free_tier"},
                },
            },
        )

    harness = runner.ExperimentHarness(spec, runs, repo_root=root)
    harness.start()
    for _ in range(spec.n_planned):
        harness.reveal_manual_case()
        harness.submit_manual({"answer": "manual"})

    terminal = harness.run_agent(
        client=runner.httpx.Client(transport=runner.httpx.MockTransport(serve))
    )

    assert terminal["outcome"] == runner.SUCCEEDED
    assert terminal["cost"] == {
        "amount": "0",
        "asset": None,
        "payment_status": "free_tier",
    }


def test_harness_records_an_agent_transport_error_as_the_terminal_result(locked):
    spec, runs, root = locked
    harness = runner.ExperimentHarness(spec, runs, repo_root=root)
    for _ in range(spec.n_planned):
        harness.reveal_manual_case()
        harness.submit_manual({"answer": "manual"})

    def fail(request):
        raise runner.httpx.ConnectError("offline", request=request)

    terminal = harness.run_agent(
        client=runner.httpx.Client(transport=runner.httpx.MockTransport(fail))
    )

    assert terminal["outcome"] == runner.FAILED
    assert terminal["failure"] == {
        "kind": "transport_error",
        "message": "ConnectError: offline",
    }


def test_a_primary_slot_is_claimed_once_and_never_again(locked):
    """No scored retry, enforced by the data rather than by discipline.

    A second run of a case whose first answer disappointed cannot be recorded, so it cannot
    reach the report. That is the difference between a stopping rule and a promise.
    """
    spec, runs, root = locked
    slot = _slot(spec, root, "case-1", "manual")
    runner.open_run(spec, runs, repo_root=root)
    runner.claim_slot(spec, runs, slot=slot, repo_root=root)
    runner.terminate_slot(
        spec,
        runs,
        slot=slot,
        repo_root=root,
        raw_output={"answer": "first"},
    )
    with pytest.raises(ValueError, match="already claimed"):
        runner.claim_slot(spec, runs, slot=slot, repo_root=root)


def test_an_attempt_has_exactly_one_ending(locked):
    spec, runs, root = locked
    slot = _slot(spec, root, "case-1", "agent")
    runner.claim_slot(spec, runs, slot=slot, repo_root=root)
    runner.terminate_slot(
        spec,
        runs,
        slot=slot,
        repo_root=root,
        failure={"kind": "timeout", "message": "no response"},
    )
    with pytest.raises(ValueError, match="already terminated"):
        runner.terminate_slot(
            spec,
            runs,
            slot=slot,
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
    slot = _slot(spec, root, "case-2", "manual")
    runner.claim_slot(spec, runs, slot=slot, repo_root=root)

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
    slot = _slot(spec, root, "case-3", "agent")
    runner.claim_slot(spec, runs, slot=slot, repo_root=root)
    runner.recover_interrupted(spec, runs)
    with pytest.raises(ValueError, match="already claimed"):
        runner.claim_slot(spec, runs, slot=slot, repo_root=root)


def test_inputs_that_move_while_an_arm_runs_are_retained_as_tamper_not_discarded(
    locked,
):
    """The detection is the finding. Dropping the attempt would drop it."""
    spec, runs, root = locked
    slot = _slot(spec, root, "case-4", "agent")
    runner.claim_slot(spec, runs, slot=slot, repo_root=root)
    # The inputs change under the running arm.
    (root / spec.inputs_ref).write_bytes(b'{"smuggled": true}\n')

    event = runner.terminate_slot(
        spec,
        runs,
        slot=slot,
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
    succeeded = _slot(spec, root, "case-1", "manual")
    failed = _slot(spec, root, "case-2", "manual")
    runner.claim_slot(spec, runs, slot=succeeded, repo_root=root)
    success = runner.terminate_slot(
        spec, runs, slot=succeeded, repo_root=root, raw_output={"answer": "done"}
    )
    runner.claim_slot(spec, runs, slot=failed, repo_root=root)
    failure = runner.terminate_slot(
        spec,
        runs,
        slot=failed,
        repo_root=root,
        failure={"kind": "technical", "message": "fixture"},
    )
    assert success["eligible_for_speed"] is True
    assert failure["eligible_for_speed"] is False


def test_a_blocked_service_contract_is_not_recorded_as_a_failure(locked):
    """A service that cannot accept the registered request has not failed the task. Calling
    it a failure would understate the agent and hide a gap that is ours to close."""
    spec, runs, root = locked
    harness = runner.ExperimentHarness(spec, runs, repo_root=root)
    for _ in range(spec.n_planned):
        harness.reveal_manual_case()
        harness.submit_manual({"answer": "done"})
    event = harness.run_agent(
        client=runner.httpx.Client(
            transport=runner.httpx.MockTransport(
                lambda _request: runner.httpx.Response(400, json={"error": "contract"})
            )
        )
    )
    assert event["outcome"] == runner.BLOCKED_CONTRACT
    assert event["outcome"] != runner.FAILED


def test_every_record_cites_all_three_identities(locked):
    """One hash alone can be true about a run that never happened under the others."""
    spec, runs, root = locked
    runner.open_run(spec, runs, repo_root=root)
    runner.claim_slot(
        spec,
        runs,
        slot=_slot(spec, root, "case-1", "manual"),
        repo_root=root,
    )
    for event in runner.read_events(runner.ledger_path(spec, runs)):
        if event["kind"] in (runner.RUN_OPENED, runner.STARTED):
            assert event["stage_one_protocol_hash"] == spec.stage_one_protocol_hash
            assert event["spec_hash"] == spec.spec_hash
            assert event["inputs_sha256"] == spec.inputs_sha256


def test_the_runner_api_only_grows_the_ledger(locked):
    spec, runs, root = locked
    slot = _slot(spec, root, "case-1", "manual")
    runner.claim_slot(spec, runs, slot=slot, repo_root=root)
    before = runner.ledger_path(spec, runs).read_text(encoding="utf-8")
    runner.terminate_slot(
        spec,
        runs,
        slot=slot,
        repo_root=root,
        raw_output={"a": 1},
    )
    after = runner.ledger_path(spec, runs).read_text(encoding="utf-8")
    assert after.startswith(before)  # only grew


def test_a_half_written_final_line_is_reported_rather_than_skipped(locked):
    """That is what a crash mid-append looks like. Skipping it would turn a visible
    interruption into an attempt that never appears."""
    spec, runs, root = locked
    runner.claim_slot(
        spec,
        runs,
        slot=_slot(spec, root, "case-1", "manual"),
        repo_root=root,
    )
    path = runner.ledger_path(spec, runs)
    with path.open("a", encoding="utf-8") as handle:
        handle.write('{"kind": "attempt_termi')
    with pytest.raises(ValueError, match="interrupted mid-append"):
        runner.read_events(path)


def test_source_queries_are_logged_before_the_answer_that_used_them_exists(locked):
    """The manual arm's sources are its working. Curated afterwards, they become the set
    that happens to support the answer given."""
    spec, runs, root = locked
    slot = _slot(spec, root, "case-1", "manual")
    runner.claim_slot(spec, runs, slot=slot, repo_root=root)
    runner.record_source_query(
        spec,
        runs,
        slot=slot,
        repo_root=root,
        request={"url": "https://example.invalid/pool"},
        response_summary={"status": 200, "body_sha256": "0xabc"},
    )
    kinds = [e["kind"] for e in runner.read_events(runner.ledger_path(spec, runs))]
    assert kinds.index(runner.SOURCE_QUERY) < len(kinds)
    assert runner.TERMINATED not in kinds  # the answer does not exist yet


def test_an_unknown_event_kind_or_caller_selected_outcome_is_refused(locked):
    spec, runs, root = locked
    with pytest.raises(ValueError, match="unknown event kind"):
        runner.append_event(runner.ledger_path(spec, runs), {"kind": "looks_fine"})
    slot = _slot(spec, root, "case-1", "manual")
    runner.claim_slot(spec, runs, slot=slot, repo_root=root)
    with pytest.raises(TypeError, match="outcome"):
        runner.terminate_slot(
            spec,
            runs,
            slot=slot,
            outcome="mostly_worked",
            repo_root=root,
        )
