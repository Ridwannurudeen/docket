"""The synthetic production probe, and the table it writes to.

Every request here is served by an in-process transport rather than a socket, so a run is a
fixed sequence of answers and a failing step is a deliberate one instead of a flake.
"""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from docket import probe
from docket.store import Store

ROOT = Path(__file__).resolve().parents[1]
STEP_NAMES = ("home", "services", "api_status", "advantage_v3", "free_tier_hire")
GOOD = {
    "/": (200, "<!doctype html><title>Docket — case file</title>"),
    "/services": (200, {"services": [{"service_id": "range-doctor"}], "total": 1}),
    "/api/status": (200, {"status": "ok"}),
    "/advantage/v3.json": (200, {"families": [{"spec_id": "v3-07"}], "summary": {"n_families": 1}}),
    "/hire/range-doctor": (200, {"result": {"positions": []}, "receipt": {"service": "x"}}),
}


def _client(answers: dict, *, seen: list | None = None) -> httpx.Client:
    def handle(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append((request.method, request.url.path, request.read()))
        status, body = answers[request.url.path]
        if isinstance(body, str):
            # The real `/` negotiates on Accept: a caller that does not ask for HTML is
            # given the JSON index, which carries no title. The fake does the same, so a
            # probe that forgets to ask for the shell fails here as it did in production.
            if "text/html" not in request.headers.get("accept", ""):
                return httpx.Response(status, json={"service": "docket"})
            return httpx.Response(status, text=body)
        return httpx.Response(status, json=body)

    return httpx.Client(transport=httpx.MockTransport(handle), timeout=5.0)


def test_a_healthy_deployment_passes_every_step_in_order():
    seen: list = []

    steps = probe.run("http://docket.test", client=_client(GOOD, seen=seen))

    assert [step["name"] for step in steps] == list(STEP_NAMES)
    assert all(step["ok"] for step in steps), steps
    assert all(step["status_code"] == 200 for step in steps)
    assert all(isinstance(step["latency_ms"], int) for step in steps)
    assert [method for method, _, _ in seen] == ["GET", "GET", "GET", "GET", "POST"]


def test_the_hire_step_sends_the_catalogue_worked_example_and_nothing_else():
    """A probe that typed its own example would keep passing after the catalogue changed
    the terms it was meant to be exercising."""
    seen: list = []

    probe.run("http://docket.test", client=_client(GOOD, seen=seen))

    _, path, body = seen[-1]
    assert path == "/hire/range-doctor"
    assert json.loads(body) == probe.worked_example()
    assert probe.worked_example()["wallet"].startswith("0x")
    assert "limit" not in probe.worked_example()


@pytest.mark.parametrize(
    ("path", "answer", "detail"),
    [
        ("/", (200, "<!doctype html><title>Somewhere else</title>"), "no Docket title"),
        ("/services", (503, {}), "did not answer 200"),
        (
            "/services",
            (200, {"services": [{"service_id": "a"}], "total": 4}),
            "does not match",
        ),
        ("/api/status", (200, {"status": "down"}), "reports 'down'"),
        (
            "/advantage/v3.json",
            (200, {"families": [], "summary": {"n_families": 3}}),
            "claims 3 families",
        ),
        ("/hire/range-doctor", (200, {"receipt": {}}), "no result object"),
        ("/hire/range-doctor", (200, {"result": {}}), "no receipt"),
    ],
)
def test_each_step_names_the_fault_it_found(path, answer, detail):
    steps = probe.run("http://docket.test", client=_client({**GOOD, path: answer}))
    failed = [step for step in steps if not step["ok"]]

    assert len(failed) == 1, steps
    assert detail in failed[0]["detail"]


def test_a_run_completes_every_step_even_after_one_fails():
    """One fault per run would hide the rest of the deployment's state, and the whole point
    of five steps is that they fail for five different reasons."""
    answers = {**GOOD, "/services": (500, {})}

    steps = probe.run("http://docket.test", client=_client(answers))

    assert [step["name"] for step in steps] == list(STEP_NAMES)
    assert [step["ok"] for step in steps] == [True, False, True, True, True]


def test_a_transport_failure_is_recorded_rather_than_raised():
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    client = httpx.Client(transport=httpx.MockTransport(refuse))

    steps = probe.run("http://docket.test", client=client)

    assert [step["ok"] for step in steps] == [False] * 5
    assert all(step["status_code"] is None for step in steps)
    assert all("ConnectError" in step["detail"] for step in steps)


def test_main_writes_one_run_and_exits_on_the_conjunction(tmp_path, monkeypatch):
    database = tmp_path / "probe.sqlite3"
    Store(database)
    monkeypatch.setenv("DOCKET_DB", str(database))
    monkeypatch.setattr(
        probe,
        "run",
        lambda base_url, **_: [
            {
                "name": name,
                "ok": name != "free_tier_hire",
                "status_code": 200,
                "latency_ms": 5,
                "detail": "recorded",
            }
            for name in STEP_NAMES
        ],
    )

    code = probe.main([])

    assert code == 1
    runs = Store(database).latest_probe_runs(24)
    assert len(runs) == 1
    assert runs[0]["ok"] is False
    assert [step["name"] for step in runs[0]["steps"]] == list(STEP_NAMES)


def test_main_refuses_to_run_without_a_named_database(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("DOCKET_DB", raising=False)

    code = probe.main([])

    assert code == 1
    assert "DOCKET_DB is required" in capsys.readouterr().out


def test_the_default_base_url_is_the_loopback_port_the_unit_listens_on():
    """A default that drifted from the application unit would leave the probe measuring
    nothing while reporting that it measured everything."""
    service = (ROOT / "deploy/systemd/docket.service").read_text(encoding="utf-8")
    timer = (ROOT / "deploy/systemd/docket-probe.timer").read_text(encoding="utf-8")

    assert probe.DEFAULT_BASE_URL == "http://127.0.0.1:8090"
    assert "--host 127.0.0.1 --port 8090" in service
    # Six runs an hour against a twenty-per-hour free-tier allowance.
    assert "OnCalendar=*:0/10" in timer


def test_a_probe_run_must_agree_with_its_own_steps(tmp_path):
    store = Store(tmp_path / "probe.sqlite3")
    now = datetime.now(UTC).isoformat()
    steps = [
        {
            "name": "home",
            "ok": False,
            "status_code": 500,
            "latency_ms": 1,
            "detail": "no",
        }
    ]

    with pytest.raises(ValueError, match="conjunction"):
        store.record_probe_run(started_at=now, finished_at=now, ok=True, steps=steps)
    with pytest.raises(ValueError, match="non-empty list"):
        store.record_probe_run(started_at=now, finished_at=now, ok=True, steps=[])
    with pytest.raises(ValueError, match="must carry"):
        store.record_probe_run(started_at=now, finished_at=now, ok=True, steps=[{"name": "home"}])


def test_the_probe_window_bounds_the_rows_a_reader_is_given(tmp_path):
    store = Store(tmp_path / "probe.sqlite3")
    step = {
        "name": "home",
        "ok": True,
        "status_code": 200,
        "latency_ms": 1,
        "detail": "as served",
    }
    inside = (datetime.now(UTC) - timedelta(hours=23)).isoformat()
    outside = (datetime.now(UTC) - timedelta(hours=25)).isoformat()
    store.record_probe_run(started_at=inside, finished_at=inside, ok=True, steps=[step])
    store.record_probe_run(started_at=outside, finished_at=outside, ok=True, steps=[step])

    assert len(store.latest_probe_runs(24)) == 1
    assert len(store.latest_probe_runs(48)) == 2
    with pytest.raises(ValueError, match="between 1 and"):
        store.latest_probe_runs(0)


def test_a_run_that_cannot_be_recorded_still_journals_its_readings(
    tmp_path, monkeypatch, capsys
):
    """The run happened whether or not it could be written down. Printing after the write
    took the findings down with the database, at the moment they were most worth having."""
    database = tmp_path / "probe.sqlite3"
    Store(database)
    database.write_bytes(b"this is not a database")
    monkeypatch.setenv("DOCKET_DB", str(database))
    monkeypatch.setattr(
        probe,
        "run",
        lambda base_url, **_: [
            {
                "name": name,
                "ok": True,
                "status_code": 200,
                "latency_ms": 5,
                "detail": "as served",
            }
            for name in STEP_NAMES
        ],
    )

    code = probe.main([])
    printed = capsys.readouterr().out

    assert code == 1
    assert "Docket probe: not recorded" in printed
    for name in STEP_NAMES:
        assert f"Docket probe: {name} ok" in printed
    # The run passed; only the recording failed, and the exit status says so without
    # claiming the deployment is broken.
    assert "Docket probe: passed" not in printed
