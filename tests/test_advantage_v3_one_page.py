"""One table over every registered task, derived and verdict-free.

The point of the table is that a reader can see all three reports at once without any of
them being restated. So these tests check two things: that every published figure equals the
committed artifact it came from, and that nothing in the table ranks anything.
"""

import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from docket.advantage.v2 import report as v2_report
from docket.advantage.v3 import report as v3_report
from docket.advantage.v3 import report_snapshot
from docket.api import create_app
from docket.api.advantage_pages import v3_landing
from docket.store import Store

ROOT = Path(__file__).resolve().parents[1]
V1_DIR = ROOT / "docket/advantage/experiments"
SHELL = ROOT / "docket/api/web/advantage-v3.html"
# `tests/test_advantage_report.py` forbids these across the advantage surface; the one-page
# table publishes measures beside each other and must never rank them.
VERDICT_WORDS = ("best", "superior", "proves", "guaranteed", "winner", "recommended")


@pytest.fixture(scope="module")
def payload():
    return v3_report.report()


@pytest.fixture(autouse=True)
def reset_report_snapshot():
    report_snapshot._reset_for_testing()
    yield
    report_snapshot._reset_for_testing()


def _rows(payload, version):
    return [
        row
        for row in payload["summary"]["one_page"]["rows"]
        if row["version"] == version
    ]


def test_the_summary_carries_one_row_for_every_registered_task(payload):
    one_page = payload["summary"]["one_page"]

    assert one_page["verdict"] is None
    assert "No verdict is computed" in one_page["note"]
    assert one_page["n_rows"] == len(one_page["rows"])
    assert [row["task"] for row in _rows(payload, "v1")] == list(v3_report.V1_TASK_IDS)
    assert [row["task"] for row in _rows(payload, "v2")] == [
        experiment["experiment_id"] for experiment in v2_report.experiments()
    ]
    assert [row["task"] for row in _rows(payload, "v3")] == [
        family["spec_id"] for family in payload["families"]
    ]
    assert one_page["n_rows"] == 3 + len(v2_report.experiments()) + len(
        payload["families"]
    )


def test_every_row_carries_the_registered_fields(payload):
    required = {
        "version",
        "task",
        "category",
        "arms",
        "n_planned",
        "n_terminal",
        "median_agent_seconds",
        "median_manual_seconds",
        "cost_by_arm",
        "quality_by_arm",
        "quality_measure",
        "state",
        "unavailable",
    }

    for row in payload["summary"]["one_page"]["rows"]:
        assert set(row) == required, row["task"]
        assert isinstance(row["category"], str) and row["category"].strip()
        assert isinstance(row["arms"], list)
        for field, reason in row["unavailable"].items():
            assert field in required
            assert isinstance(reason, str) and reason.strip()


def test_v1_rows_equal_their_committed_records(payload):
    for row in _rows(payload, "v1"):
        record = json.loads(
            (V1_DIR / f"{row['task']}.json").read_text(encoding="utf-8")
        )
        assert row["category"] == record["category"]
        assert row["median_agent_seconds"] == record["agent_arm"]["seconds"]
        assert row["median_manual_seconds"] == record["manual_arm"]["seconds"]
        assert row["cost_by_arm"]["agent"] == record["agent_arm"]["cost"]
        assert row["cost_by_arm"]["manual"] == record["manual_arm"]["cost"]
        # v1 refuses to grade its own arms, and the table says so rather than inventing one.
        assert set(row["quality_by_arm"].values()) == {None}
        assert "marking its own homework" in row["unavailable"]["quality_by_arm"]


def test_a_missing_v1_record_is_refused_rather_than_dropped(tmp_path, payload):
    """A short table that looks complete is worse than a loud failure."""
    (tmp_path / "01-liquidity.json").write_text(
        (V1_DIR / "01-liquidity.json").read_text(encoding="utf-8"), encoding="utf-8"
    )

    with pytest.raises(ValueError, match="one-page table cannot omit a registered task"):
        v3_report.one_page(payload["families"], v1_dir=tmp_path)


def test_a_v2_read_failure_degrades_the_table_instead_of_failing_the_route(
    monkeypatch, payload
):
    """`/advantage/v3.json` is the v3 report; a v2 artifact fault must not take it down."""
    import docket.advantage.v2.report as v2_module

    def explode():
        raise RuntimeError("corpus unreadable")

    monkeypatch.setattr(v2_module, "experiments", explode)
    table = v3_report.one_page(payload["families"])

    assert [row["version"] for row in table["rows"]].count("v2") == 0
    assert "corpus unreadable" in table["degraded"]["v2"]
    assert "could not be rebuilt" in table["degraded"]["v2"]
    assert table["verdict"] is None
    assert table["n_rows"] == len(table["rows"])
    # The v1 and v3 rows still publish in full.
    assert [row["version"] for row in table["rows"]].count("v3") == len(
        payload["families"]
    )


