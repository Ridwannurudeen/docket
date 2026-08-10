"""What a set of trials has to keep, and what it must refuse to summarise away.

Every test here is the same failure approached from a different side: a run record that
flatters the runs behind it. Either a failed trial is dropped, or a retry is counted as an
extra observation, or a spread is quoted over a denominator that is not the trial list a
reader can see.

Nothing here touches a network. The arms are local functions that raise or return on
demand, and `sleep` is injected wherever the retry path is exercised, so a retry test costs
nothing. There is one deliberate exception, and it is named where it happens: a single test
injects a real 100ms sleep, because whether a trial's recorded seconds cover its backoff
waits cannot be asserted without a wait that actually takes time.
"""

import json
import statistics
import time

import pytest

from docket.advantage.v2.spec import TaskSpec
from docket.advantage.v2.trials import run_trials, save
from docket.hire.receipts import canonical_hash

MANUAL_NULL = {
    "name": "manual",
    "what_it_does": "A person opens the wallet on BscScan and reads each position's range.",
    "why_it_is_the_right_null": "It is what somebody does today without hiring the agent.",
}
EMPTY_WALLET_NULL = {
    "name": "empty-wallet",
    "what_it_does": "The same agent run against a wallet that holds no v3 positions.",
    "why_it_is_the_right_null": (
        "It separates reading the chain from restating the question back at the caller."
    ),
}


def _spec(**overrides) -> TaskSpec:
    fields = {
        "spec_id": "v2-01-liquidity",
        "question": "Is this wallet earning fees on its v3 positions right now?",
        "category": "yield",
        "claim": "The agent arm answers in fewer seconds than the manual arm.",
        "metric": {
            "name": "seconds_to_answer",
            "formula": "monotonic clock at the answer minus monotonic clock at the start",
            "units": "seconds",
        },
        "null_baselines": (MANUAL_NULL, EMPTY_WALLET_NULL),
        "dataset_ref": "docket/advantage/v2/datasets/01-liquidity.json",
        "dataset_sha256": "9f" * 32,
        "n_planned": 10,
        "stopping_rule": "Ten runs per arm, whatever the interim numbers say.",
        "falsifier": "The agent arm's median is at or above the manual arm's median.",
        "registered_at": "2026-08-22T00:00:00+00:00",
    }
    return TaskSpec(**(fields | overrides))


def _no_sleep(seconds: float) -> None:
    """A trial runner that really slept would make its own retry tests cost seconds."""


def test_a_failing_arm_is_kept_with_its_error_and_counted_in_the_denominator():
    """An upstream that goes down mid-experiment is a fact about hiring that agent. A
    runner that dropped the trial would publish the ones that happened to work, over a
    denominator that no longer says how many were attempted."""
    calls = []

    def flaky():
        calls.append(1)
        if len(calls) == 2:
            raise RuntimeError("upstream said no")
        return {"ok": len(calls)}

    trial_set = run_trials(_spec(), flaky, "agent", n=3, sleep=_no_sleep)
    summary = trial_set.summary()

    assert [trial["index"] for trial in trial_set.trials] == [0, 1, 2]
    failed = trial_set.trials[1]
    assert failed["error"] == "RuntimeError: upstream said no"
    assert failed["output"] is None
    assert failed["output_hash"] is None
    assert failed["attempts"] == 1
    assert trial_set.trials[0]["output_hash"] == canonical_hash({"ok": 1})
    assert summary["n_run"] == 3
    assert summary["n_succeeded"] == 2
    assert summary["n_failed"] == 1


def test_a_trial_that_retried_twice_and_then_returned_is_one_trial_not_three():
    """Retry is per attempt, not per trial. Counting each attempt as its own observation
    would let a flaky network inflate n, and the inflation would land entirely on whichever
    arm was hardest to reach — the one the count is supposed to be evidence about."""
    waits = []
    calls = []

    def flaky():
        calls.append(1)
        if len(calls) < 3:
            raise ConnectionError("getaddrinfo failed")
        return "answered"

    trial_set = run_trials(_spec(), flaky, "agent", n=1, retry=2, sleep=waits.append)
    trial = trial_set.trials[0]

    assert len(trial_set.trials) == 1
    assert trial["attempts"] == 3
    assert trial["error"] is None
    assert trial["output"] == "answered"
    assert trial["output_hash"] == canonical_hash("answered")
    assert waits == [1.0, 3.0]
    assert trial_set.summary()["n_run"] == 1
    assert trial_set.summary()["n_succeeded"] == 1


