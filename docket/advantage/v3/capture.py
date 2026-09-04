"""The scheduled capture that turns two live URLs into frozen evidence.

The Yield family's registration names a moment — 2026-08-26T12:00:00Z — two URLs, an order,
and exactly three attempts sixty seconds apart. That precision is not fussiness. A capture
whose time or retry policy is chosen while it runs can be repeated until it produces a
convenient universe, and nothing in the resulting bytes would show that it had been.

So this module does one thing: it performs the registered attempts and records what happened,
including the failures. It does not decide when to run, how many times to try, or which
attempt to keep — the registration decided all of that before any of it existed.

Two properties matter more than the fetching.

**Raw bytes, never parsed and re-serialised.** The registration hashes the exact response body
with bare SHA-256. A capture that parsed the JSON and re-encoded it would produce a different
digest for the same response, and the input lock would reject its own evidence — or worse,
accept a re-encoding as though it were the thing the server sent.

**Every attempt is recorded, not just the one that worked.** The registration requires the
ordinal, the scheduled time and both HTTP statuses for each attempt. A capture that reported
only its success would leave a reader unable to tell one clean fetch from three tries, and the
difference is exactly the thing retry policies are written to bound.

This module does not choose a schedule. It pre-arms when something starts it, then waits inside
that process for the registered attempts. The caller can be cron, a systemd timer or a person,
and none of them can move the registered moment.
"""

import argparse
import asyncio
import hashlib
import json
import os
import platform
import re
import shutil
import sys
import threading
import time
from concurrent.futures import TimeoutError as FutureTimeoutError
from datetime import UTC, datetime, timedelta
from importlib import resources
from pathlib import Path

import httpx

from .runner import _ledger_lock
from .spec import is_yield_family, load, yield_capture_attempts

# The registered attempt policy. Read from the spec at run time rather than duplicated as
# behaviour — these constants exist to name what the code is checking against, and a spec
# that disagrees with them is the spec that wins.
ATTEMPT_OFFSETS_S = (0, 60, 120)
# Phase timeouts stop one socket operation from hanging. They are not a total request cap:
# httpx restarts the read timeout for each chunk, so the monotonic deadline below is what
# bounds a slow-drip response and the complete two-request attempt.
REQUEST_TIMEOUT = httpx.Timeout(connect=5.0, read=10.0, write=5.0, pool=5.0)
ATTEMPT_DEADLINE_S = 50.0
# The input validator requires each observation to fall inside its own attempt's ONE minute:
# `attempt_start <= observed_at < attempt_start + 1 minute`. A tolerance wider than that lets
# a capture succeed here and be refused at lock, which is the worst place to find out — the
# bytes would already be frozen and the moment gone.
LATE_TOLERANCE_S = 5
# A transport failure has no HTTP status, but the validator requires a plain int and would
# refuse `null` at lock — after the bytes were frozen and the moment had passed. Zero is
# never a real status code, so it records "no response" without being mistaken for one.
NO_RESPONSE = 0
TERMINAL_WRITE_FAILURE_EXIT = 4

# The hard attempt deadline must still finish inside its own minute after the allowed late
# start. Per-phase HTTP timeouts do not enter this proof because only the monotonic deadline
# is a total bound.
assert LATE_TOLERANCE_S + ATTEMPT_DEADLINE_S < 60, (
    "the attempt budget must fit inside one registered minute"
)


class CaptureRefused(RuntimeError):
    """The capture cannot be performed as registered, so it is not performed at all."""


_ATTEMPT_LOOP = None
_ATTEMPT_LOOP_LOCK = threading.Lock()


def _attempt_loop() -> asyncio.AbstractEventLoop:
    global _ATTEMPT_LOOP
    with _ATTEMPT_LOOP_LOCK:
        if _ATTEMPT_LOOP is None:
            loop = asyncio.new_event_loop()

            def run_loop():
                asyncio.set_event_loop(loop)
                loop.run_forever()

            threading.Thread(
                target=run_loop,
                name="docket-v3-capture-http",
                daemon=True,
            ).start()
            _ATTEMPT_LOOP = loop
    return _ATTEMPT_LOOP


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _stamp_at(moment: datetime) -> str:
    """A UTC instant in the exact spelling the validator compares against."""
    return moment.isoformat().replace("+00:00", "Z")


