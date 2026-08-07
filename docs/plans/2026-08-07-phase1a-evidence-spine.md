# Docket Phase 1a — Evidence Spine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce a real, dated, reproducible dataset of every BSC ERC-8004 agent with deterministic quality signals computed over it — the factual base for Docket's "Data Quality" differentiator and for every listing page built later.

**Architecture:** A thin typed 8004scan client feeds a snapshot-based SQLite store; pure-function signals are computed over stored rows (no network), so they are unit-testable and re-runnable; a generator emits the honest coverage numbers as JSON + Markdown. Nothing in this phase renders UI or touches a chain.

**Tech Stack:** Python 3.11+, `httpx==0.28.1` (already pinned), stdlib `sqlite3`, `pytest`. No new dependencies.

## Global Constraints

- No new dependencies. `httpx==0.28.1` and stdlib only. Do not add pandas, sqlalchemy, requests, or an ORM.
- 8004scan internal API base: `https://8004scan.io/api/v1`. Verified live 2026-08-07: rate limits `X-Ratelimit-Limit-Minute: 180`, `X-Ratelimit-Limit-Day: 20000`; `limit` max 100; params are **snake_case** (`chain_id`, `min_feedbacks`, `min_score`, `sort_by`, `sort_order`, `offset`, `limit`, `search`, `owner_address`, `x402_supported`, `is_testnet`, `is_active`).
- BSC mainnet is `chain_id=56`. Never ingest testnet into the same snapshot.
- **Local DNS is intermittently flaky** (verified: `getaddrinfo failed` from httpx, same URL fine seconds later). Every network call retries with backoff on transport errors.
- **Every published number is generated, never typed.** The coverage report is emitted by code from the store; no statistic is hand-written into prose anywhere.
- Honest coverage semantics: report what was actually stored (`sampled`), what the API claimed existed (`expected`), and `dropped = max(expected - sampled, 0)`. A mismatch is rendered as partial, never silently rounded away.
- No agent is described as "verified", "trusted", or "safe" by Docket. Signals are factual observations (has feedback / declares a protocol / shares a bulk-mint pattern), never a safety claim.
- No Claude/Anthropic attribution; no Co-Authored-By.
- Repo: `C:\Users\gudma\OneDrive\Desktop\GITHUB-FILES\docket`. Run everything with `./.venv/Scripts/python` (Git Bash on Windows). Do not push.

## File Structure

```
docket/__init__.py          # package marker
docket/scan8004.py          # typed 8004scan client: retry, rate-limit pacing, pagination
docket/store.py             # SQLite schema + upsert + snapshot bookkeeping
docket/ingest.py            # full BSC sweep, resumable, drift-safe
docket/signals.py           # pure per-agent signal functions (no network)
docket/coverage.py          # generated honest-numbers report (JSON + Markdown)
tests/test_scan8004.py      # client behavior against recorded fixtures (no live network)
tests/test_store.py         # schema, upsert idempotency, snapshot bookkeeping
tests/test_signals.py       # every signal, both directions
tests/test_coverage.py      # report arithmetic incl. partial/dropped case
```

Adding `docket/` makes this a two-package flat layout (`docket` + `experiments`), which triggers setuptools' "Multiple top-level packages discovered" error — Task 1 fixes that, closing a deferred minor from Phase 0.

---

### Task 1: Store + packaging fix

**Files:**
- Create: `docket/__init__.py`, `docket/store.py`, `tests/test_store.py`
- Modify: `pyproject.toml` (add `[build-system]` + explicit packages)

**Interfaces:**
- Produces: `Store` class with `Store(path)`, `.upsert_agents(rows: list[dict], snapshot_id: int) -> int`, `.begin_snapshot(chain_id: int, expected: int|None) -> int`, `.finish_snapshot(snapshot_id, sampled: int) -> None`, `.agent_count(snapshot_id=None) -> int`, `.iter_agents(snapshot_id=None) -> Iterator[dict]`. Tasks 2-4 consume all of these.

- [ ] **Step 1: Fix packaging in `pyproject.toml`**

Add after the `[project.optional-dependencies]` block:

```toml
[build-system]
requires = ["setuptools>=61"]
build-backend = "setuptools.build_meta"

[tool.setuptools]
packages = ["docket", "experiments"]
```

- [ ] **Step 2: Write the failing test `tests/test_store.py`**

