# Docket Phase 1c — Agent-Facing API Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Serve Docket's evidence over a read-only HTTP API that a *machine* can drive with no instructions — because TermiX's evaluators hire through coding agents, and their own tooling fails closed on anything undocumented.

**Architecture:** A FastAPI app reading the Phase 1a/1b SQLite store directly (506 rows — no caching layer earns its keep yet). Every statistic ships with its own coverage context; no endpoint returns a verdict. A hand-written `/llms.txt` and `SKILL.md` sit alongside the auto-generated OpenAPI so an agent can orient without guessing.

**Tech Stack:** Python 3.11+, `fastapi==0.137.1`, `uvicorn==0.49.0`, `pydantic==2.13.4` (matching the house pins in `warden-roadmap/pyproject.toml`), plus the existing `httpx`/stdlib. `pytest` with FastAPI's `TestClient`.

## Global Constraints

- Pin exactly: `fastapi==0.137.1`, `uvicorn==0.49.0`, `pydantic==2.13.4`. These are the only new dependencies permitted in this phase.
- **Read-only.** No endpoint writes to the store, triggers a sweep, or probes anything. Phase 1c ships zero mutation.
- **No bare statistics.** Any response containing a count or percentage also carries `snapshot_id`, `captured_at`, and the `sampled`/`expected`/`dropped` context it was computed from. A number without its coverage is a lie by omission.
- **No verdicts.** No field may be named or valued `safe`, `trusted`, `verified_by_docket`, `recommended`, `score` (as an opinion), or `rank`. Docket serves observations — `has_feedback`, `declares_callable`, `last_probe_outcome` — and the reader judges. A test enforces the field-name ban across every response model.
- `responded_pct` and every other rate divides by the population actually measured (probed endpoints), never by the registry.
- Errors are structured: `{"error": {"code": "<STABLE_SNAKE_CODE>", "message": "<what to do about it>"}}` with a stable code an agent can branch on. No bare 500s, no HTML error pages.
- CORS: `GET`/`HEAD` from any origin (this is public evidence), no credentials.
- No Claude/Anthropic attribution; no Co-Authored-By. Stage by explicit filename. Do not push. `data/` stays gitignored.
- Repo `.`, run with `./.venv/Scripts/python`.

## File Structure

```
docket/api/__init__.py     # create_app() factory
docket/api/models.py       # pydantic response models (the public contract)
docket/api/routes.py       # the endpoints
docket/api/static/llms.txt # hand-written agent orientation guide
docket/api/static/SKILL.md # drop-in skill file for coding agents
tests/test_api.py
tests/test_api_contract.py # the bans: no verdict fields, no bare statistics
```

---

### Task 1: Response models and the contract tests

**Files:**
- Create: `docket/api/__init__.py`, `docket/api/models.py`, `tests/test_api_contract.py`
- Modify: `pyproject.toml` (add the three pins)

**Interfaces:**
- Produces: `Coverage`, `AgentSummary`, `AgentDetail`, `EndpointObservation`, `ListResponse`, `StatsResponse`, `ErrorBody` pydantic models, and `BANNED_FIELD_NAMES` (a frozenset the contract test imports). Task 2's routes return these.

**Why the models come first:** they are the public contract an evaluator's agent will parse. Getting the field names right — and provably free of verdict language — matters more than the handlers.

- [ ] **Step 1: Add the pins to `pyproject.toml`** under `[project] dependencies`:

```toml
    "fastapi==0.137.1",
    "uvicorn==0.49.0",
    "pydantic==2.13.4",
```

Then `./.venv/Scripts/python -m pip install -e ".[dev]"`.

- [ ] **Step 2: Write the failing contract test `tests/test_api_contract.py`**

```python
import pydantic

from docket.api.models import (
    BANNED_FIELD_NAMES,
    AgentDetail,
    AgentSummary,
    Coverage,
    ListResponse,
    StatsResponse,
)

ALL_MODELS = [Coverage, AgentSummary, AgentDetail, ListResponse, StatsResponse]


def _field_names(model: type[pydantic.BaseModel]) -> set[str]:
    return set(model.model_fields)


def test_no_model_exposes_a_verdict_field():
    """Docket serves observations. A verdict field would make it an authority it has not earned."""
    for model in ALL_MODELS:
        offending = _field_names(model) & BANNED_FIELD_NAMES
        assert not offending, f"{model.__name__} exposes verdict field(s): {offending}"


def test_banned_names_cover_the_obvious_temptations():
    for name in ("safe", "trusted", "verified_by_docket", "recommended", "rank", "trust_score"):
        assert name in BANNED_FIELD_NAMES


def test_every_statistic_carries_its_coverage():
    """StatsResponse must not be able to report a count without the snapshot it came from."""
    required = {"snapshot_id", "captured_at", "sampled", "expected", "dropped"}
    assert required <= _field_names(Coverage)
    assert "coverage" in _field_names(StatsResponse)
    assert Coverage.model_fields["snapshot_id"].is_required()


def test_list_response_states_its_coverage_too():
    assert "coverage" in _field_names(ListResponse)


def test_agent_summary_uses_observation_language():
    names = _field_names(AgentSummary)
    assert {"has_feedback", "declares_callable"} <= names


def test_agent_detail_carries_timestamped_observations():
    names = _field_names(AgentDetail)
    assert "observations" in names
    assert "endpoints" in names
```