def _stamp() -> str:
    return _stamp_at(_utc_now())


def _observations_outside(record: dict, attempt_start: datetime) -> list[str]:
    """Which of the two observations fell outside the attempt's own registered minute.

    The lock checks `attempt_start <= observed_at < attempt_start + 1 minute` per URL, so this
    asks the same question the validator will, before the bytes are frozen rather than after.
    """
    window_end = attempt_start + timedelta(minutes=1)
    outside = []
    for name in ("pools", "token_list"):
        observed = datetime.fromisoformat(
            record[f"{name}_observed_at"].replace("Z", "+00:00")
        )
        if not attempt_start <= observed < window_end:
            outside.append(name)
    return outside


async def _fetch(client: httpx.AsyncClient, url: str) -> dict:
    """One request, returning the raw bytes and the status, never raising for status.

    A non-200 is data here, not an error: the registration wants the status of every attempt
    recorded, and an exception would throw away the very thing it asked for.
    """
    try:
        response = await client.get(url)
    except httpx.HTTPError as exc:
        return {
            "url": url,
            "status": NO_RESPONSE,
            "transport_error": str(exc),
            "body": None,
            # Stamped even on failure: the snapshot needs the moment each URL was observed,
            # and a failed attempt still has to show it fell inside its registered minute.
            "observed_at": _stamp(),
        }
    return {
        "url": url,
        "status": response.status_code,
        "transport_error": None,
        "body": response.content,
        "observed_at": _stamp(),
    }


async def _capture_attempt_async(
    urls: tuple[str, str],
    observations: list,
    *,
    ordinal: int,
    scheduled_at: str,
) -> dict:
    async with httpx.AsyncClient(
        follow_redirects=False, timeout=REQUEST_TIMEOUT
    ) as client:
        observations[0] = await _fetch(client, urls[0])
        observations[1] = await _fetch(client, urls[1])
    return _attempt_record(urls, observations, ordinal, scheduled_at)


def _attempt_record(
    urls: tuple[str, str],
    observations: list,
    ordinal: int,
    scheduled_at: str,
    *,
    deadline_exceeded: bool = False,
) -> dict:
    first, second = observations
    if deadline_exceeded:
        observed_at = _stamp()
        if first is None:
            first = {
                "url": urls[0],
                "status": NO_RESPONSE,
                "transport_error": (
                    "attempt wall-clock deadline elapsed before the pools observation "
                    "completed"
                ),
                "body": None,
                "observed_at": observed_at,
            }
        second = {
            "url": urls[1],
            "status": NO_RESPONSE,
            "transport_error": (
                "attempt wall-clock deadline elapsed before the attempt completed; the "
                "token-list response is not eligible"
            ),
            "body": None,
            "observed_at": observed_at,
        }

    assert first is not None and second is not None
    both_ok = first["status"] == 200 and second["status"] == 200
    # Field names are the validator's, not this module's. An attempt log that reads well here
    # and fails `_required_fields` at lock would be discovered with the bytes already frozen
    # and the registered moment gone — there is no second capture to fix it with.
    return {
        "attempt_ordinal": ordinal,
        "scheduled_at": scheduled_at,
        # One observation time per URL, not one per attempt. The snapshots are validated
        # separately and must show pools observed no later than token_list — the registered
        # order — which a single shared timestamp could not evidence.
        "pools_observed_at": first["observed_at"],
        "token_list_observed_at": second["observed_at"],
        "pools_status": first["status"],
        "token_list_status": second["status"],
        "transport_errors": [first["transport_error"], second["transport_error"]],
        "succeeded": both_ok,
        "attempt_outcome": (
            "deadline_exceeded"
            if deadline_exceeded
            else ("succeeded" if both_ok else "failed")
        ),
        # Bodies are carried out of this function but never into the record: the record is
        # the audit trail and the bodies are the evidence, and mixing them would put
        # megabytes of pool data inside a log of what time we asked.
        "_bodies": (first["body"], second["body"]) if both_ok else None,
    }


