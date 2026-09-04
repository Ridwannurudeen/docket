"""SQLite store for 8004scan agent snapshots.

A snapshot is one ingestion run: it records what the API claimed existed
(`expected`) alongside what we actually stored (`sampled`), so every number
Docket publishes can state its own coverage instead of implying completeness.
"""

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .jobs.models import Activation, dumps, loads

# Why a sweep stopped. Closed, because an open vocabulary here would let a new stop condition
# arrive unclassified and be served as if it were a clean finish. Only `exhausted` may be
# promoted to readers; the rest describe a sweep that ended without reaching the end.
STOP_REASONS = ("exhausted", "max_pages", "not_advancing")
# Verification levels, weakest to strongest, for ORDER BY only. Repeated here rather than
# imported because this module is stdlib sqlite3 over a schema and imports nothing from the
# domain packages; `tests/test_external_listings.py` asserts it equals
# `marketplace.external.LEVELS`, so the two cannot drift apart in silence.
#
# The rank is the whole point. The names do not sort into their own order — 'live' sorts
# before 'registered' alphabetically — so ordering on the column would have put a weaker
# listing above a stronger one. NULL, meaning nothing has been observed, sorts last: a row
# Docket merely found in an index must never head a page above one it actually verified.
EXTERNAL_LEVELS = (
    "registered",
    "endpoint_detected",
    "live",
    "payment_tested",
    "docket_tested",
    "docket_verified",
)
EXTERNAL_LEVEL_ORDER_SQL = (
    "CASE level "
    + " ".join(
        f"WHEN '{name}' THEN {len(EXTERNAL_LEVELS) - index}"
        for index, name in enumerate(EXTERNAL_LEVELS)
    )
    + " ELSE 99 END ASC"
)
COMPLETE_STOP_REASON = "exhausted"
CANARY_TERMINAL_VERDICTS = ("passed", "failed", "not_yet_exercised")
CANARY_CHECK_STATUSES = CANARY_TERMINAL_VERDICTS
MAX_CANARY_HISTORY_LIMIT = 100
# The window a status surface reads probe history over. Named here rather than at the
# call site so the number a page publishes and the number the query used are one value.
PROBE_WINDOW_HOURS = 24
MAX_PROBE_WINDOW_HOURS = 24 * 30
PROBE_STEP_FIELDS = frozenset({"name", "ok", "status_code", "latency_ms", "detail"})
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
CREATE TABLE IF NOT EXISTS probe_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,
    finished_at TEXT NOT NULL,
    ok INTEGER NOT NULL,
    steps_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS probe_runs_started ON probe_runs (started_at DESC);
