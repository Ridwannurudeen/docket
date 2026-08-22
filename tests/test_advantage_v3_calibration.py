"""Seat calibration capture, and the selection it exists to make impossible.

The rule is: preserve failed attempts, do not select a later passing run. The dangerous way
to test that is to assert "it raises" or "it passes", because a bridge that quietly promoted
a later attempt would still raise on the cases where raising was expected. So the tests that
matter here assert **which attempt's answers reach the envelope** — with a better-looking
second attempt planted directly on disk, bypassing the write gate, exactly as an operator
could.
"""

import json
from base64 import b64encode
from pathlib import Path

import pytest

from docket.advantage.v3 import calibration
from docket.advantage.v3.spec import load

SPECS_DIR = Path(__file__).resolve().parents[1] / "docket/advantage/v3/specs"
SPEC = load(SPECS_DIR / "v3-03-warden-security.json")
YIELD_SPEC = load(SPECS_DIR / "v3-02-yield-router.json")
SEAT = "seat-a"


def _shared_set() -> bytes:
    cases = []
    for number in range(1, 9):
        hostile = number <= 4
        cases.append(
            {
                "case_id": f"cal-{number}",
                "input": {"payload": f"calibration payload {number}"},
                "expected_hostile": hostile,
                "expected_classes": ["PROMPT_INJECTION"] if hostile else [],
            }
        )
    return json.dumps(
        {"spec_id": SPEC.spec_id, "cases": cases}, sort_keys=True
    ).encode()


def _answer(correct: bool = True) -> bytes:
    shared = json.loads(_shared_set().decode("utf-8"))["cases"]
    return json.dumps(
        {
            "evaluator_id": SEAT,
            "results": [
                {
                    "case_id": case["case_id"],
                    "predicted_hostile": case["expected_hostile"]
                    if correct
                    else not case["expected_hostile"],
                    "predicted_classes": case["expected_classes"] if correct else [],
                }
                for case in shared
            ],
        },
        sort_keys=True,
    ).encode()


def _capture(root: Path, raw, *, seat: str = SEAT, error: str | None = None):
    # The ordinal comes from the request record, not from re-reading the directory: until
    # the response is written the attempt is deliberately unreadable, which is the property
    # that stops an unrecorded attempt from existing at all.
    opened = calibration.open_attempt(
        SPEC,
        root,
        evaluator_id=seat,
        model_build="build-x",
        session_id=f"session-{seat}",
        calibration_set=_shared_set(),
    )
    ordinal = opened["attempt_ordinal"]
    return calibration.record_response(
        SPEC,
        root,
        evaluator_id=seat,
        attempt_ordinal=ordinal,
        raw_response=raw,
        error=error,
    )


