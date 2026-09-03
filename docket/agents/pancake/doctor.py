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

from datetime import UTC, datetime

from .pools import PoolClient, is_plausible, net_fee_apr
from .positions import MAX_EXAMINED, PositionReader
from .tickmath import in_range, range_position_pct

POSITION_URL = "https://pancakeswap.finance/liquidity/{token_id}?chain=bsc"
# The statuses where the pool's own trading figures are worth quoting at all: a
# closed position is not in the pool, and an unreadable pool has no figures.
RANGE_STATUSES = ("in_range", "out_of_range_below", "out_of_range_above")
# How near an edge a live position has to sit before the edge is worth naming.
# Any tighter and the tool is inventing urgency out of ordinary price movement.
EDGE_MARGIN = 0.15
RATE_LIMITATION = (
    "The rates annualise one pool-wide 24-hour observation. They are not a forecast, "
    "realized position profit, or a claim that the same rate will continue. In "
    "particular the pool rate is not this position's rate: a v3 position earns in "
    "proportion to its share of the liquidity active at the traded tick, which this read "
    "does not measure, so a wide range earns less than the pool rate and a tight one "
    "earns more. The figures below apply the pool's rate to a declared notional and are "
    "labelled that way; they are a fixed-notional proxy, not this position's earnings."
)
BREAK_EVEN_LIMITATION = (
    "Cost-only break-even assumes a recentered position earns the observed net pool rate. "
    "It excludes realized impermanent loss, future rate changes, and any cost not included "
    "in the caller-declared estimate."
)
_DECISION_IMPACT_SECTION: dict | None = None


def pancake_headline(decision_impact: dict) -> dict:
    """The fixed-notional decision impact in presenter-ready order."""
    fixed_notional = decision_impact["dollars_at_notionals"]["notionals"][0]
    payback = decision_impact["break_even_shift"]
    reversals = decision_impact["ranking_reversals"]
    registration_state = decision_impact["registration_state"]
    statement = (
        f"At a declared ${fixed_notional['notional_usd']:,.0f} fixed notional, the median "
        f"annual fee overstatement across {fixed_notional['n_pools']} eligible pools is "
        f"${fixed_notional['median_annual_overstatement_usd']:,.2f}. Across "
        f"{payback['n_moves']} candidate moves, real payback arrives a median "
        f"{payback['median_days_later_than_gross_implies']:.2f} days later than gross "
        f"implies. Ranking reversals were {reversals['numerator']}/"
        f"{reversals['denominator']}. Registration state: {registration_state}."
    )
    return {
        "statement": statement,
        "fixed_notional_usd": fixed_notional["notional_usd"],
        "n_pools": fixed_notional["n_pools"],
        "median_annual_overstatement_usd": fixed_notional[
            "median_annual_overstatement_usd"
        ],
        "n_candidate_moves": payback["n_moves"],
        "median_payback_delay_days": payback["median_days_later_than_gross_implies"],
        "ranking_reversals": {
            "numerator": reversals["numerator"],
            "denominator": reversals["denominator"],
        },
        "registration_state": registration_state,
    }


def _decision_impact_section() -> dict:
    """Load the frozen decision-impact analysis once for this process."""
    global _DECISION_IMPACT_SECTION

    if _DECISION_IMPACT_SECTION is None:
        from docket.advantage.v2.report import decision_impact_section

        _DECISION_IMPACT_SECTION = decision_impact_section()
    return _DECISION_IMPACT_SECTION


