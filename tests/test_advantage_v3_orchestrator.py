"""The driver that walks a locked family's registered slots.

runner.py is the ledger. These tests attack the driver: a slot that is never claimed
before work starts, an agent that runs before the manual block, a failed primary that
is retried into a success, a clock the operator can edit, and an unlocked spec that
still reaches an arm. Each test names the mutation it kills.
"""

import inspect
import json
from pathlib import Path

import pytest

import docket.advantage.v3.spec as spec_module
from docket.advantage.v3 import orchestrator, runner, scoring
from docket.advantage.v3.spec import PairedSpec, lock_inputs, save
from docket.hire.receipts import canonical_hash

from test_advantage_v3_spec import (  # noqa: F401
    SPECS_DIR,
    _input_record,
    _valid,
    _write_inputs,
)


@pytest.fixture(autouse=True)
def _register_the_minimal_test_protocol_validator(monkeypatch):
    monkeypatch.setitem(
        spec_module.INPUT_VALIDATORS,
        "t",
        lambda _spec, _body, _cases, _repo_root: None,
    )


@pytest.fixture
def locked(tmp_path: Path):
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


def _succeed(slot, _revealed):
    return {"raw_output": {"answer": f"{slot.case_id}:{slot.arm}"}}


def _terminals(spec, runs):
    return [
        event
        for event in runner.read_events(runner.ledger_path(spec, runs))
        if event["kind"] in (runner.TERMINATED, runner.INTERRUPTED)
    ]


def _starts(spec, runs):
    return [
        event
        for event in runner.read_events(runner.ledger_path(spec, runs))
        if event["kind"] == runner.STARTED
    ]


def _complete_manual_block(spec, runs, root):
    orchestrator.run_remaining(
        spec, runs, repo_root=root, invoke=_succeed, limit=spec.n_planned
    )


def _valid_agent_body(payload, result=None):
    if result is None:
        result = {"answer": "hired"}
    return {
        "result": result,
        "receipt": {
            "service": "test-service",
            "input_hash": canonical_hash(payload),
            "output_hash": canonical_hash(result),
            "payment": {"status": "free_tier"},
        },
    }


def _bound_agent(spec, runs):
    return [
        event
        for event in _terminals(spec, runs)
        if event["slot"] == "t::case-1::agent::primary"
    ]


def test_a_slot_is_claimed_on_disk_before_invoke_runs(locked):
    """Mutation: invoke the arm, then claim — a crash mid-arm leaves no slot at all."""
    spec, runs, root = locked
    seen = []

    def invoke(slot, revealed):
        starts = _starts(spec, runs)
        seen.append(
            {
                "invoked": slot.slot,
                "claimed": [event["slot"] for event in starts],
            }
        )
        return _succeed(slot, revealed)

    terminal = orchestrator.run_next(spec, runs, repo_root=root, invoke=invoke)

    assert seen == [
        {
            "invoked": "t::case-1::manual::primary",
            "claimed": ["t::case-1::manual::primary"],
        }
    ]
    assert terminal["slot"] == "t::case-1::manual::primary"
    assert terminal["kind"] == runner.TERMINATED
    assert terminal["outcome"] == runner.SUCCEEDED
    assert terminal["raw_output"] == {"answer": "case-1:manual"}


def test_a_crash_after_claim_leaves_that_slot_interrupted_not_absent(locked):
    """Mutation: skip the claim, so a dead process looks like the slot was never started.

    Also kills: resume without recover_interrupted, then claim the same slot again.
    """
    spec, runs, root = locked
    crashed = _slot(spec, root, "case-1", "manual")
    runner.claim_slot(spec, runs, slot=crashed, repo_root=root)

    invoked = []

    def invoke(slot, _revealed):
        invoked.append((slot.case_id, slot.arm))
        return _succeed(slot, _revealed)

    results = orchestrator.run_remaining(spec, runs, repo_root=root, invoke=invoke)

    state = runner.read_state(runner.ledger_path(spec, runs))
    assert state[crashed.slot].terminal["outcome"] == runner.INTERRUPTED
    assert state[crashed.slot].terminal["elapsed_ns"] is None
    assert ("case-1", "manual") not in invoked
    assert invoked[0] == ("case-2", "manual")
    assert results[0]["slot"] == crashed.slot
    assert results[0]["outcome"] == runner.INTERRUPTED
    assert results[1]["slot"] == "t::case-2::manual::primary"


