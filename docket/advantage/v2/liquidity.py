"""Two ways a fee rate goes wrong, measured over a pool set instead of over one pair.

v1's task 01 published a seven-thousandths-of-a-point disagreement between its two arms and
explained it: PancakeSwap Info shows $2.06K where the explorer serves $2,058, so a reader
working from the screen computes 15.406% where a reader working from the route computes
15.399%. One pool, one day, one pair of numbers. Nothing in it says whether reading displayed
figures is a hazard worth a service or a rounding error in the ordinary sense of the phrase,
because a single difference has no size to compare against.

The same run recorded a second gap almost in passing, and it is an order of magnitude larger.
`feeUSD24h` is the whole fee the pool charged; a third of it goes to the protocol. A reader
who annualises the gross figure publishes 22.99% where the net rate is 15.41% — half again as
much yield as the position actually earns. v1 measured that on the same single pool.

So this module computes three rates per pool from one registered snapshot and reports the two
gaps between them as distributions. The arms are built to isolate one effect each. The
rounding arm runs the identical net formula on figures put through the display model, so the
only thing that differs between it and the raw arm is what the screen showed; it takes no view
on where a reader learned about the protocol cut, which is the other arm's whole subject. The
gross arm skips the subtraction on raw figures, so the only thing that differs between it and
the raw arm is the cut. Read together they answer which of the two a reader should actually
worry about, and the answer is not the one v1's narrative leads with.

The display model is the load-bearing assumption and it is an empirical one. PancakeSwap Info
scales a dollar figure to K, M or B and prints two decimals of the mantissa — not two
significant figures, and not three: v1's manual arm recorded $2.06K, $3.27M and $20.59M off
the same page, and only the mantissa rule produces all three. The evidence for it is those
strings and nothing else, which is why `ui_display` returns the string rather than the number:
it is a claim about output that can be checked against output. Where the model has to make a
choice v1's record cannot settle — a mantissa that rounds up to a thousand — the choice is
marked as the model's own and the run record states that no registered pool reaches it.

Every aggregate here carries the count it was computed over, and `rate` comes from `scoring`
rather than being written a second time, because a share of pools is a rate like any other.
"""

import statistics

from ...agents.pancake.pools import net_fee_apr
from .scoring import rate

# The scales PancakeSwap Info abbreviates to, ascending, and the two decimals it prints on
# whichever mantissa it lands on.
UI_SCALES = ((1.0, ""), (1_000.0, "K"), (1_000_000.0, "M"), (1_000_000_000.0, "B"))
UI_DECIMALS = 2
# The figures a reader takes off the pool page. `protocolFeeUSD24h` is not among them — the
# page does not show it at all, which is what the gross arm is about; it is put through the
# display model here so that the rounding arm differs from the raw arm in rounding alone and
# not in which of the three inputs it rounded.
UI_FIELDS = ("feeUSD24h", "protocolFeeUSD24h", "tvlUSD")
# The naive annualisation `net_fee_apr` already does, restated here because the gross arm has
# to do the same one to be a comparison rather than a second method.
DAYS = 365


def _scaled(value: float) -> tuple[str, float, str]:
    """The mantissa as it is printed, the factor it was divided by, and the suffix.

    A mantissa that rounds up to a thousand is promoted to the next scale rather than printed
    with four digits. Nothing in v1's record settles which of those PancakeSwap Info does —
    the case needs a figure within half a cent of a scale boundary — so this is the model's own
    choice, marked as one, and the run record states that no pool in the registered snapshot
    lands close enough for it to matter.
    """
    magnitude = abs(value)
    index = 0
    while index + 1 < len(UI_SCALES) and magnitude >= UI_SCALES[index + 1][0]:
        index += 1
    factor, suffix = UI_SCALES[index]
    mantissa = f"{value / factor:.{UI_DECIMALS}f}"
    if abs(float(mantissa)) >= 1000 and index + 1 < len(UI_SCALES):
        factor, suffix = UI_SCALES[index + 1]
        mantissa = f"{value / factor:.{UI_DECIMALS}f}"
    return mantissa, factor, suffix


def ui_display(value: float) -> str:
    """What PancakeSwap Info prints for a dollar figure.

    A string rather than a number on purpose: it is the half of the model there is evidence
    for, and the evidence is three figures a human read off the page during v1's manual arm.
    """
    mantissa, _factor, suffix = _scaled(value)
    return f"${mantissa}{suffix}"


def ui_rounded(value: float) -> float:
    """The number behind that string — what a reader keying the display into a calculator has.

    Derived from the same formatting `ui_display` uses rather than from a parallel rule, so
    the printed figure and the computed one cannot drift apart.
    """
    mantissa, factor, _suffix = _scaled(value)
    return float(mantissa) * factor


def rounded_pool(pool: dict) -> dict:
    """The three inputs at display precision, as floats, ready for the same net formula."""
    return {field: ui_rounded(float(pool.get(field) or 0)) for field in UI_FIELDS}


def ui_rounded_net_fee_apr(pool: dict) -> float:
    """The net rate a reader working from the screen computes.

    It calls `net_fee_apr` — the shipped one, the same function the raw arm and the Range
    Doctor call — on rounded inputs. Structural rather than stylistic: an arm with its own copy
    of the formula could differ from the raw arm in the formula while claiming to differ only
    in the rounding.
    """
    return net_fee_apr(rounded_pool(pool))