def capture_attempt(urls: tuple[str, str], *, ordinal: int, scheduled_at: str) -> dict:
    """One ordered pair of requests, bounded by one monotonic attempt deadline."""
    deadline = time.monotonic() + ATTEMPT_DEADLINE_S
    observations = [None, None]
    future = asyncio.run_coroutine_threadsafe(
        _capture_attempt_async(
            urls,
            observations,
            ordinal=ordinal,
            scheduled_at=scheduled_at,
        ),
        _attempt_loop(),
    )
    try:
        return future.result(timeout=max(0.0, deadline - time.monotonic()))
    except FutureTimeoutError as expiry:
        if future.done():
            error = future.exception()
            if error is not None:
                # The attempt failed as the deadline passed. Its own exception is the
                # event; the expiry is only how this thread found out about it.
                raise error from expiry
        else:
            future.cancel()
        return _attempt_record(
            urls,
            observations,
            ordinal,
            scheduled_at,
            deadline_exceeded=True,
        )


def run_registered_capture(
    spec,
    *,
    journal: Path | None = None,
    now: datetime | None = None,
    clock=None,
    sleep=time.sleep,
    attempt=capture_attempt,
) -> dict:
    """Perform the capture the spec registered, at the moment it registered.

    `now`, `clock`, `sleep` and `attempt` are injected so the whole policy is testable without
    waiting for a date to arrive or touching a network. That is the only reason they exist;
    nothing here reads them to decide anything.

    Injecting `now` without a `clock` freezes time, which makes the sleeps deterministic —
    each one becomes the attempt's full offset, because no time has passed.
    """
    schedule = registered_schedule(spec)
    started = now or datetime.now(UTC)
    if clock is None:
        clock = (lambda: started) if now is not None else _utc_now
    scheduled = datetime.fromisoformat(
        schedule["first_attempt_at"].replace("Z", "+00:00")
    )
    if started.tzinfo is None or started.utcoffset() is None:
        raise CaptureRefused("the capture clock must report a timezone-aware instant")
    if started > scheduled + timedelta(seconds=LATE_TOLERANCE_S):
        raise CaptureRefused(
            f"the registered capture opened at {schedule['first_attempt_at']} and it is now "
            f"{started.isoformat()}, past the {LATE_TOLERANCE_S}s tolerance. A late capture is "
            "not the registered attempt; the protocol must be recommitted for a new time "
            "rather than quietly answering with a later universe."
        )

    checked_at = clock()
    if checked_at.tzinfo is None or checked_at.utcoffset() is None:
        raise CaptureRefused("the capture clock must report a timezone-aware instant")
    if checked_at > scheduled + timedelta(seconds=LATE_TOLERANCE_S):
        raise CaptureRefused(
            f"the registered capture opened at {schedule['first_attempt_at']} but the "
            f"preflight clock reads {checked_at.isoformat()}, past the "
            f"{LATE_TOLERANCE_S}s tolerance. A late capture is not the registered attempt; "
            "the protocol must be recommitted for a new time rather than quietly answering "
            "with a later universe."
        )

    if journal is not None:
        write_armed(spec, schedule, journal, started=started, checked_at=checked_at)

    delay = (scheduled - clock()).total_seconds()
    if delay > 0:
        sleep(delay)
    ready_at = clock()
    if ready_at > scheduled + timedelta(seconds=LATE_TOLERANCE_S):
        raise CaptureRefused(
            f"the registered capture opened at {schedule['first_attempt_at']} but the armed "
            f"process woke at {ready_at.isoformat()}, past the {LATE_TOLERANCE_S}s tolerance. "
            "A late capture is not the registered attempt; the protocol must be recommitted "
            "for a new time rather than quietly answering with a later universe."
        )

    attempts, bodies = [], None
    stopped_reason = None
    for ordinal, offset in enumerate(ATTEMPT_OFFSETS_S, start=1):
        if offset:
            # Wait until this attempt's own registered time, never a relative sixty seconds
            # stacked after however long the last attempt took. The deadline allows an
            # attempt to last 50s, so relative spacing would push attempt three past the end of its
            # window — and a 200/200 observed outside its minute is refused at lock with the
            # bytes already frozen. A negative delay means we are already late; the window
            # check below is what decides whether that is still usable.
            delay = ((scheduled + timedelta(seconds=offset)) - clock()).total_seconds()
            if delay > 0:
                sleep(delay)
        attempt_start = scheduled + timedelta(seconds=offset)
        checked_at = clock()
        latest_start = attempt_start + timedelta(seconds=LATE_TOLERANCE_S)
        if checked_at > latest_start:
            # Not "has the window closed" but "can this attempt still FINISH inside it".
            # Starting at +59s is inside the window and useless: the total deadline could stamp
            # observations a minute late, the attempt could report 200/200, and the lock would
            # refuse the snapshot it had already frozen. The same budget that bounds the first
            # attempt bounds every attempt, so an attempt that cannot fit is not begun.
            #
            # Skipping ahead is not the alternative. The validator requires capture_log entry
            # i to carry attempt_ordinal i with no gaps, so a skipped attempt makes every
            # later one unlockable. Stopping is the only honest outcome.
            stopped_reason = (
                f"attempt {ordinal} could no longer start inside the "
                f"{LATE_TOLERANCE_S}s late tolerance: the clock read "
                f"{_stamp_at(checked_at)} after the latest allowed start "
                f"{_stamp_at(latest_start)}."
            )
            break
        record = attempt(
            (schedule["pools_url"], schedule["token_list_url"]),
            ordinal=ordinal,
            scheduled_at=_stamp_at(attempt_start),
        )
        bodies_this = record.pop("_bodies", None)
        # Persist before doing anything else with it. An attempt that exists only in this
        # list is lost to a crash, and the registered minute in which it could be made again
        # will already have passed.
        if journal is not None:
            write_attempt(record | {"_bodies": bodies_this}, journal)
        attempts.append(record)
        if record["succeeded"]:
            late = _observations_outside(record, attempt_start)
            if late:
                # A 200/200 that landed outside its minute cannot be used and cannot be
                # recorded as an unchosen attempt either — spec.py refuses to log a both-200
                # attempt as anything but the chosen one. The capture is over; saying so is
                # the only output that does not produce evidence the lock will reject.
                return {
                    "captured": False,
                    "attempts": attempts,
                    "why": (
                        f"attempt {ordinal} returned 200 from both URLs but observed "
                        f"{late} outside its registered minute beginning "
                        f"{_stamp_at(attempt_start)}. The lock requires each observation "
                        "inside its own attempt window, and a both-200 attempt cannot be "
                        "recorded as unchosen, so the protocol must be recommitted."
                    ),
                }
            bodies = bodies_this
            break

    if bodies is None:
        # Registered outcome, not an exception: three failed attempts is a result the
        # protocol anticipated and named, and it says the lock fails rather than that
        # another time may be tried.
        if stopped_reason is not None:
            attempted = len(attempts)
            verb = "was" if attempted == 1 else "were"
            remaining = len(ATTEMPT_OFFSETS_S) - attempted
            return {
                "captured": False,
                "attempts": attempts,
                "why": (
                    f"{attempted} of 3 registered attempts {verb} made. "
                    f"{stopped_reason} The remaining {remaining} registered attempt"
                    f"{'s were' if remaining != 1 else ' was'} not made because skipping "
                    "an ordinal would leave an invalid capture-log gap. None of the attempts "
                    "made returned 200 from both URLs, so input lock fails and the protocol "
                    "must be recommitted before another time is used."
                ),
            }
        return {
            "captured": False,
            "attempts": attempts,
            "why": (
                "None of the three registered attempts returned 200 from both URLs. The "
                "registration says input lock fails and the protocol must be recommitted "
                "before another time is used — a fourth attempt is not available."
            ),
        }

    return {
        "captured": True,
        "attempts": attempts,
        "pools": {
            "url": schedule["pools_url"],
            "sha256": hashlib.sha256(bodies[0]).hexdigest(),
            "bytes": len(bodies[0]),
        },
        "token_list": {
            "url": schedule["token_list_url"],
            "sha256": hashlib.sha256(bodies[1]).hexdigest(),
            "bytes": len(bodies[1]),
        },
        "_raw": bodies,
    }


