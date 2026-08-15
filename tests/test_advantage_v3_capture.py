"""The capture that cannot be repeated until it produces a convenient universe.

The Yield registration names a moment, two URLs, an order and exactly three attempts. A
capture that chose any of those while it ran could be retried until the pools looked good,
and the frozen bytes would carry no sign of it. These tests hold the policy where the
registration put it.
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from docket.advantage.v3 import capture
from docket.advantage.v3.spec import load

SPEC = load(
    Path(__file__).resolve().parents[1]
    / "docket/advantage/v3/specs/v3-02-yield-router.json"
)
SCHEDULED = datetime(2026, 8, 21, 12, 0, 0, tzinfo=timezone.utc)


def _attempt(succeed_on: int):
    """A fake attempt that succeeds on the given ordinal and fails before it."""

    def run(urls, *, ordinal, scheduled_at):
        ok = ordinal >= succeed_on
        return {
            "ordinal": ordinal,
            "scheduled_at": scheduled_at,
            "observed_at": "2026-08-21T12:00:00+00:00",
            "statuses": [200, 200] if ok else [503, 200],
            "transport_errors": [None, None],
            "succeeded": ok,
            "_bodies": (b'{"pools":[]}', b'{"tokens":[]}') if ok else None,
        }

    return run


def test_the_registered_moment_and_urls_are_read_from_the_spec_not_from_the_code():
    schedule = capture.registered_schedule(SPEC)
    assert schedule["first_attempt_at"] == "2026-08-21T12:00:00Z"
    assert "explorer.pancakeswap.com" in schedule["pools_url"]
    assert "tokens.pancakeswap.finance" in schedule["token_list_url"]


def test_capturing_early_is_refused():
    """An early capture freezes a different observation window than the registered one, and
    nothing in the resulting bytes would show it."""
    with pytest.raises(capture.CaptureRefused, match="Capturing early"):
        capture.run_registered_capture(
            SPEC, now=SCHEDULED - timedelta(seconds=1), attempt=_attempt(1)
        )


def test_capturing_late_is_refused_rather_than_quietly_accepted():
    """A capture an hour late is not the registered attempt. The registration says the
    protocol must be recommitted for a new time, not that a later universe may stand in."""
    with pytest.raises(capture.CaptureRefused, match="not the registered attempt"):
        capture.run_registered_capture(
            SPEC, now=SCHEDULED + timedelta(hours=1), attempt=_attempt(1)
        )


def test_a_first_attempt_success_stops_there():
    result = capture.run_registered_capture(SPEC, now=SCHEDULED, attempt=_attempt(1))
    assert result["captured"] is True
    assert len(result["attempts"]) == 1
    assert result["pools"]["sha256"]


def test_a_failed_attempt_is_recorded_rather_than_forgotten():
    """The registration wants the ordinal, scheduled time and both statuses for every
    attempt. A capture reporting only its success leaves a reader unable to tell one clean
    fetch from three tries."""
    slept: list[int] = []
    result = capture.run_registered_capture(
        SPEC, now=SCHEDULED, sleep=slept.append, attempt=_attempt(3)
    )
    assert result["captured"] is True
    assert [a["ordinal"] for a in result["attempts"]] == [1, 2, 3]
    assert [a["succeeded"] for a in result["attempts"]] == [False, False, True]
    assert result["attempts"][0]["statuses"] == [503, 200]
    assert slept == [60, 60]  # the registered sixty-second spacing


def test_three_failures_end_the_protocol_rather_than_inviting_a_fourth_attempt():
    """The registration anticipated this outcome and named it: input lock fails and the
    protocol must be recommitted. A fourth try is the thing that would let a capture be
    repeated until the universe was convenient."""
    result = capture.run_registered_capture(
        SPEC, now=SCHEDULED, sleep=lambda _s: None, attempt=_attempt(99)
    )
    assert result["captured"] is False
    assert len(result["attempts"]) == 3
    assert "must be recommitted" in result["why"]
    assert "fourth attempt is not available" in result["why"]


def test_the_raw_bytes_are_written_unparsed(tmp_path: Path):
    """The registration hashes the exact response body. A capture that parsed and
    re-serialised would hash a re-encoding and the input lock would reject its own evidence."""
    body = b'{"pools": [ {"id": "0xabc"} ]}'

    def run(urls, *, ordinal, scheduled_at):
        return {
            "ordinal": ordinal,
            "scheduled_at": scheduled_at,
            "observed_at": "2026-08-21T12:00:00+00:00",
            "statuses": [200, 200],
            "transport_errors": [None, None],
            "succeeded": True,
            "_bodies": (body, b"[]"),
        }

    result = capture.run_registered_capture(SPEC, now=SCHEDULED, attempt=run)
    capture.write_capture(result, tmp_path)
    assert (tmp_path / "pools.raw.json").read_bytes() == body  # byte for byte
    import hashlib

    assert result["pools"]["sha256"] == hashlib.sha256(body).hexdigest()


def test_the_attempt_log_never_carries_the_bodies(tmp_path: Path):
    """The log is the audit trail and the bodies are the evidence. Megabytes of pool data
    inside a record of what time we asked would make neither readable."""
    result = capture.run_registered_capture(SPEC, now=SCHEDULED, attempt=_attempt(1))
    capture.write_capture(result, tmp_path)
    log = (tmp_path / "capture-attempts.json").read_text(encoding="utf-8")
    assert "_bodies" not in log and "_raw" not in log
