"""The paired run, recorded as it happens rather than summarised after it.

Every earlier report in this build could, in principle, have been assembled from results the
author already had. v1 says so about itself. v2 fixed the pre-registration half but compares
against nulls. v3 pairs an agent against a person, and the thing that makes a paired run
believable is not the arithmetic at the end — it is that the record of what happened was
written before the outcome was known and could not be revised afterwards.

So this module is an append-only ledger and almost nothing else. One JSONL file per family.
Events are appended and flushed to disk before the work they describe begins, which is the
only ordering under which a crash leaves evidence rather than a gap.

**A slot is claimed once.** A primary attempt is identified by
``(spec_id, case_id, arm, "primary")``. The first ``attempt_started`` for that identity wins;
a second is refused permanently, not merely while the process lives. That single rule is what
makes "no scored retry" a property of the data instead of a promise in prose — a second run
of a case whose first answer disappointed cannot be recorded, so it cannot be reported.

**An interruption is a result.** A slot that starts and never terminates is closed as
``interrupted`` when the ledger is next read. The detection time is recorded because it is
known; the finish time and the elapsed duration are left null because they are not. Inventing
either would be the cheapest possible lie and the hardest to notice.

**The lock is checked three times.** At run opening, immediately before each attempt, and
again at terminal validation. The middle one is the one that matters: inputs verified once at
the top of a long run say nothing about the bytes an arm actually saw. An attempt whose
post-check fails is retained as ``input_tamper`` and scored as a failure — never discarded,
because discarding it would hide the tampering it detected.

Nothing here calls a Docket service in process. The agent arm goes over HTTP to the deployed
service exactly as a buyer's would, because an in-process call measures this repository rather
than the product a judge can hire.
"""

import json
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from ...hire.receipts import canonical_hash
from .spec import PairedSpec, assert_runnable

ARMS = ("manual", "agent")
PRIMARY = "primary"
SECONDARY = "secondary"

# Event kinds. Closed, because an unrecognised kind in an evidence ledger is a record whose
# meaning is decided by whoever reads it last.
STARTED = "attempt_started"
TERMINATED = "attempt_terminated"
INTERRUPTED = "interrupted"
SOURCE_QUERY = "source_query"
RUN_OPENED = "run_opened"
EVENT_KINDS = (STARTED, TERMINATED, INTERRUPTED, SOURCE_QUERY, RUN_OPENED)

# Terminal outcomes. `blocked_service_contract` is deliberately distinct from `failed`: a
# service that cannot accept the registered request has not failed the task, and recording it
# as a failure would understate the agent while hiding a gap that is ours to close.
SUCCEEDED = "succeeded"
FAILED = "failed"
TIMED_OUT = "timed_out"
INPUT_TAMPER = "input_tamper"
BLOCKED_CONTRACT = "blocked_service_contract"
OUTCOMES = (SUCCEEDED, FAILED, TIMED_OUT, INPUT_TAMPER, BLOCKED_CONTRACT, INTERRUPTED)
# Only a success can contribute a duration to the speed comparison. Everything else either
# has no honest elapsed time or has one that measures a failure rather than the work.
SPEED_ELIGIBLE = (SUCCEEDED,)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def ledger_path(spec: PairedSpec, runs_dir: Path) -> Path:
    return Path(runs_dir) / f"{spec.spec_id}.jsonl"


