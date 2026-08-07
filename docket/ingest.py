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


def ingest_bsc(
    store: Store,
    client: Scan8004Client,
    *,
    chain_id: int = 56,
    max_pages: int | None = None,
    snapshot_id: int | None = None,
) -> dict:
    """Sweep every page of the BSC registry into one snapshot.

    `snapshot_id` reuses an existing snapshot row; it does NOT resume the offset. The sweep
    always replays from offset 0 — idempotent, thanks to the store's primary key, but it
    re-spends quota. A true incremental resume via `store.max_token_id` is a follow-up.
    """
    first_items, expected = client.list_agents(chain_id, limit=MAX_LIMIT, offset=0)
    sid = snapshot_id if snapshot_id is not None else store.begin_snapshot(chain_id, expected)

    pages = 0
    offset = 0
    items = first_items
    highest = _highest_token_id(items)
    while items:
        store.upsert_agents(items, sid)
        pages += 1
        offset += MAX_LIMIT
        if max_pages is not None and pages >= max_pages:
            break
        items, latest_total = client.list_agents(chain_id, limit=MAX_LIMIT, offset=offset)
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
                break
            highest = page_high
        if pages % 50 == 0:
            logger.info("ingest: %d pages, %d stored", pages, store.agent_count(sid))

    sampled = store.agent_count(sid)
    store.finish_snapshot(sid, sampled, expected)
    return {
        "snapshot_id": sid,
        "sampled": sampled,
        "expected": expected,
        "dropped": max(expected - sampled, 0),
        "pages": pages,
    }
