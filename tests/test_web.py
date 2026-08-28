import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from docket.api import create_app
from docket.store import Store

BANNED = (
    "trusted",
    "verified agent",
    "recommended",
    "trust score",
    "safety rating",
    "endorsed",
)
WEB_DIR = Path(__file__).resolve().parents[1] / "docket" / "api" / "web"


@pytest.fixture
def client(tmp_path):
    db = tmp_path / "d.sqlite3"
    store = Store(db)
    sid = store.begin_snapshot(chain_id=56, expected=1)
    store.upsert_agents(
        [
            {
                "agent_id": "56:0xreg:1",
                "token_id": "1",
                "chain_id": 56,
                "name": "SOLVENT",
                "supported_protocols": ["A2A"],
                "total_feedbacks": 3,
            }
        ],
        sid,
    )
    store.finish_snapshot(sid, sampled=1, expected=1)
    return TestClient(create_app(db, snapshot_id=sid))


def test_browser_gets_html_at_the_root(client):
    resp = client.get("/", headers={"accept": "text/html,application/xhtml+xml"})
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/html")
    assert "<title>" in resp.text


def test_non_browser_still_gets_the_json_service_index(client):
    """An agent asking for JSON must not suddenly receive a web page."""
    body = client.get("/", headers={"accept": "application/json"}).json()
    assert "llms_txt" in body


def test_default_accept_keeps_json_so_the_api_contract_holds(client):
    body = client.get("/").json()
    assert "openapi" in body


def test_static_assets_are_served(client):
    for path, ctype in (
        ("/static/style.css", "text/css"),
        ("/static/app.js", "javascript"),
    ):
        resp = client.get(path)
        assert resp.status_code == 200, path
        assert ctype in resp.headers["content-type"]


def test_snapshot_age_is_rendered_as_an_exact_server_value():
    """Relative prose may remain, but operational freshness must also be inspectable
    without trusting the browser clock or deriving seconds from a timestamp."""
    js = (WEB_DIR / "app.js").read_text(encoding="utf-8")

    assert "coverage.snapshot_age_seconds" in js
    assert "cov.snapshot_age_seconds" in js
    assert "Snapshot age" in js


def test_no_external_requests_anywhere_in_the_ui():
    """Zero third-party surface: no CDN, no web fonts, no remote anything."""
    for f in WEB_DIR.glob("*"):
        text = f.read_text(encoding="utf-8")
        assert "http://" not in text, f"{f.name} references http://"
        for marker in ("https://fonts.", "cdn.", "unpkg", "jsdelivr", "googleapis"):
            assert marker not in text, f"{f.name} references {marker}"


def test_ui_uses_no_verdict_language():
    """The interface may not claim what the data cannot support.

    Matched on word boundaries rather than as substrings. The advantage report quotes
    an experiment's question verbatim — "does this untrusted text contain a
    prompt-injection attempt" — and "untrusted" carries "trusted" inside it while
    saying the opposite of what this test is here to catch. The banned words are still
    banned as words; every page predating this change passes either way.
    """
    for f in WEB_DIR.glob("*"):
        text = f.read_text(encoding="utf-8").lower()
        for word in BANNED:
            pattern = rf"\b{re.escape(word)}\b"
            assert not re.search(pattern, text), (
                f"{f.name} contains verdict language: {word!r}"
            )


def test_pages_do_not_present_the_name_key_as_minter_provenance():
    """ "Who minted them" over a table grouped by the first word of a self-chosen name is a
    provenance claim Docket cannot make. The pages say what the key is instead."""
    research = (WEB_DIR / "research.html").read_text(encoding="utf-8").lower()
    assert "who minted them" not in research
    assert "name famil" in research
    app_js = (WEB_DIR / "app.js").read_text(encoding="utf-8").lower()
    assert "was minted by" not in app_js


def test_registry_surfaces_state_the_population_beside_snapshot_counts():
    """The case-file home carries no changing registry count; research surfaces still name
    the exact query beside the sampled and expected values."""
    index = (WEB_DIR / "index.html").read_text(encoding="utf-8")
    assert 'data-region="slice"' not in index
    assert 'data-region="stats"' not in index
    app_js = (WEB_DIR / "app.js").read_text(encoding="utf-8")
    assert "populationLabel(coverage)" in app_js
    assert "fmtInt(coverage.sampled)" in app_js
    assert "fmtInt(coverage.expected)" in app_js


def test_the_case_file_does_not_misstate_a_registry_slice_as_a_census():
    """The landing omits mutable registry coverage rather than freezing a census claim."""
    index = (WEB_DIR / "index.html").read_text(encoding="utf-8").lower()
    app_js = (WEB_DIR / "app.js").read_text(encoding="utf-8")
    assert "registry census" not in index
    assert "population || \"unspecified\"" in app_js