def test_the_first_terminal_slot_is_the_first_manual_case(locked):
    """Mutation: walk agents first, or alternate inside a pair."""
    spec, runs, root = locked
    invoked = []

    def invoke(slot, _revealed):
        invoked.append((slot.case_id, slot.arm))
        return _succeed(slot, _revealed)

    orchestrator.run_remaining(spec, runs, repo_root=root, invoke=invoke)

    assert invoked[: spec.n_planned] == [
        (f"case-{number}", "manual") for number in range(1, spec.n_planned + 1)
    ]
    assert invoked[spec.n_planned :] == [
        (f"case-{number}", "agent") for number in range(1, spec.n_planned + 1)
    ]
    first = _terminals(spec, runs)[0]
    assert first["slot"] == "t::case-1::manual::primary"
    assert first["arm"] == "manual"
    last_manual = _terminals(spec, runs)[spec.n_planned - 1]
    first_agent = _terminals(spec, runs)[spec.n_planned]
    assert last_manual["slot"] == "t::case-5::manual::primary"
    assert first_agent["slot"] == "t::case-1::agent::primary"


def test_asking_for_an_agent_slot_before_the_manual_block_refuses_without_claiming_it(
    locked,
):
    """Mutation: honour a caller-chosen slot and start the agent block early."""
    spec, runs, root = locked
    invoked = []

    def invoke(slot, _revealed):
        invoked.append(slot.slot)
        return _succeed(slot, _revealed)

    agent = _slot(spec, root, "case-1", "agent")
    with pytest.raises(
        orchestrator.OrchestratorRefused,
        match="the registered manual block must run next; refusing t::case-1::agent::primary",
    ):
        orchestrator.run_next(spec, runs, repo_root=root, invoke=invoke, slot=agent)

    assert invoked == []
    assert _starts(spec, runs) == []
    assert _terminals(spec, runs) == []


def test_a_failed_primary_binds_and_a_later_success_cannot_replace_it(locked):
    """Mutation: retry a failed slot until invoke returns success; keep the last one.

    The second run_remaining is the planted later attempt. The ledger must still
    carry the first failure for case-1/manual, and invoke must not be asked again.
    """
    spec, runs, root = locked
    attempts = []

    def invoke(slot, _revealed):
        attempts.append((slot.case_id, slot.arm))
        if slot.case_id == "case-1" and slot.arm == "manual":
            return {"failure": {"kind": "technical", "message": "first answer"}}
        return _succeed(slot, _revealed)

    orchestrator.run_remaining(spec, runs, repo_root=root, invoke=invoke)
    orchestrator.run_remaining(spec, runs, repo_root=root, invoke=invoke)

    bound = [
        event
        for event in _terminals(spec, runs)
        if event["slot"] == "t::case-1::manual::primary"
    ]
    assert len(bound) == 1
    assert bound[0]["outcome"] == runner.FAILED
    assert bound[0]["failure"] == {"kind": "technical", "message": "first answer"}
    assert bound[0]["raw_output"] is None
    assert attempts.count(("case-1", "manual")) == 1


def test_elapsed_ns_comes_from_the_injected_clock_not_from_the_arm(locked):
    """Mutation: write invoke['elapsed_ns'] into the ledger, or ignore `clock`."""
    spec, runs, root = locked
    calls = {"n": 0}

    def clock():
        calls["n"] += 1
        if calls["n"] == 1:
            return 10
        return 10 + 7_000_000_000

    def invoke(_slot, _revealed):
        return {
            "raw_output": {"answer": "operator-timed"},
            "elapsed_ns": 1,
            "eligible_for_speed": False,
        }

    terminal = orchestrator.run_next(
        spec, runs, repo_root=root, invoke=invoke, clock=clock
    )

    assert terminal["slot"] == "t::case-1::manual::primary"
    assert terminal["elapsed_ns"] == 7_000_000_000
    assert terminal["outcome"] == runner.SUCCEEDED
    assert terminal["eligible_for_speed"] is True


def test_a_timeout_on_the_orchestrator_clock_beats_a_late_success(locked):
    """Mutation: keep a success whose elapsed already passed the registered deadline."""
    spec, runs, root = locked
    timeout_ns = spec.timing["timeout_seconds"] * 1_000_000_000
    calls = {"n": 0}

    def clock():
        calls["n"] += 1
        return 0 if calls["n"] == 1 else timeout_ns + 1

    terminal = orchestrator.run_next(
        spec,
        runs,
        repo_root=root,
        invoke=lambda slot, revealed: _succeed(slot, revealed),
        clock=clock,
    )

    assert terminal["slot"] == "t::case-1::manual::primary"
    assert terminal["outcome"] == runner.TIMED_OUT
    assert terminal["raw_output"] is None
    assert terminal["eligible_for_speed"] is False


