from pathlib import Path

from docket.advantage.v2 import page as v2_page
from docket.advantage.v2 import report as v2_report


WEB = Path(__file__).resolve().parents[1] / "docket" / "api" / "web"
PAGES = tuple(sorted(WEB.glob("*.html")))


def test_every_surface_uses_the_restrained_light_stylesheet():
    css = (WEB / "style.css").read_text(encoding="utf-8")

    assert "color-scheme: light" in css
    assert "color-scheme: dark" not in css
    assert 'content: "LP"' not in css
    assert len(PAGES) == 8
    for page in PAGES:
        assert 'href="/static/style.css?v=9"' in page.read_text(encoding="utf-8")


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
