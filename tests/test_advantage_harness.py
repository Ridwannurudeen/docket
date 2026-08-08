"""What the harness must not do: lose an arm, invent a number, or grade itself."""

import json
import time

from docket.advantage.harness import Experiment, compare, load, record_arm, save
from docket.api.models import BANNED_FIELD_NAMES
from docket.hire.receipts import canonical_hash

PAID = {"amount": "0.01", "unit": "$U", "note": "one hire at the catalogue price"}
FREE = {"amount": "0", "unit": "$U", "note": "public endpoints only"}
# Field names Docket already refuses, plus the words a comparison reaches for when it
# starts arguing instead of measuring. Nothing containing "speed": the ratio is a fact.
VERDICT_WORDS = BANNED_FIELD_NAMES | {
    "better",
    "worse",
    "winner",
    "wins",
    "superior",
    "proves",
    "advantage",
    "quality",
}


def _experiment(agent_seconds, manual_seconds) -> Experiment:
    output = {"positions_in_range": 2}
    return Experiment(
        task_id="01-liquidity",
        question="Is this wallet earning fees on its v3 positions right now?",
        category="yield",
        agent_arm={
            "name": "agent",
            "seconds": agent_seconds,
            "output": output,
            "output_hash": canonical_hash(output),
            "cost": PAID,
            "error": None,
        },
        manual_arm={
            "name": "manual",
            "seconds": manual_seconds,
            "output": output,
            "output_hash": canonical_hash(output),
            "cost": FREE,
            "error": None,
        },
        manual_steps=["Open the wallet on BscScan", "Read each position's range"],
        notes="The manual arm did not compute the protocol fee split.",
    )


def test_record_arm_times_the_work_and_hashes_what_came_back():
    """The hash is the one thing a reader can check alone, so it is computed the same
    way a hire receipt's is — same function, same recipe."""
    result = {"regime": "risk-off"}

    def work():
        time.sleep(0.02)
        return result

    arm = record_arm("agent", work, cost=PAID)

    assert arm["name"] == "agent"
    assert arm["seconds"] >= 0.01
    assert arm["output"] == result
    assert arm["output_hash"] == canonical_hash(result)
    assert arm["output_hash"].startswith("0x")
    assert arm["cost"] == PAID
    assert arm["error"] is None


def test_a_lost_arm_is_recorded_rather_than_raised():
    """An arm that fails is a finding about the task. Raising here would delete it."""

    def boom():
        raise RuntimeError("upstream said no")

    arm = record_arm("agent", boom, cost=FREE)

    assert arm["error"] == "RuntimeError: upstream said no"
    assert arm["output"] is None
    assert arm["output_hash"] is None
    assert arm["seconds"] >= 0


def test_compare_states_the_speedup_as_manual_over_agent():
    deltas = compare(_experiment(12.0, 60.0))

    assert deltas["seconds_agent"] == 12.0
    assert deltas["seconds_manual"] == 60.0
    assert deltas["cost_agent"] == PAID
    assert deltas["cost_manual"] == FREE
    assert deltas["speedup"] == 5.0


def test_compare_invents_no_speedup_when_a_timing_is_missing():
    """An arm that was never timed has no ratio. A zero is not a stand-in for one."""
    assert compare(_experiment(12.0, None))["speedup"] is None
    assert compare(_experiment(None, 60.0))["speedup"] is None
    assert compare(_experiment(0.0, 60.0))["speedup"] is None


def test_compare_reports_deltas_and_passes_no_judgement():
    deltas = compare(_experiment(12.0, 60.0))

    assert set(deltas) == {
        "seconds_agent",
        "seconds_manual",
        "cost_agent",
        "cost_manual",
        "speedup",
    }
    blob = json.dumps(deltas).lower()
    for word in VERDICT_WORDS:
        assert word not in blob, f"compare() grades the arms: {word}"


def test_a_saved_experiment_round_trips_byte_identically(tmp_path):
    """A committed experiment is evidence; reading and rewriting it must not edit it."""
    original = _experiment(12.0, 60.0)
    first, second = tmp_path / "01.json", tmp_path / "02.json"

    save(original, first)
    reloaded = load(first)
    save(reloaded, second)

    assert reloaded == original
    assert first.read_bytes() == second.read_bytes()