def test_run_next_calls_assert_runnable_even_when_prepare_is_skipped(
    locked, monkeypatch
):
    """Mutation: drop `assert_runnable` from `run_next` and rely on runner's `_prepare`.

    `_prepare` already reaches `assert_runnable` through `open_run`. A caller that
    passes `prepare=False` — `main` and `run_remaining` both do after their own
    prepare — would skip that path. The orchestrator's own call is the property.
    """
    spec, runs, root = locked
    invoked = []

    def invoke(slot, revealed):
        invoked.append(slot.slot)
        return _succeed(slot, revealed)

    def refuse(_spec, *, repo_root=None):
        raise ValueError("assert-runnable-from-run-next")

    monkeypatch.setattr(orchestrator, "assert_runnable", refuse)

    with pytest.raises(
        orchestrator.OrchestratorRefused, match="assert-runnable-from-run-next"
    ):
        orchestrator.run_next(spec, runs, repo_root=root, invoke=invoke, prepare=False)

    assert invoked == []
    assert _starts(spec, runs) == []
    assert _terminals(spec, runs) == []


def test_run_remaining_calls_assert_runnable_before_any_slot(locked, monkeypatch):
    """Mutation: drop `assert_runnable` from `run_remaining` and walk slots anyway.

    `run_next` is stubbed so this pins `run_remaining`'s own call, not the one
    it would inherit by delegating.
    """
    spec, runs, root = locked

    def refuse(_spec, *, repo_root=None):
        raise ValueError("assert-runnable-from-run-remaining")

    def should_not_run(*_args, **_kwargs):
        raise AssertionError("run_remaining reached a slot without assert_runnable")

    monkeypatch.setattr(orchestrator, "assert_runnable", refuse)
    monkeypatch.setattr(orchestrator, "run_next", should_not_run)

    with pytest.raises(
        orchestrator.OrchestratorRefused, match="assert-runnable-from-run-remaining"
    ):
        orchestrator.run_remaining(spec, runs, repo_root=root, invoke=_succeed)

    assert _starts(spec, runs) == []
    assert _terminals(spec, runs) == []


def test_an_unlocked_spec_never_claims_a_slot(tmp_path):
    """Mutation: skip assert_runnable and start an arm against stage one."""
    spec = PairedSpec(**_valid())
    runs = tmp_path / "runs"
    invoked = []

    def invoke(slot, _revealed):
        invoked.append(slot.slot)
        return _succeed(slot, _revealed)

    with pytest.raises(orchestrator.OrchestratorRefused, match="no locked inputs"):
        orchestrator.run_next(spec, runs, repo_root=tmp_path, invoke=invoke)

    assert invoked == []
    path = runner.ledger_path(spec, runs)
    assert not path.exists() or path.read_text(encoding="utf-8").strip() == ""


def test_the_default_hire_posts_to_the_registered_endpoint(locked):
    """Mutation: call the in-process catalogue, or POST somewhere the spec did not name.

    Also kills an import-time `hire=httpx.post` default: the function we pass here is
    the one that must run, not a client bound when the module was imported.
    """
    spec, runs, root = locked
    seen = {}

    def manuals_only(slot, _revealed):
        if slot.arm != "manual":
            raise AssertionError(f"default hire should take the agent slot, not {slot}")
        return _succeed(slot, _revealed)

    orchestrator.run_remaining(
        spec, runs, repo_root=root, invoke=manuals_only, limit=spec.n_planned
    )

    def hire(url, *, json, headers, timeout, client=None):
        seen["url"] = url
        seen["body"] = json
        seen["timeout"] = timeout
        seen["headers"] = headers
        result = {"answer": "hired"}
        return runner.httpx.Response(
            200,
            json={
                "result": result,
                "receipt": {
                    "service": "test-service",
                    "input_hash": canonical_hash(json),
                    "output_hash": canonical_hash(result),
                    "payment": {"status": "free_tier"},
                },
            },
        )

    terminal = orchestrator.run_next(
        spec,
        runs,
        repo_root=root,
        hire=hire,
        payment_headers={"X-PAYMENT": "signed"},
    )

    assert terminal["slot"] == "t::case-1::agent::primary"
    assert terminal["outcome"] == runner.SUCCEEDED
    assert terminal["raw_output"] == {"answer": "hired"}
    assert seen == {
        "url": spec.execution_protocol["agent_endpoint"],
        "body": {},
        "timeout": spec.timing["timeout_seconds"],
        "headers": {"X-PAYMENT": "signed"},
    }


