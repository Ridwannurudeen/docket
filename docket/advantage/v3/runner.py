"""The paired run, recorded as it happens rather than summarised after it.

Every earlier report in this build could, in principle, have been assembled from results the
author already had. v1 says so about itself. v2 fixed the pre-registration half but compares
against nulls. v3 pairs an agent against a person, and the thing that makes a paired run
believable is not the arithmetic at the end — it is that the harness records a claim before
the outcome is known and refuses another claim for the same registered slot.

This module is the experiment harness and an API-append ledger. One JSONL file is used per
family. Events are appended and flushed to disk before the work they describe begins. The
file is ordinary editable storage with no independent tamper resistance; the claim-once
guarantee belongs to the harness API, not to the JSONL file.

**A slot is claimed once.** A primary attempt is identified by
``(spec_id, case_id, arm, "primary")``. The first ``attempt_started`` for that identity wins;
a second is refused permanently, not merely while the process lives. That single rule is what
makes "no scored retry" a property of the data instead of a promise in prose — a second run
of a case whose first answer disappointed cannot be recorded, so it cannot be reported.

**An interruption is a result.** A resume operation closes a slot that starts and never
terminates. The detection time is recorded because it is known; the finish time and elapsed
duration are left null because they are not. Reports only read the ledger and surface an
expired dangling slot as stale until a run resume records the interruption.

**The lock is checked three times.** At run opening, immediately before each attempt, and
again at terminal validation. The middle one is the one that matters: inputs verified once at
the top of a long run say nothing about the bytes an arm actually saw. An attempt whose
post-check fails is retained as ``input_tamper`` and scored as a failure — never discarded,
because discarding it would hide the tampering it detected.

Nothing here calls a Docket service in process. The agent arm goes over HTTP to the deployed
service exactly as a buyer's would, because an in-process call measures this repository rather
than the product a judge can hire.
"""

import hashlib
import json
import os
import time
from base64 import b64decode, b64encode
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

from ...hire.receipts import canonical_hash
from .spec import (
    RANGE_CAPTURE_NOT_BEFORE,
    YIELD_SOURCE_URLS,
    PairedSpec,
    assert_runnable,
    is_health_family,
    is_range_family,
    is_warden_family,
    is_yield_family,
    yield_capture_attempts,
)

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


@contextmanager
def _ledger_lock(path: Path):
    """Hold one cross-process lock for a complete read/check/append transaction."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_suffix(path.suffix + ".lock")
    try:
        descriptor = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        pass
    else:
        os.close(descriptor)
    with lock_path.open("r+b") as handle:
        if os.name == "nt":
            import msvcrt

            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
            try:
                if handle.seek(0, os.SEEK_END) == 0:
                    handle.write(b"0")
                    handle.flush()
                yield
            finally:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                if handle.seek(0, os.SEEK_END) == 0:
                    handle.write(b"0")
                    handle.flush()
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _append_event_unlocked(path: Path, event: dict) -> dict:
    if event.get("kind") not in EVENT_KINDS:
        raise ValueError(f"runner: unknown event kind {event.get('kind')!r}")
    stamped = {"recorded_at": _now(), **event}
    line = json.dumps(stamped, sort_keys=True, ensure_ascii=False)
    with Path(path).open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(line + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    return stamped


def append_event(path: Path, event: dict) -> dict:
    """Append one event and put it on disk before returning.

    The flush and `fsync` are the point. An event buffered in the process that is about to do
    the work it describes is not a record of that work having started — it is a record that
    will exist if nothing goes wrong, which is the case it was written for.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with _ledger_lock(path):
        return _append_event_unlocked(path, event)


def _read_events_unlocked(path: Path) -> list[dict]:
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
            raise ValueError(
                f"runner: {path.name} line {number} is not valid JSON — the ledger was "
                "interrupted mid-append and must be inspected, not repaired automatically"
            ) from exc
    return events


def read_events(path: Path) -> list[dict]:
    """Read ledger evidence without creating a directory or lock file."""
    path = Path(path)
    return _read_events_unlocked(path)


