"""The status document, and the page that is only a rendering of it.

Every case here fixes `now` and supplies the chain reading, because a status surface whose
verdict depends on the wall clock and the network is one nobody can reproduce a complaint
about.
"""

import re
import sqlite3
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from docket.api import create_app
from docket.api import status as status_module
from docket.api.status import (
    REFRESH_MAX_AGE_SECONDS,
    deployed_commit,
    router,
    status_page,
    status_report,
)
from docket.store import Store

NOW = datetime(2026, 9, 3, 12, 0, tzinfo=UTC)
COMMIT = "f" * 40
CHECK_NAMES = ("home", "services", "api_status", "advantage_v3", "free_tier_hire")


def _rpc(ok: bool = True) -> dict:
    return {
        "endpoint_host": "bsc-dataseed.example" if ok else None,
        "ok": ok,
        "block_number": 119_000_000 if ok else None,
        "latency_ms": 180,
    }


def _steps(ok: bool) -> list[dict]:
    return [
        {
            "name": name,
            "ok": ok,
            "status_code": 200 if ok else 502,
            "latency_ms": 12,
            "detail": "as served" if ok else "the route did not answer 200",
        }
        for name in CHECK_NAMES
    ]


def _healthy_store(tmp_path, *, refresh_age_seconds: int = 60) -> Store:
    store = Store(tmp_path / "status.sqlite3")
    observed = (NOW - timedelta(seconds=refresh_age_seconds)).isoformat()
    snapshot = store.begin_snapshot(chain_id=56, expected=3)
    store.finish_snapshot(snapshot, sampled=3, expected=3)
    # The store stamps its own clock, and these cases are about how old a reading is, so the
    # observation time is set here rather than waited for.
    with sqlite3.connect(store.path) as connection:
        connection.execute(
            "UPDATE snapshots SET started_at = ?, finished_at = ? WHERE id = ?",
            (observed, observed, snapshot),
        )
    run_id = store.begin_canary_run("range-doctor", "https://docket.example")
    store.finish_canary_run(
        run_id,
        verdict="passed",
        checks=[
            {
                "leg": "fresh_browser_surface",
                "checked": ["the page was served"],
                "status": "passed",
                "observed": {"status_code": 200},
                "evidence": {"status_code": 200},
            }
        ],
        finished_at=observed,
    )
    store.record_probe_run(started_at=observed, finished_at=observed, ok=True, steps=_steps(True))
    return store


def _report(store: Store, *, commit_path, rpc_ok: bool = True) -> dict:
    return status_report(
        store,
        release_commit_path=commit_path,
        now=NOW,
        rpc_probe=lambda: _rpc(rpc_ok),
    )


@pytest.fixture
def commit_file(tmp_path):
    path = tmp_path / "RELEASE-commit.txt"
    path.write_text(COMMIT + "\n", encoding="ascii")
    return path


def test_a_healthy_deployment_reports_ok_and_names_what_it_is_running(tmp_path, commit_file):
    report = _report(_healthy_store(tmp_path), commit_path=commit_file)

    assert report["status"] == "ok"
    assert report["deployed_commit"] == COMMIT
    assert report["db"] == {
        "reachable": True,
        "journal_mode": "delete",
        "path_redacted": f"{tmp_path.name}/status.sqlite3",
    }
    assert report["latest_refresh"]["complete"] is True
    assert report["latest_refresh"]["age_seconds"] == 60
    assert report["latest_canary"]["verdict"] == "passed"
    assert report["rpc"]["block_number"] == 119_000_000
    assert report["probes"] == {
        "last_run_at": report["probes"]["last_run_at"],
        "ok_count": 1,
        "fail_count": 0,
        "window_hours": 24,
    }
    assert report["generated_at"] == NOW.isoformat()


def test_the_redacted_path_publishes_no_directory_above_the_database(tmp_path, commit_file):
    """The production path is in the runbook; a developer's home directory is not, and a
    status page is the surface most likely to leak one."""
    report = _report(_healthy_store(tmp_path), commit_path=commit_file)

    assert str(tmp_path.parent) not in report["db"]["path_redacted"]
    assert report["db"]["path_redacted"].count("/") == 1


def test_a_refresh_older_than_two_windows_is_degraded(tmp_path, commit_file):
    fresh = _report(
        _healthy_store(tmp_path, refresh_age_seconds=REFRESH_MAX_AGE_SECONDS),
        commit_path=commit_file,
    )
    stale_path = tmp_path / "stale"
    stale_path.mkdir()
    stale = _report(
        _healthy_store(stale_path, refresh_age_seconds=REFRESH_MAX_AGE_SECONDS + 1),
        commit_path=commit_file,
    )

    assert fresh["status"] == "ok"
    assert stale["status"] == "degraded"
    assert stale["latest_refresh"]["age_seconds"] == REFRESH_MAX_AGE_SECONDS + 1


def test_a_partial_refresh_is_degraded_however_recent_it_is(tmp_path, commit_file):
    store = _healthy_store(tmp_path)
    snapshot = store.begin_snapshot(chain_id=56, expected=9)
    store.finish_snapshot(snapshot, sampled=4, expected=9, stop_reason="max_pages")

    report = _report(store, commit_path=commit_file)

    assert report["latest_refresh"]["complete"] is False
    assert report["status"] == "degraded"


