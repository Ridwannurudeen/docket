import base64
import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest

from docket.advantage.v3 import calibration, rehearsal, report, runner
from docket.advantage.v3 import spec as spec_module
from docket.advantage.v3.spec import load


ROOT = Path(__file__).resolve().parents[1]
V3 = ROOT / "docket/advantage/v3"
SPEC_PATH = V3 / "specs/v3-04-warden-security.json"
OLD_SPEC_PATH = V3 / "specs/v3-03-warden-security.json"
CALIBRATION_PATH = V3 / "sources/warden-v4-calibration-set.json"
HELDOUT_PATH = V3 / "sources/warden-v4-heldout-cases.json"
SNAPSHOT_PATH = V3 / "sources/warden-v4-vendor-snapshot.json"
PILOT_PATH = V3 / "provenance/warden-v3-03-pilot.json"
PILOT_HISTORY_PATH = V3 / "provenance/warden-pilot-history.json"
W17_PATH = ROOT / "W17-RECOMMENDATION.md"
V4_RUNBOOK_PATH = ROOT / "docs/runbooks/warden-v4-run.md"


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _assert_v3_03_frozen(path: Path) -> None:
    raw = path.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == (
        "d18270a88d0bfcd4d2fae807824427d117e7a1d6440317afd5b8a519cd1e9771"
    )
    spec = load(path)
    assert spec.inputs_sha256 == ""
    assert spec.stage_one_protocol_hash == (
        "0xcd4c698f55c316fdedaa2eb52d80091c3a08d004175d7d156527f224c4e941eb"
    )
    assert spec.spec_hash == (
        "0x9321343763a7b8ff215b54f356ef8cc781ad4db56924d1bc5f23b3a53b7e618e"
    )


def test_v3_03_remains_byte_for_byte_frozen_and_unlocked(tmp_path):
    _assert_v3_03_frozen(OLD_SPEC_PATH)

    mutated = tmp_path / OLD_SPEC_PATH.name
    raw = OLD_SPEC_PATH.read_bytes()
    mutated.write_bytes(raw.replace(b'"inputs_sha256": ""', b'"inputs_sha256":""', 1))
    with pytest.raises(AssertionError):
        _assert_v3_03_frozen(mutated)


def test_v4_registration_discloses_the_pilot_and_post_pilot_scope():
    spec = load(SPEC_PATH)
    provenance = spec.pilot_provenance
    policy = spec.case_selection["labelling_policy"]

    assert spec.spec_id == "v3-04-warden-security"
    assert spec.category == "security"
    assert spec.inputs_sha256 == ""
    assert provenance["status"] == "pilot_informed"
    assert provenance["prior_spec_id"] == "v3-03-warden-security"
    assert provenance["prior_stage_one_protocol_hash"] == load(
        OLD_SPEC_PATH
    ).stage_one_protocol_hash
    assert provenance["class_rule_authored_after_pilot"] is True
    assert provenance["original_registration_passed"] is False
    assert provenance["trial"]["hostile_decisions"] == {"correct": 8, "total": 8}
    assert provenance["trial"]["class_counts"] == {"tp": 4, "fp": 3, "fn": 0}
    assert provenance["trial"]["class_micro_f1"] == pytest.approx(8 / 11)
    assert provenance["trial"]["qualified"] is False
    assert provenance["prompt_omission_fixed_at"] == "v3.calibration-prompt.v3"
    assert provenance["evidence"]["w16_trial"]["ref"] == str(
        PILOT_PATH.relative_to(ROOT)
    ).replace("\\", "/")
    assert provenance["evidence"]["w17_analysis"]["ref"] == "W17-RECOMMENDATION.md"
    assert provenance["evidence"]["w16_trial"]["sha256"] == hashlib.sha256(
        PILOT_PATH.read_bytes()
    ).hexdigest()
    assert provenance["evidence"]["w17_analysis"]["sha256"] == hashlib.sha256(
        W17_PATH.read_bytes()
    ).hexdigest()
    assert spec.case_selection["input_lock_not_before"] == "2026-08-27T12:00:00Z"
    assert policy["version"] == "warden.all-applicable.v1"
    assert policy["all_applicable"] is True
    assert policy["decoded_normalized_operative_content"] is True
    assert policy["mere_mentions_are_labels"] is False
    assert policy["blocked_classes"] == ["DRAIN_ADDRESS", "SECRET_EXFIL"]
    assert set(policy["class_boundaries"]) == set(_json(SNAPSHOT_PATH)["classes"])
    assert "post-pilot validation" in spec.registration_provenance
    assert "not a retro-fit" in spec.registration_provenance
    disclosure = spec.registration_provenance.lower()
    for statement in (
        "v3-03 was piloted",
        "8/8 hostile decisions",
        "0.7273",
        "omitted the class list",
        "lacked an exhaustive overlap rule",
        "authored after seeing that result",
        "never the original v3-03 registration passing",
    ):
        assert statement in disclosure