def test_a_422_from_the_registered_endpoint_binds_as_blocked_for_that_agent_slot(
    locked,
):
    """Mutation: treat a contract refusal as a success, or retry it into a later 200."""
    spec, runs, root = locked

    def manuals_only(slot, revealed):
        if slot.arm != "manual":
            raise AssertionError(slot.slot)
        return _succeed(slot, revealed)

    orchestrator.run_remaining(
        spec, runs, repo_root=root, invoke=manuals_only, limit=spec.n_planned
    )

    def refuse(_url, *, json, headers, timeout, client=None):
        return runner.httpx.Response(422, json={"error": "shape"})

    first = orchestrator.run_next(spec, runs, repo_root=root, hire=refuse)
    assert first["slot"] == "t::case-1::agent::primary"
    assert first["outcome"] == runner.BLOCKED_CONTRACT

    def later_ok(url, *, json, headers, timeout, client=None):
        result = {"answer": "too late"}
        return runner.httpx.Response(
            200,
            json={
                "result": result,
                "receipt": {
                    "service": "test-service",
                    "input_hash": canonical_hash(json),
                    "output_hash": canonical_hash(result),
                    "payment": {"status": "free_tier"},
                },
            },
        )

    orchestrator.run_remaining(spec, runs, repo_root=root, hire=later_ok)
    bound = [
        event
        for event in _terminals(spec, runs)
        if event["slot"] == "t::case-1::agent::primary"
    ]
    assert len(bound) == 1
    assert bound[0]["outcome"] == runner.BLOCKED_CONTRACT
    assert bound[0]["raw_output"] is None


def test_a_200_with_the_wrong_service_binds_the_agent_slot_as_failed(locked):
    """Mutation: `receipt_valid = True` — a forged service id becomes SUCCEEDED."""
    spec, runs, root = locked
    _complete_manual_block(spec, runs, root)

    def hire(_url, *, json, headers, timeout, client=None):
        body = _valid_agent_body(json)
        body["receipt"]["service"] = "someone-else"
        return runner.httpx.Response(200, json=body)

    terminal = orchestrator.run_next(spec, runs, repo_root=root, hire=hire)
    bound = _bound_agent(spec, runs)

    assert terminal["slot"] == "t::case-1::agent::primary"
    assert terminal["outcome"] == runner.FAILED
    assert terminal["failure"]["kind"] == "invalid_receipt_or_empty"
    assert terminal["raw_output"] is None
    assert len(bound) == 1
    assert bound[0]["outcome"] == runner.FAILED
    assert bound[0]["failure"]["kind"] == "invalid_receipt_or_empty"


def test_a_200_with_the_wrong_input_hash_binds_the_agent_slot_as_failed(locked):
    """Mutation: drop the input_hash conjunct — a receipt for a different request succeeds."""
    spec, runs, root = locked
    _complete_manual_block(spec, runs, root)

    def hire(_url, *, json, headers, timeout, client=None):
        body = _valid_agent_body(json)
        body["receipt"]["input_hash"] = canonical_hash({"not": "this payload"})
        return runner.httpx.Response(200, json=body)

    terminal = orchestrator.run_next(spec, runs, repo_root=root, hire=hire)
    bound = _bound_agent(spec, runs)

    assert terminal["outcome"] == runner.FAILED
    assert terminal["failure"]["kind"] == "invalid_receipt_or_empty"
    assert terminal["raw_output"] is None
    assert len(bound) == 1
    assert bound[0]["outcome"] == runner.FAILED


def test_a_200_with_the_wrong_output_hash_binds_the_agent_slot_as_failed(locked):
    """Mutation: drop the output_hash conjunct — a result that does not match binds."""
    spec, runs, root = locked
    _complete_manual_block(spec, runs, root)

    def hire(_url, *, json, headers, timeout, client=None):
        body = _valid_agent_body(json)
        body["receipt"]["output_hash"] = canonical_hash({"answer": "different"})
        return runner.httpx.Response(200, json=body)

    terminal = orchestrator.run_next(spec, runs, repo_root=root, hire=hire)
    bound = _bound_agent(spec, runs)

    assert terminal["outcome"] == runner.FAILED
    assert terminal["failure"]["kind"] == "invalid_receipt_or_empty"
    assert terminal["raw_output"] is None
    assert len(bound) == 1
    assert bound[0]["outcome"] == runner.FAILED