```python
import sqlite3
from pathlib import Path

from docket.store import Store

ROW = {
    "agent_id": "56:0x8004a169fb4a3325136eb29fa0ceb6d2e539a432:136384",
    "token_id": "136384",
    "chain_id": 56,
    "contract_address": "0x8004a169fb4a3325136eb29fa0ceb6d2e539a432",
    "owner_address": "0xe4fe23fb57dbb9ac2f685ea29b6b9a1409a0d359",
    "name": "Agent #136384",
    "description": None,
    "supported_protocols": [],
    "x402_supported": True,
    "is_verified": False,
    "total_feedbacks": 0,
    "total_score": 0.0,
    "created_at": "2026-06-16T15:03:30Z",
}


def test_snapshot_roundtrip(tmp_path: Path):
    store = Store(tmp_path / "d.sqlite3")
    sid = store.begin_snapshot(chain_id=56, expected=243421)
    assert store.upsert_agents([ROW], sid) == 1
    store.finish_snapshot(sid, sampled=1)
    assert store.agent_count(sid) == 1
    got = next(store.iter_agents(sid))
    assert got["agent_id"] == ROW["agent_id"]
    assert got["supported_protocols"] == []  # round-trips as a list, not a JSON string
    assert got["x402_supported"] is True     # round-trips as bool, not 0/1


def test_upsert_is_idempotent_and_updates(tmp_path: Path):
    store = Store(tmp_path / "d.sqlite3")
    sid = store.begin_snapshot(chain_id=56, expected=None)
    store.upsert_agents([ROW], sid)
    store.upsert_agents([{**ROW, "name": "SOLVENT", "total_feedbacks": 3}], sid)
    assert store.agent_count(sid) == 1          # no duplicate row
    got = next(store.iter_agents(sid))
    assert got["name"] == "SOLVENT"             # latest write wins
    assert got["total_feedbacks"] == 3


def test_snapshot_records_partial_coverage(tmp_path: Path):
    store = Store(tmp_path / "d.sqlite3")
    sid = store.begin_snapshot(chain_id=56, expected=100)
    store.upsert_agents([ROW], sid)
    store.finish_snapshot(sid, sampled=1)
    with sqlite3.connect(tmp_path / "d.sqlite3") as conn:
        row = conn.execute(
            "SELECT expected, sampled, finished_at FROM snapshots WHERE id = ?", (sid,)
        ).fetchone()
    assert row[0] == 100 and row[1] == 1 and row[2] is not None
```

Run: `./.venv/Scripts/python -m pytest tests/test_store.py -q` → Expected: FAIL (no module named docket).

- [ ] **Step 3: Write `docket/__init__.py` (empty) and `docket/store.py`**

```python
"""SQLite store for 8004scan agent snapshots.

A snapshot is one ingestion run: it records what the API claimed existed
(`expected`) alongside what we actually stored (`sampled`), so every number
Docket publishes can state its own coverage instead of implying completeness.
"""

import json
import sqlite3
from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chain_id INTEGER NOT NULL,
    expected INTEGER,
    sampled INTEGER,
    started_at TEXT NOT NULL,
    finished_at TEXT
);
CREATE TABLE IF NOT EXISTS agents (
    snapshot_id INTEGER NOT NULL,
    agent_id TEXT NOT NULL,
    token_id TEXT NOT NULL,
    chain_id INTEGER NOT NULL,
    contract_address TEXT,
    owner_address TEXT,
    name TEXT,
    description TEXT,
    supported_protocols TEXT NOT NULL DEFAULT '[]',
    x402_supported INTEGER NOT NULL DEFAULT 0,
    is_verified INTEGER NOT NULL DEFAULT 0,
    total_feedbacks INTEGER NOT NULL DEFAULT 0,
    total_score REAL NOT NULL DEFAULT 0,
    created_at TEXT,
    PRIMARY KEY (snapshot_id, agent_id)
);
CREATE INDEX IF NOT EXISTS agents_owner ON agents (snapshot_id, owner_address);
CREATE INDEX IF NOT EXISTS agents_token ON agents (snapshot_id, token_id);
"""

_COLUMNS = (
    "agent_id token_id chain_id contract_address owner_address name description "
    "supported_protocols x402_supported is_verified total_feedbacks total_score created_at"
).split()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Store:
    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as conn:
            conn.executescript(SCHEMA)

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def begin_snapshot(self, chain_id: int, expected: int | None) -> int:
        with self._conn() as conn:
            cur = conn.execute(
                "INSERT INTO snapshots (chain_id, expected, started_at) VALUES (?, ?, ?)",
                (chain_id, expected, _now()),
            )
            return int(cur.lastrowid)

    def finish_snapshot(self, snapshot_id: int, sampled: int) -> None:
        with self._conn() as conn:
            conn.execute(
                "UPDATE snapshots SET sampled = ?, finished_at = ? WHERE id = ?",
                (sampled, _now(), snapshot_id),
            )

    def upsert_agents(self, rows: list[dict], snapshot_id: int) -> int:
        payload = []
        for r in rows:
            payload.append(
                (
                    snapshot_id,
                    r["agent_id"],
                    str(r.get("token_id") or ""),
                    int(r.get("chain_id") or 0),
                    r.get("contract_address"),
                    (r.get("owner_address") or "").lower() or None,
                    r.get("name"),
                    r.get("description"),
                    json.dumps(r.get("supported_protocols") or []),
                    1 if r.get("x402_supported") else 0,
                    1 if r.get("is_verified") else 0,
                    int(r.get("total_feedbacks") or 0),
                    float(r.get("total_score") or 0),
                    r.get("created_at"),
                )
            )
        with self._conn() as conn:
            conn.executemany(
                """INSERT INTO agents
                   (snapshot_id, agent_id, token_id, chain_id, contract_address,
                    owner_address, name, description, supported_protocols,
                    x402_supported, is_verified, total_feedbacks, total_score, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT (snapshot_id, agent_id) DO UPDATE SET
                     name = excluded.name,
                     description = excluded.description,
                     supported_protocols = excluded.supported_protocols,
                     x402_supported = excluded.x402_supported,
                     is_verified = excluded.is_verified,
                     total_feedbacks = excluded.total_feedbacks,
                     total_score = excluded.total_score""",
                payload,
            )
        return len(payload)

    def latest_snapshot_id(self, chain_id: int = 56) -> int | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT id FROM snapshots WHERE chain_id = ? ORDER BY id DESC LIMIT 1",
                (chain_id,),
            ).fetchone()
        return int(row["id"]) if row else None

    def snapshot(self, snapshot_id: int) -> dict:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM snapshots WHERE id = ?", (snapshot_id,)
            ).fetchone()
        return dict(row) if row else {}

    def agent_count(self, snapshot_id: int | None = None) -> int:
        with self._conn() as conn:
            if snapshot_id is None:
                row = conn.execute("SELECT COUNT(*) AS n FROM agents").fetchone()
            else:
                row = conn.execute(
                    "SELECT COUNT(*) AS n FROM agents WHERE snapshot_id = ?", (snapshot_id,)
                ).fetchone()
        return int(row["n"])

    def max_token_id(self, snapshot_id: int) -> int:
        """Highest numeric token_id stored — the resume point for an ascending sweep."""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT MAX(CAST(token_id AS INTEGER)) AS m FROM agents WHERE snapshot_id = ?",
                (snapshot_id,),
            ).fetchone()
        return int(row["m"] or 0)

    def iter_agents(self, snapshot_id: int | None = None) -> Iterator[dict]:
        sql = "SELECT * FROM agents"
        args: tuple = ()
        if snapshot_id is not None:
            sql += " WHERE snapshot_id = ?"
            args = (snapshot_id,)
        sql += " ORDER BY CAST(token_id AS INTEGER)"
        with self._conn() as conn:
            for row in conn.execute(sql, args):
                d = dict(row)
                d["supported_protocols"] = json.loads(d["supported_protocols"])
                d["x402_supported"] = bool(d["x402_supported"])
                d["is_verified"] = bool(d["is_verified"])
                yield d
```

