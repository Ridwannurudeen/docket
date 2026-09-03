"""The yield optimisation executor: compare, decide, and build the whole move.

The official category verb is "routes liquidity to the highest available APR", and both
halves of that sentence carry weight here. "Highest" is a superlative over a population,
so it is bounded by the eligible set `agents/yield_router/universe.py` builds and names —
the comparison says highest *within this set, at this source, at this moment*, and never
more. "Routes" is the half that used to be missing: `agents/yield_router/migration.py`
now builds every transaction of the move, so an activation in this category ends with a
position in the destination pool rather than with a swap leg and a note saying the rest
is the caller's.

Two refusals are worth stating because they are the ones a reader will look for. A move
whose break-even runs past the caller's horizon is a `noop` with the arithmetic attached,
not a route built anyway with a caveat. And a route whose simulated calls came back with
a disagreement is an `alert`, never an action.

The module-object imports below, and `from __future__ import annotations`, exist for the
same reason they do in the grid executor: `migration` imports `PreparedCall` from this
package, so nothing here may touch its attributes at import time.
"""

from __future__ import annotations

from ...agents.pancake.pools import net_fee_apr
from ...agents.yield_router import migration as yield_migration
from ...agents.yield_router import router as yield_router
from ...agents.yield_router.universe import eligible_pools
from ...execution import now as chain_now
from . import register
from .base import Decision

CATEGORY = "yield_optimisation"
CATEGORY_VERB = "Routes liquidity to the highest available APR"
DEFAULT_BAND_WIDTH_TICKS = 1_000
DEFAULT_SLIPPAGE_BPS = 50


def _universe_from(inputs: dict):
    """The eligible set this activation compares within, built from its own inputs.

    The pools and the token allowlist are supplied on the activation rather than fetched
    here, for the reason the v3 registrations give: a comparison whose population was
    fetched at decision time cannot be reproduced by a reader who was not there. A caller
    that hands over a snapshot gets an answer anybody can recompute.
    """
    pools = inputs.get("pools")
    allowlist = inputs.get("token_allowlist")
    if not isinstance(pools, list) or not pools:
        raise ValueError(
            "yield activation: `pools` must be the explorer's top-pool rows, so the set "
            "this comparison is bounded by is one a reader can reproduce"
        )
    if not allowlist:
        raise ValueError(
            "yield activation: `token_allowlist` must be the token list the pools were "
            "gated against; an absent allowlist rejects every pool and looks like a "
            "quiet market"
        )
    return eligible_pools(
        pools,
        {str(address).lower() for address in allowlist},
        source=str(inputs.get("source") or "caller-supplied snapshot"),
        observed_at=str(inputs.get("observed_at") or "unstated"),
    )