def diagnose(
    position: dict,
    pool: dict | None,
    pool_stats: dict | None,
    *,
    declared_position_value_usd: float | None = None,
    estimated_recenter_cost_usd: float | None = None,
    decision_horizon_days: int | None = None,
) -> dict:
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
    economics = _economic_consequence(status, pool_stats, declared_position_value_usd)
    apr = economics["net_apr"]

    symbol0 = _symbol(row, "token0", position["token0"])
    symbol1 = _symbol(row, "token1", position["token1"])
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
        findings.extend(_pool_findings(pool_stats, economics, status))

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
    elif status == "in_range":
        actions = _in_range_actions(tick, lower, upper, pct, link)

    observation_block = (pool or {}).get("block_number") or position.get("block_number")
    observation_time = (pool or {}).get("observation_time") or position.get(
        "observation_time"
    )
    conditional_actions = _conditional_actions(
        status,
        actions,
        economics,
        estimated_recenter_cost_usd,
        decision_horizon_days,
    )

    return {
        "status": status,
        "in_range": status == "in_range",
        "range_position_pct": pct,
        "pool_net_apr": apr,
        "decision": _position_decision(position["token_id"], status),
        "verifiable_facts": {
            "pair": f"{symbol0}/{symbol1}",
            "position_id": position["token_id"],
            "token0": position["token0"],
            "token1": position["token1"],
            "current_tick": tick,
            "lower_tick": lower,
            "upper_tick": upper,
            "bsc_block": observation_block,
            "observation_time": observation_time,
        },
        "economic_consequence": economics,
        "conditional_actions": conditional_actions,
        "findings": findings,
        "actions": actions,
        "as_of_block": observation_block,
        "observed_at": observation_time,
        "computed_at": datetime.now(UTC).isoformat(),
    }


def report(
    address: str,
    *,
    reader: PositionReader | None = None,
    pools: PoolClient | None = None,
    limit: int | None = None,
    include_closed: bool = False,
    token_id: int | None = None,
    observation_block: int | None = None,
    declared_position_value_usd: float | None = None,
    estimated_recenter_cost_usd: float | None = None,
    decision_horizon_days: int | None = None,
    pool_rows: list[dict] | None = None,
    token_allowlist: set[str] | None = None,
    source_evidence: dict | None = None,
) -> dict:
    """Diagnose the v3 positions a wallet controls, held directly or staked.

    The rejected pools travel in the output rather than being filtered away in
    silence: a list the user cannot audit is worth less than one that shows what
    it refused and why.

    The same rule governs the positions that are not diagnosed. `limit` bounds
    how many open positions are returned, `token_id` selects one exact NFT, and
    `include_closed` decides whether unselected closed positions are worth
    returning. Every choice hands back a count: the output
    carries `positions_held`, `positions_examined` and `closed_skipped` so a
    truncated report says "37 of these were closed" rather than showing a short
    list and letting it pass for the whole wallet.
    """
    if (
        declared_position_value_usd is not None
        or estimated_recenter_cost_usd is not None
    ) and token_id is None:
        raise ValueError(
            "token_id is required when declaring a position value or recenter cost"
        )

    frozen_values = (pool_rows, token_allowlist, source_evidence)
    if any(value is not None for value in frozen_values) and not all(
        value is not None for value in frozen_values
    ):
        raise ValueError(
            "pool_rows, token_allowlist and source_evidence must be supplied together"
        )

    reader = reader or PositionReader()
    if pool_rows is not None:
        rows = pool_rows
        allowlist = token_allowlist
    else:
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
    read = reader.wallet_positions(
        address,
        limit=limit,
        include_closed=include_closed,
        token_id=token_id,
        observation_block=observation_block,
    )
    # Whatever block the wallet was actually read at is the one every pool is read at too,
    # including when the caller asked for "latest" — otherwise a slow scan diagnoses early
    # positions against a later price, and nothing in the output shows it happened.
    read_at_block = read.get("observation_block")
    for position in read["positions"]:
        # Only reached under `include_closed`. A zero-liquidity position is
        # `closed` whatever its pool is doing, so reading a pool only to ignore
        # it is four RPC calls spent to change nothing.
        if position["liquidity"] == 0:
            entries.append(
                {
                    "position": position,
                    "pool": None,
                    "diagnosis": diagnose(
                        position,
                        None,
                        None,
                        declared_position_value_usd=declared_position_value_usd,
                        estimated_recenter_cost_usd=estimated_recenter_cost_usd,
                        decision_horizon_days=decision_horizon_days,
                    ),
                }
            )
            continue
        key = (position["token0"], position["token1"], position["fee"])
        if key not in pool_cache:
            pool_cache[key] = reader.pool_state(
                *key,
                observation_block=read_at_block,
                archive_first=observation_block is not None,
            )
        pool = pool_cache[key]
        entries.append(
            {
                "position": position,
                "pool": pool,
                "diagnosis": diagnose(
                    position,
                    pool,
                    by_pool.get(str(pool.get("address") or "").lower()),
                    declared_position_value_usd=declared_position_value_usd,
                    estimated_recenter_cost_usd=estimated_recenter_cost_usd,
                    decision_horizon_days=decision_horizon_days,
                ),
            }
        )

    return {
        "address": address,
        "computed_at": datetime.now(UTC).isoformat(),
        "decision": _report_decision(read, entries),
        "pancake_headline": pancake_headline(_decision_impact_section()),
        "observation": {
            "bsc_block": read["observation_block"],
            "observation_time": read["observation_time"],
        },
        "target_token_id": read.get("target_token_id"),
        "target_found": read.get("target_found"),
        "positions_held": read["positions_held"],
        "positions_examined": read["positions_examined"],
        "closed_skipped": read["closed_skipped"],
        "open_skipped": read.get("open_skipped", 0),
        "scan_complete": read["scan_complete"],
        "stopped_by": read.get("stopped_by"),
        "coverage": _coverage_sentence(read),
        "primary_limitation": _primary_limitation(read, entries),
        "positions": entries,
        "pools": {"checked": len(rows), "rejected": rejected},
        "sources": source_evidence,
    }


