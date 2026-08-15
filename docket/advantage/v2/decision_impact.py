"""Whether the arithmetic error changes a decision, or only a number.

The liquidity experiment established something real: across 22 eligible PancakeSwap v3 pools,
quoting the gross fee rate overstates the rate a liquidity provider keeps by a median 49.3%,
and the gross error is larger than the display-rounding error on all 22. That is a measured
finding and it is correct.

It is also, on its own, a claim about a percentage. A liquidity provider does not act on a
percentage — they act on *which pool to be in* and *whether moving is worth it*. So the honest
question, and the one this module answers, is narrower and harder: **does reading gross rather
than net change what someone would do?**

Three ways it can, each measured separately because they fail differently:

**Ranking reversals.** If gross and net rank the eligible pools in the same order, a provider
choosing "the best pool" lands in the same place either way and the error costs them nothing
in that decision. Every pair whose order flips is a case where it does. This is the strongest
of the three, because it needs no assumption about position size at all.

**Dollars at a fixed notional.** A percentage-point gap means nothing without a position to
apply it to, so the overstatement is restated as money at declared notionals. The notionals
are inputs, stated on the output, and never inferred from anything.

**Break-even movement.** A provider deciding whether to move capital compares the gain against
a switching cost. Computed from gross, the break-even arrives sooner than it really does — so
the error does not merely inflate the reward, it makes a move look like it pays back faster
than it will.

What this module does not do: it does not claim any provider made any of these decisions, or
that anyone lost money. It measures what the published numbers would support, over a frozen
snapshot, and says so. Nobody's realised outcome is observed here.
"""

from itertools import combinations


def ranking_reversals(pools: list[dict]) -> dict:
    """Pairs whose order flips between the gross ranking and the net one.

    A reversal is the cleanest form of decision impact available here: it needs no notional,
    no horizon and no assumption about the provider. Either the two orderings disagree about
    which of two pools is better, or they do not.
    """
    ranked = [
        pool
        for pool in pools
        if pool.get("gross_fee_apr") is not None and pool.get("net_fee_apr") is not None
    ]
    reversed_pairs = []
    for left, right in combinations(ranked, 2):
        gross_order = left["gross_fee_apr"] - right["gross_fee_apr"]
        net_order = left["net_fee_apr"] - right["net_fee_apr"]
        # Only a strict disagreement counts. A tie in either ranking is not a reversal:
        # nothing was reordered, and counting it would inflate the finding.
        if gross_order * net_order < 0:
            reversed_pairs.append(
                {
                    "pool_a": left["pool"],
                    "pair_a": left.get("pair"),
                    "pool_b": right["pool"],
                    "pair_b": right.get("pair"),
                    "gross_prefers": (
                        left["pool"] if gross_order > 0 else right["pool"]
                    ),
                    "net_prefers": left["pool"] if net_order > 0 else right["pool"],
                }
            )
    comparable = len(ranked) * (len(ranked) - 1) // 2
    return {
        "numerator": len(reversed_pairs),
        "denominator": comparable,
        "value": None if comparable == 0 else len(reversed_pairs) / comparable,
        "reversed_pairs": reversed_pairs,
        "best_pool_changes": _best_changes(ranked),
        "what_this_measures": (
            "Ordered pairs of eligible pools whose relative order differs between the gross "
            "ranking and the net one. A provider choosing between two pools on the published "
            "figure would pick differently in exactly these cases, and identically in the "
            "rest — where the arithmetic error is real and costs that decision nothing."
        ),
    }


def _best_changes(ranked: list[dict]) -> dict:
    """Whether the single best pool differs between the two rankings.

    The reversal count can be non-zero while the top pool is the same in both, which is a much
    weaker finding than it sounds — most providers pick the top of a list, not a pair.
    """
    if not ranked:
        return {"changes": None, "gross_best": None, "net_best": None}
    gross_best = max(ranked, key=lambda p: p["gross_fee_apr"])
    net_best = max(ranked, key=lambda p: p["net_fee_apr"])
    return {
        "changes": gross_best["pool"] != net_best["pool"],
        "gross_best": gross_best["pool"],
        "gross_best_pair": gross_best.get("pair"),
        "net_best": net_best["pool"],
        "net_best_pair": net_best.get("pair"),
    }