def append_event(path: Path, event: dict) -> dict:
    """Append one event and put it on disk before returning.

    The flush and `fsync` are the point. An event buffered in the process that is about to do
    the work it describes is not a record of that work having started — it is a record that
    will exist if nothing goes wrong, which is the case it was written for.
    """
    if event.get("kind") not in EVENT_KINDS:
        raise ValueError(f"runner: unknown event kind {event.get('kind')!r}")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    stamped = {"recorded_at": _now(), **event}
    line = json.dumps(stamped, sort_keys=True, ensure_ascii=False)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(line + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    return stamped


def read_events(path: Path) -> list[dict]:
    path = Path(path)
    if not path.exists():
        return []
    events = []
    for number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError as exc:
            # A half-written final line is what a crash mid-append looks like. It is
            # reported rather than skipped, because silently dropping it would turn a
            # visible interruption into a missing attempt.
            raise ValueError(
                f"runner: {path.name} line {number} is not valid JSON — the ledger was "
                "interrupted mid-append and must be inspected, not repaired automatically"
            ) from exc
    return events


def slot_id(spec_id: str, case_id: str, arm: str, kind: str = PRIMARY) -> str:
    if arm not in ARMS:
        raise ValueError(f"runner: unknown arm {arm!r}")
    if kind not in (PRIMARY, SECONDARY):
        raise ValueError(f"runner: unknown attempt kind {kind!r}")
    return f"{spec_id}::{case_id}::{arm}::{kind}"


@dataclass(frozen=True)
class SlotState:
    """What the ledger says about one attempt slot."""

    started: dict | None = None
    terminal: dict | None = None

    @property
    def is_claimed(self) -> bool:
        return self.started is not None

    @property
    def is_terminated(self) -> bool:
        return self.terminal is not None

    @property
    def is_dangling(self) -> bool:
        """Started, never finished — a crash, a kill, or a machine that went away."""
        return self.is_claimed and not self.is_terminated


def read_state(path: Path) -> dict[str, SlotState]:
    """Fold the ledger into one state per slot. Later events never erase earlier ones."""
    state: dict[str, SlotState] = {}
    for event in read_events(path):
        slot = event.get("slot")
        if slot is None:
            continue
        current = state.get(slot, SlotState())
        if event["kind"] == STARTED:
            # A second start is refused at write time; if one is present the ledger was
            # edited by hand, and the first claim is the one that stands.
            if current.started is None:
                state[slot] = SlotState(started=event, terminal=current.terminal)
        elif event["kind"] in (TERMINATED, INTERRUPTED):
            if current.terminal is None:
                state[slot] = SlotState(started=current.started, terminal=event)
    return state


def open_run(
    spec: PairedSpec, runs_dir: Path, *, repo_root: Path | None = None
) -> dict:
    """Record that a run began, after proving the inputs are locked and unchanged."""
    _assert_locked(spec, repo_root)
    path = ledger_path(spec, runs_dir)
    return append_event(
        path,
        {
            "kind": RUN_OPENED,
            "spec_id": spec.spec_id,
            "opened_at": _now(),
            **_lock_header(spec),
        },
    )


def recover_interrupted(spec: PairedSpec, runs_dir: Path) -> list[dict]:
    """Close every slot that was claimed and never terminated.

    Called before a run resumes. The finish time and elapsed duration stay null: the process
    that would have known them is gone, and a plausible number here would be indistinguishable
    from a measured one.
    """
    path = ledger_path(spec, runs_dir)
    closed = []
    for slot, state in read_state(path).items():
        if not state.is_dangling:
            continue
        closed.append(
            append_event(
                path,
                {
                    "kind": INTERRUPTED,
                    "slot": slot,
                    "spec_id": spec.spec_id,
                    "outcome": INTERRUPTED,
                    "detected_at": _now(),
                    "finished_at": None,
                    "elapsed_ns": None,
                    "eligible_for_speed": False,
                    "note": (
                        "This attempt started and never reported a terminal event. The "
                        "detection time is recorded because it is known; the finish time and "
                        "duration are null because they are not. It scores zero and is not "
                        "re-run."
                    ),
                },
            )
        )
    return closed


def claim_slot(
    spec: PairedSpec,
    runs_dir: Path,
    *,
    case_id: str,
    arm: str,
    kind: str = PRIMARY,
    repo_root: Path | None = None,
    case_binding: dict | None = None,
) -> dict:
    """Claim an attempt slot, or refuse because it was already claimed.

    The lock is re-checked here, immediately before the work, rather than only at
    `open_run`: a long run's inputs can move under it, and a check at the top of the run says
    nothing about the bytes this arm is about to see.
    """
    _assert_locked(spec, repo_root)
    path = ledger_path(spec, runs_dir)
    slot = slot_id(spec.spec_id, case_id, arm, kind)
    state = read_state(path).get(slot, SlotState())
    if state.is_claimed and kind == PRIMARY:
        raise ValueError(
            f"runner: primary slot {slot} was already claimed at "
            f"{state.started.get('recorded_at')}. A primary attempt is claimed once — a "
            "second run of a case whose first answer disappointed is exactly what the "
            "stopping rule forbids, so it cannot be recorded and therefore cannot be reported."
        )
    return append_event(
        path,
        {
            "kind": STARTED,
            "slot": slot,
            "spec_id": spec.spec_id,
            "case_id": case_id,
            "arm": arm,
            "attempt_kind": kind,
            "started_at": _now(),
            "started_monotonic_ns": time.monotonic_ns(),
            "case_binding": case_binding or {},
            **_lock_header(spec),
        },
    )


def terminate_slot(
    spec: PairedSpec,
    runs_dir: Path,
    *,
    case_id: str,
    arm: str,
    outcome: str,
    kind: str = PRIMARY,
    repo_root: Path | None = None,
    raw_output: object = None,
    failure: dict | None = None,
    cost: dict | None = None,
    receipt: dict | None = None,
) -> dict:
    """Close an attempt, recording what came back and whether it may count for speed.

    The lock is checked once more here. A post-attempt mismatch means the inputs moved while
    the arm ran, so the attempt is retained as `input_tamper` rather than as whatever it
    claimed to be — the detection is the finding, and discarding the attempt would discard it.
    """
    if outcome not in OUTCOMES:
        raise ValueError(f"runner: unknown outcome {outcome!r}")
    path = ledger_path(spec, runs_dir)
    slot = slot_id(spec.spec_id, case_id, arm, kind)
    state = read_state(path).get(slot, SlotState())
    if not state.is_claimed:
        raise ValueError(f"runner: cannot terminate {slot}, it was never claimed")
    if state.is_terminated:
        raise ValueError(
            f"runner: {slot} already terminated as "
            f"{state.terminal.get('outcome')!r}; an attempt has one ending"
        )

    try:
        _assert_locked(spec, repo_root)
    except ValueError as exc:
        outcome = INPUT_TAMPER
        failure = {
            "kind": INPUT_TAMPER,
            "message": str(exc),
            "detected": "after the attempt ran, on the terminal re-check",
        }

    started_ns = state.started.get("started_monotonic_ns")
    now_ns = time.monotonic_ns()
    elapsed_ns = None if started_ns is None else now_ns - started_ns
    return append_event(
        path,
        {
            "kind": TERMINATED,
            "slot": slot,
            "spec_id": spec.spec_id,
            "case_id": case_id,
            "arm": arm,
            "attempt_kind": kind,
            "outcome": outcome,
            "finished_at": _now(),
            "finished_monotonic_ns": now_ns,
            "elapsed_ns": elapsed_ns,
            # Derived, never supplied: an operator who can mark their own attempt eligible
            # can choose which durations enter the comparison.
            "eligible_for_speed": outcome in SPEED_ELIGIBLE and kind == PRIMARY,
            "output_sha256": None if raw_output is None else canonical_hash(raw_output),
            "raw_output": raw_output,
            "failure": failure,
            "cost": cost,
            "receipt": receipt,
            **_lock_header(spec),
        },
    )


def record_source_query(
    spec: PairedSpec,
    runs_dir: Path,
    *,
    case_id: str,
    arm: str,
    request: dict,
    response_summary: dict,
) -> dict:
    """Log a source the manual arm consulted, before the answer that used it exists.

    The manual arm's sources are its working. Recorded as they are fetched, they cannot be
    curated afterwards into the set that happens to support the answer given.
    """
    return append_event(
        ledger_path(spec, runs_dir),
        {
            "kind": SOURCE_QUERY,
            "slot": slot_id(spec.spec_id, case_id, arm),
            "spec_id": spec.spec_id,
            "case_id": case_id,
            "arm": arm,
            "request": request,
            "response": response_summary,
        },
    )


def _lock_header(spec: PairedSpec) -> dict:
    """The three identities every record cites, because they answer different questions.

    The protocol hash says which registered choices governed. The spec hash says which
    protocol-plus-input-lock. The input digest says which exact bytes. A record carrying only
    one of them can be true about a run that never happened under the others.
    """
    return {
        "stage_one_protocol_hash": spec.stage_one_protocol_hash,
        "spec_hash": spec.spec_hash,
        "inputs_sha256": spec.inputs_sha256,
        "inputs_ref": spec.inputs_ref,
    }


def _assert_locked(spec: PairedSpec, repo_root: Path | None) -> None:
    if repo_root is None:
        assert_runnable(spec)
    else:
        assert_runnable(spec, repo_root=repo_root)
