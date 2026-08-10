"""The journey a person with no prior knowledge has to be able to walk.

Land, find a service by the job it does, understand what it does and what it cannot do,
and reach a control that actually runs it. Before this stage the site ended at
"inspect": no page linked /hire, hiring was POST-only, and nothing anywhere carried a
category. These tests hold each step of that walk open, and hold the honesty of the
existing pages in place while the copy moves from indictment to warranty.

Every figure on this site is still read from the API at runtime. So most of what is
asserted here is that the page has somewhere to put an answer and that app.js paints it
from the response — never that a number is present in the markup, which would be the
staleness bug these pages exist to avoid.
"""

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from docket.api import create_app
from docket.store import Store

WEB_DIR = Path(__file__).resolve().parents[1] / "docket" / "api" / "web"
PAGES = ("index.html", "research.html", "agent.html", "advantage.html", "service.html")


@pytest.fixture
def client(tmp_path):
    db = tmp_path / "w.sqlite3"
    store = Store(db)
    sid = store.begin_snapshot(chain_id=56, expected=1)
    store.upsert_agents(
        [
            {
                "agent_id": "56:0xreg:1",
                "token_id": "1",
                "chain_id": 56,
                "name": "OpenOdds.Ai",
                "supported_protocols": ["A2A"],
                "total_feedbacks": 3,
            }
        ],
        sid,
    )
    store.finish_snapshot(sid, sampled=1, expected=1)
    return TestClient(create_app(db, snapshot_id=sid))


def _read(name: str) -> str:
    return (WEB_DIR / name).read_text(encoding="utf-8")


# ----------------------------------------------------------------------- routes


def test_every_page_of_the_journey_is_served_as_html(client):
    for path in ("/", "/research", "/service", "/agent", "/advantage"):
        resp = client.get(path, headers={"accept": "text/html"})
        assert resp.status_code == 200, path
        assert resp.headers["content-type"].startswith("text/html"), path
        assert "<title>" in resp.text, path


def test_the_old_browse_url_moves_rather_than_breaking(client):
    """/browse was published. It becomes one canonical URL, permanently redirected, so a
    link somebody already has still lands on the page it named."""
    resp = client.get("/browse", follow_redirects=False)
    assert resp.status_code == 308
    assert resp.headers["location"] == "/research"
    assert client.get("/browse").status_code == 200


def test_the_moved_url_carries_the_filters_it_was_asked_for(client):
    """Every filter on that page lives in the query string, so a narrowed view is a link
    someone sends. A redirect that dropped it would answer a request for one slice with
    the whole snapshot and say nothing about it — the same defect as the retired
    `publisher` filter, and 308 is permanent, so a browser would cache the broken mapping."""
    query = "has_feedback=true&name_family=gembots"
    resp = client.get(f"/browse?{query}", follow_redirects=False)
    assert resp.status_code == 308
    assert resp.headers["location"] == f"/research?{query}"


# ------------------------------------------------------- the home leads with jobs


def test_the_home_leads_with_the_jobs_and_keeps_the_evidence_beneath_them(client):
    """The evidence is the warranty, not the pitch — so it moves below the jobs. Moves,
    not goes: every region the coverage discipline lives in is still on the page."""
    index = _read("index.html")
    jobs = index.index('data-region="jobs"')
    for region in ('data-region="stats"', 'data-region="slice"', 'data-region="families"'):
        assert region in index, region
        assert jobs < index.index(region), f"{region} sits above the jobs"


def test_the_home_paints_the_four_jobs_from_the_api_rather_than_typing_them_in(client):
    """A job label typed into the markup is a label that drifts from /categories."""
    app_js = _read("app.js")
    assert "paintJobs" in app_js
    assert '"/categories"' in app_js
    for label in ("Keep LP earning", "Run a capped grid", "Protect a loan"):
        assert label not in _read("index.html"), label


def test_a_category_with_nothing_in_it_renders_the_api_s_own_empty_sentence(client):
    """The empty state is served, not authored twice: the page prints what /categories
    says and cannot soften it."""
    app_js = _read("app.js")
    assert "category.empty" in app_js or "entry.empty" in app_js
    body = client.get("/categories").json()
    empty = [c for c in body["categories"] if c["service_count"] == 0]
    assert empty, "this test means nothing if every shelf is stocked"


def test_no_page_promises_stock_it_does_not_have(client):
    """ "Coming soon" over a bare shelf is the failure this stage was told to avoid."""
    for path in WEB_DIR.glob("*"):
        text = path.read_text(encoding="utf-8").lower()
        for promise in ("coming soon", "launching soon", "available soon", "in beta soon"):
            assert promise not in text, f"{path.name} promises: {promise}"


def test_the_home_says_what_a_reader_can_do_before_it_says_what_is_wrong(client):
    index = _read("index.html")
    heading = re.search(r"<h1>(.*?)</h1>", index, re.S)
    assert heading, "the home has no h1"
    assert "hire" in heading.group(1).lower()


def test_the_home_names_the_json_behind_it_when_scripting_is_off(client):
    index = _read("index.html")
    noscript = re.search(r"<noscript>(.*?)</noscript>", index, re.S).group(1)
    for path in ("/categories", "/services"):
        assert path in noscript, path