- [ ] **Step 4: Run the tests**

```bash
cd "C:/Users/gudma/OneDrive/Desktop/GITHUB-FILES/docket"
./.venv/Scripts/python -m pip install -e ".[dev]"
./.venv/Scripts/python -m pytest tests/test_store.py -q
```
Expected: 3 passed. Then the full suite: `./.venv/Scripts/python -m pytest -q` → 11 passed (8 prior + 3).

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml docket/__init__.py docket/store.py tests/test_store.py
git commit -m "feat(store): snapshot-based SQLite store for 8004scan agents"
```

---

### Task 2: 8004scan client

**Files:**
- Create: `docket/scan8004.py`, `tests/test_scan8004.py`

**Interfaces:**
- Consumes: nothing from Task 1 (pure client).
- Produces: `Scan8004Client(base_url=API_BASE, transport=None)` with `.list_agents(chain_id: int, *, limit: int = 100, offset: int = 0, min_feedbacks: int | None = None, sort_by: str = "token_id", sort_order: str = "asc") -> tuple[list[dict], int]` returning `(items, total)`, and `.get_agent(chain_id: int, token_id: str) -> dict`. Task 3 consumes `.list_agents`.

- [ ] **Step 1: Write the failing test `tests/test_scan8004.py`**

Tests use `httpx.MockTransport` — no live network, so they are deterministic and CI-safe.

```python
import httpx
import pytest

from docket.scan8004 import API_BASE, Scan8004Client


def _client(handler) -> Scan8004Client:
    return Scan8004Client(transport=httpx.MockTransport(handler))


def test_list_agents_sends_snake_case_params_and_returns_total():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(dict(request.url.params))
        return httpx.Response(200, json={"items": [{"agent_id": "a"}], "total": 42})

    items, total = _client(handler).list_agents(56, limit=100, offset=200, min_feedbacks=1)
    assert items == [{"agent_id": "a"}]
    assert total == 42
    assert seen["chain_id"] == "56"
    assert seen["limit"] == "100"
    assert seen["offset"] == "200"
    assert seen["min_feedbacks"] == "1"
    assert seen["sort_by"] == "token_id"
    assert seen["sort_order"] == "asc"


