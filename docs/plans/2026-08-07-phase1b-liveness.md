# Docket Phase 1b — Liveness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn "declares an endpoint" into "observably answers" — sweep the whole BSC registry, resolve real endpoint URLs for the callable subset, and probe them, so Docket can say which agents actually work instead of repeating a registry claim.

**Architecture:** Three stages over the Phase 1a store, each writing its own table so a stage can be re-run without redoing the others: full list sweep (existing `ingest_bsc`) → detail enrichment for declared-callable agents → bounded liveness probing of the resolved URLs. Probing targets third-party hosts, so it is single-attempt, rate-limited, SSRF-guarded, and records observations with timestamps — never verdicts.

**Tech Stack:** Python 3.11+, `httpx==0.28.1`, stdlib `sqlite3`/`ipaddress`/`socket`, `pytest`. No new dependencies.

## Global Constraints

- No new dependencies. `httpx==0.28.1` + stdlib only.
- Verified live 2026-08-07: the 8004scan **list** projection has 30 fields and carries `supported_protocols` but **no endpoint URLs**; the **detail** endpoint (`/agents/{chain_id}/{token_id}`) has 68 fields and is the only source of `a2a_endpoint`, `mcp_server`, `agent_url`, and `services`. Detail is therefore fetched only for the declared-callable subset, never for all 247k.
- 8004scan budget: 180 req/min, 20,000/day. A full sweep (~2,470 req) plus enrichment of the callable subset (~8,700 req) fits one day with margin. Use exactly ONE `Scan8004Client` for a stage — pacing state is per-instance.
- **Agent-declared URLs are untrusted input from a public registry.** Every probe target passes an SSRF guard before any connection: `https`/`http` scheme only, DNS resolved first, and the resolved IP rejected if it is private, loopback, link-local, reserved, or multicast. No redirects followed. This is non-negotiable.
- Probing is polite: one attempt per endpoint (no retry storms against third parties), 8-second timeout, bounded concurrency, and a `User-Agent` that identifies Docket and links to the repo.
- Liveness records **observations, not verdicts**: what happened, when, and the evidence (status code, elapsed ms, error class). No probe result may be phrased as safe/trusted/recommended — the Phase 1a test enforcing that stays green.
- Every published number stays generated from the store, never typed.
- No Claude/Anthropic attribution; no Co-Authored-By. Stage by explicit filename.
- Repo `.`, run with `./.venv/Scripts/python`. Do not push. `data/` stays gitignored.

## File Structure

```
docket/store.py        # MODIFY: add endpoints + liveness tables and their accessors
docket/enrich.py       # detail fetch for declared-callable agents -> endpoint rows
docket/netguard.py     # SSRF guard: scheme + resolved-IP validation (pure, no I/O in the check)
docket/liveness.py     # bounded, single-attempt prober -> liveness observations
tests/test_netguard.py
tests/test_enrich.py
tests/test_liveness.py
```

---

### Task 1: Endpoint + liveness tables

**Files:**
- Modify: `docket/store.py`
- Modify: `tests/test_store.py`

**Interfaces:**
- Produces on `Store`: `.upsert_endpoints(rows, snapshot_id) -> int` where each row is `{"agent_id", "kind", "url"}` (`kind` ∈ `a2a|mcp|web|service`); `.iter_endpoints(snapshot_id, kind=None) -> Iterator[dict]`; `.endpoint_count(snapshot_id) -> int`; `.record_liveness(rows) -> int` where each row is `{"snapshot_id","agent_id","url","observed_at","outcome","status_code","elapsed_ms","detail"}`; `.iter_liveness(snapshot_id) -> Iterator[dict]`; `.enriched_agent_ids(snapshot_id) -> set[str]` (for resume). Tasks 2-3 consume these.

- [ ] **Step 1: Write failing tests** — append to `tests/test_store.py`:

