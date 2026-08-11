"""One arm, run n times, with every outcome kept — including the ones that raised.

v1 runs each arm once. A single observation carries no spread, so a reader cannot tell a
timing that would repeat from one that happened to land on a quiet minute, and there is
nothing for a second run to disagree with. The spec beside this module fixes n before any
of it is run; this is the half that runs it.

The failures are the point. A corpus run against a live endpoint loses trials to DNS and
to 502s, and a runner that dropped those would publish only the trials that happened to
work, over a denominator that no longer says how many were attempted. So an exception from
the arm is caught into that trial's `error` and the trial keeps its index and its place in
the count. Nothing here re-runs a trial until it passes.

Retries are per attempt, not per trial, and that distinction is what stops a flaky network
from inflating n. A call that failed twice and then returned is one observation that took
three attempts to obtain, not three observations. The attempt count travels in the record
so a reader can see which trials came easily, and the trial's seconds cover the whole
sequence — every attempt and every wait between them — because that is what obtaining that
one observation actually cost.

The summary travels with the runs wherever it leaves here as a record. `summary()` is
public, so a caller can serialise its return on its own and nothing stops that; what this
module will not do is *produce a record* shaped that way. `as_record` and `save` are the
only two ways out, and both carry the trials beside the aggregate — a published median with
no distribution under it is a figure a reader has no way to contest. The spread is computed
over the trials that returned, with the count it was computed over stated in the same
breath, and where nothing returned it is null rather than zero.

Timing and hashing follow `harness.record_arm` exactly: the clock stops before
`canonical_hash` runs, because bookkeeping is not part of the work being measured.
"""

import json
import statistics
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from ...hire.receipts import canonical_hash
from .spec import TaskSpec

# The repo's retry shape, restated rather than imported: `agents.pancake.pools` owns these
# numbers for an HTTP client and brings httpx along with them, and a trial runner that
# reached across for a constant would tie the advantage module to an agent's dependencies.
BACKOFF_S = (1.0, 3.0, 8.0)


@dataclass(frozen=True)
class TrialSet:
    """Every trial of one arm, and the pre-registration they were run against.

    `n_planned` is the spec's number and `n_run` is `len(trials)`. They are reported
    separately and never reconciled: a run that stopped short of its plan, or overran it,
    is exactly what a reader needs to see, and a record that carried only one of them
    would show a plan met by definition.

    This record does not copy what it holds, where its sibling `spec.py` deep-copies on the
    way in — a deliberate divergence, not an omission. A spec's dicts arrive from a caller
    who still holds them and its digest is what every run record cites, so a write through
    a kept reference would move a hash other files quote. Trial dicts are built here by
    `run_trials`, no caller holds one at construction, and nothing hashes this record. What
    follows from that is worth stating: `.trials` hands out live references, so a caller
    that writes through one does move what `summary()` goes on to report.
    """

    spec_id: str
    spec_hash: str
    arm_name: str
    n_planned: int
    trials: tuple[dict, ...]

    def summary(self) -> dict:
        """The counts, and the spread over the trials that returned.

        Failures are counted but not timed. A trial that spent its whole retry budget
        before giving up took real seconds, and folding those into the spread would
        describe the cost of failing rather than the cost of the work — so `seconds` is
        computed over the succeeded trials only, and `method` says so with the count it
        was computed over beside it.
        """
        returned = [trial["seconds"] for trial in self.trials if trial["error"] is None]
        n_run = len(self.trials)
        n_succeeded = len(returned)
        n_failed = n_run - n_succeeded
        return {
            "n_planned": self.n_planned,
            "n_run": n_run,
            "n_succeeded": n_succeeded,
            "n_failed": n_failed,
            # An empty list has no minimum and no middle. `statistics.median` raises on
            # one, and a zero substituted for it would publish a timing nobody measured.
            "seconds": {
                "min": min(returned) if returned else None,
                "median": statistics.median(returned) if returned else None,
                "max": max(returned) if returned else None,
            },
            "method": (
                f"{n_run} trials were run against a spec that planned {self.n_planned}. "
                f"Every trial is retained and counted, failures included: {n_failed} of "
                f"{n_run} ended in an error, and a failed trial keeps its place in the "
                "denominator rather than being re-run until it passes. Retries collapse "
                "into the trial that made them — a call that failed twice and then "
                "returned is one trial carrying three attempts, not three trials — and "
                "each trial's seconds cover its whole attempt sequence, the waits between "
                "attempts included. The min, median and max seconds are computed over the "
                f"{n_succeeded} trials that returned rather than over all {n_run}; where "
                "nothing returned they are null rather than zero, because zero is a timing "
                "nobody observed."
            ),
        }

    def as_record(self) -> dict:
        """The summary and the runs behind it, together, because there is no other way out.

        The rule is that any caller may read the aggregate only alongside the runs it came
        from, and it is worth being exact about how far this goes. `summary()` is public and
        a caller can serialise its return on its own; what this module will not do is
        *produce a record* shaped that way. `as_record` and `save` are the only two ways out
        of here, and both carry the trials beside the aggregate — so an aggregate that
        arrives as a Docket run record arrives with the distribution under it. A published
        median without one is a claim a reader has no way to contest.
        """
        return {
            "spec_id": self.spec_id,
            "spec_hash": self.spec_hash,
            "arm_name": self.arm_name,
            "summary": self.summary(),
            "trials": [dict(trial) for trial in self.trials],
        }


