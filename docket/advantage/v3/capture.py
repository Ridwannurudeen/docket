"""The scheduled capture that turns two live URLs into frozen evidence.

The Yield family's registration names a moment — 2026-08-21T12:00:00Z — two URLs, an order,
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

This module makes no attempt to be a scheduler. It runs when something runs it, and it refuses
to freeze anything if it is run at the wrong time — the caller can be cron, a systemd timer or
a person, and none of them can move the registered moment.
"""

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

# The registered attempt policy. Read from the spec at run time rather than duplicated as
# behaviour — these constants exist to name what the code is checking against, and a spec
# that disagrees with them is the spec that wins.
ATTEMPT_OFFSETS_S = (0, 60, 120)
REQUEST_TIMEOUT_S = 45.0
# How far past the scheduled moment a capture may still be attempted. A capture that ran an
# hour late is not the registered attempt, and pretending otherwise would silently move the
# observation window that the whole family is bounded by.
LATE_TOLERANCE_S = 300


class CaptureRefused(RuntimeError):
    """The capture cannot be performed as registered, so it is not performed at all."""


def _fetch(client: httpx.Client, url: str) -> dict:
    """One request, returning the raw bytes and the status, never raising for status.

    A non-200 is data here, not an error: the registration wants the status of every attempt
    recorded, and an exception would throw away the very thing it asked for.
    """
    try:
        response = client.get(url, timeout=REQUEST_TIMEOUT_S)
    except httpx.HTTPError as exc:
        return {"url": url, "status": None, "transport_error": str(exc), "body": None}
    return {
        "url": url,
        "status": response.status_code,
        "transport_error": None,
        "body": response.content,
    }


def capture_attempt(urls: tuple[str, str], *, ordinal: int, scheduled_at: str) -> dict:
    """One ordered pair of requests, recorded whether or not it succeeded."""
    with httpx.Client(follow_redirects=False) as client:
        first = _fetch(client, urls[0])
        second = _fetch(client, urls[1])
    both_ok = first["status"] == 200 and second["status"] == 200
    return {
        "ordinal": ordinal,
        "scheduled_at": scheduled_at,
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "statuses": [first["status"], second["status"]],
        "transport_errors": [first["transport_error"], second["transport_error"]],
        "succeeded": both_ok,
        # Bodies are carried out of this function but never into the record: the record is
        # the audit trail and the bodies are the evidence, and mixing them would put
        # megabytes of pool data inside a log of what time we asked.
        "_bodies": (first["body"], second["body"]) if both_ok else None,
    }


def run_registered_capture(
    spec,
    *,
    now: datetime | None = None,
    sleep=None,
    attempt=capture_attempt,
) -> dict:
    """Perform the capture the spec registered, at the moment it registered.

    `now`, `sleep` and `attempt` are injected so the whole policy is testable without waiting
    for a date to arrive or touching a network. That is the only reason they exist; nothing
    here reads them to decide anything.
    """
    schedule = registered_schedule(spec)
    now = now or datetime.now(timezone.utc)
    scheduled = datetime.fromisoformat(
        schedule["first_attempt_at"].replace("Z", "+00:00")
    )

    if now < scheduled:
        raise CaptureRefused(
            f"the registered capture opens at {schedule['first_attempt_at']} and it is now "
            f"{now.isoformat()}. Capturing early would freeze a different observation window "
            "than the one this family is registered against."
        )
    if now > scheduled + timedelta(seconds=LATE_TOLERANCE_S):
        raise CaptureRefused(
            f"the registered capture opened at {schedule['first_attempt_at']} and it is now "
            f"{now.isoformat()}, past the {LATE_TOLERANCE_S}s tolerance. A late capture is "
            "not the registered attempt; the protocol must be recommitted for a new time "
            "rather than quietly answering with a later universe."
        )

    attempts, bodies = [], None
    for ordinal, offset in enumerate(ATTEMPT_OFFSETS_S, start=1):
        if offset and sleep is not None:
            sleep(offset - ATTEMPT_OFFSETS_S[ordinal - 2])
        record = attempt(
            (schedule["pools_url"], schedule["token_list_url"]),
            ordinal=ordinal,
            scheduled_at=(scheduled + timedelta(seconds=offset)).isoformat(),
        )
        bodies_this = record.pop("_bodies", None)
        attempts.append(record)
        if record["succeeded"]:
            bodies = bodies_this
            break

    if bodies is None:
        # Registered outcome, not an exception: three failed attempts is a result the
        # protocol anticipated and named, and it says the lock fails rather than that
        # another time may be tried.
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
    chosen_by = str(spec.case_selection.get("chosen_by", ""))
    population = str(spec.case_selection.get("population", ""))
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
    import re

    found = re.search(pattern, text)
    return found.group(0) if found else None


def _all(text: str, pattern: str) -> list[str]:
    import re

    seen, out = set(), []
    for match in re.findall(pattern, text):
        if match not in seen:
            seen.add(match)
            out.append(match)
    return out


def write_capture(result: dict, directory: Path) -> dict:
    """Write the raw bodies and the attempt log, keeping the two apart."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    if not result.get("captured"):
        (directory / "capture-attempts.json").write_text(
            json.dumps(result, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        return result

    raw = result.pop("_raw")
    (directory / "pools.raw.json").write_bytes(raw[0])
    (directory / "token-list.raw.json").write_bytes(raw[1])
    (directory / "capture-attempts.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return result
