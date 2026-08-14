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


def _sweep(
    store: Store,
    client: Scan8004Client,
    *,
    chain_id: int,
    max_pages: int | None,
    snapshot_id: int | None,
    min_feedbacks: int | None = None,
) -> dict:
    """Page through one `list_agents` query into one snapshot.

    `min_feedbacks` narrows the query server-side and is sent on every page, so `expected` is
    the total for the filtered query — not the registry total.
    """
    first_items, expected = client.list_agents(
        chain_id, limit=MAX_LIMIT, offset=0, min_feedbacks=min_feedbacks
    )
    # Persisted beside `expected`, because the two are only readable together: 506 of 506 is a
    # complete sweep of the agents with feedback, and a census of nothing.
    population = "all" if min_feedbacks is None else f"min_feedbacks>={min_feedbacks}"
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

    sampled = store.agent_count(sid)
    store.finish_snapshot(sid, sampled, expected, stop_reason=stop_reason)
    return {
        "snapshot_id": sid,
        "sampled": sampled,
        "expected": expected,
        "dropped": max(expected - sampled, 0),
        "pages": pages,
        "stop_reason": stop_reason,
    }


def ingest_bsc(
    store: Store,
    client: Scan8004Client,
    *,
    chain_id: int = 56,
    max_pages: int | None = None,
    snapshot_id: int | None = None,
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
        store, client, chain_id=chain_id, max_pages=max_pages, snapshot_id=snapshot_id
    )


def ingest_targeted(
    store: Store,
    client: Scan8004Client,
    *,
    chain_id: int = 56,
    min_feedbacks: int = 1,
    snapshot_id: int | None = None,
    max_pages: int | None = None,
) -> dict:
    """Sweep only the agents the registry itself can filter down to.

    Of 247,278 BSC agents on 2026-08-07, 506 had any feedback at all — every slice worth
    publishing about is a fraction of a percent of the chain and is filterable server-side,
    so a filtered sweep reaches the end of its query where a full one cannot.

    `expected` is the total the API reports for THIS filtered query, so `min_feedbacks` is
    returned alongside it: a filtered total read as a registry total is the exact conflation
    this project exists not to publish.
    """
    result = _sweep(
        store,
        client,
        chain_id=chain_id,
        max_pages=max_pages,
        snapshot_id=snapshot_id,
        min_feedbacks=min_feedbacks,
    )
    return {**result, "min_feedbacks": min_feedbacks}