def slot_id(spec_id: str, case_id: str, arm: str, kind: str = PRIMARY) -> str:
    if arm not in ARMS:
        raise ValueError(f"runner: unknown arm {arm!r}")
    if kind not in (PRIMARY, SECONDARY):
        raise ValueError(f"runner: unknown attempt kind {kind!r}")
    return f"{spec_id}::{case_id}::{arm}::{kind}"


@dataclass(frozen=True)
class ScheduledSlot:
    """One primary identity derived from the exact locked case bytes."""

    spec_id: str
    case_id: str
    arm: str
    case_sha256: str
    ordinal: int

    @property
    def slot(self) -> str:
        return slot_id(self.spec_id, self.case_id, self.arm)


@dataclass(frozen=True)
class CaptureSlot:
    attempt_ordinal: int
    scheduled_at: datetime


def registered_capture_schedule(spec: PairedSpec) -> tuple[CaptureSlot, ...]:
    """Return the source-capture times registered before any input is frozen."""
    if spec.spec_id == "v3-01-range-doctor":
        attempts = (RANGE_CAPTURE_NOT_BEFORE,)
    elif is_range_family(spec):
        attempts = tuple(
            datetime.fromisoformat(value.replace("Z", "+00:00"))
            for value in spec.case_selection["frame_definition"][
                "pool_truth_capture_attempts"
            ]
        )
    elif is_yield_family(spec):
        attempts = yield_capture_attempts(spec)
    else:
        attempts = ()
    return tuple(
        CaptureSlot(attempt_ordinal=index, scheduled_at=scheduled_at)
        for index, scheduled_at in enumerate(attempts, start=1)
    )


def capture_ledger_path(spec: PairedSpec, captures_dir: Path) -> Path:
    return Path(captures_dir) / f"{spec.spec_id}.source-captures.jsonl"


def capture_due_sources(
    spec: PairedSpec,
    captures_dir: Path,
    *,
    now: datetime | None = None,
    client: httpx.Client | None = None,
) -> dict:
    """Run the next registered raw-byte capture when its one-minute window is open."""
    schedule = registered_capture_schedule(spec)
    if not schedule:
        raise ValueError(
            f"runner: {spec.spec_id} has no registered HTTP capture schedule"
        )
    observed_now = now or datetime.now(timezone.utc)
    if observed_now.tzinfo is None or observed_now.utcoffset() != timedelta(0):
        raise ValueError("runner: capture time must be timezone-aware UTC")
    path = capture_ledger_path(spec, captures_dir)
    with _ledger_lock(path):
        events = _read_events_unlocked(path)
        attempted = {event.get("attempt_ordinal") for event in events}
        slot = next(
            (
                candidate
                for candidate in schedule
                if candidate.attempt_ordinal not in attempted
            ),
            None,
        )
        if slot is None:
            raise ValueError(
                "runner: every registered source-capture attempt is recorded"
            )
        if observed_now < slot.scheduled_at:
            raise ValueError(
                f"runner: next source capture is scheduled for {slot.scheduled_at.isoformat()}"
            )
        if observed_now >= slot.scheduled_at + timedelta(minutes=1):
            return _append_capture_event(
                path,
                {
                    "spec_id": spec.spec_id,
                    "attempt_ordinal": slot.attempt_ordinal,
                    "scheduled_at": slot.scheduled_at.isoformat().replace(
                        "+00:00", "Z"
                    ),
                    "captured_at": observed_now.isoformat(),
                    "pools_status": 0,
                    "token_list_status": 0,
                    "source_snapshots": None,
                    "failure": "registered one-minute capture window was missed",
                },
            )

        owned_client = client is None
        session = client or httpx.Client()
        responses = {}
        failures = {}
        try:
            for name in ("pools", "token_list"):
                try:
                    responses[name] = session.get(YIELD_SOURCE_URLS[name], timeout=30.0)
                except httpx.HTTPError as exc:
                    responses[name] = None
                    failures[name] = f"{type(exc).__name__}: {exc}"
        finally:
            if owned_client:
                session.close()
        snapshots = None
        if all(
            response is not None and response.status_code == 200
            for response in responses.values()
        ):
            snapshots = {
                name: {
                    "url": YIELD_SOURCE_URLS[name],
                    "observed_at": observed_now.isoformat().replace("+00:00", "Z"),
                    "attempt_ordinal": slot.attempt_ordinal,
                    "sha256": hashlib.sha256(response.content).hexdigest(),
                    "body_base64": b64encode(response.content).decode("ascii"),
                }
                for name, response in responses.items()
            }
        return _append_capture_event(
            path,
            {
                "spec_id": spec.spec_id,
                "attempt_ordinal": slot.attempt_ordinal,
                "scheduled_at": slot.scheduled_at.isoformat().replace("+00:00", "Z"),
                "captured_at": observed_now.isoformat(),
                "pools_status": (
                    0 if responses["pools"] is None else responses["pools"].status_code
                ),
                "token_list_status": (
                    0
                    if responses["token_list"] is None
                    else responses["token_list"].status_code
                ),
                "source_snapshots": snapshots,
                "failure": failures or None,
            },
        )


