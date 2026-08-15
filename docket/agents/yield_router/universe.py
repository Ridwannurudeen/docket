"""The eligible set, and the reason beside every pool that is not in it.

"Routes to the highest available APR" is two claims, and only one of them is arithmetic.
The other is the population: highest *of what*. An unstated universe makes the superlative
unfalsifiable, and an unfalsifiable claim is worth nothing to a reader trying to check it.
So this module produces a set that names its own source, the moment it was observed, the
thresholds it was gated on and its size — and every row it turned away, with why.

The gate is `pancake.pools.is_plausible`, which already exists and is already tested.
Reusing it rather than restating it means this module cannot develop a second opinion
about the same row; its reasons are carried through verbatim. One check is added on top,
because it is the one a comparison needs and a plausibility gate does not:

**Missing fee data is an exclusion, not a zero.** `net_fee_apr` reads an absent
`feeUSD24h` as zero, which would publish an unquotable pool as a 0% one — a figure that
looks measured and is not. And an absent `protocolFeeUSD24h` is worse than useless: the
protocol keeps roughly a third of the fee, so subtracting nothing overstates what the
liquidity provider keeps by about that much. Both are refused with the reason said out
loud, which is the same discipline Stage 1e landed for the gross-versus-net figure.

Order is the source's own. Sorting here would be Docket publishing a ranking, and the
router that consumes this set orders by an explicitly named observed metric instead.
"""

from dataclasses import dataclass

from ..pancake.pools import is_plausible

# The plausibility gate's own defaults, restated here so the universe descriptor can carry
# the thresholds it was actually gated on rather than leaving a reader to guess them.
MIN_TVL = 10_000.0
MAX_TURNOVER = 50.0

UNIVERSE_BOUND = (
    "Every comparison drawn from this set means highest within this set, at this source "
    "and this moment, and nothing beyond it. It is not a claim about every pool on "
    "PancakeSwap, about other venues, or about what any of these pools does next."
)
EMPTY_UNIVERSE = (
    "No pool in this snapshot cleared the gate, so there is nothing to compare and no "
    "highest to name. The excluded rows and their reasons are below."
)


@dataclass(frozen=True)
class Exclusion:
    """One pool that is not in the set, and the gate and reason that kept it out."""

    pool_id: str
    pair: str
    gate: str
    first_failed_gate: str
    reason: str

    def as_record(self) -> dict:
        return {
            "pool_id": self.pool_id,
            "pair": self.pair,
            "gate": self.gate,
            "first_failed_gate": self.first_failed_gate,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class Universe:
    """The eligible set, everything left out of it, and what the set is a set of."""

    included: tuple[dict, ...]
    excluded: tuple[Exclusion, ...]
    source: str
    observed_at: str
    allowlist_size: int
    min_tvl: float
    max_turnover: float

    def as_record(self) -> dict:
        return {
            "size": len(self.included),
            "considered": len(self.included) + len(self.excluded),
            "excluded_count": len(self.excluded),
            "source": self.source,
            "observed_at": self.observed_at,
            "allowlist_size": self.allowlist_size,
            "min_tvl_usd": self.min_tvl,
            "max_turnover": self.max_turnover,
            "ordering": "the source's own order, unchanged — nothing here re-orders a set",
            "bound": UNIVERSE_BOUND,
            "bound_note": EMPTY_UNIVERSE if not self.included else UNIVERSE_BOUND,
            "included": [
                {"pool_id": row.get("id"), "pair": _pair(row)} for row in self.included
            ],
            "excluded": [row.as_record() for row in self.excluded],
        }


def _pair(pool: dict) -> str:
    return "/".join(
        str((pool.get(side) or {}).get("symbol") or "?")
        for side in ("token0", "token1")
    )


def _fee_data(pool: dict) -> tuple[bool, str]:
    """Whether this row carries both halves of the figure a net rate needs.

    Absent and zero are different claims and are treated differently: a pool reporting a
    fee of zero really did earn nothing over the window, and excluding it would quietly
    remove the bottom of the set a comparison is supposed to be bounded by.
    """
    if pool.get("feeUSD24h") is None:
        return False, (
            "no feeUSD24h in this row, so a fee rate cannot be computed from it — and "
            "reading an absent fee as zero would publish a rate that looks measured"
        )
    if pool.get("protocolFeeUSD24h") is None:
        return False, (
            "no protocolFeeUSD24h in this row, so the protocol's cut cannot be subtracted "
            "and a net rate cannot be computed. Treating it as zero would overstate what "
            "the liquidity provider keeps by roughly the third the protocol takes"
        )
    return True, "ok"


def _first_failed_gate(
    pool: dict, allowlist: set[str], min_tvl: float, max_turnover: float
) -> str | None:
    for side in ("token0", "token1"):
        address = str(((pool.get(side) or {}).get("id")) or "").lower()
        if address not in allowlist:
            return f"{side}_allowlist"
    tvl = float(pool.get("tvlUSD") or 0)
    if tvl < min_tvl:
        return "tvl_floor"
    if float(pool.get("volumeUSD24h") or 0) / tvl > max_turnover:
        return "turnover_ceiling"
    if pool.get("feeUSD24h") is None:
        return "feeUSD24h_non_null"
    if pool.get("protocolFeeUSD24h") is None:
        return "protocolFeeUSD24h_non_null"
    return None


def eligible_pools(
    pools,
    allowlist: set[str],
    *,
    source: str,
    observed_at: str,
    min_tvl: float = MIN_TVL,
    max_turnover: float = MAX_TURNOVER,
) -> Universe:
    """Split a snapshot into the set a claim may be made about, and everything else.

    Returns one object rather than a bare `(included, excluded)` pair, because the pair on
    its own is a set with no source, no moment and no thresholds — and a set a reader
    cannot reproduce is one they cannot check a superlative against. Both halves are on it
    as `.included` and `.excluded`.
    """
    included: list[dict] = []
    excluded: list[Exclusion] = []
    for pool in pools:
        first_failed_gate = _first_failed_gate(pool, allowlist, min_tvl, max_turnover)
        plausible, reason = is_plausible(
            pool, allowlist, min_tvl=min_tvl, max_turnover=max_turnover
        )
        if not plausible:
            excluded.append(
                Exclusion(
                    pool_id=str(pool.get("id") or "?"),
                    pair=_pair(pool),
                    gate="is_plausible",
                    first_failed_gate=first_failed_gate,
                    reason=reason,
                )
            )
            continue
        has_fees, fee_reason = _fee_data(pool)
        if not has_fees:
            excluded.append(
                Exclusion(
                    pool_id=str(pool.get("id") or "?"),
                    pair=_pair(pool),
                    gate="fee_data",
                    first_failed_gate=first_failed_gate,
                    reason=fee_reason,
                )
            )
            continue
        included.append(pool)

    return Universe(
        included=tuple(included),
        excluded=tuple(excluded),
        source=source,
        observed_at=observed_at,
        allowlist_size=len(allowlist),
        min_tvl=min_tvl,
        max_turnover=max_turnover,
    )