def test_a_200_with_a_missing_payment_binds_the_agent_slot_as_failed(locked):
    """Mutation: drop the payment-dict conjunct — a receipt with no payment succeeds."""
    spec, runs, root = locked
    _complete_manual_block(spec, runs, root)

    def hire(_url, *, json, headers, timeout, client=None):
        body = _valid_agent_body(json)
        del body["receipt"]["payment"]
        return runner.httpx.Response(200, json=body)

    terminal = orchestrator.run_next(spec, runs, repo_root=root, hire=hire)
    bound = _bound_agent(spec, runs)

    assert terminal["outcome"] == runner.FAILED
    assert terminal["failure"]["kind"] == "invalid_receipt_or_empty"
    assert terminal["raw_output"] is None
    assert len(bound) == 1
    assert bound[0]["outcome"] == runner.FAILED


def test_a_200_with_an_unsettled_payment_binds_the_agent_slot_as_failed(locked):
    """Mutation: drop the free_tier/settled conjunct — a pending payment succeeds."""
    spec, runs, root = locked
    _complete_manual_block(spec, runs, root)

    def hire(_url, *, json, headers, timeout, client=None):
        body = _valid_agent_body(json)
        body["receipt"]["payment"] = {"status": "pending"}
        return runner.httpx.Response(200, json=body)

    terminal = orchestrator.run_next(spec, runs, repo_root=root, hire=hire)
    bound = _bound_agent(spec, runs)

    assert terminal["outcome"] == runner.FAILED
    assert terminal["failure"]["kind"] == "invalid_receipt_or_empty"
    assert terminal["raw_output"] is None
    assert len(bound) == 1
    assert bound[0]["outcome"] == runner.FAILED


def test_a_200_with_an_empty_result_binds_the_agent_slot_as_failed(locked):
    """Mutation: drop the nonempty-result conjunct — `{}` binds as SUCCEEDED.

    `None` would still fail at terminate_slot even with `receipt_valid = True`.
    An empty object would not.
    """
    spec, runs, root = locked
    _complete_manual_block(spec, runs, root)

    def hire(_url, *, json, headers, timeout, client=None):
        return runner.httpx.Response(200, json=_valid_agent_body(json, result={}))

    terminal = orchestrator.run_next(spec, runs, repo_root=root, hire=hire)
    bound = _bound_agent(spec, runs)

    assert terminal["outcome"] == runner.FAILED
    assert terminal["failure"]["kind"] == "invalid_receipt_or_empty"
    assert terminal["raw_output"] is None
    assert len(bound) == 1
    assert bound[0]["outcome"] == runner.FAILED
    assert bound[0]["raw_output"] is None


def test_a_500_from_the_registered_endpoint_binds_as_http_error(locked):
    """Mutation: treat a 500 as success, or collapse it into the 422 contract path."""
    spec, runs, root = locked
    _complete_manual_block(spec, runs, root)

    def hire(_url, *, json, headers, timeout, client=None):
        return runner.httpx.Response(500, json={"error": "boom"})

    terminal = orchestrator.run_next(spec, runs, repo_root=root, hire=hire)
    bound = _bound_agent(spec, runs)

    assert terminal["outcome"] == runner.FAILED
    assert terminal["failure"]["kind"] == "http_error"
    assert "500" in terminal["failure"]["message"]
    assert terminal["raw_output"] is None
    assert len(bound) == 1
    assert bound[0]["outcome"] == runner.FAILED
    assert bound[0]["failure"]["kind"] == "http_error"


def test_malformed_json_from_the_registered_endpoint_binds_as_malformed_json(locked):
    """Mutation: skip the json() parse, or treat a 200 body as a success."""
    spec, runs, root = locked
    _complete_manual_block(spec, runs, root)

    def hire(_url, *, json, headers, timeout, client=None):
        return runner.httpx.Response(200, content=b"not-json")

    terminal = orchestrator.run_next(spec, runs, repo_root=root, hire=hire)
    bound = _bound_agent(spec, runs)

    assert terminal["outcome"] == runner.FAILED
    assert terminal["failure"]["kind"] == "malformed_json"
    assert terminal["raw_output"] is None
    assert len(bound) == 1
    assert bound[0]["outcome"] == runner.FAILED
    assert bound[0]["failure"]["kind"] == "malformed_json"