def test_a_trial_that_exhausts_its_retries_keeps_the_last_attempts_error():
    """The error a reader needs is the one the trial gave up on. Keeping the first would
    name an attempt the runner went on past, and the trial would read as having failed for
    a reason it had already recovered from once.

    This is also the only shape that reaches the "no wait after the final attempt" guard:
    a trial that succeeds breaks out before it, so `waits` is captured here. A runner that
    slept after giving up would add a spurious 8s to every failed trial's recorded seconds,
    against an endpoint it had already stopped calling."""
    waits = []
    calls = []

    def always_fails():
        calls.append(1)
        raise ConnectionError(f"attempt {len(calls)} failed")

    trial_set = run_trials(_spec(), always_fails, "agent", n=1, retry=2, sleep=waits.append)
    trial = trial_set.trials[0]

    assert trial["attempts"] == 3
    assert trial["error"] == "ConnectionError: attempt 3 failed"
    assert waits == [1.0, 3.0]
    assert trial_set.summary()["n_run"] == 1
    assert trial_set.summary()["n_failed"] == 1


def test_the_backoff_clamps_to_its_last_value_rather_than_running_off_the_end():
    """`BACKOFF_S` names three waits and a caller may ask for more attempts than that.
    Indexing it directly would raise `IndexError` inside the runner on the fourth wait,
    turning a retry budget the caller chose into a crash — and losing the trial it was in
    the middle of retrying, which is the one outcome this module exists to retain."""
    waits = []

    def always_fails():
        raise ConnectionError("getaddrinfo failed")

    trial_set = run_trials(_spec(), always_fails, "agent", n=1, retry=4, sleep=waits.append)

    assert trial_set.trials[0]["attempts"] == 5
    assert waits == [1.0, 3.0, 8.0, 8.0]


def test_a_trials_seconds_cover_its_backoff_waits_and_not_only_its_attempts():
    """The recorded cost of an observation is what it took to obtain, waits included. A
    runner that clocked only the attempts would report a trial that spent eleven seconds
    backing off as having taken milliseconds, and the arm that was hardest to reach would
    read as the cheapest one to hire.

    The only test here that really sleeps, and it has to: with the clock uninjected on
    purpose, a wait that takes no time cannot be told from one that is excluded. Two 100ms
    waits fall inside the window; the threshold is 0.15 rather than 0.2 because
    `time.monotonic` on this host has a 15.6ms resolution."""

    def always_fails():
        raise ConnectionError("getaddrinfo failed")

    trial_set = run_trials(
        _spec(), always_fails, "agent", n=1, retry=2, sleep=lambda seconds: time.sleep(0.1)
    )

    assert trial_set.trials[0]["attempts"] == 3
    assert trial_set.trials[0]["seconds"] >= 0.15


def test_the_summarys_denominators_match_the_trial_list_exactly():
    """The aggregate is worth reading only if it counts the same runs the reader can see.
    Each figure is recomputed here from `.trials` rather than trusted, because a denominator
    that drifted from its list is how a rate stops meaning anything while still looking
    exactly like one. The key set is pinned too: a seventh figure appearing in the summary
    is a figure nothing in this file would have checked against the runs."""
    calls = []

    def every_other():
        calls.append(1)
        if len(calls) % 2:
            raise TimeoutError("timed out")
        return len(calls)

    trial_set = run_trials(_spec(), every_other, "agent", n=5, sleep=_no_sleep)
    summary = trial_set.summary()
    returned = [trial["seconds"] for trial in trial_set.trials if trial["error"] is None]

    assert set(summary) == {
        "n_planned",
        "n_run",
        "n_succeeded",
        "n_failed",
        "seconds",
        "method",
    }
    assert set(summary["seconds"]) == {"min", "median", "max"}
    assert summary["n_run"] == len(trial_set.trials) == 5
    assert summary["n_succeeded"] == len(returned) == 2
    assert summary["n_failed"] == len(trial_set.trials) - len(returned) == 3
    assert summary["n_succeeded"] + summary["n_failed"] == summary["n_run"]
    assert summary["seconds"]["min"] == min(returned)
    assert summary["seconds"]["median"] == statistics.median(returned)
    assert summary["seconds"]["max"] == max(returned)


def test_the_method_states_what_was_retained_and_what_the_seconds_cover():
    """A timing whose method is unstated cannot be read, and this one is computed over a
    subset — the trials that returned. A reader who did not know that would take the median
    for the median of the set, which is the flattering half of it."""
    calls = []

    def every_other():
        calls.append(1)
        if len(calls) % 2:
            raise TimeoutError("timed out")
        return len(calls)

    method = run_trials(_spec(), every_other, "agent", n=4, sleep=_no_sleep).summary()["method"]

    assert "Every trial is retained and counted" in method
    assert "2 of 4 ended in an error" in method
    assert "Retries collapse into the trial that made them" in method
    assert "over the 2 trials that returned" in method