```python
def test_endpoints_roundtrip_and_upsert_is_idempotent(tmp_path: Path):
    store = Store(tmp_path / "d.sqlite3")
    sid = store.begin_snapshot(chain_id=56, expected=None)
    rows = [
        {"agent_id": "56:r:1", "kind": "a2a", "url": "https://a.example/agent"},
        {"agent_id": "56:r:1", "kind": "mcp", "url": "https://a.example/mcp"},
    ]
    assert store.upsert_endpoints(rows, sid) == 2
    store.upsert_endpoints(rows, sid)  # same rows again
    assert store.endpoint_count(sid) == 2  # no duplicates
    kinds = {e["kind"] for e in store.iter_endpoints(sid)}
    assert kinds == {"a2a", "mcp"}
    assert [e["url"] for e in store.iter_endpoints(sid, kind="mcp")] == ["https://a.example/mcp"]


def test_enriched_agent_ids_reports_what_has_been_processed(tmp_path: Path):
    store = Store(tmp_path / "d.sqlite3")
    sid = store.begin_snapshot(chain_id=56, expected=None)
    store.upsert_endpoints([{"agent_id": "56:r:1", "kind": "a2a", "url": "https://a/x"}], sid)
    store.mark_enriched(["56:r:1", "56:r:2"], sid)  # r:2 had no endpoints at all
    assert store.enriched_agent_ids(sid) == {"56:r:1", "56:r:2"}


def test_liveness_rows_are_append_only_observations(tmp_path: Path):
    store = Store(tmp_path / "d.sqlite3")
    sid = store.begin_snapshot(chain_id=56, expected=None)
    obs = {
        "snapshot_id": sid, "agent_id": "56:r:1", "url": "https://a/x",
        "observed_at": "2026-08-07T10:00:00+00:00", "outcome": "responded",
        "status_code": 200, "elapsed_ms": 143, "detail": None,
    }
    assert store.record_liveness([obs]) == 1
    assert store.record_liveness([{**obs, "observed_at": "2026-08-07T11:00:00+00:00",
                                   "outcome": "timeout", "status_code": None,
                                   "elapsed_ms": 8000, "detail": "ReadTimeout"}]) == 1
    seen = list(store.iter_liveness(sid))
    assert len(seen) == 2  # history is kept, not overwritten
    assert {s["outcome"] for s in seen} == {"responded", "timeout"}
```

Run: `./.venv/Scripts/python -m pytest tests/test_store.py -q` → FAIL (no such methods).

- [ ] **Step 2: Extend `SCHEMA` in `docket/store.py`** — append to the existing `SCHEMA` string:

```sql
CREATE TABLE IF NOT EXISTS endpoints (
    snapshot_id INTEGER NOT NULL,
    agent_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    url TEXT NOT NULL,
    PRIMARY KEY (snapshot_id, agent_id, kind, url)
);
CREATE TABLE IF NOT EXISTS enriched (
    snapshot_id INTEGER NOT NULL,
    agent_id TEXT NOT NULL,
    PRIMARY KEY (snapshot_id, agent_id)
);
CREATE TABLE IF NOT EXISTS liveness (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_id INTEGER NOT NULL,
    agent_id TEXT NOT NULL,
    url TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    outcome TEXT NOT NULL,
    status_code INTEGER,
    elapsed_ms INTEGER,
    detail TEXT
);
CREATE INDEX IF NOT EXISTS liveness_snapshot ON liveness (snapshot_id, agent_id);
```

- [ ] **Step 3: Add the methods to `Store`** (same style as the existing ones — `with self._conn() as conn:`, `executemany`, `ON CONFLICT DO NOTHING` for endpoints/enriched since they carry no mutable fields; plain INSERT for `liveness` because it is append-only history). `iter_endpoints` and `iter_liveness` return plain dicts via `dict(row)`.

- [ ] **Step 4: Run** `./.venv/Scripts/python -m pytest tests/test_store.py -q` → expect 8 passed (5 prior + 3 new), then full suite → 38 passed.

- [ ] **Step 5: Commit**

```bash
git add docket/store.py tests/test_store.py
git commit -m "feat(store): endpoint, enrichment and liveness tables"
```

---

### Task 2: SSRF guard

**Files:**
- Create: `docket/netguard.py`, `tests/test_netguard.py`

**Interfaces:**
- Produces: `check_url(url: str, resolver=socket.getaddrinfo) -> tuple[bool, str]` returning `(allowed, reason)`; `SAFE = "ok"`. Task 3 calls it before every probe.

**Why this exists:** probe targets come from a public registry that anyone can write to for the price of gas. Without this guard, an attacker registers an agent whose endpoint is `http://169.254.169.254/latest/meta-data/` or `http://127.0.0.1:8080/admin` and our prober becomes their request forwarder.

- [ ] **Step 1: Write the failing test `tests/test_netguard.py`**

