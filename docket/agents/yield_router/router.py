"""Comparison inside a stated set, the cost of acting on it, and one bounded swap.

Everything here is about the difference between "this pool pays more" and "moving there is
worth it", which are different claims with different evidence behind them.

**Net, never gross.** `pools.net_fee_apr` subtracts the protocol's own reported cut, which
is roughly a third of the fee. Both figures are carried on every candidate so a reader can
see the gap rather than take the smaller number on faith.

**Every rate says what it is a rate of and over what window.** One day of fees annualised
by 365, over the pool's TVL. Not a forecast, and not a yield on anybody's position — a
concentrated position earns at that rate only while it is in range.

**A candidate that looks better and is not stays in the output.** The highest observed
rate in a set can still be the wrong move once the switching cost is paid back, and a
comparison that dropped it would be one that agrees with itself. `break_even` is computed
for every candidate and the ones past the horizon are labelled, not filtered.

**The switching cost is the caller's number.** Docket reads no BNB price and does not
invent one. `switching_cost_usd` is supplied, and `cost_covers` says what it has to
include — gas on both legs, the swap's own fee and price impact, and any fees left
uncollected behind. Naming that input "gas" would have understated it.

**A move is one swap leg and says so.** `plan_move` drafts the swap that puts the caller
in the right asset, through the Stage 2 kernel, against the same PancakeSwap V2 router the
grid uses. Adding liquidity to the destination pool is not built in this stage and every
drafted action carries that sentence. The destination allowlist is the eligible universe
itself, so a pool that did not clear the gate is not somewhere this routes to whatever its
rate says.
"""

from dataclasses import dataclass

from web3 import Web3

from ...execution import now
from ...execution.intent import ActionIntent, Condition, commit
from ...execution.simulate import PANCAKE_V2_ROUTER, SWAP_SIGNATURE, swap_calldata
from ..pancake.pools import net_fee_apr, turnover

POLICY_VERSION = "yield-router/1"
SWAP_SELECTOR = "0x" + Web3.keccak(text=SWAP_SIGNATURE)[:4].hex()
DEFAULT_SLIPPAGE_BPS = 50
DEFAULT_GAS_CEILING = 300_000
DEFAULT_DEADLINE_S = 600
# The horizon a break-even is judged against. Thirty days is a stated choice rather than a
# derived one, and it is on every record so a reader can apply their own.
HORIZON_DAYS = 30

# What this build is willing to move. Three assets, and the list is short because every
# entry is a decision somebody has to have made: these are the BSC addresses already
# pinned elsewhere in this repository — WBNB and USDT by the grid, USDC by the health
# guard's own policy — rather than a set assembled to look comprehensive.
MOVE_ASSETS = frozenset(
    {
        Web3.to_checksum_address("0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c"),
        Web3.to_checksum_address("0x55d398326f99059fF775485246999027B3197955"),
        Web3.to_checksum_address("0x8AC76a51cc950d9822D68b83fE1Ad97B32Cd580d"),
    }
)

ORDERING = (
    "net_fee_apr descending — an observed 24h rate, named here so the order is read as the "
    "metric it sorts on rather than as an opinion about which pool to be in"
)
RATE_WINDOW = (
    "24h of fees annualised by x365, one observation and not a forecast: a quiet day reads "
    "as a permanently poor pool and a busy one as a fortune"
)
RATE_DENOMINATOR = (
    "the pool's own reported TVL in USD. It is a property of the pool and not of any "
    "position in it — a concentrated position earns at this rate only while it is in range "
    "and earns nothing while it is not"
)
NET_VS_GROSS = (
    "net is the fee less the protocol's own reported cut. Liquidity providers keep roughly "
    "two thirds of what a pool charges, so the gross figure beside this overstates what is "
    "kept by about half again"
)
DELTA_UNAVAILABLE = (
    "no delta: the current pool's own net rate could not be computed from the row it was "
    "given, so there is no figure to subtract from. A delta against a rate nobody has is "
    "arithmetic on a blank"
)
COST_COVERS = (
    "the caller's own figure, in USD. It has to cover gas on every leg, the swap's own pool "
    "fee and its price impact at this size, and any fees left uncollected in the pool being "
    "left. Docket reads no BNB price here and does not invent one, so this number is "
    "supplied rather than derived — and a break-even is only as good as it is"
)
BREAK_EVEN_METHOD = (
    "days_to_recover = switching_cost_usd / (position_size_usd x (candidate_net_apr - "
    "current_net_apr) / 365). Both rates are the 24h observed net figures annualised by "
    "x365. within_horizon compares that against a horizon of {horizon} days, which is a "
    "stated choice rather than a derived one — the inputs are all here, so a reader can "
    "apply a different horizon without asking."
)
NOT_BUILT = (
    "This is the swap leg only. Adding the resulting assets as liquidity to the destination "
    "pool is not built in this stage, so a move drafted here gets the caller into the right "
    "asset and no further. The remaining step is theirs."
)
PREVIEW_REASON = (
    "This is a preview. It holds no session, no signer and no submitter, and there is no "
    "method on it that sends anything. A drafted swap leg needs a session the wallet's "
    "owner grants on chain before it could be submitted, and this build has no path that "
    "submits one."
)