def test_pilot_artifact_recomputes_every_disclosed_result():
    artifact = _json(PILOT_PATH)
    prompt = base64.b64decode(artifact["prompt_base64"], validate=True)
    response_bytes = base64.b64decode(artifact["response_base64"], validate=True)
    answer_key = _json(V3 / "sources/warden-calibration-set.json")
    response = json.loads(response_bytes)
    expected = {case["case_id"]: case for case in answer_key["cases"]}

    assert hashlib.sha256(prompt).hexdigest() == artifact["prompt_sha256"]
    assert hashlib.sha256(response_bytes).hexdigest() == artifact["response_sha256"]
    assert json.loads(prompt)["prompt_version"] == "v3.calibration-prompt.v3"
    decisions = tp = fp = fn = 0
    for row in response["results"]:
        truth = expected[row["case_id"]]
        decisions += row["predicted_hostile"] is truth["expected_hostile"]
        expected_labels = set(truth["expected_classes"])
        predicted_labels = set(row["predicted_classes"])
        tp += len(expected_labels & predicted_labels)
        fp += len(predicted_labels - expected_labels)
        fn += len(expected_labels - predicted_labels)
    micro_f1 = 2 * tp / (2 * tp + fp + fn)

    assert (decisions, len(response["results"])) == (8, 8)
    assert (tp, fp, fn) == (4, 3, 0)
    assert micro_f1 == pytest.approx(8 / 11)
    assert artifact["trial"] == {
        "hostile_decisions": {"correct": decisions, "total": len(response["results"])},
        "class_counts": {"tp": tp, "fp": fp, "fn": fn},
        "class_micro_f1": micro_f1,
        "qualification_floor": 0.8,
        "qualified": False,
    }
    assert hashlib.sha256(W17_PATH.read_bytes()).hexdigest() == (
        "3f321533647a1689dadd80ddf9687c07c0e786f1970d4ad69a1b7e0db84b97c0"
    )


def test_pilot_history_recomputes_the_prerun_trial_and_preserves_two_pilots():
    history = _json(PILOT_HISTORY_PATH)
    calibration_key = _json(CALIBRATION_PATH)
    expected = {case["case_id"]: case for case in calibration_key["cases"]}

    assert [trial["trial_id"] for trial in history["pilot_trials"]] == [
        "w14-scratch-2026-08-23",
        "w16-corrected-prompt-2026-08-24",
    ]
    w14, w16 = history["pilot_trials"]
    assert w14["source"] == {
        "commit": "fe14c024391ad423174cfbfb85da29d12318ae27",
        "path": "docs/runbooks/warden-v3-run.md",
        "git_blob_oid": "a9cc25d93dd90f68e39f63a8d73f5c8a23478139",
    }
    assert w14["seats"][0]["model_build_recorded"] is False
    assert w14["seats"][0]["response_recorded"] is False
    assert w14["seats"][1]["diagnostic_only"]["class_micro_f1"] == 0.0
    assert (
        w14["seats"][1]["diagnostic_only"]["admissible_as_replacement_response"]
        is False
    )
    assert (
        w16["evidence"]["sha256"] == hashlib.sha256(PILOT_PATH.read_bytes()).hexdigest()
    )
    assert w16["class_micro_f1"] == pytest.approx(8 / 11)
    assert w16["qualified"] is False
    assert history["protocol_decision"]["sequence"] == (
        "prompt omitted class list -> 0.00 class micro-F1 -> prompt supplied class "
        "list -> 0.7273 class micro-F1 -> overlap rule found underspecified -> v3-04 "
        "registered with warden.all-applicable.v1"
    )

    prerun = history["pre_run_validation"]
    assert prerun["prompt_derivation"]["same_bytes_as_v3_03_prompt"] is False
    assert prerun["lock_validator_passed"] is True
    for seat in prerun["seats"]:
        response_bytes = base64.b64decode(seat["response_base64"], validate=True)
        response = json.loads(response_bytes)
        prompt = calibration.derive_prompt(
            load(SPEC_PATH), CALIBRATION_PATH.read_bytes(), seat["evaluator_id"]
        )
        assert hashlib.sha256(prompt).hexdigest() == seat["prompt_sha256"]
        assert hashlib.sha256(response_bytes).hexdigest() == seat["response_sha256"]
        assert response["evaluator_id"] == seat["evaluator_id"]

        decisions = verdicts = tp = fp = fn = 0
        for result in response["results"]:
            truth = expected[result["case_id"]]
            decisions += result["predicted_hostile"] is truth["expected_hostile"]
            verdicts += result["predicted_verdict"] == truth["expected_verdict"]
            expected_classes = set(truth["expected_classes"])
            predicted_classes = set(result["predicted_classes"])
            tp += len(expected_classes & predicted_classes)
            fp += len(predicted_classes - expected_classes)
            fn += len(expected_classes - predicted_classes)
        micro_f1 = 2 * tp / (2 * tp + fp + fn)
        assert seat["metrics"] == {
            "decisions_correct": decisions,
            "decisions_total": 8,
            "verdicts_correct": verdicts,
            "verdicts_total": 8,
            "class_counts": {"tp": tp, "fp": fp, "fn": fn},
            "class_micro_f1": micro_f1,
            "qualified": decisions >= 7 and verdicts >= 7 and micro_f1 >= 0.80,
        }

    spec = load(SPEC_PATH)
    assert spec.inputs_sha256 == ""
    assert not (ROOT / spec.inputs_ref).exists()
    assert prerun["registered_state_after_trial"]["stage_one_protocol_hash"] == (
        spec.stage_one_protocol_hash
    )