def test_the_run_record_cites_the_spec_it_was_registered_against():
    """Every run record carries the spec's hash. Without it the runs describe an experiment
    whose metric, n and falsifier could have been settled once the results were visible, and
    nothing in the record would show that they had been."""
    spec = _spec()

    trial_set = run_trials(spec, lambda: "ok", "agent", n=2, sleep=_no_sleep)
    record = trial_set.as_record()

    assert trial_set.spec_hash == spec.spec_hash
    assert trial_set.spec_id == spec.spec_id
    assert record["spec_hash"] == spec.spec_hash
    assert record["spec_id"] == spec.spec_id
    assert record["arm_name"] == "agent"


def test_n_planned_is_the_pre_registered_number_not_the_n_that_was_run():
    """The two are reported side by side and never reconciled. A run that stopped short of
    its plan is exactly what a reader needs to see, and a record that copied `n` into
    `n_planned` would show a plan that had been met by definition."""
    trial_set = run_trials(_spec(n_planned=10), lambda: "ok", "agent", n=3, sleep=_no_sleep)
    summary = trial_set.summary()

    assert trial_set.n_planned == 10
    assert summary["n_planned"] == 10
    assert summary["n_run"] == 3


def test_a_set_where_nothing_returned_summarises_without_dividing_by_zero():
    """An arm whose upstream was down for the whole window is a result, not a gap. The
    spread over zero observations is null rather than zero — `statistics.median([])` raises
    and a zero would publish a timing nobody measured — and every trial is still there."""

    def down():
        raise ConnectionError("getaddrinfo failed")

    trial_set = run_trials(_spec(), down, "agent", n=3, retry=1, sleep=_no_sleep)
    summary = trial_set.summary()

    assert summary["n_run"] == 3
    assert summary["n_succeeded"] == 0
    assert summary["n_failed"] == 3
    assert summary["seconds"] == {"min": None, "median": None, "max": None}
    assert [trial["attempts"] for trial in trial_set.trials] == [2, 2, 2]
    assert len(trial_set.as_record()["trials"]) == 3


def test_as_record_carries_every_trial_beside_the_summary():
    """`as_record` and `save` are the only two ways out of this module, and both carry the
    runs beside the aggregate. That is what stops a Docket run record from publishing a
    median with no distribution under it — a claim a reader has no way to contest."""
    trial_set = run_trials(_spec(), lambda: "ok", "agent", n=4, sleep=_no_sleep)
    record = trial_set.as_record()

    assert set(record) == {"spec_id", "spec_hash", "arm_name", "summary", "trials"}
    assert len(record["trials"]) == record["summary"]["n_run"] == 4
    assert [trial["index"] for trial in record["trials"]] == [0, 1, 2, 3]
    assert set(record["trials"][0]) == {
        "index",
        "seconds",
        "output",
        "output_hash",
        "error",
        "attempts",
    }


def test_asking_for_fewer_than_one_trial_raises():
    """A set with no trials would summarise to a denominator of zero while still citing the
    spec it was registered against — a record of an experiment that never ran, wearing the
    shape of one that did."""
    with pytest.raises(ValueError, match="n is 0"):
        run_trials(_spec(), lambda: "ok", "agent", n=0)
    with pytest.raises(ValueError, match="n is -1"):
        run_trials(_spec(), lambda: "ok", "agent", n=-1)


def test_a_negative_retry_raises_rather_than_recording_a_trial_that_never_ran():
    """`range(retry + 1)` is empty at -1, so the attempt loop would not run — and the trial
    would still be appended, with no error, `attempts: 0`, and an output hash standing for a
    value nobody obtained. `summary()` classifies on `error is None`, so it would count
    toward `n_succeeded` and its near-zero seconds would enter the spread. A negative retry
    is not a smaller budget of attempts; it is a manufactured observation."""
    with pytest.raises(ValueError, match="retry is -1"):
        run_trials(_spec(), lambda: "ok", "agent", n=2, retry=-1)


def test_a_saved_run_record_carries_its_trials_and_writes_lf_endings(tmp_path):
    """The file is what a reader is served. Same recipe as `spec.save` and `harness.save`,
    so a committed record read and rewritten produces no diff, and a CRLF picked up from the
    host cannot change the bytes without changing a word."""
    trial_set = run_trials(_spec(), lambda: "ok", "agent", n=2, sleep=_no_sleep)
    path = tmp_path / "runs" / "01-agent.json"

    save(trial_set, path)
    record = json.loads(path.read_text(encoding="utf-8"))

    assert record == trial_set.as_record()
    assert len(record["trials"]) == 2
    assert record["summary"]["n_run"] == 2
    assert b"\r\n" not in path.read_bytes()
    assert path.read_bytes().endswith(b"\n")
