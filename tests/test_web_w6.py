import asyncio
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
        response = client.post(f"/agents/{AGENT_ID}/probe")

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
    refused = client.post(f"/agents/{AGENT_ID}/probe")
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
    response = client.post(f"/agents/{AGENT_ID}/probe")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "probe_not_available"


def test_live_probe_requires_a_callable_declaration(tmp_path, monkeypatch):
    agent = {**AGENT, "supported_protocols": []}
    client, _store, _snapshot_id = _agent_client(tmp_path, agent=agent)

    def unexpected_probe(*_args, **_kwargs):
        raise AssertionError("a non-callable declaration must not be probed")

    monkeypatch.setattr(routes, "probe_one", unexpected_probe)
    response = client.post(f"/agents/{AGENT_ID}/probe")

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
    response = client.post(f"/agents/{AGENT_ID}/probe")

    assert response.status_code == 429
    assert response.headers["retry-after"]
    assert response.json()["error"]["code"] == "probe_rate_limited"


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
                async_client.post(f"/agents/{AGENT_ID}/probe")
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
    assert "pancake: initPancake" in script
    assert "postJSON(record.hire_path, exampleBody(record))" in script
    for runtime_path in (
        'fetchJSON("/services/range-doctor")',
        'fetchJSON("/lp-record")',
        'fetchJSON("/advantage/v2.json")',
    ):
        assert runtime_path in script


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
for (const text of ["$126.78", "across 22 eligible pools", "8.30 days", "0/231", "post_hoc"]) {
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


def test_navigation_names_the_registry_destination_and_links_pancake():
    index = Path("docket/api/web/index.html").read_text(encoding="utf-8")

    assert 'href="/research">Browse agents</a>' in index
    assert 'href="/pancake">PancakeSwap</a>' in index