- [ ] **Step 3: Write `docket/api/models.py`**

Models, all `pydantic.BaseModel`:
- `BANNED_FIELD_NAMES = frozenset({"safe", "trusted", "verified", "verified_by_docket", "recommended", "rank", "trust_score", "score", "rating", "endorsed", "certified"})`
- `Coverage`: `snapshot_id: int`, `captured_at: str | None`, `sampled: int`, `expected: int`, `dropped: int`, `complete: bool`, `filter: str | None` (e.g. `"min_feedbacks=1"` — states what population this snapshot covers).
- `AgentSummary`: `agent_id: str`, `token_id: str`, `name: str | None`, `description: str | None`, `owner_address: str | None`, `has_feedback: bool`, `feedback_count: int`, `declares_callable: bool`, `protocols: list[str]`, `x402: bool`, `publisher: str`, `placeholder_name: bool`.
- `EndpointObservation`: `url: str`, `kind: str`, `observed_at: str | None`, `outcome: str | None`, `status_code: int | None`, `elapsed_ms: int | None`, `detail: str | None`.
- `AgentDetail`: everything in `AgentSummary` plus `endpoints: list[str]`, `observations: list[EndpointObservation]`, `coverage: Coverage`.
- `ListResponse`: `items: list[AgentSummary]`, `total: int`, `limit: int`, `offset: int`, `coverage: Coverage`.
- `StatsResponse`: `coverage: Coverage`, plus the generated figures — `with_feedback`, `callable_declared`, `endpoints_resolved`, `endpoints_probed`, `endpoints_responded`, `responded_pct_of_probed`, `blocked_by_policy`, `unresolved`, `distinct_publishers`, `top_publishers: list[dict]`, and `probe_method: str` (a one-line statement of how liveness was measured).
- `ErrorBody`: `error: dict[str, str]`.

Note `responded_pct_of_probed` is named that way on purpose — the field name itself states its denominator, so it cannot be misquoted downstream.

- [ ] **Step 4: Run** `./.venv/Scripts/python -m pytest tests/test_api_contract.py -q` → 6 passed. Full suite → 81 passed.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml docket/api/__init__.py docket/api/models.py tests/test_api_contract.py
git commit -m "feat(api): response contract with verdict-field ban and mandatory coverage"
```

---

### Task 2: The endpoints

**Files:**
- Create: `docket/api/routes.py`, `tests/test_api.py`
- Modify: `docket/api/__init__.py` (add `create_app`)

**Interfaces:**
- Consumes: `Store`, `signals_for`, `coverage_report`.
- Produces: `create_app(db_path: str | Path, snapshot_id: int | None = None) -> FastAPI`.

**Endpoints:**

| Method | Path | Purpose |
|---|---|---|
| GET | `/` | Service identity, links to `/llms.txt`, `/openapi.json`, `/stats` |
| GET | `/health` | Docket's own liveness + which snapshot is being served |
| GET | `/stats` | The generated coverage + liveness figures |
| GET | `/agents` | Filterable list: `has_feedback`, `declares_callable`, `responded`, `publisher`, `limit` (≤100), `offset` |
| GET | `/agents/{agent_id:path}` | One agent with endpoints and timestamped observations |
| GET | `/llms.txt` | Plain-text agent orientation (Task 3) |

`agent_id` contains colons (`56:0x8004…:136384`), hence the `:path` converter — a test pins that a colon-bearing id resolves.

- [ ] **Step 1: Write the failing test `tests/test_api.py`**

```python
import pytest
from fastapi.testclient import TestClient

from docket.api import create_app
from docket.store import Store