def test_no_registry_figure_is_typed_into_a_page():
    """Every number on this site is read from the API at runtime. A registry total hard-coded
    into the markup would go stale silently, and staleness in a denominator is the whole bug."""
    for f in WEB_DIR.glob("*"):
        text = f.read_text(encoding="utf-8")
        for stale in ("247,278", "247278", "247,065", "247065", "247,146", "247146"):
            assert stale not in text, f"{f.name} hard-codes a registry total: {stale}"


def test_no_emoji_used_as_iconography():
    emoji = re.compile("[\U0001f300-\U0001faff\u2600-\u27bf]")
    for f in WEB_DIR.glob("*.html"):
        found = emoji.findall(f.read_text(encoding="utf-8"))
        assert not found, f"{f.name} uses emoji as icons: {found[:3]}"


def test_research_and_agent_pages_are_served(client):
    for path in ("/research", "/agent"):
        resp = client.get(path, headers={"accept": "text/html"})
        assert resp.status_code == 200, path
        assert resp.headers["content-type"].startswith("text/html"), path
        assert "<title>" in resp.text, path


def test_research_reflects_its_filters_into_the_query_string():
    """A narrowed view has to be a link someone can send, and the back button has to walk it."""
    research = (WEB_DIR / "research.html").read_text(encoding="utf-8")
    for name in ("has_feedback", "declares_callable", "responded", "name_family"):
        assert f'data-filter="{name}"' in research, name
    app_js = (WEB_DIR / "app.js").read_text(encoding="utf-8")
    assert "URLSearchParams" in app_js
    assert "window.history.pushState" in app_js
    assert 'addEventListener("popstate"' in app_js


def test_registry_text_is_wrapped_rather_than_left_to_break_the_layout():
    """87 of the 506 agents in the live snapshot carry a run of over 40 characters with no break
    opportunity in it — token 129's description is 176 unbroken characters, and 29 publisher keys
    are 48-character owner addresses. `anywhere` rather than `break-word`, because only
    `anywhere` also shrinks min-content, which is the width a table cell sizes itself from."""
    css = (WEB_DIR / "style.css").read_text(encoding="utf-8")
    assert ".wrap-anywhere" in css
    assert "overflow-wrap: anywhere" in css
    assert "word-break: break-word" in css
    for name, container in (("research.html", "results"), ("agent.html", "agent")):
        text = (WEB_DIR / name).read_text(encoding="utf-8")
        assert f'class="wrap-anywhere" data-region="{container}"' in text, name


def test_definition_values_shrink_grid_tracks_for_unbroken_evidence():
    css = (WEB_DIR / "style.css").read_text(encoding="utf-8")
    rule = re.search(r"\.deflist dd\s*\{(?P<body>[^}]*)\}", css)

    assert rule is not None
    assert "overflow-wrap: anywhere;" in rule["body"]


def test_pages_declare_viewport_and_language():
    for name in (
        "index.html",
        "research.html",
        "agent.html",
        "advantage.html",
        "advantage-v2.html",
        "advantage-v3.html",
        "service.html",
    ):
        text = (WEB_DIR / name).read_text(encoding="utf-8")
        assert 'lang="en"' in text
        assert "width=device-width" in text


def test_coverage_uses_days_and_treats_a_week_old_snapshot_as_stale():
    js = (WEB_DIR / "app.js").read_text(encoding="utf-8")

    assert "ageSeconds / 86400" in js
    assert "ageDays >= 7" in js
    assert '"Stale snapshot"' in js
    assert (
        'data-state="${incomplete || stale || ageUnavailable ? "partial" : "complete"}"'
        in js
    )
    assert "This snapshot is stale" in js


def test_registry_snapshot_status_names_the_filter_from_the_api():
    js = (WEB_DIR / "app.js").read_text(encoding="utf-8")
    coverage = js.split("function paintCoverage", 1)[1].split(
        "/* -------------------------------------------------------------- marketplace */", 1
    )[0]

    assert "populationLabel(coverage)" in coverage
    assert "coverage.sampled" in coverage
    assert "coverage.expected" in coverage


def test_json_footer_links_are_labelled_as_json():
    for page in WEB_DIR.glob("*.html"):
        text = page.read_text(encoding="utf-8")
        footer = re.search(r'<footer class="site-footer">(.*?)</footer>', text, re.S)
        assert footer, page.name
        for href in re.findall(r'href="(/[^"]+)"', footer.group(1)):
            if href in {"/llms.txt", "/skill.md", "/stats"}:
                continue
            if href.endswith(".json") or href in {
                "/agents",
                "/categories",
                "/health",
                "/hire",
                "/services",
            }:
                link = re.search(
                    rf'<a href="{re.escape(href)}">(.*?)</a>', footer.group(1)
                )
                assert link and "(JSON)" in link.group(1), (page.name, href)