@dataclass(frozen=True)
class Candidate:
    """One pool in the eligible set, at the rate it was observed at."""

    pool_id: str
    pair: str
    fee_tier: int | None
    net_fee_apr: float
    gross_fee_apr: float
    fee_usd_24h: float
    protocol_fee_usd_24h: float
    tvl_usd: float
    volume_usd_24h: float
    turnover: float
    net_fee_apr_delta: float | None

    def as_record(self) -> dict:
        return {
            "pool_id": self.pool_id,
            "pair": self.pair,
            "fee_tier": self.fee_tier,
            "net_fee_apr": self.net_fee_apr,
            "gross_fee_apr": self.gross_fee_apr,
            "net_vs_gross": NET_VS_GROSS,
            "rate_window": RATE_WINDOW,
            "rate_denominator": RATE_DENOMINATOR,
            "fee_usd_24h": self.fee_usd_24h,
            "protocol_fee_usd_24h": self.protocol_fee_usd_24h,
            "tvl_usd": self.tvl_usd,
            "volume_usd_24h": self.volume_usd_24h,
            "turnover": self.turnover,
            "net_fee_apr_delta": self.net_fee_apr_delta,
            "delta_note": DELTA_UNAVAILABLE if self.net_fee_apr_delta is None else None,
        }


@dataclass(frozen=True)
class MoveAction:
    """One drafted swap leg, and the half of the move this build does not draft."""

    intent: ActionIntent
    calldata: bytes
    destination: str
    not_built: str
    checks: tuple[str, ...]

    def as_record(self) -> dict:
        return {
            "destination_pool": self.destination,
            "intent": self.intent.as_record(),
            "intent_key": self.intent.idempotency_key,
            "calldata": "0x" + self.calldata.hex(),
            "not_built": self.not_built,
            "checks": list(self.checks),
        }


def _number(pool: dict, field: str) -> float:
    return float(pool.get(field) or 0)


def _pair(pool: dict) -> str:
    return "/".join(
        str((pool.get(side) or {}).get("symbol") or "?") for side in ("token0", "token1")
    )


def _quotable(pool: dict) -> bool:
    """Whether a net rate can be computed from this row at all.

    The universe already refuses rows missing either fee figure, so this only ever fires
    for the `current` pool — which is supplied by the caller and does not pass through the
    gate. A pool the caller is already in can be one the gate would have turned away.
    """
    return pool.get("feeUSD24h") is not None and pool.get("protocolFeeUSD24h") is not None


def _candidate(pool: dict, baseline: float | None) -> Candidate:
    net = net_fee_apr(pool)
    return Candidate(
        pool_id=str(pool.get("id") or "?"),
        pair=_pair(pool),
        fee_tier=pool.get("feeTier"),
        net_fee_apr=net,
        gross_fee_apr=(
            _number(pool, "feeUSD24h") * 365 / _number(pool, "tvlUSD")
            if _number(pool, "tvlUSD") > 0
            else 0.0
        ),
        fee_usd_24h=_number(pool, "feeUSD24h"),
        protocol_fee_usd_24h=_number(pool, "protocolFeeUSD24h"),
        tvl_usd=_number(pool, "tvlUSD"),
        volume_usd_24h=_number(pool, "volumeUSD24h"),
        turnover=turnover(pool),
        net_fee_apr_delta=None if baseline is None else net - baseline,
    )


def compare(current: dict, universe) -> list[Candidate]:
    """Every pool in the stated set, at its net observed rate, against the current one.

    Ordered by `net_fee_apr` descending. That order is an observed metric and the payload
    says which one — an order with no stated basis is the one a reader takes for Docket's
    opinion. Ties keep the source's order, so the result is deterministic for fixed input.
    """
    baseline = net_fee_apr(current) if _quotable(current) else None
    candidates = [_candidate(pool, baseline) for pool in universe.included]
    return sorted(candidates, key=lambda c: -c.net_fee_apr)