```python
from docket.netguard import SAFE, check_url


def _resolver(ip: str):
    """Stub getaddrinfo returning one A record for the given IP."""
    def resolve(host, port, *a, **kw):
        return [(2, 1, 6, "", (ip, port or 443))]
    return resolve


def test_public_https_is_allowed():
    ok, reason = check_url("https://agent.example.com/a2a", resolver=_resolver("93.184.216.34"))
    assert ok is True and reason == SAFE


def test_loopback_is_blocked():
    ok, reason = check_url("http://localhost:8080/admin", resolver=_resolver("127.0.0.1"))
    assert ok is False and "loopback" in reason


def test_private_range_is_blocked():
    for ip in ("10.0.0.5", "192.168.1.10", "172.16.0.1"):
        ok, reason = check_url("http://internal/x", resolver=_resolver(ip))
        assert ok is False and "private" in reason


def test_cloud_metadata_address_is_blocked():
    ok, reason = check_url(
        "http://169.254.169.254/latest/meta-data/", resolver=_resolver("169.254.169.254")
    )
    assert ok is False and "link-local" in reason


def test_non_http_schemes_are_blocked():
    for url in ("file:///etc/passwd", "ftp://x/y", "gopher://x", "ws://x/y"):
        ok, reason = check_url(url, resolver=_resolver("93.184.216.34"))
        assert ok is False and "scheme" in reason


def test_unresolvable_host_is_blocked_not_crashed():
    def boom(*a, **kw):
        raise OSError("getaddrinfo failed")

    ok, reason = check_url("https://nope.invalid/x", resolver=boom)
    assert ok is False and "resolve" in reason


def test_missing_host_is_blocked():
    ok, reason = check_url("https:///nohost", resolver=_resolver("93.184.216.34"))
    assert ok is False and "host" in reason


def test_all_resolved_ips_must_be_public():
    """A host resolving to both a public and a private IP is rejected."""
    def dual(host, port, *a, **kw):
        return [(2, 1, 6, "", ("93.184.216.34", 443)), (2, 1, 6, "", ("127.0.0.1", 443))]

    ok, reason = check_url("https://sneaky.example/x", resolver=dual)
    assert ok is False
```

- [ ] **Step 2: Write `docket/netguard.py`**

```python
"""SSRF guard for probe targets.

Endpoint URLs come from a public on-chain registry that anyone can write to.
Before any probe we require an http(s) scheme and confirm that EVERY address the
host resolves to is publicly routable — a host resolving to both a public and a
private address is rejected, since we cannot control which one a later connect
would pick.
"""

import ipaddress
import socket
from urllib.parse import urlsplit

SAFE = "ok"
_ALLOWED_SCHEMES = {"http", "https"}


def _classify(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> str | None:
    if ip.is_loopback:
        return "loopback address"
    if ip.is_link_local:
        return "link-local address"
    if ip.is_private:
        return "private address"
    if ip.is_reserved:
        return "reserved address"
    if ip.is_multicast:
        return "multicast address"
    if ip.is_unspecified:
        return "unspecified address"
    return None


def check_url(url: str, resolver=socket.getaddrinfo) -> tuple[bool, str]:
    parts = urlsplit(url or "")
    if parts.scheme not in _ALLOWED_SCHEMES:
        return False, f"blocked scheme: {parts.scheme or '(none)'}"
    if not parts.hostname:
        return False, "no host in url"
    port = parts.port or (443 if parts.scheme == "https" else 80)
    try:
        infos = resolver(parts.hostname, port, 0, socket.SOCK_STREAM)
    except Exception as exc:  # DNS failure, bad host, anything
        return False, f"could not resolve host: {type(exc).__name__}"
    if not infos:
        return False, "could not resolve host: no records"
    for info in infos:
        addr = info[4][0]
        try:
            ip = ipaddress.ip_address(addr)
        except ValueError:
            return False, f"unparseable address: {addr}"
        bad = _classify(ip)
        if bad:
            return False, bad
    return True, SAFE
```

- [ ] **Step 3: Run** `./.venv/Scripts/python -m pytest tests/test_netguard.py -q` → expect 8 passed.

- [ ] **Step 4: Commit**

```bash
git add docket/netguard.py tests/test_netguard.py
git commit -m "feat(netguard): SSRF guard for registry-supplied probe targets"
```

---

### Task 3: Detail enrichment

**Files:**
- Create: `docket/enrich.py`, `tests/test_enrich.py`

