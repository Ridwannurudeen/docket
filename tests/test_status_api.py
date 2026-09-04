"""The status document, and the page that is only a rendering of it.

Every case here fixes `now` and supplies the chain reading, because a status surface whose
verdict depends on the wall clock and the network is one nobody can reproduce a complaint
about.
"""

import re
import socket
import sqlite3
import threading
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from docket.api import create_app
from docket.api import status as status_module
from docket.api.status import (
    CANARY_RUN_TIMEOUT_S,
    PROBE_VERDICT_RUNS,
    REFRESH_MAX_AGE_SECONDS,
    REFRESH_SWEEP_TIMEOUT_S,
    REPORT_TTL_S,
    RPC_ENDPOINT,
    STATUS_ALLOWANCE,
    STATUS_WINDOW_S,
    bounded_rpc_probe,
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
        "endpoint_host": "bsc-dataseed.example",
        "ok": ok,
        "block_number": 119_000_000 if ok else None,
        "latency_ms": 180,
        "reason": None if ok else "ConnectTimeout: the endpoint did not answer",
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


def _stamp(store: Store, sql: str, parameters: tuple) -> None:
    """The store stamps its own clock, and these cases are about how old a reading is, so
    the observation time is set here rather than waited for."""
    with sqlite3.connect(store.path) as connection:
        connection.execute(sql, parameters)


def _healthy_store(tmp_path, *, refresh_age_seconds: int = 60) -> Store:
    store = Store(tmp_path / "status.sqlite3")
    observed = (NOW - timedelta(seconds=refresh_age_seconds)).isoformat()
    snapshot = store.begin_snapshot(chain_id=56, expected=3)
    store.finish_snapshot(snapshot, sampled=3, expected=3)
    _stamp(
        store,
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
        "recent_ok": 1,
        "recent_considered": 1,
    }
    assert report["refresh_in_progress"] is None
    assert report["latest_canary"]["exercised"] is True
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


def test_a_partial_sweep_does_not_unseat_the_snapshot_still_being_served(
    tmp_path, commit_file
):
    """A page-bounded sweep is never promoted, so the previous snapshot stays in service and
    keeps being correct. One of those is not an outage; a run of them stops the served
    snapshot being refreshed, and the staleness bound below is what catches that."""
    store = _healthy_store(tmp_path)
    snapshot = store.begin_snapshot(chain_id=56, expected=9)
    store.finish_snapshot(snapshot, sampled=4, expected=9, stop_reason="max_pages")

    report = _report(store, commit_path=commit_file)

    assert report["latest_refresh"]["complete"] is True
    assert report["refresh_in_progress"] is None
    assert report["status"] == "ok"


def test_sweeps_that_keep_ending_partial_surface_as_a_stale_snapshot(
    tmp_path, commit_file
):
    store = _healthy_store(tmp_path, refresh_age_seconds=REFRESH_MAX_AGE_SECONDS + 1)
    snapshot = store.begin_snapshot(chain_id=56, expected=9)
    store.finish_snapshot(snapshot, sampled=4, expected=9, stop_reason="max_pages")

    report = _report(store, commit_path=commit_file)

    assert report["latest_refresh"]["complete"] is True
    assert report["latest_refresh"]["age_seconds"] == REFRESH_MAX_AGE_SECONDS + 1
    assert report["status"] == "degraded"


def test_a_sweep_in_flight_is_reported_without_unseating_the_served_snapshot(
    tmp_path, commit_file
):
    """A refresh takes up to two hours, and for every minute of it the newest row has a null
    finished_at. Judging that row painted the page degraded for the whole of a sweep that was
    working, which is how a status surface teaches an operator to ignore it."""
    store = _healthy_store(tmp_path)
    started = (NOW - timedelta(minutes=40)).isoformat()
    snapshot = store.begin_snapshot(chain_id=56, expected=9)
    _stamp(store, "UPDATE snapshots SET started_at = ? WHERE id = ?", (started, snapshot))

    report = _report(store, commit_path=commit_file)

    assert report["latest_refresh"]["complete"] is True
    assert report["refresh_in_progress"] == {
        "started_at": started,
        "age_seconds": 40 * 60,
    }
    assert report["status"] == "ok"


def test_a_sweep_that_outlives_its_unit_deadline_is_degraded(tmp_path, commit_file):
    store = _healthy_store(tmp_path)
    started = (NOW - timedelta(seconds=REFRESH_SWEEP_TIMEOUT_S + 1)).isoformat()
    snapshot = store.begin_snapshot(chain_id=56, expected=9)
    _stamp(store, "UPDATE snapshots SET started_at = ? WHERE id = ?", (started, snapshot))

    report = _report(store, commit_path=commit_file)

    assert report["refresh_in_progress"]["age_seconds"] == REFRESH_SWEEP_TIMEOUT_S + 1
    assert report["status"] == "degraded"


def test_a_first_sweep_still_running_is_degraded_because_nothing_is_served_yet(tmp_path):
    store = Store(tmp_path / "first.sqlite3")
    store.begin_snapshot(chain_id=56, expected=9)

    report = _report(store, commit_path=tmp_path / "absent.txt")

    assert report["latest_refresh"]["complete"] is False
    assert report["refresh_in_progress"] is not None
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

    unexercised_report = _report(unexercised, commit_path=commit_file)
    assert unexercised_report["status"] == "ok"
    assert unexercised_report["latest_canary"]["exercised"] is False
    assert _report(failed, commit_path=commit_file)["status"] == "degraded"


def test_a_canary_left_running_past_its_unit_deadline_is_degraded(tmp_path, commit_file):
    """The unit is killed at TimeoutStartSec, so a `running` row older than that is a run
    whose result nobody will ever receive — which is not the same as a run in flight."""
    started = (NOW - timedelta(seconds=CANARY_RUN_TIMEOUT_S + 1)).isoformat()
    running = _healthy_store(tmp_path)
    running.begin_canary_run("range-doctor", "https://docket.example", started_at=started)
    fresh_path = tmp_path / "fresh"
    fresh_path.mkdir()
    fresh = _healthy_store(fresh_path)
    fresh.begin_canary_run(
        "range-doctor",
        "https://docket.example",
        started_at=(NOW - timedelta(seconds=60)).isoformat(),
    )

    stale_report = _report(running, commit_path=commit_file)

    assert stale_report["latest_canary"]["verdict"] == "running"
    assert stale_report["latest_canary"]["exercised"] is False
    assert stale_report["status"] == "degraded"
    assert _report(fresh, commit_path=commit_file)["status"] == "ok"


def test_a_chain_read_that_found_no_endpoint_is_degraded(tmp_path, commit_file):
    report = _report(_healthy_store(tmp_path), commit_path=commit_file, rpc_ok=False)

    assert report["rpc"] == {
        "endpoint_host": "bsc-dataseed.example",
        "ok": False,
        "block_number": None,
        "latency_ms": 180,
        "reason": "ConnectTimeout: the endpoint did not answer",
    }
    assert report["status"] == "degraded"


def test_the_newest_probe_run_failing_is_degraded(tmp_path, commit_file):
    store = _healthy_store(tmp_path)
    inside = (NOW - timedelta(minutes=10)).isoformat()
    store.record_probe_run(started_at=inside, finished_at=inside, ok=False, steps=_steps(False))

    report = _report(store, commit_path=commit_file)

    assert report["probes"]["ok_count"] == 1
    assert report["probes"]["fail_count"] == 1
    assert report["probes"]["recent_ok"] == 1
    assert report["probes"]["recent_considered"] == 2
    assert report["status"] == "degraded"


def test_one_old_probe_failure_does_not_hold_the_page_red_for_a_day(
    tmp_path, commit_file
):
    """The window counts still report it. The verdict does not, because a transient failure
    twenty hours ago says nothing about whether this deployment is serving now."""
    store = _healthy_store(tmp_path)
    failed_at = (NOW - timedelta(hours=20)).isoformat()
    store.record_probe_run(
        started_at=failed_at, finished_at=failed_at, ok=False, steps=_steps(False)
    )
    for minutes in (30, 20, 10):
        at = (NOW - timedelta(minutes=minutes)).isoformat()
        store.record_probe_run(started_at=at, finished_at=at, ok=True, steps=_steps(True))

    report = _report(store, commit_path=commit_file)

    assert report["probes"]["fail_count"] == 1
    assert report["probes"]["ok_count"] == 4
    assert report["probes"]["recent_ok"] == PROBE_VERDICT_RUNS
    assert report["probes"]["recent_considered"] == PROBE_VERDICT_RUNS
    assert report["status"] == "ok"


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
    assert "1 of 1 runs passed in 24h; 1 of the last 1 passed" in page
    assert f"the last {PROBE_VERDICT_RUNS} runs all passed" in page
    assert "none running" in page
    assert f"under {REFRESH_MAX_AGE_SECONDS:,}s" in page
    assert page.count("<td>out of tolerance</td>") == 0
    assert page.count("<td>within tolerance</td>") == 5
    assert "<!-- status-content -->" not in page


def test_the_page_marks_the_reading_that_moved_the_verdict(tmp_path, commit_file):
    store = _healthy_store(tmp_path)
    shell = (status_module.WEB_DIR / "status.html").read_text(encoding="utf-8")

    page = status_page(shell, _report(store, commit_path=commit_file, rpc_ok=False))

    assert page.count("<td>out of tolerance</td>") == 1
    assert "no answer in 180ms — ConnectTimeout: the endpoint did not answer" in page


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
        "refresh_in_progress",
        "latest_canary",
        "rpc",
        "probes",
        "generated_at",
    }
    assert client.get("/status").status_code == 200