# ------------------------------------------------------------- the service page


def test_the_service_page_has_the_activation_control_that_did_not_exist(client):
    """The dead end this stage exists to remove: no page linked /hire, and hiring was
    POST-only. This is the control."""
    service = _read("service.html")
    for region in ("service", "activate", "outcome"):
        assert f'data-region="{region}"' in service, region
    app_js = _read("app.js")
    assert "initService" in app_js
    # The page posts to the hire_path the API handed it rather than building a URL of its
    # own, so the control cannot drift from the contract /services publishes.
    assert "postJSON(record.hire_path" in app_js


def test_the_service_page_builds_its_form_from_the_declared_input_schema(client):
    app_js = _read("app.js")
    assert "input_schema" in app_js
    # The one declared string field that carries newlines is warden-scan's payload, and
    # a single-line input cannot hold one.
    assert "textarea" in app_js.lower()


def test_the_service_page_shows_the_receipt_it_was_handed(client):
    app_js = _read("app.js")
    for field in ("input_hash", "output_hash", "delivered_at"):
        assert field in app_js, field


def test_the_service_page_states_the_limitations_and_the_evidence(client):
    app_js = _read("app.js")
    for field in ("limitations", "evidence", "identity_note"):
        assert field in app_js, field


def test_a_card_that_names_an_identity_does_not_imply_docket_indexed_it(client):
    """The detail page carries the note; a card is where the reader decides. "Bound to the
    BSC ERC-8004 agent …" alone reads as an agent Docket has observations for, and for the
    one binding Docket's own stock has, it has none — that agent is not in the served
    snapshot. So the card says where that question is answered."""
    app_js = _read("app.js")
    assert "card.agent_id" in app_js
    assert "snapshot holds that agent is stated on the service page" in app_js


def test_a_metric_can_only_be_rendered_with_its_denominator_attached(client):
    """`display` carries the denominator inside the string. Painting `numerator` on its
    own is how a rate loses its base, so the page has no access to it."""
    app_js = _read("app.js")
    assert "metric.display" in app_js
    assert "metric.numerator" not in app_js


def test_the_service_page_works_from_the_command_line_when_scripting_is_off(client):
    service = _read("service.html")
    noscript = re.search(r"<noscript>(.*?)</noscript>", service, re.S).group(1)
    assert "/services" in noscript
    assert "POST" in noscript and "/hire/" in noscript


# ------------------------------------------------------------ the research route


def test_the_registry_browser_moved_intact(client):
    """Same page, new route and new framing: it is the raw plane, not the shop front."""
    research = _read("research.html")
    for name in ("has_feedback", "declares_callable", "responded", "name_family"):
        assert f'data-filter="{name}"' in research, name
    assert 'class="wrap-anywhere" data-region="results"' in research
    assert 'data-page="research"' in research
    assert "research" in _read("app.js")


def test_nothing_inside_the_site_still_links_at_the_moved_url(client):
    """The redirect is there for links other people already hold. A link this site emits
    itself should go straight to the page rather than take a hop it controls."""
    for path in WEB_DIR.glob("*"):
        text = path.read_text(encoding="utf-8")
        assert 'href="/browse"' not in text, f"{path.name} still links at /browse"


def test_the_research_page_says_docket_assigns_these_agents_no_category(client):
    """The one line that keeps the two planes apart in a reader's head."""
    research = _read("research.html").lower()
    assert "categor" in research


# ------------------------------------------------------------------ every page


def test_every_page_carries_the_same_navigation(client):
    for name in PAGES:
        text = _read(name)
        for href in ('href="/"', 'href="/research"', 'href="/advantage"', 'href="/llms.txt"'):
            assert href in text, f"{name} is missing {href}"


def test_every_page_declares_its_language_and_viewport(client):
    for name in PAGES:
        text = _read(name)
        assert 'lang="en"' in text, name
        assert "width=device-width" in text, name


def test_every_page_keeps_the_no_verdict_footer(client):
    for name in PAGES:
        assert "observations, not verdicts" in _read(name).lower(), name


def test_the_stylesheet_and_module_are_versioned_so_a_returning_reader_gets_them(client):
    """Measured, not guessed: a browser that had already loaded this site served the old
    /static/style.css against the new markup, because nothing about the URL had changed —
    the job grid lost its layout and the run form its controls. The version query is what
    makes a redeploy reach somebody who has been here before."""
    for name in PAGES:
        text = _read(name)
        assert 'href="/static/style.css?v=' in text, name
        # advantage.html reads no live data and loads no module; every page that does
        # load one has to version it for the same reason.
        if "/static/app.js" in text:
            assert 'src="/static/app.js?v=' in text, name


def test_every_page_asks_for_the_same_version_of_the_same_two_files():
    """One stylesheet and one module serve the whole site, so one token has to cover them.
    A bump applied to some pages and not others is worse than no bump at all: the pages
    that moved pull the new file, the pages that did not keep the old one out of cache,
    and which design a reader sees depends on where they landed."""
    tokens = set()
    for name in PAGES:
        text = _read(name)
        tokens.update(re.findall(r'/static/(?:style\.css|app\.js)\?v=([^"]+)', text))
    assert len(tokens) == 1, f"the site asks for several asset versions at once: {tokens}"
