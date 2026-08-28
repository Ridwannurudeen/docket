from pathlib import Path
import re

from fastapi.testclient import TestClient

from docket.advantage.v2 import page as v2_page
from docket.advantage.v2 import report as v2_report
from docket.api import create_app
from docket.store import Store


WEB = Path(__file__).resolve().parents[1] / "docket" / "api" / "web"
PAGES = tuple(sorted(WEB.glob("*.html")))


def test_every_surface_uses_the_restrained_light_stylesheet():
    css = (WEB / "style.css").read_text(encoding="utf-8")

    assert "color-scheme: light" in css
    assert "color-scheme: dark" not in css
    assert 'content: "LP"' not in css
    assert len(PAGES) == 9
    for page in PAGES:
        assert 'href="/static/style.css?v=11"' in page.read_text(encoding="utf-8")


def test_evidence_landings_link_to_depth_instead_of_collapsing_it():
    v1 = (WEB / "advantage.html").read_text(encoding="utf-8")
    pancake = (WEB / "pancake.html").read_text(encoding="utf-8")
    v3 = (WEB / "advantage-v3.html").read_text(encoding="utf-8")
    v2 = v2_page.render(v2_report.report())

    assert '<a href="/advantage/v1/01-liquidity">' in v1
    assert '<a href="/advantage/v1/02-trading">' in v1
    assert '<a href="/advantage/v1/03-security">' in v1
    assert "Inspect the timing, cost, output, and scope rules" in v1
    assert "Inspect the full outputs, manual steps, and recorded notes" in v1
    assert "Inspect all linked observations" in pancake
    assert "<!-- v3-family-index -->" in v3
    for experiment in v2_report.report()["experiments"]:
        assert f'href="/advantage/v2/{experiment["experiment_id"]}"' in v2
    assert "Every run behind those figures" not in v2
    assert '<details class="evidence-details">' not in v2
    assert pancake.index("<summary") < pancake.index("</details>")


def test_stats_has_a_server_rendered_human_surface_without_moving_its_json(tmp_path):
    db = tmp_path / "stats-html.sqlite3"
    store = Store(db)
    snapshot = store.begin_snapshot(chain_id=56, expected=0)
    store.finish_snapshot(snapshot, sampled=0, expected=0)
    client = TestClient(create_app(db, snapshot_id=snapshot))

    machine = client.get("/stats")
    human = client.get("/stats", headers={"accept": "text/html"})

    assert machine.headers["content-type"].startswith("application/json")
    assert machine.json()["coverage"]["snapshot_id"] == snapshot
    assert human.headers["content-type"].startswith("text/html")
    assert "Registry coverage" in human.text
    assert "0 of 0 agents sampled" in human.text
    assert "One GET per declared A2A or MCP endpoint" in human.text


def test_navigation_and_generated_evidence_use_one_presentation_vocabulary():
    working_page_expected = (
        ("/", "Services"),
        ("/pancake", "PancakeSwap"),
        ("/research", "Browse agents"),
        ("/advantage", "Advantage report"),
        ("/llms.txt", "API"),
    )
    for page in PAGES:
        document = page.read_text(encoding="utf-8")
        nav = re.search(r'<nav class="site-nav".*?</nav>', document, re.S).group(0)
        links = tuple(
            re.findall(r'<a href="([^"]+)"(?: aria-current="page")?>([^<]+)</a>', nav)
        )
        expected = (
            (
                ("#evidence", "Evidence"),
                ("#services", "Services"),
                ("#experiments", "Experiments"),
                ("/advantage/v3.json", "Raw data"),
            )
            if page.name == "index.html"
            else working_page_expected
        )
        assert links == expected, page.name

    v2_source = (
        Path(__file__).resolve().parents[1] / "docket" / "advantage" / "v2" / "page.py"
    ).read_text(encoding="utf-8")
    script = (WEB / "app.js").read_text(encoding="utf-8")

    assert "<h4>" not in v2_source
    assert "displayTimestamp" in script
    assert "<caption>Recorded scanner detections for this run.</caption>" in script
    assert "<caption>Eligible pools returned for this run.</caption>" in script
    assert "<caption>Grid levels returned for this preview.</caption>" in script

    v1 = (WEB / "advantage.html").read_text(encoding="utf-8")
    for task_id in ("01-liquidity", "02-trading", "03-security"):
        assert f'id="{task_id}"' in v1
