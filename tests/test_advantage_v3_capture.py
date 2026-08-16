"""The capture that cannot be repeated until it produces a convenient universe.

The Yield registration names a moment, two URLs, an order and exactly three attempts. A
capture that chose any of those while it ran could be retried until the pools looked good,
and the frozen bytes would carry no sign of it. These tests hold the policy where the
registration put it.

The fakes below deliberately take their field names from the validator rather than restating
them: an earlier version of this file passed while the real records used different keys, so
the tests proved nothing about the shape that has to survive the input lock.
"""

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest

from docket.advantage.v3 import capture
from docket.advantage.v3.spec import load

SPEC_PATH = (
    Path(__file__).resolve().parents[1]
    / "docket/advantage/v3/specs/v3-02-yield-router.json"
)
SPEC = load(SPEC_PATH)
SCHEDULED = datetime(2026, 8, 21, 12, 0, 0, tzinfo=timezone.utc)

# The exact keys spec.py demands of every capture-log entry. Restating them here is the point:
# if either side moves, the shape test below fails instead of the Aug 21 input lock.
VALIDATOR_ATTEMPT_FIELDS = {
    "attempt_ordinal",
    "scheduled_at",
    "pools_status",
    "token_list_status",
}


def _attempt(succeed_on: int, *, pools_status: int = 503):
    """A fake attempt that succeeds on the given ordinal and fails before it."""

    def run(urls, *, ordinal, scheduled_at):
        ok = ordinal >= succeed_on
        start = datetime.fromisoformat(scheduled_at.replace("Z", "+00:00"))
        return {
            "attempt_ordinal": ordinal,
            "scheduled_at": scheduled_at,
            "pools_observed_at": capture._stamp_at(start + timedelta(seconds=1)),
            "token_list_observed_at": capture._stamp_at(start + timedelta(seconds=2)),
            "pools_status": 200 if ok else pools_status,
            "token_list_status": 200,
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


def test_the_scraped_urls_are_the_registered_constants():
    """The registration writes its URLs in prose and spec.py holds them as constants. If the
    two ever disagree the capture would fetch something nobody registered."""
    from docket.advantage.v3.spec import YIELD_SOURCE_URLS

    schedule = capture.registered_schedule(SPEC)
    assert schedule["pools_url"] == YIELD_SOURCE_URLS["pools"]
    assert schedule["token_list_url"] == YIELD_SOURCE_URLS["token_list"]


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
    slept: list[float] = []
    result = capture.run_registered_capture(
        SPEC, now=SCHEDULED, sleep=slept.append, attempt=_attempt(3)
    )
    assert result["captured"] is True
    assert [a["attempt_ordinal"] for a in result["attempts"]] == [1, 2, 3]
    assert [a["succeeded"] for a in result["attempts"]] == [False, False, True]
    assert result["attempts"][0]["pools_status"] == 503
    assert result["attempts"][0]["token_list_status"] == 200
    # A frozen clock means no time passed, so each wait is its attempt's full offset from the
    # registered start — the absolute anchor, not sixty seconds stacked after the last fetch.
    assert slept == [60.0, 120.0]


def test_each_attempt_is_anchored_to_its_registered_time_not_to_the_previous_one():
    """Two timeouts make an attempt ~50s long. Sleeping a relative 60s after that would start
    attempt three past the end of its own minute, and a 200/200 observed outside its window is
    refused at lock with the bytes already frozen and the moment gone."""
    elapsed = {"s": 0.0}

    def clock():
        return SCHEDULED + timedelta(seconds=elapsed["s"])

    def sleep(seconds):
        elapsed["s"] += seconds

    def slow_attempt(urls, *, ordinal, scheduled_at):
        elapsed["s"] += 50.0  # two 25s timeouts
        return _attempt(3)(urls, ordinal=ordinal, scheduled_at=scheduled_at)

    result = capture.run_registered_capture(
        SPEC, now=SCHEDULED, clock=clock, sleep=sleep, attempt=slow_attempt
    )
    assert [a["attempt_ordinal"] for a in result["attempts"]] == [1, 2, 3]
    # Attempt three still begins at its registered 12:02:00, despite 100s of slow fetching.
    assert result["attempts"][2]["scheduled_at"] == "2026-08-21T12:02:00Z"
    # Each attempt began exactly on its registered second, so the clock reads the third
    # attempt's start plus its own duration. Relative spacing would have started attempt
    # three at 12:03:40 — after its window had closed.
    assert elapsed["s"] == 170.0  # 120s of schedule + the last attempt's own 50s


def test_an_attempt_whose_window_has_already_closed_is_not_fetched():
    """Stopping is the honest outcome: a fetch after the window closed would observe a later
    universe than the attempt it would be filed under."""
    elapsed = {"s": 0.0}

    def clock():
        return SCHEDULED + timedelta(seconds=elapsed["s"])

    def stalled_attempt(urls, *, ordinal, scheduled_at):
        elapsed["s"] += 200.0  # blows through every remaining window
        return _attempt(99)(urls, ordinal=ordinal, scheduled_at=scheduled_at)

    result = capture.run_registered_capture(
        SPEC,
        now=SCHEDULED,
        clock=clock,
        sleep=lambda s: elapsed.__setitem__("s", elapsed["s"] + s),
        attempt=stalled_attempt,
    )
    assert result["captured"] is False
    assert len(result["attempts"]) == 1  # attempts two and three were never fetched


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
        record = _attempt(1)(urls, ordinal=ordinal, scheduled_at=scheduled_at)
        return record | {"_bodies": (body, b"[]")}

    result = capture.run_registered_capture(SPEC, now=SCHEDULED, attempt=run)
    capture.write_capture(result, tmp_path)
    assert (tmp_path / "pools.raw.json").read_bytes() == body  # byte for byte
    assert result["pools"]["sha256"] == hashlib.sha256(body).hexdigest()


def test_the_attempt_log_never_carries_the_bodies(tmp_path: Path):
    """The log is the audit trail and the bodies are the evidence. Megabytes of pool data
    inside a record of what time we asked would make neither readable."""
    result = capture.run_registered_capture(SPEC, now=SCHEDULED, attempt=_attempt(1))
    capture.write_capture(result, tmp_path)
    log = (tmp_path / "capture-attempts.json").read_text(encoding="utf-8")
    assert "_bodies" not in log and "_raw" not in log


# --- the real fetching path, not a fake of it ------------------------------------------


def _stub_client(monkeypatch, handler):
    """Point capture's httpx.Client at an in-process transport."""

    class Client(httpx.Client):
        def __init__(self, **kwargs):
            super().__init__(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(capture.httpx, "Client", Client)


def test_the_real_attempt_record_carries_the_fields_the_validator_requires(monkeypatch):
    """This is the test the old fakes could not be: it runs the actual `capture_attempt` and
    checks its keys against the set spec.py demands. Field-name drift fails here rather than
    at an input lock that cannot be retried."""
    _stub_client(monkeypatch, lambda request: httpx.Response(200, content=b"{}"))
    record = capture.capture_attempt(
        ("https://a.example/p", "https://b.example/t"),
        ordinal=1,
        scheduled_at="2026-08-21T12:00:00Z",
    )
    assert VALIDATOR_ATTEMPT_FIELDS <= set(record)
    assert record["pools_status"] == 200 and record["token_list_status"] == 200
    assert isinstance(record["pools_status"], int)
    # Per-URL times, in the registered order: pools observed no later than token_list.
    assert record["pools_observed_at"] <= record["token_list_observed_at"]


def test_a_transport_failure_records_an_integer_status_not_null(monkeypatch):
    """The validator requires a plain int and would refuse `null` at lock — after the bytes
    were frozen and the moment had passed. Zero is never a real HTTP status."""

    def handler(request):
        raise httpx.ConnectTimeout("no route", request=request)

    _stub_client(monkeypatch, handler)
    record = capture.capture_attempt(
        ("https://a.example/p", "https://b.example/t"),
        ordinal=1,
        scheduled_at="2026-08-21T12:00:00Z",
    )
    assert record["pools_status"] == capture.NO_RESPONSE == 0
    assert isinstance(record["pools_status"], int)
    assert record["succeeded"] is False
    assert record["transport_errors"][0]  # the reason is kept, not swallowed


def test_the_two_urls_are_fetched_in_the_registered_order(monkeypatch):
    """Pools before token list. The validator refuses snapshots captured the other way."""
    seen: list[str] = []
    _stub_client(
        monkeypatch,
        lambda request: (
            seen.append(str(request.url)) or httpx.Response(200, content=b"{}")
        ),
    )
    capture.capture_attempt(
        ("https://a.example/p", "https://b.example/t"),
        ordinal=1,
        scheduled_at="2026-08-21T12:00:00Z",
    )
    assert seen == ["https://a.example/p", "https://b.example/t"]


# --- the production entry point --------------------------------------------------------


def test_running_the_capture_before_its_moment_exits_refused(tmp_path, capsys):
    """Exit 2 is the protocol declining, which a timer log must be able to tell apart from
    the capture crashing."""
    code = capture.main([str(SPEC_PATH), str(tmp_path)])
    assert code == 2
    assert "Capturing early" in capsys.readouterr().out


def test_the_entry_point_writes_the_evidence_on_success(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(
        capture, "run_registered_capture", lambda spec: _captured_result()
    )
    code = capture.main([str(SPEC_PATH), str(tmp_path)])
    assert code == 0
    assert (tmp_path / "pools.raw.json").read_bytes() == b'{"pools":[]}'
    assert "captured at attempt 1" in capsys.readouterr().out


def test_the_entry_point_reports_a_failed_capture_distinctly(
    monkeypatch, tmp_path, capsys
):
    """Exit 3, not 0: three failed attempts is a real outcome the operator must see, and a
    timer that logged success would hide the one thing worth waking up for."""
    monkeypatch.setattr(
        capture,
        "run_registered_capture",
        lambda spec: {"captured": False, "attempts": [], "why": "three failures"},
    )
    code = capture.main([str(SPEC_PATH), str(tmp_path)])
    assert code == 3
    assert "three failures" in capsys.readouterr().out
    assert json.loads((tmp_path / "capture-attempts.json").read_text())["why"]


def _captured_result() -> dict:
    pools, tokens = b'{"pools":[]}', b'{"tokens":[]}'
    return {
        "captured": True,
        "attempts": [
            _attempt(1)(("a", "b"), ordinal=1, scheduled_at="2026-08-21T12:00:00Z")
            | {"_bodies": None}
        ],
        "pools": {
            "url": "u",
            "sha256": hashlib.sha256(pools).hexdigest(),
            "bytes": len(pools),
        },
        "token_list": {
            "url": "u",
            "sha256": hashlib.sha256(tokens).hexdigest(),
            "bytes": len(tokens),
        },
        "_raw": (pools, tokens),
    }


def test_an_attempt_that_cannot_finish_inside_its_window_is_not_begun():
    """Starting at +59s is inside the window and useless: two timeouts would stamp the
    observations a minute late, the attempt would report 200/200, and the lock would refuse
    the snapshot already frozen. The budget that bounds attempt one bounds every attempt."""
    elapsed = {"s": 0.0}

    def clock():
        return SCHEDULED + timedelta(seconds=elapsed["s"])

    def sleep(seconds):
        # An oversleeping OS: the wait overshoots attempt two's start by most of its minute.
        elapsed["s"] += seconds + 50.0

    result = capture.run_registered_capture(
        SPEC, now=SCHEDULED, clock=clock, sleep=sleep, attempt=_attempt(99)
    )
    assert result["captured"] is False
    assert len(result["attempts"]) == 1  # attempt two was never begun


def test_a_success_observed_outside_its_window_is_reported_not_frozen():
    """The worst outcome is a 200/200 the lock will refuse. It cannot be used, and it cannot
    be recorded as an unchosen attempt either, so the capture has to end and say why."""

    def late_success(urls, *, ordinal, scheduled_at):
        start = datetime.fromisoformat(scheduled_at.replace("Z", "+00:00"))
        record = _attempt(1)(urls, ordinal=ordinal, scheduled_at=scheduled_at)
        # Both fetches returned 200, but the second landed after the minute closed.
        record["token_list_observed_at"] = capture._stamp_at(
            start + timedelta(seconds=75)
        )
        return record

    result = capture.run_registered_capture(
        SPEC, now=SCHEDULED, sleep=lambda _s: None, attempt=late_success
    )
    assert result["captured"] is False
    assert "token_list" in result["why"]
    assert "outside its registered minute" in result["why"]
    assert "must be recommitted" in result["why"]


def test_an_in_window_success_is_still_frozen_normally():
    """The new guard must not reject the ordinary case it exists to protect."""
    result = capture.run_registered_capture(SPEC, now=SCHEDULED, attempt=_attempt(1))
    assert result["captured"] is True


def test_a_family_id_resolves_even_from_an_unreadable_directory(monkeypatch):
    """The capture has one registered moment, so it does not get to fail on a cwd.

    `Path.is_file()` returns False for a missing path but re-raises a permission error, and
    the resolver tried the argument as a path before falling through to the packaged spec.
    A family id is always going to be found in the package; a working directory the service
    user cannot stat is not a reason to abandon the only observation this family gets.
    Reproduced on the VPS by running the unit's own command from a directory the `docket`
    user could not read.
    """
    from docket.advantage.v3 import capture

    real_is_file = Path.is_file

    def _refuse_to_stat(self, *args, **kwargs):
        if str(self) == "v3-02-yield-router":
            raise PermissionError(13, "Permission denied")
        return real_is_file(self, *args, **kwargs)

    monkeypatch.setattr(Path, "is_file", _refuse_to_stat)

    resolved = capture._resolve_spec("v3-02-yield-router")

    assert resolved.name == "v3-02-yield-router.json"
    assert load(resolved).spec_id == "v3-02-yield-router"
