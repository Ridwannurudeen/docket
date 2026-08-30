import json
from datetime import datetime
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

import docket.refresh as refresh_module
from docket.api import create_app
from docket.refresh import (
    RefreshRefused,
    owned_agent_ids_from_environment,
    refresh_once,
)
from docket.scan8004 import Scan8004Client
from docket.store import Store

REGISTRY_ADDRESS = "0x8004a169fb4a3325136eb29fa0ceb6d2e539a432"
ROOT = Path(__file__).resolve().parents[1]


def _agent(token: int, *, feedbacks: int = 1, callable: bool = False) -> dict:
    return {
        "agent_id": f"56:{REGISTRY_ADDRESS}:{token}",
        "token_id": str(token),
        "chain_id": 56,
        "name": f"Agent #{token}",
        "supported_protocols": ["A2A"] if callable else [],
        "total_feedbacks": feedbacks,
        "total_score": 0.0,
    }


def _complete_registry(*agents: dict):
    by_token = {agent["token_id"]: agent for agent in agents}
    filtered = [agent for agent in agents if agent["total_feedbacks"] >= 1]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/agents"):
            offset = int(request.url.params["offset"])
            page = filtered[offset : offset + 100]
            return httpx.Response(200, json={"items": page, "total": len(filtered)})
        token = request.url.path.rsplit("/", 1)[-1]
        agent = by_token[token]
        detail = dict(agent)
        if agent["supported_protocols"]:
            detail["a2a_endpoint"] = f"https://agent-{token}.example/a2a"
        return httpx.Response(200, json=detail)

    return handler


def _public(host, port, *args, **kwargs):
    return [(2, 1, 6, "", ("93.184.216.34", port or 443))]


class _PeerStream:
    def get_extra_info(self, info):
        if info == "server_addr":
            return ("93.184.216.34", 443)
        return None


def _probe_client() -> httpx.Client:
    return httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                extensions={"network_stream": _PeerStream()},
            )
        )
    )


def test_refresh_promotes_only_after_enrichment_and_probing(tmp_path, monkeypatch):
    store = Store(tmp_path / "d.sqlite3")
    registry = Scan8004Client(
        transport=httpx.MockTransport(_complete_registry(_agent(1, callable=True))),
        pace=False,
    )
    observations = []
    original_enrich = refresh_module.enrich_callable
    original_probe = refresh_module.probe_snapshot

    def enrich(*args, **kwargs):
        observations.append(("enrich", store.latest_complete_snapshot_id()))
        return original_enrich(*args, **kwargs)

    def probe(*args, **kwargs):
        observations.append(("probe", store.latest_complete_snapshot_id()))
        return original_probe(*args, **kwargs)

    monkeypatch.setattr(refresh_module, "enrich_callable", enrich)
    monkeypatch.setattr(refresh_module, "probe_snapshot", probe)
    with _probe_client() as probe_client:
        result = refresh_once(
            store,
            registry,
            probe_client=probe_client,
            resolver=_public,
        )

    assert observations == [("enrich", None), ("probe", None)]
    assert store.latest_complete_snapshot_id() == result["snapshot_id"]
    assert result["enrichment"]["fetched"] == 1
    assert result["liveness"]["responded"] == 1
    refresh_status = json.loads(
        (store.path.parent / "last-refresh.json").read_text(encoding="utf-8")
    )
    assert refresh_status["status"] == "ok"
    assert (
        datetime.fromisoformat(refresh_status["timestamp"]).utcoffset().total_seconds()
        == 0
    )


def test_bounded_refresh_is_refused_and_never_promoted(tmp_path):
    store = Store(tmp_path / "d.sqlite3")
    agents = [_agent(token) for token in range(150)]
    registry = Scan8004Client(
        transport=httpx.MockTransport(_complete_registry(*agents)), pace=False
    )

    with pytest.raises(RefreshRefused, match="max_pages"):
        refresh_once(store, registry, max_pages=1)

    assert store.latest_complete_snapshot_id() is None
    row = store.snapshot(store.latest_snapshot_id())
    assert row["stop_reason"] == "max_pages"
    assert row["promoted_at"] is None
    refresh_status = json.loads(
        (store.path.parent / "last-refresh.json").read_text(encoding="utf-8")
    )
    assert refresh_status["status"] == "refused"
    assert (
        datetime.fromisoformat(refresh_status["timestamp"]).utcoffset().total_seconds()
        == 0
    )


