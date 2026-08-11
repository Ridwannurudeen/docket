"""What a pre-registration must refuse to register, and what its hash has to survive.

Every one of these tests exists to stop the same failure from a different side: a spec
edited after the runs came in. Either the record refuses the field that would make it
unfalsifiable, or the digest moves when the record does. Nothing here touches a network
or a clock — a spec is text, and its hash has to be the same wherever it is rebuilt.
"""

import json

import pytest

from docket.advantage.v2.spec import TaskSpec, load, save
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


def test_a_spec_with_one_null_baseline_raises_rather_than_registering():
    """One null shows the arm did something. It cannot show that what it did was the
    mechanism the claim names rather than the setup around it, so a spec that offers
    only one would license a conclusion its own design could not reach."""
    with pytest.raises(ValueError, match="null baselines"):
        _spec(null_baselines=(MANUAL_NULL,))


def test_a_null_baseline_missing_the_argument_for_its_choice_raises():
    """A null nobody can run, or whose choice is never argued, is a baseline picked
    after the fact. The three keys are the whole defence against that."""
    with pytest.raises(ValueError, match="why_it_is_the_right_null"):
        _spec(
            null_baselines=(
                MANUAL_NULL,
                {"name": "empty-wallet", "what_it_does": "A wallet with no positions."},
            )
        )
    with pytest.raises(ValueError, match="what_it_does"):
        _spec(
            null_baselines=(
                MANUAL_NULL,
                {"name": "empty-wallet", "why_it_is_the_right_null": "It shares the setup."},
            )
        )


def test_a_null_baseline_whose_fields_are_present_but_blank_raises():
    """Three empty strings satisfy a presence check and describe nothing. Two rows of
    them would meet the two-null count with no null stated at all, which is the shape
    the count exists to refuse."""
    blank = {"name": "", "what_it_does": "", "why_it_is_the_right_null": ""}
    with pytest.raises(ValueError, match="what_it_does"):
        _spec(null_baselines=(blank, dict(blank)))
    with pytest.raises(ValueError, match="why_it_is_the_right_null"):
        _spec(null_baselines=(MANUAL_NULL, EMPTY_WALLET_NULL | {"why_it_is_the_right_null": "  "}))


def test_the_same_null_listed_twice_raises():
    """Two rows naming one null is one null. It clears the count while leaving the
    second comparison — the one that separates the mechanism from the setup — unmade."""
    with pytest.raises(ValueError, match="distinct"):
        _spec(null_baselines=(MANUAL_NULL, dict(MANUAL_NULL)))


def test_an_empty_falsifier_raises():
    """A claim that names no result which would refute it is not a claim. Registering
    one would mean no number of runs could ever settle it, and every run that came in
    would read as support."""
    with pytest.raises(ValueError, match="falsifier"):
        _spec(falsifier="")
    with pytest.raises(ValueError, match="falsifier"):
        _spec(falsifier="   ")


def test_a_spec_planning_a_single_run_per_arm_raises():
    """One run per arm is what v1 already records. A single trial carries no spread to
    report next to its number, so the plan has to name at least two."""
    with pytest.raises(ValueError, match="n_planned"):
        _spec(n_planned=1)


def test_two_planned_runs_is_the_smallest_plan_that_registers():
    """The floor is where an off-by-one hides. A rule written `<= 2` would refuse the
    smallest plan a spec is allowed to make, and no other test here would notice."""
    assert _spec(n_planned=2).n_planned == 2


def test_a_metric_without_a_written_out_formula_raises():
    """A metric named but not written out can be recomputed a different way once the
    runs are in, and both recipes will answer to the same name in the report."""
    with pytest.raises(ValueError, match="formula"):
        _spec(metric={"name": "seconds_to_answer", "units": "seconds"})
    with pytest.raises(ValueError, match="formula"):
        _spec(metric={"name": "seconds_to_answer", "formula": "  ", "units": "seconds"})


def test_a_blank_claim_raises():
    """The claim is the one sentence the runs are evidence for. Without it the spec
    freezes a procedure and leaves what it was testing to be written afterwards."""
    with pytest.raises(ValueError, match="claim"):
        _spec(claim="   ")


