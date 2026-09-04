"""Exercise category hires and evidence reports through an installed wheel, never source."""

import os
import tempfile
from dataclasses import replace
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path

from fastapi.testclient import TestClient

import docket
import docket.agents.grid.lifecycle
import docket.agents.grid.operator
import docket.agents.pancake.doctor
import docket.agents.venus.guard
import docket.agents.yield_router.migration
import docket.agents.yield_router.router
import docket.jobs.executors
from docket.api import create_app
from docket.hire import catalogue
from docket.identity import register

WORKSPACE = Path(os.environ["GITHUB_WORKSPACE"]).resolve()
INSTALLED_PACKAGE = Path(docket.__file__).resolve()
assert not INSTALLED_PACKAGE.is_relative_to(WORKSPACE), (
    f"smoke imported the checkout at {INSTALLED_PACKAGE}, not the installed wheel"
)

# The category executors are looked up by category, so a wheel that shipped the package
# without them would answer every activation with a KeyError at run time rather than at
# import time. Asserted here because that is the exact shape of the defect this file
# exists to catch: every source-tree test passes while the installed package is short.
docket.jobs.executors.load_executors()
assert set(docket.jobs.executors.EXECUTORS) == {
    "rebalancing",
    "grid_trading",
    "yield_optimisation",
    "health_factor",
}, sorted(docket.jobs.executors.EXECUTORS)

registration = register.build_registration_json(
    catalogue.SERVICES["range-doctor"],
    clock=lambda: datetime(2026, 8, 30, tzinfo=UTC),
)
assert registration["version"] == version("docket")

PAYLOADS = {
    "range-doctor": {"wallet": "0x0000000000000000000000000000000000000001"},
    "grid-operator": {"wallet": "0x0000000000000000000000000000000000000001"},
    "yield-router": {},
    "health-guard": {"wallet": "0x0000000000000000000000000000000000000001"},
}

for service_id in PAYLOADS:
    service = catalogue.SERVICES[service_id]
    catalogue.SERVICES[service_id] = replace(
        service,
        run=lambda payload, service_id=service_id: {
            "service_id": service_id,
            "smoke": "installed-wheel route reached",
        },
    )

with tempfile.TemporaryDirectory(prefix="docket-installed-smoke-") as scratch:
    client = TestClient(create_app(db_path=Path(scratch) / "smoke.sqlite3"))
    for service_id, payload in PAYLOADS.items():
        response = client.post(f"/hire/{service_id}", json=payload)
        assert response.status_code == 200, (
            f"{service_id} returned {response.status_code}: {response.text}"
        )
        body = response.json()
        assert body["result"]["service_id"] == service_id
        assert body["receipt"]["service"] == service_id

    report = client.get("/advantage/v3.json")
    assert report.status_code == 200, report.text
    families = report.json()["families"]
    assert [family["spec_id"] for family in families] == [
        "v3-01-range-doctor",
        "v3-02-yield-router",
        "v3-03-warden-security",
        "v3-04-warden-security",
        "v3-05-range-doctor",
        "v3-06-yield-router-assisted",
        "v3-07-range-doctor",
        "v3-08-yield-router",
        "v3-09-health-guard",
    ]
    assert {family["state"] for family in families} == {
        "complete_unscored",
        "abandoned_after_failed_primary",
        "locked_not_run",
        "registered_waiting_for_inputs",
        "superseded_before_input_lock",
    }

    page = client.get("/advantage/v3")
    assert page.status_code == 200, page.text
    assert "complete_unscored" in page.text
    assert "locked_not_run" in page.text
    assert "abandoned_after_failed_primary" in page.text
    assert "registered_waiting_for_inputs" in page.text
    for path in ("/llms.txt", "/skill.md"):
        document = client.get(path)
        assert document.status_code == 200, path
        assert "/advantage/v3.json" in document.text, path
        assert "/advantage/v3" in document.text, path