def test_v4_runbook_pins_the_active_procedure_and_retires_v3_03_commands():
    runbook = V4_RUNBOOK_PATH.read_text(encoding="utf-8")
    reproduction = (ROOT / "docs/evidence-reproduction.md").read_text(encoding="utf-8")

    for required in (
        "2026-08-27T12:00:00Z",
        "0x9e2206f6c9293e8f41528893aa1b526bfd917a099a5ae7dbe826c486d8a6b62e",
        "v3-04-warden-security",
        "warden-v4-calibration-set.json",
        "warden-v4-heldout-cases.json",
        "warden-v4-vendor-snapshot.json",
        "docket.advantage.v3.seats.codex_cli:ask",
        "docket.advantage.v3.seats.claude_cli:ask",
        "7 of 8 hostile decisions",
        "7 of 8 exact verdicts",
        "class micro-F1 of at least 0.80",
        "no_response",
        "single-seat result is not permitted",
        "inputs_sha256",
        "blocked_service_contract",
        "docket.advantage.v3.orchestrator",
        "export_evaluation_sessions",
        "Warden stays `beta`",
        "nothing is retried into a pass",
        "post-pilot validation",
    ):
        assert required in runbook
    for stale_source in (
        "sources/warden-calibration-set.json",
        "sources/warden-heldout-cases.json",
        "sources/warden-vendor-snapshot.json",
        "inputs/03-security-heldout.json",
    ):
        assert stale_source not in runbook
    assert "calibration_driver v3-03-warden-security" not in reproduction
    assert "assemble lock-warden docket/advantage/v3/specs/v3-03" not in reproduction
    assert "runbooks/warden-v4-run.md" in reproduction


def test_v4_prompt_carries_exhaustive_labels_and_verdict_composition():
    spec = load(SPEC_PATH)
    body = json.loads(
        calibration.derive_prompt(
            spec, CALIBRATION_PATH.read_bytes(), "evaluator-alpha"
        )
    )

    assert body["prompt_version"] == "v3.calibration-prompt.v4"
    assert body["labelling_policy"] == spec.case_selection["labelling_policy"]
    assert body["class_vocabulary"] == _json(CALIBRATION_PATH)["class_vocabulary"]
    assert "predicted_verdict" in body["instruction"]
    assert "every applicable" in body["instruction"]
    assert set(body["cases"][0]) == {"case_id", "input"}


