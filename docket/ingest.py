"""Full-registry sweep of BSC ERC-8004 agents into a dated snapshot.

Ordering is ascending token_id on purpose: the registry grows by thousands of
agents per day, and any ordering that puts new rows at the front shifts the
paginator's window mid-sweep and silently skips agents. Ascending token_id
appends growth after the cursor; the store's primary key absorbs overlap.

`sampled` is always counted from the store, never from pages served, so a
repeating or overlapping paginator cannot inflate a published number.
"""

import logging
import re

from .scan8004 import MAX_LIMIT, Scan8004Client
from .store import Store

logger = logging.getLogger(__name__)

_AGENT_ID = re.compile(
    r"(?P<chain_id>0|[1-9][0-9]*):"
    r"(?P<registry>0x[0-9a-fA-F]{40}):"
    r"(?P<token_id>0|[1-9][0-9]*)"
)


def _highest_token_id(items: list[dict]) -> int:
    """Highest numeric token_id in a page; -1 when none parse."""
    best = -1
    for item in items:
        try:
            token = int(item.get("token_id"))
        except (TypeError, ValueError):
            continue
        best = max(best, token)
    return best


def _owned_targets(agent_ids: tuple[str, ...], chain_id: int) -> list[tuple[str, str]]:
    targets = []
    seen = set()
    for value in agent_ids:
        match = _AGENT_ID.fullmatch(value.strip()) if isinstance(value, str) else None
        if match is None or int(match["chain_id"]) != chain_id:
            raise ValueError(
                f"owned agent id {value!r} must be "
                f"{chain_id}:<20-byte registry address>:<token id>"
            )
        normalized = (
            f"{chain_id}:{match['registry'].lower()}:{int(match['token_id'])}"
        )
        if normalized not in seen:
            targets.append((normalized, match["token_id"]))
            seen.add(normalized)
    return targets


def _owned_detail(detail: dict, expected_agent_id: str, token_id: str, chain_id: int) -> int:
    actual_agent_id = detail.get("agent_id")
    if (
        not isinstance(actual_agent_id, str)
        or actual_agent_id.lower() != expected_agent_id
    ):
        raise ValueError(
            f"owned agent lookup for {expected_agent_id} returned agent_id "
            f"{actual_agent_id!r}"
        )
    try:
        actual_chain_id = int(detail.get("chain_id"))
        actual_token_id = str(int(detail.get("token_id")))
        total_feedbacks = int(detail.get("total_feedbacks"))
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"owned agent lookup for {expected_agent_id} returned malformed identity fields"
        ) from exc
    if (
        actual_chain_id != chain_id
        or actual_token_id != str(int(token_id))
        or total_feedbacks < 0
    ):
        raise ValueError(
            f"owned agent lookup for {expected_agent_id} returned mismatched identity fields"
        )
    return total_feedbacks


