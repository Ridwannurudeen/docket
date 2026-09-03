"""The grid trading executor: one activation, one observation, one bounded decision.

The official category verb is "places and manages automated grid orders", and this is
what Docket can honestly put behind it on an automated market maker. There is no order
book on PancakeSwap V2, so nothing rests anywhere; a level is a price Docket watches and
the first observation that crosses it fires one bounded swap. `agents/grid/lifecycle.py`
holds that mechanism and says so in every summary it produces. This module is the seam
between it and the activation: it reads the spec out of `activation.inputs`, reads the
price off the chain, asks the lifecycle what to do, and checks the answer against the
activation's own policy before anything is handed on.

`within_policy` is a second gate in front of the on-chain one, never a replacement for
it. The session's allowlists and caps are enforced where they cannot be argued with; what
this adds is a refusal that happens before a transaction is paid for.

The module-object import of the lifecycle below is deliberate. `lifecycle` imports
`PreparedCall` from this package, so importing its names here at module scope would close
a cycle whenever an importer reached the lifecycle first. Binding the module and reading
attributes at call time leaves the order free either way — and `from __future__ import
annotations` is part of that, because an annotation naming a type on the half-built module
would otherwise be evaluated while it is still half-built.
"""

from __future__ import annotations

from ...agents.grid import lifecycle as grid_lifecycle
from ...agents.grid.operator import observe_price
from ...execution import now as chain_now
from ...execution.simulate import PANCAKE_V2_ROUTER, BscQuoteReader
from .base import Decision
from . import register

CATEGORY = "grid_trading"
CATEGORY_VERB = "Places and manages automated grid orders"
# The one contract this category ever calls, and the one function on it. Anything else
# in a decision is a bug in the lifecycle, not a policy question.
ALLOWED_TARGETS = frozenset({PANCAKE_V2_ROUTER})


def _int(inputs: dict, name: str, *, required: bool = True, default=None):
    if name not in inputs or inputs[name] is None:
        if required:
            raise ValueError(f"grid activation: {name} is required")
        return default
    value = inputs[name]
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise ValueError(f"grid activation: {name} must be an integer, got {value!r}")
    try:
        return int(value)
    except ValueError:
        raise ValueError(
            f"grid activation: {name} must be an integer of atomic units, got {value!r}"
        ) from None


def spec_from(inputs: dict) -> grid_lifecycle.GridSpec:
    """One request body turned into a validated spec, or a refusal naming the field.

    Integers arrive as strings as often as not — a wei figure exceeds what JSON's number
    type is defined to carry, so the browser sends decimal strings. Both are accepted and
    both become the same integer; a float is refused, because it is the one shape that
    rounds differently on another machine.
    """
    spec = grid_lifecycle.GridSpec(
        base=inputs["base"],
        quote=inputs["quote"],
        price_lower=_int(inputs, "price_lower"),
        price_upper=_int(inputs, "price_upper"),
        levels=_int(inputs, "levels"),
        amount_per_level_atomic=_int(inputs, "amount_per_level_atomic"),
        total_cap_atomic=_int(inputs, "total_cap_atomic"),
        expires_at=_int(inputs, "expires_at"),
        max_slippage_bps=_int(inputs, "max_slippage_bps", required=False, default=50),
        stop_price=_int(inputs, "stop_price", required=False),
        direction_rule=inputs.get("direction_rule", "buy_below_sell_above"),
        base_decimals=_int(inputs, "base_decimals", required=False, default=18),
    )
    return spec.validate()


def state_from(inputs: dict) -> grid_lifecycle.GridState:
    """The grid's own progress, as the activation carries it between ticks."""
    raw = inputs.get("grid_state") or {}
    fills = tuple(
        grid_lifecycle.Fill(
            level=fill.get("level"),
            side=fill["side"],
            amount_in=int(fill["amount_in"]),
            amount_out=int(fill["amount_out"]),
            tx_hash=fill["tx_hash"],
            block=int(fill["block"]),
        )
        for fill in raw.get("fills") or ()
    )
    reference = raw.get("reference_price")
    return grid_lifecycle.GridState(
        open_levels=tuple(int(index) for index in raw.get("open_levels") or ()),
        fills=fills,
        spent_atomic=int(raw.get("spent_atomic") or 0),
        paused=bool(raw.get("paused")),
        cancelled=bool(raw.get("cancelled")),
        revoked=bool(raw.get("revoked")),
        reference_price=None if reference is None else int(reference),
    )


