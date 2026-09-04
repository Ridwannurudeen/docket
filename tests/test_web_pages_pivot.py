"""The four activation surfaces the marketplace pivot adds, and what they may not do.

These pages are shells: everything a reader sees on them is fetched at runtime and written
into the DOM by an ES module. That makes two things worth holding open here. The first is
that the shells are actually served, carry the pivot's site chrome, and name exactly one
entry module each. The second is that the modules escape what they interpolate — every
string these pages render is a service name, an agent name or an error message somebody
else wrote, and the one place a `<script>` could get in is an unescaped template hole.

The payment module is also pinned against `docket/hire/x402.py`. That module signs, in a
browser, the exact EIP-712 structure the server verifies; the two files have no shared
source, so a constant that drifts on one side would produce signatures the other silently
refuses. Re-deriving the ABI selectors from their signatures is the same guard for the
calldata the page builds.
"""

import json
import re
from pathlib import Path

import pytest
from eth_utils import function_signature_to_4byte_selector
from fastapi.testclient import TestClient

from docket.api import create_app
from docket.hire.x402 import (
    B402_RELAYER,
    BSC_CHAIN_ID,
    EIP712_DOMAINS,
    TRANSFER_WITH_AUTHORIZATION_TYPES,
    X402_VERSION,
)

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "docket" / "api" / "web"
JS = WEB / "js"

# route -> (shell file, body key, entry module)
PIVOT_PAGES = {
    "/activate": ("activate.html", "activate", "activate"),
    "/my-agents": ("my-agents.html", "my-agents", "my-agents"),
    "/search": ("search.html", "search", "search"),
    "/providers": ("providers.html", "providers", "providers"),
}

MODULES = (
    "abi.js",
    "activation.js",
    "api.js",
    "jobs.js",
    "payment.js",
    "providers.js",
    "search.js",
    "ui.js",
    "wallet.js",
)


@pytest.fixture
def client(tmp_path):
    return TestClient(create_app(tmp_path / "pivot.sqlite3"))


def _read(name):
    return (JS / name).read_text(encoding="utf-8")


def test_the_four_pivot_pages_are_served_as_html(client):
    for path, (_, key, _entry) in PIVOT_PAGES.items():
        response = client.get(path, headers={"accept": "text/html"})
        assert response.status_code == 200, path
        assert response.headers["content-type"].startswith("text/html"), path
        assert f'data-page="{key}"' in response.text, path
        assert "<title>" in response.text, path


def test_each_pivot_page_loads_exactly_one_entry_module(client):
    """One script tag per page, pointing at a module that exists and does one thing.

    A page that loaded two modules would have two answers to "what runs here", and the
    ordering between them would be the kind of implicit contract that breaks silently."""
    for _path, (shell, _key, entry) in PIVOT_PAGES.items():
        document = (WEB / shell).read_text(encoding="utf-8")
        scripts = re.findall(r"<script[^>]*src=\"([^\"]+)\"", document)
        assert scripts == [f"/static/js/pages/{entry}.js?v=13"], shell
        module = JS / "pages" / f"{entry}.js"
        assert module.is_file(), module
        served = client.get(f"/static/js/pages/{entry}.js")
        assert served.status_code == 200, entry
        assert "init()" in served.text, entry


def test_pivot_pages_carry_the_pivot_site_chrome():
    """The nav contract, the footer links the existing tests pin, and the v13 assets."""
    expected_nav = (
        ("/", "Explore"),
        ("/search", "Find agents"),
        ("/my-agents", "My agents"),
        ("/providers", "Providers"),
        ("/advantage", "Evidence"),
        ("/llms.txt", "API"),
    )
    for shell, _key, _entry in PIVOT_PAGES.values():
        document = (WEB / shell).read_text(encoding="utf-8")
        nav = re.search(r'<nav class="site-nav".*?</nav>', document, re.S).group(0)
        links = tuple(
            re.findall(
                r'<a href="([^"]+)"(?: aria-current="page")?>([^<]+)</a>',
                nav,
            )
        )
        assert links == expected_nav, shell
        footer = re.search(
            r'<footer class="site-footer">.*?</footer>', document, re.S
        ).group(0)
        assert '<a href="/pancake">PancakeSwap</a>' in footer, shell
        assert '<a href="/research">Browse agents</a>' in footer, shell
        assert '<a href="/status">Status</a>' in footer, shell
        assert 'href="/static/style.css?v=13"' in document, shell


