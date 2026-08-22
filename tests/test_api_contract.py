import json
from pathlib import Path

import pydantic
from fastapi.testclient import TestClient

from docket.api import create_app
from docket.api import routes
from docket.api.models import (
    BANNED_FIELD_NAMES,
    AgentDetail,
    AgentSummary,
    CatalogueResponse,
    CategoryListing,
    CategoryResponse,
    Coverage,
    EvidenceLink,
    ListResponse,
    MetricFigure,
    RefreshStatus,
    ServiceCard,
    ServiceDetail,
    ServiceListing,
    ServicesResponse,
    StatsResponse,
)
from docket.store import Store

ALL_MODELS = [
    Coverage,
    AgentSummary,
    AgentDetail,
    ListResponse,
    RefreshStatus,
    StatsResponse,
    ServiceListing,
    CatalogueResponse,
    MetricFigure,
    EvidenceLink,
    ServiceCard,
    ServiceDetail,
    ServicesResponse,
    CategoryListing,
    CategoryResponse,
]


def _field_names(model: type[pydantic.BaseModel]) -> set[str]:
    return set(model.model_fields)


def test_no_model_exposes_a_verdict_field():
    """Docket serves observations. A verdict field would make it an authority it has not earned."""
    for model in ALL_MODELS:
        offending = _field_names(model) & BANNED_FIELD_NAMES
        assert not offending, f"{model.__name__} exposes verdict field(s): {offending}"


def test_banned_names_cover_the_obvious_temptations():
    for name in (
        "safe",
        "trusted",
        "verified_by_docket",
        "recommended",
        "rank",
        "trust_score",
    ):
        assert name in BANNED_FIELD_NAMES


def test_the_word_a_marketplace_reaches_for_first_is_banned_too():
    """ "Best" is the one a shop front wants and the one Docket has least standing to say:
    it ranks nothing, so it cannot know. It was honoured in the copy rules and missing from
    the set the tests actually iterate, which left the value-level scans blind to it."""
    assert "best" in BANNED_FIELD_NAMES


def test_every_statistic_carries_its_coverage():
    """StatsResponse must not be able to report a count without the snapshot it came from."""
    required = {
        "snapshot_id",
        "captured_at",
        "snapshot_age_seconds",
        "sampled",
        "expected",
        "dropped",
    }
    assert required <= _field_names(Coverage)
    assert "coverage" in _field_names(StatsResponse)
    assert "refresh_status" in _field_names(StatsResponse)
    assert Coverage.model_fields["snapshot_id"].is_required()
    assert StatsResponse.model_fields["refresh_status"].is_required()


def test_list_response_states_its_coverage_too():
    assert "coverage" in _field_names(ListResponse)


def test_agent_summary_uses_observation_language():
    names = _field_names(AgentSummary)
    assert {"has_feedback", "declares_callable"} <= names


def test_agent_detail_carries_timestamped_observations():
    names = _field_names(AgentDetail)
    assert "observations" in names
    assert "endpoints" in names


def test_a_metric_cannot_be_served_without_the_way_it_was_measured():
    """The marketplace layer inherits the coverage discipline: a figure with no window,
    no date and no method is a number nobody can date or contest."""
    names = _field_names(MetricFigure)
    assert {"window", "observed_at", "method", "numerator", "denominator"} <= names
    for required in ("window", "observed_at", "method"):
        assert MetricFigure.model_fields[required].is_required(), required


def test_a_service_states_what_it_cannot_do():
    """`limitations` is required on the detail model, so a service cannot be published
    with the sentence a marketplace is most tempted to leave out."""
    assert "limitations" in _field_names(ServiceDetail)
    assert ServiceDetail.model_fields["limitations"].is_required()


def test_a_service_listing_declares_its_order_rather_than_implying_one():
    """An undeclared order is where an invented ranking hides."""
    assert "ordering" in _field_names(ServicesResponse)
    assert ServicesResponse.model_fields["ordering"].is_required()


def test_a_category_can_say_it_is_empty_and_must_say_which_it_is():
    names = _field_names(CategoryListing)
    assert {"service_count", "empty"} <= names
    # No default: a category serving no `empty` at all could be a bare shelf that says
    # nothing, which is the exact failure the field exists to prevent.
    assert CategoryListing.model_fields["empty"].is_required()