def test_v2_quality_is_never_a_nested_object(payload):
    for row in _rows(payload, "v2"):
        for value in row["quality_by_arm"].values():
            assert value is None
        assert row["n_terminal"] is None
        assert "terminal-primary count" in row["unavailable"]["n_terminal"]
    scored = [row for row in _rows(payload, "v2") if row["quality_measure"]]
    assert scored, "at least one v2 experiment publishes scores worth pointing at"
    for row in scored:
        assert "scores block" in row["quality_measure"]


def test_the_rendered_column_names_both_denominators(payload):
    rendered = v3_landing(SHELL.read_text(encoding="utf-8"), payload)

    assert "Planned cases / terminal primaries" in rendered
    assert "Planned / terminal<" not in rendered


def test_v2_rows_equal_their_computed_experiments(payload):
    by_id = {
        experiment["experiment_id"]: experiment
        for experiment in v2_report.experiments()
    }

    for row in _rows(payload, "v2"):
        experiment = by_id[row["task"]]
        assert row["category"] == experiment["spec"]["category"]
        assert row["n_planned"] == experiment["spec"]["n_planned"]
        assert row["state"] == (
            v3_report.REFUTED
            if experiment["falsifier_result"]["refuted"]
            else v3_report.NOT_REFUTED
        )
        # v2 has no clock on either arm, so both medians are null with the reason attached.
        assert row["median_agent_seconds"] is None
        assert row["median_manual_seconds"] is None
        assert (
            "no per-arm elapsed seconds" in row["unavailable"]["median_agent_seconds"]
        )


def test_v3_rows_equal_their_family_objects(payload):
    by_id = {family["spec_id"]: family for family in payload["families"]}

    for row in _rows(payload, "v3"):
        family = by_id[row["task"]]
        assert row["state"] == family["state"]
        assert row["category"] == family["spec"]["category"]
        assert row["n_planned"] == family["spec"]["n_planned"]
        if family["run_progress"] is None:
            assert row["n_terminal"] is None
        else:
            assert row["n_terminal"] == family["run_progress"]["terminal_primaries"]
        if family["speed"] is None:
            assert row["median_agent_seconds"] is None
            assert row["median_manual_seconds"] is None
            assert row["unavailable"]["median_agent_seconds"]
        else:
            assert (
                row["median_agent_seconds"] == family["speed"]["agent_median_seconds"]
            )
        if family["quality"] is None:
            assert set(row["quality_by_arm"].values()) == {None}
            assert row["quality_measure"] is None
            assert row["unavailable"]["quality_by_arm"]
        else:
            assert (
                row["quality_by_arm"]["agent"]
                == (family["quality"]["arms"]["agent"]["median_total"])
            )


def test_an_unscored_family_publishes_its_reason_rather_than_a_number(payload):
    unscored = next(
        row
        for row in _rows(payload, "v3")
        if row["state"] == v3_report.COMPLETE_UNSCORED
    )
    family = next(
        item for item in payload["families"] if item["spec_id"] == unscored["task"]
    )

    assert set(unscored["quality_by_arm"].values()) == {None}
    assert unscored["unavailable"]["quality_by_arm"] == family["unscored_reason"]


def test_the_new_families_appear_registered_and_waiting(payload):
    rows = {row["task"]: row for row in _rows(payload, "v3")}

    for spec_id in ("v3-08-yield-router", "v3-09-health-guard"):
        row = rows[spec_id]
        assert row["state"] == v3_report.REGISTERED_WAITING
        assert row["arms"] == ["agent", "manual"]
        assert row["n_planned"] == 3
        assert row["n_terminal"] is None
    assert rows["v3-09-health-guard"]["category"] == "health factor"


def test_the_table_never_ranks_anything(payload):
    body = json.dumps(payload["summary"]["one_page"]).lower()

    for word in VERDICT_WORDS:
        assert word not in body, word


def test_the_landing_page_renders_the_table_before_the_family_index(payload):
    rendered = v3_landing(SHELL.read_text(encoding="utf-8"), payload)

    assert "Every registered task on one page" in rendered
    assert rendered.index("Every registered task on one page") < rendered.index(
        "registered families</h2>"
    )
    for row in payload["summary"]["one_page"]["rows"]:
        assert row["task"] in rendered
    text = re.sub(r"<[^>]+>", " ", rendered).lower()
    for word in VERDICT_WORDS:
        assert word not in text, word


def test_the_json_route_serves_the_same_table(tmp_path):
    db = tmp_path / "one-page.sqlite3"
    store = Store(db)
    snapshot = store.begin_snapshot(chain_id=56, expected=0)
    store.finish_snapshot(snapshot, sampled=0, expected=0)
    client = TestClient(create_app(db, snapshot_id=snapshot))

    served = client.get("/advantage/v3.json").json()
    rendered = client.get("/advantage/v3", headers={"accept": "text/html"})

    assert served["summary"]["one_page"]["verdict"] is None
    assert served["summary"]["one_page"]["n_rows"] == len(
        served["summary"]["one_page"]["rows"]
    )
    assert rendered.status_code == 200
    assert "Every registered task on one page" in rendered.text
