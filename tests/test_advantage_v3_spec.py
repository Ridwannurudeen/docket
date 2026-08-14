"""The registration half of v3, and the refusals that make it worth registering.

v1 is the only report in this build that pairs an agent arm against a human one, and it is
three single pairs whose framing was settled with the results visible. v2 pre-registers
properly and compares against nulls, so it is not the paired report the sponsor's gate asks
for — `docket/advantage/v2/report.py` says so in its own words. v3 is the pairing, run the
way v2 taught us to run things, and these tests hold the parts a reader has to be able to
check.
"""

import json
from pathlib import Path

import pytest

from docket.advantage.v3.spec import PairedSpec, assert_runnable, load, save

SPECS_DIR = (
    Path(__file__).resolve().parents[1] / "docket" / "advantage" / "v3" / "specs"
)
REGISTERED = sorted(SPECS_DIR.glob("*.json"))


def _valid(**overrides) -> dict:
    body = {
        "spec_id": "t",
        "question": "q?",
        "category": "yield/LP",
        "claim": "the hired arm scores no lower and takes less time",
        "falsifier": "a lower median rubric total refutes the quality limb",
        "arms": {
            arm: {
                "what_it_does": "does the thing",
                "who_runs_it": "somebody",
                "what_is_recorded": "seconds, cost, output",
            }
            for arm in ("agent", "manual")
        },
        "case_selection": {"rule": "five live positions spanning the states"},
        "quality_rubric": {
            "scale": "0-3",
            "criteria": [
                {"name": "a", "full_marks_means": "all", "zero_means": "none"},
                {"name": "b", "full_marks_means": "all", "zero_means": "none"},
            ],
        },
        "scoring": {
            "evaluators": 2,
            "blinded": True,
            "disagreement": "published, not resolved",
        },
        "measures": {"time": "wall clock", "cost": "out of pocket only"},
        "n_planned": 5,
        "stopping_rule": "every frozen case once per arm",
        "registered_at": "2026-08-14T00:00:00+00:00",
        "inputs_ref": "docket/advantage/v3/inputs/x.json",
    }
    return body | overrides


# ------------------------------------------------------------------ the refusals


def test_a_spec_must_compare_an_agent_against_a_human():
    """The gate asks for both ways. v2's arms are nulls, which is why it cannot be this."""
    with pytest.raises(ValueError, match="arms are"):
        PairedSpec(**_valid(arms={"agent": {}, "keyword_null": {}}))


def test_an_arm_nobody_can_rerun_is_refused():
    thin = {"agent": {"what_it_does": "", "who_runs_it": "", "what_is_recorded": ""}}
    with pytest.raises(ValueError, match="the agent arm leaves"):
        PairedSpec(**_valid(arms=_valid()["arms"] | thin))


def test_one_pair_per_task_is_refused_because_that_is_v1():
    with pytest.raises(ValueError, match="fewer than 3"):
        PairedSpec(**_valid(n_planned=1))


def test_a_rubric_with_one_criterion_or_no_anchors_is_refused():
    with pytest.raises(ValueError, match="fewer than 2"):
        PairedSpec(
            **_valid(quality_rubric={"scale": "0-3", "criteria": [{"name": "a"}]})
        )
    unanchored = {
        "scale": "0-3",
        "criteria": [
            {"name": "a", "full_marks_means": "all", "zero_means": ""},
            {"name": "b", "full_marks_means": "all", "zero_means": "none"},
        ],
    }
    with pytest.raises(ValueError, match="criterion 'a' leaves"):
        PairedSpec(**_valid(quality_rubric=unanchored))


def test_unblinded_or_single_evaluator_scoring_is_refused():
    """Quality is the one measure here that is a judgement, and a judgement made while you
    can see which arm produced the output is not evidence about the arms."""
    scoring = _valid()["scoring"]
    with pytest.raises(ValueError, match="not blinded"):
        PairedSpec(**_valid(scoring=scoring | {"blinded": False}))
    with pytest.raises(ValueError, match="fewer than 2"):
        PairedSpec(**_valid(scoring=scoring | {"evaluators": 1}))
    with pytest.raises(ValueError, match="disagree"):
        PairedSpec(**_valid(scoring=scoring | {"disagreement": "  "}))


