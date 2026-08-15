"""The v3 report is a view over evidence, never a place to type a result."""

import json

from docket.advantage.v3 import report, runner, scoring

from test_advantage_v3_scoring import (
    _append_attempt,
    _complete_range_ledger,
    _locked_family,
    _range_output,
    _score_sheet,
)


def _build_report(tmp_path):
    return report.report(
        specs_dir=tmp_path / "specs",
        runs_dir=tmp_path / "runs",
        sheets_dir=tmp_path / "sheets",
        mappings_dir=tmp_path / "mappings",
        repo_root=tmp_path,
    )


def _score_completed_family(spec, inputs, tmp_path, *, scores):
    ledger = tmp_path / "runs" / f"{spec.spec_id}.jsonl"
    bundle = scoring.build_blinded_bundle(spec, ledger, repo_root=tmp_path)
    seats = [row["evaluator_id"] for row in spec.scoring["evaluator_roster"]]
    for seat in seats:
        scoring.ingest_score_sheet(
            spec,
            bundle,
            _score_sheet(spec, bundle, scores, seat_id=seat),
            tmp_path / "sheets",
        )
    scoring.publish_mapping(
        spec,
        bundle,
        tmp_path / "sheets",
        tmp_path / "mappings",
        repo_root=tmp_path,
    )


def test_the_committed_families_are_registered_waiting_for_inputs():
    payload = report.report()

    assert [family["state"] for family in payload["families"]] == [
        report.REGISTERED_WAITING,
        report.REGISTERED_WAITING,
        report.REGISTERED_WAITING,
    ]
    assert set(payload["summary"]["states"]) == {report.REGISTERED_WAITING}
    assert "proved" not in json.dumps(payload).lower()


def test_locked_not_run_running_and_complete_unscored_come_only_from_the_ledger(
    tmp_path, monkeypatch
):
    spec, inputs = _locked_family(tmp_path, monkeypatch, "v3-01-range-doctor")
    assert _build_report(tmp_path)["families"][0]["state"] == report.LOCKED_NOT_RUN

    ledger = tmp_path / "runs" / f"{spec.spec_id}.jsonl"
    first_case = inputs["cases"][0]["case_id"]
    _append_attempt(
        spec,
        ledger,
        first_case,
        "manual",
        output=_range_output(),
        elapsed_seconds=100,
    )
    assert _build_report(tmp_path)["families"][0]["state"] == report.RUNNING

    for case in inputs["cases"]:
        for arm in ("manual", "agent"):
            if case["case_id"] == first_case and arm == "manual":
                continue
            _append_attempt(
                spec,
                ledger,
                case["case_id"],
                arm,
                output=_range_output(),
                elapsed_seconds=100 if arm == "manual" else 40,
            )
    family = _build_report(tmp_path)["families"][0]
    assert family["state"] == report.COMPLETE_UNSCORED
    assert family["quality"] is None
    assert family["falsifier_result"] is None


def test_two_durable_sheets_and_mapping_produce_not_refuted_from_the_numbers(
    tmp_path, monkeypatch
):
    spec, inputs = _locked_family(tmp_path, monkeypatch, "v3-01-range-doctor")
    ledger = tmp_path / "runs" / f"{spec.spec_id}.jsonl"
    _complete_range_ledger(spec, inputs, ledger)
    _score_completed_family(spec, inputs, tmp_path, scores={"agent": 3, "manual": 2})

    family = _build_report(tmp_path)["families"][0]

    assert family["state"] == report.NOT_REFUTED
    assert family["quality"]["arms"]["agent"]["median_total"] == 15
    assert family["quality"]["arms"]["manual"]["median_total"] == 10
    assert family["speed"]["material"] is True
    assert family["falsifier_result"]["refuted"] is False
    assert all(
        check["refuted"] is False for check in family["falsifier_result"]["checks"]
    )


def test_a_failed_arm_flows_through_zero_quality_speed_and_refutation(
    tmp_path, monkeypatch
):
    spec, inputs = _locked_family(tmp_path, monkeypatch, "v3-01-range-doctor")
    failed_case = inputs["cases"][0]["case_id"]
    ledger = tmp_path / "runs" / f"{spec.spec_id}.jsonl"
    _complete_range_ledger(spec, inputs, ledger, failed={(failed_case, "agent")})
    _score_completed_family(spec, inputs, tmp_path, scores={"agent": 3, "manual": 2})

    family = _build_report(tmp_path)["families"][0]

    assert family["state"] == report.REFUTED
    failed = next(
        row
        for row in family["quality"]["outputs"]
        if row["case_id"] == failed_case and row["arm"] == "agent"
    )
    assert failed["total"] == 0
    assert family["speed"]["n_complete_pairs"] == spec.n_planned - 1
    assert family["speed"]["material"] is False
    assert family["falsifier_result"]["refuted"] is True


def test_a_blocked_contract_keeps_every_performance_aggregate_unscored(
    tmp_path, monkeypatch
):
    spec, inputs = _locked_family(tmp_path, monkeypatch, "v3-01-range-doctor")
    ledger = tmp_path / "runs" / f"{spec.spec_id}.jsonl"
    _complete_range_ledger(spec, inputs, ledger)
    events = runner.read_events(ledger)
    events[-1]["outcome"] = runner.BLOCKED_CONTRACT
    events[-1]["eligible_for_speed"] = False
    events[-1]["failure"] = {"kind": runner.BLOCKED_CONTRACT}
    ledger.write_text(
        "".join(json.dumps(event, sort_keys=True) + "\n" for event in events),
        encoding="utf-8",
    )

    family = _build_report(tmp_path)["families"][0]

    assert family["state"] == report.COMPLETE_UNSCORED
    assert family["unscored_reason"] == runner.BLOCKED_CONTRACT
    assert family["quality"] is None
    assert family["speed"] is None
    assert family["formula_metrics"] is None
    assert family["falsifier_result"] is None
    assert family["costs"]["totals"]