def test_pivot_pages_ship_no_inline_style_and_no_second_stylesheet():
    """The CSP names two style hashes and no others; a new inline block would be blocked."""
    for shell, _key, _entry in PIVOT_PAGES.values():
        document = (WEB / shell).read_text(encoding="utf-8")
        assert "<style>" not in document, shell
        assert 'style="' not in document, shell
        assert document.count('rel="stylesheet"') == 1, shell


def test_pivot_pages_state_what_happens_without_scripting():
    """A shell whose content arrives by fetch must say so rather than render as blank."""
    for shell, _key, _entry in PIVOT_PAGES.values():
        document = (WEB / shell).read_text(encoding="utf-8")
        assert "<noscript>" in document, shell


def test_no_pivot_module_writes_markup_without_the_escaper_in_scope():
    """A module that assigns `innerHTML` must have `escapeHTML` available to it.

    This is the cheap half of the guard and it only catches the gross case: a new module
    that starts writing markup without importing the escaper at all. The half that
    actually proves escaping is behavioural, in `tests/e2e/tests/escaping.spec.ts`, which
    pushes markup through every field a publisher controls — service name, agent name,
    error message, receipt field, failed-check detail — and asserts the browser renders it
    as text rather than as an element."""
    for name in MODULES:
        source = _read(name)
        if ".innerHTML" not in source:
            continue
        assert "escapeHTML" in source, name


def test_the_escaping_walk_covers_every_channel_a_publisher_controls():
    """The behavioural test is the guard; this holds its coverage open.

    A channel dropped from that spec is a channel nobody is checking, and the failure mode
    is silent, so the list of what it must exercise lives here rather than only there."""
    spec = (ROOT / "tests" / "e2e" / "tests" / "escaping.spec.ts").read_text(
        encoding="utf-8"
    )
    for channel in (
        "service name",
        "agent name",
        "error message",
        "receipt field",
        "failed check",
    ):
        assert channel in spec, channel


def test_the_payment_module_signs_what_the_server_verifies():
    """The browser's EIP-712 structure is the server's, field for field and in order."""
    source = _read("payment.js")
    fields = re.search(
        r"export const TRANSFER_WITH_AUTHORIZATION = \[(.*?)\];", source, re.S
    ).group(1)
    browser = re.findall(r'name: "([^"]+)", type: "([^"]+)"', fields)
    server = [
        (field["name"], field["type"])
        for field in TRANSFER_WITH_AUTHORIZATION_TYPES["TransferWithAuthorization"]
    ]
    assert browser == server

    domain = re.search(r"export const EIP712_DOMAIN = \[(.*?)\];", source, re.S).group(
        1
    )
    assert re.findall(r'name: "([^"]+)", type: "([^"]+)"', domain) == [
        ("name", "string"),
        ("version", "string"),
        ("chainId", "uint256"),
        ("verifyingContract", "address"),
    ]
    assert f"export const X402_VERSION = {X402_VERSION};" in source


def test_the_wallet_module_targets_the_chain_docket_settles_on():
    source = _read("wallet.js")
    assert f'export const BSC_CHAIN_ID = "0x{BSC_CHAIN_ID:x}";' in source
    assert "https://bsc-dataseed.binance.org" in source
    assert "https://bscscan.com" in source
    # The relayer is the one contract the browser is ever asked to approve, and it is the
    # same address the server names as the EIP-712 verifying contract.
    assert B402_RELAYER == next(iter(EIP712_DOMAINS.values()))["verifyingContract"]