def dollars_at_notionals(pools: list[dict], notionals_usd: list[float]) -> dict:
    """The overstatement restated as money, at notionals the caller declares.

    A percentage-point gap is not a quantity anyone can act on. The notionals are inputs and
    are echoed on the output for exactly that reason: this is arithmetic applied to a declared
    position size, not a claim about anyone's actual holdings.
    """
    rows = []
    for notional in notionals_usd:
        per_pool = []
        for pool in pools:
            gross = pool.get("gross_fee_apr")
            net = pool.get("net_fee_apr")
            if gross is None or net is None:
                continue
            per_pool.append(
                {
                    "pool": pool["pool"],
                    "pair": pool.get("pair"),
                    "annual_gross_usd": notional * gross,
                    "annual_net_usd": notional * net,
                    "annual_overstatement_usd": notional * (gross - net),
                }
            )
        overstatements = sorted(row["annual_overstatement_usd"] for row in per_pool)
        rows.append(
            {
                "notional_usd": notional,
                "n_pools": len(per_pool),
                "median_annual_overstatement_usd": _median(overstatements),
                "max_annual_overstatement_usd": (
                    overstatements[-1] if overstatements else None
                ),
                "pools": per_pool,
            }
        )
    return {
        "notionals": rows,
        "what_this_measures": (
            "The gross-versus-net gap applied to declared position sizes. The sizes are "
            "inputs echoed here, not observations: no wallet was read and nobody is claimed "
            "to hold any of these positions."
        ),
    }


def break_even_shift(
    pools: list[dict], *, notional_usd: float, switching_cost_usd: float
) -> dict:
    """How much sooner a MOVE appears to pay back when the gain is read gross.

    A move is a comparison between two pools, and its payback comes from the *difference*
    between them — not from the destination's whole return. An earlier version of this
    function divided the switching cost by the destination's entire yield, which answers
    "how long until this pool's fees cover the cost of getting here" and understated the real
    payback roughly sixfold on a representative pair. The published figure was wrong, and the
    docstring above it described the correct model while the code did something else.

    So the unit here is an ordered pair: stay in `current`, or pay the switching cost to reach
    `destination`. Only pairs where the destination actually beats the current pool are
    break-even candidates at all — moving to a worse pool never repays, and including those
    would mix "never" into a median of days.
    """
    ranked = [
        pool
        for pool in pools
        if pool.get("gross_fee_apr") is not None and pool.get("net_fee_apr") is not None
    ]
    rows = []
    for current in ranked:
        for destination in ranked:
            if current["pool"] == destination["pool"]:
                continue
            gross_gain = destination["gross_fee_apr"] - current["gross_fee_apr"]
            net_gain = destination["net_fee_apr"] - current["net_fee_apr"]
            # A pair only informs a move decision if BOTH readings call it an improvement.
            # Where they disagree the ranking itself reversed, which the reversal measure
            # already counts and which is a different finding from a mis-stated payback.
            if gross_gain <= 0 or net_gain <= 0:
                continue
            gross_days = switching_cost_usd / (notional_usd * gross_gain / 365)
            net_days = switching_cost_usd / (notional_usd * net_gain / 365)
            rows.append(
                {
                    "from_pool": current["pool"],
                    "from_pair": current.get("pair"),
                    "to_pool": destination["pool"],
                    "to_pair": destination.get("pair"),
                    "break_even_days_from_gross": gross_days,
                    "break_even_days_from_net": net_days,
                    # Positive means the real payback is later than the gross figure implies.
                    # That direction is the one that matters: an optimistic error is the one
                    # that talks somebody into acting.
                    "days_later_than_gross_implies": net_days - gross_days,
                }
            )
    shifts = sorted(row["days_later_than_gross_implies"] for row in rows)
    return {
        "notional_usd": notional_usd,
        "switching_cost_usd": switching_cost_usd,
        "n_moves": len(rows),
        "median_days_later_than_gross_implies": _median(shifts),
        "max_days_later_than_gross_implies": shifts[-1] if shifts else None,
        "moves": rows,
        "what_this_measures": (
            "For each ordered pair of pools where moving is an improvement under both "
            "readings, the difference between the payback period the gross rates imply and "
            "the one the net rates support. The notional and the switching cost are inputs. A "
            "positive figure means the real payback is later than the published numbers "
            "suggest."
        ),
        "what_it_does_not_measure": (
            "Impermanent loss, price movement, gas beyond the declared switching cost, or "
            "whether either rate persists. A break-even computed from one annualised day is a "
            "statement about today's figures, not a forecast. Pairs where the two readings "
            "disagree about whether moving helps at all are excluded here and counted as "
            "ranking reversals instead."
        ),
    }


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    middle = len(values) // 2
    if len(values) % 2:
        return values[middle]
    return (values[middle - 1] + values[middle]) / 2