def _position_decision(token_id: int, status: str) -> str:
    if status == "in_range":
        return (
            f"Position {token_id} is inside its range and can currently earn pool fees."
        )
    if status == "out_of_range_below":
        return (
            f"Position {token_id} is below its range and currently earns no pool fees."
        )
    if status == "out_of_range_above":
        return (
            f"Position {token_id} is above its range and currently earns no pool fees."
        )
    if status == "closed":
        return (
            f"Position {token_id} is closed and holds no pool liquidity, so it currently "
            "earns no pool fees."
        )
    return (
        f"Position {token_id}'s pool state could not be read, so whether it currently "
        "earns pool fees is unknown."
    )


def _economic_consequence(
    status: str,
    pool_stats: dict | None,
    declared_position_value_usd: float | None,
) -> dict:
    consequence = {
        "gross_apr": None,
        "net_apr": None,
        "overstatement_relative": None,
        "overstatement_percentage_points": None,
        "declared_position_value_usd": declared_position_value_usd,
        "declared_position_value_source": (
            "caller" if declared_position_value_usd is not None else None
        ),
        "annual_gross_usd": None,
        "annual_net_usd": None,
        "annual_overstatement_usd": None,
        "pool_net_apr_if_in_range": None,
        "pool_rate_at_declared_value_usd": None,
        "fee_usd_24h": None,
        "protocol_fee_usd_24h": None,
        "tvl_usd": None,
        "observation_window": "24 hours, annualised by multiplying by 365",
        "limitation": RATE_LIMITATION,
        "unavailable_reason": None,
    }
    if status not in RANGE_STATUSES:
        consequence["unavailable_reason"] = (
            "the position is closed, so no live pool rate or dollar consequence is quoted"
            if status == "closed"
            else "the current pool state could not be read, so no rate or dollar "
            "consequence is quoted"
        )
        return consequence
    if pool_stats is None:
        consequence["unavailable_reason"] = (
            "this pool is not in the explorer's top-pool snapshot, so no 24-hour fee row "
            "is available"
        )
        return consequence
    if not pool_stats.get("plausible"):
        consequence["unavailable_reason"] = (
            "the pool row failed the plausibility gate: "
            f"{pool_stats.get('reason') or 'no reason was supplied'}"
        )
        return consequence

    row = pool_stats.get("row") or {}
    if row.get("feeUSD24h") is None:
        consequence["unavailable_reason"] = (
            "feeUSD24h is absent from the pool row, so no fee rate is treated as measured"
        )
        return consequence
    if row.get("protocolFeeUSD24h") is None:
        consequence["unavailable_reason"] = (
            "protocolFeeUSD24h is absent from the pool row, so the protocol cut cannot be "
            "subtracted and no net rate is quoted"
        )
        return consequence

    tvl = float(row.get("tvlUSD") or 0)
    if tvl <= 0:
        consequence["unavailable_reason"] = (
            "tvlUSD is not positive, so no fee rate can be computed"
        )
        return consequence
    fee = float(row["feeUSD24h"])
    protocol_fee = float(row["protocolFeeUSD24h"])
    gross = fee * 365 / tvl
    net = net_fee_apr(row)
    gap = gross - net
    consequence.update(
        {
            "gross_apr": gross,
            "net_apr": net,
            "overstatement_relative": None if net == 0 else gap / net,
            "overstatement_percentage_points": gap * 100,
            "pool_net_apr_if_in_range": net if status == "in_range" else 0.0,
            "fee_usd_24h": fee,
            "protocol_fee_usd_24h": protocol_fee,
            "tvl_usd": tvl,
        }
    )
    if declared_position_value_usd is None:
        consequence["unavailable_reason"] = (
            "declared_position_value_usd was not supplied for this exact token_id; Docket "
            "has no trusted first-party source for this NFT's USD value"
        )
        return consequence

    consequence.update(
        {
            "annual_gross_usd": declared_position_value_usd * gross,
            "annual_net_usd": declared_position_value_usd * net,
            "annual_overstatement_usd": declared_position_value_usd * gap,
            "pool_rate_at_declared_value_usd": (
                declared_position_value_usd * net if status == "in_range" else 0.0
            ),
        }
    )
    return consequence