def test_a_blank_falsifier_or_selection_rule_is_refused():
    with pytest.raises(ValueError, match="falsifier is empty"):
        PairedSpec(**_valid(falsifier="   "))
    with pytest.raises(ValueError, match="case_selection.rule is blank"):
        PairedSpec(**_valid(case_selection={"rule": ""}))


def test_the_record_cannot_be_edited_through_a_reference_its_caller_kept():
    rubric = _valid()["quality_rubric"]
    spec = PairedSpec(**_valid(quality_rubric=rubric))
    before = spec.spec_hash
    rubric["criteria"].append({"name": "smuggled"})
    assert spec.quality_rubric["criteria"] != rubric["criteria"]
    assert spec.spec_hash == before


# ------------------------------------------------------- the two-stage input lock


def test_a_spec_is_not_runnable_until_its_inputs_are_frozen():
    """The half v2 could not do and disclosed instead. A live dataset cannot be hashed
    before it exists, so the question is registered first and the cases second — and until
    the second commit lands, nothing may run against it."""
    spec = PairedSpec(**_valid())
    assert spec.runnable is False
    with pytest.raises(ValueError, match="no locked inputs"):
        assert_runnable(spec)

    locked = PairedSpec(**_valid(inputs_sha256="0xabc"))
    assert locked.runnable is True
    assert_runnable(locked)  # does not raise


def test_locking_the_inputs_changes_the_hash_so_the_two_stages_are_distinguishable():
    """A run cites a digest. If freezing the cases left the digest alone, a reader could not
    tell which stage of the registration a run was made against."""
    assert (
        PairedSpec(**_valid()).spec_hash
        != PairedSpec(**_valid(inputs_sha256="0xabc")).spec_hash
    )


# --------------------------------------------------------- round trip and tamper


def test_a_spec_edited_after_registration_refuses_to_load(tmp_path: Path):
    path = tmp_path / "s.json"
    save(PairedSpec(**_valid()), path)
    record = json.loads(path.read_text(encoding="utf-8"))
    record["claim"] = "something more flattering, decided later"
    path.write_text(json.dumps(record), encoding="utf-8")

    with pytest.raises(ValueError, match="does not hash to the digest it carries"):
        load(path)


def test_save_and_load_round_trip_to_the_same_digest(tmp_path: Path):
    spec = PairedSpec(**_valid())
    path = tmp_path / "s.json"
    save(spec, path)
    assert load(path).spec_hash == spec.spec_hash


# ------------------------------------------------- the three registered families


def test_all_three_families_are_registered_and_load_clean():
    """Range, Yield and Warden — and Warden is what satisfies the sponsor's requirement that
    at least one task come from trading, stock or security."""
    assert [p.stem for p in REGISTERED] == [
        "v3-01-range-doctor",
        "v3-02-yield-router",
        "v3-03-warden-security",
    ]
    specs = [load(p) for p in REGISTERED]
    assert any(spec.category == "security" for spec in specs)
    for spec in specs:
        assert spec.n_planned >= 5
        assert spec.runnable is False  # stage one: the cases are not frozen yet


def test_every_registered_family_plans_more_than_one_pair():
    """Three anecdotes is what v1 is. The point of v3 is that each task is a family."""
    assert [load(p).n_planned for p in REGISTERED] == [5, 5, 12]


def test_no_registered_spec_has_locked_inputs_before_its_cases_exist():
    """If this fails, a spec claims frozen cases while no inputs file is committed — which
    would be the self-attestation v3 exists to avoid, wearing a digest."""
    inputs_dir = SPECS_DIR.parent / "inputs"
    for path in REGISTERED:
        spec = load(path)
        if spec.runnable:
            assert (inputs_dir.parent / spec.inputs_ref.split("v3/", 1)[1]).exists(), (
                f"{spec.spec_id} carries an inputs digest but {spec.inputs_ref} is not committed"
            )
