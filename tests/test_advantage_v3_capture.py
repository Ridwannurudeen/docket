"""The capture that cannot be repeated until it produces a convenient universe.

The Yield registration names a moment, two URLs, an order and exactly three attempts. A
capture that chose any of those while it ran could be retried until the pools looked good,
and the frozen bytes would carry no sign of it. These tests hold the policy where the
registration put it.

The fakes below deliberately take their field names from the validator rather than restating
them: an earlier version of this file passed while the real records used different keys, so
the tests proved nothing about the shape that has to survive the input lock.
"""

import asyncio
import hashlib
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from docket.advantage.v3 import capture
from docket.advantage.v3.spec import load

SPEC_PATH = (
    Path(__file__).resolve().parents[1]
    / "docket/advantage/v3/specs/v3-02-yield-router.json"
)
SPEC = load(SPEC_PATH)
SCHEDULED = datetime(2026, 8, 26, 12, 0, 0, tzinfo=timezone.utc)

# The exact keys spec.py demands of every capture-log entry. Restating them here is the point:
# if either side moves, the shape test below fails instead of the Aug 26 input lock.
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
    assert schedule["first_attempt_at"] == "2026-08-26T12:00:00Z"
    assert "explorer.pancakeswap.com" in schedule["pools_url"]
    assert "tokens.pancakeswap.finance" in schedule["token_list_url"]


def test_the_scraped_urls_are_the_registered_constants():
    """The registration writes its URLs in prose and spec.py holds them as constants. If the
    two ever disagree the capture would fetch something nobody registered."""
    from docket.advantage.v3.spec import YIELD_SOURCE_URLS

    schedule = capture.registered_schedule(SPEC)
    assert schedule["pools_url"] == YIELD_SOURCE_URLS["pools"]
    assert schedule["token_list_url"] == YIELD_SOURCE_URLS["token_list"]


def test_an_early_start_arms_then_waits_for_the_registered_moment(tmp_path):
    elapsed = {"seconds": -600.0}
    slept: list[float] = []

    def clock():
        return SCHEDULED + timedelta(seconds=elapsed["seconds"])

    def sleep(seconds):
        slept.append(seconds)
        elapsed["seconds"] += seconds

    result = capture.run_registered_capture(
        SPEC,
        journal=tmp_path,
        now=clock(),
        clock=clock,
        sleep=sleep,
        attempt=_attempt(1),
    )

    armed = json.loads((tmp_path / "armed.json").read_text(encoding="utf-8"))
    assert slept == [600.0]
    assert armed["attempt_schedule"] == [
        "2026-08-26T12:00:00Z",
        "2026-08-26T12:01:00Z",
        "2026-08-26T12:02:00Z",
    ]
    assert armed["process_started_at"] == "2026-08-26T11:50:00Z"
    assert armed["registered_moment"] == "2026-08-26T12:00:00Z"
    assert armed["spec_hash"] == SPEC.spec_hash
    assert armed["host_identity"]
    assert armed["preflight"]["clock_checked_at"] == "2026-08-26T11:50:00Z"
    assert armed["preflight"]["clock_timezone_aware"] is True
    assert armed["preflight"]["directory_writable"] is True
    assert armed["preflight"]["disk_free_bytes"] > 0
    assert result["captured"] is True


def test_arming_refuses_a_directory_without_free_disk_space(monkeypatch, tmp_path):
    monkeypatch.setattr(
        capture.shutil, "disk_usage", lambda path: SimpleNamespace(free=0)
    )

    with pytest.raises(capture.CaptureRefused, match="no free disk space"):
        capture.write_armed(
            SPEC,
            {"first_attempt_at": "2026-08-26T12:00:00Z"},
            tmp_path,
            started=SCHEDULED - timedelta(minutes=10),
        )
    assert not (tmp_path / "armed.json").exists()


