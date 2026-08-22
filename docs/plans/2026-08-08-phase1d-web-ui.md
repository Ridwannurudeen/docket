# Docket Phase 1d — Web UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A human front door over the same evidence the API serves, good enough that someone with zero prior knowledge can land, find an agent, understand what is actually known about it, and reach the point of hiring — without instructions.

**Architecture:** Dependency-free static HTML/CSS/JS served by the existing FastAPI app, fetching the JSON API already built in Phase 1c. No build step, no `node_modules`, no external requests at all — matching the house pattern in `warden-roadmap/site/`. The root path content-negotiates: browsers get HTML, everything else keeps the JSON service index.

**Tech Stack:** HTML5, CSS custom properties, vanilla ES modules. No framework, no CDN, no web fonts.

## Global Constraints

- **Zero external requests.** No CDN, no Google Fonts, no analytics, no icon package. Fonts are a system stack; icons are inline SVG. This matches warden's self-only CSP and removes the whole supply-chain surface.
- **No build step.** Files are served as authored. A judge cloning the repo can open the site immediately.
- **The UI may not state anything the API does not.** Every number rendered comes from `/stats` or `/agents` at runtime; nothing is hardcoded in markup. If the API says a snapshot is partial, the page says partial.
- **No verdict language in the interface either.** The banned vocabulary from the API contract (`safe`, `trusted`, `verified`, `recommended`, `score`, `rank`) may not appear as a UI label or badge. "Responded 200, 3 hours ago" is allowed; "Verified agent" is not. A test greps the built HTML/JS for the banned words.
- Dark mode only, per the generated design system: `--bg #0F172A`, `--fg #F8FAFC`, `--muted #272F42`, `--border #475569`, `--accent #22C55E`, `--danger #EF4444`. Body text ≥ 4.5:1, large text ≥ 3:1.
- Accessibility is not optional: visible focus rings, keyboard-reachable everything, `aria-label` on icon-only controls, tabular numerals for data columns, `prefers-reduced-motion` respected, no meaning conveyed by colour alone (status always carries text, not just a dot).
- Responsive at 375 / 768 / 1024 / 1440. No horizontal scroll on mobile; wide tables scroll inside their own container.
- No Claude/Anthropic attribution; no Co-Authored-By. Stage by explicit filename. Do not push.
- Repo `.`, run with `./.venv/Scripts/python`.

## File Structure

```
docket/api/web/index.html      # landing
docket/api/web/browse.html     # agent list
docket/api/web/agent.html      # agent detail (reads ?id= from the query string)
docket/api/web/style.css       # design tokens + all styles
docket/api/web/app.js          # shared fetch helpers, rendering, formatting
tests/test_web.py              # serving, content negotiation, and the banned-word grep
```

---

### Task 1: Shell, tokens, and the landing page

**Files:**
- Create: `docket/api/web/{index.html,style.css,app.js}`, `tests/test_web.py`
- Modify: `docket/api/routes.py` (static mount + root content negotiation), `pyproject.toml` (package-data for `web/*`)

**Interfaces:**
- Produces: `GET /` returning HTML when `Accept` contains `text/html`, JSON otherwise; `GET /static/*` serving the assets. `app.js` exports `fetchJSON`, `fmtInt`, `fmtPct`, `relativeTime`, `outcomeLabel`.

**The landing page must answer, in this order:** what Docket is (one sentence), what it currently knows (the live coverage numbers), what those numbers mean, and where to go next. The generated design system calls this the "Real-Time / Operations Landing" pattern: hero with live status, then key metrics, then how it works, then the call to action.

- [ ] **Step 1: Add package-data for the web assets** in `pyproject.toml` — extend the existing `[tool.setuptools.package-data]` entry so `web/*` ships alongside `static/*`. Verify with a clean `git archive` export, not an in-tree check: a stale `docket.egg-info/SOURCES.txt` masks omissions locally.

- [ ] **Step 2: Write the failing test `tests/test_web.py`**

```python
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
    store.upsert_agents([{
        "agent_id": "56:0xreg:1", "token_id": "1", "chain_id": 56, "name": "SOLVENT",
        "supported_protocols": ["A2A"], "total_feedbacks": 3,
    }], sid)
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
    """The interface may not claim what the data cannot support."""
    for f in WEB_DIR.glob("*"):
        text = f.read_text(encoding="utf-8").lower()
        for word in BANNED:
            assert word not in text, f"{f.name} contains verdict language: {word!r}"


def test_no_emoji_used_as_iconography():
    emoji = re.compile("[\U0001F300-\U0001FAFF\u2600-\u27BF]")
    for f in WEB_DIR.glob("*.html"):
        found = emoji.findall(f.read_text(encoding="utf-8"))
        assert not found, f"{f.name} uses emoji as icons: {found[:3]}"


def test_pages_declare_viewport_and_language():
    for name in ("index.html", "browse.html", "agent.html"):
        text = (WEB_DIR / name).read_text(encoding="utf-8")
        assert 'lang="en"' in text
        assert "width=device-width" in text
```

- [ ] **Step 3: Write `docket/api/web/style.css`** — design tokens first (the palette above, an 8px spacing scale, a type scale of 12/14/16/18/24/32, radius and border tokens), then layout, then components. Requirements that are graded, not stylistic: visible `:focus-visible` outline of at least 2px on every interactive element; `font-variant-numeric: tabular-nums` on every numeric cell so columns do not jitter; a `@media (prefers-reduced-motion: reduce)` block that disables transitions; `overflow-x: auto` on table wrappers so wide data never scrolls the page body. System font stack: `-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif`, with `ui-monospace, "Cascadia Code", Consolas, monospace` for addresses and IDs.

