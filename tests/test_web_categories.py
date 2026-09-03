"""The journey a person with no prior knowledge has to be able to walk.

Land, find a service by the job it does, understand what it does and what it cannot do,
and reach a control that actually runs it. Before this stage the site ended at
"inspect": no page linked /hire, hiring was POST-only, and nothing anywhere carried a
category. These tests hold each step of that walk open, and hold the honesty of the
existing pages in place while the copy moves from indictment to warranty.

The homepage is a server-delivered public case file. Its small, frozen fact inventory is
present without scripting and guarded against the committed evidence; live registry and
service-detail surfaces still read their changing values from the API.
"""

import re
import subprocess
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
    "advantage-v3.html",
    "service.html",
    "pancake.html",
)
ASSET_PAGES = (*PAGES, "stats.html")


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


def _plain(markup: str) -> str:
    return " ".join(re.sub(r"<[^>]+>", " ", markup).split())


# ----------------------------------------------------------------------- routes


def test_every_page_of_the_journey_is_served_as_html(client):
    for path in (
        "/",
        "/research",
        "/service",
        "/agent",
        "/advantage",
        "/advantage/v2",
        "/advantage/v3",
    ):
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


# --------------------------------------------------- the home is a public case file


def test_the_home_leads_with_a_marketplace_and_publishes_the_loss_immediately(client):
    """The product leads and the loss still arrives on the same page, without scripting.

    The pivot moved the adverse finding below the listings; it did not move it off the
    home page, out of the served HTML, or behind a control a reader has to operate.
    """
    index = _read("index.html")
    h1 = re.search(r"<h1[^>]*>(.*?)</h1>", index, re.S)
    assert h1 and "Find BSC agents that actually work." in h1.group(1)
    hero = re.search(r'<section class="case-hero".*?</section>', index, re.S).group(0)
    assert 'href="#explore"' in hero
    assert 'href="/activate?service=range-doctor&amp;demo=1"' in hero

    evidence = re.search(r'<section[^>]+id="evidence".*?</section>', index, re.S).group(
        0
    )
    assert "Hire by evidence, not promises." in evidence
    assert (
        "We measured our own security agent against a human. The human won." in evidence
    )
    assert 'href="/advantage/v3"' in evidence
    assert 'href="/service?id=range-doctor"' in evidence
    assert index.index('id="explore"') < index.index('id="evidence"')


def test_the_home_server_renders_the_four_bound_services_from_the_registry(client):
    """The case-file register must stay aligned with the committed service bindings."""
    from docket.marketplace.registry import all_records

    index = client.get("/", headers={"accept": "text/html"}).text
    bound = [
        record
        for record in all_records()
        if record.agent_id and record.service_id != "solvent-signal"
    ]
    assert len(bound) == 4
    display_names = {
        "range-doctor": "Range Doctor",
        "grid-operator": "Grid Operator",
        "yield-router": "Yield Router",
        "health-guard": "Health Guard",
    }
    for record in bound:
        token_id = record.agent_id.rsplit(":", 1)[1]
        assert f'data-service-id="{record.service_id}"' in index
        assert display_names[record.service_id] in index
        assert token_id in index
        assert f'href="/service?id={record.service_id}"' in index


def test_the_case_file_does_not_invent_an_empty_category_claim(client):
    """The counts are still published; they are read off the served page, not the shell,
    because the shell carries placeholders and the server fills them from the records."""
    index = _read("index.html")
    served = _plain(client.get("/", headers={"accept": "text/html"}).text)
    assert EMPTY_CATEGORY not in index
    assert "4 ERC-8004 identities" in served
    assert "6 services" in served


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


def test_the_home_keeps_the_full_decision_impact_bound_on_one_finding(client):
    index = _read("index.html")
    finding = re.search(r'<aside class="hero-finding".*?</aside>', index, re.S).group(0)
    for phrase in (
        "$126.78",
        "$10k notional",
        "n=22",
        "one frozen daily snapshot",
        "post-hoc, not realized return or forecast",
        "8.30 days",
        "0/231",
        "0.00%",
    ):
        assert phrase in finding


def test_the_home_names_the_json_behind_it_when_scripting_is_off(client):
    index = _read("index.html")
    noscript = re.search(r"<noscript>(.*?)</noscript>", index, re.S).group(1)
    for path in ("/services", "/advantage/v3.json"):
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
    assert 'field.type === "array"' in app_js
    assert "data-array-control" in app_js


