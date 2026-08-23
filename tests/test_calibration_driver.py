"""The calibration run driver, attacked at the paths that would quietly invalidate it.

Each test names the mutation it kills. A mutation that still passes is a decorative test.
"""

import hashlib
import inspect
import json
from base64 import b64decode
from pathlib import Path

import pytest

from docket.advantage.v3 import calibration, calibration_driver
from docket.advantage.v3.spec import load

SPECS_DIR = Path(__file__).resolve().parents[1] / "docket/advantage/v3/specs"
SPEC = load(SPECS_DIR / "v3-03-warden-security.json")
CALIBRATION_PATH = (
    Path(__file__).resolve().parents[1]
    / "docket/advantage/v3/sources/warden-calibration-set.json"
)
SEAT = "seat-a"
# Bytes a JSON parse-and-dump would rewrite: key order, spacing, trailing newlines.
UNMODIFIED = b'{"z": 1, "a": 2}\n\n'


def _set() -> bytes:
    return CALIBRATION_PATH.read_bytes()


def _run(root: Path, call_seat, *, seat: str = SEAT, session_id: str | None = None):
    return calibration_driver.run_seat(
        SPEC,
        root,
        evaluator_id=seat,
        model_build="build-x",
        session_id=session_id or f"session-{seat}",
        calibration_set=_set(),
        call_seat=call_seat,
    )


def _response(root: Path, seat: str = SEAT, ordinal: int = 1) -> dict:
    path = calibration.response_path(SPEC, root, seat, ordinal)
    return json.loads(path.read_text(encoding="utf-8"))


def test_an_exception_from_the_seat_still_persists_a_response(tmp_path):
    """Mutation: catch the exception and return without calling record_response.

    The next invocation would then see no capture and let the seat try again.
    """

    def boom(_prompt):
        raise RuntimeError("seat exploded")

    with pytest.raises(RuntimeError, match="seat exploded"):
        _run(tmp_path, boom)

    record = _response(tmp_path)
    assert record["outcome"] == calibration.NO_RESPONSE
    assert "RuntimeError" in record["error"]
    assert "seat exploded" in record["error"]
    assert record["response_base64"] is None


def test_a_timeout_from_the_seat_still_persists_a_response(tmp_path):
    """Mutation: treat TimeoutError as retryable and call the seat again.

    One attempt per invocation. A timeout is an answer of nothing, not a cue to try
    until something comes back.
    """
    calls = {"n": 0}

    def hang(_prompt):
        calls["n"] += 1
        raise TimeoutError("seat timed out")

    with pytest.raises(TimeoutError, match="seat timed out"):
        _run(tmp_path, hang)

    assert calls["n"] == 1
    record = _response(tmp_path)
    assert record["outcome"] == calibration.NO_RESPONSE
    assert "TimeoutError" in record["error"]
    assert "seat timed out" in record["error"]
    assert record["response_base64"] is None


def test_returned_bytes_are_persisted_unmodified(tmp_path):
    """Mutation: json.loads / dumps the seat's body before recording it.

    The digest is taken over what arrived. A pretty-print or key sort would bind a
    different answer than the one the seat produced.
    """
    record = _run(tmp_path, lambda _prompt: UNMODIFIED)
    assert record["outcome"] == calibration.CAPTURED
    assert b64decode(record["response_base64"]) == UNMODIFIED
    assert record["response_sha256"] == hashlib.sha256(UNMODIFIED).hexdigest()


def test_a_second_invocation_after_a_capture_is_refused(tmp_path):
    """Mutation: skip open_attempt's gate and ask the seat again.

    The first bytes bind, whatever they say. A second go is a selected later run.
    """
    _run(tmp_path, lambda _prompt: UNMODIFIED)
    with pytest.raises(ValueError, match="already captured a response"):
        _run(tmp_path, lambda _prompt: b'{"improved": true}')

    record = _response(tmp_path)
    assert b64decode(record["response_base64"]) == UNMODIFIED
    assert not calibration.response_path(SPEC, tmp_path, SEAT, 2).exists()