def _sweep(
    store: Store,
    client: Scan8004Client,
    *,
    chain_id: int,
    max_pages: int | None,
    snapshot_id: int | None,
    min_feedbacks: int | None = None,
    owned_agent_ids: tuple[str, ...] = (),
    promote: bool = True,
) -> dict:
    """Page through one `list_agents` query into one snapshot.

    `min_feedbacks` narrows the query server-side and is sent on every page, so `expected` is
    the total for the filtered query — not the registry total.
    """
    owned_targets = _owned_targets(owned_agent_ids, chain_id)
    first_items, expected = client.list_agents(
        chain_id, limit=MAX_LIMIT, offset=0, min_feedbacks=min_feedbacks
    )
    # Persisted beside `expected`, because the two are only readable together: 506 of 506 is a
    # complete sweep of the agents with feedback, and a census of nothing.
    population = "all" if min_feedbacks is None else f"min_feedbacks>={min_feedbacks}"
    if owned_targets:
        owned_population = ",".join(agent_id for agent_id, _ in owned_targets)
        population = f"{population} OR agent_id in ({owned_population})"
    sid = (
        snapshot_id
        if snapshot_id is not None
        else store.begin_snapshot(chain_id, expected, population)
    )

    pages = 0
    offset = 0
    items = first_items
    highest = _highest_token_id(items)
    # A clean finish is assigned only by the loop's no-break path. Starting with the promotable
    # reason would let a future `break` that forgot its classification fail open.
    stop_reason: str | None = None
    while items:
        store.upsert_agents(items, sid)
        pages += 1
        offset += MAX_LIMIT
        if max_pages is not None and pages >= max_pages:
            stop_reason = "max_pages"
            break
        items, latest_total = client.list_agents(
            chain_id, limit=MAX_LIMIT, offset=offset, min_feedbacks=min_feedbacks
        )
        if latest_total > expected:
            expected = latest_total  # registry grew mid-sweep; report it, don't hide it
        if items:
            page_high = _highest_token_id(items)
            if page_high <= highest:
                # An ascending sweep must strictly advance. A page that doesn't means the API
                # is ignoring `offset`; without this an unbounded sweep would loop forever.
                logger.warning(
                    "ingest: page %d did not advance past token_id %d; stopping early",
                    pages + 1,
                    highest,
                )
                stop_reason = "not_advancing"
                break
            highest = page_high
        if pages % 50 == 0:
            logger.info("ingest: %d pages, %d stored", pages, store.agent_count(sid))
    else:
        stop_reason = "exhausted"

    if stop_reason is None:
        raise RuntimeError("ingest sweep stopped without a classified reason")

    stored_agent_ids = {
        agent["agent_id"].lower() for agent in store.iter_agents(sid)
    }
    owned_agents_added = 0
    for expected_agent_id, token_id in owned_targets:
        detail = client.get_agent(chain_id, token_id)
        total_feedbacks = _owned_detail(
            detail, expected_agent_id, token_id, chain_id
        )
        if expected_agent_id not in stored_agent_ids:
            if min_feedbacks is not None and total_feedbacks < min_feedbacks:
                expected += 1
            owned_agents_added += 1
        store.upsert_agents([detail], sid)
        stored_agent_ids.add(expected_agent_id)

    sampled = store.agent_count(sid)
    store.finish_snapshot(
        sid,
        sampled,
        expected,
        stop_reason=stop_reason,
        promote=promote,
    )
    return {
        "snapshot_id": sid,
        "sampled": sampled,
        "expected": expected,
        "dropped": max(expected - sampled, 0),
        "pages": pages,
        "stop_reason": stop_reason,
        "owned_agents_added": owned_agents_added,
    }


def ingest_bsc(
    store: Store,
    client: Scan8004Client,
    *,
    chain_id: int = 56,
    max_pages: int | None = None,
    snapshot_id: int | None = None,
    promote: bool = True,
) -> dict:
    """Sweep every page of the BSC registry into one snapshot.

    A full sweep is impractical past ~100k agents — deep OFFSET pages exceed the client's 30s
    timeout and a retry replays from offset 0 — so `ingest_targeted` is the supported path for
    the listable subset.

    `snapshot_id` reuses an existing snapshot row; it does NOT resume the offset. The sweep
    always replays from offset 0 — idempotent, thanks to the store's primary key, but it
    re-spends quota. A true incremental resume via `store.max_token_id` is a follow-up.
    """
    return _sweep(
        store,
        client,
        chain_id=chain_id,
        max_pages=max_pages,
        snapshot_id=snapshot_id,
        promote=promote,
    )


def ingest_targeted(
    store: Store,
    client: Scan8004Client,
    *,
    chain_id: int = 56,
    min_feedbacks: int = 1,
    snapshot_id: int | None = None,
    max_pages: int | None = None,
    owned_agent_ids: tuple[str, ...] = (),
    promote: bool = True,
) -> dict:
    """Sweep only the agents the registry itself can filter down to.

    Of 247,278 BSC agents on 2026-08-07, 506 had any feedback at all — every slice worth
    publishing about is a fraction of a percent of the chain and is filterable server-side,
    so a filtered sweep reaches the end of its query where a full one cannot.

    `expected` is the total the API reports for THIS filtered query, plus each explicit owned
    agent that falls outside it. The composite population is persisted with the snapshot, so
    a filtered total read as a registry total is the exact conflation this project exists not
    to publish. `promote=False` leaves a finished candidate hidden while enrichment and probes
    run.
    """
    result = _sweep(
        store,
        client,
        chain_id=chain_id,
        max_pages=max_pages,
        snapshot_id=snapshot_id,
        min_feedbacks=min_feedbacks,
        owned_agent_ids=owned_agent_ids,
        promote=promote,
    )
    return {**result, "min_feedbacks": min_feedbacks}
