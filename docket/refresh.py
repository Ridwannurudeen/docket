"""Refresh the served ERC-8004 snapshot without exposing a partial pipeline run."""

import os
import socket
from collections.abc import Mapping

import httpx

from .enrich import enrich_callable
from .ingest import ingest_targeted
from .liveness import probe_snapshot
from .scan8004 import Scan8004Client
from .store import COMPLETE_STOP_REASON, Store

CHAIN_ID = 56
MIN_FEEDBACKS = 1
PROBE_KINDS = ("a2a", "mcp")


class RefreshRefused(RuntimeError):
    """The candidate did not satisfy the conditions required for promotion."""


def _candidate(store: Store, result: dict) -> dict:
    snapshot_id = result["snapshot_id"]
    row = store.snapshot(snapshot_id)
    if (
        row.get("finished_at") is None
        or row.get("sampled") is None
        or row.get("expected") is None
        or row["sampled"] <= 0
        or row["sampled"] != row["expected"]
        or row.get("stop_reason") != COMPLETE_STOP_REASON
        or row.get("promoted_at") is not None
    ):
        raise RefreshRefused(
            f"candidate snapshot {snapshot_id} refused: "
            f"stop_reason={row.get('stop_reason')!r}, "
            f"sampled={row.get('sampled')!r}, expected={row.get('expected')!r}"
        )
    return row


def refresh_once(
    store: Store,
    client: Scan8004Client,
    *,
    chain_id: int = CHAIN_ID,
    min_feedbacks: int = MIN_FEEDBACKS,
    owned_agent_ids: tuple[str, ...] = (),
    max_pages: int | None = None,
    probe_client: httpx.Client | None = None,
    resolver=socket.getaddrinfo,
) -> dict:
    """Ingest, enrich and probe one candidate, then expose it in one final step."""
    ingestion = ingest_targeted(
        store,
        client,
        chain_id=chain_id,
        min_feedbacks=min_feedbacks,
        max_pages=max_pages,
        owned_agent_ids=owned_agent_ids,
        promote=False,
    )
    snapshot_id = ingestion["snapshot_id"]
    _candidate(store, ingestion)

    enrichment = enrich_callable(store, client, snapshot_id)
    enriched = store.enriched_agent_ids(snapshot_id)
    if len(enriched) != enrichment["considered"]:
        raise RefreshRefused(
            f"candidate snapshot {snapshot_id} refused: "
            f"enriched={len(enriched)}, callable={enrichment['considered']}"
        )

    targets = sum(
        1 for kind in PROBE_KINDS for _ in store.iter_endpoints(snapshot_id, kind=kind)
    )
    liveness = probe_snapshot(
        store,
        snapshot_id,
        client=probe_client,
        kinds=PROBE_KINDS,
        resolver=resolver,
    )
    observations = sum(1 for _ in store.iter_liveness(snapshot_id))
    if liveness["probed"] != targets or observations != targets:
        raise RefreshRefused(
            f"candidate snapshot {snapshot_id} refused: "
            f"targets={targets}, probed={liveness['probed']}, observations={observations}"
        )

    _candidate(store, ingestion)
    store.promote_snapshot(snapshot_id)
    return {
        "snapshot_id": snapshot_id,
        "ingest": ingestion,
        "enrichment": enrichment,
        "liveness": liveness,
    }


def owned_agent_ids_from_environment(environment: Mapping[str, str]) -> tuple[str, ...]:
    value = environment.get("DOCKET_OWNED_AGENT_IDS")
    if value is None or not value.strip():
        return ()
    agent_ids = tuple(part.strip() for part in value.split(","))
    if any(not agent_id for agent_id in agent_ids):
        raise ValueError(
            "DOCKET_OWNED_AGENT_IDS must be a comma-separated list of agent ids"
        )
    return agent_ids


def run_from_environment(environment: Mapping[str, str] | None = None) -> dict:
    environment = os.environ if environment is None else environment
    database = environment.get("DOCKET_DB", "").strip()
    if not database:
        raise ValueError("DOCKET_DB is required")
    owned_agent_ids = owned_agent_ids_from_environment(environment)
    with Scan8004Client() as client:
        return refresh_once(
            Store(database),
            client,
            owned_agent_ids=owned_agent_ids,
        )


def main() -> int:
    try:
        result = run_from_environment()
    except Exception as exc:
        print(f"Docket refresh: failed ({type(exc).__name__}: {exc})")
        return 1
    print(f"Docket refresh: promoted snapshot {result['snapshot_id']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