def test_arming_refuses_a_directory_without_write_access(monkeypatch, tmp_path):
    monkeypatch.setattr(capture.os, "access", lambda path, mode: False)

    with pytest.raises(capture.CaptureRefused, match="is not writable"):
        capture.write_armed(
            SPEC,
            {"first_attempt_at": "2026-08-26T12:00:00Z"},
            tmp_path,
            started=SCHEDULED - timedelta(minutes=10),
        )
    assert not (tmp_path / "armed.json").exists()


def test_arming_refuses_a_blank_host_identity(monkeypatch, tmp_path):
    monkeypatch.setattr(capture.platform, "node", lambda: "  ")

    with pytest.raises(capture.CaptureRefused, match="host identity is blank"):
        capture.write_armed(
            SPEC,
            {"first_attempt_at": "2026-08-26T12:00:00Z"},
            tmp_path,
            started=SCHEDULED - timedelta(minutes=10),
        )
    assert not (tmp_path / "armed.json").exists()


def test_arming_refuses_a_timezone_naive_clock_before_writing(tmp_path):
    stub = SimpleNamespace(
        case_selection={
            "chosen_by": (
                "Capture at 2026-08-26T12:00:00Z from https://a.example/p then "
                "https://b.example/t."
            ),
            "population": "two sources",
        },
        spec_hash="0x" + "a" * 64,
    )

    with pytest.raises(capture.CaptureRefused, match="timezone-aware"):
        capture.run_registered_capture(
            stub,
            journal=tmp_path,
            now=SCHEDULED - timedelta(minutes=10),
            clock=lambda: datetime(2026, 8, 26, 11, 50),
            attempt=_attempt(1),
        )
    assert not (tmp_path / "armed.json").exists()


def test_capturing_late_is_refused_rather_than_quietly_accepted():
    """A capture an hour late is not the registered attempt. The registration says the
    protocol must be recommitted for a new time, not that a later universe may stand in."""
    with pytest.raises(capture.CaptureRefused, match="not the registered attempt"):
        capture.run_registered_capture(
            SPEC, now=SCHEDULED + timedelta(hours=1), attempt=_attempt(1)
        )


def test_a_late_preflight_clock_refuses_even_when_process_start_was_in_time():
    def forbidden_attempt(*args, **kwargs):
        raise AssertionError("a late preflight must perform zero HTTP")

    with pytest.raises(capture.CaptureRefused, match="preflight clock"):
        capture.run_registered_capture(
            SPEC,
            now=SCHEDULED,
            clock=lambda: SCHEDULED + timedelta(seconds=6),
            attempt=forbidden_attempt,
        )


def test_an_armed_process_that_wakes_late_refuses_before_the_attempt(tmp_path):
    elapsed = {"seconds": -600.0}

    def clock():
        return SCHEDULED + timedelta(seconds=elapsed["seconds"])

    def oversleep(seconds):
        elapsed["seconds"] += seconds + 6.0

    def forbidden_attempt(*args, **kwargs):
        raise AssertionError("a late wake must perform zero HTTP")

    with pytest.raises(capture.CaptureRefused, match="armed process woke"):
        capture.run_registered_capture(
            SPEC,
            journal=tmp_path,
            now=clock(),
            clock=clock,
            sleep=oversleep,
            attempt=forbidden_attempt,
        )
    assert (tmp_path / "armed.json").exists()
    assert not list(tmp_path.glob("attempt-*.json"))


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
    """The deadline allows an attempt to last 50s. Sleeping a relative 60s after that would start
    attempt three past the end of its own minute, and a 200/200 observed outside its window is
    refused at lock with the bytes already frozen and the moment gone."""
    elapsed = {"s": 0.0}

    def clock():
        return SCHEDULED + timedelta(seconds=elapsed["s"])

    def sleep(seconds):
        elapsed["s"] += seconds

    def slow_attempt(urls, *, ordinal, scheduled_at):
        elapsed["s"] += 50.0  # the complete attempt deadline
        return _attempt(3)(urls, ordinal=ordinal, scheduled_at=scheduled_at)

    result = capture.run_registered_capture(
        SPEC, now=SCHEDULED, clock=clock, sleep=sleep, attempt=slow_attempt
    )
    assert [a["attempt_ordinal"] for a in result["attempts"]] == [1, 2, 3]
    # Attempt three still begins at its registered 12:02:00, despite 100s of slow fetching.
    assert result["attempts"][2]["scheduled_at"] == "2026-08-26T12:02:00Z"
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
    assert "1 of 3 registered attempts was made" in result["why"]
    assert "attempt 2 could no longer start" in result["why"]