def _plant_second_attempt(root: Path, raw: bytes) -> None:
    """Write a second attempt straight to disk, the way an operator could.

    The write gate refuses to mint this. Planting it is the whole point: the bridge must
    still bind the first captured attempt even when a better one exists beside it.
    """
    first_response = calibration.response_path(SPEC, root, SEAT, 1)
    request = json.loads(
        calibration.request_path(SPEC, root, SEAT, 1).read_text(encoding="utf-8")
    )
    import hashlib

    request |= {
        "attempt_ordinal": 2,
        "previous_attempt_sha256": hashlib.sha256(
            first_response.read_bytes()
        ).hexdigest(),
    }
    req_path = calibration.request_path(SPEC, root, SEAT, 2)
    req_path.write_text(
        json.dumps(request, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )
    response = {
        "artifact_version": calibration.RESPONSE_VERSION,
        "spec_id": SPEC.spec_id,
        "evaluator_id": SEAT,
        "session_id": request["session_id"],
        "attempt_ordinal": 2,
        "request_sha256": hashlib.sha256(req_path.read_bytes()).hexdigest(),
        "received_at": "2026-08-16T00:00:00+00:00",
        "outcome": calibration.CAPTURED,
        "response_sha256": hashlib.sha256(raw).hexdigest(),
        "response_base64": b64encode(raw).decode("ascii"),
        "error": None,
    }
    calibration.response_path(SPEC, root, SEAT, 2).write_text(
        json.dumps(response, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )


def test_the_prompt_is_derived_from_the_registration_not_supplied(tmp_path):
    """Two callers with the same registration derive the same ask, byte for byte."""
    first = calibration.derive_prompt(SPEC, _shared_set(), SEAT)
    again = calibration.derive_prompt(SPEC, _shared_set(), SEAT)
    assert first == again
    body = json.loads(first.decode("utf-8"))
    assert body["stage_one_protocol_hash"] == SPEC.stage_one_protocol_hash
    assert [case["case_id"] for case in body["cases"]] == [
        f"cal-{n}" for n in range(1, 9)
    ]
    # The answer key is not in the ask.
    assert "expected_hostile" not in first.decode("utf-8")


def test_pancake_prompt_requests_submitted_answers():
    shared = {
        "spec_id": YIELD_SPEC.spec_id,
        "cases": [
            {
                "case_id": f"cal-{number}",
                "input": {"scenario": number},
                "expected": {"decision": "STAY"},
            }
            for number in range(1, 9)
        ],
    }
    raw_set = json.dumps(shared, sort_keys=True).encode()

    prompt = json.loads(calibration.derive_prompt(YIELD_SPEC, raw_set, SEAT))

    assert "submitted" in prompt["instruction"]
    assert "predicted_hostile" not in prompt["instruction"]


def test_pancake_calibration_captures_submitted_answers(tmp_path):
    shared = {
        "spec_id": YIELD_SPEC.spec_id,
        "cases": [
            {
                "case_id": f"cal-{number}",
                "input": {"scenario": number},
                "expected": {"decision": "STAY"},
            }
            for number in range(1, 9)
        ],
    }
    raw_set = json.dumps(shared, sort_keys=True).encode()
    for seat in YIELD_SPEC.scoring["evaluator_roster"]:
        evaluator_id = seat["evaluator_id"]
        request = calibration.open_attempt(
            YIELD_SPEC,
            tmp_path,
            evaluator_id=evaluator_id,
            model_build="build-x",
            session_id=f"session-{evaluator_id}",
            calibration_set=raw_set,
        )
        answer = {
            "evaluator_id": evaluator_id,
            "results": [
                {
                    "case_id": case["case_id"],
                    "submitted": case["expected"],
                }
                for case in shared["cases"]
            ],
        }
        calibration.record_response(
            YIELD_SPEC,
            tmp_path,
            evaluator_id=evaluator_id,
            attempt_ordinal=request["attempt_ordinal"],
            raw_response=json.dumps(answer, sort_keys=True).encode(),
        )

    rows = calibration.assemble_evaluator_calibration(YIELD_SPEC, tmp_path, raw_set)

    assert rows[0]["calibration_results"][0] == {
        "case_id": "cal-1",
        "input": {"scenario": 1},
        "expected": {"decision": "STAY"},
        "submitted": {"decision": "STAY"},
    }


def test_a_captured_seat_cannot_be_asked_again(tmp_path):
    _capture(tmp_path, _answer(correct=False))
    with pytest.raises(ValueError, match="already captured a response"):
        calibration.open_attempt(
            SPEC,
            tmp_path,
            evaluator_id=SEAT,
            model_build="build-x",
            session_id="session-retry",
            calibration_set=_shared_set(),
        )


def test_a_seat_that_never_answered_may_try_again(tmp_path):
    """A transport failure is not an answer, so it does not spend the seat's one attempt."""
    _capture(tmp_path, None, error="connection reset")
    second = calibration.open_attempt(
        SPEC,
        tmp_path,
        evaluator_id=SEAT,
        model_build="build-x",
        session_id="session-2",
        calibration_set=_shared_set(),
    )
    assert second["attempt_ordinal"] == 2
    # The second attempt names the first, so the first cannot later be removed quietly.
    assert second["previous_attempt_sha256"] is not None
    calibration.record_response(
        SPEC, tmp_path, evaluator_id=SEAT, attempt_ordinal=2, raw_response=_answer()
    )
    recorded = calibration.attempts(SPEC, tmp_path, SEAT)
    assert [entry["response"]["outcome"] for entry in recorded] == [
        "no_response",
        "captured",
    ]


def test_a_failure_is_written_down_rather_than_leaving_nothing(tmp_path):
    record = _capture(tmp_path, None, error="connection reset")
    assert record["outcome"] == calibration.NO_RESPONSE
    assert record["error"] == "connection reset"
    assert record["response_base64"] is None


def test_the_first_captured_attempt_binds_even_when_a_better_one_exists(tmp_path):
    """Fable's mutation 1: a bridge selecting max(ordinal) passes every single-attempt test.

    So this asserts the *values that reach the envelope*, not that something raised.
    """
    _capture(tmp_path, _answer(correct=False))
    # Every roster seat must have answered before the bridge will assemble anything.
    _capture(tmp_path, _answer(), seat="seat-b")
    _plant_second_attempt(tmp_path, _answer(correct=True))

    rows = calibration.assemble_evaluator_calibration(SPEC, tmp_path, _shared_set())
    seat_row = next(row for row in rows if row["evaluator_id"] == SEAT)
    first_case = next(
        entry
        for entry in seat_row["calibration_results"]
        if entry["case_id"] == "cal-1"
    )
    # cal-1 is hostile; attempt 1 said it was not. The wrong answer must survive.
    assert first_case["expected_hostile"] is True
    assert first_case["predicted_hostile"] is False
    assert first_case["predicted_classes"] == []


def test_unparseable_binding_bytes_do_not_fall_through_to_a_later_attempt(tmp_path):
    """Fable's mutation 2: `except JSONDecodeError: continue` silently promotes attempt 2."""
    _capture(tmp_path, b"\xff\xfe not json at all")
    _plant_second_attempt(tmp_path, _answer(correct=True))

    with pytest.raises(ValueError, match="not\\s+UTF-8 JSON|bound an attempt"):
        calibration.assemble_evaluator_calibration(SPEC, tmp_path, _shared_set())


def test_a_removed_attempt_leaves_a_link_that_points_at_nothing(tmp_path):
    _capture(tmp_path, None, error="timeout")
    calibration.open_attempt(
        SPEC,
        tmp_path,
        evaluator_id=SEAT,
        model_build="build-x",
        session_id="session-2",
        calibration_set=_shared_set(),
    )
    calibration.record_response(
        SPEC, tmp_path, evaluator_id=SEAT, attempt_ordinal=2, raw_response=_answer()
    )
    calibration.request_path(SPEC, tmp_path, SEAT, 1).unlink()
    calibration.response_path(SPEC, tmp_path, SEAT, 1).unlink()

    with pytest.raises(ValueError, match="not contiguous from 1"):
        calibration.attempts(SPEC, tmp_path, SEAT)


def test_an_attempt_whose_response_is_missing_is_refused(tmp_path):
    calibration.open_attempt(
        SPEC,
        tmp_path,
        evaluator_id=SEAT,
        model_build="build-x",
        session_id="session-1",
        calibration_set=_shared_set(),
    )
    with pytest.raises(ValueError, match="no response record"):
        calibration.attempts(SPEC, tmp_path, SEAT)


def test_the_expected_answers_come_from_the_key_not_from_the_seat(tmp_path):
    """A seat restating the truth would be a seat marking its own paper."""
    tampered = json.loads(_answer().decode("utf-8"))
    for row in tampered["results"]:
        row["expected_hostile"] = False
        row["expected_classes"] = ["INVENTED"]
    _capture(tmp_path, json.dumps(tampered, sort_keys=True).encode())
    _capture(tmp_path, _answer(), seat="seat-b")

    rows = calibration.assemble_evaluator_calibration(SPEC, tmp_path, _shared_set())
    entry = next(
        item for item in rows[0]["calibration_results"] if item["case_id"] == "cal-1"
    )
    assert entry["expected_hostile"] is True
    assert entry["expected_classes"] == ["PROMPT_INJECTION"]


def test_a_missing_prediction_is_not_defaulted(tmp_path):
    partial = json.loads(_answer().decode("utf-8"))
    del partial["results"][0]["predicted_classes"]
    _capture(tmp_path, json.dumps(partial, sort_keys=True).encode())
    with pytest.raises(ValueError, match="unanswered|not a default"):
        calibration.assemble_evaluator_calibration(SPEC, tmp_path, _shared_set())


def test_answering_a_different_calibration_set_is_refused(tmp_path):
    _capture(tmp_path, _answer())
    other = json.loads(_shared_set().decode("utf-8"))
    other["cases"][0]["input"]["payload"] = "a different question"
    with pytest.raises(ValueError, match="different calibration set"):
        calibration.assemble_evaluator_calibration(
            SPEC, tmp_path, json.dumps(other, sort_keys=True).encode()
        )


def test_an_envelope_row_that_was_never_captured_is_refused(tmp_path):
    for seat in ("seat-a", "seat-b"):
        _capture(tmp_path, _answer(), seat=seat)
    rows = calibration.assemble_evaluator_calibration(SPEC, tmp_path, _shared_set())
    raw = _shared_set()
    body = {
        "calibration_set": {"body_base64": b64encode(raw).decode("ascii")},
        "evaluator_calibration": rows,
    }
    calibration.verify_calibration_capture(SPEC, body, tmp_path)

    edited = json.loads(json.dumps(body))
    edited["evaluator_calibration"][0]["calibration_results"][0][
        "predicted_hostile"
    ] = not edited["evaluator_calibration"][0]["calibration_results"][0][
        "predicted_hostile"
    ]
    with pytest.raises(ValueError, match="differs from what the binding attempt"):
        calibration.verify_calibration_capture(SPEC, edited, tmp_path)


def test_the_bridge_does_not_score(tmp_path):
    """Scoring lives in the validator, once. A seat that answers everything wrong still
    assembles — being wrong is the validator's verdict to reach, not the bridge's."""
    for seat in ("seat-a", "seat-b"):
        _capture(tmp_path, _answer(correct=False), seat=seat)
    rows = calibration.assemble_evaluator_calibration(SPEC, tmp_path, _shared_set())
    assert len(rows) == 2
    source = Path(calibration.__file__).read_text(encoding="utf-8")
    for arithmetic in ("micro_f1", "0.80", "< 7", "seven of eight"):
        assert arithmetic not in source.split('"""', 2)[2], arithmetic


def test_edited_response_bytes_are_refused_against_their_own_digest(tmp_path):
    """The module records a digest of what the seat said. It has to read it back.

    Without this check the digest is decoration: an operator can rewrite `response_base64`
    to a better answer, leave `response_sha256` untouched, and the envelope assembles
    cleanly. The one artifact built to make a response tamper-evident becomes the place
    tampering does not show.
    """
    # The seat actually answered badly; the tamper replaces that with a perfect sheet.
    _capture(tmp_path, _answer(correct=False))
    _capture(tmp_path, _answer(), seat="seat-b")

    path = calibration.response_path(SPEC, tmp_path, SEAT, 1)
    record = json.loads(path.read_text(encoding="utf-8"))
    improved = _answer(correct=True)
    assert b64encode(improved).decode("ascii") != record["response_base64"]
    record["response_base64"] = b64encode(improved).decode("ascii")
    # response_sha256 deliberately left as it was.
    path.write_text(
        json.dumps(record, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )

    with pytest.raises(ValueError, match="do not match the digest recorded"):
        calibration.assemble_evaluator_calibration(SPEC, tmp_path, _shared_set())
