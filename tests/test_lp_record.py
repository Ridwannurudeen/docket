"""The daily record of the controlled position.

The behaviour worth pinning is not that a good day is written down. It is that a bad day is
written down too — an unreachable endpoint has to leave a line saying so, because a gap in
an append-only file reads exactly like nobody having run it, and a reader auditing the
history months later cannot tell those apart.
"""

import hashlib
import json
import os
from datetime import UTC, datetime, timedelta

import pytest

from docket.agents.pancake import lp_record

WALLET = "0xe55816904796341bf8535e25f6c8b647927fc946"
TOKEN = 7141050
WHEN = datetime(2026, 8, 16, 6, 0, tzinfo=UTC)


def _report(**overrides):
    body = {
        "address": WALLET,
        "target_token_id": TOKEN,
        "target_found": True,
        "positions_held": 1,
        "positions_examined": 1,
        "closed_skipped": 0,
        "scan_complete": True,
        "decision": f"Position {TOKEN} is inside its range and can earn fees.",
        "positions": [{"position": {"token_id": TOKEN}}],
    }
    return body | overrides


def _sha256(record):
    body = json.dumps(
        record, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(body).hexdigest()


def _history_with_decision(path):
    observations = []
    for day in range(8):
        observation = lp_record.observe(
            WALLET,
            TOKEN,
            reporter=lambda *a, **k: _report(),
            now=WHEN + timedelta(days=day),
        )
        lp_record.append(observation, path)
        observations.append(observation)
    decision = lp_record.append_owner_decision(
        path,
        decision="WAIT",
        rationale="Recenter cost exceeds the observed short-window fee opportunity.",
        decided_at="2026-08-24T06:05:00+00:00",
        prior_observation_sha256=_sha256(observations[-1]),
        alternatives=["RECENTER"],
    )
    later = lp_record.observe(
        WALLET,
        TOKEN,
        reporter=lambda *a, **k: _report(),
        now=WHEN + timedelta(days=9),
    )
    lp_record.append(later, path)
    return decision


def test_a_successful_day_records_the_product_s_own_output():
    record = lp_record.observe(
        WALLET,
        TOKEN,
        declared_position_value_usd=50.55,
        reporter=lambda *a, **k: _report(),
        now=WHEN,
    )
    assert record["observed"] is True
    assert record["still_held"] is True
    assert record["target_found"] is True
    assert record["observed_at"] == "2026-08-16T06:00:00+00:00"
    # The report travels whole rather than being summarised into this file's own vocabulary.
    assert record["report"]["target_token_id"] == TOKEN


def test_an_unreachable_endpoint_still_leaves_a_line():
    """The point of the file. A day with no line cannot be told from a day nobody ran."""

    def _raise(*_args, **_kwargs):
        raise RuntimeError("every BSC endpoint failed")

    record = lp_record.observe(WALLET, TOKEN, reporter=_raise, now=WHEN)
    assert record["observed"] is False
    assert "every BSC endpoint failed" in record["error"]
    assert record["observed_at"] == "2026-08-16T06:00:00+00:00"
    assert "report" not in record


def test_a_closed_or_transferred_position_is_visible_rather_than_absent():
    record = lp_record.observe(
        WALLET,
        TOKEN,
        reporter=lambda *a, **k: _report(
            target_found=False, positions_held=0, positions=[]
        ),
        now=WHEN,
    )
    assert record["observed"] is True
    assert record["still_held"] is False
    assert record["target_found"] is False


def test_the_history_is_append_only(tmp_path):
    path = tmp_path / "lp" / "controlled.jsonl"
    first = lp_record.observe(
        WALLET, TOKEN, reporter=lambda *a, **k: _report(), now=WHEN
    )
    lp_record.append(first, path)

    def _raise(*_args, **_kwargs):
        raise RuntimeError("endpoints down")

    lp_record.append(lp_record.observe(WALLET, TOKEN, reporter=_raise, now=WHEN), path)

    history = lp_record.read(path)
    assert [entry["observed"] for entry in history] == [True, False]
    # The first day is untouched by the second being written.
    assert history[0]["report"]["target_token_id"] == TOKEN
    assert path.read_text(encoding="utf-8").count("\n") == 2


def test_reading_a_history_that_does_not_exist_yet_is_not_an_error(tmp_path):
    assert lp_record.read(tmp_path / "never-written.jsonl") == []


def test_read_history_returns_every_nonblank_line_in_order(tmp_path):
    path = tmp_path / "controlled.jsonl"
    records = [{"sequence": 1}, {"sequence": 2}, {"sequence": 3}]
    path.write_text(
        "\n".join(json.dumps(record) for record in records[:2])
        + "\n\n"
        + json.dumps(records[2])
        + "\n",
        encoding="utf-8",
    )
    assert lp_record.read_history(path) == records


@pytest.mark.parametrize(
    "reporter, expected",
    [
        (lambda *a, **k: _report(), 0),
        (lambda *a, **k: _report(target_found=False, positions_held=0), 1),
    ],
    ids=["found", "not-found"],
)
def test_the_timer_learns_whether_the_day_produced_a_diagnosis(
    tmp_path, monkeypatch, reporter, expected
):
    """A recorded failure is still a failure the unit should see."""
    monkeypatch.setattr(lp_record.doctor, "report", reporter)
    path = tmp_path / "controlled.jsonl"
    code = lp_record.main(
        [WALLET, str(TOKEN), str(path), "--declared-value-usd", "50.55"]
    )
    assert code == expected
    assert len(lp_record.read(path)) == 1


def test_an_observation_keeps_the_original_jsonl_byte_format(tmp_path):
    """Observation bytes stay compatible while hashes use their own canonical form."""
    path = tmp_path / "controlled.jsonl"
    lp_record.append(
        lp_record.observe(
            WALLET,
            TOKEN,
            reporter=lambda *a, **k: _report(
                decision=f"Position {TOKEN} earns caf\u00e9 fees."
            ),
            now=WHEN,
        ),
        path,
    )
    line = path.read_text(encoding="utf-8").splitlines()[0]
    assert line == json.dumps(json.loads(line), sort_keys=True)
    assert "caf\\u00e9" in line


def test_a_transferred_position_is_not_hidden_by_the_wallet_holding_others():
    """The one day this record exists to catch, previously reported as a normal day.

    `still_held` read the wallet's total position count, so a wallet that had moved the
    tracked NFT away but still held any other one recorded `still_held: true`. The record
    is about token 7141050, not about how busy its owner is.
    """
    record = lp_record.observe(
        WALLET,
        TOKEN,
        reporter=lambda *a, **k: _report(
            target_found=False, positions_held=3, positions=[]
        ),
        now=WHEN,
    )
    assert record["still_held"] is False
    assert record["target_found"] is False
    # The wallet's own count is kept, because it is a fact — just not this one.
    assert record["wallet_positions_held"] == 3


def test_owner_decision_is_canonical_and_fsynced(tmp_path, monkeypatch):
    path = tmp_path / "controlled.jsonl"
    observation = lp_record.observe(
        WALLET, TOKEN, reporter=lambda *a, **k: _report(), now=WHEN
    )
    lp_record.append(observation, path)
    fsynced = []
    monkeypatch.setattr(
        os, "fsync", lambda file_descriptor: fsynced.append(file_descriptor)
    )

    decision = lp_record.append_owner_decision(
        path,
        decision="RECENTER",
        rationale="The owner accepts the declared recenter cost.",
        decided_at="2026-08-22T06:05:00Z",
        prior_observation_sha256=_sha256(observation),
        alternatives=["WAIT"],
    )

    assert decision == {
        "record_version": "lp-record.v1",
        "kind": "owner_decision",
        "decision": "RECENTER",
        "rationale": "The owner accepts the declared recenter cost.",
        "decided_at": "2026-08-22T06:05:00Z",
        "prior_observation_sha256": _sha256(observation),
        "supersedes_decision_sha256": None,
        "alternatives": ["WAIT"],
        "token_id": TOKEN,
    }
    assert fsynced
    line = path.read_text(encoding="utf-8").splitlines()[-1]
    assert line == json.dumps(
        decision, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )


def test_later_observation_answers_latest_owner_decision(tmp_path):
    path = tmp_path / "controlled.jsonl"
    decision = _history_with_decision(path)
    history = lp_record.read_history(path)

    assert len(history) == 10
    assert history[-1]["answers_decision_sha256"] == _sha256(decision)
    lp_record.verify_history(path)


@pytest.mark.parametrize(
    "mutation, referenced_index",
    [
        ("alter", 7),
        ("alter", 8),
        ("remove", 7),
        ("remove", 8),
    ],
    ids=[
        "alter-observation",
        "alter-decision",
        "remove-observation",
        "remove-decision",
    ],
)
def test_verify_history_rejects_tampering_with_a_referenced_line(
    tmp_path, mutation, referenced_index
):
    path = tmp_path / "controlled.jsonl"
    _history_with_decision(path)
    history = lp_record.read_history(path)
    if mutation == "alter":
        history[referenced_index]["altered"] = True
    else:
        del history[referenced_index]
    path.write_text(
        "".join(
            json.dumps(
                record, sort_keys=True, separators=(",", ":"), ensure_ascii=False
            )
            + "\n"
            for record in history
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="hash"):
        lp_record.verify_history(path)


def test_verify_history_requires_later_observation_to_answer_latest_decision(tmp_path):
    path = tmp_path / "controlled.jsonl"
    _history_with_decision(path)
    history = lp_record.read_history(path)
    del history[-1]["answers_decision_sha256"]
    path.write_text(
        "".join(
            json.dumps(
                record, sort_keys=True, separators=(",", ":"), ensure_ascii=False
            )
            + "\n"
            for record in history
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="latest owner decision"):
        lp_record.verify_history(path)


@pytest.mark.parametrize("mutation", ["alter", "remove"])
def test_back_to_back_decisions_chain_and_detect_tampering(tmp_path, mutation):
    path = tmp_path / "controlled.jsonl"
    observation = lp_record.observe(
        WALLET, TOKEN, reporter=lambda *a, **k: _report(), now=WHEN
    )
    lp_record.append(observation, path)
    first = lp_record.append_owner_decision(
        path,
        decision="WAIT",
        rationale="The fee opportunity does not yet repay the recenter cost.",
        decided_at="2026-08-22T06:05:00+00:00",
        prior_observation_sha256=_sha256(observation),
        alternatives=["RECENTER"],
    )
    second = lp_record.append_owner_decision(
        path,
        decision="RECENTER",
        rationale="The owner now accepts the measured recenter cost.",
        decided_at="2026-08-22T07:05:00+00:00",
        prior_observation_sha256=_sha256(observation),
        alternatives=["WAIT"],
    )

    assert first["supersedes_decision_sha256"] is None
    assert second["supersedes_decision_sha256"] == _sha256(first)
    lp_record.verify_history(path)

    history = lp_record.read_history(path)
    if mutation == "alter":
        history[1]["rationale"] = "Hand-edited after the later decision."
    else:
        del history[1]
    path.write_text(
        "".join(json.dumps(record, sort_keys=True) + "\n" for record in history),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="supersedes.*hash"):
        lp_record.verify_history(path)


@pytest.mark.parametrize("corruption", ["valid-json", "invalid-json"])
def test_a_broken_history_does_not_stop_the_next_observation(tmp_path, corruption):
    path = tmp_path / "controlled.jsonl"
    observations = []
    for day in range(7):
        observation = lp_record.observe(
            WALLET,
            TOKEN,
            reporter=lambda *a, **k: _report(),
            now=WHEN + timedelta(days=day),
        )
        lp_record.append(observation, path)
        observations.append(observation)
    decision = lp_record.append_owner_decision(
        path,
        decision="WAIT",
        rationale="The measured fee opportunity does not yet repay the recenter cost.",
        decided_at="2026-08-23T06:05:00+00:00",
        prior_observation_sha256=_sha256(observations[-1]),
        alternatives=["RECENTER"],
    )
    lines = path.read_text(encoding="utf-8").splitlines()
    if corruption == "valid-json":
        third = json.loads(lines[2])
        third["record_version"] = "hand-edited"
        lines[2] = json.dumps(third, sort_keys=True)
    else:
        lines[2] = "{hand-edited"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    ninth = lp_record.observe(
        WALLET,
        TOKEN,
        reporter=lambda *a, **k: _report(),
        now=WHEN + timedelta(days=8),
    )
    lp_record.append(ninth, path)

    written_lines = path.read_text(encoding="utf-8").splitlines()
    assert len(written_lines) == 9
    written_ninth = json.loads(written_lines[-1])
    assert written_ninth["observed_at"] == ninth["observed_at"]
    assert written_ninth["answers_decision_sha256"] == _sha256(decision)
    with pytest.raises(ValueError, match="line 3"):
        lp_record.verify_history(path)
    with pytest.raises(ValueError, match="line 3"):
        lp_record.main(
            [
                "decide",
                "--path",
                str(path),
                "--decision",
                "WAIT",
                "--rationale",
                "A decision must not bind across a damaged history.",
            ]
        )


def test_altering_an_unreferenced_observation_is_not_detected_by_design(tmp_path):
    path = tmp_path / "controlled.jsonl"
    _history_with_decision(path)
    history = lp_record.read_history(path)
    history[0]["altered"] = True
    path.write_text(
        "".join(json.dumps(record, sort_keys=True) + "\n" for record in history),
        encoding="utf-8",
    )

    lp_record.verify_history(path)


def test_decide_subcommand_records_only_the_owner_s_typed_decision(tmp_path):
    path = tmp_path / "controlled.jsonl"
    earlier = lp_record.observe(
        WALLET, TOKEN, reporter=lambda *a, **k: _report(), now=WHEN
    )
    lp_record.append(earlier, path)
    observation = lp_record.observe(
        WALLET,
        TOKEN,
        reporter=lambda *a, **k: _report(),
        now=WHEN + timedelta(days=1),
    )
    lp_record.append(observation, path)

    code = lp_record.main(
        [
            "decide",
            "--path",
            str(path),
            "--decision",
            "WAIT",
            "--rationale",
            "The owner chooses to wait for another observation.",
        ]
    )

    assert code == 0
    decision = lp_record.read_history(path)[-1]
    assert decision["decision"] == "WAIT"
    assert decision["rationale"] == "The owner chooses to wait for another observation."
    assert decision["alternatives"] == []
    assert decision["prior_observation_sha256"] == _sha256(observation)
    assert datetime.fromisoformat(decision["decided_at"]).utcoffset() == timedelta(0)


def test_decide_refuses_a_failed_latest_observation(tmp_path, capsys):
    path = tmp_path / "controlled.jsonl"
    lp_record.append(
        lp_record.observe(WALLET, TOKEN, reporter=lambda *a, **k: _report(), now=WHEN),
        path,
    )

    def _raise(*_args, **_kwargs):
        raise RuntimeError("endpoints down")

    lp_record.append(
        lp_record.observe(WALLET, TOKEN, reporter=_raise, now=WHEN + timedelta(days=1)),
        path,
    )

    with pytest.raises(SystemExit, match="2"):
        lp_record.main(
            [
                "decide",
                "--path",
                str(path),
                "--decision",
                "WAIT",
                "--rationale",
                "This must not bind to a failed day.",
            ]
        )
    assert "latest observation to have observed true" in capsys.readouterr().err
    assert len(lp_record.read_history(path)) == 2


def test_decide_requires_a_report_decision_sentence(tmp_path, capsys):
    path = tmp_path / "controlled.jsonl"
    lp_record.append(
        lp_record.observe(
            WALLET,
            TOKEN,
            reporter=lambda *a, **k: _report(decision="  "),
            now=WHEN,
        ),
        path,
    )

    with pytest.raises(SystemExit, match="2"):
        lp_record.main(
            [
                "decide",
                "--path",
                str(path),
                "--decision",
                "WAIT",
                "--rationale",
                "This must bind to a diagnosis.",
            ]
        )
    assert "report to have a decision sentence" in capsys.readouterr().err


@pytest.mark.parametrize(
    "decided_at", ["2026-08-22T06:05:00", "2026-08-22T07:05:00+01:00"]
)
def test_owner_decision_rejects_a_non_utc_decided_at(tmp_path, decided_at):
    path = tmp_path / "controlled.jsonl"
    observation = lp_record.observe(
        WALLET, TOKEN, reporter=lambda *a, **k: _report(), now=WHEN
    )
    lp_record.append(observation, path)

    with pytest.raises(ValueError, match="ISO-8601 UTC"):
        lp_record.append_owner_decision(
            path,
            decision="WAIT",
            rationale="A timestamp with an explicit UTC offset is required.",
            decided_at=decided_at,
            prior_observation_sha256=_sha256(observation),
            alternatives=["RECENTER"],
        )


def test_owner_decision_rejects_an_empty_rationale(tmp_path):
    path = tmp_path / "controlled.jsonl"
    observation = lp_record.observe(
        WALLET, TOKEN, reporter=lambda *a, **k: _report(), now=WHEN
    )
    lp_record.append(observation, path)

    with pytest.raises(ValueError, match="rationale must be a non-empty string"):
        lp_record.append_owner_decision(
            path,
            decision="WAIT",
            rationale="  ",
            decided_at="2026-08-22T06:05:00+00:00",
            prior_observation_sha256=_sha256(observation),
            alternatives=["RECENTER"],
        )


def test_owner_decision_rejects_the_wrong_token_id(tmp_path):
    path = tmp_path / "controlled.jsonl"
    observation = lp_record.observe(
        WALLET, TOKEN, reporter=lambda *a, **k: _report(), now=WHEN
    )
    lp_record.append(observation, path)

    with pytest.raises(ValueError, match=f"token_id must be {TOKEN}"):
        lp_record.append(
            {
                "record_version": "lp-record.v1",
                "kind": "owner_decision",
                "decision": "WAIT",
                "rationale": "This record names a different position.",
                "decided_at": "2026-08-22T06:05:00+00:00",
                "prior_observation_sha256": _sha256(observation),
                "supersedes_decision_sha256": None,
                "alternatives": ["RECENTER"],
                "token_id": TOKEN + 1,
            },
            path,
        )


def test_top_level_help_lists_both_subcommands(capsys):
    with pytest.raises(SystemExit, match="0"):
        lp_record.main(["--help"])

    help_text = capsys.readouterr().out
    assert "observe" in help_text
    assert "decide" in help_text


def test_owner_decision_rejects_a_value_outside_the_owner_choices(tmp_path):
    path = tmp_path / "controlled.jsonl"
    observation = lp_record.observe(
        WALLET, TOKEN, reporter=lambda *a, **k: _report(), now=WHEN
    )
    lp_record.append(observation, path)

    with pytest.raises(ValueError, match="WAIT or RECENTER"):
        lp_record.append_owner_decision(
            path,
            decision="SELL",
            rationale="Not an allowed decision.",
            decided_at="2026-08-22T06:05:00+00:00",
            prior_observation_sha256=_sha256(observation),
            alternatives=[],
        )