def test_a_transport_error_from_hire_binds_as_transport_error(locked):
    """Mutation: swallow ConnectError, or record it as a success with no receipt."""
    spec, runs, root = locked
    _complete_manual_block(spec, runs, root)

    def hire(_url, *, json, headers, timeout, client=None):
        raise runner.httpx.ConnectError("offline")

    terminal = orchestrator.run_next(spec, runs, repo_root=root, hire=hire)
    bound = _bound_agent(spec, runs)

    assert terminal["outcome"] == runner.FAILED
    assert terminal["failure"]["kind"] == "transport_error"
    assert "ConnectError" in terminal["failure"]["message"]
    assert terminal["raw_output"] is None
    assert len(bound) == 1
    assert bound[0]["outcome"] == runner.FAILED
    assert bound[0]["failure"]["kind"] == "transport_error"


def test_a_timeout_from_hire_binds_the_agent_slot_as_timed_out(locked):
    """Mutation: drop the TimeoutException branch, or persist it as FAILED."""
    spec, runs, root = locked
    _complete_manual_block(spec, runs, root)

    def hire(_url, *, json, headers, timeout, client=None):
        raise runner.httpx.TimeoutException("deadline")

    terminal = orchestrator.run_next(spec, runs, repo_root=root, hire=hire)
    bound = _bound_agent(spec, runs)

    assert terminal["outcome"] == runner.TIMED_OUT
    assert terminal["failure"]["kind"] == runner.TIMED_OUT
    assert terminal["raw_output"] is None
    assert len(bound) == 1
    assert bound[0]["outcome"] == runner.TIMED_OUT
    assert bound[0]["raw_output"] is None


def test_a_settled_hire_records_a_report_compatible_direct_cost(locked):
    """Mutation: persist asset/payment_status instead of the scorer's amount/unit."""
    spec, runs, root = locked
    _complete_manual_block(spec, runs, root)

    def hire(_url, *, json, headers, timeout, client=None):
        body = _valid_agent_body(json)
        body["receipt"]["payment"] = {
            "status": "settled",
            "amount": "5",
            "asset": "0xasset",
        }
        return runner.httpx.Response(200, json=body)

    terminal = orchestrator.run_next(spec, runs, repo_root=root, hire=hire)

    assert terminal["outcome"] == runner.SUCCEEDED
    assert terminal["cost"] == {"amount": "5", "unit": "0xasset"}
    assert scoring.cost_metrics({("case-1", "agent"): {"terminal": terminal}})[
        "totals"
    ] == [{"arm": "agent", "amount": "5", "unit": "0xasset"}]


@pytest.mark.parametrize(
    "payment",
    [
        {"status": "settled", "amount": "not-a-number", "asset": "0xasset"},
        {"status": "settled", "amount": "5", "asset": ""},
    ],
    ids=("nonnumeric-amount", "blank-asset"),
)
def test_unreportable_payment_metadata_stays_in_the_receipt_not_cost(locked, payment):
    """Mutation: persist a cost the report cannot sum honestly."""
    spec, runs, root = locked
    _complete_manual_block(spec, runs, root)

    def hire(_url, *, json, headers, timeout, client=None):
        body = _valid_agent_body(json)
        body["receipt"]["payment"] = payment
        return runner.httpx.Response(200, json=body)

    terminal = orchestrator.run_next(spec, runs, repo_root=root, hire=hire)

    assert terminal["outcome"] == runner.SUCCEEDED
    assert terminal["receipt"]["payment"] == payment
    assert terminal["cost"] is None
    assert (
        scoring.cost_metrics({("case-1", "agent"): {"terminal": terminal}})["totals"]
        == []
    )


def test_a_reveal_failure_is_refused_before_the_slot_is_claimed(locked, monkeypatch):
    """Mutation: wrap `_reveal` and `run_arm` in one `except` and bind FAILED.

    A missing case (or any other reveal fault) is not an arm result. Binding it
    as `invoke_error` spends a preregistered pair on a fault the operator can
    still fix. The slot must stay unclaimed.
    """
    spec, runs, root = locked
    invoked = []

    def invoke(slot, _revealed):
        invoked.append(slot.slot)
        return _succeed(slot, _revealed)

    def missing(_spec, slot, _repo_root):
        raise StopIteration(slot.case_id)

    monkeypatch.setattr(orchestrator, "_reveal", missing)

    with pytest.raises(orchestrator.OrchestratorRefused, match="revealed"):
        orchestrator.run_next(spec, runs, repo_root=root, invoke=invoke)

    assert invoked == []
    assert _starts(spec, runs) == []
    assert _terminals(spec, runs) == []