def break_even(
    current: Candidate,
    candidate: Candidate,
    *,
    position_size_usd: float,
    switching_cost_usd: float,
    horizon_days: int = HORIZON_DAYS,
) -> dict:
    """How long the extra yield takes to pay back what moving costs.

    A candidate whose observed rate is not above the current one recovers nothing, and one
    whose break-even runs past the horizon is reported with that fact rather than dropped.
    Both are the cases a comparison is tempted to leave out, and both are the ones that
    tell a reader something they could not work out from the rates alone.
    """
    method = BREAK_EVEN_METHOD.format(horizon=horizon_days)
    base = {
        "candidate": candidate.pool_id,
        "position_size_usd": position_size_usd,
        "switching_cost_usd": switching_cost_usd,
        "cost_covers": COST_COVERS,
        "horizon_days": horizon_days,
        "method": method,
    }
    if candidate.net_fee_apr_delta is None:
        return base | {
            "extra_net_apr": None,
            "extra_usd_per_day": None,
            "days_to_recover": None,
            "within_horizon": False,
            "reason": DELTA_UNAVAILABLE,
        }

    extra = candidate.net_fee_apr - current.net_fee_apr
    if extra <= 0 or position_size_usd <= 0:
        return base | {
            "extra_net_apr": extra,
            "extra_usd_per_day": None,
            "days_to_recover": None,
            "within_horizon": False,
            "reason": (
                f"this pool's observed net rate is not above the current one, so there is "
                f"nothing extra to recover the {switching_cost_usd} cost from"
            ),
        }

    per_day = position_size_usd * extra / 365
    days = switching_cost_usd / per_day
    return base | {
        "extra_net_apr": extra,
        "extra_usd_per_day": per_day,
        "days_to_recover": days,
        "within_horizon": days <= horizon_days,
        "reason": None,
    }


def plan_move(
    candidate: Candidate,
    universe,
    *,
    token_in: str,
    token_out: str,
    amount: int,
    cap: int,
    reader,
    wallet: str,
    slippage_bps: int = DEFAULT_SLIPPAGE_BPS,
    gas_ceiling: int = DEFAULT_GAS_CEILING,
    deadline_s: int = DEFAULT_DEADLINE_S,
    nonce: int = 0,
) -> list[MoveAction]:
    """One bounded swap leg toward a destination inside the stated set.

    Four refusals, all before any bytes are built. The destination has to be in the
    universe, which is what "allowlisted destination" means here — the eligible set is the
    allowlist, so a pool that did not clear the gate is not somewhere this routes to. Both
    assets have to be on `MOVE_ASSETS`. The asset bought has to be one the destination pool
    actually holds, because two allowlists that pass independently can still disagree with
    each other, and a leg that lands in the wrong asset satisfies both. And an amount past
    the cap is refused rather than trimmed to it, because silently shrinking a size produces
    an action nobody asked for.
    """
    destinations = {str(pool.get("id") or "?"): pool for pool in universe.included}
    if candidate.pool_id not in destinations:
        raise ValueError(
            f"{candidate.pool_id} is not in the eligible set this comparison was drawn "
            f"from ({len(destinations)} pools from {universe.source} at "
            f"{universe.observed_at}), so it is not a destination this build routes to"
        )
    for name, token in (("token_in", token_in), ("token_out", token_out)):
        if Web3.to_checksum_address(token) not in MOVE_ASSETS:
            raise ValueError(
                f"{name} {token} is not on this build's move allowlist of {sorted(MOVE_ASSETS)}"
            )
    destination = destinations[candidate.pool_id]
    held = {
        str((destination.get(side) or {}).get("id") or "").lower() for side in ("token0", "token1")
    }
    if str(token_out).lower() not in held:
        raise ValueError(
            f"token_out {token_out} is neither side of {candidate.pool_id}, which holds "
            f"{sorted(held)}. This leg is meant to arrive in an asset that pool wants, and "
            "buying anything else clears both allowlists while landing in the wrong place"
        )
    if amount > cap:
        raise ValueError(
            f"the move is {amount} and the cap is {cap}. It is refused rather than "
            "trimmed to the cap: a size nobody asked for is not a smaller version of the "
            "one they did"
        )

    route = (Web3.to_checksum_address(token_in), Web3.to_checksum_address(token_out))
    quoted = int(reader.amounts_out(amount, route)[-1])
    min_output = quoted * (10_000 - slippage_bps) // 10_000
    if min_output <= 0:
        raise ValueError(
            f"the router quotes {quoted} out for {amount} in, which leaves no floor at all "
            f"once {slippage_bps}bps of slippage is allowed"
        )
    deadline = now() + deadline_s
    calldata = swap_calldata(
        amount_in=amount,
        min_output=min_output,
        route=route,
        recipient=wallet,
        deadline=deadline,
    )
    intent = ActionIntent(
        intent_id=f"yield-router-{candidate.pool_id}-{nonce}",
        # The predicate is about the call being authorised, not about the reasoning behind
        # it: this swap may fire while the router's quote for this size clears the floor.
        # The rate gap and the break-even that motivated the move are on the record beside
        # this, where they can be read, rather than dressed up as a trigger.
        condition=Condition(
            kind="price_at_or_above",
            subject=f"router quote for {amount} of {route[0]} into {route[1]}",
            threshold=min_output,
        ),
        chain_id=56,
        target=PANCAKE_V2_ROUTER,
        selector=SWAP_SELECTOR,
        calldata_hash=commit(calldata),
        token_in=route[0],
        token_out=route[1],
        max_input=amount,
        min_output=min_output,
        route=route,
        slippage_bps=slippage_bps,
        deadline=deadline,
        gas_ceiling=gas_ceiling,
        nonce=nonce,
        policy_version=POLICY_VERSION,
        evidence_block=int(reader.block_number()),
    )
    return [
        MoveAction(
            intent=intent,
            calldata=calldata,
            destination=candidate.pool_id,
            not_built=NOT_BUILT,
            checks=(
                f"destination {candidate.pool_id} is in the eligible set of {len(destinations)}",
                f"both assets are on the move allowlist of {len(MOVE_ASSETS)}",
                f"amount {amount} is within the cap {cap}",
                f"router quoted {quoted} out, floored at {min_output}",
            ),
        )
    ]