def test_a_missing_seat_callable_refuses_rather_than_simulating(tmp_path):
    """Mutation: `def run_seat(..., call_seat=_fake_perfect_sheet)` — or any default
    that returns bytes when nothing was injected.

    A fabricated calibration is worse than no calibration, because it is
    indistinguishable from a real one afterwards. The parameter default must stay
    None so the callable is resolved at call time, not at import.
    """
    assert (
        inspect.signature(calibration_driver.run_seat).parameters["call_seat"].default
        is None
    )
    with pytest.raises(calibration_driver.CalibrationRefused, match="no seat callable"):
        _run(tmp_path, None)

    assert not calibration.seat_dir(SPEC, tmp_path, SEAT).exists()


def test_two_seats_cannot_share_a_session(tmp_path):
    """Mutation: skip the session check and let seat-b reuse seat-a's session id.

    `_validate_evaluator_calibration` would refuse at lock, after both seats had
    already answered. The driver has to refuse before the second request is minted.
    """
    shared = "session-shared"
    _run(tmp_path, lambda _prompt: UNMODIFIED, seat="seat-a", session_id=shared)
    with pytest.raises(calibration_driver.CalibrationRefused, match="distinct session"):
        _run(tmp_path, lambda _prompt: UNMODIFIED, seat="seat-b", session_id=shared)

    assert not calibration.seat_dir(SPEC, tmp_path, "seat-b").exists()
    assert calibration.response_path(SPEC, tmp_path, "seat-a", 1).is_file()


def test_a_falsy_return_is_no_response_not_a_captured_answer(tmp_path):
    """Mutation: `raw = seat(prompt) or b"{}"`.

    A seat that returns None or b'' without raising would then bind fabricated
    bytes as CAPTURED. Falsy is no response, never an answer.
    """
    for label, returned in (("none", None), ("empty-bytes", b"")):
        root = tmp_path / label
        record = _run(root, lambda _prompt, payload=returned: payload)
        assert record["outcome"] == calibration.NO_RESPONSE
        assert record["response_base64"] is None
        assert record["response_sha256"] is None
        disk = _response(root)
        assert disk["outcome"] == calibration.NO_RESPONSE
        assert disk["response_base64"] is None


def test_a_str_return_persists_no_response_instead_of_wedging(tmp_path):
    """Mutation: pass the seat's return straight into record_response.

    sha256(str) raises inside the finally, so the request is written and the
    response is not. attempts() then raises 'no response record' and there is
    no recovery. A str is no_response with the type error, not a vanished attempt.
    """
    record = _run(tmp_path, lambda _prompt: "a string not bytes")
    assert record["outcome"] == calibration.NO_RESPONSE
    assert record["response_base64"] is None
    assert "TypeError" in record["error"]
    assert "str" in record["error"]
    listed = calibration.attempts(SPEC, tmp_path, SEAT)
    assert listed[0]["response"]["outcome"] == calibration.NO_RESPONSE
    second = _run(tmp_path, lambda _prompt: UNMODIFIED)
    assert second["outcome"] == calibration.CAPTURED
    assert second["attempt_ordinal"] == 2


def test_the_seat_is_asked_the_derived_prompt(tmp_path):
    """Mutation: `prompt = b"{}"` (or any constant) instead of derive_prompt.

    open_attempt re-derives the real prompt for the record, so the request would
    claim an ask that never reached the seat.
    """
    seen = {}

    def remember(prompt):
        seen["prompt"] = prompt
        return UNMODIFIED

    _run(tmp_path, remember)
    expected = calibration.derive_prompt(SPEC, _set(), SEAT)
    assert seen["prompt"] == expected


