import json
from datetime import datetime
from pathlib import Path

import pytest

from docket.advantage.v3 import rehearsal, report, runner, scoring
import docket.advantage.v3.spec as spec_module


REGISTERED_SPEC = (
    Path(__file__).resolve().parents[1]
    / "docket/advantage/v3/specs/v3-02-yield-router.json"
)
REGISTERED_WARDEN_SPECS = tuple(
    Path(__file__).resolve().parents[1] / f"docket/advantage/v3/specs/{spec_id}.json"
    for spec_id in ("v3-03-warden-security", "v3-04-warden-security")
)
REGISTERED_RANGE_SPECS = tuple(
    Path(__file__).resolve().parents[1] / f"docket/advantage/v3/specs/{spec_id}.json"
    for spec_id in ("v3-01-range-doctor", "v3-05-range-doctor")
)


def test_rehearsal_runs_the_complete_production_evidence_path(tmp_path):
    registered_before = REGISTERED_SPEC.read_bytes()
    output = tmp_path / "throwaway"

    payload = rehearsal.run(output)

    assert REGISTERED_SPEC.read_bytes() == registered_before
    assert rehearsal.SPEC_ID not in spec_module.INPUT_VALIDATORS
    assert rehearsal.SPEC_ID not in scoring.FAMILY_PROTOCOLS
    assert set(payload) == {"version", "states", "summary", "families"}
    assert payload["version"] == "v3"
    summary = dict(payload["summary"])
    one_page = summary.pop("one_page")
    assert summary == {
        "n_families": 1,
        "states": {report.NOT_REFUTED: 1},
        "refuted": [],
        "not_refuted": [rehearsal.SPEC_ID],
    }
    # The one-page table always covers the committed v1 and v2 artifacts as well, so its
    # row count is those plus this scratch family. It computes no verdict for any of them.
    assert one_page["verdict"] is None
    assert one_page["n_rows"] == len(one_page["rows"])
    assert [row["task"] for row in one_page["rows"] if row["version"] == "v3"] == [
        rehearsal.SPEC_ID
    ]

    family = payload["families"][0]
    assert family["spec_id"] == rehearsal.SPEC_ID
    assert family["state"] == report.NOT_REFUTED
    assert family["spec"]["inputs_sha256"]
    assert len(family["spec"]["inputs_sha256"]) == 64
    assert "REHEARSAL ONLY" in family["spec"]["registration_provenance"]
    assert family["calibration"]["all_seats_qualified"] is True
    assert family["run_progress"] == {
        "scheduled_primaries": 10,
        "claimed_primaries": 10,
        "terminal_primaries": 10,
        "outcomes": {runner.SUCCEEDED: 10},
    }
    assert family["speed"]["material"] is True
    assert family["falsifier_result"]["refuted"] is False
    assert len(family["score_sheets"]) == 2
    assert family["mapping"] is not None

    armed = json.loads((output / "capture/armed.json").read_text(encoding="utf-8"))
    assert datetime.fromisoformat(
        armed["process_started_at"].replace("Z", "+00:00")
    ) < (datetime.fromisoformat(armed["registered_moment"].replace("Z", "+00:00")))
    assert (output / "capture/capture-complete.json").is_file()
    assert len(list((output / "calibration").glob("**/attempt-01.response.json"))) == 2
    assert (output / "inputs/rehearsal-yield-cases.json").is_file()
    assert len(list((output / "mappings").glob("mapping-*.json"))) == 1

    terminals = [
        event for event in family["ledger"] if event["kind"] == runner.TERMINATED
    ]
    assert [event["arm"] for event in terminals] == ["manual"] * 5 + ["agent"] * 5
    assert all(event["receipt"] is None for event in terminals[:5])
    assert all(
        event["receipt"]["service"] == rehearsal.AGENT_SERVICE_ID
        for event in terminals[5:]
    )