AGENT = {
    "agent_id": "56:0xreg:136384", "token_id": "136384", "chain_id": 56,
    "name": "SOLVENT", "description": "glass-box trader", "owner_address": "0xabc",
    "supported_protocols": ["A2A"], "x402_supported": True,
    "total_feedbacks": 3, "total_score": 12.0,
}
QUIET = {
    "agent_id": "56:0xreg:999", "token_id": "999", "chain_id": 56,
    "name": "Agent #999", "supported_protocols": [], "total_feedbacks": 0,
}


@pytest.fixture
def client(tmp_path):
    db = tmp_path / "d.sqlite3"
    store = Store(db)
    sid = store.begin_snapshot(chain_id=56, expected=2)
    store.upsert_agents([AGENT, QUIET], sid)
    store.upsert_endpoints(
        [{"agent_id": AGENT["agent_id"], "kind": "a2a", "url": "https://a.example/a2a"}], sid
    )
    store.record_liveness([{
        "snapshot_id": sid, "agent_id": AGENT["agent_id"], "url": "https://a.example/a2a",
        "observed_at": "2026-08-07T10:00:00+00:00", "outcome": "responded",
        "status_code": 200, "elapsed_ms": 120, "detail": None,
    }])
    store.finish_snapshot(sid, sampled=2, expected=2)
    return TestClient(create_app(db, snapshot_id=sid))


def test_health_names_the_snapshot_it_serves(client):
    body = client.get("/health").json()
    assert body["status"] == "ok"
    assert body["snapshot_id"] == 1


def test_root_points_an_agent_at_its_documentation(client):
    body = client.get("/").json()
    for key in ("llms_txt", "openapi", "stats", "agents"):
        assert key in body


def test_stats_never_reports_a_number_without_coverage(client):
    body = client.get("/stats").json()
    cov = body["coverage"]
    assert cov["sampled"] == 2 and cov["expected"] == 2 and cov["dropped"] == 0
    assert cov["complete"] is True and cov["snapshot_id"] == 1
    assert body["with_feedback"] == 1
    assert "probe_method" in body and body["probe_method"]


def test_responded_pct_divides_by_probed_not_by_registry(client):
    body = client.get("/stats").json()
    # 1 endpoint probed, 1 responded -> 100% of probed, NOT 50% of the 2 agents.
    assert body["endpoints_probed"] == 1
    assert body["endpoints_responded"] == 1
    assert body["responded_pct_of_probed"] == 100.0


def test_agents_list_is_filterable_and_states_coverage(client):
    body = client.get("/agents").json()
    assert body["total"] == 2 and len(body["items"]) == 2
    assert body["coverage"]["snapshot_id"] == 1
    only = client.get("/agents", params={"has_feedback": "true"}).json()
    assert only["total"] == 1
    assert only["items"][0]["agent_id"] == AGENT["agent_id"]
    callable_only = client.get("/agents", params={"declares_callable": "true"}).json()
    assert callable_only["total"] == 1


def test_agent_detail_resolves_a_colon_bearing_id_and_carries_observations(client):
    body = client.get(f"/agents/{AGENT['agent_id']}").json()
    assert body["agent_id"] == AGENT["agent_id"]
    assert body["endpoints"] == ["https://a.example/a2a"]
    assert len(body["observations"]) == 1
    obs = body["observations"][0]
    assert obs["outcome"] == "responded" and obs["status_code"] == 200
    assert obs["observed_at"].startswith("2026-08-07")


def test_unknown_agent_returns_a_structured_actionable_error(client):
    resp = client.get("/agents/56:0xreg:404404")
    assert resp.status_code == 404
    err = resp.json()["error"]
    assert err["code"] == "agent_not_found"
    assert err["message"]  # tells the caller what to do


def test_limit_is_capped_and_offset_paginates(client):
    body = client.get("/agents", params={"limit": 5000}).json()
    assert body["limit"] == 100
    page2 = client.get("/agents", params={"limit": 1, "offset": 1}).json()
    assert len(page2["items"]) == 1 and page2["offset"] == 1


def test_bad_query_value_returns_the_structured_error_shape(client):
    resp = client.get("/agents", params={"limit": "banana"})
    assert resp.status_code == 422
    assert "error" in resp.json() and "code" in resp.json()["error"]


def test_openapi_is_served_so_an_agent_need_not_guess(client):
    spec = client.get("/openapi.json").json()
    assert "/agents" in spec["paths"] and "/stats" in spec["paths"]
