import json
from datetime import datetime
from pathlib import Path

from docket.advantage.v3 import rehearsal, report, runner, scoring
import docket.advantage.v3.spec as spec_module


REGISTERED_SPEC = (
    Path(__file__).resolve().parents[1]
    / "docket/advantage/v3/specs/v3-02-yield-router.json"
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
    assert payload["summary"] == {
        "n_families": 1,
        "states": {report.NOT_REFUTED: 1},
        "refuted": [],
        "not_refuted": [rehearsal.SPEC_ID],
    }

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
