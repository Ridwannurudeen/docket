"""Resolve the real endpoint URLs of agents that declare they are callable.

The list view only reports which protocols an agent claims; the URL anything
would actually call lives on the per-agent card, one request each. Fetching a
card for every agent would cost a request per row of a registry that grows by
thousands a day, so enrichment is confined to the ~3.6% declaring A2A or MCP —
the only agents whose endpoints another agent could invoke at all. Each fetched
agent is marked as it lands, so an interrupted run resumes instead of re-spending
quota on cards it already has.
"""

from .scan8004 import Scan8004Client
from .signals import signals_for
from .store import Store

_DIRECT_FIELDS = (("a2a_endpoint", "a2a"), ("mcp_server", "mcp"), ("agent_url", "web"))


def _clean_url(value: object) -> str:
    """Card fields are arbitrary registry-supplied JSON, not necessarily strings."""
    return value.strip() if isinstance(value, str) else ""


def extract_endpoints(detail: dict) -> list[dict]:
    """Every URL an agent card offers, as `{"kind", "url"}`. Pure; never raises on bad shapes."""
    found: list[dict] = []
    for field, kind in _DIRECT_FIELDS:
        url = _clean_url(detail.get(field))
        if url:
            found.append({"kind": kind, "url": url})
    services = detail.get("services")
    if isinstance(services, dict):
        for service in services.values():
            url = _clean_url(service.get("endpoint")) if isinstance(service, dict) else ""
            if url:
                found.append({"kind": "service", "url": url})
    return found


def enrich_callable(
    store: Store,
    client: Scan8004Client,
    snapshot_id: int,
    *,
    limit: int | None = None,
) -> dict:
    """Fetch the card of every not-yet-enriched declared-callable agent in a snapshot."""
    # Drained before any network call: a suspended generator holds its sqlite connection open
    # for the whole sweep (Phase 1a).
    callable_agents = [a for a in store.iter_agents(snapshot_id) if signals_for(a)["callable"]]
    already = store.enriched_agent_ids(snapshot_id)
    pending = [a for a in callable_agents if a["agent_id"] not in already]
    skipped = len(callable_agents) - len(pending)
    if limit is not None:
        pending = pending[:limit]

    fetched = 0
    with_endpoints = 0
    endpoints = 0
    for agent in pending:
        detail = client.get_agent(agent["chain_id"], agent["token_id"])
        rows = [{"agent_id": agent["agent_id"], **e} for e in extract_endpoints(detail)]
        if rows:
            # Endpoints before the mark: a crash between the two writes must leave the agent
            # un-enriched and refetchable, never marked done with its endpoints lost.
            store.upsert_endpoints(rows, snapshot_id)
            with_endpoints += 1
            endpoints += len(rows)
        store.mark_enriched([agent["agent_id"]], snapshot_id)
        fetched += 1

    return {
        "considered": len(callable_agents),
        "fetched": fetched,
        "with_endpoints": with_endpoints,
        "endpoints": endpoints,
        "skipped_already_enriched": skipped,
    }
