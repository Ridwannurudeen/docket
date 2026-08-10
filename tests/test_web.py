import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from docket.api import create_app
from docket.store import Store

BANNED = ("trusted", "verified agent", "recommended", "trust score", "safety rating", "endorsed")
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
    for path, ctype in (("/static/style.css", "text/css"), ("/static/app.js", "javascript")):
        resp = client.get(path)
        assert resp.status_code == 200, path
        assert ctype in resp.headers["content-type"]


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
            assert not re.search(pattern, text), f"{f.name} contains verdict language: {word!r}"


def test_pages_do_not_present_the_name_key_as_minter_provenance():
    """ "Who minted them" over a table grouped by the first word of a self-chosen name is a
    provenance claim Docket cannot make. The pages say what the key is instead."""
    index = (WEB_DIR / "index.html").read_text(encoding="utf-8").lower()
    assert "who minted them" not in index
    assert "name famil" in index
    browse = (WEB_DIR / "browse.html").read_text(encoding="utf-8").lower()
    assert "name famil" in browse
    app_js = (WEB_DIR / "app.js").read_text(encoding="utf-8").lower()
    assert "was minted by" not in app_js


def test_landing_states_the_sampled_figure_is_a_filtered_slice():
    """ "sampled 506 of 506, complete" is true and reads as a census of BNB Smart Chain. The
    landing has to say which query produced the 506 and how large the registry it came from is."""
    index = (WEB_DIR / "index.html").read_text(encoding="utf-8")
    assert 'data-region="slice"' in index, "the landing has no region for the disclosure"
    app_js = (WEB_DIR / "app.js").read_text(encoding="utf-8")
    assert "paintSlice" in app_js
    # Both halves of the sentence are read from the API, never authored into the page.
    for source in ("stats.registry_total", "populationLabel(cov)"):
        assert source in app_js, source
    lowered = app_js.lower()
    for phrase in ("filtered slice", "not a census"):
        assert phrase in lowered, phrase


def test_a_full_sweep_is_not_told_it_is_a_slice():
    """The census claim is gated on what was swept, not on arithmetic. Deciding it from
    `registry_total > expected` alone would tell a genuine whole-registry sweep that it "is not
    a census" — the same class of mislabel this stage exists to remove, pointed the other way.
    `registry_total` still gates the scale FIGURE, which is a separate question."""
    app_js = (WEB_DIR / "app.js").read_text(encoding="utf-8")
    assert 'cov.population === "all"' in app_js
    assert "was the whole registry" in app_js
    # The heading turns on the same fact, so a census is not filed under "is a slice of".
    assert "What this snapshot covers" in app_js
    assert 'census ? "What this snapshot covers"' in app_js


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


def test_browse_and_agent_pages_are_served(client):
    for path in ("/browse", "/agent"):
        resp = client.get(path, headers={"accept": "text/html"})
        assert resp.status_code == 200, path
        assert resp.headers["content-type"].startswith("text/html"), path
        assert "<title>" in resp.text, path


def test_browse_reflects_its_filters_into_the_query_string():
    """A narrowed view has to be a link someone can send, and the back button has to walk it."""
    browse = (WEB_DIR / "browse.html").read_text(encoding="utf-8")
    for name in ("has_feedback", "declares_callable", "responded", "name_family"):
        assert f'data-filter="{name}"' in browse, name
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
    for name, container in (("browse.html", "results"), ("agent.html", "agent")):
        text = (WEB_DIR / name).read_text(encoding="utf-8")
        assert f'class="wrap-anywhere" data-region="{container}"' in text, name


def test_pages_declare_viewport_and_language():
    for name in ("index.html", "browse.html", "agent.html", "advantage.html"):
        text = (WEB_DIR / name).read_text(encoding="utf-8")
        assert 'lang="en"' in text
        assert "width=device-width" in text