def _append_capture_event(path: Path, event: dict) -> dict:
    stamped = {"recorded_at": _now(), **event}
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(stamped, sort_keys=True, ensure_ascii=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    return stamped


def _locked_inputs(spec: PairedSpec, repo_root: Path | None) -> dict:
    _assert_locked(spec, repo_root)
    root = (
        Path(repo_root)
        if repo_root is not None
        else Path(__file__).resolve().parents[3]
    )
    return json.loads((root / spec.inputs_ref).read_text(encoding="utf-8"))


def scheduled_slots(
    spec: PairedSpec, *, repo_root: Path | None = None
) -> tuple[ScheduledSlot, ...]:
    """Return the registered manual block followed by the registered agent block."""
    inputs = _locked_inputs(spec, repo_root)
    cases = inputs["cases"]
    slots = []
    for arm in ARMS:
        for case in cases:
            slots.append(
                ScheduledSlot(
                    spec_id=spec.spec_id,
                    case_id=case["case_id"],
                    arm=arm,
                    case_sha256=canonical_hash(case),
                    ordinal=len(slots) + 1,
                )
            )
    return tuple(slots)


def _registered_slot(
    spec: PairedSpec, candidate: ScheduledSlot, repo_root: Path | None
) -> ScheduledSlot:
    for scheduled in scheduled_slots(spec, repo_root=repo_root):
        if scheduled.slot == candidate.slot:
            if scheduled != candidate:
                break
            return scheduled
    raise ValueError(
        "runner: the requested primary is not the exact case/arm binding in the locked schedule"
    )


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


def _fold_state(events: list[dict]) -> dict[str, SlotState]:
    state: dict[str, SlotState] = {}
    for event in events:
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


def read_state(path: Path) -> dict[str, SlotState]:
    """Fold the ledger into one state per slot. Later events never erase earlier ones."""
    path = Path(path)
    with _ledger_lock(path):
        return _fold_state(_read_events_unlocked(path))


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


def recover_interrupted(
    spec: PairedSpec, runs_dir: Path, *, expired_only: bool = False
) -> list[dict]:
    """Close every slot that was claimed and never terminated.

    Called before a run resumes. The finish time and elapsed duration stay null: the process
    that would have known them is gone, and a plausible number here would be indistinguishable
    from a measured one.
    """
    path = ledger_path(spec, runs_dir)
    closed = []
    detected_at = datetime.now(timezone.utc)
    with _ledger_lock(path):
        for slot, state in _fold_state(_read_events_unlocked(path)).items():
            if not state.is_dangling:
                continue
            deadline = state.started.get("deadline_at")
            if expired_only and (
                not isinstance(deadline, str)
                or datetime.fromisoformat(deadline) > detected_at
            ):
                continue
            closed.append(
                _append_event_unlocked(
                    path,
                    {
                        "kind": INTERRUPTED,
                        "slot": slot,
                        "spec_id": spec.spec_id,
                        "outcome": INTERRUPTED,
                        "detected_at": detected_at.isoformat(),
                        "finished_at": None,
                        "elapsed_ns": None,
                        "eligible_for_speed": False,
                        "note": (
                            "This attempt started and never reported a terminal event. The "
                            "detection time is recorded because it is known; the finish time "
                            "and duration are null because they are not. It scores zero and "
                            "is not re-run."
                        ),
                    },
                )
            )
    return closed


def claim_slot(
    spec: PairedSpec,
    runs_dir: Path,
    *,
    slot: ScheduledSlot,
    repo_root: Path | None = None,
    clock=None,
) -> dict:
    """Claim an attempt slot, or refuse because it was already claimed.

    The lock is re-checked here, immediately before the work, rather than only at
    `open_run`: a long run's inputs can move under it, and a check at the top of the run says
    nothing about the bytes this arm is about to see.
    """
    tick = time.monotonic_ns if clock is None else clock
    registered = _registered_slot(spec, slot, repo_root)
    path = ledger_path(spec, runs_dir)
    with _ledger_lock(path):
        _assert_locked(spec, repo_root)
        state = _fold_state(_read_events_unlocked(path)).get(
            registered.slot, SlotState()
        )
        if state.is_claimed:
            raise ValueError(
                f"runner: primary slot {registered.slot} was already claimed at "
                f"{state.started.get('recorded_at')}. A primary attempt is claimed once — "
                "a second run cannot be recorded or reported."
            )
        started_at = datetime.now(timezone.utc)
        return _append_event_unlocked(
            path,
            {
                "kind": STARTED,
                "slot": registered.slot,
                "spec_id": spec.spec_id,
                "case_id": registered.case_id,
                "arm": registered.arm,
                "attempt_kind": PRIMARY,
                "schedule_ordinal": registered.ordinal,
                "started_at": started_at.isoformat(),
                "deadline_at": (
                    started_at + timedelta(seconds=spec.timing["timeout_seconds"])
                ).isoformat(),
                "started_monotonic_ns": tick(),
                "case_binding": {"case_sha256": registered.case_sha256},
                **_lock_header(spec),
            },
        )


def terminate_slot(
    spec: PairedSpec,
    runs_dir: Path,
    *,
    slot: ScheduledSlot,
    repo_root: Path | None = None,
    raw_output: object = None,
    failure: dict | None = None,
    cost: dict | None = None,
    receipt: dict | None = None,
    clock=None,
) -> dict:
    return _terminate_slot(
        spec,
        runs_dir,
        slot=slot,
        repo_root=repo_root,
        raw_output=raw_output,
        failure=failure,
        cost=cost,
        receipt=receipt,
        clock=clock,
    )


def _terminate_slot(
    spec: PairedSpec,
    runs_dir: Path,
    *,
    slot: ScheduledSlot,
    repo_root: Path | None = None,
    raw_output: object = None,
    failure: dict | None = None,
    cost: dict | None = None,
    receipt: dict | None = None,
    forced_outcome: str | None = None,
    clock=None,
) -> dict:
    """Close an attempt, recording what came back and whether it may count for speed.

    The lock is checked once more here. A post-attempt mismatch means the inputs moved while
    the arm ran, so the attempt is retained as `input_tamper` rather than as whatever it
    claimed to be — the detection is the finding, and discarding the attempt would discard it.
    """
    if slot.spec_id != spec.spec_id or slot.arm not in ARMS:
        raise ValueError(
            "runner: terminal slot does not identify this registered family"
        )
    registered = slot
    if forced_outcome not in (None, TIMED_OUT, BLOCKED_CONTRACT):
        raise ValueError(f"runner: invalid harness outcome {forced_outcome!r}")
    if forced_outcome == BLOCKED_CONTRACT and registered.arm != "agent":
        raise ValueError(
            "runner: blocked_service_contract is valid only for an agent slot"
        )
    path = ledger_path(spec, runs_dir)
    with _ledger_lock(path):
        state = _fold_state(_read_events_unlocked(path)).get(
            registered.slot, SlotState()
        )
        if not state.is_claimed:
            raise ValueError(
                f"runner: cannot terminate {registered.slot}, it was never claimed"
            )
        if (
            state.started.get("case_id") != registered.case_id
            or state.started.get("arm") != registered.arm
            or state.started.get("schedule_ordinal") != registered.ordinal
            or state.started.get("case_binding")
            != {"case_sha256": registered.case_sha256}
        ):
            raise ValueError(
                "runner: terminal slot does not match the exact claimed case binding"
            )
        if state.is_terminated:
            raise ValueError(
                f"runner: {registered.slot} already terminated as "
                f"{state.terminal.get('outcome')!r}; an attempt has one ending"
            )

        started_ns = state.started.get("started_monotonic_ns")
        tick = time.monotonic_ns if clock is None else clock
        now_ns = tick()
        elapsed_ns = None if started_ns is None else now_ns - started_ns
        timeout_ns = spec.timing["timeout_seconds"] * 1_000_000_000
        if elapsed_ns is not None and elapsed_ns >= timeout_ns:
            outcome = TIMED_OUT
            raw_output = None
            failure = failure or {
                "kind": TIMED_OUT,
                "message": "the registered attempt deadline elapsed before submission",
            }
        elif forced_outcome is not None:
            outcome = forced_outcome
        elif failure is not None or raw_output is None:
            outcome = FAILED
        else:
            outcome = SUCCEEDED

        try:
            _assert_locked(spec, repo_root)
        except ValueError as exc:
            outcome = INPUT_TAMPER
            raw_output = None
            failure = {
                "kind": INPUT_TAMPER,
                "message": str(exc),
                "detected": "after the attempt ran, on the terminal re-check",
            }

        return _append_event_unlocked(
            path,
            {
                "kind": TERMINATED,
                "slot": registered.slot,
                "spec_id": spec.spec_id,
                "case_id": registered.case_id,
                "arm": registered.arm,
                "attempt_kind": PRIMARY,
                "outcome": outcome,
                "finished_at": _now(),
                "finished_monotonic_ns": now_ns,
                "elapsed_ns": elapsed_ns,
                "eligible_for_speed": outcome in SPEED_ELIGIBLE,
                "output_sha256": (
                    None if raw_output is None else canonical_hash(raw_output)
                ),
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
    slot: ScheduledSlot,
    repo_root: Path | None = None,
    request: dict,
    response_summary: dict,
) -> dict:
    """Log a source the manual arm consulted, before the answer that used it exists.

    The manual arm's sources are its working. Recorded as they are fetched, they cannot be
    curated afterwards into the set that happens to support the answer given.
    """
    registered = _registered_slot(spec, slot, repo_root)
    if registered.arm != "manual":
        raise ValueError("runner: source queries belong only to an active manual slot")
    path = ledger_path(spec, runs_dir)
    with _ledger_lock(path):
        state = _fold_state(_read_events_unlocked(path)).get(
            registered.slot, SlotState()
        )
        if not state.is_dangling:
            raise ValueError("runner: source queries require an active manual slot")
        return _append_event_unlocked(
            path,
            {
                "kind": SOURCE_QUERY,
                "slot": registered.slot,
                "spec_id": spec.spec_id,
                "case_id": registered.case_id,
                "arm": registered.arm,
                "request": request,
                "response": response_summary,
            },
        )


class ExperimentHarness:
    """Execute one locked family without accepting case, arm, outcome or timeout choices."""

    def __init__(
        self, spec: PairedSpec, runs_dir: Path, *, repo_root: Path | None = None
    ):
        self.spec = spec
        self.runs_dir = Path(runs_dir)
        self.repo_root = (
            Path(repo_root)
            if repo_root is not None
            else Path(__file__).resolve().parents[3]
        )
        self.inputs = _locked_inputs(spec, self.repo_root)
        self.slots = scheduled_slots(spec, repo_root=self.repo_root)
        self.cases = {case["case_id"]: case for case in self.inputs["cases"]}

    def start(self) -> dict:
        return open_run(self.spec, self.runs_dir, repo_root=self.repo_root)

    def resume(self) -> list[dict]:
        closed = recover_interrupted(self.spec, self.runs_dir)
        open_run(self.spec, self.runs_dir, repo_root=self.repo_root)
        return closed

    def _next_slot(self, arm: str) -> ScheduledSlot:
        state = read_state(ledger_path(self.spec, self.runs_dir))
        for scheduled in self.slots:
            current = state.get(scheduled.slot, SlotState())
            if current.is_dangling:
                raise ValueError(
                    f"runner: scheduled slot {scheduled.slot} is still active"
                )
            if current.is_claimed:
                continue
            if scheduled.arm != arm:
                raise ValueError(
                    f"runner: the registered {scheduled.arm} block must run next"
                )
            return scheduled
        raise ValueError(f"runner: the registered {arm} block has no remaining slots")

    def _active_manual(self) -> ScheduledSlot:
        state = read_state(ledger_path(self.spec, self.runs_dir))
        active = [
            scheduled
            for scheduled in self.slots
            if scheduled.arm == "manual"
            and state.get(scheduled.slot, SlotState()).is_dangling
        ]
        if len(active) != 1:
            raise ValueError(
                "runner: exactly one manual slot must be active for submission"
            )
        return active[0]

    def reveal_manual_case(self) -> dict:
        slot = self._next_slot("manual")
        revealed = _manual_reveal(
            self.spec,
            self.inputs,
            self.cases[slot.case_id],
            self.repo_root,
        )
        claim_slot(self.spec, self.runs_dir, slot=slot, repo_root=self.repo_root)
        _record_manual_reveal_sources(
            self.spec,
            self.runs_dir,
            slot,
            revealed,
            self.repo_root,
        )
        return revealed

    def submit_manual(self, raw_output: object, *, cost: dict | None = None) -> dict:
        return terminate_slot(
            self.spec,
            self.runs_dir,
            slot=self._active_manual(),
            repo_root=self.repo_root,
            raw_output=raw_output,
            cost=cost,
        )

    def run_agent(
        self,
        payment_headers: dict[str, str] | None = None,
        *,
        client: httpx.Client | None = None,
    ) -> dict:
        headers = payment_headers or {}
        slot = self._next_slot("agent")
        payload = _agent_payload(
            self.spec, self.inputs, self.cases[slot.case_id], self.repo_root
        )
        claim_slot(self.spec, self.runs_dir, slot=slot, repo_root=self.repo_root)
        owned_client = client is None
        session = client or httpx.Client()
        try:
            try:
                response = session.post(
                    self.spec.execution_protocol["agent_endpoint"],
                    json=payload,
                    headers=headers,
                    timeout=self.spec.timing["timeout_seconds"],
                )
            except httpx.TimeoutException as exc:
                return _terminate_slot(
                    self.spec,
                    self.runs_dir,
                    slot=slot,
                    repo_root=self.repo_root,
                    failure={"kind": TIMED_OUT, "message": str(exc)},
                    forced_outcome=TIMED_OUT,
                )
            except httpx.RequestError as exc:
                return terminate_slot(
                    self.spec,
                    self.runs_dir,
                    slot=slot,
                    repo_root=self.repo_root,
                    failure={
                        "kind": "transport_error",
                        "message": f"{type(exc).__name__}: {exc}",
                    },
                )
            if response.status_code in (400, 422):
                return _terminate_slot(
                    self.spec,
                    self.runs_dir,
                    slot=slot,
                    repo_root=self.repo_root,
                    failure={
                        "kind": BLOCKED_CONTRACT,
                        "message": (
                            f"the registered request was refused with HTTP "
                            f"{response.status_code}"
                        ),
                    },
                    forced_outcome=BLOCKED_CONTRACT,
                )
            if response.status_code != 200:
                return terminate_slot(
                    self.spec,
                    self.runs_dir,
                    slot=slot,
                    repo_root=self.repo_root,
                    failure={
                        "kind": "http_error",
                        "message": f"agent endpoint returned HTTP {response.status_code}",
                    },
                )
            try:
                body = response.json()
            except ValueError as exc:
                return terminate_slot(
                    self.spec,
                    self.runs_dir,
                    slot=slot,
                    repo_root=self.repo_root,
                    failure={"kind": "malformed_json", "message": str(exc)},
                )
            result = body.get("result") if isinstance(body, dict) else None
            receipt = body.get("receipt") if isinstance(body, dict) else None
            payment = receipt.get("payment") if isinstance(receipt, dict) else None
            receipt_valid = bool(
                isinstance(receipt, dict)
                and receipt.get("service")
                == self.spec.execution_protocol["agent_service_id"]
                and receipt.get("input_hash") == canonical_hash(payload)
                and result not in (None, "", [], {})
                and receipt.get("output_hash") == canonical_hash(result)
                and isinstance(payment, dict)
                and payment.get("status") in {"free_tier", "settled"}
            )
            if not receipt_valid:
                return terminate_slot(
                    self.spec,
                    self.runs_dir,
                    slot=slot,
                    repo_root=self.repo_root,
                    failure={
                        "kind": "invalid_receipt_or_empty",
                        "message": (
                            "agent response lacked a nonempty hash-bound result or a valid "
                            "free-tier/settled receipt"
                        ),
                    },
                    receipt=receipt,
                )
            return terminate_slot(
                self.spec,
                self.runs_dir,
                slot=slot,
                repo_root=self.repo_root,
                raw_output=result,
                receipt=receipt,
                cost={
                    "amount": payment.get("amount", "0"),
                    "asset": payment.get("asset"),
                    "payment_status": payment["status"],
                },
            )
        finally:
            if owned_client:
                session.close()

    def export_evaluation_sessions(self, sessions_dir: Path) -> tuple[Path, ...]:
        from . import scoring

        bundle = scoring.build_blinded_bundle(
            self.spec,
            ledger_path(self.spec, self.runs_dir),
            repo_root=self.repo_root,
        )
        paths = []
        for seat in self.spec.scoring["evaluator_roster"]:
            evaluator_id = seat["evaluator_id"]
            seat_key = hashlib.sha256(evaluator_id.encode("utf-8")).hexdigest()[:24]
            path = Path(sessions_dir) / f"{self.spec.spec_id}-{seat_key}.json"
            body = {
                "session_version": "v3.evaluation-session.v1",
                "evaluator_id": evaluator_id,
                "bundle": bundle,
                "score_sheet_template": {
                    "spec_id": self.spec.spec_id,
                    "spec_hash": self.spec.spec_hash,
                    "evaluator_id": evaluator_id,
                    "blinded_bundle_hash": canonical_hash(bundle),
                    "scores": [],
                },
            }
            _write_exclusive_json(path, body)
            paths.append(path)
        return tuple(paths)

    def import_evaluation_submission(self, raw_sheet: bytes, sheets_dir: Path) -> dict:
        from . import scoring

        bundle = scoring.build_blinded_bundle(
            self.spec,
            ledger_path(self.spec, self.runs_dir),
            repo_root=self.repo_root,
        )
        return scoring.ingest_score_sheet(self.spec, bundle, raw_sheet, sheets_dir)


def _manual_case(case: dict) -> dict:
    hidden = {
        "truth",
        "expected_verdict",
        "labels",
        "evidence_spans",
        "hostile",
        "critical",
        "survival_predicates",
    }
    return {key: value for key, value in case.items() if key not in hidden}


def _manual_reveal(
    spec: PairedSpec,
    inputs: dict,
    case: dict,
    repo_root: Path,
) -> dict:
    revealed = _manual_case(case)
    if is_range_family(spec):
        pool_truth_ref = next(
            source for source in case["source_refs"] if source["kind"] == "pool_truth"
        )
        source_ref = pool_truth_ref["ref"]
        snapshots = _read_locked_json(pool_truth_ref, repo_root)["source_snapshots"]
    elif is_yield_family(spec):
        source_ref = spec.inputs_ref
        snapshots = inputs["source_snapshots"]
    elif is_health_family(spec):
        # The frozen Venus frame is a repository artifact rather than embedded response
        # bytes, so the reveal hands over the account's own pinned rows with the digest
        # they were locked under. The truth block is already stripped by `_manual_case`.
        frame_ref = next(
            source for source in case["source_refs"] if source["kind"] == "venus_frame"
        )
        frame = _read_locked_json(frame_ref, repo_root)
        row = next(
            account
            for account in frame["accounts"]
            if account["account"] == case["account"]
        )
        derived = {
            "status",
            "weighted_collateral_usd",
            "borrowed_usd",
            "collateral_ratio",
            "derived_headroom_usd",
            "venus_headroom_usd",
            "difference_usd",
            "exactly_equal",
        }
        return {
            **revealed,
            "frame_ref": f"{frame_ref['ref']}#accounts/{case['account']}",
            "account_state": {
                name: value for name, value in row.items() if name not in derived
            },
        }
    else:
        return revealed

    exposed = {}
    for name, snapshot in snapshots.items():
        raw = b64decode(snapshot["body_base64"], validate=True)
        if hashlib.sha256(raw).hexdigest() != snapshot["sha256"]:
            raise ValueError(
                "runner: a locked manual source changed after input validation"
            )
        exposed[name] = {
            **snapshot,
            "name": name,
            "source_ref": f"{source_ref}#source_snapshots/{name}",
            "body": json.loads(raw.decode("utf-8")),
        }
    return {**revealed, "source_snapshots": exposed}


def _record_manual_reveal_sources(
    spec: PairedSpec,
    runs_dir: Path,
    slot: ScheduledSlot,
    revealed: dict,
    repo_root: Path,
) -> None:
    for snapshot in revealed.get("source_snapshots", {}).values():
        record_source_query(
            spec,
            runs_dir,
            slot=slot,
            repo_root=repo_root,
            request={
                "name": snapshot["name"],
                "url": snapshot["url"],
                "source_ref": snapshot["source_ref"],
            },
            response_summary={
                "attempt_ordinal": snapshot["attempt_ordinal"],
                "observed_at": snapshot["observed_at"],
                "body_sha256": snapshot["sha256"],
            },
        )


def _read_locked_json(source: dict, repo_root: Path) -> dict:
    path = repo_root / source["ref"]
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != source["sha256"]:
        raise ValueError("runner: a locked source changed after input validation")
    return json.loads(raw.decode("utf-8"))


def _agent_payload(spec: PairedSpec, inputs: dict, case: dict, repo_root: Path) -> dict:
    if is_range_family(spec):
        pool_truth_ref = next(
            source for source in case["source_refs"] if source["kind"] == "pool_truth"
        )
        snapshots = _read_locked_json(pool_truth_ref, repo_root)["source_snapshots"]
        return {
            "wallet": case["wallet"],
            "position_manager": case["position_manager"],
            "token_id": case["token_id"],
            "observation_block": case["observation_block"],
            "declared_position_value_usd": case["declared_position_value_usd"],
            "estimated_recenter_cost_usd": case["estimated_recenter_cost_usd"],
            "decision_horizon_days": case["decision_horizon_days"],
            "source_refs": case["source_refs"],
            "pool_snapshot": snapshots["pools"],
            "token_list_snapshot": snapshots["token_list"],
        }
    if is_yield_family(spec):
        return {
            "pool": case["pool_id"],
            "position_size_usd": case["position_value_usd"],
            "switching_cost_usd": case["switching_cost_usd"],
            "horizon_days": case["decision_horizon_days"],
            "pool_snapshot": inputs["source_snapshots"]["pools"],
            "token_list_snapshot": inputs["source_snapshots"]["token_list"],
        }
    if is_health_family(spec):
        return {
            "wallet": case["account"],
            "trigger_shortfall_usd": case["trigger_shortfall_usd"],
            "observation_block": case["observation_block"],
            "source_refs": case["source_refs"],
        }
    if is_warden_family(spec):
        return {"payload": case["text"]}
    value = case.get("input")
    return value if isinstance(value, dict) else {}


def _write_exclusive_json(path: Path, body: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = (
        json.dumps(body, sort_keys=True, indent=2, ensure_ascii=False) + "\n"
    ).encode()
    try:
        with path.open("xb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError as exc:
        raise ValueError(
            f"runner: evaluation session {path.name!r} already exists"
        ) from exc


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