def test_a_window_guard_reports_when_two_attempts_were_made():
    elapsed = {"s": 0.0}

    def clock():
        return SCHEDULED + timedelta(seconds=elapsed["s"])

    def slow_second_attempt(urls, *, ordinal, scheduled_at):
        if ordinal == 2:
            elapsed["s"] += 70.0
        return _attempt(99)(urls, ordinal=ordinal, scheduled_at=scheduled_at)

    result = capture.run_registered_capture(
        SPEC,
        now=SCHEDULED,
        clock=clock,
        sleep=lambda seconds: elapsed.__setitem__("s", elapsed["s"] + seconds),
        attempt=slow_second_attempt,
    )

    assert result["captured"] is False
    assert len(result["attempts"]) == 2
    assert "2 of 3 registered attempts were made" in result["why"]
    assert "attempt 3 could no longer start" in result["why"]


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
    """Point capture's httpx.AsyncClient at an in-process transport."""

    class AsyncClient(httpx.AsyncClient):
        def __init__(self, **kwargs):
            super().__init__(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(capture.httpx, "AsyncClient", AsyncClient)


def test_the_real_attempt_record_carries_the_fields_the_validator_requires(monkeypatch):
    """This is the test the old fakes could not be: it runs the actual `capture_attempt` and
    checks its keys against the set spec.py demands. Field-name drift fails here rather than
    at an input lock that cannot be retried."""
    _stub_client(monkeypatch, lambda request: httpx.Response(200, content=b"{}"))
    record = capture.capture_attempt(
        ("https://a.example/p", "https://b.example/t"),
        ordinal=1,
        scheduled_at="2026-08-26T12:00:00Z",
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
        scheduled_at="2026-08-26T12:00:00Z",
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
        scheduled_at="2026-08-26T12:00:00Z",
    )
    assert seen == ["https://a.example/p", "https://b.example/t"]


def test_a_dripping_response_is_abandoned_at_the_attempt_deadline(monkeypatch):
    class DripStream(httpx.AsyncByteStream):
        def __init__(self):
            self.chunks_yielded = 0
            self.closed = threading.Event()

        async def __aiter__(self):
            for _ in range(20):
                await asyncio.sleep(0.01)
                self.chunks_yielded += 1
                yield b"x"

        async def aclose(self):
            await asyncio.sleep(0.4)
            self.closed.set()

    seen = []
    stream = DripStream()

    def handler(request):
        seen.append(request)
        return httpx.Response(200, stream=stream)

    _stub_client(monkeypatch, handler)
    monkeypatch.setattr(capture, "ATTEMPT_DEADLINE_S", 0.05, raising=False)

    started = time.monotonic()
    record = capture.capture_attempt(
        ("https://a.example/p", "https://b.example/t"),
        ordinal=1,
        scheduled_at="2026-08-26T12:00:00Z",
    )
    elapsed = time.monotonic() - started

    assert elapsed < 0.3
    assert record["attempt_outcome"] == "deadline_exceeded"
    assert record["succeeded"] is False
    assert record["pools_status"] == capture.NO_RESPONSE
    assert record["token_list_status"] == capture.NO_RESPONSE
    assert len(seen) == 1
    chunks_at_return = stream.chunks_yielded
    assert stream.closed.is_set() is False
    assert stream.chunks_yielded < 20
    assert seen[0].extensions["timeout"] == {
        "connect": 5.0,
        "read": 10.0,
        "write": 5.0,
        "pool": 5.0,
    }
    assert stream.closed.wait(1.0) is True
    assert stream.chunks_yielded == chunks_at_return


def test_a_deadline_race_cannot_preserve_success_bytes(monkeypatch):
    cancelled = threading.Event()

    async def completed_observations(urls, observations, *, ordinal, scheduled_at):
        observations[:] = [
            {
                "url": urls[0],
                "status": 200,
                "transport_error": None,
                "body": b"pools",
                "observed_at": scheduled_at,
            },
            {
                "url": urls[1],
                "status": 200,
                "transport_error": None,
                "body": b"tokens",
                "observed_at": scheduled_at,
            },
        ]
        try:
            await asyncio.sleep(1.0)
        finally:
            cancelled.set()

    monkeypatch.setattr(capture, "_capture_attempt_async", completed_observations)
    monkeypatch.setattr(capture, "ATTEMPT_DEADLINE_S", 0.05)

    record = capture.capture_attempt(
        ("https://a.example/p", "https://b.example/t"),
        ordinal=1,
        scheduled_at="2026-08-26T12:00:00Z",
    )

    assert record["attempt_outcome"] == "deadline_exceeded"
    assert record["succeeded"] is False
    assert record["token_list_status"] == capture.NO_RESPONSE
    assert record["_bodies"] is None
    assert cancelled.wait(1.0) is True


def test_a_future_finishing_at_the_deadline_is_still_a_deadline_record(monkeypatch):
    class BoundaryFuture:
        def result(self, timeout):
            raise capture.FutureTimeoutError()

        def done(self):
            return True

        def exception(self):
            return None

        def cancel(self):
            raise AssertionError("a completed future cannot be cancelled")

    def boundary_submission(coroutine, loop):
        coroutine.close()
        return BoundaryFuture()

    monkeypatch.setattr(
        capture.asyncio, "run_coroutine_threadsafe", boundary_submission
    )

    record = capture.capture_attempt(
        ("https://a.example/p", "https://b.example/t"),
        ordinal=1,
        scheduled_at="2026-08-26T12:00:00Z",
    )

    assert record["attempt_outcome"] == "deadline_exceeded"
    assert record["succeeded"] is False
    assert record["_bodies"] is None


def test_a_future_failing_at_the_deadline_propagates_its_own_error(monkeypatch):
    worker_error = RuntimeError("worker failed at the deadline")

    class BoundaryFuture:
        def result(self, timeout):
            raise capture.FutureTimeoutError()

        def done(self):
            return True

        def exception(self):
            return worker_error

        def cancel(self):
            raise AssertionError("a completed future cannot be cancelled")

    def boundary_submission(coroutine, loop):
        coroutine.close()
        return BoundaryFuture()

    monkeypatch.setattr(
        capture.asyncio, "run_coroutine_threadsafe", boundary_submission
    )

    with pytest.raises(RuntimeError, match="worker failed at the deadline"):
        capture.capture_attempt(
            ("https://a.example/p", "https://b.example/t"),
            ordinal=1,
            scheduled_at="2026-08-26T12:00:00Z",
        )


# --- the production entry point --------------------------------------------------------


def test_running_the_capture_after_its_window_exits_refused_without_http(
    tmp_path, capsys
):
    """A persistent timer may catch up late; it must record the refusal without fetching."""

    def forbidden_attempt(*args, **kwargs):
        raise AssertionError("a late activation must perform zero HTTP")

    code = capture.main(
        [str(SPEC_PATH), str(tmp_path)],
        now=SCHEDULED + timedelta(minutes=3),
        attempt=forbidden_attempt,
    )
    assert code == 2
    assert "not the registered attempt" in capsys.readouterr().out
    refusal = json.loads(
        (tmp_path / "capture-refused.json").read_text(encoding="utf-8")
    )
    assert refusal["outcome"] == "refused"
    assert "not the registered attempt" in refusal["reason"]
    assert not (tmp_path / "armed.json").exists()


def test_the_entry_point_writes_the_evidence_on_success(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(
        capture, "run_registered_capture", lambda spec, **kwargs: _captured_result()
    )
    code = capture.main([str(SPEC_PATH), str(tmp_path)])
    assert code == 0
    assert (tmp_path / "pools.raw.json").read_bytes() == b'{"pools":[]}'
    assert "captured at attempt 1" in capsys.readouterr().out


def test_the_entry_point_reports_a_failed_capture_distinctly(tmp_path, capsys):
    """Exit 3, not 0: three failed attempts is a real outcome the operator must see, and a
    timer that logged success would hide the one thing worth waking up for."""
    elapsed = {"seconds": 0.0}

    def clock():
        return SCHEDULED + timedelta(seconds=elapsed["seconds"])

    code = capture.main(
        [str(SPEC_PATH), str(tmp_path)],
        now=clock(),
        clock=clock,
        sleep=lambda seconds: elapsed.__setitem__(
            "seconds", elapsed["seconds"] + seconds
        ),
        attempt=_attempt(99),
    )
    assert code == 3
    assert "None of the three registered attempts" in capsys.readouterr().out
    assert json.loads((tmp_path / "capture-attempts.json").read_text())["why"]
    failure = json.loads((tmp_path / "capture-failed.json").read_text())
    assert set(failure) == {"outcome", "recorded_at", "reason"}
    assert failure["outcome"] == "failed"
    assert failure["recorded_at"] == "2026-08-26T12:02:00Z"
    assert "three registered attempts" in failure["reason"]
    assert sorted(path.name for path in tmp_path.glob("attempt-*.json")) == [
        "attempt-01.json",
        "attempt-02.json",
        "attempt-03.json",
    ]


def test_the_entry_point_persists_an_unexpected_runtime_failure(
    monkeypatch, tmp_path, capsys
):
    def fail_after_load(spec, **kwargs):
        raise OSError("journal device unavailable")

    monkeypatch.setattr(capture, "run_registered_capture", fail_after_load)

    code = capture.main([str(SPEC_PATH), str(tmp_path)])

    assert code == 1
    assert "capture failed: OSError" in capsys.readouterr().out
    failure = json.loads((tmp_path / "capture-failed.json").read_text())
    assert failure["outcome"] == "failed"
    assert failure["reason"] == "OSError: journal device unavailable"


def test_a_terminal_write_failure_falls_back_to_stderr_and_exit_four(
    monkeypatch, tmp_path, capsys
):
    def refuse_reference(reference):
        raise capture.CaptureRefused("unknown registered family")

    def unwritable(path, payload):
        raise PermissionError("read-only capture directory")

    monkeypatch.setattr(capture, "_resolve_spec", refuse_reference)
    monkeypatch.setattr(capture, "_create_exclusively", unwritable)

    code = capture.main(["missing-family", str(tmp_path)])

    streams = capsys.readouterr()
    assert code == 4
    assert "capture refused: unknown registered family" in streams.out
    assert "terminal evidence write failed" in streams.err
    assert "unknown registered family" in streams.err


def _captured_result() -> dict:
    pools, tokens = b'{"pools":[]}', b'{"tokens":[]}'
    return {
        "captured": True,
        "attempts": [
            _attempt(1)(("a", "b"), ordinal=1, scheduled_at="2026-08-26T12:00:00Z")
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
    """Starting at +59s is inside the window and useless: the deadline could stamp the
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


def test_a_second_run_cannot_overwrite_a_capture_that_already_happened(tmp_path):
    """The registered moment admits three attempts across three minutes, so a second run of
    the unit can begin while the window is still open — a manual start, a systemd retry,
    someone checking whether it worked.

    Truncating writes meant that run would replace the bytes the first one froze, silently
    and unrecoverably: by the time anyone read the file the window would have closed and
    there would be no way to obtain the original observation again.
    """
    from docket.advantage.v3 import capture

    directory = tmp_path / "yield"
    result = _captured_result()
    result["_raw"] = (b'{"a":1}', b'{"b":2}')
    capture.write_capture(dict(result) | {"_raw": result["_raw"]}, directory)
    assert (directory / "pools.raw.json").read_bytes() == b'{"a":1}'

    with pytest.raises(capture.CaptureRefused, match="already been captured"):
        capture.write_capture(
            dict(result) | {"_raw": (b"different", b"bytes")},
            directory,
        )
    # The first observation survives the second run untouched.
    assert (directory / "pools.raw.json").read_bytes() == b'{"a":1}'


def test_each_attempt_is_persisted_before_the_next_one_is_made(tmp_path):
    """An attempt held only in memory is lost to a crash — after the one minute in which it
    could have been made again."""
    from docket.advantage.v3 import capture

    journal = tmp_path / "journal"
    record = {
        "attempt_ordinal": 1,
        "scheduled_at": "2026-08-26T12:00:00Z",
        "pools_status": 200,
        "token_list_status": 200,
        "succeeded": True,
        "_bodies": (b'{"pools":true}', b'{"tokens":true}'),
    }
    capture.write_attempt(record, journal)

    written = json.loads((journal / "attempt-01.json").read_text(encoding="utf-8"))
    # The log records what happened; the bodies live beside it rather than inside it.
    assert written["attempt_ordinal"] == 1
    assert "_bodies" not in written
    assert (journal / "attempt-01.pools.raw.json").read_bytes() == b'{"pools":true}'

    with pytest.raises(capture.CaptureRefused):
        capture.write_attempt(record, journal)


def test_an_exclusive_write_flushes_before_it_fsyncs(monkeypatch):
    events = []

    class Handle:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            return False

        def write(self, payload):
            events.append(("write", payload))

        def flush(self):
            events.append(("flush", None))

        def fileno(self):
            events.append(("fileno", None))
            return 7

    class Target:
        name = "record.json"

        def open(self, mode):
            events.append(("open", mode))
            return Handle()

    monkeypatch.setattr(
        capture.os, "fsync", lambda file_descriptor: events.append(("fsync", 7))
    )

    capture._create_exclusively(Target(), b"evidence")

    assert events == [
        ("open", "xb"),
        ("write", b"evidence"),
        ("flush", None),
        ("fileno", None),
        ("fsync", 7),
    ]


def test_duplicate_activation_is_refused_before_another_attempt(tmp_path):
    calls: list[int] = []

    def first_attempt(urls, *, ordinal, scheduled_at):
        calls.append(ordinal)
        return _attempt(1)(urls, ordinal=ordinal, scheduled_at=scheduled_at)

    capture.run_registered_capture(
        SPEC,
        journal=tmp_path,
        now=SCHEDULED,
        attempt=first_attempt,
    )

    with pytest.raises(capture.CaptureRefused, match="attempt evidence already exists"):
        capture.run_registered_capture(
            SPEC,
            journal=tmp_path,
            now=SCHEDULED,
            attempt=first_attempt,
        )
    assert calls == [1]


def test_live_cli_activations_are_serialized_until_attempt_evidence_exists(tmp_path):
    entered = threading.Event()
    release = threading.Event()

    def first_attempt(urls, *, ordinal, scheduled_at):
        entered.set()
        assert release.wait(1.0) is True
        return _attempt(1)(urls, ordinal=ordinal, scheduled_at=scheduled_at)

    def forbidden_attempt(*args, **kwargs):
        raise AssertionError("a live duplicate must not perform HTTP")

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(
            capture.main,
            [str(SPEC_PATH), str(tmp_path)],
            now=SCHEDULED,
            attempt=first_attempt,
        )
        assert entered.wait(1.0) is True
        second = pool.submit(
            capture.main,
            [str(SPEC_PATH), str(tmp_path)],
            now=SCHEDULED,
            attempt=forbidden_attempt,
        )
        try:
            time.sleep(0.05)
            assert second.done() is False
        finally:
            release.set()
        assert first.result() == 0
        assert second.result() == 2

    assert not (tmp_path / "armed-02.json").exists()


def test_a_crash_before_any_attempt_rearms_the_same_registered_moment(tmp_path):
    elapsed = {"seconds": -600.0}

    def clock():
        return SCHEDULED + timedelta(seconds=elapsed["seconds"])

    def crash_during_sleep(seconds):
        elapsed["seconds"] += 30.0
        raise OSError("process crashed while waiting")

    with pytest.raises(OSError, match="crashed while waiting"):
        capture.run_registered_capture(
            SPEC,
            journal=tmp_path,
            now=clock(),
            clock=clock,
            sleep=crash_during_sleep,
            attempt=_attempt(1),
        )
    original = (tmp_path / "armed.json").read_bytes()
    assert not list(tmp_path.glob("attempt-*.json"))

    result = capture.run_registered_capture(
        SPEC,
        journal=tmp_path,
        now=clock(),
        clock=clock,
        sleep=lambda seconds: elapsed.__setitem__(
            "seconds", elapsed["seconds"] + seconds
        ),
        attempt=_attempt(1),
    )

    assert result["captured"] is True
    assert (tmp_path / "armed.json").read_bytes() == original
    rearmed = json.loads((tmp_path / "armed-02.json").read_text(encoding="utf-8"))
    assert rearmed["registered_moment"] == "2026-08-26T12:00:00Z"
    assert rearmed["process_started_at"] == "2026-08-26T11:50:30Z"
    assert (tmp_path / "attempt-01.json").exists()


@pytest.mark.parametrize(
    "attempt_name",
    [
        "attempt-01.json",
        "attempt-01.pools.raw.json",
        "attempt-01.token-list.raw.json",
    ],
)
def test_a_restart_after_any_attempt_evidence_refuses_before_http(
    tmp_path, attempt_name
):
    schedule = capture.registered_schedule(SPEC)
    capture.write_armed(
        SPEC,
        schedule,
        tmp_path,
        started=SCHEDULED - timedelta(minutes=10),
    )
    (tmp_path / attempt_name).write_bytes(b"evidence\n")

    def forbidden_attempt(*args, **kwargs):
        raise AssertionError("a restart after attempt evidence must perform zero HTTP")

    with pytest.raises(capture.CaptureRefused, match="attempt evidence already exists"):
        capture.run_registered_capture(
            SPEC,
            journal=tmp_path,
            now=SCHEDULED - timedelta(minutes=9),
            sleep=lambda _seconds: None,
            attempt=forbidden_attempt,
        )
    assert not (tmp_path / "armed-02.json").exists()


def test_a_restart_cannot_rearm_a_different_registered_moment(tmp_path):
    (tmp_path / "armed.json").write_text(
        json.dumps({"registered_moment": "2026-08-25T12:00:00Z"}),
        encoding="utf-8",
    )

    with pytest.raises(capture.CaptureRefused, match="different registered moment"):
        capture.run_registered_capture(
            SPEC,
            journal=tmp_path,
            now=SCHEDULED - timedelta(minutes=9),
            sleep=lambda _seconds: None,
            attempt=_attempt(1),
        )
    assert not (tmp_path / "armed-02.json").exists()


def test_a_restart_cannot_rearm_a_different_registered_spec(tmp_path):
    (tmp_path / "armed.json").write_text(
        json.dumps(
            {
                "registered_moment": "2026-08-26T12:00:00Z",
                "spec_hash": "0x" + "00" * 32,
            }
        ),
        encoding="utf-8",
    )

    def forbidden_attempt(*args, **kwargs):
        raise AssertionError("a changed registration must perform zero HTTP")

    with pytest.raises(capture.CaptureRefused, match="different registered spec"):
        capture.run_registered_capture(
            SPEC,
            journal=tmp_path,
            now=SCHEDULED - timedelta(minutes=9),
            sleep=lambda _seconds: None,
            attempt=forbidden_attempt,
        )
    assert not (tmp_path / "armed-02.json").exists()


def test_a_restart_refuses_a_non_object_armed_record(tmp_path):
    (tmp_path / "armed.json").write_text("[]\n", encoding="utf-8")

    with pytest.raises(capture.CaptureRefused, match="not a JSON object"):
        capture.run_registered_capture(
            SPEC,
            journal=tmp_path,
            now=SCHEDULED - timedelta(minutes=9),
            sleep=lambda _seconds: None,
            attempt=_attempt(1),
        )
    assert not (tmp_path / "armed-02.json").exists()


def test_packaged_cli_arms_and_waits_for_the_recommitted_moment(tmp_path):
    elapsed = {"seconds": -600.0}
    slept: list[float] = []

    def clock():
        return SCHEDULED + timedelta(seconds=elapsed["seconds"])

    def sleep(seconds):
        slept.append(seconds)
        elapsed["seconds"] += seconds

    code = capture.main(
        ["v3-02-yield-router", str(tmp_path)],
        now=clock(),
        clock=clock,
        sleep=sleep,
        attempt=_attempt(1),
    )

    assert code == 0
    assert slept == [600.0]
    armed = json.loads((tmp_path / "armed.json").read_text())
    assert armed["registered_moment"] == "2026-08-26T12:00:00Z"
    assert (tmp_path / "capture-complete.json").exists()


def test_main_arms_then_persists_raw_bytes_before_the_success_manifests(
    monkeypatch, tmp_path
):
    moment = datetime(2030, 1, 2, 12, 0, tzinfo=timezone.utc)
    elapsed = {"seconds": -600.0}

    def clock():
        return moment + timedelta(seconds=elapsed["seconds"])

    def sleep(seconds):
        elapsed["seconds"] += seconds

    stub_spec = SimpleNamespace(
        case_selection={
            "chosen_by": (
                "Capture at 2030-01-02T12:00:00Z from "
                "https://pools.example.test/list then "
                "https://tokens.example.test/list."
            ),
            "population": "The two registered public sources.",
        },
        spec_hash="0x" + "a" * 64,
    )
    spec_path = tmp_path / "future-spec.json"
    spec_path.write_text("{}\n", encoding="utf-8")
    output = tmp_path / "capture"
    monkeypatch.setattr(capture, "load", lambda path: stub_spec)
    monkeypatch.setattr(capture, "_utc_now", clock)
    _stub_client(
        monkeypatch, lambda request: httpx.Response(200, content=b'{"ok":true}')
    )

    created: list[str] = []
    fsynced_after_create: list[int] = []
    create_exclusively = capture._create_exclusively

    def record_create(path, payload):
        created.append(path.name)
        create_exclusively(path, payload)

    monkeypatch.setattr(capture, "_create_exclusively", record_create)
    monkeypatch.setattr(
        capture.os,
        "fsync",
        lambda file_descriptor: fsynced_after_create.append(len(created)),
    )

    code = capture.main(
        [str(spec_path), str(output)],
        now=clock(),
        clock=clock,
        sleep=sleep,
    )

    assert code == 0
    assert created == [
        "armed.json",
        "attempt-01.pools.raw.json",
        "attempt-01.token-list.raw.json",
        "attempt-01.json",
        "pools.raw.json",
        "token-list.raw.json",
        "capture-attempts.json",
        "capture-complete.json",
    ]
    assert fsynced_after_create == list(range(1, len(created) + 1))
    assert json.loads((output / "armed.json").read_text())["process_started_at"] == (
        "2030-01-02T11:50:00Z"
    )
    assert (output / "pools.raw.json").read_bytes() == b'{"ok":true}'
    assert json.loads((output / "capture-complete.json").read_text())["outcome"] == (
        "captured"
    )