def test_the_service_form_keeps_integer_arrays_and_large_integers_exact(tmp_path):
    """A grid order must carry the exact indexes and atomic-unit integers the reader typed."""
    module = tmp_path / "app.mjs"
    module.write_text(_read("app.js"), encoding="utf-8")
    script = tmp_path / "form-contract.mjs"
    script.write_text(
        """
globalThis.document = {
  body: { dataset: {} },
  querySelector: () => null,
  querySelectorAll: () => [],
};
globalThis.window = {};
const { encodeJSON, inputControl, readForm } = await import("./app.mjs");

const arrayMarkup = inputControl("filled", { type: "array", required: false });
if (!arrayMarkup.includes("data-array-control") || !arrayMarkup.includes('type="number"')) {
  throw new Error("filled is not rendered as an integer-array control");
}

const scalar = { value: "9007199254740993123456789" };
const items = [{ value: "2" }, { value: "9007199254740993" }];
const form = {
  elements: { namedItem: (name) => name === "lower" ? scalar : null },
  querySelector: (selector) => selector.includes("filled")
    ? { querySelectorAll: () => items }
    : null,
};
const record = {
  input_schema: {
    lower: { type: "integer", required: true },
    filled: { type: "array", items: { type: "integer" }, required: false },
  },
};
const body = readForm(record, form);
const encoded = encodeJSON(body);
if (encoded !== '{"lower":9007199254740993123456789,"filled":[2,9007199254740993]}') {
  throw new Error(`integer precision or array shape changed: ${encoded}`);
}
""",
        encoding="utf-8",
    )
    completed = subprocess.run(
        ["node", str(script)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr


def test_the_worked_example_replaces_edited_regular_and_advanced_fields(tmp_path):
    """The example action submits schema defaults, never values left in the form."""
    module = tmp_path / "app.mjs"
    module.write_text(_read("app.js"), encoding="utf-8")
    script = tmp_path / "worked-example.mjs"
    script.write_text(
        """
globalThis.document = {
  body: { dataset: {} },
  querySelector: () => null,
  querySelectorAll: () => [],
};
globalThis.window = {};
const { encodeJSON, submissionBody } = await import("./app.mjs");

const controls = {
  wallet: { value: "edited-wallet" },
  declared_position_value_usd: { value: "999.99" },
  observation_block: { value: "117443373" },
  decision_horizon_days: { value: "365" },
};
const arrayItems = {
  innerHTML: "",
  querySelectorAll: () => [{ value: "7" }, { value: "8" }],
};
const arrayControl = {
  dataset: { nextIndex: "9" },
  querySelector: (selector) => selector === "[data-array-items]" ? arrayItems : null,
  querySelectorAll: (selector) => selector === "input" ? arrayItems.querySelectorAll() : [],
};
const form = {
  elements: { namedItem: (name) => controls[name] || null },
  querySelector: (selector) => selector.includes("filled") ? arrayControl : null,
};
const record = {
  input_schema: {
    wallet: { type: "string", required: true, default: "controlled-wallet" },
    declared_position_value_usd: { type: "number", required: false, default: 50.55 },
    observation_block: { type: "integer", required: false, advanced: true },
    decision_horizon_days: { type: "integer", required: false, default: 30, advanced: true },
    filled: {
      type: "array",
      items: { type: "integer" },
      required: false,
      default: [2, "9007199254740993"],
      advanced: true,
    },
  },
};

const runButton = { matches: () => false };
const edited = encodeJSON(submissionBody(record, form, runButton));
if (edited !== '{"wallet":"edited-wallet","declared_position_value_usd":999.99,"observation_block":117443373,"decision_horizon_days":365,"filled":[7,8]}') {
  throw new Error(`ordinary submission stopped reading the form: ${edited}`);
}

const exampleButton = { matches: (selector) => selector === "[data-example]" };
const example = encodeJSON(submissionBody(record, form, exampleButton));
if (example !== '{"wallet":"controlled-wallet","declared_position_value_usd":50.55,"decision_horizon_days":30,"filled":[2,9007199254740993]}') {
  throw new Error(`worked example used edited fields: ${example}`);
}
if (controls.wallet.value !== "controlled-wallet" ||
    controls.declared_position_value_usd.value !== "50.55" ||
    controls.observation_block.value !== "" ||
    controls.decision_horizon_days.value !== "30") {
  throw new Error("worked example did not reset every scalar control");
}
if (!arrayItems.innerHTML.includes('value="2"') ||
    !arrayItems.innerHTML.includes('value="9007199254740993"') ||
    arrayControl.dataset.nextIndex !== "2") {
  throw new Error("worked example did not reset the advanced array control");
}
""",
        encoding="utf-8",
    )
    completed = subprocess.run(
        ["node", str(script)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert "submissionBody(record, form, event.submitter)" in _read("app.js")


def test_the_agent_page_exposes_dockets_bound_service_with_the_same_hire_gating(client):
    app_js = _read("app.js")
    assert "detail.associated_services" in app_js
    assert "serviceCard(service)" in app_js
    assert "card.paid_stock" in app_js


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
    """The case-file home gets section anchors; the working pages retain task navigation."""
    for name in PAGES:
        text = _read(name)
        nav = re.search(r'<nav class="site-nav"[^>]*>(.*?)</nav>', text, re.S)
        assert nav, f"{name} has no primary navigation"
        expected = [
            "/",
            "/search",
            "/my-agents",
            "/providers",
            "/advantage",
            "/llms.txt",
        ]
        assert re.findall(r'href="([^"]+)"', nav.group(1)) == expected, (
            f"{name} has competing or out-of-order primary destinations"
        )


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
    for name in ASSET_PAGES:
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
    for name in ASSET_PAGES:
        text = _read(name)
        tokens.update(re.findall(r'/static/(?:style\.css|app\.js)\?v=([^"]+)', text))
    assert tokens == {"13"}, f"the site asks for unexpected asset versions: {tokens}"


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
    index = _read("index.html")
    if without_a_run:
        assert (
            "Every service here is one Docket runs itself and can show a recorded run"
            not in index
        ), (
            f"the homepage claims a recorded run for every service, but {without_a_run} have none"
        )
    rows = re.findall(r'<article class="service-ledger-row".*?</article>', index, re.S)
    assert len(rows) == 4
    assert all("Evidence state" in row for row in rows)
    assert all("paid_stock: false" in row for row in rows)


def test_the_v1_report_points_at_v2_and_says_which_one_answers_the_sponsor(client):
    """v2 was reachable only from itself: the served v1 page carried no "v2" string at all,
    and the homepage linked the JSON endpoint rather than the page. The report a reader is
    sent to must also tell them what the other one is, or the pair reads as one superseding
    the other — which is the opposite of what these two are.
    """
    v1 = _read("advantage.html")
    assert 'href="/advantage/v2"' in v1, "the v1 report does not link the v2 report"
    assert "agent-versus-computed-null armour with no manual arm" in v1, (
        "v1 links v2 without saying that v1 is the one with the manual arm"
    )
    # And it has to survive being served, not merely sit in the file.
    served = client.get("/advantage").text
    assert "/advantage/v2" in served


def test_each_report_body_links_the_other_two_and_keeps_all_three_additive(client):
    roles = (
        "original paired eligibility artifact at n=1",
        "agent-versus-computed-null armour with no manual arm",
        "pre-registered paired evaluation scored by two prompt-blinded model seats run by one operator",
    )
    pages = {
        "/advantage": _read("advantage.html"),
        "/advantage/v2": _read("advantage-v2.html"),
        "/advantage/v3": _read("advantage-v3.html"),
    }

    for path, body in pages.items():
        for sibling in pages:
            if sibling != path:
                assert f'href="{sibling}"' in body, (path, sibling)
        assert "additive" in body.lower(), path
        assert "none supersedes another" in body.lower(), path
        for role in roles:
            assert role in body, (path, role)
        assert client.get(path, headers={"accept": "text/html"}).status_code == 200


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

    The live evidence wallet returns no positions — 25 held, all 25 closed — and a reader
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
    """A service without a presenter must degrade to the old behaviour, not an empty region."""
    js = re.sub(r"\s+", " ", (WEB_DIR / "app.js").read_text(encoding="utf-8"))
    fallback = js.split("if (!presenter)", 1)[1].split("return presenter", 1)[0]

    assert '<h3 id="result-heading">What came back</h3>' in fallback
    assert "<pre>${escapeHTML(JSON.stringify(result, null, 2))}</pre>" in fallback


def test_warden_results_are_presented_as_a_decision_not_a_payload():
    """The second presenter, and the second of Warden's four admission limbs.

    A security verdict dumped as JSON is the case where raw output is worst: the reader most
    needs to know what was matched and where, and is least able to work it out from a nested
    structure.
    """
    js = (WEB_DIR / "app.js").read_text(encoding="utf-8")
    assert '"warden-scan": presentWardenScan' in js
    assert "function presentWardenScan(" in js
    flat = re.sub(r"\s+", " ", js)
    # A clean scan is the weaker of the two answers, and must say so.
    assert "a miss and an absence look identical" in flat
    # The sanitized text is labelled as the scanner's output, never as a safe string.
    assert "not a statement that the remaining text is safe" in flat


def test_a_clean_warden_verdict_does_not_read_as_a_guarantee():
    js = re.sub(r"\s+", " ", (WEB_DIR / "app.js").read_text(encoding="utf-8"))
    assert "nothing was detected in this payload" in js
    # An empty detection list is explained rather than left to imply safety.
    assert "does not mean the payload is safe" in js


def test_every_service_a_judge_can_run_presents_its_result():
    """Half the catalogue was still handing back raw JSON.

    A presenter is one of the four admission limbs, but the reason it matters here is
    simpler: BNB's functionality criterion is a stranger activating a service and
    understanding what came back, and a nested payload fails that whether or not anything is
    for sale.
    """
    js = (WEB_DIR / "app.js").read_text(encoding="utf-8")
    for service in (
        "range-doctor",
        "warden-scan",
        "yield-router",
        "grid-operator",
        "health-guard",
    ):
        assert f'"{service}": present' in js, f"{service} still falls back to raw JSON"


def test_the_grid_preview_cannot_be_mistaken_for_a_working_grid():
    """A table of prices reads like an order book. A reader who skims could believe something
    is placing them, and nothing is — the object that produced it holds no signer."""
    flat = re.sub(r"\s+", " ", (WEB_DIR / "app.js").read_text(encoding="utf-8"))
    assert "A plan, and only a plan." in flat
    assert "Nothing was signed, submitted or held." in flat
    assert "requires a session the wallet's owner grants on chain" in flat


def test_an_empty_venus_account_is_not_reported_as_a_healthy_one():
    """The common case for any wallet a judge tries. A zero shortfall on an account holding
    nothing is not a health report, and the difference is an answer versus a reassurance."""
    flat = re.sub(r"\s+", " ", (WEB_DIR / "app.js").read_text(encoding="utf-8"))
    assert "no Venus markets" in flat
    assert "is not a statement that the account is healthy" in flat
    assert "nothing borrowed to be liquidated" in flat


def test_the_yield_decision_leads_and_carries_the_pool_it_was_measured_against():
    """MOVE means nothing without the baseline it beat, and the baseline was not read from a
    wallet — so the page says where it came from rather than letting a reader assume."""
    flat = re.sub(r"\s+", " ", (WEB_DIR / "app.js").read_text(encoding="utf-8"))
    assert "Compared against" in flat
    assert "was not read from any wallet" in flat
    assert "annualise one 24-hour observation" in flat


def test_the_experiment_register_keeps_every_missing_result_visible(client):
    """The register is checked against the committed artifacts rather than a literal.

    The homepage said "Six registered families" while the report had reconstructed seven,
    so the page and the README disagreed about the same quantity. The row count, the
    heading count and every state tally are now read from `report()`, which is the only
    thing that can go stale without a test noticing.
    """
    from docket.advantage.v3.report import report

    summary = report()["summary"]
    served = client.get("/", headers={"accept": "text/html"}).text
    register = re.search(
        r'<section[^>]+id="experiments".*?</section>', served, re.S
    ).group(0)
    assert f"{summary['n_families']} registered families. No scored result." in _plain(
        register
    )
    assert register.count('class="experiment-row"') == summary["n_families"]
    assert register.count("Observed 29 Aug 2026") == summary["n_families"]
    for state, count in summary["states"].items():
        assert register.count(state) == count, state
    assert "Absent" in register

    styles = _read("style.css")
    for class_name in ("experiment-row", "experiment-facts", "experiment-state"):
        assert f".{class_name}" in styles, class_name


def test_yield_service_copy_names_both_current_registered_families():
    home = _read("index.html")
    row = re.search(
        r'<article class="service-ledger-row" data-service-id="yield-router">.*?</article>',
        home,
        re.S,
    ).group(0)

    assert "v3-02" in row
    assert "abandoned_after_failed_primary" in row
    assert "v3-06" in row
    assert "registered_waiting_for_inputs" in row
    assert "Registered family locked_not_run" not in row


def test_v3_vocabulary_names_the_abandoned_predecessor_state():
    v3 = _read("advantage-v3.html")

    assert "Read the nine definitions" in v3
    assert "abandoned_after_failed_primary" in v3
    assert "failed primary" in v3


def test_agent_pages_do_not_probe_a_missing_worked_example_record():
    js = _read("app.js")

    assert "fetchJSON(`/agents/${WORKED_EXAMPLE_ID}`)" not in js
    assert 'id === WORKED_EXAMPLE_ID ? workedExample(detail) : ""' in js


def test_service_forms_put_the_worked_example_first_and_reproducibility_behind_disclosure():
    js = _read("app.js")
    styles = _read("style.css")

    assert "field.example_note" in js
    assert "field.advanced" in js
    assert '<details class="advanced">' in js
    assert "Advanced — reproducibility" in js
    assert 'type="submit" class="btn" data-example' in js
    assert "Try the worked example" in js
    assert "querySelectorAll('button[type=\"submit\"]')" in js
    for class_name in ("advanced", "advanced-fields", "example-note"):
        assert f".{class_name}" in styles


def test_free_service_vocabulary_keeps_admission_below_the_action():
    js = _read("app.js")

    assert '"Run a free preview"' in js
    assert '"Run it free"' in js
    assert "Why this isn't for sale yet" in js
    assert "Open ${escapeHTML(card.stock_status)}" not in js
    assert "Run the ${escapeHTML(record.stock_status)}" not in js


def test_empty_metric_cards_state_that_no_run_has_been_recorded():
    js = _read("app.js")

    assert "if (!metrics.length)" in js
    assert "No run recorded yet." in js


def test_cards_show_the_closed_evidence_modality_field():
    js = _read("app.js")

    assert "card.evidence_modality" in js
    assert "record.evidence_modality" in js
    assert "Evidence modality" in js


def test_service_register_distinguishes_registration_stock_and_evidence():
    home = _read("index.html")
    rows = re.findall(r'<article class="service-ledger-row".*?</article>', home, re.S)

    assert len(rows) == 4
    for row in rows:
        assert "ERC-8004" in row
        assert "Evidence state" in row
        assert "paid_stock: false" in row
        assert "View on chain" in row


def test_homepage_is_the_public_case_file_and_keeps_external_context_in_research(
    client,
):
    index = _read("index.html")
    research = _read("research.html")
    styles = _read("style.css")
    served = _plain(client.get("/", headers={"accept": "text/html"}).text)

    assert "$126.78" in index
    assert "$10k notional" in index
    assert "8.30 days" in index
    assert "n=22" in index
    assert "0/231" in index
    # The counters are derived, so they are asserted on the served page. The phrases the
    # old rail used are banned outright: they contradicted the approved canary.
    assert "6 services" in served
    assert "0 Public paid hires" in served
    assert "0 Services open for paid hiring" in served
    assert "settlements ever run" not in index
    assert "No settlement has occurred" not in index
    assert "arXiv:2606.26028" not in index
    assert "arXiv:2606.12128" not in index
    assert "arXiv:2606.26028" in research
    assert "arXiv:2606.12128" in research
    for phrase in (
        "4% of registrations exposed a live service endpoint",
        "59.2% of reviewers showed coordinated Sybil behaviour",
        "77.9% of agents with feedback kept no valid feedback",
        "preprint",
    ):
        assert phrase in " ".join(research.split())
    for class_name in ("case-hero", "hero-finding", "truth-rail"):
        assert f".{class_name}" in styles


def test_service_opening_leads_with_its_recorded_metric(client):
    response = client.get("/service?id=range-doctor", headers={"accept": "text/html"})

    assert response.status_code == 200
    opening = response.text.split('data-region="service"', 1)[1].split("</div>", 1)[0]
    assert "<h1>Range Doctor</h1>" in opening
    assert "14 of 14 position NFTs the wallet held" in opening
    assert "one recorded run against one wallet" in opening
    assert "What arrives" in response.text
    assert "What has been observed of it" in response.text
    assert "What it cannot do" in response.text
    assert "wallet" in response.text
    assert "/advantage" in response.text


def test_home_metadata_does_not_promise_a_run_behind_every_service():
    index = _read("index.html")
    description = re.search(
        r'<meta\s+name="description"\s+content="([^"]+)"', index, re.S
    )

    assert description
    assert "recorded run behind each one" not in description.group(1)
    assert "$126.78" in description.group(1)