def run_trials(
    spec: TaskSpec,
    arm_fn: Callable[[], object],
    arm_name: str,
    *,
    n: int,
    retry: int = 0,
    backoff: tuple[float, ...] = BACKOFF_S,
    sleep: Callable[[float], None] = time.sleep,
) -> TrialSet:
    """Run one arm n times and keep every outcome, the ones that raised included.

    `retry` counts the attempts *after* the first, so a trial makes at most `retry + 1` of
    them and `retry=0` is a single attempt. Each trial's `seconds` is the elapsed time for
    the whole trial — every attempt it made and every backoff wait between them — because
    that is the honest cost of getting that one observation, and a figure that timed only
    the attempt which finally worked would describe a run nobody had.

    An exception from `arm_fn` is data, not an error condition: it is caught into that
    trial's `error`, and the trial keeps its index and its place in the count. The only
    things this function raises for are `n < 1` and a negative `retry` — neither is a
    failed experiment, and both would produce a record of runs that did not happen.

    `sleep` exists so a test can exercise the retry path without waiting on it. It is the
    only thing injected here — the clock is not, so a recorded timing is always a real one.
    """
    if n < 1 or retry < 0:
        raise ValueError(
            f"run_trials: n is {n} and retry is {retry} — a set of fewer than one trial "
            "would summarise to a denominator of zero while still citing the spec it was "
            "registered against, and a negative retry is not a smaller budget of attempts "
            "but a trial that never runs: it empties the attempt loop, and the trial is "
            "appended anyway with no error and an output hash for a value nobody obtained"
        )
    trials = []
    for index in range(n):
        output = None
        error = None
        started = time.monotonic()
        for attempt in range(retry + 1):
            attempts = attempt + 1
            try:
                output = arm_fn()
                # Cleared rather than left: a trial that failed twice and then returned is
                # a trial that returned, and the earlier attempts are told by `attempts`.
                error = None
                break
            except Exception as exc:
                error = f"{type(exc).__name__}: {exc}"
            if attempt < retry:
                sleep(backoff[min(attempt, len(backoff) - 1)])
        seconds = time.monotonic() - started
        trials.append(
            {
                "index": index,
                "seconds": seconds,
                "output": output,
                "output_hash": None if error else canonical_hash(output),
                "error": error,
                "attempts": attempts,
            }
        )
    return TrialSet(
        spec_id=spec.spec_id,
        spec_hash=spec.spec_hash,
        arm_name=arm_name,
        n_planned=spec.n_planned,
        trials=tuple(trials),
    )


def save(trial_set: TrialSet, path) -> None:
    """Write the trials, and the summary over them, as sorted indented JSON with LF endings.

    The same recipe as `spec.save` and `harness.save`, for the same reason: a committed run
    record that reformatted itself on every read would produce diffs that hide whether the
    evidence changed. It writes `as_record()`, so the runs cannot be separated from the
    aggregate on the way to disk either.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    blob = json.dumps(trial_set.as_record(), sort_keys=True, indent=2, ensure_ascii=False)
    path.write_text(blob + "\n", encoding="utf-8", newline="\n")