def test_a_failed_canary_is_degraded_and_an_unexercised_one_is_not(tmp_path, commit_file):
    """`not_yet_exercised` is what the canary records when its paid limbs are not configured
    and what a deployment with a deliberately disabled canary timer shows for days. Counting
    it would leave this page permanently degraded, which is the same as having no page."""
    unexercised = _healthy_store(tmp_path)
    run_id = unexercised.begin_canary_run("range-doctor", "https://docket.example")
    unexercised.finish_canary_run(run_id, verdict="not_yet_exercised", checks=[])
    failed_path = tmp_path / "failed"
    failed_path.mkdir()
    failed = _healthy_store(failed_path)
    failed_run = failed.begin_canary_run("range-doctor", "https://docket.example")
    failed.finish_canary_run(failed_run, verdict="failed", checks=[])

    assert _report(unexercised, commit_path=commit_file)["status"] == "ok"
    assert _report(failed, commit_path=commit_file)["status"] == "degraded"


def test_a_chain_read_that_found_no_endpoint_is_degraded(tmp_path, commit_file):
    report = _report(_healthy_store(tmp_path), commit_path=commit_file, rpc_ok=False)

    assert report["rpc"] == {
        "endpoint_host": None,
        "ok": False,
        "block_number": None,
        "latency_ms": 180,
    }
    assert report["status"] == "degraded"


def test_one_failed_probe_run_inside_the_window_is_degraded(tmp_path, commit_file):
    store = _healthy_store(tmp_path)
    inside = (NOW - timedelta(hours=1)).isoformat()
    store.record_probe_run(started_at=inside, finished_at=inside, ok=False, steps=_steps(False))

    report = _report(store, commit_path=commit_file)

    assert report["probes"]["ok_count"] == 1
    assert report["probes"]["fail_count"] == 1
    assert report["status"] == "degraded"


def test_a_probe_run_older_than_the_window_leaves_the_counts_alone(tmp_path, commit_file):
    store = _healthy_store(tmp_path)
    outside = (NOW - timedelta(hours=25)).isoformat()
    store.record_probe_run(started_at=outside, finished_at=outside, ok=False, steps=_steps(False))

    report = _report(store, commit_path=commit_file)

    assert report["probes"]["fail_count"] == 0
    assert report["status"] == "ok"


def test_a_database_that_cannot_be_read_is_down_rather_than_degraded(tmp_path, commit_file):
    store = _healthy_store(tmp_path)
    (tmp_path / "status.sqlite3").write_bytes(b"this is not a database")

    report = _report(store, commit_path=commit_file)

    assert report["status"] == "down"
    assert report["db"]["reachable"] is False
    assert report["latest_refresh"] == {"at": None, "age_seconds": None, "complete": False}
    assert report["probes"]["window_hours"] == 24
    # The deployment identity is not read out of the database, so it survives losing it.
    assert report["deployed_commit"] == COMMIT


def test_the_deployed_commit_prefers_the_release_record_then_git_then_nothing(tmp_path):
    recorded = tmp_path / "RELEASE-commit.txt"
    recorded.write_text(COMMIT + "\n", encoding="ascii")

    assert deployed_commit(recorded) == COMMIT
    # No release record: this checkout is a git repository, so the answer is its HEAD, and a
    # tree that is not one says `source` rather than inventing a commit.
    fallback = deployed_commit(tmp_path / "absent.txt")
    assert re.fullmatch(r"[0-9a-f]{40}|source", fallback), fallback


def test_the_page_publishes_the_same_readings_as_the_document(tmp_path, commit_file):
    store = _healthy_store(tmp_path)
    report = _report(store, commit_path=commit_file)
    shell = (status_module.WEB_DIR / "status.html").read_text(encoding="utf-8")

    page = status_page(shell, report)

    assert "<title>Docket status</title>" in page
    assert COMMIT in page
    assert "119,000,000" in page
    assert "1 of 1 runs passed" in page
    assert "0 failed runs in the last 24 hours" in page
    assert f"under {REFRESH_MAX_AGE_SECONDS:,}s" in page
    assert page.count("<td>out of tolerance</td>") == 0
    assert page.count("<td>within tolerance</td>") == 4
    assert "<!-- status-content -->" not in page


def test_the_page_marks_the_reading_that_moved_the_verdict(tmp_path, commit_file):
    store = _healthy_store(tmp_path)
    shell = (status_module.WEB_DIR / "status.html").read_text(encoding="utf-8")

    page = status_page(shell, _report(store, commit_path=commit_file, rpc_ok=False))

    assert page.count("<td>out of tolerance</td>") == 1
    assert "no endpoint answered in 180ms" in page


def test_both_routes_are_served_from_one_reading(tmp_path):
    store = _healthy_store(tmp_path)
    app = FastAPI()
    app.include_router(
        router(
            store,
            release_commit_path=tmp_path / "RELEASE-commit.txt",
            rpc_probe=lambda: _rpc(True),
        )
    )
    client = TestClient(app)

    document = client.get("/api/status")
    page = client.get("/status")

    assert document.status_code == 200
    assert document.headers["content-type"].startswith("application/json")
    assert document.json()["status"] in {"ok", "degraded", "down"}
    assert page.status_code == 200
    assert page.headers["content-type"].startswith("text/html")
    assert document.json()["deployed_commit"] in page.text


def test_the_application_serves_the_status_routes(tmp_path, monkeypatch):
    monkeypatch.setattr(status_module, "bounded_rpc_probe", lambda: _rpc(True))
    database = tmp_path / "app.sqlite3"
    client = TestClient(create_app(database))

    document = client.get("/api/status")

    assert document.status_code == 200
    assert set(document.json()) == {
        "status",
        "deployed_commit",
        "db",
        "latest_refresh",
        "latest_canary",
        "rpc",
        "probes",
        "generated_at",
    }
    assert client.get("/status").status_code == 200