class YieldRouteExecutor:
    """Category `yield_optimisation`. Holds no key, sends nothing, and says which it is."""

    category = CATEGORY

    def __init__(self, reader=None, clock=None) -> None:
        self._reader = reader
        self._clock = clock if clock is not None else chain_now

    def _chain(self):
        if self._reader is None:
            self._reader = yield_migration.BscMigrationReader()
        return self._reader

    def evaluate(self, activation, *, reader=None) -> Decision:
        """Compare inside the stated set, then build the move if it pays for itself.

        The comparison runs first and its result is on the evidence whatever happens
        next, so a `noop` carries the same numbers a route would have — a reader can see
        the candidate that was not taken and the break-even that ruled it out.
        """
        chain = reader if reader is not None else self._chain()
        moment = int(self._clock())
        inputs = activation.inputs or {}
        try:
            universe = _universe_from(inputs)
            position = inputs["position"]
            position_size_usd = float(inputs["position_size_usd"])
            switching_cost_usd = float(inputs["switching_cost_usd"])
        except (KeyError, TypeError, ValueError) as exc:
            return Decision(
                kind="alert",
                summary=(
                    f"this activation's inputs do not describe a comparison: "
                    f"{type(exc).__name__}: {exc}. Nothing is compared and nothing built"
                ),
                evidence={"category_verb": CATEGORY_VERB},
            )

        horizon_days = int(inputs.get("horizon_days") or yield_router.HORIZON_DAYS)
        current_row = yield_migration.match_current_pool(position, universe)
        baseline = (
            net_fee_apr(current_row)
            if current_row is not None and yield_router._quotable(current_row)
            else None
        )
        candidates = yield_router.compare(current_row or {}, universe)
        if not candidates:
            return Decision(
                kind="noop",
                summary=(
                    f"no pool in the set from {universe.source} at {universe.observed_at} "
                    "cleared the gate, so there is no highest to route to and no "
                    "comparison behind one"
                ),
                evidence={
                    "category_verb": CATEGORY_VERB,
                    "universe": universe.as_record(),
                },
            )

        destination = candidates[0]
        current = (
            yield_router._candidate(current_row, baseline)
            if current_row is not None
            else yield_router._candidate({}, None)
        )
        payback = yield_router.break_even(
            current,
            destination,
            position_size_usd=position_size_usd,
            switching_cost_usd=switching_cost_usd,
            horizon_days=horizon_days,
        )
        comparison = {
            "category_verb": CATEGORY_VERB,
            "ordering": yield_router.ORDERING,
            "universe": universe.as_record(),
            "candidates": [candidate.as_record() for candidate in candidates],
            "current": current.as_record(),
            "break_even": payback,
        }
        if not payback["within_horizon"]:
            why = payback["reason"] or (
                f"{payback['days_to_recover']} days to recover the stated cost"
            )
            return Decision(
                kind="noop",
                summary=(
                    f"{destination.pool_id} is the highest observed net rate in this set, "
                    f"and moving there does not pay for itself inside {horizon_days} "
                    f"days: {why}. Staying is the decision, and the arithmetic that made "
                    "it is attached"
                ),
                evidence=comparison,
            )

        destination_row = next(
            row
            for row in universe.included
            if str(row.get("id")) == destination.pool_id
        )
        try:
            plan = yield_migration.plan_full_route(
                position,
                destination_row,
                universe=universe,
                reader=chain,
                owner=activation.owner,
                session=(activation.session or {})["address"],
                position_size_usd=position_size_usd,
                switching_cost_usd=switching_cost_usd,
                horizon_days=horizon_days,
                max_slippage_bps=int(
                    inputs.get("max_slippage_bps") or DEFAULT_SLIPPAGE_BPS
                ),
                band_width_ticks=int(
                    inputs.get("band_width_ticks") or DEFAULT_BAND_WIDTH_TICKS
                ),
                now=moment,
            )
        except (KeyError, TypeError, ValueError) as exc:
            return Decision(
                kind="alert",
                summary=(
                    f"the move to {destination.pool_id} pays for itself but cannot be "
                    f"built: {type(exc).__name__}: {exc}"
                ),
                evidence=comparison,
            )

        evidence = comparison | {
            "plan": plan.as_record(),
            "plan_hash": plan.plan_hash,
            "disclosure": plan.disclosure,
        }
        failed = [call.purpose for call in plan.calls if not call.simulation["ok"]]
        if failed:
            return Decision(
                kind="alert",
                summary=(
                    f"the route into {destination.pool_id} was built and the chain "
                    f"disagreed with {len(failed)} of its {len(plan.calls)} calls at "
                    f"simulation, starting with: {failed[0]}. Nothing is sent"
                ),
                evidence=evidence,
                observed_at=str(plan.evidence["observed_at"]),
                block=int(plan.evidence["block"]),
            )
        return Decision(
            kind="action",
            summary=(
                f"routing this position into {destination.pool_id} at a net observed rate "
                f"of {destination.net_fee_apr:.6f} against {current.net_fee_apr:.6f}, "
                f"recovering the stated switching cost in "
                f"{payback['days_to_recover']:.2f} days inside a {horizon_days}-day "
                f"horizon. {len(plan.calls)} calls, ticks "
                f"[{plan.tick_lower}, {plan.tick_upper}], the new position minted to the "
                "owner"
            ),
            prepared=plan.calls,
            evidence=evidence,
            observed_at=str(plan.evidence["observed_at"]),
            block=int(plan.evidence["block"]),
        )

    def within_policy(self, activation, decision: Decision) -> tuple[bool, str]:
        """Whether the session was granted everything this route needs.

        The first call in a migration is the owner's own ERC-721 approval and is not the
        session's to make; it is exempted by name rather than by position, so a route
        whose order changed cannot smuggle a session call past this gate.
        """
        if decision.kind != "action":
            return True, f"a {decision.kind} decision sends nothing"
        policy = activation.policy or {}
        if policy.get("emergency_pause"):
            return False, "the session policy is under an emergency pause"
        contracts = {
            str(address).lower() for address in policy.get("contract_allowlist") or ()
        }
        functions = {
            str(selector).lower() for selector in policy.get("function_allowlist") or ()
        }
        tokens = {str(token).lower() for token in policy.get("token_allowlist") or ()}
        gas_ceiling = policy.get("max_gas_price_wei")
        for call in decision.prepared:
            if not call.simulation["ok"]:
                return False, (
                    "the chain disagreed with this call at simulation: "
                    f"{call.simulation['revert_reason']}"
                )
            if call.purpose.startswith("OWNER SIGNS:"):
                continue
            if contracts and call.to.lower() not in contracts:
                return False, (
                    f"{call.to} is not on the session's contract allowlist of "
                    f"{sorted(contracts)}"
                )
            selector = call.data[:10].lower()
            if functions and selector not in functions:
                return False, (
                    f"selector {selector} is not on the session's function allowlist of "
                    f"{sorted(functions)}"
                )
            if gas_ceiling is not None and call.gas_ceiling > int(gas_ceiling):
                return False, (
                    f"the call's gas ceiling {call.gas_ceiling} exceeds the policy's "
                    f"{gas_ceiling}"
                )
        if tokens:
            disclosure = decision.evidence.get("disclosure") or {}
            sequence = disclosure.get("transaction_sequence") or ()
            for step in sequence:
                target = str(step.get("to") or "").lower()
                if (
                    target != yield_migration.NPM.lower()
                    and target != yield_router.PANCAKE_V2_ROUTER.lower()
                    and target not in tokens
                ):
                    return False, (
                        f"{step.get('to')} is neither the position manager nor the "
                        "router, and is not on the session's token allowlist"
                    )
        return True, (
            "every session-signed call is to an allowlisted contract and cleared the "
            "checks that could run at this block; the owner's own NFT approval is "
            "outside the session's authority by design"
        )


register(YieldRouteExecutor())