def test_limit_is_capped_at_100():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["limit"] == "100"
        return httpx.Response(200, json={"items": [], "total": 0})

    _client(handler).list_agents(56, limit=5000)


def test_retries_transport_errors_then_succeeds():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] < 3:
            raise httpx.ConnectError("getaddrinfo failed", request=request)
        return httpx.Response(200, json={"items": [], "total": 0})

    items, total = _client(handler).list_agents(56)
    assert calls["n"] == 3 and items == [] and total == 0


def test_gives_up_after_max_attempts():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("getaddrinfo failed", request=request)

    with pytest.raises(httpx.ConnectError):
        _client(handler).list_agents(56)


def test_retries_429_then_succeeds():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, json={"detail": "slow down"})
        return httpx.Response(200, json={"items": [], "total": 7})

    _, total = _client(handler).list_agents(56)
    assert calls["n"] == 2 and total == 7


def test_api_base_is_the_internal_endpoint():
    assert API_BASE == "https://8004scan.io/api/v1"
```

Run: `./.venv/Scripts/python -m pytest tests/test_scan8004.py -q` → Expected: FAIL (no module).

- [ ] **Step 2: Write `docket/scan8004.py`**

```python
"""Client for 8004scan's internal API.

Two APIs exist on 8004scan with incompatible conventions. This targets the
internal one (`/api/v1`, snake_case params, 180 req/min + 20k/day, no key),
because it is the only one exposing `min_feedbacks`/`min_score` and it carries
18x the anonymous quota of the documented public API. Verified 2026-08-07.

Not used deliberately: `/agents/search` (returns 502) and `/feedbacks?tokenId=`
(silently ignores the filter).
"""

import time

import httpx

API_BASE = "https://8004scan.io/api/v1"
MAX_LIMIT = 100
MAX_ATTEMPTS = 4
BACKOFF_S = (1.0, 3.0, 8.0)
# 180 req/min ceiling; pace below it so a long sweep never trips the limiter.
MIN_INTERVAL_S = 0.4


class Scan8004Client:
    def __init__(
        self,
        base_url: str = API_BASE,
        transport: httpx.BaseTransport | None = None,
        pace: bool = True,
    ) -> None:
        self._client = httpx.Client(
            base_url=base_url,
            transport=transport,
            timeout=30.0,
            headers={"accept": "application/json"},
        )
        self._pace = pace
        self._last_call = 0.0

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "Scan8004Client":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def _throttle(self) -> None:
        if not self._pace:
            return
        elapsed = time.monotonic() - self._last_call
        if elapsed < MIN_INTERVAL_S:
            time.sleep(MIN_INTERVAL_S - elapsed)
        self._last_call = time.monotonic()

    def _get(self, path: str, params: dict) -> dict:
        last: Exception | None = None
        for attempt in range(MAX_ATTEMPTS):
            self._throttle()
            try:
                resp = self._client.get(path, params=params)
                if resp.status_code == 429 or resp.status_code >= 500:
                    last = httpx.HTTPStatusError(
                        f"{resp.status_code} from {path}", request=resp.request, response=resp
                    )
                else:
                    resp.raise_for_status()
                    return resp.json()
            except httpx.TransportError as exc:
                last = exc
            if attempt < MAX_ATTEMPTS - 1:
                time.sleep(BACKOFF_S[min(attempt, len(BACKOFF_S) - 1)])
        raise last  # type: ignore[misc]

    def list_agents(
        self,
        chain_id: int,
        *,
        limit: int = MAX_LIMIT,
        offset: int = 0,
        min_feedbacks: int | None = None,
        sort_by: str = "token_id",
        sort_order: str = "asc",
    ) -> tuple[list[dict], int]:
        params: dict[str, object] = {
            "chain_id": chain_id,
            "limit": min(limit, MAX_LIMIT),
            "offset": offset,
            "sort_by": sort_by,
            "sort_order": sort_order,
        }
        if min_feedbacks is not None:
            params["min_feedbacks"] = min_feedbacks
        data = self._get("/agents", params)
        return list(data.get("items") or []), int(data.get("total") or 0)

    def get_agent(self, chain_id: int, token_id: str) -> dict:
        return self._get(f"/agents/{chain_id}/{token_id}", {})
