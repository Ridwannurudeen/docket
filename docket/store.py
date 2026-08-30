"""SQLite store for 8004scan agent snapshots.

A snapshot is one ingestion run: it records what the API claimed existed
(`expected`) alongside what we actually stored (`sampled`), so every number
Docket publishes can state its own coverage instead of implying completeness.
"""

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

# Why a sweep stopped. Closed, because an open vocabulary here would let a new stop condition
# arrive unclassified and be served as if it were a clean finish. Only `exhausted` may be
# promoted to readers; the rest describe a sweep that ended without reaching the end.
STOP_REASONS = ("exhausted", "max_pages", "not_advancing")
COMPLETE_STOP_REASON = "exhausted"
CANARY_TERMINAL_VERDICTS = ("passed", "failed", "not_yet_exercised")
CANARY_CHECK_STATUSES = CANARY_TERMINAL_VERDICTS
MAX_CANARY_HISTORY_LIMIT = 100
CANARY_SENSITIVE_FIELDS = frozenset(
    {
        "x-payment",
        "payment-signature",
        "authorization",
        "signature",
        "private-key",
        "mnemonic",
        "api-key",
        "api-secret",
        "secret-key",
    }
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chain_id INTEGER NOT NULL,
    expected INTEGER,
    sampled INTEGER,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    promoted_at TEXT,
    -- Which query this snapshot swept: "all" for the whole registry, or the predicate that
    -- narrowed it, e.g. "min_feedbacks>=1". NULL where a sweep predating this column never
    -- recorded one; that reads as unspecified and is never filled in by guesswork.
    population TEXT
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
CREATE TABLE IF NOT EXISTS liveness_on_demand (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_id INTEGER NOT NULL,
    agent_id TEXT NOT NULL,
    url TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    outcome TEXT NOT NULL,
    status_code INTEGER,
    elapsed_ms INTEGER,
    detail TEXT,
    requested_from_ip_hash TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS liveness_on_demand_snapshot_agent
    ON liveness_on_demand (snapshot_id, agent_id, id DESC);
CREATE TABLE IF NOT EXISTS hire_payments (
    nonce TEXT PRIMARY KEY,
    payment_id TEXT NOT NULL UNIQUE,
    service_id TEXT NOT NULL,
    payer TEXT NOT NULL,
    recipient TEXT NOT NULL,
    asset TEXT NOT NULL,
    amount TEXT NOT NULL,
    resource TEXT NOT NULL,
    input_hash TEXT NOT NULL,
    output_hash TEXT,
    status TEXT NOT NULL,
    result_json TEXT,
    receipt_json TEXT,
    transaction_id TEXT,
    network TEXT,
    error TEXT,
    operator_recovered_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS hire_payments_status ON hire_payments (status);
CREATE TABLE IF NOT EXISTS canary_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    service_id TEXT NOT NULL,
    target_url TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    verdict TEXT NOT NULL CHECK (
        verdict IN ('running', 'passed', 'failed', 'not_yet_exercised')
    ),
    checks_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS canary_runs_service ON canary_runs (service_id, id DESC);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canary_run(row: sqlite3.Row) -> dict:
    run = dict(row)
    run["checks"] = json.loads(run.pop("checks_json"))
    return run


def _agent(row: sqlite3.Row) -> dict:
    agent = dict(row)
    agent["supported_protocols"] = json.loads(agent["supported_protocols"])
    agent["x402_supported"] = bool(agent["x402_supported"])
    agent["is_verified"] = bool(agent["is_verified"])
    return agent


def _sensitive_canary_field(value) -> str | None:
    if isinstance(value, dict):
        for key, nested in value.items():
            normalized = str(key).strip().lower().replace("_", "-")
            if normalized in CANARY_SENSITIVE_FIELDS:
                return normalized
            found = _sensitive_canary_field(nested)
            if found is not None:
                return found
    elif isinstance(value, (list, tuple)):
        for nested in value:
            found = _sensitive_canary_field(nested)
            if found is not None:
                return found
    return None


class Store:
    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as conn:
            conn.executescript(SCHEMA)
            # CREATE TABLE IF NOT EXISTS leaves an existing table alone, so a database written
            # before a column existed never gains it from SCHEMA. Added here instead, and only
            # when absent: the live database holds real sweeps and must migrate, not be rebuilt.
            snapshot_columns = {
                r["name"] for r in conn.execute("PRAGMA table_info(snapshots)")
            }
            payment_columns = {
                r["name"] for r in conn.execute("PRAGMA table_info(hire_payments)")
            }
            if not {"population", "stop_reason", "promoted_at"} <= snapshot_columns or (
                "operator_recovered_at" not in payment_columns
            ):
                # `executescript` leaves no transaction open. Reserve the writer only when a
                # migration may be needed, then recheck under that lock: another initializer
                # may have completed the same migration while this connection waited.
                conn.execute("BEGIN IMMEDIATE")
                snapshot_columns = {
                    r["name"] for r in conn.execute("PRAGMA table_info(snapshots)")
                }
                payment_columns = {
                    r["name"] for r in conn.execute("PRAGMA table_info(hire_payments)")
                }
                if "population" not in snapshot_columns:
                    conn.execute("ALTER TABLE snapshots ADD COLUMN population TEXT")
                if "stop_reason" not in snapshot_columns:
                    conn.execute("ALTER TABLE snapshots ADD COLUMN stop_reason TEXT")
                if "promoted_at" not in snapshot_columns:
                    conn.execute("ALTER TABLE snapshots ADD COLUMN promoted_at TEXT")
                    conn.execute(
                        """UPDATE snapshots SET promoted_at = finished_at
                           WHERE finished_at IS NOT NULL
                             AND sampled IS NOT NULL AND expected IS NOT NULL
                             AND sampled = expected AND sampled > 0
                             AND (stop_reason IS NULL OR stop_reason = ?)""",
                        (COMPLETE_STOP_REASON,),
                    )
                if "operator_recovered_at" not in payment_columns:
                    conn.execute(
                        "ALTER TABLE hire_payments ADD COLUMN operator_recovered_at TEXT"
                    )

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        try:
            with (
                conn
            ):  # commits on clean exit; contextlib.closing would silently drop writes
                yield conn
        finally:
            conn.close()

    def payment_by_nonce(self, nonce: str) -> dict:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM hire_payments WHERE nonce = ?", (nonce,)
            ).fetchone()
        if row is None:
            return {}
        payment = dict(row)
        for field in ("result_json", "receipt_json"):
            if payment[field] is not None:
                payment[field.removesuffix("_json")] = json.loads(payment[field])
        return payment

    def record_operator_recovery(self, nonce: str) -> bool:
        """Record a token-authenticated delivery without changing payment finality."""
        recovered_at = _now()
        with self._conn() as conn:
            cursor = conn.execute(
                """UPDATE hire_payments
                   SET operator_recovered_at = ?, updated_at = ?
                   WHERE nonce = ? AND status IN ('settled', 'settlement_unknown')""",
                (recovered_at, recovered_at, nonce),
            )
        return cursor.rowcount == 1

    def reserve_payment(
        self,
        *,
        nonce: str,
        payment_id: str,
        service_id: str,
        payer: str,
        recipient: str,
        asset: str,
        amount: str,
        resource: str,
        input_hash: str,
    ) -> tuple[bool, dict]:
        """Atomically claim a nonce; concurrent callers can never both own it."""
        observed_at = _now()
        with self._conn() as conn:
            cursor = conn.execute(
                """INSERT INTO hire_payments
                   (nonce, payment_id, service_id, payer, recipient, asset, amount,
                    resource, input_hash, status, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'verified', ?, ?)
                   ON CONFLICT DO NOTHING""",
                (
                    nonce,
                    payment_id,
                    service_id,
                    payer,
                    recipient,
                    asset,
                    amount,
                    resource,
                    input_hash,
                    observed_at,
                    observed_at,
                ),
            )
            row = conn.execute(
                "SELECT * FROM hire_payments WHERE nonce = ?", (nonce,)
            ).fetchone()
        return cursor.rowcount == 1, dict(row) if row else {}

    def record_payment_output(
        self, payment_id: str, *, output_hash: str, result: dict
    ) -> None:
        result_json = json.dumps(
            result, sort_keys=True, ensure_ascii=False, allow_nan=False
        )
        with self._conn() as conn:
            cursor = conn.execute(
                """UPDATE hire_payments
                   SET output_hash = ?, result_json = ?, status = 'output_ready',
                       updated_at = ?
                   WHERE payment_id = ? AND status = 'verified'""",
                (
                    output_hash,
                    result_json,
                    _now(),
                    payment_id,
                ),
            )
        if cursor.rowcount != 1:
            raise ValueError("payment output was not recorded from verified state")

    def begin_payment_settlement(self, payment_id: str) -> bool:
        """Persist the one-way settlement boundary before any external call is made."""
        with self._conn() as conn:
            cursor = conn.execute(
                """UPDATE hire_payments SET status = 'settling', updated_at = ?
                   WHERE payment_id = ? AND status = 'output_ready'""",
                (_now(), payment_id),
            )
        return cursor.rowcount == 1

    def finish_payment(
        self,
        payment_id: str,
        *,
        transaction_id: str,
        network: str,
        receipt: dict,
    ) -> None:
        with self._conn() as conn:
            cursor = conn.execute(
                """UPDATE hire_payments
                   SET transaction_id = ?, network = ?, receipt_json = ?,
                       status = 'settled', updated_at = ?
                   WHERE payment_id = ? AND status = 'settling'""",
                (
                    transaction_id,
                    network,
                    json.dumps(
                        receipt, sort_keys=True, ensure_ascii=False, allow_nan=False
                    ),
                    _now(),
                    payment_id,
                ),
            )
        if cursor.rowcount != 1:
            raise ValueError("payment was not finalized from settling state")

    def reconcile_stale_settlement(
        self,
        nonce: str,
        *,
        expected_updated_at: str,
        stale_before: str,
        receipt: dict,
        error: str,
    ) -> bool:
        """Atomically classify one unchanged stale settlement without retrying it."""
        payment = receipt.get("payment") if isinstance(receipt, dict) else None
        if (
            not isinstance(payment, dict)
            or payment.get("status") != "settlement_unknown"
        ):
            raise ValueError("reconciliation requires a settlement_unknown receipt")
        receipt_json = json.dumps(
            receipt, sort_keys=True, ensure_ascii=False, allow_nan=False
        )
        reconciled_at = _now()
        with self._conn() as conn:
            cursor = conn.execute(
                """UPDATE hire_payments
                   SET status = 'settlement_unknown', error = ?, receipt_json = ?,
                       operator_recovered_at = ?, updated_at = ?
                   WHERE nonce = ? AND status = 'settling' AND updated_at = ?
                     AND julianday(updated_at) <= julianday(?)
                     AND transaction_id IS NULL AND network IS NULL""",
                (
                    error,
                    receipt_json,
                    reconciled_at,
                    reconciled_at,
                    nonce,
                    expected_updated_at,
                    stale_before,
                ),
            )
        return cursor.rowcount == 1

    def reconcile_stale_pre_settlement(
        self,
        nonce: str,
        *,
        expected_status: str,
        expected_updated_at: str,
        stale_before: str,
        error: str,
    ) -> bool:
        """Close one unchanged stale row whose settlement boundary was never crossed."""
        if expected_status not in {"verified", "output_ready"}:
            raise ValueError(
                "pre-settlement reconciliation requires an in-flight state"
            )
        reconciled_at = _now()
        with self._conn() as conn:
            cursor = conn.execute(
                """UPDATE hire_payments
                   SET status = 'failed_no_charge', error = ?, updated_at = ?
                   WHERE nonce = ? AND status = ? AND updated_at = ?
                     AND julianday(updated_at) <= julianday(?)
                     AND transaction_id IS NULL AND network IS NULL
                     AND receipt_json IS NULL
                     AND (
                         (? = 'verified' AND result_json IS NULL
                                           AND output_hash IS NULL)
                         OR
                         (? = 'output_ready' AND result_json IS NOT NULL
                                               AND output_hash IS NOT NULL)
                     )""",
                (
                    error,
                    reconciled_at,
                    nonce,
                    expected_status,
                    expected_updated_at,
                    stale_before,
                    expected_status,
                    expected_status,
                ),
            )
        return cursor.rowcount == 1

    def fail_payment(
        self,
        payment_id: str,
        *,
        status: str,
        error: str,
        receipt: dict | None = None,
    ) -> None:
        if status not in {
            "failed_no_charge",
            "settlement_failed",
            "settlement_unknown",
        }:
            raise ValueError(f"unsupported terminal payment status {status!r}")
        if status == "settlement_unknown" and not isinstance(receipt, dict):
            raise ValueError("settlement_unknown requires a recovery receipt")
        if status != "settlement_unknown" and receipt is not None:
            raise ValueError(f"{status} does not accept a recovery receipt")
        receipt_json = (
            json.dumps(receipt, sort_keys=True, ensure_ascii=False, allow_nan=False)
            if receipt is not None
            else None
        )
        with self._conn() as conn:
            conn.execute(
                """UPDATE hire_payments
                   SET status = ?, error = ?, receipt_json = ?, updated_at = ?
                   WHERE payment_id = ? AND status != 'settled'""",
                (status, error, receipt_json, _now(), payment_id),
            )

    def begin_canary_run(
        self, service_id: str, target_url: str, started_at: str | None = None
    ) -> int:
        """Persist the running state before the canary makes any external request."""
        with self._conn() as conn:
            cursor = conn.execute(
                """INSERT INTO canary_runs
                   (service_id, target_url, started_at, verdict, checks_json)
                   VALUES (?, ?, ?, 'running', '[]')""",
                (
                    service_id,
                    target_url,
                    started_at if started_at is not None else _now(),
                ),
            )
        return int(cursor.lastrowid)

    def finish_canary_run(
        self,
        run_id: int,
        *,
        verdict: str,
        checks: list[dict],
        finished_at: str | None = None,
    ) -> dict:
        if verdict not in CANARY_TERMINAL_VERDICTS:
            raise ValueError(
                f"unsupported canary verdict {verdict!r}; "
                f"expected one of {CANARY_TERMINAL_VERDICTS}"
            )
        if not isinstance(checks, list):
            raise ValueError("canary checks must be a list")
        for check in checks:
            if (
                not isinstance(check, dict)
                or not {
                    "leg",
                    "checked",
                    "observed",
                    "evidence",
                }
                <= check.keys()
            ):
                raise ValueError(
                    "every canary check must carry leg, checked, observed and evidence"
                )
            if check.get("status") not in CANARY_CHECK_STATUSES:
                raise ValueError(
                    f"unsupported canary check status {check.get('status')!r}; "
                    f"expected one of {CANARY_CHECK_STATUSES}"
                )
        if verdict == "passed" and not checks:
            raise ValueError("a passed canary requires a non-empty list of checks")
        if verdict == "passed" and any(check["status"] != "passed" for check in checks):
            raise ValueError(
                "a passed canary requires every check to have status 'passed'"
            )
        sensitive_field = _sensitive_canary_field(checks)
        if sensitive_field is not None:
            raise ValueError(
                f"canary checks must not store sensitive field {sensitive_field!r}"
            )
        try:
            encoded_checks = json.dumps(
                checks, sort_keys=True, ensure_ascii=False, allow_nan=False
            )
        except (TypeError, ValueError) as exc:
            raise ValueError("canary checks must be finite JSON values") from exc

        with self._conn() as conn:
            cursor = conn.execute(
                """UPDATE canary_runs
                   SET finished_at = ?, verdict = ?, checks_json = ?
                   WHERE id = ? AND verdict = 'running'""",
                (
                    finished_at if finished_at is not None else _now(),
                    verdict,
                    encoded_checks,
                    run_id,
                ),
            )
            if cursor.rowcount != 1:
                raise ValueError("canary run does not exist or is no longer running")
            row = conn.execute(
                "SELECT * FROM canary_runs WHERE id = ?", (run_id,)
            ).fetchone()
        return _canary_run(row)

    def latest_canary_run(self, service_id: str) -> dict:
        with self._conn() as conn:
            row = conn.execute(
                """SELECT * FROM canary_runs
                   WHERE service_id = ? ORDER BY id DESC LIMIT 1""",
                (service_id,),
            ).fetchone()
        return _canary_run(row) if row else {}

    def iter_canary_runs(self, service_id: str, limit: int = 30) -> Iterator[dict]:
        if (
            not isinstance(limit, int)
            or isinstance(limit, bool)
            or not 1 <= limit <= MAX_CANARY_HISTORY_LIMIT
        ):
            raise ValueError(
                f"canary history limit must be between 1 and {MAX_CANARY_HISTORY_LIMIT}"
            )
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT * FROM canary_runs
                   WHERE service_id = ? ORDER BY id DESC LIMIT ?""",
                (service_id, limit),
            ).fetchall()
        for row in rows:
            yield _canary_run(row)

    def begin_snapshot(
        self, chain_id: int, expected: int | None, population: str | None = None
    ) -> int:
        """Open a snapshot. `population` is the query it sweeps — "all", or the predicate that
        narrowed it. Recorded here rather than left to the caller's memory: `expected` says how
        many rows a query claimed, and without the query beside it a filtered total reads as a
        census of the whole registry."""
        with self._conn() as conn:
            cur = conn.execute(
                "INSERT INTO snapshots (chain_id, expected, started_at, population) "
                "VALUES (?, ?, ?, ?)",
                (chain_id, expected, _now(), population),
            )
            return int(cur.lastrowid)

    def finish_snapshot(
        self,
        snapshot_id: int,
        sampled: int,
        expected: int | None = None,
        stop_reason: str = "exhausted",
        *,
        promote: bool = True,
    ) -> None:
        """Close a snapshot. Pass `expected` to overwrite the figure `begin_snapshot` recorded —
        a sweep that watches the registry grow must persist the final claim, or a later reader
        would compare `sampled` against a stale total and publish false completeness.

        `stop_reason` records WHY the sweep ended, because "it ended" and "it reached the end"
        are not the same event and only one of them may be served. A sweep stopped by a page
        cap or by a paginator that stopped advancing is finished and partial, and until this
        column existed it was indistinguishable from a clean one: `finished_at` was set either
        way, so `latest_complete_snapshot_id` would promote it the moment a sweep ran
        unattended.
        """
        if stop_reason not in STOP_REASONS:
            raise ValueError(
                f"unknown stop_reason {stop_reason!r}; expected one of {STOP_REASONS}"
            )
        finished_at = _now()
        with self._conn() as conn:
            if expected is None:
                conn.execute(
                    "UPDATE snapshots SET sampled = ?, finished_at = ?, stop_reason = ? "
                    "WHERE id = ?",
                    (sampled, finished_at, stop_reason, snapshot_id),
                )
            else:
                conn.execute(
                    "UPDATE snapshots SET sampled = ?, expected = ?, finished_at = ?, "
                    "stop_reason = ? WHERE id = ?",
                    (sampled, expected, finished_at, stop_reason, snapshot_id),
                )
            if promote:
                conn.execute(
                    """UPDATE snapshots SET promoted_at = ?
                       WHERE id = ? AND finished_at IS NOT NULL
                         AND sampled IS NOT NULL AND expected IS NOT NULL
                         AND sampled = expected AND sampled > 0
                         AND (stop_reason IS NULL OR stop_reason = ?)""",
                    (finished_at, snapshot_id, COMPLETE_STOP_REASON),
                )

    def promote_snapshot(self, snapshot_id: int) -> None:
        """Make one fully finished candidate visible to readers."""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM snapshots WHERE id = ?", (snapshot_id,)
            ).fetchone()
            if row is None:
                raise ValueError(
                    f"snapshot {snapshot_id} cannot be promoted: it does not exist"
                )
            if (
                row["finished_at"] is None
                or row["sampled"] is None
                or row["expected"] is None
                or row["sampled"] <= 0
                or row["sampled"] != row["expected"]
                or row["stop_reason"] not in {None, COMPLETE_STOP_REASON}
            ):
                raise ValueError(
                    f"snapshot {snapshot_id} cannot be promoted: it is not a complete exhausted sweep"
                )
            conn.execute(
                "UPDATE snapshots SET promoted_at = ? WHERE id = ?",
                (_now(), snapshot_id),
            )

    def upsert_agents(self, rows: list[dict], snapshot_id: int) -> int:
        payload = []
        for r in rows:
            token_id = r.get("token_id")
            payload.append(
                (
                    snapshot_id,
                    r["agent_id"],
                    "" if token_id is None else str(token_id),
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
                     owner_address = excluded.owner_address,
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
        """The newest snapshot row, finished or not — what a sweep resuming its own run wants."""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT id FROM snapshots WHERE chain_id = ? ORDER BY id DESC LIMIT 1",
                (chain_id,),
            ).fetchone()
        return int(row["id"]) if row else None

    def latest_complete_snapshot_id(self, chain_id: int = 56) -> int | None:
        """The newest snapshot that ran to the end — what a reader must be served.

        A sweep in flight, or one that crashed, is still the newest row while its counts are
        being written. Serving it would publish a partial capture as the whole of what Docket
        observed: every count understated, and `complete` computed against an `expected` the
        run never reached.

        `finished_at IS NOT NULL` was the whole of this test, and it caught only the crashed
        sweep. It did not catch the *finished and partial* one: `_sweep` stops on a page cap or
        a paginator that will not advance, and then closes the snapshot exactly as a clean run
        does. Harmless while every sweep was launched by hand and checked; the moment one runs
        unattended, a truncated capture becomes what the site serves. So completeness is now
        the same predicate `coverage_report` publishes — `sampled == expected` — plus the
        recorded reason the sweep ended.

        Rows written before `stop_reason` existed carry NULL and are judged on counts alone:
        they were run and checked by hand, and rejecting them would take the live snapshot off
        the site to fix a bug it does not have.
        """
        with self._conn() as conn:
            row = conn.execute(
                "SELECT id FROM snapshots WHERE chain_id = ? AND promoted_at IS NOT NULL "
                "AND finished_at IS NOT NULL "
                "AND sampled IS NOT NULL AND expected IS NOT NULL AND sampled = expected "
                "AND sampled > 0 AND (stop_reason IS NULL OR stop_reason = ?) "
                "ORDER BY id DESC LIMIT 1",
                (chain_id, COMPLETE_STOP_REASON),
            ).fetchone()
        return int(row["id"]) if row else None

    def registry_total(self, chain_id: int = 56) -> int | None:
        """A LOWER BOUND on this chain's size: the largest total any sweep recorded, finished
        or not.

        `expected` is what the registry API answered when a sweep asked it, so it is a recorded
        observation and does not depend on that sweep completing. Read it as "at least this many
        agents were registered when some sweep last measured" and never as the size of the
        registry: where every sweep on record was filtered — the state a targeted refresh loop
        produces on a fresh database — the largest total recorded is a FILTERED total, and the
        chain is larger than this figure rather than equal to it. It may also equal the served
        snapshot's own `expected`, which is that same case seen from the other side.

        It is still the figure a filtered snapshot has to be read against: 506 of 506 is
        complete, and complete is a fraction of a percent of the chain. None where no sweep has
        recorded a total at all.
        """
        with self._conn() as conn:
            row = conn.execute(
                "SELECT MAX(expected) AS m FROM snapshots WHERE chain_id = ?",
                (chain_id,),
            ).fetchone()
        return int(row["m"]) if row and row["m"] is not None else None

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
                    "SELECT COUNT(*) AS n FROM agents WHERE snapshot_id = ?",
                    (snapshot_id,),
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
                yield _agent(row)

    def agent_by_id(self, snapshot_id: int, agent_id: str) -> dict:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM agents WHERE snapshot_id = ? AND agent_id = ?",
                (snapshot_id, agent_id),
            ).fetchone()
        return _agent(row) if row else {}

    def upsert_endpoints(self, rows: list[dict], snapshot_id: int) -> int:
        payload = [(snapshot_id, r["agent_id"], r["kind"], r["url"]) for r in rows]
        with self._conn() as conn:
            conn.executemany(
                """INSERT INTO endpoints (snapshot_id, agent_id, kind, url)
                   VALUES (?,?,?,?)
                   ON CONFLICT (snapshot_id, agent_id, kind, url) DO NOTHING""",
                payload,
            )
        return len(payload)

    def iter_endpoints(
        self, snapshot_id: int, kind: str | None = None
    ) -> Iterator[dict]:
        sql = "SELECT * FROM endpoints WHERE snapshot_id = ?"
        args: tuple = (snapshot_id,)
        if kind is not None:
            sql += " AND kind = ?"
            args += (kind,)
        with self._conn() as conn:
            for row in conn.execute(sql, args):
                yield dict(row)

    def endpoint_count(self, snapshot_id: int) -> int:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM endpoints WHERE snapshot_id = ?",
                (snapshot_id,),
            ).fetchone()
        return int(row["n"])

    def mark_enriched(self, agent_ids: list[str], snapshot_id: int) -> int:
        """Record that an agent's card has been fetched — including agents that turned out to
        have no endpoints at all, so a resumed run does not re-fetch them forever."""
        payload = [(snapshot_id, agent_id) for agent_id in agent_ids]
        with self._conn() as conn:
            conn.executemany(
                """INSERT INTO enriched (snapshot_id, agent_id) VALUES (?,?)
                   ON CONFLICT (snapshot_id, agent_id) DO NOTHING""",
                payload,
            )
        return len(payload)

    def enriched_agent_ids(self, snapshot_id: int) -> set[str]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT agent_id FROM enriched WHERE snapshot_id = ?", (snapshot_id,)
            ).fetchall()
        return {row["agent_id"] for row in rows}

    def record_liveness(self, rows: list[dict]) -> int:
        """Append sweep probe observations. Never an upsert — each sweep probe is a distinct
        event, and overwriting one would erase the history behind the snapshot figures."""
        payload = [
            (
                r["snapshot_id"],
                r["agent_id"],
                r["url"],
                r["observed_at"],
                r["outcome"],
                r.get("status_code"),
                r.get("elapsed_ms"),
                r.get("detail"),
            )
            for r in rows
        ]
        with self._conn() as conn:
            conn.executemany(
                """INSERT INTO liveness
                   (snapshot_id, agent_id, url, observed_at, outcome,
                    status_code, elapsed_ms, detail)
                   VALUES (?,?,?,?,?,?,?,?)""",
                payload,
            )
        return len(payload)

    def iter_liveness(self, snapshot_id: int) -> Iterator[dict]:
        with self._conn() as conn:
            for row in conn.execute(
                "SELECT * FROM liveness WHERE snapshot_id = ? ORDER BY id",
                (snapshot_id,),
            ):
                yield dict(row)

    def record_on_demand_liveness(
        self, observation: dict, *, requested_from_ip_hash: str
    ) -> int:
        with self._conn() as conn:
            cursor = conn.execute(
                """INSERT INTO liveness_on_demand
                   (snapshot_id, agent_id, url, observed_at, outcome,
                    status_code, elapsed_ms, detail, requested_from_ip_hash)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (
                    observation["snapshot_id"],
                    observation["agent_id"],
                    observation["url"],
                    observation["observed_at"],
                    observation["outcome"],
                    observation.get("status_code"),
                    observation.get("elapsed_ms"),
                    observation.get("detail"),
                    requested_from_ip_hash,
                ),
            )
        return cursor.rowcount

    def latest_on_demand_liveness(self, snapshot_id: int, agent_id: str) -> dict:
        with self._conn() as conn:
            row = conn.execute(
                """SELECT * FROM liveness_on_demand
                   WHERE snapshot_id = ? AND agent_id = ?
                   ORDER BY id DESC LIMIT 1""",
                (snapshot_id, agent_id),
            ).fetchone()
        return dict(row) if row else {}
