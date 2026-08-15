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
    """How much sooner a move appears to pay back when the gain is read gross.

    A provider weighing a move compares the extra yield against what moving costs. Computed
    from gross, the payback arrives earlier than it will — so the error does not only inflate
    the reward, it makes the move look like it recovers its cost faster.
    """
    rows = []
    for pool in pools:
        gross = pool.get("gross_fee_apr")
        net = pool.get("net_fee_apr")
        if gross is None or net is None:
            continue
        gross_daily = notional_usd * gross / 365
        net_daily = notional_usd * net / 365
        gross_days = None if gross_daily <= 0 else switching_cost_usd / gross_daily
        net_days = None if net_daily <= 0 else switching_cost_usd / net_daily
        rows.append(
            {
                "pool": pool["pool"],
                "pair": pool.get("pair"),
                "break_even_days_from_gross": gross_days,
                "break_even_days_from_net": net_days,
                # Positive means the real payback is later than the gross figure implies,
                # which is the direction that matters: the optimistic error is the dangerous
                # one, because it is the one that talks somebody into acting.
                "days_later_than_gross_implies": (
                    None
                    if gross_days is None or net_days is None
                    else net_days - gross_days
                ),
            }
        )
    shifts = sorted(
        row["days_later_than_gross_implies"]
        for row in rows
        if row["days_later_than_gross_implies"] is not None
    )
    return {
        "notional_usd": notional_usd,
        "switching_cost_usd": switching_cost_usd,
        "n_pools": len(rows),
        "median_days_later_than_gross_implies": _median(shifts),
        "max_days_later_than_gross_implies": shifts[-1] if shifts else None,
        "pools": rows,
        "what_this_measures": (
            "The difference between the payback period a gross rate implies and the one the "
            "net rate supports, at a declared position size and switching cost. Both are "
            "inputs. A positive figure means the real payback is later than the published "
            "number suggests."
        ),
        "what_it_does_not_measure": (
            "Impermanent loss, price movement, gas, or whether either rate persists. A "
            "break-even computed from one annualised day is a statement about today's "
            "figures, not a forecast."
        ),
    }


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    middle = len(values) // 2
    if len(values) % 2:
        return values[middle]
    return (values[middle - 1] + values[middle]) / 2