def test_the_abi_selectors_are_the_keccak_prefixes_they_claim_to_be():
    """Four constants that cannot be derived in the browser, re-derived here."""
    source = _read("abi.js")
    signatures = {
        "APPROVE": "approve(address,uint256)",
        "ALLOWANCE": "allowance(address,address)",
        "BALANCE_OF": "balanceOf(address)",
        "TRANSFER": "transfer(address,uint256)",
    }
    for name, signature in signatures.items():
        declared = re.search(rf'export const {name} = "(0x[0-9a-f]{{8}})";', source)
        assert declared, name
        expected = "0x" + function_signature_to_4byte_selector(signature).hex()
        assert declared.group(1) == expected, (name, signature)


def test_the_allowance_helper_never_offers_an_unlimited_approval():
    """Exact-amount approvals only. An infinite allowance would outlive the hire."""
    source = _read("payment.js")
    assert "ensureAllowance" in source
    for unlimited in (
        "ffffffffffffffff",
        "MaxUint",
        "2n ** 256n",
        "constants.MaxUint256",
    ):
        assert unlimited not in source
    assert "encodeApprove(relayer, required)" in source


def test_the_challenge_probe_cannot_decode_as_base64():
    """The probe asks for terms without spending the free tier, which only works while the
    header is unreadable: a decodable one would be judged as a payment instead."""
    import base64
    import binascii

    probe = re.search(r'const CHALLENGE_PROBE = "([^"]+)";', _read("payment.js")).group(
        1
    )
    with pytest.raises(binascii.Error):
        base64.b64decode(probe, validate=True)


def test_the_service_page_offers_activation_without_scripting(client):
    """The Activate control is server-rendered, and absent when no service was named."""
    named = client.get("/service?id=range-doctor")
    assert named.status_code == 200
    assert (
        '<a class="btn btn-primary" href="/activate?service=range-doctor">'
        in named.text
    )
    assert "<!-- service-activate -->" not in named.text

    unnamed = client.get("/service")
    assert unnamed.status_code == 200
    assert "/activate?service=" not in unnamed.text


def test_the_pivot_pages_are_reachable_from_the_static_mount(client):
    """Every module the pages import is served, so no page can 404 half its behaviour."""
    for name in MODULES:
        response = client.get(f"/static/js/{name}")
        assert response.status_code == 200, name
        assert response.headers["content-type"].startswith("text/javascript"), name


def test_the_installed_package_would_carry_the_browser_modules():
    """`web/*` does not match `web/js/*`; a wheel built without these globs ships pages
    whose scripts 404, and the package job smoke-tests JSON routes rather than HTML."""
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    for glob in ('"web/*"', '"web/js/*"', '"web/js/pages/*"'):
        assert glob in pyproject, glob


def test_the_activation_module_names_every_state_the_plan_declares():
    """A stepper that silently omitted a state would hide the one the reader is stuck on."""
    source = _read("ui.js")
    for state in (
        "quoted",
        "awaiting_wallet",
        "authorized",
        "paid_or_reserved",
        "queued",
        "running",
        "needs_approval",
        "completed",
        "failed",
        "refunded",
        "awaiting_session",
        "funded",
        "active",
        "paused",
        "revoking",
        "revoked",
        "expired",
    ):
        assert f'"{state}"' in source, state


def test_the_search_module_names_every_verification_level():
    source = _read("ui.js")
    for level in (
        "registered",
        "endpoint_detected",
        "live",
        "payment_tested",
        "docket_tested",
        "docket_verified",
    ):
        assert f'"{level}"' in source, level
    assert 'HIREABLE_FROM = "docket_tested"' in source


def test_every_mutating_control_signs_the_message_the_server_issues():
    """Pause, cancel and revoke each carry a fresh signature over the activation's own
    nonce, and over the server's own sentence wherever the server serves one.

    `authMessage` prefers `activation.auth_message` and falls back to the documented
    template. That order is what lets the server start binding the request body into the
    message — the shape the activation lane is moving to — without the browser signing
    something the server no longer verifies."""
    jobs = _read("jobs.js")
    assert "wallet.personalSign(" in jobs
    assert "api.authMessage(activation, action)" in jobs
    for control in ("pauseActivation", "cancelActivation", "revokeActivation"):
        assert control in jobs, control

    api = _read("api.js")
    assert "const message = `Docket activation ${activationId} ${action} ${nonce}`;" in api
    assert "return binds ? `${message} ${binds}` : message;" in api
    # The message is composed here and checked before it reaches a wallet. A field on the
    # response is not trusted for it: a response is attacker-reachable the moment anything
    # between the browser and Docket is, and `personal_sign` over a server-supplied string
    # is a signature over whatever that string turned out to say.
    assert "auth_message" not in api
    assert "if (value && /\\s/.test(String(value)))" in api
    assert '"unsafe_message"' in api
    # A create has no counterpart here on purpose: `/api/activations/nonce` issues that
    # message and the browser signs it verbatim, which is stricter than rebuilding it.
    assert "activation create" not in api


