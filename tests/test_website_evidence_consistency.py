"""Public report summaries must preserve the limitations in their source records."""

import json
from pathlib import Path

from fastapi.testclient import TestClient

from docket.api import create_app

ROOT = Path(__file__).resolve().parents[1]


def test_lp_baseline_disclosure_is_visible_before_report_details(tmp_path):
    record = json.loads(
        (ROOT / "docket/advantage/experiments/01-liquidity.json").read_text()
    )
    assert "performed by this agent driving a real Chrome browser" in record["notes"]
    with TestClient(create_app(tmp_path / "audit.sqlite3")) as client:
        page = client.get("/advantage").text
    hero = page.split('<section class="hero">', 1)[1].split("</section>", 1)[0]
    assert "agent-operated browser" in hero
    assert "unaided human" in hero
    assert "time saved was real" not in page


def test_report_roles_do_not_imply_sponsor_acceptance_or_exclude_v3(tmp_path):
    with TestClient(create_app(tmp_path / "audit.sqlite3")) as client:
        for route in ("/advantage", "/advantage/v2", "/advantage/v3"):
            page = client.get(route).text
            assert "does not establish sponsor eligibility" in page, route
        page = client.get("/advantage/v2").text
    assert "It is the only report here" not in page
    assert "No transaction was sent, anywhere in this build" not in page
