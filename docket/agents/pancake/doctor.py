"""The Range Doctor: what a PancakeSwap v3 position is doing, and nothing beyond that.

Read-only by construction. This module reads, computes and writes sentences; it
loads no key, builds no transaction and asks for no approval. Every action it
emits terminates at a link into PancakeSwap's own interface, where the user acts
for themselves. A tool with no code path to move funds does not need to be
trusted not to move them.

Three rules govern the wording, because on a read-only adviser the wording *is*
the product.

**Findings are facts carrying their own inputs.** "Current tick 66100 is above
the position's upper bound 66052" can be checked against the chain by whoever
reads it. "Your position is out of range" cannot, and asks to be believed
instead.

**Actions are conditional and priced.** Each names the belief it rests on ("if
you expect the price to stay near tick X") and what acting costs — gas, and the
impermanent loss that rebalancing converts from paper into realised. A bare
imperative would be advice, and nothing here has a view worth following.

**Clearing the plausibility gate is not an endorsement.** The gate rejects
numbers that cannot be true; it says nothing about numbers that merely should
not be trusted. The live top pools on 2026-08-08 included one turning over
twelve times its TVL in a day at a 29% annualised net fee rate — it passes,
because nothing about it is arithmetically impossible. So no sentence here is
phrased in a way that lets a pass read as approval, and a test enforces that by
banning the vocabulary of endorsement outright.
"""

from datetime import datetime, timezone

from .pools import PoolClient, is_plausible, net_fee_apr
from .positions import PositionReader
from .tickmath import in_range, range_position_pct

POSITION_URL = "https://pancakeswap.finance/liquidity/{token_id}?chain=bsc"
# The statuses where the pool's own trading figures are worth quoting at all: a
# closed position is not in the pool, and an unreadable pool has no figures.
RANGE_STATUSES = ("in_range", "out_of_range_below", "out_of_range_above")
# How near an edge a live position has to sit before the edge is worth naming.
# Any tighter and the tool is inventing urgency out of ordinary price movement.
EDGE_MARGIN = 0.15


