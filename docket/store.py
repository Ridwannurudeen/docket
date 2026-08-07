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


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Store:
    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as conn:
            conn.executescript(SCHEMA)

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        try:
            with conn:  # commits on clean exit; contextlib.closing would silently drop writes
                yield conn
        finally:
            conn.close()

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
                    str(r.get("token_id", "")),
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
        with self._conn() as conn:
            row = conn.execute(
                "SELECT id FROM snapshots WHERE chain_id = ? ORDER BY id DESC LIMIT 1",
                (chain_id,),
            ).fetchone()
        return int(row["id"]) if row else None

    def snapshot(self, snapshot_id: int) -> dict:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM snapshots WHERE id = ?", (snapshot_id,)).fetchone()
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