class _Clock:
    """A monotonic clock that only moves when a test moves it."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def _routed(store: Store, tmp_path, *, probe, clock=None, ttl_s=REPORT_TTL_S) -> TestClient:
    app = FastAPI()
    app.include_router(
        router(
            store,
            release_commit_path=tmp_path / "absent.txt",
            rpc_probe=probe,
            ttl_s=ttl_s,
            **({"clock": clock} if clock is not None else {}),
        )
    )
    return TestClient(app)


def test_one_reading_stands_for_the_window_and_is_retaken_after_it(tmp_path, monkeypatch):
    """Both routes are public and one reading is an outbound chain read, so the reading is
    what is bounded rather than the requests. The document carries the instant it was taken,
    which is how a caller inside the window can tell it is being served a held reading."""
    readings = []
    clock = _Clock()
    monkeypatch.setattr(
        status_module, "_utc_now", lambda: NOW + timedelta(seconds=clock.now)
    )
    client = _routed(
        _healthy_store(tmp_path),
        tmp_path,
        probe=lambda: (readings.append(1), _rpc(True))[1],
        clock=clock,
    )

    first = client.get("/api/status").json()
    clock.now += REPORT_TTL_S - 1
    held = client.get("/api/status").json()
    page = client.get("/status")
    clock.now += 1
    retaken = client.get("/api/status").json()

    assert held == first
    assert held["generated_at"] == first["generated_at"]
    assert first["generated_at"] in page.text
    assert retaken["generated_at"] != first["generated_at"]
    assert len(readings) == 2, "the chain was read once per window, not once per request"


def test_the_page_is_served_from_the_same_reading_as_the_document(tmp_path):
    readings = []
    client = _routed(
        _healthy_store(tmp_path),
        tmp_path,
        probe=lambda: (readings.append(1), _rpc(True))[1],
        clock=_Clock(),
    )

    document = client.get("/api/status").json()
    for _ in range(5):
        client.get("/status")

    assert len(readings) == 1
    assert document["generated_at"] in client.get("/status").text


def test_the_document_is_rate_limited_per_peer_and_the_page_is_not(tmp_path):
    client = _routed(_healthy_store(tmp_path), tmp_path, probe=lambda: _rpc(True))

    for _ in range(STATUS_ALLOWANCE):
        assert client.get("/api/status").status_code == 200
    refused = client.get("/api/status")

    assert refused.status_code == 429
    assert set(refused.json()) == {"error_code", "message"}
    assert refused.json()["error_code"] == "status_rate_limited"
    assert str(STATUS_ALLOWANCE) in refused.json()["message"]
    assert str(STATUS_WINDOW_S) in refused.json()["message"]
    # spend_window rounds up, so a window that has barely started resets in w + 1 at most.
    assert 0 < int(refused.headers["Retry-After"]) <= STATUS_WINDOW_S + 1
    # The page costs a render of a reading already taken, and a person who has just hit a
    # bound is exactly the person who needs to read it.
    assert client.get("/status").status_code == 200


def test_the_chain_reading_makes_one_attempt_against_one_endpoint(monkeypatch):
    """`escrow/chain.py::Rpc` would try four endpoints twice each. That is right for a job
    that must get an answer and wrong for a public route, where it turns one request into
    eight outbound connections."""
    attempted = []

    def refuse(url):
        attempted.append(url)
        raise ConnectionError("connection refused")

    monkeypatch.setattr(status_module, "_session", refuse)

    reading = bounded_rpc_probe()

    assert attempted == [RPC_ENDPOINT]
    assert reading["ok"] is False
    assert reading["block_number"] is None
    assert reading["endpoint_host"] == urlsplit(RPC_ENDPOINT).hostname
    assert "ConnectionError" in reading["reason"]


def test_the_chain_reading_names_the_block_and_no_reason_when_it_answers(monkeypatch):
    attempted = []

    class _Session:
        eth = type("_Eth", (), {"block_number": 119_700_000})()

    def answer(url):
        attempted.append(url)
        return _Session()

    monkeypatch.setattr(status_module, "_session", answer)

    reading = bounded_rpc_probe()

    assert attempted == [RPC_ENDPOINT]
    assert reading == {
        "endpoint_host": urlsplit(RPC_ENDPOINT).hostname,
        "ok": True,
        "block_number": 119_700_000,
        "latency_ms": reading["latency_ms"],
        "reason": None,
    }


class _Listener:
    """A real socket that accepts connections and counts them.

    The point of MAJOR 1 is a retry loop inside the HTTP provider, below anything a stubbed
    session can see. Only a socket can count what actually left this machine.
    """

    def __init__(self, answer: bytes | None = None) -> None:
        self._answer = answer
        self._socket = socket.socket()
        self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._socket.bind(("127.0.0.1", 0))
        self._socket.listen(16)
        self._socket.settimeout(0.2)
        self.accepts = 0
        self._held: list[socket.socket] = []
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self._socket.getsockname()[1]}"

    def _serve(self) -> None:
        while not self._stop.is_set():
            try:
                connection, _ = self._socket.accept()
            except OSError:
                continue
            self.accepts += 1
            if self._answer is None:
                # Held open and never answered: the endpoint that is up and mute, which is
                # the case the provider's ReadTimeout retry fires on.
                self._held.append(connection)
                continue
            try:
                connection.recv(65535)
                connection.sendall(self._answer)
            except OSError:
                pass
            finally:
                connection.close()

    def close(self) -> None:
        self._stop.set()
        self._thread.join(timeout=2)
        for connection in self._held:
            connection.close()
        self._socket.close()


@pytest.fixture
def silent_endpoint():
    listener = _Listener()
    yield listener
    listener.close()


@pytest.fixture
def refusing_endpoint():
    listener = _Listener(
        answer=b"HTTP/1.1 503 Service Unavailable\r\nContent-Length: 0\r\n"
        b"Connection: close\r\n\r\n"
    )
    yield listener
    listener.close()


def test_a_mute_endpoint_costs_exactly_one_connection(monkeypatch, silent_endpoint):
    """web3 7.16.0's HTTPProvider retries ConnectionError, HTTPError and Timeout five times
    by default, and eth_blockNumber is on its retry allowlist — so `request_kwargs={"timeout"}`
    bounds one connection while the provider quietly makes five. Measured before the fix:
    5 accepts and 5 x timeout plus 1.875s of backoff, inside the lock a reading is built
    under. This drives the real `_session`, because the defect lives below any stub."""
    monkeypatch.setattr(status_module, "RPC_TIMEOUT_S", 0.4)
    monkeypatch.setattr(status_module, "RPC_ENDPOINT", silent_endpoint.url)

    reading = bounded_rpc_probe()

    assert silent_endpoint.accepts == 1
    assert reading["ok"] is False
    assert reading["block_number"] is None
    assert reading["reason"]
    # One timeout, not five plus backoff.
    assert reading["latency_ms"] < 1200


def test_a_refusing_endpoint_costs_exactly_one_connection(monkeypatch, refusing_endpoint):
    monkeypatch.setattr(status_module, "RPC_TIMEOUT_S", 0.4)
    monkeypatch.setattr(status_module, "RPC_ENDPOINT", refusing_endpoint.url)

    reading = bounded_rpc_probe()

    assert refusing_endpoint.accepts == 1
    assert reading["ok"] is False
    assert reading["reason"]


def test_the_provider_is_built_with_retries_turned_off():
    """Asserted on the object as well as on the socket: the socket test would keep passing
    if a future web3 changed its allowlist, and this one says what was intended."""
    session = status_module._session("http://127.0.0.1:1")

    assert session.provider.exception_retry_configuration is None


def test_the_page_names_the_sweep_in_flight_and_the_paid_path(tmp_path, commit_file):
    store = _healthy_store(tmp_path)
    started = (NOW - timedelta(minutes=40)).isoformat()
    snapshot = store.begin_snapshot(chain_id=56, expected=9)
    _stamp(store, "UPDATE snapshots SET started_at = ? WHERE id = ?", (started, snapshot))
    shell = (status_module.WEB_DIR / "status.html").read_text(encoding="utf-8")

    page = status_page(shell, _report(store, commit_path=commit_file))

    assert "Sweep in flight" in page
    assert "running, 2,400s old" in page
    assert page.count("<td>out of tolerance</td>") == 0
    assert page.count("<td>within tolerance</td>") == 5
    # The lede must not let "ok" be read as "the paid path works".
    assert "It does not cover the paid path" in page


def test_the_page_says_when_the_paid_path_was_never_exercised(tmp_path, commit_file):
    store = _healthy_store(tmp_path)
    run_id = store.begin_canary_run("range-doctor", "https://docket.example")
    store.finish_canary_run(run_id, verdict="not_yet_exercised", checks=[])
    shell = (status_module.WEB_DIR / "status.html").read_text(encoding="utf-8")

    page = status_page(shell, _report(store, commit_path=commit_file))

    assert "last exercised never" in page
    assert "not exercised" in page
    assert page.count("<td>out of tolerance</td>") == 0