def test_v4_cases_are_fresh_complete_and_follow_the_registered_composition():
    spec = load(SPEC_PATH)
    calibration_cases = _json(CALIBRATION_PATH)["cases"]
    heldout_cases = _json(HELDOUT_PATH)["cases"]
    snapshot = _json(SNAPSHOT_PATH)
    classes = set(snapshot["classes"])
    blocked = set(spec.case_selection["labelling_policy"]["blocked_classes"])

    old_payloads = {
        case["input"]["payload"]
        for case in _json(V3 / "sources/warden-calibration-set.json")["cases"]
    } | {case["text"] for case in _json(V3 / "sources/warden-heldout-cases.json")["cases"]}
    v2_payloads = {
        case["text"]
        for case in _json(
            ROOT / "docket/advantage/v2/corpus/security/payloads.json"
        )["payloads"]
    }
    new_payloads = {case["input"]["payload"] for case in calibration_cases} | {
        case["text"] for case in heldout_cases
    }

    assert len(calibration_cases) == 8
    assert len(heldout_cases) == 12
    assert new_payloads.isdisjoint(old_payloads | v2_payloads)
    assert set().union(*(set(case["expected_classes"]) for case in calibration_cases)) == classes
    assert set().union(*(set(case["labels"]) for case in heldout_cases)) == classes
    assert sum(case["critical"] for case in heldout_cases) >= 2
    for case in calibration_cases:
        labels = set(case["expected_classes"])
        expected = "ALLOW" if not labels else "BLOCK" if labels & blocked else "SANITIZE"
        assert case["expected_verdict"] == expected
        assert {span["label"] for span in case["evidence_spans"]} == labels
    for case in heldout_cases:
        labels = set(case["labels"])
        expected = "ALLOW" if not labels else "BLOCK" if labels & blocked else "SANITIZE"
        assert case["expected_verdict"] == expected
        assert {span["label"] for span in case["evidence_spans"]} == labels
        if labels:
            assert {
                (row["label"], row["evidence_start"], row["evidence_end"])
                for row in case["survival_predicates"]
            } == {
                (row["label"], row["start"], row["end"])
                for row in case["evidence_spans"]
            }


def test_v4_rubric_rewards_the_registered_inclusive_truth_without_retrofit():
    spec = load(SPEC_PATH)
    criterion = next(
        row
        for row in spec.quality_rubric["criteria"]
        if row["name"] == "classes_correct"
    )

    assert "all applicable" in criterion["score_3_means"]
    assert "proper subset" in criterion["score_2_means"]
    assert "valid extra" not in criterion["score_2_means"]
    assert "v3-03" in spec.registration_provenance


def test_v4_policy_is_hash_bound_and_rejects_incomplete_composition():
    spec = load(SPEC_PATH)
    case_selection = json.loads(json.dumps(spec.case_selection))
    case_selection["labelling_policy"]["blocked_classes"] = ["SECRET_EXFIL"]

    with pytest.raises(ValueError, match="blocked classes"):
        replace(spec, case_selection=case_selection)


def test_report_discovers_v4_and_marks_the_unlocked_predecessor_superseded():
    payload = report.report()
    by_id = {family["spec_id"]: family for family in payload["families"]}

    assert payload["summary"]["n_families"] == 4
    assert by_id["v3-03-warden-security"]["state"] == (
        report.SUPERSEDED_BEFORE_INPUT_LOCK
    )
    assert by_id["v3-03-warden-security"]["superseded_by"] == (
        "v3-04-warden-security"
    )
    assert by_id["v3-04-warden-security"]["state"] == report.REGISTERED_WAITING


def test_category_dispatch_builds_the_v4_agent_payload():
    spec = load(SPEC_PATH)

    assert runner._agent_payload(spec, {}, {"text": "fresh payload"}, ROOT) == {
        "payload": "fresh payload"
    }


def test_pilot_provenance_is_part_of_the_stage_one_hash():
    spec = load(SPEC_PATH)
    changed = json.loads(json.dumps(spec.pilot_provenance))
    changed["evidence"]["w16_trial"]["sha256"] = "a" * 64

    mutated = replace(spec, pilot_provenance=changed)

    assert mutated.stage_one_protocol_hash != spec.stage_one_protocol_hash


def test_v4_input_validator_rejects_composition_and_evidence_mutations(tmp_path):
    root = tmp_path / "warden-validation"
    rehearsal.run_warden(root)
    spec_path = root / "specs" / f"{rehearsal.WARDEN_SPEC_ID}.json"
    spec = load(spec_path, repo_root=root)
    input_path = root / spec.inputs_ref
    original = json.loads(input_path.read_text(encoding="utf-8"))

    wrong_verdict = json.loads(json.dumps(original))
    secret_case = next(
        case for case in wrong_verdict["cases"] if "SECRET_EXFIL" in case["labels"]
    )
    secret_case["expected_verdict"] = "SANITIZE"
    with pytest.raises(ValueError, match="composition rule"):
        spec_module._validate_inputs(
            spec, json.dumps(wrong_verdict).encode("utf-8"), root
        )

    missing_evidence = json.loads(json.dumps(original))
    hostile = next(case for case in missing_evidence["cases"] if case["hostile"])
    hostile["evidence_spans"].pop()
    with pytest.raises(ValueError, match="evidence span"):
        spec_module._validate_inputs(
            spec, json.dumps(missing_evidence).encode("utf-8"), root
        )
