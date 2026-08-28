"""The v3 report is one startup snapshot with two representations, never two accounts."""

from copy import deepcopy

import pytest
from fastapi.testclient import TestClient

from docket.advantage.v3 import page, report, report_snapshot
from docket.api import create_app
from docket.hire import catalogue
from docket.store import Store


@pytest.fixture(autouse=True)
def reset_report_snapshot():
    report_snapshot._reset_for_testing()
    yield
    report_snapshot._reset_for_testing()


@pytest.fixture
def client(tmp_path):
    db = tmp_path / "v3.sqlite3"
    store = Store(db)
    snapshot = store.begin_snapshot(chain_id=56, expected=0)
    store.finish_snapshot(snapshot, sampled=0, expected=0)
    return TestClient(create_app(db, snapshot_id=snapshot))


def test_the_current_surface_shows_the_complete_unscored_family_and_never_says_proved(
    client,
):
    document = client.get("/advantage/v3.json")
    rendered = client.get("/advantage/v3", headers={"accept": "text/html"})
    payload = document.json()

    assert document.status_code == 200
    assert rendered.status_code == 200
    assert rendered.headers["content-type"].startswith("text/html")
    assert [family["state"] for family in payload["families"]] == [
        report.SUPERSEDED_BEFORE_INPUT_LOCK,
        report.LOCKED_NOT_RUN,
        report.SUPERSEDED_BEFORE_INPUT_LOCK,
        report.COMPLETE_UNSCORED,
        report.LOCKED_NOT_RUN,
    ]
    v4 = next(
        family
        for family in payload["families"]
        if family["spec_id"] == "v3-04-warden-security"
    )
    assert v4["unscored_reason"] == "score_sheets_missing"
    assert v4["run_progress"] == {
        "scheduled_primaries": 24,
        "claimed_primaries": 24,
        "terminal_primaries": 24,
        "outcomes": {"failed": 1, "succeeded": 23},
    }
    assert rendered.text.count(report.LOCKED_NOT_RUN) >= 2
    assert report.COMPLETE_UNSCORED in rendered.text
    assert report.SUPERSEDED_BEFORE_INPUT_LOCK in rendered.text
    assert "if reconstruction fails, both surfaces report the error explicitly" in rendered.text
    assert "<title>Agent advantage report v3 — Docket</title>" in rendered.text
    assert (
        "Every scheduled primary has a terminal ledger event; required scoring artifacts "
        "are absent, so rubric quality and the registered falsifier remain unavailable."
        in rendered.text
    )
    for body in (document.text, rendered.text):
        assert "proved" not in body.lower()

    family_page = client.get("/advantage/v3/v3-04-warden-security").text
    assert "<title>v3-04-warden-security — Docket</title>" in family_page
    assert "1 failed; 23 succeeded" in family_page
    assert '{&quot;failed&quot;: 1, &quot;succeeded&quot;: 23}' not in family_page
    assert (
        "No terminal outcomes."
        in client.get("/advantage/v3/v3-02-yield-router").text
    )


def test_openapi_names_every_v3_state(client):
    description = client.get("/openapi.json").json()["paths"]["/advantage/v3.json"][
        "get"
    ]["description"]

    assert report.SUPERSEDED_BEFORE_INPUT_LOCK in description


def test_the_report_is_built_once_and_both_routes_use_that_startup_payload(
    tmp_path, monkeypatch
):
    payload = deepcopy(report.report())
    payload["families"][0]["spec"]["question"] = "startup-only sentinel"
    calls = []

    def build_report():
        calls.append("built")
        return payload

    monkeypatch.setattr(report_snapshot.report_module, "report", build_report)
    db = tmp_path / "startup.sqlite3"
    app = create_app(db)
    client = TestClient(app)

    assert calls == ["built"]
    for _ in range(2):
        assert (
            client.get("/advantage/v3.json").json()["families"][0]["spec"]["question"]
            == "startup-only sentinel"
        )
        assert (
            "startup-only sentinel"
            in client.get("/advantage/v3/v3-01-range-doctor").text
        )
        assert (
            catalogue._measured_value("range-doctor", 1.0)["benchmark_state"]
            == report.LOCKED_NOT_RUN
        )
        assert report_snapshot.get_report() is payload
    assert calls == ["built"]


def test_v3_report_failure_is_pinned_and_served_without_killing_health(
    tmp_path, monkeypatch
):
    calls = []

    def fail_report():
        calls.append("failed")
        raise PermissionError("synthetic startup report failure")

    monkeypatch.setattr(report_snapshot.report_module, "report", fail_report)
    db = tmp_path / "startup-report-failure.sqlite3"
    store = Store(db)
    snapshot = store.begin_snapshot(chain_id=56, expected=0)
    store.finish_snapshot(snapshot, sampled=0, expected=0)

    app = create_app(db, snapshot_id=snapshot)
    client = TestClient(app)

    assert client.get("/health").status_code == 200
    assert client.get("/health").json()["status"] == "ok"
    expected = {
        "error": {
            "code": "advantage_v3_unavailable",
            "message": (
                "The v3 report could not be reconstructed at process startup. "
                "This process is serving no v3 family state."
            ),
        }
    }
    for _ in range(2):
        document = client.get("/advantage/v3.json")
        rendered = client.get("/advantage/v3", headers={"accept": "text/html"})

        assert document.status_code == 503
        assert document.json() == expected
        assert rendered.status_code == 503
        assert "V3 report unavailable" in rendered.text
        assert "advantage_v3_unavailable" in rendered.text
        assert expected["error"]["message"] in rendered.text
        assert "synthetic startup report failure" not in rendered.text
        assert 'id="v3-01-range-doctor"' not in rendered.text

    measured = catalogue._measured_value("range-doctor", 1.0)
    assert measured["benchmark_state"] is None
    assert measured["report_url"] is None
    assert calls == ["failed"]


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
        (
            report.RUNNING,
            "Expired deadlines are shown as stale; this report does not repair the ledger.",
        ),
        (
            report.COMPLETE_UNSCORED,
            "Every scheduled primary has a terminal ledger event; required scoring artifacts "
            "are absent, so rubric quality and the registered falsifier remain unavailable.",
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
        assert "v3-05-range-doctor" in body, path
        assert "v3-01-range-doctor" in body, path


def test_the_root_index_adds_v3_without_moving_the_prior_reports(client):
    index = client.get("/", headers={"accept": "application/json"}).json()

    assert index["advantage"] == "/advantage.json"
    assert index["advantage_v2"] == "/advantage/v2.json"
    assert index["advantage_v3"] == "/advantage/v3.json"