```

- [ ] **Step 3: Run the tests**

```bash
./.venv/Scripts/python -m pytest tests/test_scan8004.py -q
```
Expected: 6 passed. (`test_gives_up_after_max_attempts` sleeps ~12s from the backoff — acceptable; do not shorten `BACKOFF_S` to make the test faster, pass `pace=False` if a future test needs speed.)

- [ ] **Step 4: Commit**

```bash
git add docket/scan8004.py tests/test_scan8004.py
git commit -m "feat(scan8004): internal-API client with backoff and rate pacing"
```

---

### Task 3: Drift-safe ingestion

**Files:**
- Create: `docket/ingest.py`, `tests/test_ingest.py`

**Interfaces:**
- Consumes: `Store` (Task 1), `Scan8004Client` (Task 2).
- Produces: `ingest_bsc(store: Store, client: Scan8004Client, *, chain_id: int = 56, max_pages: int | None = None, snapshot_id: int | None = None) -> dict` returning `{"snapshot_id": int, "sampled": int, "expected": int, "dropped": int, "pages": int}`. Task 4 reads the resulting snapshot.

**Why ascending token_id, not plain offset:** the registry grows ~3,500 agents/day (verified: newest token_id moved 254,408 → 257,920 within one day). A full sweep takes minutes, so descending/`created_at` ordering shifts rows under the paginator and silently skips agents. Ascending `token_id` appends new rows *after* the cursor, so a sweep sees a stable prefix; the upsert primary key absorbs any overlap.

- [ ] **Step 1: Write the failing test `tests/test_ingest.py`**

```python
import httpx

from docket.ingest import ingest_bsc
from docket.scan8004 import Scan8004Client
from docket.store import Store


def _row(token: int) -> dict:
    return {
        "agent_id": f"56:0xreg:{token}",
        "token_id": str(token),
        "chain_id": 56,
        "name": f"Agent #{token}",
        "supported_protocols": [],
        "total_feedbacks": 0,
        "total_score": 0.0,
    }