def test_a_spec_naming_no_dataset_digest_raises():
    """A dataset identified by path alone is whatever that path holds on the day
    somebody reads it, so the runs could not be checked against the inputs they were
    registered against."""
    with pytest.raises(ValueError, match="dataset_sha256"):
        _spec(dataset_sha256="")


def test_the_spec_hash_is_the_same_before_and_after_a_save_and_load(tmp_path):
    """A run record cites its spec by hash. If the digest moved on the trip through
    JSON — where `null_baselines` becomes a list and has to come back a tuple — every
    citation would dangle the moment the spec was read back off disk."""
    original = _spec()
    path = tmp_path / "01.json"

    save(original, path)
    reloaded = load(path)

    assert reloaded.spec_hash == original.spec_hash
    assert reloaded == original
    assert isinstance(reloaded.null_baselines, tuple)


def test_mutating_the_dicts_the_caller_still_holds_does_not_move_the_hash():
    """`frozen=True` stops the fields being rebound, not the dicts behind them being
    written through a reference the caller kept. A digest that moved when a caller's
    dict did would leave every citation of the earlier one pointing at nothing — the
    failure freezing the record was chosen to prevent — and would leave the spec in a
    state construction refuses, since `__post_init__` does not run a second time."""
    metric = dict(_spec().metric)
    baseline = dict(MANUAL_NULL)
    spec = _spec(metric=metric, null_baselines=(baseline, EMPTY_WALLET_NULL))
    registered = spec.spec_hash

    metric["formula"] = ""
    baseline["why_it_is_the_right_null"] = "picked once the runs were in"

    assert spec.spec_hash == registered
    assert spec.metric["formula"] == _spec().metric["formula"]
    assert spec.null_baselines[0] == MANUAL_NULL


def test_two_specs_differing_in_one_character_hash_differently():
    """The digest is what pins the pre-registration to the runs that cite it. One that
    survived an edited claim would let the claim be rewritten after the results."""
    original = _spec()
    edited = _spec(claim=original.claim.replace("fewer", "Fewer"))

    assert edited.claim != original.claim
    assert edited.spec_hash != original.spec_hash


def test_a_saved_spec_carries_the_hash_a_reader_recomputes_from_the_file_alone(tmp_path):
    """The file has to be checkable by somebody holding nothing else. So it carries its
    own digest, and that digest is `canonical_hash` over the rest of the file exactly as
    written — the same recipe that binds a hire receipt to its delivery."""
    spec = _spec()
    path = tmp_path / "01.json"

    save(spec, path)
    record = json.loads(path.read_text(encoding="utf-8"))

    assert record["spec_hash"] == spec.spec_hash
    assert record["spec_hash"].startswith("0x")
    body = {key: value for key, value in record.items() if key != "spec_hash"}
    assert canonical_hash(body) == record["spec_hash"]
    assert load(path).spec_hash == record["spec_hash"]


def test_load_raises_when_the_file_was_edited_after_it_was_registered(tmp_path):
    """The digest travels inside the file so the two cannot be separated, and `load` is
    the one place that is worth anything. A spec edited on disk that came back with a
    freshly computed hash would leave the citation in a run record as the only trace,
    and nobody reads a run record to find out whether the spec moved."""
    path = tmp_path / "01.json"
    save(_spec(), path)

    registered = path.read_text(encoding="utf-8")
    edited = registered.replace("fewer seconds", "Fewer seconds")
    assert edited != registered, "the edit under test did not change the file"
    path.write_text(edited, encoding="utf-8", newline="\n")

    with pytest.raises(ValueError, match="spec_hash"):
        load(path)


def test_a_saved_spec_round_trips_byte_identically_with_lf_endings(tmp_path):
    """A committed spec is the frozen half of the evidence. Reading and rewriting it
    must not edit it, and a CRLF picked up from the host would change the bytes without
    changing a word."""
    original = _spec()
    first, second = tmp_path / "01.json", tmp_path / "02.json"

    save(original, first)
    save(load(first), second)

    assert first.read_bytes() == second.read_bytes()
    assert b"\r\n" not in first.read_bytes()
    assert first.read_bytes().endswith(b"\n")