-- Third-party agents Docket lists but did not build. The listing travels as one JSON
-- document because its shape belongs to `marketplace.external`, not to this schema; the
-- three columns beside it are the ones a marketplace query filters on, denormalised so a
-- category or level filter is an index seek rather than a scan that parses every row.
-- `level` is NULL for a listing that has only been seen in the registry index: being
-- indexed is not an observation, and it must not sort above `registered`.
CREATE TABLE IF NOT EXISTS external_listings (
    agent_id TEXT PRIMARY KEY,
    chain_id INTEGER NOT NULL,
    category TEXT,
    level TEXT,
    hireable INTEGER NOT NULL DEFAULT 0,
    source TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    listing_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS external_listings_category ON external_listings (category);
CREATE INDEX IF NOT EXISTS external_listings_level ON external_listings (level);
-- Append-only, like `liveness`. Every level attempt writes one row whether it passed or
-- not, so a listing that dropped a level leaves the evidence of both readings behind
-- instead of the newer one erasing the older.
CREATE TABLE IF NOT EXISTS verification_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id TEXT NOT NULL,
    level TEXT NOT NULL,
    at TEXT NOT NULL,
    ok INTEGER NOT NULL,
    detail_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS verification_runs_listing
    ON verification_runs (agent_id, id DESC);
-- One row per issued claim nonce. Single use: `verified_at` is stamped by the accepted
-- signature and a nonce carrying one is never accepted again, so a captured signature
-- cannot be replayed into a second listing.
CREATE TABLE IF NOT EXISTS provider_claims (
    nonce TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL,
    issued_at TEXT NOT NULL,
    verified_at TEXT,
    owner TEXT
);
CREATE INDEX IF NOT EXISTS provider_claims_agent ON provider_claims (agent_id, nonce);
CREATE TABLE IF NOT EXISTS activations (
    activation_id TEXT PRIMARY KEY,
    service_id TEXT NOT NULL,
    category TEXT NOT NULL,
    kind TEXT NOT NULL,
    owner TEXT NOT NULL,
    state TEXT NOT NULL,
    quote_json TEXT NOT NULL,
    policy_json TEXT,
    session_json TEXT,
    inputs_json TEXT NOT NULL,
    result_json TEXT,
    receipts_json TEXT NOT NULL,
    events_json TEXT NOT NULL,
    next_action_json TEXT NOT NULL,
    auth_nonce TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    expires_at TEXT
);
CREATE INDEX IF NOT EXISTS activations_owner ON activations (owner);
CREATE INDEX IF NOT EXISTS activations_service ON activations (service_id);
CREATE INDEX IF NOT EXISTS activations_state ON activations (state);
CREATE INDEX IF NOT EXISTS activations_created ON activations (created_at);
-- The encrypted keystore of one activation's session key. Separate from `activations`
-- because that row is served to a browser and this one must never be: nothing reads
-- `keystore_json` except the tick and the revoke sweep, both of which ask for it by
-- activation id.
CREATE TABLE IF NOT EXISTS sessions (
    activation_id TEXT PRIMARY KEY,
    address TEXT NOT NULL,
    keystore_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    revoked_at TEXT
);
-- Nonces issued for a `create` that has no activation to carry one yet. Single-use: the
-- consuming DELETE is what makes it so, not a flag a second request could race.
CREATE TABLE IF NOT EXISTS activation_nonces (
    nonce TEXT PRIMARY KEY,
    owner TEXT NOT NULL,
    message TEXT NOT NULL,
    issued_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);
"""

# How long a create nonce stays spendable. Long enough for a person to read a wallet
# prompt, short enough that a nonce left open in a tab is not still open tomorrow.
ACTIVATION_NONCE_TTL_SECONDS = 600
MAX_ACTIVATION_PAGE = 200
# How many create nonces one owner may hold at once, and how many open persistent
# activations. Both bound work a stranger can ask this process to do on an address
# they do not control: a nonce costs a row, an open session costs a keystore and a
# slice of every tick.
MAX_LIVE_NONCES_PER_OWNER = 20
MAX_OPEN_ACTIVATIONS_PER_OWNER = 5


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _canary_run(row: sqlite3.Row) -> dict:
    run = dict(row)
    run["checks"] = json.loads(run.pop("checks_json"))
    return run


def _probe_run(row: sqlite3.Row) -> dict:
    run = dict(row)
    run["ok"] = bool(run["ok"])
    run["steps"] = json.loads(run.pop("steps_json"))
    return run
class StaleActivation(ValueError):
    """The stored activation moved between the read and the write, so nothing was written."""


def _strictly_after(written: str, held: str | None) -> str | None:
    """The stamp to store so this write moves the row past the value the caller held.

    Returns `None` when the stamp being written already sits after the held one, which is
    the ordinary case and needs no adjustment.

    Everything else is adjusted, because this column is the concurrency token rather than
    caller data. Two stamps sharing a microsecond, a clock that stepped backwards, a stamp
    a caller supplied through `at=` that is not a timestamp at all, one without a timezone
    that cannot even be compared with an aware one — each would leave the row holding a
    value a competing writer could still match. A stamp that cannot be ordered is replaced
    outright with this module's own, so the column stays parseable and monotonic and the
    same value can never come back around to be matched a second time.
    """
    if not held:
        return None
    try:
        holding = datetime.fromisoformat(held)
    except (ValueError, TypeError):
        # Not even the held value is an instant, so there is nothing to order against.
        # The row still must not keep a value a competing writer could match again.
        return _now()
    after_holding = (holding + timedelta(microseconds=1)).isoformat()
    try:
        if datetime.fromisoformat(written) > holding:
            return None
    except (ValueError, TypeError):
        # An unparseable stamp, or one written without a timezone beside one with it.
        # `_now()` alone would not do: these callers pass their own clock, and a frozen
        # or skewed one could put the row *behind* a value some reader still holds,
        # which is the shape that lets a stale write match a second time. Whichever of
        # the two is later is the one that keeps the column moving forwards.
        moved = _now()
        return moved if moved > after_holding else after_holding
    return after_holding

def _activation_row(activation: Activation, *, with_nonce: bool = True) -> tuple:
    """The row, in column order. `with_nonce=False` drops `auth_nonce` for the update
    statement, which must never write it — see `save_activation`."""
    return (
        activation.activation_id,
        activation.service_id,
        activation.category,
        activation.kind,
        activation.owner,
        activation.state,
        dumps(activation.quote.to_dict()),
        None if activation.policy is None else dumps(activation.policy),
        None if activation.session is None else dumps(activation.session),
        dumps(activation.inputs),
        None if activation.result is None else dumps(activation.result),
        dumps([receipt.to_dict() for receipt in activation.receipts]),
        dumps([event.to_dict() for event in activation.events]),
        dumps(activation.next_action.to_dict()),
        *((activation.auth_nonce,) if with_nonce else ()),
        activation.created_at,
        activation.updated_at,
        activation.expires_at,
    )


def _activation(row: sqlite3.Row) -> Activation:
    return Activation.from_dict(
        {
            "activation_id": row["activation_id"],
            "service_id": row["service_id"],
            "category": row["category"],
            "kind": row["kind"],
            "owner": row["owner"],
            "state": row["state"],
            "quote": loads(row["quote_json"]),
            "policy": loads(row["policy_json"]),
            "session": loads(row["session_json"]),
            "inputs": loads(row["inputs_json"]),
            "result": loads(row["result_json"]),
            "receipts": loads(row["receipts_json"], []),
            "events": loads(row["events_json"], []),
            "next_action": loads(row["next_action_json"]),
            "auth_nonce": row["auth_nonce"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "expires_at": row["expires_at"],
        }
    )


def _activation_filter(owner: str | None, state: str | None) -> tuple[str, tuple]:
    clauses = []
    args: tuple = ()
    if owner is not None:
        clauses.append("owner = ?")
        args += (owner,)
    if state is not None:
        clauses.append("state = ?")
        args += (state,)
    return (" WHERE " + " AND ".join(clauses) if clauses else ""), args


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
            journal_mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
            if str(journal_mode).lower() != "delete":
                raise RuntimeError(
                    "Docket requires SQLite DELETE journal mode; "
                    f"found {journal_mode!r}"
                )
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

    def latest_settled_payment(self, service_id: str) -> dict:
        """The newest hire payment for one service that actually reached `settled`.

        `settled` and nothing else. A row left at `settlement_unknown` is a payment whose
        facilitator answer never came back, and reading one as a settlement would turn the
        gap the recovery path exists to record into a fact the admission gate relies on.

        The result columns are named rather than selected with `*`: the row also carries
        the whole result and receipt bodies, and an admission decision needs none of them.
        """
        with self._conn() as conn:
            row = conn.execute(
                """SELECT nonce, payment_id, service_id, payer, recipient, asset, amount,
                          transaction_id, network, created_at, updated_at
                   FROM hire_payments
                   WHERE service_id = ? AND status = 'settled'
                   ORDER BY updated_at DESC, rowid DESC LIMIT 1""",
                (service_id,),
            ).fetchone()
        return dict(row) if row else {}

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

    def record_probe_run(
        self,
        *,
        started_at: str,
        finished_at: str,
        ok: bool,
        steps: list[dict],
    ) -> int:
        """Persist one synthetic production probe run, whole.

        Written after the run rather than around it, unlike a canary: a probe that dies
        mid-flight leaves no row at all, and no row reads as a probe that did not report
        rather than as one that reported success.
        """
        if not isinstance(ok, bool):
            raise ValueError("probe ok must be a bool")
        if not isinstance(steps, list) or not steps:
            raise ValueError("a probe run requires a non-empty list of steps")
        for step in steps:
            if not isinstance(step, dict) or not PROBE_STEP_FIELDS <= step.keys():
                raise ValueError(
                    "every probe step must carry " + ", ".join(sorted(PROBE_STEP_FIELDS))
                )
            if not isinstance(step["ok"], bool):
                raise ValueError("every probe step's ok must be a bool")
        if ok != all(step["ok"] for step in steps):
            raise ValueError("a probe run's ok must be the conjunction of its steps")
        try:
            encoded_steps = json.dumps(
                steps, sort_keys=True, ensure_ascii=False, allow_nan=False
            )
        except (TypeError, ValueError) as exc:
            raise ValueError("probe steps must be finite JSON values") from exc

        with self._conn() as conn:
            cursor = conn.execute(
                """INSERT INTO probe_runs (started_at, finished_at, ok, steps_json)
                   VALUES (?, ?, ?, ?)""",
                (started_at, finished_at, int(ok), encoded_steps),
            )
        return int(cursor.lastrowid)

    def latest_probe_runs(
        self, window_hours: int = PROBE_WINDOW_HOURS, *, now: datetime | None = None
    ) -> list[dict]:
        """Every probe run started inside the window, newest first.

        Bounded by the window rather than by a row count, because the figure a status page
        publishes is a rate over a stated period: a `LIMIT` would silently change the
        denominator the moment the probe timer fired more often than the page assumed.

        `now` is the instant the window is measured back from. A caller that has already
        fixed the observation time for the rest of its report passes it here, so the whole
        report is taken at one instant rather than at one instant plus this clock.
        """
        if (
            not isinstance(window_hours, int)
            or isinstance(window_hours, bool)
            or not 1 <= window_hours <= MAX_PROBE_WINDOW_HOURS
        ):
            raise ValueError(
                f"probe window must be between 1 and {MAX_PROBE_WINDOW_HOURS} hours"
            )
        observed_at = datetime.now(UTC) if now is None else now
        since = (observed_at - timedelta(hours=window_hours)).isoformat()
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT * FROM probe_runs
                   WHERE started_at >= ? ORDER BY id DESC""",
                (since,),
            ).fetchall()
        return [_probe_run(row) for row in rows]

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
                    f"snapshot {snapshot_id} cannot be promoted: it is not a complete "
                    "exhausted sweep"
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

    def upsert_external_listing(self, listing: dict) -> None:
        """Write one third-party listing, replacing whatever was held for that agent.

        The filter columns are derived from the document rather than passed in beside it,
        so a row cannot be indexed under a category or level its own JSON does not carry.
        """
        verification = listing.get("verification") or {}
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO external_listings
                   (agent_id, chain_id, category, level, hireable, source, updated_at,
                    listing_json)
                   VALUES (?,?,?,?,?,?,?,?)
                   ON CONFLICT (agent_id) DO UPDATE SET
                     chain_id = excluded.chain_id,
                     category = excluded.category,
                     level = excluded.level,
                     hireable = excluded.hireable,
                     source = excluded.source,
                     updated_at = excluded.updated_at,
                     listing_json = excluded.listing_json""",
                (
                    listing["agent_id"],
                    int(listing["chain_id"]),
                    listing.get("category"),
                    verification.get("level"),
                    1 if listing.get("hireable") else 0,
                    listing.get("source") or "registry_index",
                    listing.get("updated_at") or _now(),
                    json.dumps(listing, sort_keys=True, ensure_ascii=False),
                ),
            )

    def external_listing(self, agent_id: str) -> dict:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT listing_json FROM external_listings WHERE agent_id = ?",
                (agent_id,),
            ).fetchone()
        return json.loads(row["listing_json"]) if row else {}

    def external_listing_count(self) -> int:
        with self._conn() as conn:
            row = conn.execute("SELECT COUNT(*) AS n FROM external_listings").fetchone()
        return int(row["n"])

    def search_external_listings(
        self,
        *,
        query: str | None = None,
        category: str | None = None,
        level: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[dict], int]:
        """Listings matching every supplied filter, newest observation first.

        `query` is matched against the stored name and the capability text the listing was
        classified from — the same text the rule table read, so a reader searching the
        words on the card finds the card. `level` is an exact match and never a range:
        the level names do not sort into their own order, and `'live' < 'registered'`
        alphabetically is exactly the inversion that would publish a weaker listing as a
        stronger one. A caller wanting a floor reads `external_listings_by_level`, where
        the order is the one `marketplace.external.LEVELS` declares.
        """
        where = []
        args: list = []
        if category:
            where.append("category = ?")
            args.append(category)
        if level:
            where.append("level = ?")
            args.append(level)
        if query:
            where.append(
                "(LOWER(json_extract(listing_json, '$.name')) LIKE ? ESCAPE '\\' "
                "OR LOWER(json_extract(listing_json, '$.capabilities')) LIKE ? ESCAPE '\\' "
                "OR LOWER(agent_id) LIKE ? ESCAPE '\\')"
            )
            # `%` and `_` are LIKE wildcards, so an unescaped `%` typed into a search box
            # matches every row and reads as a search that found everything.
            escaped = (
                query.lower()
                .replace("\\", "\\\\")
                .replace("%", "\\%")
                .replace("_", "\\_")
            )
            pattern = f"%{escaped}%"
            args.extend([pattern, pattern, pattern])
        clause = (" WHERE " + " AND ".join(where)) if where else ""
        with self._conn() as conn:
            total = int(
                conn.execute(
                    f"SELECT COUNT(*) AS n FROM external_listings{clause}", args
                ).fetchone()["n"]
            )
            rows = conn.execute(
                f"SELECT listing_json FROM external_listings{clause} "
                f"ORDER BY {EXTERNAL_LEVEL_ORDER_SQL}, updated_at DESC, agent_id "
                "LIMIT ? OFFSET ?",
                [*args, max(limit, 0), max(offset, 0)],
            ).fetchall()
        return [json.loads(row["listing_json"]) for row in rows], total

    def external_listings_by_level(self) -> dict[str, int]:
        """How many listings stand at each level. `unverified` counts the NULL level."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT level, COUNT(*) AS n FROM external_listings GROUP BY level"
            ).fetchall()
        return {(row["level"] or "unverified"): int(row["n"]) for row in rows}

    def record_verification_run(
        self, agent_id: str, *, level: str, at: str, ok: bool, detail: dict
    ) -> int:
        with self._conn() as conn:
            cursor = conn.execute(
                """INSERT INTO verification_runs (agent_id, level, at, ok, detail_json)
                   VALUES (?,?,?,?,?)""",
                (
                    agent_id,
                    level,
                    at,
                    1 if ok else 0,
                    json.dumps(detail, sort_keys=True, ensure_ascii=False, default=str),
                ),
            )
        return int(cursor.lastrowid)

    def iter_verification_runs(self, agent_id: str, limit: int = 60) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT * FROM verification_runs WHERE agent_id = ?
                   ORDER BY id DESC LIMIT ?""",
                (agent_id, max(limit, 1)),
            ).fetchall()
        runs = []
        for row in rows:
            run = dict(row)
            run["ok"] = bool(run["ok"])
            run["detail"] = json.loads(run.pop("detail_json"))
            runs.append(run)
        return runs

    def issue_provider_claim(
        self, *, agent_id: str, nonce: str, issued_at: str
    ) -> None:
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO provider_claims (nonce, agent_id, issued_at)
                   VALUES (?,?,?)""",
                (nonce, agent_id, issued_at),
            )

    def provider_claim(self, nonce: str) -> dict:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM provider_claims WHERE nonce = ?", (nonce,)
            ).fetchone()
        return dict(row) if row else {}

    def settle_provider_claim(
        self, *, nonce: str, owner: str, verified_at: str
    ) -> bool:
        """Stamp a nonce as spent. False when it was already spent or never issued."""
        with self._conn() as conn:
            cursor = conn.execute(
                """UPDATE provider_claims SET owner = ?, verified_at = ?
                   WHERE nonce = ? AND verified_at IS NULL""",
                (owner, verified_at, nonce),
            )
        return cursor.rowcount == 1
    def payment_by_id(self, payment_id: str) -> dict:
        """One hire payment by its own id, decoded the way `payment_by_nonce` decodes it.

        An activation binds a payment it did not itself make — the buyer settled it
        through `POST /hire/{service_id}` and quotes the id back — so the lookup has to
        be by the identifier the buyer holds.
        """
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM hire_payments WHERE payment_id = ?", (payment_id,)
            ).fetchone()
        if row is None:
            return {}
        payment = dict(row)
        for field in ("result_json", "receipt_json"):
            if payment[field] is not None:
                payment[field.removesuffix("_json")] = json.loads(payment[field])
        return payment

    def create_activation(self, activation: Activation) -> None:
        """Insert one activation. A repeated id is an error, never an overwrite."""
        with self._conn() as conn:
            cursor = conn.execute(
                """INSERT INTO activations
                   (activation_id, service_id, category, kind, owner, state, quote_json,
                    policy_json, session_json, inputs_json, result_json, receipts_json,
                    events_json, next_action_json, auth_nonce, created_at, updated_at,
                    expires_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT DO NOTHING""",
                _activation_row(activation),
            )
        if cursor.rowcount != 1:
            raise ValueError(f"activation {activation.activation_id} already exists")

    def get_activation(self, activation_id: str) -> Activation | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM activations WHERE activation_id = ?", (activation_id,)
            ).fetchone()
        return _activation(row) if row else None

    def list_activations(
        self,
        owner: str | None = None,
        state: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Activation]:
        """Newest first, because an owner reading a list is looking for what just
        happened. Ordered by `created_at` and then by id, so two activations created in
        the same microsecond still come back in one fixed order rather than SQLite's."""
        if not 1 <= limit <= MAX_ACTIVATION_PAGE:
            raise ValueError(
                f"activation page size must be between 1 and {MAX_ACTIVATION_PAGE}"
            )
        if offset < 0:
            raise ValueError("activation page offset cannot be negative")
        sql, args = _activation_filter(owner, state)
        with self._conn() as conn:
            rows = conn.execute(
                f"SELECT * FROM activations{sql} "
                "ORDER BY created_at DESC, activation_id DESC LIMIT ? OFFSET ?",
                (*args, limit, offset),
            ).fetchall()
        return [_activation(row) for row in rows]

    def count_activations(
        self, owner: str | None = None, state: str | None = None
    ) -> int:
        sql, args = _activation_filter(owner, state)
        with self._conn() as conn:
            row = conn.execute(
                f"SELECT COUNT(*) AS n FROM activations{sql}", args
            ).fetchone()
        return int(row["n"])

    def save_activation(self, activation: Activation, *, expected_updated_at: str):
        """Write one activation back, refusing a row that moved underneath the caller.

        Two ticks, or a tick and an owner's revoke, can reach the same activation at the
        same time. Without this the later write would silently discard the earlier one's
        events — including, in the worst ordering, the record of a transaction that had
        already been broadcast. The read-modify-write is made safe by the row's own
        `updated_at` rather than by a lock the API would have to hold across a chain call.

        `auth_nonce` is deliberately NOT in the SET. `rotate_auth_nonce` is its only
        writer, and it runs before the work this saves — so writing the in-memory copy
        back here would restore the nonce that request just spent, and a replayed
        signature would be accepted a second time. The one column this statement must not
        touch is the one that makes a signature single-use.

        The guard is a timestamp, and two mutations can land inside the same microsecond
        — a clock's resolution is not a promise about ordering. So the stamp this writes
        is forced past the one it replaced: a row's `updated_at` strictly increases, and
        a second writer still holding the old value can therefore never match the row
        after the first writer has moved it. Without that, two writes sharing a
        microsecond were indistinguishable to the guard and the later one silently
        discarded the earlier — including, in the worst ordering, a broadcast it had
        already recorded. The cost is that `updated_at` can run up to a microsecond ahead
        of the clock under contention, which is a price worth paying for a
        compare-and-swap that actually swaps.
        """
        moved = _strictly_after(activation.updated_at, expected_updated_at)
        if moved is not None:
            activation.updated_at = moved
        with self._conn() as conn:
            cursor = conn.execute(
                """UPDATE activations
                   SET service_id = ?, category = ?, kind = ?, owner = ?, state = ?,
                       quote_json = ?, policy_json = ?, session_json = ?,
                       inputs_json = ?, result_json = ?, receipts_json = ?,
                       events_json = ?, next_action_json = ?,
                       created_at = ?, updated_at = ?, expires_at = ?
                   WHERE activation_id = ? AND updated_at = ?""",
                (
                    *_activation_row(activation, with_nonce=False)[1:],
                    activation.activation_id,
                    expected_updated_at,
                ),
            )
        if cursor.rowcount != 1:
            raise StaleActivation(
                f"{activation.activation_id} changed since it was read "
                f"(expected updated_at {expected_updated_at})"
            )

    def rotate_auth_nonce(
        self, activation_id: str, *, expected_nonce: str, new_nonce: str
    ) -> bool:
        """Spend one activation nonce and issue the next, in one statement.

        This is what makes a signature single-use. It deliberately leaves `updated_at`
        alone: the mutation that follows carries its own optimistic check against the
        value the caller read, and bumping the timestamp here would make every rotation
        invalidate the very write it exists to authorize.
        """
        with self._conn() as conn:
            cursor = conn.execute(
                """UPDATE activations SET auth_nonce = ?
                   WHERE activation_id = ? AND auth_nonce = ?""",
                (new_nonce, activation_id, expected_nonce),
            )
        return cursor.rowcount == 1

    def issue_activation_nonce(
        self, *, nonce: str, owner: str, message: str, now: datetime | None = None
    ) -> str:
        """Record a nonce a `create` may be signed against, and drop the expired ones."""
        moment = datetime.now(UTC) if now is None else now
        expires_at = moment + timedelta(seconds=ACTIVATION_NONCE_TTL_SECONDS)
        with self._conn() as conn:
            conn.execute(
                "DELETE FROM activation_nonces WHERE expires_at <= ?",
                (moment.isoformat(),),
            )
            # One owner cannot hold an unbounded number of live nonces: the route is
            # unauthenticated by design — anyone may ask for one — so the oldest are
            # dropped rather than left to accumulate a row per request.
            conn.execute(
                """DELETE FROM activation_nonces
                   WHERE owner = ? AND nonce NOT IN (
                       SELECT nonce FROM activation_nonces WHERE owner = ?
                       ORDER BY issued_at DESC, nonce DESC LIMIT ?
                   )""",
                (owner, owner, MAX_LIVE_NONCES_PER_OWNER - 1),
            )
            conn.execute(
                """INSERT INTO activation_nonces
                   (nonce, owner, message, issued_at, expires_at)
                   VALUES (?,?,?,?,?)""",
                (nonce, owner, message, moment.isoformat(), expires_at.isoformat()),
            )
        return expires_at.isoformat()

    def consume_activation_nonce(
        self, nonce: str, owner: str, now: datetime | None = None
    ) -> tuple[bool, str]:
        """Spend a create nonce, and hand back the message it was issued against.

        The DELETE is the single-use guarantee: two concurrent requests holding the same
        signature cannot both see a rowcount of one. The message comes back with it so the
        caller can check that the sentence being signed is the sentence this nonce was
        issued for — a nonce taken out for one service must not be spendable on another.
        """
        moment = datetime.now(UTC) if now is None else now
        with self._conn() as conn:
            row = conn.execute(
                """SELECT message FROM activation_nonces
                   WHERE nonce = ? AND owner = ? AND expires_at > ?""",
                (nonce, owner, moment.isoformat()),
            ).fetchone()
            cursor = conn.execute(
                """DELETE FROM activation_nonces
                   WHERE nonce = ? AND owner = ? AND expires_at > ?""",
                (nonce, owner, moment.isoformat()),
            )
        if cursor.rowcount != 1:
            return False, ""
        return True, (row["message"] if row else "")

    def create_session(
        self, activation_id: str, *, address: str, keystore_json: str
    ) -> None:
        with self._conn() as conn:
            cursor = conn.execute(
                """INSERT INTO sessions
                   (activation_id, address, keystore_json, created_at)
                   VALUES (?,?,?,?)
                   ON CONFLICT DO NOTHING""",
                (activation_id, address, keystore_json, _now()),
            )
        if cursor.rowcount != 1:
            raise ValueError(f"activation {activation_id} already holds a session key")

    def get_session(self, activation_id: str) -> dict:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM sessions WHERE activation_id = ?", (activation_id,)
            ).fetchone()
        return dict(row) if row else {}

    def mark_session_revoked(self, activation_id: str) -> bool:
        """Close a session once. A second call is False, not a second revocation."""
        with self._conn() as conn:
            cursor = conn.execute(
                """UPDATE sessions SET revoked_at = ?
                   WHERE activation_id = ? AND revoked_at IS NULL""",
                (_now(), activation_id),
            )
        return cursor.rowcount == 1

    def open_activation_count(self, owner: str, states) -> int:
        """How many of this owner's activations are in any of `states`."""
        placeholders = ",".join("?" for _ in states)
        with self._conn() as conn:
            row = conn.execute(
                f"""SELECT COUNT(*) AS n FROM activations
                    WHERE owner = ? AND state IN ({placeholders})""",
                (owner, *states),
            ).fetchone()
        return int(row["n"])

    def activations_by_state(self) -> dict[str, int]:
        """How many activations stand in each state. Empty where none exist."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT state, COUNT(*) AS n FROM activations GROUP BY state"
            ).fetchall()
        return {row["state"]: int(row["n"]) for row in rows}
