from fastapi.testclient import TestClient

from docket.api import create_app
from docket.hire.catalogue import SERVICES
from docket.hire.comparison import compare
from docket.marketplace.models import ACTIVATIONS


def test_service_cards_distinguish_one_shot_from_session_execution():
    assert "One-shot" in ACTIVATIONS["policy_action"]
    assert "software" in ACTIVATIONS["policy_action"]


def test_comparison_browser_page_and_json_share_the_same_services(tmp_path):
    with TestClient(create_app(tmp_path / "site.sqlite3")) as client:
        data = client.get("/compare").json()
        page = client.get("/compare", headers={"accept": "text/html"})
        assert page.headers["content-type"].startswith("text/html")
        assert "Compare services" in page.text
        for row in data["rows"]:
            assert row["name"] in page.text
        assert "unaided human" in page.text
        assert "Research-only" in page.text


def test_comparison_discloses_agent_operated_baseline():
    payload = compare(list(SERVICES.values()))
    assert "one human" not in payload["summary"]["reading"]
    assert "agent-operated" in payload["summary"]["reading"]


def test_v1_summary_distinguishes_free_run_from_historical_quote(tmp_path):
    with TestClient(create_app(tmp_path / "cost.sqlite3")) as client:
        response = client.get("/advantage", headers={"accept": "text/html"})
        summary = response.text.split('id="one-page"', 1)[1].split("</section>", 1)[0]
        assert "agent 0.01 USDT" not in summary
        assert "agent 0 · manual 0" in summary
        assert "agent-versus-person" not in summary