def test_recorded_request_carries_the_passed_provenance(tmp_path):
    """Mutation: hardcode model_build in the open_attempt call.

    No previous test read request-record fields through the driver, so a
    hardcoded build would still look captured.
    """
    calibration_driver.run_seat(
        SPEC,
        tmp_path,
        evaluator_id=SEAT,
        model_build="build-unique-xyz",
        session_id="session-seat-a",
        calibration_set=_set(),
        call_seat=lambda _prompt: UNMODIFIED,
    )
    request = json.loads(
        calibration.request_path(SPEC, tmp_path, SEAT, 1).read_text(encoding="utf-8")
    )
    assert request["model_build"] == "build-unique-xyz"
    assert request["session_id"] == "session-seat-a"
    assert request["evaluator_id"] == SEAT


def test_two_seats_with_distinct_sessions_both_succeed(tmp_path):
    """Mutation: refuse any second seat, or refuse whenever another request exists.

    The shared-session check's ALLOW branch was untested. Two seats with
    distinct sessions must both be asked.
    """
    first = _run(
        tmp_path, lambda _prompt: UNMODIFIED, seat="seat-a", session_id="session-a"
    )
    second = _run(
        tmp_path, lambda _prompt: UNMODIFIED, seat="seat-b", session_id="session-b"
    )
    assert first["outcome"] == calibration.CAPTURED
    assert second["outcome"] == calibration.CAPTURED
    assert calibration.response_path(SPEC, tmp_path, "seat-a", 1).is_file()
    assert calibration.response_path(SPEC, tmp_path, "seat-b", 1).is_file()
    request_a = json.loads(
        calibration.request_path(SPEC, tmp_path, "seat-a", 1).read_text(
            encoding="utf-8"
        )
    )
    request_b = json.loads(
        calibration.request_path(SPEC, tmp_path, "seat-b", 1).read_text(
            encoding="utf-8"
        )
    )
    assert request_a["session_id"] == "session-a"
    assert request_b["session_id"] == "session-b"


def _cli_args(out: Path, *extra: str) -> list[str]:
    return [
        str(SPECS_DIR / "v3-03-warden-security.json"),
        str(out),
        "--evaluator-id",
        SEAT,
        "--model-build",
        "build-x",
        "--session-id",
        "session-cli",
        "--calibration-set",
        str(CALIBRATION_PATH),
        *extra,
    ]


def test_main_drives_a_resolved_module_callable(tmp_path, monkeypatch, capsys):
    """Mutation: `call_seat=None` in main, or ignore --seat.

    A resolvable module:callable must be imported and asked. Otherwise every
    CLI invocation refuses and the entry point cannot run on the morning it
    exists for.
    """
    clients = tmp_path / "clients"
    out = tmp_path / "out"
    clients.mkdir()
    out.mkdir()
    (clients / "calib_seat_client.py").write_text(
        'def ask(_prompt):\n    return b\'{"z": 1, "a": 2}\\n\\n\'\n',
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(clients))
    code = calibration_driver.main(_cli_args(out, "--seat", "calib_seat_client:ask"))
    captured = capsys.readouterr()
    assert code == 0
    assert "captured" in captured.out
    record = _response(out)
    assert record["outcome"] == calibration.CAPTURED
    assert b64decode(record["response_base64"]) == b'{"z": 1, "a": 2}\n\n'


def test_main_refuses_when_the_seat_is_missing_or_unresolvable(tmp_path, capsys):
    """Mutation: invent a seat when --seat is absent, or treat a bad
    module:callable as a cue to simulate.

    Refusal when unconfigured is correct. There must be no third path that
    fabricates bytes.
    """
    missing = calibration_driver.main(_cli_args(tmp_path / "missing"))
    missing_out = capsys.readouterr().out
    assert missing == 2
    assert "no seat callable" in missing_out
    assert not calibration.seat_dir(SPEC, tmp_path / "missing", SEAT).exists()

    bad = calibration_driver.main(
        _cli_args(tmp_path / "bad", "--seat", "not.a.module:ask")
    )
    bad_out = capsys.readouterr().out
    assert bad == 2
    assert "calibration refused" in bad_out
    assert not calibration.seat_dir(SPEC, tmp_path / "bad", SEAT).exists()
