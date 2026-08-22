import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from docket.advantage import record_run
from docket.hire.receipts import canonical_hash


RECORDED_RUNS = (
    Path(__file__).resolve().parents[1] / "docket" / "advantage" / "recorded_runs"
)
NO_PAIR = "single recorded read; no paired run against a person"


def _health_result(*, complete=True):
    return {
        "address": "0x0000000000000000000000000000000000000001",
        "account": {
            "as_of_block": 123,
            "complete": complete,
            "markets_entered": 2,
            "markets_listed": 52,
            "rows": [
                {"symbol": "vUSDT", "borrow_balance": "10"},
                {"symbol": "vUSDC", "borrow_balance": "0"},
            ],
        },
        "assessment": {"status": "borrowing_with_headroom"},
        "actions": [],
        "submitted": False,
        "why_not_submitted": "This is a read-only preview.",
    }


def _grid_result():
    return {
        "plan": {"requested_levels": 2},
        "wallet": "0x0000000000000000000000000000000000000001",
        "observation": {"block_number": 456, "source": "router.getAmountsOut"},
        "levels": [
            {"intent": {"calldata_hash": "0x01"}, "simulation": {"agrees": True}},
            {"intent": {"calldata_hash": "0x02"}, "simulation": {"agrees": True}},
        ],
        "submitted": False,
        "why_not_submitted": "This is a read-only preview.",
    }


def _yield_result():
    return {
        "current": {"pool_id": "0xpool"},
        "candidates": [{"pool_id": "0xpool"}],
        "universe": {
            "size": 1,
            "considered": 3,
            "source": "https://explorer.pancakeswap.com/top",
            "observed_at": "2026-08-22T12:00:00+00:00",
        },
        "submitted": False,
        "why_not_submitted": "This is a comparison-only read.",
    }


def _clock():
    return datetime(2026, 8, 22, 12, 0, tzinfo=timezone.utc)


def test_record_uses_the_catalogue_runner_and_writes_the_existing_record_shape(
    tmp_path, monkeypatch
):
    payload = {"wallet": "0x0000000000000000000000000000000000000001"}
    result = _health_result()
    calls = []

    def run(received):
        calls.append(received)
        return result

    monkeypatch.setattr(
        record_run,
        "get_service",
        lambda service_id: SimpleNamespace(id=service_id, run=run),
    )
    ticks = iter((10.0, 12.5))
    monkeypatch.setattr(record_run.time, "perf_counter", lambda: next(ticks))
    out = tmp_path / "health.json"

    body = record_run.record("health-guard", payload, out_path=out, clock=_clock)

    assert calls == [payload]
    assert set(body) == {
        "agent_arm",
        "category",
        "manual_arm",
        "manual_steps",
        "notes",
        "question",
        "task_id",
    }
    arm = body["agent_arm"]
    assert arm["seconds"] == 2.5
    assert arm["error"] is None
    assert arm["output"]["request"] == payload
    assert arm["output"]["result"] == result
    assert arm["output"]["receipt"]["input_hash"] == canonical_hash(payload)
    assert arm["output"]["receipt"]["output_hash"] == canonical_hash(result)
    assert arm["output_hash"] == canonical_hash(arm["output"])
    assert arm["output"]["observation"]["block"] == 123
    assert NO_PAIR in arm["output"]["observation"]["window"]
    assert body["manual_arm"]["error"] == NO_PAIR
    assert body["manual_arm"]["output"] is None
    assert out.read_text(encoding="utf-8") == (
        json.dumps(body, sort_keys=True, indent=2, ensure_ascii=False) + "\n"
    )


