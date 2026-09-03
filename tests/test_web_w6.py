import asyncio
import base64
import hashlib
import sqlite3
import subprocess
import threading
import time
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from docket.api import create_app
from docket.api import routes
from docket.identity.register import (
    CATEGORY_SERVICE_IDS,
    REGISTRATION_BASE_URL,
    REGISTRATION_DOCUMENT_DIR,
)
from docket.liveness import OUTCOMES
from docket.store import Store


AGENT_ID = "56:0xreg:136384"
AGENT = {
    "agent_id": AGENT_ID,
    "token_id": "136384",
    "chain_id": 56,
    "name": "SOLVENT",
    "description": "glass-box trader",
    "owner_address": "0xabc",
    "supported_protocols": ["A2A"],
    "x402_supported": True,
    "total_feedbacks": 3,
    "total_score": 12.0,
}


def _agent_client(tmp_path, *, outcome="responded", agent=AGENT):
    db = tmp_path / "agents.sqlite3"
    store = Store(db)
    snapshot_id = store.begin_snapshot(chain_id=56, expected=1)
    store.upsert_agents([agent], snapshot_id)
    store.upsert_endpoints(
        [
            {"agent_id": AGENT_ID, "kind": "a2a", "url": "https://a.example/a2a"},
            {"agent_id": AGENT_ID, "kind": "web", "url": "https://a.example/"},
        ],
        snapshot_id,
    )
    store.record_liveness(
        [
            {
                "snapshot_id": snapshot_id,
                "agent_id": AGENT_ID,
                "url": "https://a.example/a2a",
                "observed_at": "2026-08-21T10:00:00+00:00",
                "outcome": outcome,
                "status_code": 200 if outcome == "responded" else None,
                "elapsed_ms": 120,
                "detail": None,
            }
        ]
    )
    store.finish_snapshot(snapshot_id, sampled=1, expected=1)
    return TestClient(create_app(db, snapshot_id=snapshot_id)), store, snapshot_id


@pytest.mark.parametrize("service_id", CATEGORY_SERVICE_IDS)
def test_registration_documents_are_served_byte_for_byte(tmp_path, service_id):
    client = TestClient(create_app(tmp_path / "registrations.sqlite3"))
    source = REGISTRATION_DOCUMENT_DIR / f"{service_id}.registration.json"

    response = client.get(f"/registrations/{service_id}.json")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    assert response.content == source.read_bytes()
    assert response.content.endswith(b"\n")
    assert f"{REGISTRATION_BASE_URL}/{service_id}.json".endswith(response.url.path)


def test_unknown_registration_uses_the_error_contract(tmp_path):
    response = TestClient(create_app(tmp_path / "unknown.sqlite3")).get(
        "/registrations/solvent-signal.json"
    )

    assert response.status_code == 404
    assert response.json() == {
        "error": {
            "code": "registration_not_found",
            "message": (
                "No registration document for 'solvent-signal'. "
                "GET /services lists the four category services."
            ),
        }
    }


def test_live_probe_records_on_demand_without_changing_snapshot_coverage(
    tmp_path, monkeypatch
):
    client, store, snapshot_id = _agent_client(tmp_path)
    calls = []
    monkeypatch.setattr(routes, "_snapshot_age_seconds", lambda _captured: 123)
    before_stats = client.get("/stats").content

    class FakeClient:
        def __init__(self, *, trust_env):
            assert trust_env is False

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

    def fake_probe(http_client, endpoint, *, now):
        assert isinstance(http_client, FakeClient)
        calls.append(endpoint)
        return {
            "snapshot_id": endpoint["snapshot_id"],
            "agent_id": endpoint["agent_id"],
            "url": endpoint["url"],
            "observed_at": now,
            "outcome": "timeout",
            "status_code": None,
            "elapsed_ms": 8000,
            "detail": "ReadTimeout",
        }

    monkeypatch.setattr(routes.httpx, "Client", FakeClient)
    monkeypatch.setattr(routes, "probe_one", fake_probe)

    def unexpected_full_scan(*_args, **_kwargs):
        raise AssertionError("the probe route must use the snapshot agent primary key")

    with monkeypatch.context() as keyed_lookup:
        keyed_lookup.setattr(Store, "iter_agents", unexpected_full_scan)
        response = client.post(f"/agents/{AGENT_ID}/probe", json={})

    assert response.status_code == 200
    assert calls == [
        {
            "snapshot_id": snapshot_id,
            "agent_id": AGENT_ID,
            "kind": "a2a",
            "url": "https://a.example/a2a",
        }
    ]
    body = response.json()
    assert body["agent_id"] == AGENT_ID
    assert body["observation"]["outcome"] == "timeout"
    assert body["observation"]["outcome"] in OUTCOMES
    assert body["probe_method"] == routes.PROBE_METHOD
    assert body["coverage_note"] == (
        f"Re-probed on request at {body['observation']['observed_at']}; "
        "not part of the snapshot's coverage figures."
    )
    assert client.get("/stats").content == before_stats

    sweep_rows = list(store.iter_liveness(snapshot_id))
    assert len(sweep_rows) == 1
    assert sweep_rows[0]["outcome"] == "responded"
    on_demand = store.latest_on_demand_liveness(snapshot_id, AGENT_ID)
    assert on_demand["outcome"] == "timeout"
    with sqlite3.connect(store.path) as conn:
        stored_row = conn.execute("SELECT * FROM liveness_on_demand").fetchone()
        stored_hash = stored_row[-1]
    assert stored_hash == hashlib.sha256(b"testclient").hexdigest()
    assert stored_hash != "testclient"
    assert "testclient" not in repr(stored_row)

    detail = client.get(f"/agents/{AGENT_ID}").json()
    assert detail["observations"][0]["outcome"] == "responded"
    assert detail["latest_on_demand_observation"]["outcome"] == "timeout"
    refused = client.post(f"/agents/{AGENT_ID}/probe", json={})
    assert refused.status_code == 409
    assert refused.json()["error"]["code"] == "probe_not_available"