def test_the_replay_panel_offers_no_way_to_buy_the_same_work_twice():
    """A replay refusal proves the authorization reached Docket and was spent, so the work
    is bought. A fresh-payment button there is one click from a second purchase, offered to
    a reader who has just been told something went wrong."""
    source = _read("activation.js")
    replay = source[source.index("authorization_replay: {") :]
    replay = replay[: replay.index("},")]
    assert "retry-payment" not in replay
    assert "second payment for it." in replay
    # The one safe recovery is resending the same bytes, and it is bounded by the
    # authorization's own window.
    assert "resend-payment" in source
    assert "pending.validBefore" in source


def test_the_session_policy_allowlists_are_fetched_and_never_invented():
    """The browser cannot know a category's allowlists, and an empty one is not a safe
    default in either direction: it either forbids the work or reads as permission."""
    source = _read("activation.js")
    assert "api.policyDefaults(state.record.service_id)" in source
    assert "What this session may touch" in source
    assert "policy_defaults_missing" in source
    assert "state.policyDefaults = envelope.policy || null" in source
    assert "...defaults" in source
    assert "policyDefaults" in _read("api.js")


def test_the_terms_signed_are_the_terms_the_page_printed():
    source = _read("activation.js")
    assert "assertTermsMatchTheQuote" in source
    assert '"quote_changed"' in source
    # And an approval is read back rather than believed.
    payment = _read("payment.js")
    assert '"allowance_not_applied"' in payment
    assert "challengeIsStale" in payment
    assert "clock_offset_seconds" in payment


def test_the_payment_is_bound_by_its_id_rather_than_by_a_spent_authorization():
    """`/api/activations/{id}/approve` binds against the server's own settled payment row.
    Re-sending the authorization would put a spent header back on the wire and prove
    nothing the server has not already recorded."""
    api = _read("api.js")
    assert "payment_id = null" in api
    assert "payment_header" not in api
    assert "payment_id: answer.payment_id" in _read("activation.js")


def test_the_page_routes_sit_directly_above_the_static_mount():
    """The pivot plan puts every lane's registration in one place so merges stay trivial."""
    routes = (ROOT / "docket" / "api" / "routes.py").read_text(encoding="utf-8")
    mount = routes.index('app.mount("/static"')
    for path in PIVOT_PAGES:
        registration = routes.index(f'@app.get("{path}", include_in_schema=False)')
        assert registration < mount, path
        assert routes.index("def favicon(") < registration, path


def test_no_pivot_module_reaches_a_host_other_than_this_one():
    """Same-origin fetches only. `connect-src 'self'` would block anything else anyway,
    and a page that tried would fail with nothing on screen to explain it."""
    for name in MODULES + tuple(
        f"pages/{entry}.js" for _s, _k, entry in PIVOT_PAGES.values()
    ):
        source = (JS / name).read_text(encoding="utf-8")
        for call in re.findall(r"fetch\(\s*([^,)]+)", source):
            assert "http" not in call, (name, call)


def test_the_receipt_export_offers_both_a_copy_and_a_download():
    source = _read("ui.js")
    assert "data-copy-receipt" in source
    assert "data-download-receipt" in source
    assert "download=" in source
    assert "<pre" in source


def test_the_e2e_suite_pins_the_installed_playwright_version():
    """The fixture and the browser have to agree, and CI installs from this manifest."""
    manifest = json.loads(
        (ROOT / "tests" / "e2e" / "package.json").read_text(encoding="utf-8")
    )
    assert manifest["devDependencies"]["@playwright/test"].startswith("1.62.")