def diagnose(position: dict, pool: dict | None, pool_stats: dict | None) -> dict:
    """One position's status, and the findings and conditional actions that follow from it.

    Pure: everything it needs arrives in the three arguments, so every branch is
    reachable from a fixture and none of them needs a network to test.

    `pool` is `PositionReader.pool_state` output, or None when it could not be
    read. `pool_stats` is `{"row", "plausible", "reason"}` built by `report`, or
    None when the pool is simply absent from the explorer's top list — three
    distinct absences that must not collapse into one, because "we did not fetch
    it", "we fetched it and refuse to quote it" and "there is no pool" are
    different things to tell someone about their own money.
    """
    lower = position["tick_lower"]
    upper = position["tick_upper"]
    tick = (pool or {}).get("tick")

    if position["liquidity"] == 0:
        status = "closed"
    elif tick is None:
        status = "unknown_pool"
    elif in_range(lower, upper, tick):
        status = "in_range"
    elif tick < lower:
        status = "out_of_range_below"
    else:
        status = "out_of_range_above"

    pct = None if tick is None else range_position_pct(lower, upper, tick)
    row = (pool_stats or {}).get("row")
    apr = None
    if status in RANGE_STATUSES and row and pool_stats.get("plausible"):
        apr = net_fee_apr(row)

    symbol0 = _symbol(row, "token0", "token0")
    symbol1 = _symbol(row, "token1", "token1")
    findings: list[str] = []
    actions: list[dict] = []
    link = POSITION_URL.format(token_id=position["token_id"])

    if status == "closed":
        findings.append(
            f"liquidity is 0, so token id {position['token_id']} holds nothing in the pool and "
            "earns no fees; the NFT itself still exists and is still readable"
        )
    elif status == "unknown_pool":
        findings.append(
            f"no pool state could be read for {position['token0']}/{position['token1']} at fee "
            f"tier {position['fee']}, so this position's range cannot be placed against a "
            "current price and nothing is claimed about where it sits"
        )
    elif status == "in_range":
        findings.append(
            f"current tick {tick} is inside the position's range [{lower}, {upper}), so this "
            "position is earning fees at the pool's rate right now"
        )
        findings.append(
            f"the price sits {pct:.0%} of the way from the lower bound {lower} to the upper "
            f"bound {upper}; earning stops at {upper}, which the pool counts as outside the range"
        )
    elif status == "out_of_range_below":
        findings.append(
            f"current tick {tick} is below the position's lower bound {lower}, so this position "
            "has earned no fees since the price left its range"
        )
        findings.append(
            f"below its range the position holds only {symbol0} — the swap out of {symbol1} "
            "already happened, on the way down through the range"
        )
    else:
        findings.append(
            f"current tick {tick} is at or above the position's upper bound {upper}, which the "
            "pool counts as outside the range, so this position has earned no fees since the "
            "price left it"
        )
        findings.append(
            f"above its range the position holds only {symbol1} — the swap out of {symbol0} "
            "already happened, on the way up through the range"
        )

    if status in RANGE_STATUSES:
        findings.extend(_pool_findings(pool_stats, apr, status))

    findings.append(
        f"positions() reports tokensOwed0={position['tokens_owed0']} and "
        f"tokensOwed1={position['tokens_owed1']} — the figures written when the position was "
        "last touched on-chain, not current uncollected fees; those need a collect() simulation "
        "this build does not run, so 0 here means 'not written since', not 'nothing owed'"
    )
    if position.get("staked"):
        findings.append(
            "this position's NFT is held by MasterChefV3, so it is staked in a farm; any farm "
            "rewards accrue outside the position and are not read here"
        )

    if status in ("out_of_range_below", "out_of_range_above"):
        actions = _out_of_range_actions(tick, lower, upper, link)
    elif status == "in_range" and pct >= 1 - EDGE_MARGIN:
        actions = [
            {
                "text": (
                    f"if you expect the price to keep rising past tick {upper}, this position "
                    f"stops earning there and it is {upper - tick} ticks away; a wider or "
                    "recentred range would keep it earning, and opening one costs gas and "
                    "realises the impermanent loss the position carries unrealised today"
                ),
                "link": link,
            }
        ]
    elif status == "in_range" and pct <= EDGE_MARGIN:
        actions = [
            {
                "text": (
                    f"if you expect the price to keep falling past tick {lower}, this position "
                    f"stops earning there and it is {tick - lower} ticks away; a wider or "
                    "recentred range would keep it earning, and opening one costs gas and "
                    "realises the impermanent loss the position carries unrealised today"
                ),
                "link": link,
            }
        ]

    return {
        "status": status,
        "in_range": status == "in_range",
        "range_position_pct": pct,
        "pool_net_apr": apr,
        "findings": findings,
        "actions": actions,
        "as_of_block": (pool or {}).get("block_number") or position.get("block_number"),
        "computed_at": datetime.now(timezone.utc).isoformat(),
    }


def report(
    address: str,
    *,
    reader: PositionReader | None = None,
    pools: PoolClient | None = None,
    limit: int | None = None,
    include_closed: bool = False,
) -> dict:
    """Diagnose the v3 positions a wallet controls, held directly or staked.

    The rejected pools travel in the output rather than being filtered away in
    silence: a list the user cannot audit is worth less than one that shows what
    it refused and why.

    The same rule governs the positions that are not diagnosed. `limit` bounds
    how many are read at all and `include_closed` decides whether the ones
    holding nothing are worth returning, and both hand back a count: the output
    carries `positions_held`, `positions_examined` and `closed_skipped` so a
    truncated report says "37 of these were closed" rather than showing a short
    list and letting it pass for the whole wallet.
    """
    reader = reader or PositionReader()
    borrowed = pools is not None
    client = pools or PoolClient()
    try:
        rows = client.top_pools()
        allowlist = client.token_allowlist()
    finally:
        if not borrowed:
            client.close()

    by_pool: dict[str, dict] = {}
    rejected: list[dict] = []
    for row in rows:
        ok, reason = is_plausible(row, allowlist)
        by_pool[str(row.get("id") or "").lower()] = {
            "row": row,
            "plausible": ok,
            "reason": reason,
        }
        if not ok:
            rejected.append(
                {
                    "pool": row.get("id"),
                    "pair": f"{_symbol(row, 'token0', '?')}/{_symbol(row, 'token1', '?')}",
                    "fee_tier": row.get("feeTier"),
                    "reason": reason,
                }
            )

    pool_cache: dict[tuple, dict] = {}
    entries = []
    read = reader.wallet_positions(address, limit=limit, include_closed=include_closed)
    for position in read["positions"]:
        # Only reached under `include_closed`. A zero-liquidity position is
        # `closed` whatever its pool is doing, so reading a pool only to ignore
        # it is four RPC calls spent to change nothing.
        if position["liquidity"] == 0:
            entries.append(
                {
                    "position": position,
                    "pool": None,
                    "diagnosis": diagnose(position, None, None),
                }
            )
            continue
        key = (position["token0"], position["token1"], position["fee"])
        if key not in pool_cache:
            pool_cache[key] = reader.pool_state(*key)
        pool = pool_cache[key]
        entries.append(
            {
                "position": position,
                "pool": pool,
                "diagnosis": diagnose(
                    position, pool, by_pool.get(str(pool.get("address") or "").lower())
                ),
            }
        )

    return {
        "address": address,
        "computed_at": datetime.now(timezone.utc).isoformat(),
        "positions_held": read["positions_held"],
        "positions_examined": read["positions_examined"],
        "closed_skipped": read["closed_skipped"],
        "scan_complete": read["scan_complete"],
        "coverage": _coverage_sentence(read),
        "positions": entries,
        "pools": {"checked": len(rows), "rejected": rejected},
    }