@pytest.mark.parametrize(
    "outcome", ["timeout", "refused", "blocked", "unresolved", "error"]
)
def test_live_probe_requires_the_last_recorded_probe_to_have_answered(
    tmp_path, monkeypatch, outcome
):
    client, _store, _snapshot_id = _agent_client(tmp_path, outcome=outcome)

    def unexpected_probe(*_args, **_kwargs):
        raise AssertionError("an ineligible endpoint must not be probed")

    monkeypatch.setattr(routes, "probe_one", unexpected_probe)
    response = client.post(f"/agents/{AGENT_ID}/probe", json={})

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "probe_not_available"


def test_live_probe_requires_a_callable_declaration(tmp_path, monkeypatch):
    agent = {**AGENT, "supported_protocols": []}
    client, _store, _snapshot_id = _agent_client(tmp_path, agent=agent)

    def unexpected_probe(*_args, **_kwargs):
        raise AssertionError("a non-callable declaration must not be probed")

    monkeypatch.setattr(routes, "probe_one", unexpected_probe)
    response = client.post(f"/agents/{AGENT_ID}/probe", json={})

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "probe_not_available"


def test_live_probe_shares_the_free_work_allowance(tmp_path, monkeypatch):
    client, _store, _snapshot_id = _agent_client(tmp_path)
    client.app.state.hire_allowances["testclient"] = (
        time.monotonic(),
        routes.FREE_TIER_HIRES,
    )

    def unexpected_probe(*_args, **_kwargs):
        raise AssertionError("a rate-limited request must not be probed")

    monkeypatch.setattr(routes, "probe_one", unexpected_probe)
    response = client.post(f"/agents/{AGENT_ID}/probe", json={})

    assert response.status_code == 429
    assert response.headers["retry-after"]
    assert response.json()["error"]["code"] == "probe_rate_limited"


@pytest.mark.parametrize(
    ("content_type", "body"),
    [
        ("text/plain", "{}"),
        ("application/x-www-form-urlencoded", "field=value"),
    ],
)
def test_live_probe_rejects_non_json_before_work_or_state_mutation(
    tmp_path, monkeypatch, content_type, body
):
    client, store, snapshot_id = _agent_client(tmp_path)
    allowances_before = dict(client.app.state.hire_allowances)

    def unexpected_store(*_args, **_kwargs):
        raise AssertionError("an unsupported body must not open the store")

    def unexpected_probe(*_args, **_kwargs):
        raise AssertionError("an unsupported body must not run a probe")

    monkeypatch.setattr(routes, "Store", unexpected_store)
    monkeypatch.setattr(routes, "probe_one", unexpected_probe)

    response = client.post(
        f"/agents/{AGENT_ID}/probe",
        content=body,
        headers={"Content-Type": content_type},
    )

    assert response.status_code == 415
    assert response.json()["error"]["code"] == "unsupported_media_type"
    assert client.app.state.hire_allowances == allowances_before
    assert store.latest_on_demand_liveness(snapshot_id, AGENT_ID) == {}


def test_live_probe_leaves_the_event_loop_free_for_health(tmp_path, monkeypatch):
    client, _store, _snapshot_id = _agent_client(tmp_path)
    app = client.app
    started = threading.Event()
    release = threading.Event()

    class FakeClient:
        def __init__(self, *, trust_env):
            assert trust_env is False

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

    def slow_probe(_client, endpoint, *, now):
        started.set()
        assert release.wait(2)
        return {
            "snapshot_id": endpoint["snapshot_id"],
            "agent_id": endpoint["agent_id"],
            "url": endpoint["url"],
            "observed_at": now,
            "outcome": "responded",
            "status_code": 204,
            "elapsed_ms": 1,
            "detail": None,
        }

    monkeypatch.setattr(routes.httpx, "Client", FakeClient)
    monkeypatch.setattr(routes, "probe_one", slow_probe)

    async def scenario():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as async_client:
            probing = asyncio.create_task(
                async_client.post(f"/agents/{AGENT_ID}/probe", json={})
            )
            assert await asyncio.to_thread(started.wait, 1)
            before = time.monotonic()
            health = await async_client.get("/health")
            elapsed = time.monotonic() - before
            release.set()
            response = await probing
        assert health.status_code == 200
        assert elapsed < 0.5
        assert response.status_code == 200

    asyncio.run(scenario())


def test_pancake_page_is_content_negotiated_and_machine_discoverable(tmp_path):
    client = TestClient(create_app(tmp_path / "pancake.sqlite3"))

    html = client.get("/pancake", headers={"Accept": "text/html"})
    machine = client.get("/pancake")
    root = client.get("/").json()

    assert html.status_code == 200
    assert html.headers["content-type"].startswith("text/html")
    assert html.headers["vary"] == "Accept"
    assert '<body data-page="pancake">' in html.text
    assert "$126.78" in html.text
    assert "8.30 days" in html.text
    assert "0/231" in html.text
    assert "post-hoc" in html.text
    assert "No live position decision is embedded" in html.text
    assert "does not run it when this page opens" in html.text
    assert "requests one fresh Range Doctor run when this page opens" not in html.text
    assert machine.status_code == 200
    assert machine.headers["vary"] == "Accept"
    assert machine.json()["page"] == "/pancake"
    assert machine.json()["pancake_context"] == {
        "first_party_skills": (
            "PancakeSwap's first-party planner skills stop at generated deep links; "
            "Range Doctor keeps the same plan-only boundary."
        ),
        "subgraph_meta": {
            "query_observed_at": "2026-08-22",
            "indexed_at": "2026-04-28T15:23:43Z",
            "has_indexing_errors": True,
            "method": (
                "Read-only _meta { block { number timestamp } hasIndexingErrors } query. "
                "Docket instead reads PancakeSwap's Explorer API and SHA-pins the response bytes."
            ),
        },
    }
    assert root["pancake"] == "/pancake"