def gross_fee_apr(pool: dict) -> float:
    """The rate a reader publishes who never learns the protocol takes a cut.

    Not an error in the arithmetic — it is the fee the pool charged, annualised the same naive
    way. It is the wrong number for an LP because an LP does not receive it.
    """
    tvl = float(pool.get("tvlUSD") or 0)
    if tvl <= 0:
        return 0.0
    return float(pool.get("feeUSD24h") or 0) * DAYS / tvl


def _relative(gap: float, net: float):
    """The gap as a share of the rate it is a gap in, or null where there is no such rate.

    A pool that charged nothing has a net rate of zero, and both an infinity and a substituted
    zero would be figures nobody measured — the same reason a rate over zero observations
    reports null rather than dividing.
    """
    return None if net == 0 else gap / net


def pool_gaps(pool: dict) -> dict:
    """One pool's three rates and the two gaps between them, with the inputs they came from.

    Gaps are signed and in percentage points of annualised rate, which is the unit the rates
    are quoted in: a gross gap of 12 means a reader publishing gross quotes a rate twelve
    points above the one the position earns. The raw inputs travel in the row so the whole
    thing can be recomputed by hand from the record, and the displayed strings travel beside
    them so a reader can check the display model against the page.
    """
    raw = {field: float(pool.get(field) or 0) for field in UI_FIELDS}
    net = net_fee_apr(pool)
    rounded = ui_rounded_net_fee_apr(pool)
    gross = gross_fee_apr(pool)
    rounding_gap = (rounded - net) * 100
    gross_gap = (gross - net) * 100
    token0 = pool.get("token0") or {}
    token1 = pool.get("token1") or {}
    return {
        "pool": pool.get("id"),
        "pair": f"{token0.get('symbol')}/{token1.get('symbol')}",
        "fee_tier": pool.get("feeTier"),
        "raw": raw,
        "displayed": {field: ui_display(raw[field]) for field in UI_FIELDS},
        "net_fee_apr": net,
        "ui_rounded_net_fee_apr": rounded,
        "gross_fee_apr": gross,
        "rounding_gap_pp": rounding_gap,
        "gross_gap_pp": gross_gap,
        "rounding_gap_relative": _relative(rounding_gap / 100, net),
        "gross_gap_relative": _relative(gross_gap / 100, net),
    }


def distribution(values) -> dict:
    """The spread, and the count it was computed over, in the same return value.

    An aggregate whose n a reader has to go and find is an aggregate a reader will quote
    without it. Over nothing at all the three figures are null rather than zero.
    """
    values = list(values)
    return {
        "n": len(values),
        "min": min(values) if values else None,
        "median": statistics.median(values) if values else None,
        "max": max(values) if values else None,
    }


def measure(dataset: dict) -> dict:
    """Both gaps over every eligible pool in the registered snapshot.

    The eligible set is read from the dataset rather than recomputed here: it was fixed when
    the snapshot was registered, before any rate over it had been computed, so no pool can be
    admitted or dropped for the gap it turned out to show.

    The distributions are over absolute gaps, because the question is how far a published rate
    moves and a mean over signed gaps would let one pool's overstatement cancel another's
    understatement. Every signed gap survives in its own row.
    """
    rows = [pool_gaps(entry["pool"]) for entry in dataset["rows"] if entry["eligible"]]
    rounding = [abs(row["rounding_gap_pp"]) for row in rows]
    gross = [abs(row["gross_gap_pp"]) for row in rows]
    dominates = sum(1 for row in rows if abs(row["gross_gap_pp"]) > abs(row["rounding_gap_pp"]))
    return {
        "pools": rows,
        "rounding_gap_pp": distribution(rounding),
        "gross_gap_pp": distribution(gross),
        "rounding_gap_relative": distribution(
            [abs(row["rounding_gap_relative"]) for row in rows if row["rounding_gap_relative"]]
        ),
        "gross_gap_relative": distribution(
            [abs(row["gross_gap_relative"]) for row in rows if row["gross_gap_relative"]]
        ),
        "pools_where_gross_gap_exceeds_rounding_gap": rate(dominates, len(rows)),
        "method": (
            f"Three rates per pool over the {len(rows)} eligible pools of the "
            f"{len(dataset['rows'])} in the registered snapshot, all from the same stored "
            "response bodies and all annualised the same naive way — one 24h window times "
            "365, which is what every LP dashboard does and is a rate observed rather than a "
            "forecast. The raw arm is docket.agents.pancake.pools.net_fee_apr on the "
            "explorer's figures. The rounding arm is that same function on the same figures "
            "put through the display model, so it differs from the raw arm in the rounding "
            "and in nothing else; it says nothing about where a reader would have learned "
            "there is a protocol cut, which is the gross arm's subject. The gross arm "
            "annualises feeUSD24h without subtracting protocolFeeUSD24h. Gaps are signed and "
            "in percentage points of annualised rate; the distributions are over their "
            "absolute values, so one pool's overstatement cannot cancel another's, and every "
            "signed gap is kept in its own row. A relative gap against a pool that charged no "
            "fees is null rather than a division, and pools with no net rate are excluded from "
            "the relative distributions and counted by the n those distributions carry."
        ),
    }