class GridExecutor:
    """Category `grid_trading`. Holds no key, sends nothing, and says which it is."""

    category = CATEGORY

    def __init__(self, reader=None, clock=None) -> None:
        # Built lazily: an executor constructed at import time must not open a socket,
        # and the registry below is populated at import time.
        self._reader = reader
        self._clock = clock if clock is not None else chain_now

    def _quotes(self):
        if self._reader is None:
            self._reader = BscQuoteReader()
        return self._reader

    def evaluate(self, activation, *, reader=None) -> Decision:
        """Read the pair's live quote, and let the lifecycle decide what it means.

        A decision the chain disagreed with comes back as an `alert` rather than as an
        action, so the tick loop cannot mistake a refused draft for an approved one. A
        malformed spec is an `alert` too, and not an exception: an activation that has
        been running for a week should report that its request body no longer validates,
        not crash the loop that was going to tell somebody.
        """
        quotes = reader if reader is not None else self._quotes()
        moment = int(self._clock())
        try:
            spec = spec_from(activation.inputs)
        except (KeyError, ValueError, TypeError) as exc:
            return Decision(
                kind="alert",
                summary=(
                    f"this grid's inputs no longer describe a runnable spec: "
                    f"{type(exc).__name__}: {exc}. Nothing is drafted"
                ),
                evidence={"category_verb": CATEGORY_VERB},
                observed_at="",
                block=0,
            )

        state = state_from(activation.inputs)
        session = (activation.session or {}).get("address")
        if not session:
            return Decision(
                kind="alert",
                summary=(
                    "this grid has no session address, so there is no account to name as "
                    "the recipient of a swap and nothing can be drafted"
                ),
                evidence={"category_verb": CATEGORY_VERB},
                observed_at="",
                block=0,
            )

        observation = observe_price(
            quotes,
            base=spec.base,
            quote=spec.quote,
            base_decimals=spec.base_decimals,
        )
        decision = grid_lifecycle.evaluate(
            state,
            observation,
            spec,
            reader=quotes,
            session_address=session,
            now=moment,
        )
        evidence = {
            "category_verb": CATEGORY_VERB,
            "spec": spec.as_record(),
            "grid_state": None
            if decision.state is None
            else decision.state.as_record(),
            "grid_decision": decision.kind,
            "no_resting_orders": grid_lifecycle.NO_RESTING_ORDERS,
        } | decision.evidence
        kind = {
            "fire": "action",
            "alert": "alert",
            "noop": "noop",
            "cancel": "alert",
            "revoke": "alert",
        }[decision.kind]
        prepared = (
            (decision.prepared,) if kind == "action" and decision.prepared else ()
        )
        return Decision(
            kind=kind,
            summary=decision.reason,
            prepared=prepared,
            evidence=evidence,
            observed_at=decision.observation["source"],
            block=int(observation.block_number),
        )

    def within_policy(self, activation, decision: Decision) -> tuple[bool, str]:
        """Whether the activation's own policy permits every call in this decision.

        Read from `activation.policy` rather than from the spec, because the two are
        different promises: the spec is what the user asked for and the policy is what
        the session was granted. A decision that satisfies the first and not the second
        is exactly the one this gate exists to stop.
        """
        if decision.kind != "action":
            return True, f"a {decision.kind} decision sends nothing"
        policy = activation.policy or {}
        contracts = {
            str(address).lower() for address in policy.get("contract_allowlist") or ()
        }
        functions = {
            str(selector).lower() for selector in policy.get("function_allowlist") or ()
        }
        per_action = policy.get("per_action_limit_atomic") or {}
        gas_ceiling = policy.get("max_gas_price_wei")
        expires_at = policy.get("expires_at")
        if policy.get("emergency_pause"):
            return False, "the session policy is under an emergency pause"
        for call in decision.prepared:
            if call.to not in ALLOWED_TARGETS:
                return False, (
                    f"{call.to} is not the PancakeSwap V2 router this category calls; a "
                    "grid that reached another contract is a bug, not a policy question"
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
            if not call.simulation["ok"]:
                return False, (
                    "the chain disagreed with this call at simulation: "
                    f"{call.simulation['revert_reason']}"
                )
            if gas_ceiling is not None and call.gas_ceiling > int(gas_ceiling):
                return False, (
                    f"the call's gas ceiling {call.gas_ceiling} exceeds the policy's "
                    f"{gas_ceiling}"
                )
        spec_record = decision.evidence.get("spec") or {}
        token_allowlist = {
            str(token).lower() for token in policy.get("token_allowlist") or ()
        }
        if token_allowlist:
            for token in (spec_record.get("base"), spec_record.get("quote")):
                if token and str(token).lower() not in token_allowlist:
                    return False, (
                        f"{token} is not on the session's token allowlist of "
                        f"{sorted(token_allowlist)}"
                    )
        intent = decision.evidence.get("intent") or {}
        token_in = intent.get("token_in")
        committed = intent.get("max_input")
        if token_in and committed is not None:
            limit = per_action.get(token_in) or per_action.get(str(token_in).lower())
            if limit is not None and int(committed) > int(limit):
                return False, (
                    f"this level commits {committed} of {token_in}, above the session's "
                    f"per-action limit of {limit}"
                )
        if expires_at is not None and spec_record.get("expires_at") is not None:
            return True, (
                "every call is to the allowlisted router, cleared its simulation, and "
                f"sits inside the session's caps until {expires_at}"
            )
        return (
            True,
            "every call is to the allowlisted router and cleared its simulation",
        )


register(GridExecutor())