**Interfaces:**
- Consumes: `Store` (Task 1), `Scan8004Client.get_agent`.
- Produces: `extract_endpoints(detail: dict) -> list[dict]` (pure — `[{"kind","url"}]`), and `enrich_callable(store, client, snapshot_id, *, limit=None) -> dict` returning `{"considered","fetched","with_endpoints","endpoints","skipped_already_enriched"}`.

**Selection rule:** only agents whose stored `supported_protocols` contain `A2A` or `MCP` are enriched. That subset is ~3.6% of the registry, which is what makes this affordable. Agents already in `enriched` are skipped, so the stage is resumable.

- [ ] **Step 1: Write the failing test `tests/test_enrich.py`**

```python
import httpx

from docket.enrich import enrich_callable, extract_endpoints
from docket.scan8004 import Scan8004Client
from docket.store import Store

DETAIL = {
    "a2a_endpoint": "https://a.example/a2a",
    "mcp_server": "https://a.example/mcp",
    "agent_url": "https://a.example",
    "services": {"oasf": {"endpoint": "https://a.example/oasf"}},
}


def test_extract_endpoints_reads_every_shape():
    got = {(e["kind"], e["url"]) for e in extract_endpoints(DETAIL)}
    assert ("a2a", "https://a.example/a2a") in got
    assert ("mcp", "https://a.example/mcp") in got
    assert ("web", "https://a.example") in got
    assert ("service", "https://a.example/oasf") in got


def test_extract_endpoints_ignores_nulls_and_blanks():
    assert extract_endpoints({"a2a_endpoint": None, "mcp_server": "", "agent_url": "   "}) == []


def test_extract_endpoints_survives_unexpected_services_shapes():
    for services in (None, [], "nope", {"x": None}, {"x": {"endpoint": None}}, {"x": "str"}):
        assert isinstance(extract_endpoints({"services": services}), list)


def _store_with(agents, tmp_path):
    store = Store(tmp_path / "d.sqlite3")
    sid = store.begin_snapshot(chain_id=56, expected=None)
    store.upsert_agents(agents, sid)
    return store, sid


def test_only_declared_callable_agents_are_fetched(tmp_path):
    agents = [
        {"agent_id": "56:r:1", "token_id": "1", "chain_id": 56, "supported_protocols": ["A2A"]},
        {"agent_id": "56:r:2", "token_id": "2", "chain_id": 56, "supported_protocols": ["Web"]},
        {"agent_id": "56:r:3", "token_id": "3", "chain_id": 56, "supported_protocols": []},
        {"agent_id": "56:r:4", "token_id": "4", "chain_id": 56, "supported_protocols": ["MCP"]},
    ]
    store, sid = _store_with(agents, tmp_path)
    fetched = []

    def handler(request: httpx.Request) -> httpx.Response:
        fetched.append(str(request.url).rsplit("/", 1)[-1])
        return httpx.Response(200, json=DETAIL)

    client = Scan8004Client(transport=httpx.MockTransport(handler), pace=False)
    result = enrich_callable(store, client, sid)
    assert sorted(fetched) == ["1", "4"]  # Web-only and empty are not fetched
    assert result["considered"] == 2 and result["fetched"] == 2
    assert store.endpoint_count(sid) == 8  # 4 endpoints x 2 agents


def test_rerun_skips_already_enriched(tmp_path):
    agents = [{"agent_id": "56:r:1", "token_id": "1", "chain_id": 56, "supported_protocols": ["A2A"]}]
    store, sid = _store_with(agents, tmp_path)
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(200, json=DETAIL)

    client = Scan8004Client(transport=httpx.MockTransport(handler), pace=False)
    enrich_callable(store, client, sid)
    second = enrich_callable(store, client, sid)
    assert calls["n"] == 1  # not re-fetched
    assert second["skipped_already_enriched"] == 1


def test_agent_with_no_endpoints_is_still_marked_enriched(tmp_path):
    agents = [{"agent_id": "56:r:1", "token_id": "1", "chain_id": 56, "supported_protocols": ["A2A"]}]
    store, sid = _store_with(agents, tmp_path)
    client = Scan8004Client(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json={})), pace=False
    )
    result = enrich_callable(store, client, sid)
    assert result["with_endpoints"] == 0
    assert store.enriched_agent_ids(sid) == {"56:r:1"}  # so a re-run does not refetch it
```