def test_rehearsal_cli_writes_the_served_json_shape_once(tmp_path, capsys):
    output = tmp_path / "one-command"

    assert rehearsal.main([str(output)]) == 0

    served = json.loads((output / "advantage-v3.json").read_text(encoding="utf-8"))
    assert set(served) == {"version", "states", "summary", "families"}
    assert served["families"][0]["spec_id"] == rehearsal.SPEC_ID
    assert served["families"][0]["state"] == report.NOT_REFUTED
    assert str(output / "advantage-v3.json") in capsys.readouterr().out

    report_before = (output / "advantage-v3.json").read_bytes()
    assert rehearsal.main([str(output)]) == 2
    assert (output / "advantage-v3.json").read_bytes() == report_before
    assert "rehearsal refused" in capsys.readouterr().out


def test_warden_rehearsal_locks_and_scores_all_slots_without_consuming_registration(
    tmp_path,
):
    registered_before = {path: path.read_bytes() for path in REGISTERED_WARDEN_SPECS}
    output = tmp_path / "warden-throwaway"

    payload = rehearsal.run_warden(output)

    assert {path: path.read_bytes() for path in REGISTERED_WARDEN_SPECS} == (
        registered_before
    )
    assert rehearsal.WARDEN_SPEC_ID not in spec_module.INPUT_VALIDATORS
    assert rehearsal.WARDEN_SPEC_ID not in scoring.FAMILY_PROTOCOLS
    summary = dict(payload["summary"])
    one_page = summary.pop("one_page")
    assert summary == {
        "n_families": 1,
        "states": {report.NOT_REFUTED: 1},
        "refuted": [],
        "not_refuted": [rehearsal.WARDEN_SPEC_ID],
    }
    assert one_page["verdict"] is None
    assert [row["task"] for row in one_page["rows"] if row["version"] == "v3"] == [
        rehearsal.WARDEN_SPEC_ID
    ]
    family = payload["families"][0]
    assert family["state"] == report.NOT_REFUTED
    assert family["calibration"]["all_seats_qualified"] is True
    assert family["run_progress"] == {
        "scheduled_primaries": 24,
        "claimed_primaries": 24,
        "terminal_primaries": 24,
        "outcomes": {runner.SUCCEEDED: 24},
    }
    assert family["formula_metrics"]["all_gates_pass"] is True
    assert family["speed"]["material"] is True
    assert len(family["score_sheets"]) == 2
    assert family["mapping"] is not None
    terminals = [
        event for event in family["ledger"] if event["kind"] == runner.TERMINATED
    ]
    assert [event["arm"] for event in terminals] == ["manual"] * 12 + ["agent"] * 12
    assert all(event["receipt"] is None for event in terminals[:12])
    assert all(
        event["receipt"]["service"] == rehearsal.WARDEN_AGENT_SERVICE_ID
        for event in terminals[12:]
    )
    assert (output / "inputs/warden-v4-rehearsal-cases.json").is_file()
    assert len(list((output / "calibration").glob("**/attempt-01.response.json"))) == 2