def _paged_handler(total: int, page_size: int, grow_by: int = 0):
    """Serves `total` rows page by page; `grow_by` simulates the registry growing mid-sweep."""
    state = {"total": total, "calls": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        state["calls"] += 1
        offset = int(request.url.params["offset"])
        limit = int(request.url.params["limit"])
        if state["calls"] == 2:
            state["total"] += grow_by
        items = [_row(t) for t in range(offset, min(offset + limit, total))]
        return httpx.Response(200, json={"items": items, "total": state["total"]})

    return handler


def test_ingests_every_page_and_records_coverage(tmp_path):
    store = Store(tmp_path / "d.sqlite3")
    client = Scan8004Client(transport=httpx.MockTransport(_paged_handler(250, 100)), pace=False)
    result = ingest_bsc(store, client)
    assert result["sampled"] == 250
    assert result["expected"] == 250
    assert result["dropped"] == 0
    assert store.agent_count(result["snapshot_id"]) == 250


def test_growth_during_sweep_is_reported_as_dropped_not_hidden(tmp_path):
    store = Store(tmp_path / "d.sqlite3")
    # 250 rows are servable, but the API's reported total grows to 300 mid-sweep.
    client = Scan8004Client(
        transport=httpx.MockTransport(_paged_handler(250, 100, grow_by=50)), pace=False
    )
    result = ingest_bsc(store, client)
    assert result["sampled"] == 250
    assert result["expected"] == 300
    assert result["dropped"] == 50  # surfaced, never silently rounded away


def test_max_pages_bounds_the_sweep(tmp_path):
    store = Store(tmp_path / "d.sqlite3")
    client = Scan8004Client(transport=httpx.MockTransport(_paged_handler(1000, 100)), pace=False)
    result = ingest_bsc(store, client, max_pages=2)
    assert result["pages"] == 2
    assert result["sampled"] == 200


def test_duplicate_rows_across_pages_do_not_inflate_the_count(tmp_path):
    store = Store(tmp_path / "d.sqlite3")

    def handler(request: httpx.Request) -> httpx.Response:
        # Every page returns the same 10 rows — a pathological paginator.
        return httpx.Response(
            200, json={"items": [_row(t) for t in range(10)], "total": 30}
        )

    client = Scan8004Client(transport=httpx.MockTransport(handler), pace=False)
    result = ingest_bsc(store, client, max_pages=3)
    assert store.agent_count(result["snapshot_id"]) == 10
    assert result["sampled"] == 10  # counted from the store, not from pages served
```

Run it → Expected: FAIL (no module).

- [ ] **Step 2: Write `docket/ingest.py`**

```python
"""Full-registry sweep of BSC ERC-8004 agents into a dated snapshot.

Ordering is ascending token_id on purpose: the registry grows by thousands of
agents per day, and any ordering that puts new rows at the front shifts the
paginator's window mid-sweep and silently skips agents. Ascending token_id
appends growth after the cursor; the store's primary key absorbs overlap.

`sampled` is always counted from the store, never from pages served, so a
repeating or overlapping paginator cannot inflate a published number.
"""

import logging

from .scan8004 import MAX_LIMIT, Scan8004Client
from .store import Store

logger = logging.getLogger(__name__)


def ingest_bsc(
    store: Store,
    client: Scan8004Client,
    *,
    chain_id: int = 56,
    max_pages: int | None = None,
    snapshot_id: int | None = None,
) -> dict:
    first_items, expected = client.list_agents(chain_id, limit=MAX_LIMIT, offset=0)
    sid = snapshot_id if snapshot_id is not None else store.begin_snapshot(chain_id, expected)

    pages = 0
    offset = 0
    items = first_items
    while items:
        store.upsert_agents(items, sid)
        pages += 1
        offset += MAX_LIMIT
        if max_pages is not None and pages >= max_pages:
            break
        items, latest_total = client.list_agents(chain_id, limit=MAX_LIMIT, offset=offset)
        if latest_total > expected:
            expected = latest_total  # registry grew mid-sweep; report it, don't hide it
        if pages % 50 == 0:
            logger.info("ingest: %d pages, %d stored", pages, store.agent_count(sid))

    sampled = store.agent_count(sid)
    store.finish_snapshot(sid, sampled)
    return {
        "snapshot_id": sid,
        "sampled": sampled,
        "expected": expected,
        "dropped": max(expected - sampled, 0),
        "pages": pages,
    }
```

- [ ] **Step 3: Run the tests**

```bash
./.venv/Scripts/python -m pytest tests/test_ingest.py -q
```
Expected: 4 passed.

- [ ] **Step 4: Commit**

```bash
git add docket/ingest.py tests/test_ingest.py
git commit -m "feat(ingest): drift-safe ascending sweep with honest coverage accounting"
```

---

### Task 4: Signals + generated coverage report

**Files:**
- Create: `docket/signals.py`, `docket/coverage.py`, `tests/test_signals.py`, `tests/test_coverage.py`

**Interfaces:**
- Consumes: `Store.iter_agents` / `Store.snapshot` (Task 1).
- Produces: `signals_for(agent: dict) -> dict` (pure), `publisher_key(agent: dict) -> str` (pure), and `coverage_report(store: Store, snapshot_id: int) -> dict` + `render_markdown(report: dict) -> str`. Phase 1b's ranking and listing pages consume all of these.

**What a signal is and is not:** each signal is a factual observation about registry data ("declares an A2A or MCP endpoint", "has at least one feedback record", "shares a bulk-mint publisher pattern"). No signal asserts that an agent is safe, trustworthy, or good. That distinction is load-bearing for the whole product.

- [ ] **Step 1: Write the failing test `tests/test_signals.py`**

```python
from docket.signals import publisher_key, signals_for


def _agent(**over) -> dict:
    base = {
        "agent_id": "56:0xreg:1",
        "token_id": "1",
        "name": "Some Agent",
        "description": "does a thing",
        "owner_address": "0xowner",
        "supported_protocols": [],
        "x402_supported": False,
        "total_feedbacks": 0,
        "total_score": 0.0,
    }
    base.update(over)
    return base


def test_placeholder_name_is_detected():
    assert signals_for(_agent(name="Agent #254413"))["placeholder_name"] is True
    assert signals_for(_agent(name="SOLVENT"))["placeholder_name"] is False


def test_callable_requires_a2a_or_mcp():
    assert signals_for(_agent(supported_protocols=["A2A"]))["callable"] is True
    assert signals_for(_agent(supported_protocols=["MCP"]))["callable"] is True
    assert signals_for(_agent(supported_protocols=["Web"]))["callable"] is False
    assert signals_for(_agent(supported_protocols=[]))["callable"] is False


def test_has_feedback_is_strictly_positive():
    assert signals_for(_agent(total_feedbacks=1))["has_feedback"] is True
    assert signals_for(_agent(total_feedbacks=0))["has_feedback"] is False


def test_describes_itself_requires_real_description():
    assert signals_for(_agent(description=None))["describes_itself"] is False
    assert signals_for(_agent(description="   "))["describes_itself"] is False
    assert signals_for(_agent(description="A yield agent."))["describes_itself"] is True


def test_publisher_key_collapses_bulk_mint_families():
    # Verified pattern: one publisher is ~46% of the chain under near-identical names.
    assert publisher_key(_agent(name="Ave.ai Trading Agent")) == "ave.ai"
    assert publisher_key(_agent(name="Ave.ai Research Agent")) == "ave.ai"
    assert publisher_key(_agent(name="Purr-Fect 1234")) == "purr-fect"
    assert publisher_key(_agent(name="SOLVENT")) == "solvent"


def test_publisher_key_falls_back_to_owner_for_placeholder_names():
    assert publisher_key(_agent(name="Agent #999", owner_address="0xABC")) == "owner:0xabc"


def test_signals_never_assert_safety():
    # Guard against a future contributor adding a "trusted"/"safe" verdict field.
    keys = set(signals_for(_agent()))
    assert not (keys & {"safe", "trusted", "verified_by_docket", "recommended"})
```

Run it → Expected: FAIL (no module).

- [ ] **Step 2: Write `docket/signals.py`**

```python
"""Deterministic, factual signals over a stored agent row. No network, no verdicts.

Each signal answers an observable question about registry data. None of them
claims an agent is safe or trustworthy — Docket surfaces evidence and lets a
reader judge. Every function here is pure so it can be unit-tested and re-run
over an old snapshot without touching the API.
"""

import re

# Auto-generated names 8004scan assigns when an agent publishes no metadata.
_PLACEHOLDER = re.compile(r"^agent\s*#?\d+$", re.IGNORECASE)
# Callable in practice: something can actually invoke it agent-to-agent.
_CALLABLE_PROTOCOLS = {"A2A", "MCP"}
# Families minted in bulk under near-identical names; collapsed so one publisher
# cannot dominate a listing page. Verified on BSC 2026-08-06/07.
_FAMILY_PREFIXES = ("ave.ai", "purr-fect", "termix", "quack", "q402", "mevx")


def _clean_name(agent: dict) -> str:
    return (agent.get("name") or "").strip()


def is_placeholder_name(agent: dict) -> bool:
    return bool(_PLACEHOLDER.match(_clean_name(agent)))


def publisher_key(agent: dict) -> str:
    """Stable key grouping agents minted by the same publisher/family."""
    name = _clean_name(agent).lower()
    if not name or _PLACEHOLDER.match(name):
        owner = (agent.get("owner_address") or "").lower()
        return f"owner:{owner}" if owner else "unknown"
    for prefix in _FAMILY_PREFIXES:
        if name.startswith(prefix):
            return prefix
    return name.split()[0]


def signals_for(agent: dict) -> dict:
    protocols = {p.upper() for p in (agent.get("supported_protocols") or [])}
    description = (agent.get("description") or "").strip()
    return {
        "placeholder_name": is_placeholder_name(agent),
        "callable": bool(protocols & _CALLABLE_PROTOCOLS),
        "has_feedback": int(agent.get("total_feedbacks") or 0) > 0,
        "describes_itself": bool(description),
        "x402": bool(agent.get("x402_supported")),
        "publisher": publisher_key(agent),
    }
```

Run: `./.venv/Scripts/python -m pytest tests/test_signals.py -q` → Expected: 7 passed.

- [ ] **Step 3: Write the failing test `tests/test_coverage.py`**

```python
from docket.coverage import coverage_report, render_markdown
from docket.store import Store


def _seed(store: Store) -> int:
    sid = store.begin_snapshot(chain_id=56, expected=6)
    rows = [
        {"agent_id": "56:r:1", "token_id": "1", "chain_id": 56, "name": "Ave.ai Trading Agent",
         "supported_protocols": [], "total_feedbacks": 0},
        {"agent_id": "56:r:2", "token_id": "2", "chain_id": 56, "name": "Ave.ai Research Agent",
         "supported_protocols": [], "total_feedbacks": 0},
        {"agent_id": "56:r:3", "token_id": "3", "chain_id": 56, "name": "Agent #3",
         "supported_protocols": [], "total_feedbacks": 0},
        {"agent_id": "56:r:4", "token_id": "4", "chain_id": 56, "name": "SOLVENT",
         "description": "glass-box trader", "supported_protocols": ["A2A"],
         "total_feedbacks": 2, "x402_supported": True},
        {"agent_id": "56:r:5", "token_id": "5", "chain_id": 56, "name": "Scout",
         "description": "finds pools", "supported_protocols": ["MCP"], "total_feedbacks": 0},
    ]
    store.upsert_agents(rows, sid)
    store.finish_snapshot(sid, sampled=5)
    return sid


def test_report_counts_are_generated_from_the_store(tmp_path):
    store = Store(tmp_path / "d.sqlite3")
    sid = _seed(store)
    rep = coverage_report(store, sid)
    assert rep["sampled"] == 5
    assert rep["expected"] == 6
    assert rep["dropped"] == 1          # partial coverage stated, not hidden
    assert rep["complete"] is False
    assert rep["with_feedback"] == 1
    assert rep["callable"] == 2
    assert rep["placeholder_name"] == 1
    assert rep["distinct_publishers"] == 4   # the two Ave.ai rows collapse to one


def test_top_publisher_share_is_reported(tmp_path):
    store = Store(tmp_path / "d.sqlite3")
    sid = _seed(store)
    rep = coverage_report(store, sid)
    top = rep["top_publishers"][0]
    assert top["publisher"] == "ave.ai"
    assert top["count"] == 2
    assert round(top["share_pct"], 1) == 40.0


def test_markdown_states_partial_coverage_explicitly(tmp_path):
    store = Store(tmp_path / "d.sqlite3")
    sid = _seed(store)
    md = render_markdown(coverage_report(store, sid))
    assert "partial" in md.lower()
    assert "5" in md and "6" in md
```

- [ ] **Step 4: Write `docket/coverage.py`**

```python
"""Generated coverage numbers for one snapshot.

Every figure Docket publishes about the BSC registry comes from here, computed
from stored rows. Nothing is typed into prose by hand, and a snapshot that did
not capture everything the API claimed says so in its own output.
"""

from collections import Counter

from .signals import signals_for
from .store import Store


def coverage_report(store: Store, snapshot_id: int) -> dict:
    meta = store.snapshot(snapshot_id)
    sampled = store.agent_count(snapshot_id)
    expected = int(meta.get("expected") or 0)
    counts = Counter()
    publishers = Counter()
    for agent in store.iter_agents(snapshot_id):
        sig = signals_for(agent)
        publishers[sig["publisher"]] += 1
        for key in ("placeholder_name", "callable", "has_feedback", "describes_itself", "x402"):
            if sig[key]:
                counts[key] += 1

    def pct(n: int) -> float:
        return round(100.0 * n / sampled, 3) if sampled else 0.0

    return {
        "snapshot_id": snapshot_id,
        "chain_id": int(meta.get("chain_id") or 0),
        "captured_at": meta.get("finished_at") or meta.get("started_at"),
        "sampled": sampled,
        "expected": expected,
        "dropped": max(expected - sampled, 0),
        "complete": expected == sampled and sampled > 0,
        "with_feedback": counts["has_feedback"],
        "with_feedback_pct": pct(counts["has_feedback"]),
        "callable": counts["callable"],
        "callable_pct": pct(counts["callable"]),
        "placeholder_name": counts["placeholder_name"],
        "describes_itself": counts["describes_itself"],
        "x402": counts["x402"],
        "distinct_publishers": len(publishers),
        "top_publishers": [
            {"publisher": p, "count": n, "share_pct": pct(n)}
            for p, n in publishers.most_common(5)
        ],
    }


def render_markdown(report: dict) -> str:
    status = "complete" if report["complete"] else "partial"
    lines = [
        f"# BSC agent registry — snapshot {report['snapshot_id']} ({status})",
        "",
        f"Captured {report['captured_at']} from chain {report['chain_id']}.",
        f"Stored **{report['sampled']:,}** of **{report['expected']:,}** agents the API "
        f"reported (`dropped={report['dropped']:,}`).",
        "",
        "| Signal | Agents | Share |",
        "| --- | ---: | ---: |",
        f"| Has at least one feedback record | {report['with_feedback']:,} | {report['with_feedback_pct']}% |",
        f"| Declares a callable endpoint (A2A or MCP) | {report['callable']:,} | {report['callable_pct']}% |",
        f"| Supports x402 | {report['x402']:,} | |",
        f"| Auto-generated placeholder name | {report['placeholder_name']:,} | |",
        f"| Distinct publishers | {report['distinct_publishers']:,} | |",
        "",
        "## Largest publishers",
        "",
        "| Publisher | Agents | Share of snapshot |",
        "| --- | ---: | ---: |",
    ]
    for row in report["top_publishers"]:
        lines.append(f"| {row['publisher']} | {row['count']:,} | {row['share_pct']}% |")
    lines += [
        "",
        "These are factual observations about registry metadata. None of them asserts "
        "that an agent is safe, trustworthy, or fit for a given purpose.",
    ]
    return "\n".join(lines)
```

- [ ] **Step 5: Run the tests**

```bash
./.venv/Scripts/python -m pytest tests/test_signals.py tests/test_coverage.py -q
```
Expected: 10 passed. Then full suite → 25 passed (8 Phase-0 + 3 store + 6 client + 4 ingest + 7 signals + 3 coverage minus none).

- [ ] **Step 6: Commit**

```bash
git add docket/signals.py docket/coverage.py tests/test_signals.py tests/test_coverage.py
git commit -m "feat(signals): factual agent signals + generated coverage report"
```

- [ ] **Step 7: Run one real bounded ingestion and record the numbers**

```bash
./.venv/Scripts/python - << 'PY'
from docket.coverage import coverage_report, render_markdown
from docket.ingest import ingest_bsc
from docket.scan8004 import Scan8004Client
from docket.store import Store

store = Store("data/agents.sqlite3")
with Scan8004Client() as client:
    result = ingest_bsc(store, client, max_pages=20)   # 2,000 agents — a bounded smoke run
print(result)
print(render_markdown(coverage_report(store, result["snapshot_id"])))
PY
```

Paste the real output into the report file. Add `data/` to `.gitignore` — the database is regenerable and must not be committed. Do not commit the smoke-run database.

---

## Self-review (done at write time)

- Spec coverage: Phase 1a of spec §4.1 (ingestion, noise filter, honest metrics with sample sizes) is covered by Tasks 1-4. Listing pages, agent-facing API, hire rails, and the three agents are Phase 1b+ and deliberately out of scope.
- Placeholders: none; every step carries runnable code or an exact command.
- Type consistency: `Store` method names used in Tasks 2-4 match Task 1's definitions (`begin_snapshot`, `finish_snapshot`, `upsert_agents`, `agent_count`, `iter_agents`, `snapshot`); `signals_for`/`publisher_key` names match between `signals.py`, its tests, and `coverage.py`.
- Constraint check: no new dependencies; every published number generated; no signal asserts safety (there is a test enforcing that).