def test_an_invoke_exception_binds_as_that_slots_first_failure(locked):
    """Mutation: leave the slot dangling, or retry the invoke until it stops raising."""
    spec, runs, root = locked

    def boom(slot, _revealed):
        raise RuntimeError("operator dropped the answer")

    terminal = orchestrator.run_next(spec, runs, repo_root=root, invoke=boom)
    assert terminal["slot"] == "t::case-1::manual::primary"
    assert terminal["outcome"] == runner.FAILED
    assert "operator dropped the answer" in terminal["failure"]["message"]

    invoked = []

    def later(slot, revealed):
        invoked.append(slot.slot)
        return _succeed(slot, revealed)

    orchestrator.run_remaining(spec, runs, repo_root=root, invoke=later)
    assert "t::case-1::manual::primary" not in invoked
    bound = [
        event
        for event in _terminals(spec, runs)
        if event["slot"] == "t::case-1::manual::primary"
    ]
    assert len(bound) == 1
    assert bound[0]["outcome"] == runner.FAILED


def test_a_missing_manual_invoke_is_refused_before_the_slot_is_claimed(locked):
    """Mutation: claim the next manual, then notice there is no operator, and leave it
    dangling — or terminate it as a failure that looks like the operator answered badly."""
    spec, runs, root = locked

    with pytest.raises(orchestrator.OrchestratorRefused, match="manual"):
        orchestrator.run_next(spec, runs, repo_root=root)

    assert _starts(spec, runs) == []
    assert _terminals(spec, runs) == []


def test_invoke_clock_and_hire_are_resolved_at_call_time_not_as_signature_defaults():
    """Mutation: `def run_next(..., hire=httpx.post, clock=time.monotonic_ns)`.

    A default binds at import. The capture already paid for that once.
    """
    parameters = inspect.signature(orchestrator.run_next).parameters
    for name in ("invoke", "clock", "hire"):
        assert parameters[name].default is None, name
    remaining = inspect.signature(orchestrator.run_remaining).parameters
    for name in ("invoke", "clock", "hire"):
        assert remaining[name].default is None, name


def test_main_refuses_an_unlocked_family_id_resolved_from_the_installed_package(
    tmp_path, capsys
):
    """Mutation: resolve the family id as a cwd path, or replace main's
    `assert_runnable` with `pass` so the refusal comes from runner instead.

    v3-01-range-doctor is a real registration with empty inputs_sha256. If main can
    load it by family id, the packaged spec is what ran; if it then starts an arm,
    the lock did not hold. `before any slot` is produced only by main's own
    `assert_runnable` — later refusals from `_prepare`/`run_next` do not say that.
    """
    runs = tmp_path / "runs"
    code = orchestrator.main(["v3-01-range-doctor", str(runs)])

    assert code == 2
    out = capsys.readouterr().out
    assert "before any slot" in out
    assert "no locked inputs" in out
    assert not runs.exists() or not any(runs.glob("*.jsonl"))


def test_main_interactive_claims_before_reveal_and_reads_one_submission(locked, capsys):
    """Mutation: reveal/read before the timed claim, or read a second submission."""
    spec, runs, root = locked

    class OneSubmission:
        calls = 0

        def readline(self):
            self.calls += 1
            assert self.calls == 1
            assert [event["slot"] for event in _starts(spec, runs)] == [
                "t::case-1::manual::primary"
            ]
            assert _terminals(spec, runs) == []
            revealed = capsys.readouterr().out.splitlines()
            assert len(revealed) == 1
            assert json.loads(revealed[0]) == {
                "case": {"case_id": "case-1"},
                "slot": "t::case-1::manual::primary",
            }
            return '{"answer":"operator-one"}\n'

    stdin = OneSubmission()
    code = orchestrator.main(
        [
            str(root / "spec.json"),
            str(runs),
            "--interactive",
            "--repo-root",
            str(root),
            "--once",
        ],
        stdin=stdin,
    )

    assert code == 0
    assert stdin.calls == 1
    bound = [
        event
        for event in _terminals(spec, runs)
        if event["slot"] == "t::case-1::manual::primary"
    ]
    assert len(bound) == 1
    assert bound[0]["outcome"] == runner.SUCCEEDED
    assert bound[0]["raw_output"] == {"answer": "operator-one"}
    assert "t::case-1::manual::primary" in capsys.readouterr().out


