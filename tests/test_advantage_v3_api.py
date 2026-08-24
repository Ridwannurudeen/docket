"""The v3 report is one startup snapshot with two representations, never two accounts."""

from copy import deepcopy

import pytest
from fastapi.testclient import TestClient

import docket.api.routes as routes_module
from docket.advantage.v3 import page, report
from docket.api import create_app
from docket.store import Store


@pytest.fixture
def client(tmp_path):
    db = tmp_path / "v3.sqlite3"
    store = Store(db)
    snapshot = store.begin_snapshot(chain_id=56, expected=0)
    store.finish_snapshot(snapshot, sampled=0, expected=0)
    return TestClient(create_app(db, snapshot_id=snapshot))


def test_the_current_surface_waits_for_inputs_and_never_says_proved(client):
    document = client.get("/advantage/v3.json")
    rendered = client.get("/advantage/v3", headers={"accept": "text/html"})

    assert document.status_code == 200
    assert rendered.status_code == 200
    assert rendered.headers["content-type"].startswith("text/html")
    assert [family["state"] for family in document.json()["families"]] == [
        report.REGISTERED_WAITING,
        report.REGISTERED_WAITING,
        report.SUPERSEDED_BEFORE_INPUT_LOCK,
        report.REGISTERED_WAITING,
    ]
    assert rendered.text.count(report.REGISTERED_WAITING) >= 3
    assert report.SUPERSEDED_BEFORE_INPUT_LOCK in rendered.text
    assert "No input artifact is locked. No arm has run." in rendered.text
    for body in (document.text, rendered.text):
        assert "proved" not in body.lower()


def test_the_report_is_built_once_and_both_routes_use_that_startup_payload(
    tmp_path, monkeypatch
):
    payload = deepcopy(report.report())
    payload["families"][0]["spec"]["question"] = "startup-only sentinel"
    calls = []

    def build_report():
        calls.append("built")
        return payload

    monkeypatch.setattr(routes_module, "advantage_v3_report", build_report)
    db = tmp_path / "startup.sqlite3"
    app = create_app(db)
    client = TestClient(app)

    assert calls == ["built"]
    for _ in range(2):
        assert (
            client.get("/advantage/v3.json").json()["families"][0]["spec"]["question"]
            == "startup-only sentinel"
        )
        assert "startup-only sentinel" in client.get("/advantage/v3").text
    assert calls == ["built"]


@pytest.mark.parametrize(
    ("state", "statement"),
    (
        (report.REGISTERED_WAITING, "No input artifact is locked. No arm has run."),
        (
            report.SUPERSEDED_BEFORE_INPUT_LOCK,
            "A later pilot-informed registration superseded this unlocked family. No arm ran.",
        ),
        (
            report.LOCKED_NOT_RUN,
            "Inputs are locked. No primary attempt has been claimed.",
        ),
        (report.RUNNING, "The claim-once ledger has work in progress."),
        (
            report.COMPLETE_UNSCORED,
            "Every scheduled primary has a terminal ledger event; performance remains unscored.",
        ),
        (
            report.REFUTED,
            "At least one registered falsifier check fired; the registered claim is refuted.",
        ),
        (
            report.NOT_REFUTED,
            "No registered falsifier check fired. This state is bounded to the registered claim.",
        ),
    ),
)
def test_every_registered_state_has_bounded_page_language(state, statement):
    payload = deepcopy(report.report())
    payload["summary"]["states"] = {state: len(payload["families"])}
    for family in payload["families"]:
        family["state"] = state
        if state != report.REGISTERED_WAITING:
            family["run_progress"] = {
                "scheduled_primaries": family["spec"]["n_planned"] * 2,
                "claimed_primaries": 0,
                "terminal_primaries": 0,
                "outcomes": {},
            }
        if state == report.COMPLETE_UNSCORED:
            family["unscored_reason"] = "score_sheets_missing"
        if state in {report.REFUTED, report.NOT_REFUTED}:
            family["falsifier_result"] = {
                "refuted": state == report.REFUTED,
                "checks": [],
            }

    rendered = page.render(payload)

    assert rendered.count(state) >= len(payload["families"])
    assert statement in rendered
    assert "proved" not in rendered.lower()


def test_report_values_are_escaped_before_they_reach_html():
    payload = deepcopy(report.report())
    payload["families"][0]["spec"]["question"] = '<script data-x="1">run()</script>'

    rendered = page.render(payload)

    assert '<script data-x="1">' not in rendered
    assert "&lt;script data-x=&quot;1&quot;&gt;run()&lt;/script&gt;" in rendered


def test_a_shell_without_the_record_marker_is_refused():
    with pytest.raises(ValueError, match="records have nowhere to go"):
        page.fill("<html><body></body></html>", report.report())


def test_both_agent_facing_documents_name_both_v3_routes(client):
    for path in ("/llms.txt", "/skill.md"):
        body = client.get(path).text
        assert "/advantage/v3.json" in body, path
        assert "/advantage/v3" in body, path


def test_the_root_index_adds_v3_without_moving_the_prior_reports(client):
    index = client.get("/", headers={"accept": "application/json"}).json()

    assert index["advantage"] == "/advantage.json"
    assert index["advantage_v2"] == "/advantage/v2.json"
    assert index["advantage_v3"] == "/advantage/v3.json"
