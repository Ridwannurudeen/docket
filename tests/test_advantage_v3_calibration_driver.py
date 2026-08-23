"""Concurrency coverage for the v3 calibration driver."""

from contextlib import contextmanager
from pathlib import Path

from docket.advantage.v3 import calibration, calibration_driver
from docket.advantage.v3.spec import load


ROOT = Path(__file__).resolve().parents[1]
SPEC = load(ROOT / "docket/advantage/v3/specs/v3-03-warden-security.json")
CALIBRATION_SET = (
    ROOT / "docket/advantage/v3/sources/warden-calibration-set.json"
).read_bytes()


def test_session_check_and_request_creation_share_one_lock(tmp_path, monkeypatch):
    """Mutation: remove the lock or move either operation outside its transaction."""
    state = {"held": False, "checks": 0, "opens": 0}
    original_refuse = calibration_driver._refuse_shared_session
    original_open = calibration.open_attempt

    @contextmanager
    def observed_lock(path):
        assert path.name == "session-claims"
        assert state["held"] is False
        state["held"] = True
        try:
            yield
        finally:
            state["held"] = False

    def checked_refuse(*args, **kwargs):
        assert state["held"] is True
        state["checks"] += 1
        return original_refuse(*args, **kwargs)

    def checked_open(*args, **kwargs):
        assert state["held"] is True
        state["opens"] += 1
        return original_open(*args, **kwargs)

    monkeypatch.setattr(calibration_driver, "_ledger_lock", observed_lock)
    monkeypatch.setattr(calibration_driver, "_refuse_shared_session", checked_refuse)
    monkeypatch.setattr(calibration, "open_attempt", checked_open)

    captured = calibration_driver.run_seat(
        SPEC,
        tmp_path,
        evaluator_id="seat-a",
        model_build="build-seat-a",
        session_id="shared-session",
        calibration_set=CALIBRATION_SET,
        call_seat=lambda _prompt: b'{"answer": "captured"}',
    )

    assert captured["outcome"] == "captured"
    assert state == {"held": False, "checks": 1, "opens": 1}
    requests = list(tmp_path.rglob("attempt-01.request.json"))
    assert len(requests) == 1