def _conditional_actions(
    status: str,
    actions: list[dict],
    economics: dict,
    estimated_recenter_cost_usd: float | None,
    decision_horizon_days: int | None,
) -> dict:
    result = {
        "actions": actions,
        "estimated_recenter_cost_usd": estimated_recenter_cost_usd,
        "estimated_recenter_cost_source": (
            "caller" if estimated_recenter_cost_usd is not None else None
        ),
        "cost_only_break_even_days": None,
        "decision_horizon_days": decision_horizon_days,
        "within_horizon": None,
        "limitation": BREAK_EVEN_LIMITATION,
        "unavailable_reason": None,
    }
    if not actions:
        result["unavailable_reason"] = (
            "no wait-versus-recenter comparison is available for a closed position"
            if status == "closed"
            else "no position-specific action is available because the current pool "
            "state is unknown"
        )
        return result

    missing = []
    if estimated_recenter_cost_usd is None:
        missing.append("estimated_recenter_cost_usd was not supplied by the caller")
    value = economics["declared_position_value_usd"]
    if value is None:
        missing.append("declared_position_value_usd was not supplied by the caller")
    net = economics["net_apr"]
    if net is None:
        missing.append("a quotable net APR is unavailable")
    elif net <= 0:
        missing.append("the observed net APR is not positive")
    if missing:
        result["unavailable_reason"] = "; ".join(missing)
        return result

    result["cost_only_break_even_days"] = estimated_recenter_cost_usd / (
        value * net / 365
    )
    if decision_horizon_days is not None:
        result["within_horizon"] = (
            result["cost_only_break_even_days"] <= decision_horizon_days
        )
    return result


def _report_decision(read: dict, entries: list[dict]) -> str:
    if entries:
        return " ".join(entry["diagnosis"]["decision"] for entry in entries)
    if read["positions_held"] == 0:
        return "This wallet holds no PancakeSwap v3 position NFT to diagnose."
    if not read["scan_complete"]:
        return (
            "No position decision is possible from this bounded read: no open position "
            "was diagnosed among the positions examined, and unread positions remain unknown."
        )
    if read.get("target_token_id") is not None:
        return (
            f"Position {read['target_token_id']} was not found among this wallet's "
            "PancakeSwap v3 position NFTs."
        )
    if read["closed_skipped"] == read["positions_examined"]:
        return (
            f"All {read['closed_skipped']} PancakeSwap v3 positions in this wallet are "
            "closed; none currently earns pool fees."
        )
    return "No active PancakeSwap v3 position was available to diagnose."