def test_the_service_layer_carries_the_identity_it_is_bound_to_or_says_it_is_not():
    names = _field_names(ServiceDetail)
    assert {"agent_id", "identity", "identity_note", "agent_path"} <= names
    assert ServiceDetail.model_fields["identity"].is_required()


def test_service_detail_redirects_html_callers_without_changing_json(tmp_path):
    client = TestClient(
        create_app(tmp_path / "services.sqlite3"), follow_redirects=False
    )

    page = client.get(
        "/services/range-doctor", headers={"Accept": "text/html,application/xhtml+xml"}
    )
    data = client.get("/services/range-doctor", headers={"Accept": "application/json"})

    assert page.status_code == 302
    assert page.headers["location"] == "/service?id=range-doctor"
    assert data.status_code == 200
    assert data.json()["service_id"] == "range-doctor"


def test_lp_record_returns_stored_observations_in_file_order(tmp_path, monkeypatch):
    path = tmp_path / "controlled.jsonl"
    history = [
        {"record_version": "lp-record.v1", "observed_at": "2026-08-21T00:00:00Z"},
        {"record_version": "lp-record.v1", "observed_at": "2026-08-22T00:00:00Z"},
    ]
    path.write_text(
        "".join(json.dumps(observation) + "\n" for observation in history),
        encoding="utf-8",
    )
    monkeypatch.setenv("DOCKET_LP_RECORD_PATH", str(path))
    client = TestClient(create_app(tmp_path / "lp.sqlite3"))

    response = client.get("/lp-record")

    assert response.status_code == 200
    assert response.json() == {
        "lines": history,
        "skipped_unparsable": 0,
        "truncated": False,
    }
    assert "/lp-record" in client.get("/openapi.json").json()["paths"]


def test_lp_record_skips_and_counts_every_unparsable_line(tmp_path, monkeypatch):
    path = tmp_path / "mixed.jsonl"
    path.write_bytes(
        b'{"ordinal":1}\n\nNOT JSON\n\xff\nNaN\nInfinity\n"\\ud800"\n{"ordinal":2}\n'
    )
    monkeypatch.setenv("DOCKET_LP_RECORD_PATH", str(path))
    client = TestClient(create_app(tmp_path / "mixed.sqlite3"))

    response = client.get("/lp-record")

    assert response.status_code == 200
    assert response.json() == {
        "lines": [{"ordinal": 1}, {"ordinal": 2}],
        "skipped_unparsable": 5,
        "truncated": False,
    }


def test_lp_record_missing_file_is_an_empty_bounded_history(tmp_path, monkeypatch):
    monkeypatch.setenv("DOCKET_LP_RECORD_PATH", str(tmp_path / "missing.jsonl"))
    client = TestClient(create_app(tmp_path / "missing.sqlite3"))

    response = client.get("/lp-record")

    assert response.status_code == 200
    assert response.json() == {
        "lines": [],
        "skipped_unparsable": 0,
        "truncated": False,
    }


def test_lp_record_disappearing_before_open_is_an_empty_bounded_history(
    tmp_path, monkeypatch
):
    path = tmp_path / "rotated.jsonl"
    path.write_text('{"ordinal":1}\n', encoding="utf-8")
    monkeypatch.setenv("DOCKET_LP_RECORD_PATH", str(path))
    client = TestClient(create_app(tmp_path / "rotated.sqlite3"))
    original_open = Path.open

    def disappear_before_open(candidate, *args, **kwargs):
        if candidate == path:
            raise FileNotFoundError(path)
        return original_open(candidate, *args, **kwargs)

    monkeypatch.setattr(Path, "open", disappear_before_open)

    response = client.get("/lp-record")

    assert response.status_code == 200
    assert response.json() == {
        "lines": [],
        "skipped_unparsable": 0,
        "truncated": False,
    }