def registered_schedule(spec) -> dict:
    """The moment and the two URLs, read from the registration rather than from here."""
    frame = spec.case_selection.get("frame_definition")
    if isinstance(frame, dict) and frame.get("version") == "range.enumerable-1024.v1":
        attempts = frame["pool_truth_capture_attempts"]
        first = datetime.fromisoformat(attempts[0].replace("Z", "+00:00"))
        if [
            datetime.fromisoformat(value.replace("Z", "+00:00")) for value in attempts
        ] != [first + timedelta(seconds=offset) for offset in ATTEMPT_OFFSETS_S]:
            raise CaptureRefused(
                "the Range successor does not register three one-minute pool captures"
            )
        return {
            "first_attempt_at": attempts[0],
            "pools_url": frame["pool_truth_sources"]["pools"],
            "token_list_url": frame["pool_truth_sources"]["token_list"],
        }
    chosen_by = str(spec.case_selection.get("chosen_by", ""))
    population = str(spec.case_selection.get("population", ""))
    if isinstance(getattr(spec, "execution_protocol", None), dict) and is_yield_family(
        spec
    ):
        attempts = yield_capture_attempts(spec)
        first = attempts[0]
        if attempts != tuple(
            first + timedelta(seconds=offset) for offset in ATTEMPT_OFFSETS_S
        ):
            raise CaptureRefused(
                "the Yield family does not register three one-minute source captures"
            )
        moment = _stamp_at(first)
    else:
        moment = _first(chosen_by, r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")
    # A trailing full stop belongs to the sentence, not the URL. The registration writes these
    # in prose, and one of them ends a sentence — fetching "…extended.json." would 404 against
    # a URL nobody registered.
    urls = [
        url.rstrip(".")
        for url in _all(population + " " + chosen_by, r"https://[^\s,\"]+")
    ]
    if moment is None or len(urls) < 2:
        raise CaptureRefused(
            "the registration does not name a capture moment and two URLs, so there is no "
            "registered capture to perform"
        )
    return {"first_attempt_at": moment, "pools_url": urls[0], "token_list_url": urls[1]}


def _first(text: str, pattern: str) -> str | None:
    found = re.search(pattern, text)
    return found.group(0) if found else None


def _all(text: str, pattern: str) -> list[str]:
    seen, out = set(), []
    for match in re.findall(pattern, text):
        if match not in seen:
            seen.add(match)
            out.append(match)
    return out


def _create_exclusively(path: Path, payload: bytes) -> None:
    """Create, never replace.

    The registered moment admits three attempts inside three minutes, so a second run of
    this unit can begin while the window is still open — a manual start, a systemd retry, an
    operator checking whether it worked. Truncating writes meant that run would overwrite the
    capture the first one had already made, and the overwrite would be silent and
    unrecoverable: the window would have closed by the time anyone read the file.
    """
    try:
        with path.open("xb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError as exc:
        raise CaptureRefused(
            f"{path.name} already exists. This registered moment has already been captured, "
            "and a second run does not get to replace what the first one observed."
        ) from exc


def _json_bytes(record: dict) -> bytes:
    return (json.dumps(record, indent=2, sort_keys=True) + "\n").encode("utf-8")


def write_armed(
    spec,
    schedule: dict,
    directory: Path,
    *,
    started: datetime,
    checked_at: datetime | None = None,
    host_identity: str | None = None,
) -> Path:
    """Prove the process and its output path were ready before the moment."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    if not os.access(directory, os.W_OK):
        raise CaptureRefused(f"the capture directory {directory} is not writable")
    disk_free_bytes = shutil.disk_usage(directory).free
    if disk_free_bytes <= 0:
        raise CaptureRefused(
            f"the capture directory {directory} has no free disk space"
        )
    identity = (host_identity if host_identity is not None else platform.node()).strip()
    if not identity:
        raise CaptureRefused("the capture host identity is blank")
    payload = _json_bytes(
        {
            "registered_moment": schedule["first_attempt_at"],
            "attempt_schedule": [
                _stamp_at(
                    datetime.fromisoformat(
                        schedule["first_attempt_at"].replace("Z", "+00:00")
                    )
                    + timedelta(seconds=offset)
                )
                for offset in ATTEMPT_OFFSETS_S
            ],
            "process_started_at": _stamp_at(started.astimezone(UTC)),
            "spec_hash": spec.spec_hash,
            "host_identity": identity,
            "preflight": {
                "clock_checked_at": _stamp_at(
                    (checked_at or started).astimezone(UTC)
                ),
                "clock_timezone_aware": True,
                "directory_writable": True,
                "disk_free_bytes": disk_free_bytes,
            },
        }
    )
    original = directory / "armed.json"
    if not original.exists():
        try:
            _create_exclusively(original, payload)
            return original
        except CaptureRefused:
            pass

    try:
        existing = json.loads(original.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CaptureRefused(
            "armed.json exists but is unreadable, so this process cannot establish which "
            "registered moment was armed and must not make an HTTP attempt."
        ) from exc
    if not isinstance(existing, dict):
        raise CaptureRefused(
            "armed.json is not a JSON object, so this process cannot establish which "
            "registered moment was armed and must not make an HTTP attempt."
        )
    if existing.get("registered_moment") != schedule["first_attempt_at"]:
        raise CaptureRefused(
            "armed.json names a different registered moment, so this process must not "
            "replace it or make an HTTP attempt."
        )
    if existing.get("spec_hash") != spec.spec_hash:
        raise CaptureRefused(
            "armed.json names a different registered spec, so this process must not "
            "replace it or make an HTTP attempt."
        )
    attempts = sorted(path.name for path in directory.glob("attempt-*.json"))
    if attempts:
        raise CaptureRefused(
            f"attempt evidence already exists ({', '.join(attempts)}), so the registered "
            "window is in progress or complete and this process must not make another "
            "HTTP attempt."
        )

    ordinal = 2
    while (directory / f"armed-{ordinal:02d}.json").exists():
        ordinal += 1
    path = directory / f"armed-{ordinal:02d}.json"
    try:
        _create_exclusively(path, payload)
    except CaptureRefused as exc:
        raise CaptureRefused(
            "another activation re-armed this registered moment first, so this process "
            "must not make an HTTP attempt."
        ) from exc
    return path


def write_terminal(
    outcome: str, reason: str, directory: Path, *, recorded_at: datetime
) -> Path:
    """Persist a refusal or runtime failure without replacing an earlier event."""
    if outcome not in {"refused", "failed"}:
        raise ValueError(f"unsupported capture terminal outcome {outcome!r}")
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    payload = _json_bytes(
        {
            "outcome": outcome,
            "recorded_at": _stamp_at(recorded_at.astimezone(UTC)),
            "reason": reason,
        }
    )
    ordinal = 1
    while True:
        suffix = "" if ordinal == 1 else f"-{ordinal:02d}"
        path = directory / f"capture-{outcome}{suffix}.json"
        try:
            _create_exclusively(path, payload)
            return path
        except CaptureRefused:
            ordinal += 1


def write_attempt(record: dict, directory: Path) -> Path:
    """Persist one attempt the moment it finishes, before the next one is made.

    Attempts previously accumulated in memory until the whole capture ended, so a crash
    after a successful fetch lost the bytes *and* the history of how they were obtained —
    after the one minute in which either could be obtained again.
    """
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    ordinal = record["attempt_ordinal"]
    body = {key: value for key, value in record.items() if key != "_bodies"}
    path = directory / f"attempt-{ordinal:02d}.json"
    bodies = record.get("_bodies")
    if bodies:
        _create_exclusively(
            directory / f"attempt-{ordinal:02d}.pools.raw.json", bodies[0]
        )
        _create_exclusively(
            directory / f"attempt-{ordinal:02d}.token-list.raw.json", bodies[1]
        )
    _create_exclusively(path, _json_bytes(body))
    return path


def write_capture(
    result: dict, directory: Path, *, recorded_at: datetime | None = None
) -> dict:
    """Write the raw bodies and the attempt log, keeping the two apart."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    if not result.get("captured"):
        _create_exclusively(directory / "capture-attempts.json", _json_bytes(result))
        write_terminal(
            "failed",
            result["why"],
            directory,
            recorded_at=recorded_at or _utc_now(),
        )
        return result

    raw = result.pop("_raw")
    _create_exclusively(directory / "pools.raw.json", raw[0])
    _create_exclusively(directory / "token-list.raw.json", raw[1])
    _create_exclusively(directory / "capture-attempts.json", _json_bytes(result))
    _create_exclusively(
        directory / "capture-complete.json",
        _json_bytes(
            {
                "outcome": "captured",
                "pools_sha256": result["pools"]["sha256"],
                "token_list_sha256": result["token_list"]["sha256"],
            }
        ),
    )
    return result


def _resolve_spec(reference: str) -> Path:
    """Take a family id or a path, and return the specification the runtime actually has.

    A unit file naming an absolute path pins a filesystem layout: the deployed venv lives at
    /opt/docket-venvs/<commit>, while /opt/docket/docket is the *previous* release's source
    tree. A path pointing there would still exist and would still parse, so the capture would
    run happily against a spec that is not the deployed one. Resolving from the installed
    package means the capture uses the registration the running Docket ships with.
    """
    candidate = Path(reference)
    try:
        looks_like_a_file = candidate.is_file()
    except OSError:
        # `is_file()` swallows a missing path but re-raises a permission error, so a family
        # id resolved from a directory the service user cannot stat would crash here rather
        # than falling through to the packaged spec — which is where a family id was always
        # going to be found. The capture has one registered moment and no second attempt, so
        # it does not get to fail on the readability of a working directory it never uses.
        looks_like_a_file = False
    if looks_like_a_file:
        return candidate
    packaged = (
        resources.files("docket.advantage") / "v3" / "specs" / f"{reference}.json"
    )
    if packaged.is_file():
        return Path(str(packaged))
    raise CaptureRefused(
        f"{reference!r} is neither a readable specification file nor a family id shipped "
        "with the installed package"
    )


def main(
    argv: list[str] | None = None,
    *,
    now: datetime | None = None,
    clock=None,
    sleep=time.sleep,
    attempt=capture_attempt,
) -> int:
    """The production entry point, so the capture is something a timer can actually run.

    Without this the module was reachable only from its own tests — which is the shape of code
    that passes every check and then does not exist on the morning it was written for.
    """

    process_started = now or _utc_now()
    runtime_clock = clock or (
        (lambda: process_started) if now is not None else _utc_now
    )
    parser = argparse.ArgumentParser(
        description="Perform a v3 family's registered capture, at its registered moment."
    )
    parser.add_argument(
        "spec", help="a registered family id, or a path to a specification JSON"
    )
    parser.add_argument(
        "out", help="directory to write the raw bodies and attempt log into"
    )
    args = parser.parse_args(argv)
    output = Path(args.out)

    def event_time() -> datetime:
        return runtime_clock()

    def terminal_exit(outcome: str, reason: str, code: int) -> int:
        try:
            write_terminal(outcome, reason, output, recorded_at=event_time())
        except OSError as failure:
            print(
                f"capture {outcome}: {reason}; terminal evidence write failed: "
                f"{type(failure).__name__}: {failure}",
                file=sys.stderr,
            )
            print(f"capture {outcome}: {reason}")
            return TERMINAL_WRITE_FAILURE_EXIT
        print(f"capture {outcome}: {reason}")
        return code

    try:
        spec = load(_resolve_spec(args.spec))
    except CaptureRefused as refusal:
        return terminal_exit("refused", str(refusal), 2)
    except Exception as failure:
        return terminal_exit("failed", f"{type(failure).__name__}: {failure}", 1)

    try:
        with _ledger_lock(output / "capture"):
            result = run_registered_capture(
                spec,
                journal=output,
                now=process_started,
                clock=runtime_clock,
                sleep=sleep,
                attempt=attempt,
            )
    except CaptureRefused as refusal:
        # Exit 2, not 1: this is the protocol declining, which a timer log should be able to
        # tell apart from the capture crashing.
        return terminal_exit("refused", str(refusal), 2)
    except Exception as failure:
        return terminal_exit("failed", f"{type(failure).__name__}: {failure}", 1)

    try:
        write_capture(result, output, recorded_at=event_time())
    except CaptureRefused as refusal:
        return terminal_exit("refused", str(refusal), 2)
    except Exception as failure:
        return terminal_exit("failed", f"{type(failure).__name__}: {failure}", 1)
    if not result["captured"]:
        print(result["why"])
        return 3
    print(
        f"captured at attempt {result['attempts'][-1]['attempt_ordinal']}: "
        f"pools {result['pools']['sha256'][:16]}… ({result['pools']['bytes']} bytes), "
        f"token list {result['token_list']['sha256'][:16]}… "
        f"({result['token_list']['bytes']} bytes)"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised through main()
    raise SystemExit(main())