def _primary_limitation(read: dict, entries: list[dict]) -> str:
    if not read["scan_complete"]:
        return (
            "This scan stopped before the end of the wallet, so unread positions are unknown "
            "and no wallet-wide absence claim is possible."
        )
    if not entries:
        return (
            "No active position was available, so this run establishes no position-level "
            "economic consequence or decision impact."
        )
    if all(entry["diagnosis"]["status"] == "closed" for entry in entries):
        return (
            "The selected position is closed, so this run establishes no live fee rate, "
            "dollar consequence, or recenter break-even."
        )
    return (
        "The fee figures annualise one pool-wide 24-hour observation rather than realized "
        "position profit or a forecast, and current collectable fees are not simulated."
    )


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
    target = read.get("target_token_id")
    if target is not None and returned:
        state = (
            "is closed and holds no liquidity"
            if read["positions"][0]["liquidity"] == 0
            else "holds liquidity and is diagnosed below"
        )
        tail = f"the requested position {target} {state}"
        skipped = []
        if closed:
            skipped.append(f"{closed} other closed positions were skipped")
        if read.get("open_skipped"):
            skipped.append(
                f"{read['open_skipped']} other open positions were not selected"
            )
        if skipped:
            tail += "; " + ", and ".join(skipped)
    elif target is not None and complete:
        tail = f"the requested position {target} was not found in this wallet"
    elif target is not None:
        tail = (
            f"the requested position {target} was not found among the positions read so far, "
            "and whether it is among the unread positions is unknown"
        )
    elif returned:
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
        # The remedy depends on which bound stopped the read. `limit` is the caller's to
        # raise; MAX_EXAMINED is not, and telling them to raise `limit` in that case is a
        # instruction that cannot work.
        remedy = (
            "raise `limit` to return more"
            if read.get("stopped_by") == "limit"
            else (
                f"this read examines at most {MAX_EXAMINED} position NFTs and stopped at that "
                "ceiling, so raising `limit` will not reach further into this wallet"
            )
        )
        tail += (
            f". The read was bounded and did not reach the end of this wallet — {remedy}, and "
            "the positions not reached are unknown rather than absent"
        )
    return f"{scope}: {tail}."


def _pool_findings(pool_stats: dict | None, economics: dict, status: str) -> list[str]:
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
    if economics["net_apr"] is None:
        return [f"no fee rate is quoted: {economics['unavailable_reason']}"]

    row = pool_stats["row"]
    tvl = float(row.get("tvlUSD") or 0)
    gross = float(row.get("feeUSD24h") or 0)
    protocol = float(row.get("protocolFeeUSD24h") or 0)
    apr = economics["net_apr"]
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
            "kind": "recenter",
            "text": (
                f"if you expect the price to stay near tick {tick}, a range recentred there "
                "would earn fees again — opening one costs gas and turns this position's "
                "impermanent loss from unrealised into realised"
            ),
            "link": link,
        },
        {
            "kind": "wait",
            "text": (
                f"if you expect the price to return into [{lower}, {upper}), leaving the "
                "position untouched costs nothing and it starts earning again when the price "
                "comes back"
            ),
            "link": link,
        },
    ]


def _in_range_actions(
    tick: int, lower: int, upper: int, pct: float, link: str
) -> list[dict]:
    if pct >= 1 - EDGE_MARGIN:
        edge = f"the upper edge at tick {upper} is {upper - tick} ticks away"
    elif pct <= EDGE_MARGIN:
        edge = f"the lower edge at tick {lower} is {tick - lower} ticks away"
    else:
        edge = f"the current tick {tick} remains inside [{lower}, {upper})"
    return [
        {
            "kind": "wait",
            "text": (
                f"if you expect the price to remain inside [{lower}, {upper}), leaving the "
                f"position untouched costs no switching gas and keeps it earning; {edge}"
            ),
            "link": link,
        },
        {
            "kind": "recenter",
            "text": (
                f"if you expect the price to leave [{lower}, {upper}), a wider or recentred "
                "range may keep earning after the move, but opening one costs gas and "
                "realises the impermanent loss this position carries unrealised today"
            ),
            "link": link,
        },
    ]


def _symbol(row: dict | None, side: str, fallback: str) -> str:
    return str(((row or {}).get(side) or {}).get("symbol") or fallback)
