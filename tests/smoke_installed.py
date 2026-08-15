"""Exercise the four category hires through an installed wheel, never the checkout."""

import os
import tempfile
from dataclasses import replace
from pathlib import Path

import docket
import docket.agents.grid.operator
import docket.agents.pancake.doctor
import docket.agents.venus.guard
import docket.agents.yield_router.router
from fastapi.testclient import TestClient

from docket.api import create_app
from docket.hire import catalogue

WORKSPACE = Path(os.environ["GITHUB_WORKSPACE"]).resolve()
INSTALLED_PACKAGE = Path(docket.__file__).resolve()
assert not INSTALLED_PACKAGE.is_relative_to(WORKSPACE), (
    f"smoke imported the checkout at {INSTALLED_PACKAGE}, not the installed wheel"
)

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