- [ ] **Step 4: Write `docket/api/web/app.js`** — an ES module exporting: `fetchJSON(path)` (throws with the API's structured `error.code` on failure); `fmtInt` (locale thousands separators); `fmtPct`; `relativeTime(iso)` ("3 hours ago"); `outcomeLabel(outcome)` mapping the closed vocabulary to human text plus a CSS class — `responded` → "Answered", `timeout` → "Timed out", `refused` → "Refused connection", `blocked` → "Not probed (policy)", `unresolved` → "DNS failed", `error` → "Probe error". Every one of those labels describes what happened, never what it implies about the agent. Include a `renderError(container, err)` that shows the error code and a retry affordance rather than a blank page.

- [ ] **Step 5: Write `docket/api/web/index.html`** — hero (one-sentence description, live snapshot status line), a metrics row driven by `/stats` (registered / with feedback / declaring callable / endpoints answered, each with its denominator visible), a short "what these numbers mean" section explaining coverage and the outcome vocabulary in plain language, and a primary CTA to Browse. Every metric renders a skeleton state before data arrives and an explicit error state if `/stats` fails — never a silent zero, which would read as a real measurement.

- [ ] **Step 6: Wire serving in `routes.py`** — mount `StaticFiles` at `/static` pointing at the `web` directory; make `GET /` inspect the `Accept` header and return `FileResponse(index.html)` when it contains `text/html`, else the existing JSON body. Keep the JSON path byte-identical so Phase 1c's tests stay green.

- [ ] **Step 7: Run** `./.venv/Scripts/python -m pytest tests/test_web.py -q` → 8 passed. Full suite → 103 passed.

- [ ] **Step 8: Commit**

```bash
git add docket/api/web/index.html docket/api/web/style.css docket/api/web/app.js docket/api/routes.py pyproject.toml tests/test_web.py
git commit -m "feat(web): dependency-free landing page over the live evidence"
```

---

### Task 2: Browse and agent detail

**Files:**
- Create: `docket/api/web/browse.html`, `docket/api/web/agent.html`
- Modify: `docket/api/routes.py` (serve both), `tests/test_web.py` (two tests)

**The find→compare→hire path** is 20% of TermiX's rubric and the main track's Functionality criterion. Browse must let someone filter to agents whose endpoints actually answered in one click, and the detail page must show the evidence behind that claim rather than asserting it.

- [ ] **Step 1: Write `browse.html`** — a filter bar (checkboxes for *has feedback*, *declares a callable endpoint*, *endpoint answered*; a publisher filter; all reflected in the URL query string so a filtered view is shareable and the back button works), and a results table: agent name (linking to detail), token id, feedback count, declared protocols, and last observation with its timestamp. Show the active coverage line above the table — the reader must always know which population they are filtering inside. Empty state explains *why* a filter returned nothing and offers to clear it; loading state is a skeleton, not a spinner.

- [ ] **Step 2: Write `agent.html`** — reads `?id=` from the query string, fetches `/agents/{id}`. Sections: identity (name, token id, owner, publisher); what it declares (protocols, x402, description, endpoints); what was observed (a table of every probe with outcome, status code, elapsed ms, and timestamp); and the coverage this evidence came from. A prominent, plain-language honesty note near the observations: an endpoint answering proves the host is reachable, not that the agent does anything useful — and link the AGENTSAI case as the worked example if that agent is in the current snapshot. If an agent has no observations, say exactly that and why (not callable / not yet probed), never render an empty table.

- [ ] **Step 3: Serve both** at `/browse` and `/agent` (HTML), and add tests that both return 200 `text/html` and that `browse.html` reflects filters into the query string (assert the source contains the history/`URLSearchParams` wiring).

- [ ] **Step 4: Run** the suite → 105 passed.

- [ ] **Step 5: Commit**

```bash
git add docket/api/web/browse.html docket/api/web/agent.html docket/api/routes.py tests/test_web.py
git commit -m "feat(web): browse and agent detail with observation evidence"
```

---

### Task 3: Real-data review

- [ ] **Step 1:** Serve the real store and walk the site as a first-time visitor would:

```bash
./.venv/Scripts/python -m uvicorn --factory "docket.api:create_app" --host 127.0.0.1 --port 8099
```

- [ ] **Step 2:** Check with the Browser tool at 1440, 768 and 375 widths: no horizontal scroll, focus rings visible when tabbing, numbers aligned, coverage line present on every page that shows a number. Capture what is actually rendered rather than trusting the markup.

- [ ] **Step 3:** Verify the honest path end to end — filter Browse to "endpoint answered", open one of the agents that genuinely returned 200, and confirm the detail page shows the raw observation (status, elapsed, timestamp) rather than a summary adjective.

- [ ] **Step 4:** Fix whatever the review surfaces, then commit.

---

## Self-review (done at write time)

- Spec coverage: this is the human half of spec §4.2's "two equal front doors"; the agent-facing half shipped in Phase 1c.
- The honesty constraints from the API are re-enforced at the UI layer by tests (banned verdict words, no hardcoded numbers, no external requests) rather than left to reviewer judgement.
- Accessibility items that are usually skipped — focus rings, tabular numerals, reduced motion, colour-plus-text status — are written as requirements with a graded rationale, not as a checklist afterthought.
- Deliberate deviation from the generated design system: it recommends importing Inter from Google Fonts; this plan uses a system font stack instead, because a self-only CSP and zero external requests matter more here than the specific typeface.
