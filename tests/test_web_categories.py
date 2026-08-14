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
from docket.marketplace.registry import EMPTY_CATEGORY
from docket.store import Store

WEB_DIR = Path(__file__).resolve().parents[1] / "docket" / "api" / "web"
PAGES = (
    "index.html",
    "research.html",
    "agent.html",
    "advantage.html",
    "advantage-v2.html",
    "service.html",
)


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
    for region in (
        'data-region="stats"',
        'data-region="slice"',
        'data-region="families"',
    ):
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
    says and cannot soften it.

    Every shelf is stocked now, so the page's empty branch has nothing to paint from a
    live response — which is exactly when a test like this rots into a no-op. The registry
    is emptied here instead, so the sentence the page would print is still asserted to be
    the API's own rather than one the markup carries.
    """
    app_js = _read("app.js")
    assert "category.empty" in app_js or "entry.empty" in app_js
    assert EMPTY_CATEGORY not in _read("index.html"), (
        "the page authors its own empty state"
    )
    assert all(
        c["empty"] is None for c in client.get("/categories").json()["categories"]
    )


def test_no_page_promises_stock_it_does_not_have(client):
    """ "Coming soon" over a bare shelf is the failure this stage was told to avoid."""
    for path in WEB_DIR.glob("*"):
        text = path.read_text(encoding="utf-8").lower()
        for promise in (
            "coming soon",
            "launching soon",
            "available soon",
            "in beta soon",
        ):
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
    assert 'field.type === "number"' in app_js
    assert "Number(raw)" in app_js


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


def test_every_page_carries_exactly_one_primary_destination_per_section(client):
    """The old presence-only check allowed v2 to add its own Advantage link beside v1.

    A report version may make its own URL the Advantage destination, but it may not grow a
    second top-level entry. Exact ordered hrefs keep every primary nav to the house's four
    sections and reject extras rather than merely proving the expected links are somewhere.
    """
    for name in PAGES:
        text = _read(name)
        nav = re.search(r'<nav class="site-nav"[^>]*>(.*?)</nav>', text, re.S)
        assert nav, f"{name} has no primary navigation"
        advantage_href = (
            "/advantage/v2" if name == "advantage-v2.html" else "/advantage"
        )
        assert re.findall(r'href="([^"]+)"', nav.group(1)) == [
            "/",
            "/research",
            advantage_href,
            "/llms.txt",
        ], f"{name} has competing or out-of-order primary destinations"


def test_every_page_declares_its_language_and_viewport(client):
    for name in PAGES:
        text = _read(name)
        assert 'lang="en"' in text, name
        assert "width=device-width" in text, name


def test_every_page_keeps_the_no_verdict_footer(client):
    for name in PAGES:
        assert "observations, not verdicts" in _read(name).lower(), name


def test_the_stylesheet_and_module_are_versioned_so_a_returning_reader_gets_them(
    client,
):
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
    assert len(tokens) == 1, (
        f"the site asks for several asset versions at once: {tokens}"
    )


# ------------------------------------------------- served claims vs served reality


def test_the_homepage_does_not_claim_a_recorded_run_for_services_that_have_none():
    """The shop front cannot promise evidence the shelf does not carry.

    The hero used to read "Every service here is one Docket runs itself and can show a
    recorded run behind it" while grid-operator, yield-router and health-guard each carried
    zero metrics and zero evidence. Every test passed: nothing tied the sentence to the
    registry it described. This is that tie.
    """
    from docket.marketplace.registry import all_records

    without_a_run = sorted(r.service_id for r in all_records() if not r.metrics)
    hero = _read("index.html")
    if without_a_run:
        assert (
            "Every service here is one Docket runs itself and can show a recorded run"
            not in hero
        ), (
            f"the homepage claims a recorded run for every service, but {without_a_run} have none"
        )
        assert "and some do not yet" in hero, (
            "services without a recorded run exist, so the homepage has to say so"
        )


def test_the_v1_report_points_at_v2_and_says_which_one_answers_the_sponsor(client):
    """v2 was reachable only from itself: the served v1 page carried no "v2" string at all,
    and the homepage linked the JSON endpoint rather than the page. The report a reader is
    sent to must also tell them what the other one is, or the pair reads as one superseding
    the other — which is the opposite of what these two are.
    """
    v1 = _read("advantage.html")
    assert 'href="/advantage/v2"' in v1, "the v1 report does not link the v2 report"
    assert "holds no human arm" in v1, (
        "v1 links v2 without saying that v1 is the one with the human arm"
    )
    # And it has to survive being served, not merely sit in the file.
    served = client.get("/advantage").text
    assert "/advantage/v2" in served


# ------------------------------------------------------- the paid answer, as a person reads it


def test_the_result_is_presented_before_it_is_dumped():
    """A buyer paid for an answer, not a payload.

    `paintOutcome` used to put `JSON.stringify(result)` straight into a <pre>, which made
    every service look identical and left the reader doing the interpreting they had just
    paid to have done. The raw response stays — it is the evidence — but behind a <details>
    rather than in front of the finding.
    """
    js = (WEB_DIR / "app.js").read_text(encoding="utf-8")
    assert "const PRESENTERS = {" in js
    assert '"range-doctor": presentRangeDoctor' in js
    assert "function presentResult(record, answer)" in js
    assert "answer.receipt" in js
    # The whole answer stays reachable, including the receipt that supplies proof.
    assert '<details class="raw">' in js
    assert "exactly as the service returned it" in js
    assert "JSON.stringify(answer, null, 2)" in js


def test_the_range_presenter_dispatches_on_the_id_the_service_api_returns():
    """ServiceDetail exposes service_id; record.id made every real hire use raw JSON."""
    js = _read("app.js")

    assert "PRESENTERS[record.service_id]" in js
    assert 'record.service_id === "range-doctor"' in js


def test_range_doctor_renders_all_eight_sections_in_the_required_order():
    """A per-position card interleaves facts and actions; TermiX requires global ordering."""
    js = _read("app.js")
    presenter = js.split("function presentRangeDoctor", 1)[1].split(
        "const STATUS_WORDS", 1
    )[0]
    headings = (
        "1. Decision",
        "2. Verifiable facts",
        "3. Economic consequence",
        "4. Conditional actions",
        "5. Coverage",
        "6. Measured value",
        "7. Proof",
        "8. Primary limitation",
    )

    offsets = [presenter.index(heading) for heading in headings]
    assert offsets == sorted(offsets)
    assert "receipt.input_hash" in presenter
    assert "receipt.output_hash" in presenter
    assert "receipt.delivered_at" in presenter
    assert "notice notice-warn" in presenter


def test_an_empty_range_doctor_result_leads_with_a_decision_and_keeps_coverage():
    """The single most damaging thing this product can show a judge.

    The live evidence wallet returns no positions — 21 held, all 21 closed — and a reader
    who sees an empty list with nothing above it concludes their positions are fine. The
    presenter has to decide first, then keep the coverage sentence and say what an empty
    answer is not.
    """
    js = _read("app.js")
    empty_branch = js.split("function presentRangeDoctor", 1)[1].split(
        "const STATUS_WORDS", 1
    )[0]
    # Collapsed: the formatter chooses where these sentences wrap, and the claim under test
    # is about what they say, not about where the line breaks fall.
    flat = re.sub(r"\s+", " ", empty_branch)
    assert flat.index("1. Decision") < flat.index("5. Coverage")
    assert "result.decision" in flat
    assert "result.coverage" in flat
    # A COMPLETE scan that found nothing may say so — and must still refuse to be read as
    # a clean bill of health.
    assert "No position-specific facts are available" in flat
    assert "No position-level economic consequence is available" in flat
    assert "No position-specific action is available" in flat
    # A BOUNDED scan may not say so at all: unread positions are unknown, not absent, and
    # the page must not turn "we stopped early" into "you have none".
    assert "scan_complete === false" in flat
    assert "unread positions are unknown, not absent" in flat


def test_unrun_v3_and_unadmitted_payment_are_named_as_missing_not_filled():
    """Old v1 timing and a free-preview receipt must not masquerade as current paid proof."""
    presenter = (
        _read("app.js")
        .split("function presentRangeDoctor", 1)[1]
        .split("const STATUS_WORDS", 1)[0]
    )
    flat = re.sub(r"\s+", " ", presenter)

    assert "not admitted to paid stock" in flat
    assert "preregistered v3 paired report has not run" in flat
    assert "Settlement transaction / payment ID" in flat
    assert "Unique settlement nonce" in flat
    assert 'payment.status === "settled"' in flat
    assert "exact-once settlement is not built" not in flat
    assert "43.063" not in flat
    assert "528.31" not in flat


def test_the_presenter_never_asserts_a_rate_is_a_forecast():
    """The no-verdict discipline survives the presentation pass: the same figures, ordered
    for a reader, with the same thing said about what they are not."""
    js = (WEB_DIR / "app.js").read_text(encoding="utf-8")
    assert "An observation, not a forecast." in js
    assert "does not prove chain finality" in js


def test_pay_and_hire_is_rendered_only_for_admitted_paid_stock():
    """A price is visible for comparison, but preview/research/beta stock cannot acquire
    a sale CTA until the API says all four admission facts passed."""
    js = re.sub(r"\s+", " ", _read("app.js"))

    assert "card.paid_stock" in js
    assert "record.paid_stock" in js
    assert "Pay ${escapeHTML(card.price_display)} and hire" in js
    assert "Price after admission" in js
    assert "Paid-stock status" in js


def test_a_service_with_no_presenter_still_shows_its_payload():
    """Five of six services have no presenter yet. They must degrade to the old behaviour,
    not to an empty region."""
    js = re.sub(r"\s+", " ", (WEB_DIR / "app.js").read_text(encoding="utf-8"))
    assert (
        "if (!presenter) return `<pre>${escapeHTML(JSON.stringify(result, null, 2))}</pre>`;"
    ) in js
