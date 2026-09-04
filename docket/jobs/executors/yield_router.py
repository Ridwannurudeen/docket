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

The session plane reads three keys off `Decision.evidence` and can see them no other
way: `received_tokens`, which a sweep looks for; `token_hints`, which carries what no
calldata does; and `slippage_bps`, which the policy bounds. All three ride on every
decision this module returns, and `received_tokens` never goes empty while the session
holds anything — the plane reads the *last* decision, so a `noop` that dropped it would
strand a half-finished move's tokens. `token_amounts` and `token_amounts_by_call` are
published beside them and are informational; the spend actually charged is derived from
the calldata by `docket.sessions.spend`, which is where it belongs.

The module-object imports below, and `from __future__ import annotations`, exist for the
same reason they do in the grid executor: `migration` imports `PreparedCall` from this
package, so nothing here may touch its attributes at import time.
"""

from __future__ import annotations

from datetime import UTC, datetime

from web3 import Web3

from ...agents.pancake.pools import net_fee_apr
from ...agents.yield_router import migration as yield_migration
from ...agents.yield_router import router as yield_router
from ...agents.yield_router.universe import eligible_pools
from ...execution import now as chain_now
from . import register
from .allowlists import (
    APPROVE,
    NPM,
    NPM_COLLECT,
    NPM_DECREASE_LIQUIDITY,
    NPM_MINT,
    PANCAKE_V2_ROUTER,
    SWAP_EXACT_TOKENS_FOR_TOKENS,
)
from .base import Decision

CATEGORY = "yield_optimisation"
CATEGORY_VERB = "Routes liquidity to the highest available APR"
DEFAULT_BAND_WIDTH_TICKS = 1_000
DEFAULT_SLIPPAGE_BPS = 50
# Taken from `allowlists.py` rather than retyped. One note for the integrator: that
# table's `yield_optimisation` defaults name only the router and the two tokens, so a
# session created from them unedited cannot make the four position-manager calls this
# route needs. The route is right and the defaults are short. `within_policy` reads the
# owner's actual grant rather than the defaults, so this bites only an activation created
# from the table without adding the position manager to it.
ALLOWED_SELECTORS = frozenset(
    {
        APPROVE,
        SWAP_EXACT_TOKENS_FOR_TOKENS,
        NPM_MINT,
        NPM_DECREASE_LIQUIDITY,
        NPM_COLLECT,
    }
)


def _utc_now() -> str:
    """The moment a decision was taken, as a UTC ISO timestamp."""
    return datetime.now(UTC).isoformat()


def _already_moved(activation, position, reader) -> bool:
    """Whether the move this activation was created for has already happened.

    Two facts have to agree, and neither alone is enough. A burned position could be one
    a route is halfway through, so on its own it means resume rather than stop; a mint
    receipt could belong to a route whose position was never burned. Together they are a
    finished move, and planning another one would send a route against a position that
    holds nothing.
    """
    minted = any(
        str((receipt.execution or {}).get("purpose", "")).startswith("mint into")
        and int((receipt.execution or {}).get("status", 0)) == 1
        for receipt in getattr(activation, "receipts", ()) or ()
    )
    if not minted:
        return False
    liquidity = yield_migration.position_liquidity(
        reader, int(position["token_id"]), owner=activation.owner
    )
    return liquidity == 0


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


def _held_tokens(activation, position=None) -> list[str]:
    """Every token this session could be holding, for a decision that builds nothing.

    **This may not come back empty while the session holds anything.** The session plane
    reads the *last* decision, so a route that alerted or stayed put would otherwise hand
    a sweep an empty list and leave whatever the session is carrying behind in an address
    nobody watches — a half-finished move's swap output, an un-minted balance.

    So it is the union of the position's own two tokens, which are what a move starts and
    ends in, and whatever the previous decision said it had received. Only an activation
    that has never decided anything and names no position reports nothing, and at that
    point the session is holding nothing either.
    """
    tokens = set()
    for key in ("token0", "token1"):
        value = (position or {}).get(key)
        if isinstance(value, str) and value:
            tokens.add(Web3.to_checksum_address(value))
    previous = ((activation.result or {}).get("last_decision") or {}).get("evidence") or {}
    for token in previous.get("received_tokens") or ():
        if isinstance(token, str) and token:
            tokens.add(token)
    return sorted(tokens)


def _no_spend(slippage_bps=None, *, tokens=()) -> dict:
    """The keys the session plane reads, for a decision that spends nothing.

    Written even here. An absent mapping and an empty one read alike to
    `SessionPolicy.allows` but not to a person: one says this decision spends nothing and
    the other says nobody wrote down what it spends.
    """
    return {
        "category_verb": CATEGORY_VERB,
        "token_amounts": {},
        "token_amounts_by_call": [],
        "token_hints": {"tokens": list(tokens)},
        "received_tokens": list(tokens),
        "slippage_bps": slippage_bps,
    }


class YieldRouteExecutor:
    """Category `yield_optimisation`. Holds no key, sends nothing, and says which it is."""

    category = CATEGORY

    def __init__(self, reader=None, clock=None) -> None:
        self._reader = reader
        self._clock = clock if clock is not None else chain_now

    def _chain(self, reader):
        """The chain reader this pass uses, from whatever the caller handed over.

        The tick loop passes the raw `Rpc` callable from `docket/escrow/chain.py`, which
        is a failover wrapper and not a reader, so it is wrapped into the one this route
        needs. A caller holding its own reader — a test, or anything with a node —
        passes that and it is used as given. The two are told apart by `pool_state`,
        which every reader this route accepts has and an `Rpc` does not.
        """
        if reader is not None:
            if hasattr(reader, "pool_state"):
                return reader
            return yield_migration.BscMigrationReader(rpc=reader)
        if self._reader is None:
            self._reader = yield_migration.BscMigrationReader()
        return self._reader

    def evaluate(self, activation, *, reader=None) -> Decision:
        """Compare inside the stated set, then build the move if it pays for itself.

        The comparison runs first and its result is on the evidence whatever happens
        next, so a `noop` carries the same numbers a route would have — a reader can see
        the candidate that was not taken and the break-even that ruled it out.
        """
        chain = self._chain(reader)
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
                prepared=(),
                evidence=_no_spend(tokens=_held_tokens(activation)),
                observed_at=_utc_now(),
                block=0,
            )

        horizon_days = int(inputs.get("horizon_days") or yield_router.HORIZON_DAYS)
        slippage_bps = int(inputs.get("max_slippage_bps") or DEFAULT_SLIPPAGE_BPS)
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
                prepared=(),
                evidence=_no_spend(
                    slippage_bps, tokens=_held_tokens(activation, position)
                )
                | {"universe": universe.as_record()},
                observed_at=_utc_now(),
                block=0,
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
        # Both policy keys ride on every decision, action or not: `SessionPolicy.allows`
        # reads spend and tolerance off the evidence and can see them no other way, so a
        # decision that spends nothing says so with an empty mapping rather than by
        # leaving the key out and reading as unrecorded.
        comparison = _no_spend(
            slippage_bps, tokens=_held_tokens(activation, position)
        ) | {
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
                prepared=(),
                evidence=comparison,
                observed_at=_utc_now(),
                block=0,
            )

        # A finished route leaves a burned position and a mint receipt. Read live rather
        # than remembered: the executor holds no state of its own between passes, and a
        # route that had already moved would otherwise be planned and sent all over again
        # on the next tick — from a position with nothing left in it.
        if _already_moved(activation, position, chain):
            return Decision(
                kind="noop",
                summary=(
                    f"position {position.get('token_id')} holds no liquidity and this "
                    "activation carries a mint receipt, so the move it was created for "
                    "has already happened. Nothing further is planned"
                ),
                prepared=(),
                evidence=comparison | {"already_moved": True},
                observed_at=_utc_now(),
                block=0,
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
                max_slippage_bps=slippage_bps,
                band_width_ticks=int(
                    inputs.get("band_width_ticks") or DEFAULT_BAND_WIDTH_TICKS
                ),
                now=moment,
            )
        except yield_migration.NftApprovalRequired as exc:
            # Caught ahead of the generic clause below, which is a ValueError and would
            # otherwise swallow this one — leaving the browser an alert that mentions an
            # approval and nothing machine-readable to ask the owner to sign.
            return Decision(
                kind="alert",
                summary=(
                    f"the move to {destination.pool_id} pays for itself and cannot start "
                    f"until the owner approves the session for the position NFT: {exc}"
                ),
                prepared=(),
                evidence=comparison | {"needs_nft_approval": dict(exc.detail)},
                observed_at=_utc_now(),
                block=0,
            )
        except (KeyError, TypeError, ValueError) as exc:
            return Decision(
                kind="alert",
                summary=(
                    f"the move to {destination.pool_id} pays for itself but cannot be "
                    f"built: {type(exc).__name__}: {exc}"
                ),
                prepared=(),
                evidence=comparison,
                observed_at=_utc_now(),
                block=0,
            )

        evidence = comparison | {
            "plan": plan.as_record(),
            "plan_hash": plan.plan_hash,
            "disclosure": plan.disclosure,
            "token_amounts": plan.session_spend,
            "token_amounts_by_call": [dict(e) for e in plan.session_spend_by_call],
            # Everything the session can be left holding: swap outputs, and whatever the
            # mint does not take of either destination token. A sweep that did not know
            # to look for them would leave them behind in an address nobody watches.
            "received_tokens": sorted(
                set(plan.session_spend) | set(_held_tokens(activation, position))
            ),
            "token_hints": {
                "tokens": sorted(
                    set(plan.session_spend) | set(_held_tokens(activation, position))
                )
            },
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
                prepared=(),
                evidence=evidence | {"token_amounts": {}},
                observed_at=_utc_now(),
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
            observed_at=_utc_now(),
            block=int(plan.evidence["block"]),
        )

    def within_policy(self, activation, decision: Decision) -> tuple[bool, str]:
        """Whether the session was granted everything this route needs.

        Every call in the batch is the session's to make. The owner's own ERC-721
        approval used to sit in the list and be exempted by name; it is a precondition
        now, read before the route is built and refused without, so there is nothing
        here to exempt and no name left to match against.
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
        for call in decision.prepared:
            # `False` is the chain refusing. `None` is a preflight that could not run
            # until an earlier call in this same batch lands. Only the first is a refusal.
            if call.simulation["ok"] is False:
                return False, (
                    "the chain disagreed with this call at simulation: "
                    f"{call.simulation['revert_reason']}"
                )
            if call.selector not in ALLOWED_SELECTORS:
                return False, (
                    f"selector {call.selector} is not one this category emits "
                    f"({sorted(ALLOWED_SELECTORS)})"
                )
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
        if tokens:
            disclosure = decision.evidence.get("disclosure") or {}
            sequence = disclosure.get("transaction_sequence") or ()
            for step in sequence:
                target = str(step.get("to") or "").lower()
                if (
                    target != NPM.lower()
                    and target != PANCAKE_V2_ROUTER.lower()
                    and target not in tokens
                ):
                    return False, (
                        f"{step.get('to')} is neither the position manager nor the "
                        "router, and is not on the session's token allowlist"
                    )
        return True, (
            "every call is to an allowlisted contract and cleared the checks that could "
            "run at this block. The owner's own NFT approval is not in this batch at "
            "all — it is a precondition the route reads before it builds. The gas price "
            "is not checked here: this gate sees gas units and the policy bounds a "
            "price, and `docket.sessions.executor` reads the price of the moment itself"
        )


register(CATEGORY, YieldRouteExecutor())
