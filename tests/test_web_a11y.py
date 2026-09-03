"""Accessibility and small-device checks, asserted against markup rather than a screenshot.

None of this needs a browser, and that is the point: the failures below are the ones that ship
silently because the person who introduced them was looking at a wide window with a mouse. An
image with no alt text, a control with no name, a page with two first-level headings or none,
a missing `lang`, a positive `tabindex` that reorders the keyboard path, a missing viewport
meta, or a fixed width no narrow screen can hold.

Both the shells and the served pages are checked. The shells alone would miss everything the
server writes into them — `stats`, `service`, `pancake` and `status` all render their first
heading — and the served pages alone would miss a shell that is never requested here.
"""

import re
from html.parser import HTMLParser
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from docket.api import create_app
from docket.api import status as status_module
from docket.store import Store

WEB = Path(__file__).resolve().parents[1] / "docket" / "api" / "web"
SHELLS = tuple(sorted(WEB.glob("*.html")))
PAGES = (
    "/",
    "/pancake",
    "/research",
    "/agent",
    "/service?id=range-doctor",
    "/advantage",
    "/advantage/v2",
    "/advantage/v3",
    "/stats",
    "/status",
)
# The narrowest viewport worth designing for. A `width` in pixels above it cannot shrink, so
# the page scrolls sideways; a `min-width` above it is legitimate inside a container that
# scrolls on its own, which is why the two are judged separately below.
MAX_FIXED_WIDTH_PX = 320
CONTROL_TAGS = frozenset({"input", "select", "textarea"})
# Control types that carry their own name: a button's name is its value or its text, and a
# hidden field is never reached by anyone.
SELF_NAMING_TYPES = frozenset({"button", "hidden", "image", "reset", "submit"})
NAMING_ATTRIBUTES = ("aria-label", "aria-labelledby", "title")
FIXED_WIDTH = re.compile(r"(?<![-\w])width:\s*([0-9.]+)px")
MIN_WIDTH = re.compile(r"min-width:\s*([0-9.]+)px")


def _offline_rpc() -> dict:
    """The status page makes a chain read when it is requested. This suite is about markup,
    so the reading is supplied rather than fetched."""
    return {
        "endpoint_host": "bsc-dataseed.example",
        "ok": True,
        "block_number": 1,
        "latency_ms": 1,
    }


class _Markup(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.images: list[dict] = []
        self.controls: list[tuple[dict, bool]] = []
        self.label_targets: set[str] = set()
        self.label_depth = 0
        self.h1_count = 0
        self.html_lang: str | None = None
        self.has_viewport = False
        self.navs: list[dict] = []
        self.tabindexes: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        attributes = {name.lower(): (value or "") for name, value in attrs}
        if tag == "html":
            self.html_lang = attributes.get("lang")
        elif tag == "meta" and attributes.get("name") == "viewport":
            self.has_viewport = True
        elif tag == "h1":
            self.h1_count += 1
        elif tag == "img":
            self.images.append(attributes)
        elif tag == "nav":
            self.navs.append(attributes)
        elif tag == "label":
            self.label_depth += 1
            if attributes.get("for"):
                self.label_targets.add(attributes["for"])
        if tag in CONTROL_TAGS:
            self.controls.append((attributes, self.label_depth > 0))
        if "tabindex" in attributes:
            self.tabindexes.append(attributes["tabindex"])

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "label":
            self.label_depth = max(self.label_depth - 1, 0)

    def unnamed_controls(self) -> list[dict]:
        return [
            attributes
            for attributes, wrapped in self.controls
            if attributes.get("type", "text").lower() not in SELF_NAMING_TYPES
            and not wrapped
            and not any(attributes.get(name) for name in NAMING_ATTRIBUTES)
            and attributes.get("id", "") not in self.label_targets
        ]


def _parse(document: str) -> _Markup:
    markup = _Markup()
    markup.feed(document)
    markup.close()
    return markup


@pytest.fixture(scope="module")
def served(tmp_path_factory) -> dict[str, str]:
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(status_module, "bounded_rpc_probe", _offline_rpc)
        database = tmp_path_factory.mktemp("a11y") / "a11y.sqlite3"
        store = Store(database)
        snapshot = store.begin_snapshot(chain_id=56, expected=0)
        store.finish_snapshot(snapshot, sampled=0, expected=0)
        client = TestClient(create_app(database, snapshot_id=snapshot))
        pages = {}
        for path in PAGES:
            response = client.get(path, headers={"accept": "text/html"})
            assert response.status_code == 200, path
            assert response.headers["content-type"].startswith("text/html"), path
            pages[path] = response.text
    return pages


def test_every_shell_declares_a_language_and_a_viewport():
    for shell in SHELLS:
        markup = _parse(shell.read_text(encoding="utf-8"))

        assert markup.html_lang, f"{shell.name} sets no <html lang>"
        assert markup.has_viewport, f"{shell.name} carries no viewport meta"


def test_every_served_page_has_exactly_one_first_level_heading(served):
    for path, document in served.items():
        markup = _parse(document)

        assert markup.h1_count == 1, f"{path} has {markup.h1_count} <h1> elements"


def test_every_image_carries_alt_text(served):
    for name, document in _documents(served):
        markup = _parse(document)
        missing = [image for image in markup.images if "alt" not in image]

        assert missing == [], f"{name} serves an <img> without alt: {missing[:2]}"


def test_every_form_control_carries_a_name(served):
    for name, document in _documents(served):
        unnamed = _parse(document).unnamed_controls()

        assert unnamed == [], f"{name} serves an unlabelled control: {unnamed[:2]}"


def test_the_primary_navigation_is_named_on_every_page(served):
    for name, document in _documents(served):
        navs = _parse(document).navs

        assert navs, f"{name} carries no <nav>"
        for nav in navs:
            assert nav.get("aria-label"), f"{name} has a <nav> with no aria-label"
        primary = [nav for nav in navs if "site-nav" in nav.get("class", "").split()]
        assert primary, f"{name} carries no primary navigation"
        for nav in primary:
            assert nav["aria-label"] == "Primary", name


def test_no_page_takes_the_keyboard_path_away_from_the_document(served):
    for name, document in _documents(served):
        positive = [value for value in _parse(document).tabindexes if int(value) > 0]

        assert positive == [], f"{name} sets a positive tabindex: {positive[:3]}"


def test_the_stylesheet_holds_no_width_a_narrow_screen_cannot_show():
    css = (WEB / "style.css").read_text(encoding="utf-8")
    fixed = [value for value in FIXED_WIDTH.findall(css) if float(value) > MAX_FIXED_WIDTH_PX]

    assert fixed == [], f"style.css fixes a width wider than a phone: {fixed}"
    # A `min-width` above the same threshold is the deliberate opposite: the wide tables are
    # allowed to overflow because the element around them scrolls instead of the page.
    if [value for value in MIN_WIDTH.findall(css) if float(value) > MAX_FIXED_WIDTH_PX]:
        assert ".table-wrap {\n  overflow-x: auto;" in css


def _documents(served: dict[str, str]):
    for shell in SHELLS:
        yield shell.name, shell.read_text(encoding="utf-8")
    yield from served.items()