def test_non_advancing_refresh_is_refused_and_never_promoted(tmp_path):
    store = Store(tmp_path / "d.sqlite3")
    agent = _agent(1)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"items": [agent], "total": 2})

    registry = Scan8004Client(transport=httpx.MockTransport(handler), pace=False)
    with pytest.raises(RefreshRefused, match="not_advancing"):
        refresh_once(store, registry)

    assert store.latest_complete_snapshot_id() is None
    row = store.snapshot(store.latest_snapshot_id())
    assert row["stop_reason"] == "not_advancing"
    assert row["promoted_at"] is None


def test_unexpected_refresh_failure_writes_error_status(tmp_path):
    store = Store(tmp_path / "error-status.sqlite3")

    def fail(_request: httpx.Request) -> httpx.Response:
        raise RuntimeError("fixture registry failure")

    registry = Scan8004Client(transport=httpx.MockTransport(fail), pace=False)

    with pytest.raises(RuntimeError, match="fixture registry failure"):
        refresh_once(store, registry)

    refresh_status = json.loads(
        (store.path.parent / "last-refresh.json").read_text(encoding="utf-8")
    )
    assert refresh_status["status"] == "error"
    assert (
        datetime.fromisoformat(refresh_status["timestamp"]).utcoffset().total_seconds()
        == 0
    )


def test_refresh_includes_an_allowlisted_agent_with_zero_feedback(tmp_path):
    store = Store(tmp_path / "d.sqlite3")
    filtered = _agent(1)
    owned = _agent(2, feedbacks=0)
    registry = Scan8004Client(
        transport=httpx.MockTransport(_complete_registry(filtered, owned)), pace=False
    )

    result = refresh_once(store, registry, owned_agent_ids=(owned["agent_id"],))

    assert {row["agent_id"] for row in store.iter_agents(result["snapshot_id"])} == {
        filtered["agent_id"],
        owned["agent_id"],
    }
    assert result["ingest"]["sampled"] == result["ingest"]["expected"] == 2
    assert store.latest_complete_snapshot_id() == result["snapshot_id"]


def test_owned_agent_ids_are_read_from_the_refresh_environment():
    first = _agent(1)["agent_id"]
    second = _agent(2)["agent_id"]
    assert owned_agent_ids_from_environment(
        {"DOCKET_OWNED_AGENT_IDS": f" {first}, {second} "}
    ) == (first, second)


def test_owned_agent_ids_environment_rejects_an_empty_list_item():
    with pytest.raises(ValueError, match="comma-separated"):
        owned_agent_ids_from_environment(
            {"DOCKET_OWNED_AGENT_IDS": f"{_agent(1)['agent_id']},,"}
        )


def test_running_app_serves_the_snapshot_promoted_by_refresh(tmp_path):
    store = Store(tmp_path / "d.sqlite3")
    original = store.begin_snapshot(56, 1, "min_feedbacks>=1")
    store.upsert_agents([_agent(1)], original)
    store.finish_snapshot(original, 1)
    app = create_app(store.path)

    registry = Scan8004Client(
        transport=httpx.MockTransport(_complete_registry(_agent(1), _agent(2))),
        pace=False,
    )
    refreshed = refresh_once(store, registry)

    response = TestClient(app).get("/stats")
    assert response.status_code == 200
    assert response.json()["coverage"]["snapshot_id"] == refreshed["snapshot_id"]
    assert response.json()["coverage"]["sampled"] == 2
    assert response.json()["refresh_status"]["status"] == "ok"
    assert response.json()["refresh_status"]["timestamp"]


def test_refresh_systemd_units_run_the_pipeline_every_six_hours():
    service = (ROOT / "deploy/systemd/docket-refresh.service").read_text(
        encoding="utf-8"
    )
    timer = (ROOT / "deploy/systemd/docket-refresh.timer").read_text(encoding="utf-8")
    runbook = (ROOT / "docs/deployment-runbook.md").read_text(encoding="utf-8")

    assert "User=docket" in service
    assert "Environment=DOCKET_DB=/var/lib/docket/data/agents.sqlite3" in service
    assert "EnvironmentFile=-/etc/docket/docket-refresh.conf" in service
    assert "ExecStart=/opt/docket/.venv/bin/python -P -m docket.refresh" in service
    assert "ReadWritePaths=/var/lib/docket" in service
    assert "OnCalendar=*-*-* 01,07,13,19:41:00 UTC" in timer
    assert "Persistent=true" in timer
    assert "Restart=no" in service
    assert "/var/lib/docket/data/last-refresh.json" in runbook
    assert "systemctl status docket-refresh.service" in runbook
    assert "journalctl -u docket-refresh.service" in runbook
    assert "Restart=no" in runbook