def test_lp_record_line_cap_marks_only_a_nonempty_remainder_truncated(
    tmp_path, monkeypatch
):
    path = tmp_path / "line-cap.jsonl"
    first_two = b'{"ordinal":1}\n{"ordinal":2}\n'
    monkeypatch.setattr(routes, "LP_RECORD_MAX_LINES", 2)
    monkeypatch.setenv("DOCKET_LP_RECORD_PATH", str(path))
    client = TestClient(create_app(tmp_path / "line-cap.sqlite3"))

    path.write_bytes(first_two + b'{"ordinal":3}\n')
    truncated = client.get("/lp-record").json()
    path.write_bytes(first_two)
    exact = client.get("/lp-record").json()
    path.write_bytes(b"\nNOT JSON\n" + b'{"ordinal":3}\n')
    physical_cap = client.get("/lp-record").json()

    assert truncated == {
        "lines": [{"ordinal": 1}, {"ordinal": 2}],
        "skipped_unparsable": 0,
        "truncated": True,
    }
    assert exact["lines"] == [{"ordinal": 1}, {"ordinal": 2}]
    assert exact["truncated"] is False
    assert physical_cap == {
        "lines": [],
        "skipped_unparsable": 1,
        "truncated": True,
    }


def test_lp_record_byte_cap_never_publishes_a_partial_line(tmp_path, monkeypatch):
    path = tmp_path / "byte-cap.jsonl"
    first = b'{"ordinal":1}\n'
    second = b'{"ordinal":2}\n'
    monkeypatch.setattr(routes, "LP_RECORD_MAX_BYTES", len(first))
    monkeypatch.setenv("DOCKET_LP_RECORD_PATH", str(path))
    client = TestClient(create_app(tmp_path / "byte-cap.sqlite3"))

    path.write_bytes(first + second)
    truncated = client.get("/lp-record").json()
    path.write_bytes(first)
    exact = client.get("/lp-record").json()
    path.write_bytes(b'{"ordinal":123456789}\n')
    partial = client.get("/lp-record").json()

    assert truncated == {
        "lines": [{"ordinal": 1}],
        "skipped_unparsable": 0,
        "truncated": True,
    }
    assert exact["lines"] == [{"ordinal": 1}]
    assert exact["truncated"] is False
    assert partial == {
        "lines": [],
        "skipped_unparsable": 0,
        "truncated": True,
    }


def test_lp_record_read_failure_uses_the_api_error_envelope(tmp_path, monkeypatch):
    monkeypatch.setenv("DOCKET_LP_RECORD_PATH", str(tmp_path))
    client = TestClient(create_app(tmp_path / "unreadable.sqlite3"))

    response = client.get("/lp-record")

    assert response.status_code == 500
    assert response.headers["content-type"].startswith("application/json")
    assert response.json() == {
        "error": {
            "code": "lp_record_unavailable",
            "message": "The controlled LP record could not be read just now. Retry.",
        }
    }


def test_changed_machine_contract_is_documented_in_llms_txt(tmp_path):
    body = TestClient(create_app(tmp_path / "llms.sqlite3")).get("/llms.txt").text

    for term in (
        "refresh_status",
        "lines",
        "skipped_unparsable",
        "truncated",
        f"{routes.LP_RECORD_MAX_BYTES // (1024 * 1024)} MiB",
        f"{routes.LP_RECORD_MAX_LINES:,}",
        "physical lines",
        "lp_record_unavailable",
        "Authorization: Bearer",
        "operator_unauthorized",
        "recovery_rate_limited",
    ):
        assert term in body


def test_unpinned_app_adopts_only_a_newly_promoted_snapshot(tmp_path):
    db_path = tmp_path / "refresh.sqlite3"
    store = Store(db_path)
    current = store.begin_snapshot(56, expected=1)
    store.finish_snapshot(current, sampled=1)
    client = TestClient(create_app(db_path))
    candidate = store.begin_snapshot(56, expected=1)
    store.finish_snapshot(candidate, sampled=1, promote=False)

    first = client.get("/stats").json()
    assert first["coverage"]["snapshot_id"] == current
    assert first["refresh_status"] is None

    store.promote_snapshot(candidate)

    assert client.get("/stats").json()["coverage"]["snapshot_id"] == candidate
