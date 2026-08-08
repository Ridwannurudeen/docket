"""One task, run with an agent and without one, recorded so a reader can check the claim.

The comparison a report like this invites is "which arm was better", and that is
exactly the claim this module refuses to make. `compare` returns elapsed seconds,
what each arm cost, and the ratio between the two timings. Nothing else: the
outputs of both arms travel with the experiment in full, hash-bound, and a reader
grades them. A harness that scored its own runs would be marking its own homework.

Cost is a `{"amount", "unit", "note"}` triple rather than a number, so "0.01 $U"
and "0 (public endpoints only)" are both sayable without converting either into
the other. Time is never priced. An hourly rate is the one assumption that would
turn every finding here into whatever number the author needed, and no figure in
this module depends on one.

A failing arm is recorded, not raised. An upstream that goes down mid-experiment
is a fact about hiring that agent, and a harness that threw it away would report
only the runs that happened to succeed.

Hashes come from `hire.receipts.canonical_hash` — the same function, and so the
same recipe, that binds a hire receipt to its delivery. A reader who can check
one can check the other without learning a second procedure.
"""

import json
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path

from ..hire.receipts import canonical_hash


@dataclass
class Experiment:
    """Both arms of one task, plus what a reader needs to repeat the manual one.

    `manual_steps` is not documentation. A manual arm nobody can reproduce is an
    unfalsifiable baseline, and an unfalsifiable baseline is how these reports
    become worthless. `notes` is where an honest loss goes.
    """

    task_id: str
    question: str
    category: str
    agent_arm: dict
    manual_arm: dict
    manual_steps: list[str]
    notes: str


def record_arm(name: str, fn: Callable[[], object], *, cost: dict | None = None) -> dict:
    """Run one arm, time it, hash what it returned.

    The hash is computed after the clock stops: bookkeeping is not part of the work
    being measured. `cost` is the caller's own triple, passed through untouched,
    because only the caller knows whether an arm spent a hire, gas, or nothing.
    """
    output = None
    error = None
    started = time.monotonic()
    try:
        output = fn()
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
    seconds = time.monotonic() - started
    return {
        "name": name,
        "seconds": seconds,
        "output": output,
        "output_hash": None if error else canonical_hash(output),
        "cost": cost,
        "error": error,
    }


def compare(experiment: Experiment) -> dict:
    """The factual deltas between the two arms, and nothing that reads as a verdict.

    `speedup` is `None` whenever it cannot be divided — an arm that was never timed
    has no ratio, and a zero would be a number this harness made up.
    """
    seconds_agent = experiment.agent_arm.get("seconds")
    seconds_manual = experiment.manual_arm.get("seconds")
    return {
        "seconds_agent": seconds_agent,
        "seconds_manual": seconds_manual,
        "cost_agent": experiment.agent_arm.get("cost"),
        "cost_manual": experiment.manual_arm.get("cost"),
        "speedup": (
            None
            if not seconds_agent or seconds_manual is None
            else round(seconds_manual / seconds_agent, 2)
        ),
    }


def save(experiment: Experiment, path) -> None:
    """Write the experiment as sorted, indented JSON with LF endings.

    Deterministic on purpose: a committed experiment that reformatted itself on every
    read would produce diffs that hide whether the evidence changed.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    blob = json.dumps(asdict(experiment), sort_keys=True, indent=2, ensure_ascii=False)
    path.write_text(blob + "\n", encoding="utf-8", newline="\n")


def load(path) -> Experiment:
    """A file missing a field raises rather than defaulting: a half-read experiment
    would be reported as a whole one."""
    return Experiment(**json.loads(Path(path).read_text(encoding="utf-8")))