def test_w6_paths_are_in_both_machine_documents(tmp_path):
    client = TestClient(create_app(tmp_path / "docs.sqlite3"))
    llms = client.get("/llms.txt").text
    skill = client.get("/skill.md").text

    for path in (
        "/pancake",
        "/registrations/{service_id}.json",
        "/agents/{agent_id}/probe",
    ):
        assert path in llms
        assert path in skill
    for document in (llms, skill):
        assert "on-demand" in document
        assert "not part of the snapshot's coverage figures" in document


def test_w6_frontend_contract_is_runtime_driven_and_actionable():
    web = Path("docket/api/web")
    page = (web / "pancake.html").read_text(encoding="utf-8")
    script = (web / "app.js").read_text(encoding="utf-8")

    headings = [
        "Live decision",
        "Fixed-window record",
        "Economics",
        "Conditional actions",
        "Structural safety",
        "Decision impact",
        "PancakeSwap context",
    ]
    assert [page.index(heading) for heading in headings] == sorted(
        page.index(heading) for heading in headings
    )
    assert (
        "Range Doctor holds no key, requests no approval, and has no code path that sends a transaction"
        in page
    )
    assert 'href="/skill.md"' in page
    assert (
        "offers the worked Range Doctor request when you choose Run fresh decision"
        in page
    )
    assert "runs the worked Range Doctor request when it opens" not in page
    assert "pancake: initPancake" in script
    assert "data-pancake-run" in script
    assert "await postJSON(record.hire_path, exampleBody(record))" in script
    for runtime_path in (
        'fetchJSON("/services/range-doctor")',
        'fetchJSON("/lp-record")',
        'fetchJSON("/advantage/v2.json")',
    ):
        assert runtime_path in script


def test_research_starts_the_listing_before_name_family_options_finish():
    script = Path("docket/api/web/app.js").read_text(encoding="utf-8")
    init = script[script.index("async function initBrowse()") :]

    assert init.index("goToBrowse(state, false)") < init.index(
        "await fillNameFamilyOptions(state.name_family)"
    )


def test_research_has_a_native_mobile_agent_view():
    script = Path("docket/api/web/app.js").read_text(encoding="utf-8")
    styles = Path("docket/api/web/style.css").read_text(encoding="utf-8")

    assert 'class="agent-cards"' in script
    assert 'class="browse-table table-wrap"' in script
    assert ".agent-cards" in styles
    assert ".browse-table" in styles
    mobile = styles[styles.index("@media (max-width: 640px)") :]
    touch_target_start = mobile.index(".agent-card h3 a")
    touch_target = mobile[touch_target_start : mobile.index("}", touch_target_start)]
    assert "display: inline-flex" in touch_target
    assert "min-width: 44px" in touch_target
    assert "min-height: 44px" in touch_target