@pytest.mark.parametrize(
    ("service_id", "result", "block", "observed_at"),
    [
        ("grid-operator", _grid_result(), 456, "2026-08-22T12:00:00+00:00"),
        (
            "yield-router",
            _yield_result(),
            None,
            "2026-08-22T12:00:00+00:00",
        ),
    ],
)
def test_record_captures_each_service_observation_without_inventing_a_block(
    tmp_path, monkeypatch, service_id, result, block, observed_at
):
    monkeypatch.setattr(
        record_run,
        "get_service",
        lambda requested: SimpleNamespace(id=requested, run=lambda payload: result),
    )
    ticks = iter((1.0, 1.25))
    monkeypatch.setattr(record_run.time, "perf_counter", lambda: next(ticks))

    body = record_run.record(
        service_id, {}, out_path=tmp_path / f"{service_id}.json", clock=_clock
    )
    observation = body["agent_arm"]["output"]["observation"]

    assert observation["block"] == block
    assert observation["observed_at"] == observed_at
    assert observation["method"].strip()
    assert observation["population"].strip()
    assert observation["does_not_show"].strip()


@pytest.mark.parametrize(
    ("service_id", "result"),
    [
        ("health-guard", {}),
        ("health-guard", {"error": "upstream failed", "note": "read failed"}),
        ("health-guard", _health_result(complete=False)),
        ("grid-operator", {"levels": [], "why_not_submitted": "no result"}),
        (
            "yield-router",
            {
                "universe": {"size": 0, "considered": 0},
                "candidates": [],
                "why_not_submitted": "no result",
            },
        ),
    ],
)
def test_record_refuses_error_or_empty_service_results(
    tmp_path, monkeypatch, service_id, result
):
    monkeypatch.setattr(
        record_run,
        "get_service",
        lambda requested: SimpleNamespace(id=requested, run=lambda payload: result),
    )
    out = tmp_path / "refused.json"

    with pytest.raises(ValueError, match="refused"):
        record_run.record(service_id, {}, out_path=out, clock=_clock)

    assert not out.exists()


def test_committed_category_reads_are_hash_bound_single_runs():
    expected = {
        "health-guard": "05-health-guard-read.json",
        "grid-operator": "06-grid-preview-read.json",
        "yield-router": "07-yield-router-read.json",
    }
    assert {path.name for path in RECORDED_RUNS.glob("*.json")} == set(
        expected.values()
    )

    for service_id, filename in expected.items():
        body = json.loads((RECORDED_RUNS / filename).read_text(encoding="utf-8"))
        arm = body["agent_arm"]
        receipt = arm["output"]["receipt"]
        request = arm["output"]["request"]
        result = arm["output"]["result"]
        assert receipt["service"] == service_id
        assert receipt["input_hash"] == canonical_hash(request)
        assert receipt["output_hash"] == canonical_hash(result)
        assert arm["output_hash"] == canonical_hash(arm["output"])
        assert arm["seconds"] > 0
        assert arm["error"] is None
        assert body["manual_arm"] == {
            "cost": None,
            "error": NO_PAIR,
            "name": "manual",
            "output": None,
            "output_hash": None,
            "seconds": None,
        }
        observation = arm["output"]["observation"]
        assert NO_PAIR in observation["window"]
        for field in ("observed_at", "population", "method", "does_not_show"):
            assert observation[field].strip(), f"{service_id} missing {field}"

    health = json.loads(
        (RECORDED_RUNS / expected["health-guard"]).read_text(encoding="utf-8")
    )
    health_result = health["agent_arm"]["output"]["result"]
    assert health_result["account"]["complete"] is True
    assert any(
        int(row["borrow_balance"]) > 0 for row in health_result["account"]["rows"]
    )
    assert health["agent_arm"]["output"]["observation"]["block"] > 0


def test_recorded_runs_are_declared_as_package_data():
    pyproject = (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text(
        encoding="utf-8"
    )
    assert '"recorded_runs/*.json"' in pyproject


def test_reproduction_docs_name_all_three_commands_hashes_and_archive_boundary():
    docs = (
        Path(__file__).resolve().parents[1] / "docs" / "evidence-reproduction.md"
    ).read_text(encoding="utf-8")
    section = docs[docs.index("## Recorded category runs") :]
    for service_id in ("health-guard", "grid-operator", "yield-router"):
        assert f"record_run {service_id}" in section
    for phrase in (
        "input_hash",
        "output_hash",
        "canonical_hash",
        "DOCKET_ARCHIVE_RPC",
        "single recorded read",
        "no paired run against a person",
    ):
        assert phrase in section