- [ ] **Step 2: Write `docket/enrich.py`.** `extract_endpoints` reads `a2a_endpoint` → kind `a2a`, `mcp_server` → `mcp`, `agent_url` → `web`, and any `services[*]["endpoint"]` → `service`; it strips whitespace, skips falsy values, and must not raise on any unexpected `services` shape (the test pins six of them). `enrich_callable` selects declared-callable agents via `signals_for(agent)["callable"]` from Phase 1a, skips `store.enriched_agent_ids(snapshot_id)`, calls `client.get_agent(chain_id, token_id)` per agent, upserts extracted endpoints, and calls `store.mark_enriched([...], snapshot_id)` — marking on every fetched agent including those with zero endpoints, so re-runs converge. Respect `limit` for bounded runs. Fully drain any `iter_agents` generator before starting network calls (Phase 1a carry-forward: a suspended generator holds a connection).

- [ ] **Step 3: Run** `./.venv/Scripts/python -m pytest tests/test_enrich.py -q` → expect 6 passed.

- [ ] **Step 4: Commit**

```bash
git add docket/enrich.py tests/test_enrich.py
git commit -m "feat(enrich): resolve real endpoint URLs for declared-callable agents"
```

---

### Task 4: Liveness prober

**Files:**
- Create: `docket/liveness.py`, `tests/test_liveness.py`

**Interfaces:**
- Consumes: `Store` (Task 1), `check_url` (Task 2).
- Produces: `OUTCOMES` (frozenset), `probe_one(client, endpoint, *, now) -> dict`, `probe_snapshot(store, snapshot_id, *, client=None, limit=None, kinds=("a2a","mcp")) -> dict` returning `{"probed","responded","blocked","failed"}`.

**Outcome vocabulary** (exactly these, no others): `responded` (HTTP response received, any status), `timeout`, `refused` (connection error), `blocked` (SSRF guard rejected — never connected), `error` (anything else). Every row stores the status code where one exists, elapsed ms, and an error class name in `detail`. None of these words is a verdict about the agent.

- [ ] **Step 1: Write the failing test `tests/test_liveness.py`**

```python
import httpx

from docket.liveness import OUTCOMES, probe_snapshot
from docket.store import Store


def _seed(tmp_path, urls):
    store = Store(tmp_path / "d.sqlite3")
    sid = store.begin_snapshot(chain_id=56, expected=None)
    store.upsert_endpoints(
        [{"agent_id": f"56:r:{i}", "kind": "a2a", "url": u} for i, u in enumerate(urls)], sid
    )
    return store, sid


def _client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_outcome_vocabulary_is_closed():
    assert OUTCOMES == frozenset({"responded", "timeout", "refused", "blocked", "error"})


def test_responded_records_status_and_elapsed(tmp_path):
    store, sid = _seed(tmp_path, ["https://ok.example/a2a"])
    with _client(lambda r: httpx.Response(200, json={"ok": True})) as c:
        result = probe_snapshot(store, sid, client=c, resolver=_public)
    assert result["responded"] == 1
    row = next(iter(store.iter_liveness(sid)))
    assert row["outcome"] == "responded" and row["status_code"] == 200
    assert row["elapsed_ms"] is not None and row["observed_at"]


def test_non_2xx_still_counts_as_responded(tmp_path):
    """A 404 proves the host is up; it is an observation, not a judgement."""
    store, sid = _seed(tmp_path, ["https://ok.example/a2a"])
    with _client(lambda r: httpx.Response(404)) as c:
        probe_snapshot(store, sid, client=c, resolver=_public)
    row = next(iter(store.iter_liveness(sid)))
    assert row["outcome"] == "responded" and row["status_code"] == 404


def test_ssrf_blocked_target_is_never_connected(tmp_path):
    store, sid = _seed(tmp_path, ["http://127.0.0.1:8080/admin"])
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return httpx.Response(200)

    with _client(handler) as c:
        result = probe_snapshot(store, sid, client=c, resolver=_loopback)
    assert calls["n"] == 0  # the guard ran before any request
    assert result["blocked"] == 1
    row = next(iter(store.iter_liveness(sid)))
    assert row["outcome"] == "blocked" and "loopback" in (row["detail"] or "")


def test_timeout_and_refused_are_distinguished(tmp_path):
    store, sid = _seed(tmp_path, ["https://a.example/1", "https://b.example/2"])

    def handler(request):
        if request.url.host == "a.example":
            raise httpx.ReadTimeout("too slow", request=request)
        raise httpx.ConnectError("refused", request=request)

    with _client(handler) as c:
        probe_snapshot(store, sid, client=c, resolver=_public)
    outcomes = {r["outcome"] for r in store.iter_liveness(sid)}
    assert outcomes == {"timeout", "refused"}


def _public(host, port, *a, **kw):
    return [(2, 1, 6, "", ("93.184.216.34", port or 443))]


def _loopback(host, port, *a, **kw):
    return [(2, 1, 6, "", ("127.0.0.1", port or 80))]
```