def test_main_once_recovers_a_dangling_slot_before_running_the_next(locked, capsys):
    """Mutation: peek the next slot before recover_interrupted, so a crash looks like
    an active operator and the CLI refuses instead of closing case-1 as interrupted."""
    spec, runs, root = locked
    crashed = _slot(spec, root, "case-1", "manual")
    runner.claim_slot(spec, runs, slot=crashed, repo_root=root)

    class OneSubmission:
        def readline(self):
            return '{"answer":"two"}\n'

    code = orchestrator.main(
        [
            str(root / "spec.json"),
            str(runs),
            "--interactive",
            "--repo-root",
            str(root),
            "--once",
        ],
        stdin=OneSubmission(),
    )

    assert code == 0
    state = runner.read_state(runner.ledger_path(spec, runs))
    assert state[crashed.slot].terminal["outcome"] == runner.INTERRUPTED
    assert state["t::case-2::manual::primary"].terminal["raw_output"] == {
        "answer": "two"
    }
    assert ("case-1", "manual") not in [
        (event["case_id"], event["arm"])
        for event in _terminals(spec, runs)
        if event["outcome"] == runner.SUCCEEDED
    ]
    out = capsys.readouterr().out
    assert "t::case-1::manual::primary" in out
    assert "t::case-2::manual::primary" in out


def test_main_noninteractive_refuses_before_reading_or_claiming(locked, capsys):
    """Mutation: read stdin or claim a manual slot without explicit interaction."""
    spec, runs, root = locked

    class ForbiddenInput:
        def readline(self):
            raise AssertionError("noninteractive mode read a submission")

    code = orchestrator.main(
        [
            str(root / "spec.json"),
            str(runs),
            "--repo-root",
            str(root),
            "--once",
        ],
        stdin=ForbiddenInput(),
    )

    assert code == 2
    assert "--interactive" in capsys.readouterr().out
    assert _starts(spec, runs) == []
    assert _terminals(spec, runs) == []


def test_main_agent_slot_sends_the_payment_header_through_the_http_client(
    locked, capsys, monkeypatch
):
    """Mutation: drop the CLI header or the client before the registered POST."""
    spec, runs, root = locked
    _complete_manual_block(spec, runs, root)
    seen = {}

    def handle(request):
        payload = json.loads(request.content)
        seen.update(
            method=request.method,
            url=str(request.url),
            payment=request.headers.get("X-PAYMENT"),
            payload=payload,
        )
        return runner.httpx.Response(200, json=_valid_agent_body(payload))

    transport = runner.httpx.MockTransport(handle)
    real_http_hire = orchestrator._http_hire

    def injected_http_hire(url, *, json, headers, timeout, client=None):
        assert client is not None
        return real_http_hire(
            url, json=json, headers=headers, timeout=timeout, client=client
        )

    monkeypatch.setattr(orchestrator, "_http_hire", injected_http_hire)
    with runner.httpx.Client(transport=transport) as client:
        code = orchestrator.main(
            [
                str(root / "spec.json"),
                str(runs),
                "--repo-root",
                str(root),
                "--payment-header",
                "signed-payment",
                "--once",
            ],
            client=client,
        )

    assert code == 0
    assert seen == {
        "method": "POST",
        "url": spec.execution_protocol["agent_endpoint"],
        "payment": "signed-payment",
        "payload": {},
    }
    bound = _bound_agent(spec, runs)
    assert len(bound) == 1
    assert bound[0]["outcome"] == runner.SUCCEEDED
    assert bound[0]["raw_output"] == {"answer": "hired"}
    assert bound[0]["cost"] is None
    assert (
        scoring.cost_metrics({("case-1", "agent"): {"terminal": bound[0]}})["totals"]
        == []
    )
    assert "t::case-1::agent::primary succeeded" in capsys.readouterr().out


def test_main_stops_the_agent_block_on_a_payment_challenge(locked, capsys):
    """Mutation: treat HTTP 402 as a generic failure or continue into the next slot."""
    spec, runs, root = locked
    _complete_manual_block(spec, runs, root)
    requests = 0

    def handle(_request):
        nonlocal requests
        requests += 1
        return runner.httpx.Response(402, json={"error": "payment required"})

    transport = runner.httpx.MockTransport(handle)
    with runner.httpx.Client(transport=transport) as client:
        code = orchestrator.main(
            [str(root / "spec.json"), str(runs), "--repo-root", str(root)],
            client=client,
        )

    assert code == 2
    assert requests == 1
    terminals = [event for event in _terminals(spec, runs) if event["arm"] == "agent"]
    assert len(terminals) == 1
    assert terminals[0]["outcome"] == runner.BLOCKED_CONTRACT
    assert "blocked_service_contract" in capsys.readouterr().out