def test_range_rehearsal_locks_and_scores_all_slots_without_consuming_registration(
    tmp_path, monkeypatch
):
    registered_before = {path: path.read_bytes() for path in REGISTERED_RANGE_SPECS}
    validator_before = spec_module.INPUT_VALIDATORS["v3-05-range-doctor"]
    protocol_before = scoring.FAMILY_PROTOCOLS["v3-05-range-doctor"]
    production_artifacts = (
        Path(__file__).resolve().parents[1]
        / "docket/advantage/v3/inputs/range-v5-positions.json",
        Path(__file__).resolve().parents[1]
        / "docket/advantage/v3/runs/v3-05-range-doctor.jsonl",
    )
    assert production_artifacts[0].is_file()
    production_input_before = production_artifacts[0].read_bytes()
    assert not production_artifacts[1].exists()

    class ForbiddenClient:
        def __init__(self, *args, **kwargs):
            raise AssertionError(
                "the Range rehearsal must not create a real HTTP client"
            )

    monkeypatch.setattr(rehearsal.httpx, "Client", ForbiddenClient)
    output = tmp_path / "range-throwaway"

    payload = rehearsal.run_range(output)

    assert {path: path.read_bytes() for path in REGISTERED_RANGE_SPECS} == (
        registered_before
    )
    assert rehearsal.RANGE_SPEC_ID not in spec_module.INPUT_VALIDATORS
    assert rehearsal.RANGE_SPEC_ID not in scoring.FAMILY_PROTOCOLS
    assert spec_module.INPUT_VALIDATORS["v3-05-range-doctor"] is validator_before
    assert scoring.FAMILY_PROTOCOLS["v3-05-range-doctor"] is protocol_before
    assert production_artifacts[0].read_bytes() == production_input_before
    assert not production_artifacts[1].exists()
    assert (
        json.loads((output / "advantage-v3.json").read_text(encoding="utf-8"))
        == payload
    )
    family = payload["families"][0]
    assert family["spec_id"] == rehearsal.RANGE_SPEC_ID
    assert family["state"] == report.NOT_REFUTED
    assert family["calibration"]["all_seats_qualified"] is True
    assert family["run_progress"] == {
        "scheduled_primaries": 6,
        "claimed_primaries": 6,
        "terminal_primaries": 6,
        "outcomes": {runner.SUCCEEDED: 6},
    }
    assert family["speed"]["material"] is True
    assert len(family["score_sheets"]) == 2
    assert family["mapping"] is not None
    terminals = [
        event for event in family["ledger"] if event["kind"] == runner.TERMINATED
    ]
    assert [event["arm"] for event in terminals] == ["manual"] * 3 + ["agent"] * 3
    assert all(event["receipt"] is None for event in terminals[:3])
    assert all(
        event["receipt"]["service"] == rehearsal.RANGE_AGENT_SERVICE_ID
        for event in terminals[3:]
    )
    frame = json.loads(
        (output / "sources/range-v5-enumerable-frame.json").read_text(encoding="utf-8")
    )
    assert len(frame["rows"]) == 1024
    assert len({row["index"] for row in frame["rows"]}) == 1024
    controlled = next(row for row in frame["rows"] if row["token_id"] == 7141050)
    assert set(controlled) == {
        "sample_ordinal",
        "derivation_counter",
        "index",
        "token_id",
        "owner",
        "staking_beneficiary",
    }
    assert frame["rpc_call_accounting"]["eth_getLogs"] == 0
    pool_truth = json.loads(
        (output / "sources/range-v5-pool-truth.json").read_text(encoding="utf-8")
    )
    assert pool_truth["capture_log"] == [
        {
            "attempt_ordinal": 1,
            "scheduled_at": "2026-08-26T12:10:00Z",
            "pools_status": 200,
            "token_list_status": 200,
        }
    ]
    assert len(list((output / "sheets").glob("**/*.json"))) == 2
    assert len(list((output / "mappings").glob("*.json"))) == 1
    assert len(list((output / "calibration").glob("**/attempt-01.response.json"))) == 2


def test_range_rehearsal_scores_a_corrupted_agent_fixture_as_refuted(
    tmp_path, monkeypatch
):
    original = rehearsal._range_output
    calls = 0

    def corrupted(case, root):
        nonlocal calls
        calls += 1
        output = original(case, root)
        if calls > 3:
            output["range"]["status"] = "wrong_range"
        return output

    monkeypatch.setattr(rehearsal, "_range_output", corrupted)
    payload = rehearsal.run_range(tmp_path / "corrupted-range")

    assert calls == 6
    assert payload["families"][0]["state"] == report.REFUTED


def test_range_rehearsal_refuses_existing_evidence(tmp_path):
    output = tmp_path / "existing-range"
    output.mkdir()
    sentinel = output / "sentinel.txt"
    sentinel.write_text("keep\n", encoding="utf-8")

    with pytest.raises(rehearsal.RehearsalRefused, match="first-write"):
        rehearsal.run_range(output)
    assert sentinel.read_text(encoding="utf-8") == "keep\n"
    assert list(output.iterdir()) == [sentinel]