def test_research_loading_and_focus_are_bound_to_the_winning_request(tmp_path):
    research = Path("docket/api/web/research.html").read_text(encoding="utf-8")

    assert 'id="results-heading" tabindex="-1"' in research
    assert 'data-region="results-status"' in research
    assert 'role="status"' in research
    assert 'aria-live="polite"' in research
    assert 'data-region="results" aria-busy="true"' in research

    module = tmp_path / "app.mjs"
    module.write_text(
        Path("docket/api/web/app.js").read_text(encoding="utf-8"), encoding="utf-8"
    )
    script = tmp_path / "research-loading.mjs"
    script.write_text(
        r"""
const listeners = {};
const pendingListings = [];
const history = [];
const statusUpdates = [];
const coverage = {
  snapshot_id: 34,
  captured_at: "2026-08-29T00:00:00Z",
  snapshot_age_seconds: 60,
  sampled: 101,
  expected: 101,
  dropped: 0,
  complete: true,
  population: "all",
  filter: null,
};
const item = (name, token) => ({
  agent_id: `56:0xregistry:${token}`,
  token_id: String(token),
  name,
  placeholder_name: false,
  protocols: [],
  declares_callable: false,
  feedback_count: 0,
  name_family: name,
});
const listing = (name, offset, total) => ({
  coverage,
  items: [item(name, offset + 1)],
  offset,
  total,
});
const response = (payload) => ({
  ok: true,
  status: 200,
  json: async () => payload,
});
const failedResponse = {
  ok: false,
  status: 503,
  json: async () => ({ error: { code: "listing_unavailable", message: "Listing unavailable." } }),
};
const retry = { addEventListener: () => {} };
const results = {
  attributes: { "aria-busy": "true" },
  _html: "",
  pagers: [],
  get innerHTML() { return this._html; },
  set innerHTML(value) {
    this._html = value;
    this.pagers = [...value.matchAll(/data-offset="(\d+)"/g)].map((match) => {
      const pager = {
        dataset: { offset: match[1] },
        disabled: false,
        addEventListener: (_name, callback) => { pager.callback = callback; },
      };
      return pager;
    });
  },
  setAttribute: (name, value) => { results.attributes[name] = String(value); },
  getAttribute: (name) => results.attributes[name] ?? null,
  querySelectorAll: (selector) => selector === "[data-offset]" ? results.pagers : [],
  querySelector: (selector) => selector === "[data-retry]" ? retry : null,
};
const resultsStatus = {
  _text: "",
  get textContent() { return this._text; },
  set textContent(value) {
    this._text = value;
    statusUpdates.push(value);
  },
};
const resultsHeading = {
  focusCount: 0,
  focus() { this.focusCount += 1; },
};
const snapshot = { innerHTML: "", textContent: "" };
const partial = { innerHTML: "", hidden: true };
const checkbox = {
  type: "checkbox",
  dataset: { filter: "has_feedback" },
  checked: false,
  addEventListener: (name, callback) => { listeners[`checkbox-${name}`] = callback; },
};
const select = {
  type: "select-one",
  dataset: { filter: "name_family" },
  options: [{ value: "" }],
  value: "",
  insertAdjacentHTML: (_position, html) => {
    select.options.push({ value: html.match(/value="([^"]+)"/)[1] });
  },
  addEventListener: (name, callback) => { listeners[`select-${name}`] = callback; },
};
const clear = {
  addEventListener: (name, callback) => { listeners[`clear-${name}`] = callback; },
};
const regions = { results, "results-status": resultsStatus, snapshot, partial };
globalThis.document = {
  body: { dataset: {} },
  querySelector: (selector) => {
    const match = selector.match(/^\[data-region="([^"]+)"\]$/);
    if (match) return regions[match[1]] || null;
    if (selector === '[data-filter="name_family"]') return select;
    if (selector === '[data-action="clear"]') return clear;
    return null;
  },
  querySelectorAll: (selector) => selector === "[data-filter]" ? [checkbox, select] : [],
  getElementById: (id) => id === "results-heading" ? resultsHeading : null,
};
globalThis.window = {
  location: { search: "", pathname: "/research" },
  history: { pushState: (_state, _title, url) => history.push(String(url)) },
  addEventListener: (name, callback) => { listeners[name] = callback; },
};
let listingRequest = 0;
globalThis.fetch = (path) => {
  const value = String(path);
  if (value === "/stats") {
    return Promise.resolve(response({ top_name_families: [] }));
  }
  if (value.includes("responded=true")) {
    return Promise.resolve(response({ items: [], total: 0 }));
  }
  listingRequest += 1;
  if (listingRequest === 1) {
    return Promise.resolve(response(listing("Initial", 0, 101)));
  }
  return new Promise((resolve) => pendingListings.push({ path: value, resolve }));
};
const { initBrowse } = await import("./app.mjs");
await initBrowse();
await new Promise(setImmediate);
if (resultsHeading.focusCount !== 0) {
  throw new Error("initial browse boot stole focus");
}
if (results.getAttribute("aria-busy") !== "false") {
  throw new Error("initial listing did not leave the results ready");
}
const next = results.pagers.find((button) => button.dataset.offset === "50");
if (!next || typeof next.callback !== "function") {
  throw new Error("initial Next control was not wired");
}
next.callback();
if (!next.disabled) throw new Error("stale pager remained interactive while loading");
checkbox.checked = true;
listeners["checkbox-change"]();
if (pendingListings.length !== 2) {
  throw new Error(`expected two pending listing requests, got ${pendingListings.length}`);
}
if (results.getAttribute("aria-busy") !== "true") {
  throw new Error("winning request did not mark results busy");
}
if (resultsStatus.textContent !== "Loading agents.") {
  throw new Error(`missing concise loading status: ${resultsStatus.textContent}`);
}
pendingListings[0].resolve(response(listing("Stale", 50, 101)));
await new Promise(setImmediate);
if (results.getAttribute("aria-busy") !== "true") {
  throw new Error("stale response cleared the winning request's busy state");
}
if (resultsStatus.textContent !== "Loading agents.") {
  throw new Error("stale response overwrote the winning request's status");
}
if (resultsHeading.focusCount !== 0) {
  throw new Error("stale response moved focus");
}
pendingListings[1].resolve(response(listing("Winner", 0, 1)));
await new Promise(setImmediate);
if (results.getAttribute("aria-busy") !== "false") {
  throw new Error("winning response did not clear busy state");
}
if (resultsStatus.textContent !== "Agents updated. Showing 1 to 1 of 1 matching agents.") {
  throw new Error(`missing completion status: ${resultsStatus.textContent}`);
}
if (resultsHeading.focusCount !== 1) {
  throw new Error(`winning navigation focused ${resultsHeading.focusCount} times`);
}
if (!results.innerHTML.includes("Winner") || results.innerHTML.includes("Stale")) {
  throw new Error("winning response did not exclusively paint the listing");
}
if (statusUpdates.filter((value) => value.startsWith("Agents updated.")).length !== 2) {
  throw new Error(`unexpected completion announcements: ${JSON.stringify(statusUpdates)}`);
}
listeners.popstate();
if (results.getAttribute("aria-busy") !== "true") {
  throw new Error("history navigation did not mark results busy");
}
pendingListings[2].resolve(failedResponse);
await new Promise(setImmediate);
if (results.getAttribute("aria-busy") !== "false") {
  throw new Error("failed history navigation did not clear busy state");
}
if (resultsStatus.textContent !== "Agents could not be loaded.") {
  throw new Error(`missing failure status: ${resultsStatus.textContent}`);
}
if (resultsHeading.focusCount !== 2) {
  throw new Error("failed history navigation did not restore results focus");
}
if (!results.innerHTML.includes('role="alert"')) {
  throw new Error("failed history navigation did not expose an alert");
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


def test_service_success_has_one_completion_status_and_focus_target(tmp_path):
    service = Path("docket/api/web/service.html").read_text(encoding="utf-8")

    assert 'data-region="activation-section"' in service
    assert 'data-region="outcome-status"' in service
    assert 'role="status"' in service
    assert 'aria-live="polite"' in service
    assert 'data-region="outcome" aria-busy="false"' in service

    module = tmp_path / "app.mjs"
    module.write_text(
        Path("docket/api/web/app.js").read_text(encoding="utf-8"), encoding="utf-8"
    )
    script = tmp_path / "service-completion.mjs"
    script.write_text(
        r"""
let submit;
let resolveRun;
let postCalls = 0;
let postMode = "pending";
const statusUpdates = [];
const busyUpdates = [];
const buttonUpdates = [[], []];
const buttons = buttonUpdates.map((updates) => ({
  _disabled: false,
  get disabled() { return this._disabled; },
  set disabled(value) {
    this._disabled = Boolean(value);
    updates.push(this._disabled);
  },
}));
const fieldControls = new Map();
const resultHeading = {
  attributes: {},
  focusCount: 0,
  setAttribute(name, value) { this.attributes[name] = String(value); },
  focus() { this.focusCount += 1; },
};
const form = {
  elements: { namedItem: (name) => fieldControls.get(name) || null },
  querySelector: () => null,
  querySelectorAll: (selector) => {
    if (selector === "[data-array-control]") return [];
    if (selector === 'button[type="submit"]') return buttons;
    return [];
  },
  addEventListener: (name, callback) => {
    if (name === "submit") submit = callback;
  },
};
const serviceRegion = { innerHTML: "" };
const activate = {
  innerHTML: "",
  querySelector: (selector) => selector === "[data-activate]" ? form : null,
};
const outcome = {
  attributes: { "aria-busy": "false" },
  innerHTML: "",
  setAttribute(name, value) {
    this.attributes[name] = String(value);
    if (name === "aria-busy") busyUpdates.push(String(value));
  },
  getAttribute(name) { return this.attributes[name] ?? null; },
  querySelector: (selector) => selector === "h3" ? resultHeading : null,
};
const outcomeStatus = {
  _text: "",
  get textContent() { return this._text; },
  set textContent(value) {
    this._text = value;
    statusUpdates.push(value);
  },
};
const activationSection = { hidden: false };
const regions = {
  service: serviceRegion,
  activate,
  outcome,
  "outcome-status": outcomeStatus,
  "activation-section": activationSection,
};
globalThis.document = {
  title: "Service — Docket",
  body: { dataset: {} },
  querySelector: (selector) => {
    const match = selector.match(/^\[data-region="([^"]+)"\]$/);
    return match ? regions[match[1]] || null : null;
  },
  querySelectorAll: () => [],
};
globalThis.window = { location: { search: "?id=demo" } };
const record = {
  service_id: "demo",
  name: "Demo service",
  metrics: [],
  category_job: null,
  agent_path: null,
  identity: "No chain identity.",
  identity_note: "No binding.",
  evidence: [],
  paid_stock: false,
  stock_status: "hold",
  price_display: "$0.50",
  typical_seconds: 1,
  evidence_modality: "runtime",
  activation_means: "Runs one read.",
  hire_method: "POST",
  hire_path: "/hire/demo",
  what_you_get: "A result.",
  limitations: "One observation.",
  input_schema: { wallet: { type: "string", required: true } },
};
fieldControls.set("wallet", { value: "0xabc" });
const response = (payload) => ({
  ok: true,
  status: 200,
  json: async () => payload,
});
globalThis.fetch = (path, options = {}) => {
  if (!options.method) return Promise.resolve(response(record));
  postCalls += 1;
  if (postMode === "reject") throw new Error("connection lost");
  return new Promise((resolve) => { resolveRun = resolve; });
};
const { initService } = await import("./app.mjs");
await initService();
if (typeof submit !== "function") throw new Error("service form was not wired");
const running = submit({
  preventDefault() {},
  submitter: { matches: () => false },
});
if (!buttons.every((button) => button.disabled)) {
  throw new Error("all submit controls were not disabled during the run");
}
if (outcome.getAttribute("aria-busy") !== "true") {
  throw new Error("service outcome was not marked busy");
}
if (outcomeStatus.textContent !== "Running Demo service.") {
  throw new Error(`missing run status: ${outcomeStatus.textContent}`);
}
resolveRun(response({ result: { ok: true }, receipt: { payment: { status: "not_required" } } }));
await running;
if (!buttons.every((button) => !button.disabled)) {
  throw new Error("submit controls were not restored after the run");
}
if (outcome.getAttribute("aria-busy") !== "false") {
  throw new Error("service outcome remained busy after completion");
}
if (outcomeStatus.textContent !== "Demo service finished. The result is ready.") {
  throw new Error(`missing completion status: ${outcomeStatus.textContent}`);
}
if (statusUpdates.filter((value) => value.includes("finished")).length !== 1) {
  throw new Error(`completion was announced more than once: ${JSON.stringify(statusUpdates)}`);
}
if (resultHeading.focusCount !== 1 || resultHeading.attributes.tabindex !== "-1") {
  throw new Error("completed result heading was not focused exactly once");
}
if (outcome.innerHTML.includes('role="status"') || outcome.innerHTML.includes("aria-live")) {
  throw new Error("transient outcome markup duplicated the persistent live status");
}
fieldControls.get("wallet").value = "";
postMode = "reject";
const validationCalls = postCalls;
const validationBusyStart = busyUpdates.length;
await submit({
  preventDefault() {},
  submitter: { matches: () => false },
});
if (postCalls !== validationCalls) {
  throw new Error("missing required input reached the network");
}
if (busyUpdates.slice(validationBusyStart).includes("true")) {
  throw new Error("missing required input entered the busy state");
}
if (!buttons.every((button) => !button.disabled)) {
  throw new Error("missing required input changed submit availability");
}
fieldControls.get("wallet").value = "0xabc";
const rejectionBusyStart = busyUpdates.length;
await submit({
  preventDefault() {},
  submitter: { matches: () => false },
});
if (postCalls !== validationCalls + 1) {
  throw new Error("the rejected request was not attempted exactly once");
}
if (busyUpdates.slice(rejectionBusyStart).join(",") !== "false,true,false") {
  throw new Error(`rejected request busy sequence was ${busyUpdates.slice(rejectionBusyStart)}`);
}
if (!buttons.every((button) => !button.disabled)) {
  throw new Error("submit controls were not restored after rejection");
}
if (outcomeStatus.textContent !== "") {
  throw new Error("a failed request left a stale polite completion status");
}
if ((outcome.innerHTML.match(/role="alert"/g) || []).length !== 1) {
  throw new Error("a failed request did not expose exactly one alert");
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


def test_terminal_agent_and_service_states_keep_primary_headings():
    agent = Path("docket/api/web/agent.html").read_text(encoding="utf-8")
    service = Path("docket/api/web/service.html").read_text(encoding="utf-8")
    script = Path("docket/api/web/app.js").read_text(encoding="utf-8")

    assert "<h1>This page reads live data with JavaScript</h1>" in agent
    assert "<h1>No agent selected</h1>" in script
    assert 'renderError(target, err, "Agent unavailable")' in script
    assert "<h1>No service selected</h1>" in script
    assert 'renderError(target, err, "Service unavailable")' in script
    assert 'data-region="activation-section"' in service
    assert script.count("activationSection.hidden = true") == 2


def test_interactive_targets_have_a_44_pixel_floor():
    styles = Path("docket/api/web/style.css").read_text(encoding="utf-8")

    def rule(selector):
        start = styles.index(selector)
        return styles[start : styles.index("}", start)]

    nav = rule(".site-nav a {")
    assert "min-width: 44px" in nav
    assert "min-height: 44px" in nav
    checks = rule(".check {")
    assert "min-height: 44px" in checks
    controls = rule('select,\ninput[type="text"]')
    assert "min-height: 44px" in controls
    buttons = rule(".btn {")
    assert "min-width: 44px" in buttons
    assert "min-height: 44px" in buttons
    summaries = rule("summary {")
    assert "min-height: 44px" in summaries


def test_snapshot_warning_does_not_create_a_heading_before_agent_title():
    script = Path("docket/api/web/app.js").read_text(encoding="utf-8")
    styles = Path("docket/api/web/style.css").read_text(encoding="utf-8")

    assert '<p class="notice-heading">${heading}</p>' in script
    assert "<h3>${heading}</h3>" not in script
    assert ".notice-heading" in styles


def test_critical_inline_styles_are_exactly_hash_bound_by_csp(tmp_path):
    styles = []
    for page in Path("docket/api/web").glob("*.html"):
        html = page.read_text(encoding="utf-8")
        assert 'style="' not in html, page
        assert html.count("<style>") == html.count("</style>"), page
        if "<style>" in html:
            assert html.count("<style>") == 1, page
            styles.append(html.split("<style>", 1)[1].split("</style>", 1)[0])

    assert len(styles) == 4
    policy = (
        TestClient(create_app(tmp_path / "csp.sqlite3"))
        .get("/")
        .headers["content-security-policy"]
    )
    assert "'unsafe-inline'" not in policy
    for style in set(styles):
        digest = base64.b64encode(hashlib.sha256(style.encode()).digest()).decode()
        assert f"'sha256-{digest}'" in policy


def test_research_preserves_query_name_family_during_concurrent_boot(tmp_path):
    module = tmp_path / "app.mjs"
    module.write_text(
        Path("docket/api/web/app.js").read_text(encoding="utf-8"), encoding="utf-8"
    )
    script = tmp_path / "research-boot.mjs"
    script.write_text(
        r"""
const listeners = {};
const requests = [];
const checkbox = {
  type: "checkbox",
  dataset: { filter: "has_feedback" },
  checked: false,
  addEventListener: (name, callback) => { listeners[name] = callback; },
};
const select = {
  type: "select-one",
  dataset: { filter: "name_family" },
  options: [{ value: "" }],
  _value: "",
  get value() { return this._value; },
  set value(next) {
    this._value = this.options.some((option) => option.value === next) ? next : "";
  },
  insertAdjacentHTML: (_position, html) => {
    const value = html.match(/value="([^"]+)"/)[1];
    select.options.push({ value });
  },
  addEventListener: (name, callback) => { listeners[`select-${name}`] = callback; },
};
const results = {
  setAttribute: () => {},
  querySelectorAll: () => [],
};
const resultsStatus = { textContent: "" };
globalThis.document = {
  body: { dataset: {} },
  querySelector: (selector) => {
    if (selector === '[data-filter="name_family"]') return select;
    if (selector === '[data-region="results"]') return results;
    if (selector === '[data-region="results-status"]') return resultsStatus;
    return null;
  },
  querySelectorAll: (selector) => selector === "[data-filter]" ? [select, checkbox] : [],
};
globalThis.window = {
  location: { search: "?name_family=rare-family", pathname: "/research" },
  history: { pushState: (_state, _title, url) => requests.push(String(url)) },
  addEventListener: () => {},
};
globalThis.fetch = (path) => {
  requests.push(String(path));
  return new Promise(() => {});
};
const { initBrowse } = await import("./app.mjs");
initBrowse();
if (select.value !== "rare-family") {
  throw new Error(`query family was synchronously lost: ${select.value}`);
}
checkbox.checked = true;
listeners.change();
const listing = requests.find((path) =>
  path.startsWith("/agents?") &&
  path.includes("name_family=rare-family") &&
  path.includes("has_feedback=true")
);
if (!listing) {
  throw new Error(`interaction dropped query family: ${requests.join(" | ")}`);
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


def test_pancake_only_posts_after_explicit_run_click(tmp_path):
    module = tmp_path / "app.mjs"
    module.write_text(
        Path("docket/api/web/app.js").read_text(encoding="utf-8"), encoding="utf-8"
    )
    script = tmp_path / "pancake-boot.mjs"
    script.write_text(
        r"""
const requests = [];
let runFresh;
const button = {
  disabled: false,
  textContent: "",
  addEventListener: (name, callback) => {
    if (name === "click") runFresh = callback;
  },
};
const note = { textContent: "" };
const regions = Object.fromEntries([
  "pancake-decision",
  "pancake-economics",
  "pancake-actions",
  "pancake-record",
  "pancake-impact",
  "pancake-context",
].map((name) => [name, {
  innerHTML: "",
  querySelector: (selector) => selector === "[data-pancake-run]" ? button : note,
}]));
globalThis.document = {
  body: { dataset: {} },
  querySelector: (selector) => {
    const match = selector.match(/^\[data-region="([^"]+)"\]$/);
    return match ? regions[match[1]] : null;
  },
  querySelectorAll: () => [],
};
globalThis.window = {};
const payloads = {
  "/services/range-doctor": {
    name: "Range Doctor",
    hire_path: "/hire/range-doctor",
    input_schema: {},
  },
  "/lp-record": { lines: [], skipped_unparsable: 0, truncated: false },
  "/advantage/v2.json": {
    decision_impact: {
      registration_state: "post_hoc",
      registration_note: "Registered after analysis.",
      ranking_reversals: { numerator: 0, denominator: 1, what_this_measures: "pairs" },
      dollars_at_notionals: {
        notionals: [{ notional_usd: 10000, n_pools: 1, median_annual_overstatement_usd: 1 }],
      },
      break_even_shift: {
        notional_usd: 10000,
        n_moves: 1,
        median_days_later_than_gross_implies: 1,
        what_it_does_not_measure: "future rates",
      },
    },
  },
  "/pancake": {
    pancake_context: {
      first_party_skills: "Read-only context.",
      subgraph_meta: {
        query_observed_at: "2026-08-22T00:00:00Z",
        indexed_at: "2026-08-21T00:00:00Z",
        has_indexing_errors: false,
        method: "Subgraph query.",
      },
    },
  },
  "/hire/range-doctor": { result: { positions: [] }, receipt: {} },
};
globalThis.fetch = async (path, options = {}) => {
  requests.push({ path, method: options.method || "GET" });
  return { ok: true, status: 200, json: async () => payloads[path] };
};
const { initPancake } = await import("./app.mjs");
await initPancake();
if (requests.some((request) => request.method === "POST")) {
  throw new Error("page initialization performed a POST");
}
if (typeof runFresh !== "function") throw new Error("explicit run control was not wired");
await runFresh();
const posts = requests.filter((request) => request.method === "POST");
if (posts.length !== 1 || posts[0].path !== "/hire/range-doctor") {
  throw new Error(`expected one explicit hire POST, got ${JSON.stringify(posts)}`);
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


def test_on_demand_probe_does_not_replace_sweep_observation_rows(tmp_path):
    module = tmp_path / "app.mjs"
    module.write_text(
        Path("docket/api/web/app.js").read_text(encoding="utf-8"), encoding="utf-8"
    )
    script = tmp_path / "agent-observations.mjs"
    script.write_text(
        r"""
globalThis.document = {
  body: { dataset: {} },
  querySelector: () => null,
  querySelectorAll: () => [],
};
globalThis.window = {};
const { observationSection } = await import("./app.mjs");
const rendered = observationSection({
  coverage: { snapshot_id: 34 },
  declares_callable: true,
  endpoints: ["https://a.example/a2a"],
  observations: [{
    url: "https://a.example/a2a",
    kind: "a2a",
    outcome: "responded",
    status_code: 204,
    elapsed_ms: 120,
    observed_at: "2026-08-21T10:00:00Z",
    detail: null,
  }],
  latest_on_demand_observation: {
    url: "https://a.example/a2a",
    kind: "a2a",
    outcome: "timeout",
    status_code: null,
    elapsed_ms: 8000,
    observed_at: "2026-08-22T10:00:00Z",
    detail: "ReadTimeout",
  },
});
if (rendered.includes("[object Object]")) {
  throw new Error("the on-demand observation replaced the sweep rows");
}
for (const text of ["https://a.example/a2a", "Answered", "204"]) {
  if (!rendered.includes(text)) throw new Error(`sweep table omitted ${text}`);
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


def test_agent_action_block_reuses_the_six_outcomes_and_gates_reprobe():
    script = Path("docket/api/web/app.js").read_text(encoding="utf-8")

    assert "What you can do with this agent" in script
    assert "Re-probe now" in script
    assert "declares_callable" in script
    assert 'outcome === "responded"' in script
    assert "does not show what the agent does behind it" in script
    for outcome in OUTCOMES:
        assert f"{outcome}:" in script


def test_agent_action_block_renders_endpoint_evidence_and_exact_reprobe_gate(tmp_path):
    module = tmp_path / "app.mjs"
    module.write_text(
        Path("docket/api/web/app.js").read_text(encoding="utf-8"), encoding="utf-8"
    )
    script = tmp_path / "agent-action.mjs"
    script.write_text(
        r"""
globalThis.document = {
  body: { dataset: {} },
  querySelector: () => null,
  querySelectorAll: () => [],
};
globalThis.window = {};
const { agentActionBlock } = await import("./app.mjs");
const detail = {
  declares_callable: true,
  x402: true,
  endpoints: ["https://a.example/a2a", "https://a.example/about"],
  observations: [{
    url: "https://a.example/a2a",
    kind: "a2a",
    outcome: "responded",
    status_code: 204,
    observed_at: "2026-08-21T10:00:00Z",
  }],
  latest_on_demand_observation: {
    url: "https://a.example/a2a",
    kind: "a2a",
    outcome: "timeout",
    status_code: null,
    elapsed_ms: 8000,
    observed_at: "2026-08-22T10:00:00Z",
    detail: "ReadTimeout",
  },
};
const answered = agentActionBlock(detail, "<p>bound service</p>");
for (const text of [
  "What you can do with this agent",
  "https://a.example/a2a",
  "HTTP status 204",
  "2026-08-21T10:00:00Z",
  "Declares x402 payments</dt><dd>yes",
  "bound service",
  "It does not prove the agent behind the URL does anything",
  "Latest on-demand re-probe",
  "2026-08-22T10:00:00Z",
  "not part of the snapshot's coverage figures",
  "ReadTimeout",
]) {
  if (!answered.includes(text)) throw new Error(`answered action omitted ${text}`);
}
if (answered.includes("data-reprobe")) {
  throw new Error("an on-demand timeout left the re-probe control enabled");
}
if (answered.includes("https://a.example/about")) {
  throw new Error("an unprobed web endpoint entered the A2A/MCP action block");
}
const timedOut = agentActionBlock({
  ...detail,
  latest_on_demand_observation: null,
  observations: [
    { ...detail.observations[0], outcome: "timeout", status_code: null },
    {
      url: "https://a.example/about",
      kind: "web",
      outcome: "responded",
      status_code: 200,
      observed_at: "2026-08-22T10:00:00Z",
    },
  ],
}, "");
if (timedOut.includes("data-reprobe")) {
  throw new Error("a newer web response made an A2A timeout re-probeable");
}
if (!timedOut.includes("Timed out") || !timedOut.includes("Nothing came back inside")) {
  throw new Error("timeout explanation changed");
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


def test_pancake_painters_render_runtime_rows_figures_and_actions(tmp_path):
    module = tmp_path / "app.mjs"
    module.write_text(
        Path("docket/api/web/app.js").read_text(encoding="utf-8"), encoding="utf-8"
    )
    script = tmp_path / "pancake-painters.mjs"
    script.write_text(
        r"""
const regions = new Map(
  ["pancake-record", "pancake-decision", "pancake-economics", "pancake-actions", "pancake-impact"]
    .map((name) => [name, { innerHTML: "" }]),
);
globalThis.document = {
  body: { dataset: {} },
  querySelector: (selector) => {
    const match = selector.match(/data-region="([^"]+)"/);
    return match ? regions.get(match[1]) || null : null;
  },
  querySelectorAll: () => [],
};
globalThis.window = {};
const {
  paintPancakeRecord,
  paintPancakeLive,
  paintPancakeDecisionImpact,
} = await import("./app.mjs");

paintPancakeRecord({
  skipped_unparsable: 1,
  truncated: true,
  lines: [
    {
      observed_at: "2026-08-15T00:00:00Z",
      report: { positions: [{ diagnosis: {
        decision: "first observation",
        status: "out_of_range_below",
        verifiable_facts: { bsc_block: 111 },
      } }] },
    },
    {
      kind: "owner_decision",
      decided_at: "2026-08-16T00:00:00Z",
      decision: "WAIT",
      rationale: "owner rationale",
      prior_observation_sha256: "abc",
    },
    {
      observed_at: "2026-08-17T00:00:00Z",
      answers_decision_sha256: "def",
      report: { positions: [{ diagnosis: {
        decision: "later observation",
        status: "in_range",
        verifiable_facts: { bsc_block: 222 },
      } }] },
    },
  ],
});
const history = regions.get("pancake-record").innerHTML;
if (!(history.indexOf("first observation") < history.indexOf("Owner decision: WAIT") &&
      history.indexOf("Owner decision: WAIT") < history.indexOf("later observation"))) {
  throw new Error("record sequence changed");
}
for (const text of ["below range", "in range", "could not be parsed", "was truncated", "does not run verify_history"]) {
  if (!history.includes(text)) throw new Error(`record omitted ${text}`);
}

paintPancakeRecord({ lines: [], skipped_unparsable: 0, truncated: false });
const emptyHistory = regions.get("pancake-record").innerHTML;
if (!emptyHistory.includes("No record lines are mounted on this host.")) {
  throw new Error("empty record did not explain the missing host mount");
}
if (emptyHistory.includes("<table")) {
  throw new Error("empty record rendered an empty table");
}

paintPancakeLive({ price_display: "free" }, {
  result: {
    decision: "fallback",
    pancake_headline: { median_payback_delay_days: 8.3, n_candidate_moves: 44 },
    positions: [{ diagnosis: {
      decision: "live decision sentence",
      status: "out_of_range_below",
      verifiable_facts: {
        position_id: 7141050,
        bsc_block: 333,
        observation_time: "2026-08-22T06:03:00Z",
      },
      economic_consequence: {
        gross_apr: 0.3,
        net_apr: 0.2,
        overstatement_relative: 0.5,
        declared_position_value_usd: 50.55,
        annual_gross_usd: 15.165,
        annual_net_usd: 10.11,
        annual_overstatement_usd: 5.055,
        limitation: "fixed-notional proxy limitation",
      },
      conditional_actions: {
        cost_only_break_even_days: 36.1,
        limitation: "cost-only limitation",
        actions: [{
          kind: "wait",
          text: "wait condition",
          link: "https://pancakeswap.finance/liquidity/7141050?chain=bsc",
        }],
      },
    } }],
  },
});
for (const [name, text] of [
  ["pancake-decision", "live decision sentence"],
  ["pancake-economics", "$5.06"],
  ["pancake-economics", "8.30 days across 44 candidate moves"],
  ["pancake-actions", "wait condition"],
  ["pancake-actions", "pancakeswap.finance/liquidity/7141050"],
]) {
  if (!regions.get(name).innerHTML.includes(text)) throw new Error(`${name} omitted ${text}`);
}

paintPancakeDecisionImpact({ decision_impact: {
  registration_state: "post_hoc",
  registration_note: "known after the run",
  ranking_reversals: { numerator: 0, denominator: 231, what_this_measures: "ordered pairs" },
  dollars_at_notionals: { notionals: [{
    notional_usd: 10000,
    n_pools: 22,
    median_annual_overstatement_usd: 126.78,
  }] },
  break_even_shift: {
    notional_usd: 10000,
    n_moves: 44,
    median_days_later_than_gross_implies: 8.3,
    what_it_does_not_measure: "not realized returns",
  },
} });
const impact = regions.get("pancake-impact").innerHTML;
for (const text of ["$126.78", "across 22 eligible pools", "8.30 days", "0/231", "post-hoc"]) {
  if (!impact.includes(text)) throw new Error(`impact omitted ${text}`);
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


def test_navigation_names_public_marketplace_destinations():
    index = Path("docket/api/web/index.html").read_text(encoding="utf-8")

    assert 'href="/" aria-current="page">Explore</a>' in index
    assert 'href="/search">Find agents</a>' in index
    assert 'href="/my-agents">My agents</a>' in index
    assert 'href="/providers">Providers</a>' in index
    assert 'href="/advantage">Evidence</a>' in index
    assert 'href="/llms.txt">API</a>' in index