def _coverage_sentence(read: dict) -> str:
    """What the scan covered, in one sentence, always present.

    An empty `positions` list is the single most misleading thing this agent can return: it
    looks identical whether the wallet holds nothing, holds only closed positions, or holds
    open ones the read never reached. A caller who gets `[]` and no sentence has been told
    nothing and may reasonably conclude their positions are fine.
    """
    held = read["positions_held"]
    examined = read["positions_examined"]
    closed = read["closed_skipped"]
    complete = read["scan_complete"]
    returned = len(read["positions"])

    if held == 0:
        return "This wallet holds no PancakeSwap v3 position NFTs, directly or staked."

    scope = (
        f"of the {held} position NFTs this wallet holds, {examined} were read"
        if examined < held
        else f"all {held} of this wallet's position NFTs were read"
    )
    if returned:
        tail = f"{returned} hold liquidity and are diagnosed below, and {closed} are closed"
    elif closed == examined and complete:
        tail = (
            f"every one of the {closed} is closed — they hold no liquidity, so there is no "
            "position to diagnose and nothing here is earning or losing fees"
        )
    elif closed == examined:
        tail = (
            f"all {closed} read so far are closed, and the read stopped before the end of the "
            "wallet, so whether the rest are open is unknown"
        )
    else:
        tail = f"{closed} of them are closed"

    if not complete:
        tail += (
            ". The read was bounded and did not reach the end of this wallet — raise `limit` "
            "to return more, and the positions not reached are unknown rather than absent"
        )
    return f"{scope}: {tail}."


def _pool_findings(
    pool_stats: dict | None, apr: float | None, status: str
) -> list[str]:
    if pool_stats is None:
        return [
            "this pool is not among the explorer's top pools by TVL, so no 24h fee figures were "
            "fetched for it and no fee rate is quoted here"
        ]
    if not pool_stats.get("plausible"):
        return [
            "the pool's reported figures did not pass the plausibility gate — "
            f"{pool_stats.get('reason')} — so no fee rate is quoted from them"
        ]

    row = pool_stats["row"]
    tvl = float(row.get("tvlUSD") or 0)
    gross = float(row.get("feeUSD24h") or 0)
    protocol = float(row.get("protocolFeeUSD24h") or 0)
    findings = [
        f"the pool charged ${gross:,.0f} of fees over 24h against ${tvl:,.0f} of TVL and "
        f"${protocol:,.0f} of that went to the protocol, leaving {apr:.1%} — that is one day's "
        "net fee take annualised, not a forecast and not an expected return",
        "those figures cleared a plausibility gate that only rejects numbers which cannot be "
        "true; clearing it says nothing about the pool, its tokens, or what happens next",
    ]
    if status != "in_range":
        findings.append(
            f"this position is not earning any part of that {apr:.1%} rate while it sits outside "
            "its range"
        )
    return findings


def _out_of_range_actions(tick: int, lower: int, upper: int, link: str) -> list[dict]:
    return [
        {
            "text": (
                f"if you expect the price to stay near tick {tick}, a range recentred there "
                "would earn fees again — opening one costs gas and turns this position's "
                "impermanent loss from unrealised into realised"
            ),
            "link": link,
        },
        {
            "text": (
                f"if you expect the price to return into [{lower}, {upper}), leaving the "
                "position untouched costs nothing and it starts earning again when the price "
                "comes back"
            ),
            "link": link,
        },
    ]


def _symbol(row: dict | None, side: str, fallback: str) -> str:
    return str(((row or {}).get(side) or {}).get("symbol") or fallback)