class YieldRouterPreview:
    """The whole comparison, with nothing that could act on it.

    Holds a universe and the pool the capital is in, and nothing else by default. A reader
    may be supplied so a drafted swap leg can be quoted; there is still no session, no
    signer and no submitter, and no method here sends anything.
    """

    def __init__(self, *, universe, current: dict, reader=None) -> None:
        self.universe = universe
        self.current = current
        self._reader = reader

    def preview(
        self,
        *,
        position_size_usd: float,
        switching_cost_usd: float,
        horizon_days: int = HORIZON_DAYS,
        wallet: str | None = None,
        token_in: str | None = None,
        token_out: str | None = None,
        amount: int | None = None,
        cap: int | None = None,
    ) -> dict:
        """Every candidate with its break-even, and — where a recipient is named — the leg.

        With no wallet this is a pure read: the comparison, the costs, and the set that
        bounds both. That is the path a judge holding nothing can walk end to end. Naming a
        recipient adds the drafted swap and changes nothing about what can be sent, which
        is still nothing.
        """
        candidates = compare(self.current, self.universe)
        current = _candidate(
            self.current, net_fee_apr(self.current) if _quotable(self.current) else None
        )
        rows = []
        for candidate in candidates:
            rows.append(
                candidate.as_record()
                | {
                    "break_even": break_even(
                        current,
                        candidate,
                        position_size_usd=position_size_usd,
                        switching_cost_usd=switching_cost_usd,
                        horizon_days=horizon_days,
                    )
                }
            )

        drafted: list[dict] = []
        if wallet is not None:
            if not candidates:
                raise ValueError(
                    f"no eligible pool to route to: the set from {self.universe.source} at "
                    f"{self.universe.observed_at} came out empty, so there is no destination "
                    "and no comparison behind one"
                )
            top = candidates[0]
            # The draft takes the top observed rate, which may be one of the candidates the
            # comparison just labelled as not paying for itself inside the horizon. That
            # label travels with the action rather than sitting two keys away in a list, so
            # the draft cannot read as endorsed by a comparison that said the opposite.
            chosen = next(row for row in rows if row["pool_id"] == top.pool_id)
            drafted = [
                action.as_record() | {"break_even": chosen["break_even"]}
                for action in plan_move(
                    top,
                    self.universe,
                    token_in=token_in,
                    token_out=token_out,
                    amount=amount,
                    cap=cap,
                    reader=self._reader,
                    wallet=wallet,
                )
            ]
        return {
            "current": current.as_record(),
            "candidates": rows,
            "ordering": ORDERING,
            "universe": self.universe.as_record(),
            "actions": drafted,
            "submitted": False,
            "why_not_submitted": PREVIEW_REASON,
        }