```

- [ ] **Step 2: Write `docket/api/routes.py` and `create_app`.** Serve from one `Store` opened per request (SQLite connections are cheap and the store closes them). Resolve the snapshot once at startup via `store.latest_snapshot_id(56)` unless one is injected. Register a `RequestValidationError` handler and an `HTTPException` handler that both emit the `{"error": {"code", "message"}}` shape — FastAPI's defaults return `{"detail": ...}`, which would break the contract test. Add CORS for `GET`/`HEAD`, any origin, no credentials. Compute list filters in SQL where cheap, in Python via `signals_for` where not; `total` is the count *after* filtering.

- [ ] **Step 3: Run** `./.venv/Scripts/python -m pytest tests/test_api.py -q` → 10 passed. Full suite → 91 passed.

- [ ] **Step 4: Commit**

```bash
git add docket/api/routes.py docket/api/__init__.py tests/test_api.py
git commit -m "feat(api): read-only evidence endpoints with structured errors"
```

---

### Task 3: The agent-facing surface

**Files:**
- Create: `docket/api/static/llms.txt`, `docket/api/static/SKILL.md`
- Modify: `docket/api/routes.py` (serve `/llms.txt`), `tests/test_api.py` (two tests)

**Why this task exists:** TermiX's own agent skill instructs *"Do not invent REST endpoints. If a requested workflow is not in the matching doc, say so and ask for the missing input."* An evaluator's agent that cannot find a doc will stop rather than explore. `/llms.txt` is the doc it looks for.

- [ ] **Step 1: Write `docket/api/static/llms.txt`** — plain text, no marketing. It must state, in this order: what Docket is in one sentence; the base URL; every endpoint with its parameters and an example `curl`; what the coverage fields mean and why every number carries them; the exact liveness outcome vocabulary and what each value does and does not imply; and an explicit statement that Docket publishes observations, not endorsements, and lists no agent as safe. Include the honest headline as a worked example so a reader sees the shape of the evidence.

- [ ] **Step 2: Write `docket/api/static/SKILL.md`** — a drop-in skill for a coding agent: name/description frontmatter, when to use it, the endpoint table, and worked `curl` examples for the three real workflows (find agents that actually answer; compare two agents' evidence; read the coverage before quoting any number). State the rule that a number must always be quoted with its coverage.

- [ ] **Step 3: Serve them** from `/llms.txt` (media type `text/plain`) and `/skill.md` (`text/markdown`), read from the package directory so they ship with an install.

- [ ] **Step 4: Add two tests** — `/llms.txt` returns 200 with `text/plain` and mentions every endpoint path the OpenAPI spec declares (so the doc can never silently drift from the API); `/skill.md` returns 200 and is non-empty.

- [ ] **Step 5: Run** the suite → 93 passed.

- [ ] **Step 6: Commit**

```bash
git add docket/api/static/llms.txt docket/api/static/SKILL.md docket/api/routes.py tests/test_api.py
git commit -m "feat(api): llms.txt and skill file so an agent can drive Docket unaided"
```

---

### Task 4: Serve the real data and smoke it

- [ ] **Step 1:** Run against the real store, snapshot 3 (the complete `min_feedbacks=1` sweep):

```bash
./.venv/Scripts/python -m uvicorn --factory "docket.api:create_app" --host 127.0.0.1 --port 8099
```
`create_app` needs a zero-arg default for `--factory` — default `db_path` to `data/agents.sqlite3` and `snapshot_id` to the latest complete snapshot.

- [ ] **Step 2:** Smoke every endpoint with plain `curl` (the way an evaluator would), and paste the REAL responses into the report:

```bash
curl -s localhost:8099/health
curl -s localhost:8099/stats
curl -s "localhost:8099/agents?declares_callable=true&limit=3"
curl -s "localhost:8099/agents/56:0x8004a169fb4a3325136eb29fa0ceb6d2e539a432:49637"
curl -s localhost:8099/llms.txt | head -30
```

- [ ] **Step 3:** Confirm the headline reads honestly end to end — `/stats` must show the real coverage (506 sampled of 506 expected for snapshot 3) and liveness figures that match what the store holds. If any number looks better than the truth, stop and report it.

- [ ] **Step 4: Commit** any fixes the smoke run required.

---

## Self-review (done at write time)

- Spec coverage: this is spec §4.2's "agent-facing surface" — `llms.txt` + skill file + no-auth discovery + strict schemas + actionable error codes. The human UI is Phase 1d and deliberately absent.
- Placeholders: none. Tasks 2-3 describe handlers and documents in prose, but every endpoint, parameter, field name, error code, andmedia type the tests pin is stated exactly.
- Honesty: the verdict-field ban and the coverage-on-every-statistic rule are enforced by tests, not convention; `responded_pct_of_probed` encodes its denominator in its own name.
- New dependencies are limited to the three house-pinned web packages and justified: FastAPI's auto-generated OpenAPI is what lets an evaluator's agent avoid inventing endpoints.