- [ ] **Step 2: Write `docket/liveness.py`.** `probe_snapshot` pulls endpoints of the requested `kinds` from the store, calls `check_url(url, resolver=resolver)` on each; on rejection it records `blocked` with the guard's reason in `detail` and **makes no request**. Otherwise it issues a single `GET` with `timeout=8.0`, `follow_redirects=False`, and headers `{"user-agent": "Docket/0.1 (+https://github.com/Ridwannurudeen/docket)", "accept": "application/json"}`, timing it with `time.monotonic()`. Map `httpx.TimeoutException` → `timeout`, `httpx.ConnectError` → `refused`, other `httpx.HTTPError` → `error`. One attempt per endpoint — no retries against third parties. Pace requests so no single host is hit more than once per second. Batch results into `store.record_liveness(...)`. Accept an injected `client` and `resolver` for hermetic tests; default to a real `httpx.Client` and `socket.getaddrinfo`.

- [ ] **Step 3: Run** `./.venv/Scripts/python -m pytest tests/test_liveness.py -q` → expect 5 passed. Full suite → 57 passed (38 + 8 netguard + 6 enrich + 5 liveness).

- [ ] **Step 4: Commit**

```bash
git add docket/liveness.py tests/test_liveness.py
git commit -m "feat(liveness): SSRF-guarded single-attempt endpoint probing"
```

---

### Task 5: Run the real pipeline and extend the coverage report

**Files:**
- Modify: `docket/coverage.py`, `tests/test_coverage.py`

- [ ] **Step 1:** Extend `coverage_report` with liveness figures computed from the store — `endpoints_resolved`, `agents_probed`, `agents_responded`, `responded_pct` (share of probed, not of the registry), and `blocked` — plus a `liveness_observed_at` window. Add a test seeding liveness rows and asserting the arithmetic, including that `responded_pct` divides by probed and not by `sampled`. Extend `render_markdown` with a liveness section that states the probe method in one line (single attempt, 8s timeout, no redirects, SSRF-guarded) so a reader knows exactly what the number means.

- [ ] **Step 2: Run the real full sweep** (read-only, ~2,470 requests, ~16 min):

```bash
./.venv/Scripts/python - << 'PY'
from docket.ingest import ingest_bsc
from docket.scan8004 import Scan8004Client
from docket.store import Store
store = Store("data/agents.sqlite3")
with Scan8004Client() as client:
    print(ingest_bsc(store, client))
PY
```

- [ ] **Step 3: Run enrichment** over the declared-callable subset for that snapshot (bounded to `limit=2000` on the first run so a mistake is cheap; report the real counts).

- [ ] **Step 4: Run liveness** over the resolved `a2a`/`mcp` endpoints (`limit=500` on the first run).

- [ ] **Step 5:** Regenerate the coverage report and paste the REAL rendered markdown into the report file. Write it to disk with `encoding="utf-8"` explicitly — this machine defaults to cp1252 and will mangle the em dash. Commit only code and tests; `data/` stays gitignored.

- [ ] **Step 6: Commit**

```bash
git add docket/coverage.py tests/test_coverage.py
git commit -m "feat(coverage): liveness figures with stated probe method"
```

---

## Self-review (done at write time)

- Spec coverage: spec §4.1's "endpoint liveness probes" and the honest-metrics requirement are covered by Tasks 2-5; the full sweep in Task 5 dissolves Phase 1a's ordered-sample caveat.
- Placeholders: none. Tasks 3-4 describe their modules in prose rather than pasting full bodies, but every interface, outcome value, header, timeout, and edge case the tests pin is stated exactly.
- Security: the SSRF guard is its own task with its own tests, and Task 4's tests prove no request is issued for a blocked target.
- Honesty: `responded_pct` is explicitly a share of probed endpoints, never of the registry — the most likely place a misleading headline number could appear.
