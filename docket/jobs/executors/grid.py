"""The grid trading executor: one activation, one observation, one bounded decision.

The official category verb is "places and manages automated grid orders", and this is
what Docket can honestly put behind it on an automated market maker. There is no order
book on PancakeSwap V2, so nothing rests anywhere; a level is a price Docket watches and
the first observation that crosses it fires one bounded swap. `agents/grid/lifecycle.py`
holds that mechanism and says so in every summary it produces. This module is the seam
between it and the activation: it reads the spec out of `activation.inputs`, reads the
price off the chain, asks the lifecycle what to do, and checks the answer against the
activation's own policy before anything is handed on.

`within_policy` is a second gate in front of `docket/sessions/policy.py`, never a
replacement for it. The session plane reads four keys off `Decision.evidence` and can see
them no other way, so all four are written on every decision this module returns,
including the ones that send nothing: `token_amounts` (the batch total),
`token_amounts_by_call` (the same split per call, because the policy charges per call),
`token_hints` (what no calldata carries) and `received_tokens` (what the session is left
holding, so a revoke sweeps it). A spend the policy cannot see is a spend it reads as zero.

The grid's own progress is carried the way the tick loop carries it. Each pass's evidence
is persisted at `activation.result["last_decision"]["evidence"]`, and that is where the
next pass reads its state from; `activation.inputs` is only ever right on the very first
pass, and preferring it would re-fire every filled level on every tick.

The module-object import of the lifecycle below is deliberate. `lifecycle` imports
`PreparedCall` from this package, so importing its names here at module scope would close
a cycle whenever an importer reached the lifecycle first. Binding the module and reading
attributes at call time leaves the order free either way — and `from __future__ import
annotations` is part of that, because an annotation naming a type on the half-built module
would otherwise be evaluated while it is still half-built.
"""

from __future__ import annotations

from datetime import datetime, timezone

from ...agents.grid import lifecycle as grid_lifecycle
from ...agents.grid.operator import observe_price
from ...execution import now as chain_now
from ...execution.simulate import BscQuoteReader
from . import register
from .allowlists import (
    APPROVE,
    SWAP_EXACT_TOKENS_FOR_TOKENS,
)
from .base import Decision

CATEGORY = "grid_trading"
CATEGORY_VERB = "Places and manages automated grid orders"
# Taken from `allowlists.py`, the single table the activation API serves as this
# category's policy defaults. Writing the same addresses and selectors down again here is
# how an executor's targets and its own category's allowlist drift apart with nothing
# saying so — and the drift stays invisible until a session refuses a call it was granted.
ALLOWED_SELECTORS = frozenset({APPROVE, SWAP_EXACT_TOKENS_FOR_TOKENS})


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


def _expiry(activation, inputs: dict) -> int:
    """When this grid stops, taken from the activation rather than from the body.

    `activation.expires_at` is the session's own expiry and is the one the owner set; a
    grid outliving the session that funds it is the failure the expiry exists to stop.
    The request body's `expires_at` stands in only when the activation carries none, so a
    spec cannot quietly outlive its session by naming a later date in its inputs.
    """
    stated = getattr(activation, "expires_at", None)
    if isinstance(stated, str) and stated.strip():
        moment = datetime.fromisoformat(stated.replace("Z", "+00:00"))
        if moment.tzinfo is not None:
            return int(moment.timestamp())
    return _int(inputs, "expires_at")


def spec_from(inputs: dict, activation=None) -> grid_lifecycle.GridSpec:
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
        expires_at=(
            _int(inputs, "expires_at")
            if activation is None
            else _expiry(activation, inputs)
        ),
        max_slippage_bps=_int(inputs, "max_slippage_bps", required=False, default=50),
        stop_price=_int(inputs, "stop_price", required=False),
        direction_rule=inputs.get("direction_rule", "buy_below_sell_above"),
        base_decimals=_int(inputs, "base_decimals", required=False, default=18),
    )
    return spec.validate()


def carried_state(activation) -> dict:
    """The evidence the previous pass left behind, wherever the loop wrote it.

    `activation.result["last_decision"]["evidence"]` is where the tick loop persists it.
    `result["grid_state"]` is the shape this executor wrote before that contract settled
    and is read for one release so a grid mid-flight when the release lands does not
    restart from its opening state. `inputs` is last and is only ever right on the first
    pass — preferring it would re-fire every filled level on every tick.
    """
    result = activation.result or {}
    last = (result.get("last_decision") or {}).get("evidence") or {}
    if last.get("grid_state"):
        return last["grid_state"]
    if result.get("grid_state"):
        return result["grid_state"]
    return (activation.inputs or {}).get("grid_state") or {}


def state_from(activation) -> grid_lifecycle.GridState:
    """The grid's own progress, as the activation carries it between ticks."""
    raw = carried_state(activation)
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
        fired=tuple(
            grid_lifecycle.Fired(
                level=int(entry["level"]),
                intent_key=entry.get("intent_key") or "",
                tx_hash=entry.get("tx_hash"),
            )
            for entry in raw.get("fired") or ()
        ),
        spent_atomic=int(raw.get("spent_atomic") or 0),
        paused=bool(raw.get("paused")),
        cancelled=bool(raw.get("cancelled")),
        revoked=bool(raw.get("revoked")),
        reference_price=None if reference is None else int(reference),
    )


def _utc_now() -> str:
    """The moment this decision was taken, as a UTC ISO timestamp.

    It used to carry the name of the read that produced the observation, which is a
    useful thing to publish and not a time. That name is on the evidence under `source`
    now, and this field is what it says it is."""
    return datetime.now(timezone.utc).isoformat()


def _by_call(prepared, level) -> list[dict]:
    """What each call in this batch spends, in the order they are broadcast.

    The approval spends nothing — it authorises, and charging it would bill the session
    twice for the same tokens, once for permitting the swap and once for the swap itself.
    Only the swap moves anything out.
    """
    return [
        {level.token_in: str(level.size)}
        if call.selector == SWAP_EXACT_TOKENS_FOR_TOKENS
        else {}
        for call in prepared
    ]


def _no_spend(spec=None) -> dict:
    """Evidence for a decision that proposes nothing, with the two policy keys still on it.

    An absent `token_amounts` and an empty one read alike to `SessionPolicy.allows`, but
    they do not read alike to a person: one says this decision spends nothing and the
    other says nobody wrote down what it spends. The first is what these are.
    """
    return {
        "category_verb": CATEGORY_VERB,
        "token_amounts": {},
        "token_amounts_by_call": [],
        "token_hints": {} if spec is None else {"tokens": [spec.base, spec.quote]},
        "received_tokens": [] if spec is None else [spec.base, spec.quote],
        "slippage_bps": None if spec is None else spec.max_slippage_bps,
    }


class GridExecutor:
    """Category `grid_trading`. Holds no key, sends nothing, and says which it is."""

    category = CATEGORY

    def __init__(self, reader=None, clock=None) -> None:
        # Built lazily: an executor constructed at import time must not open a socket,
        # and the registry below is populated at import time.
        self._reader = reader
        self._clock = clock if clock is not None else chain_now

    def _quotes(self, reader):
        """The router reader this pass uses, from whatever the caller handed over.

        The tick loop passes the raw `Rpc` callable from `docket/escrow/chain.py`, which
        is a failover wrapper and not a quote reader, so it is wrapped here. A caller that
        already has a reader — a test, or anything holding its own node — passes that
        instead and it is used as given. The two are told apart by whether the object can
        answer `amounts_out`, which is the only thing this executor asks a reader for.
        """
        if reader is not None:
            return (
                reader if hasattr(reader, "amounts_out") else BscQuoteReader(rpc=reader)
            )
        if self._reader is None:
            self._reader = BscQuoteReader()
        return self._reader

    def _reconcile(self, state, activation, spec, session, reader):
        """Close the loop on every level this grid has already sent.

        The fire branch marks a level fired the moment it drafts one, and only a receipt
        can take it off that list. So each pass reads the receipts the session executor
        recorded, pulls the ERC-20 Transfer logs out of the ones that succeeded, and hands
        `record_fills` both halves: what actually traded, and which levels reverted. A
        reverted swap traded nothing, so its level goes back to open and its notional
        comes back off the cap — a grid that kept charging reverted transactions against
        its cap would spend its whole allowance on transactions that never happened.

        A receipt the node has not caught up with yet leaves its level fired, which is
        the correct answer: sent, unconfirmed, and not to be drafted again.
        """
        if not state.fired or not hasattr(reader, "transaction_receipt"):
            return state
        pending = {entry.tx_hash: entry.level for entry in state.fired if entry.tx_hash}
        seen = {
            (receipt.execution or {}).get("tx_hash"): receipt.execution or {}
            for receipt in getattr(activation, "receipts", ()) or ()
            if (receipt.execution or {}).get("tx_hash")
        }
        landed, reverted = [], []
        for tx_hash, level in pending.items():
            execution = seen.get(tx_hash)
            if execution is None:
                continue
            if int(execution.get("status", 1)) != 1:
                reverted.append(level)
                continue
            receipt = reader.transaction_receipt(tx_hash)
            if receipt is None:
                continue
            landed.extend(
                grid_lifecycle.detect_fills(
                    [{**dict(receipt), "level": level}], spec, recipient=session
                )
            )
        if not landed and not reverted:
            return state
        return grid_lifecycle.record_fills(
            state,
            landed,
            reverted=reverted,
            notional_atomic=spec.amount_per_level_atomic,
        )

    def evaluate(self, activation, *, reader=None) -> Decision:
        """Read the pair's live quote, and let the lifecycle decide what it means.

        A decision the chain disagreed with comes back as an `alert` rather than as an
        action, so the tick loop cannot mistake a refused draft for an approved one. A
        malformed spec is an `alert` too, and not an exception: an activation that has
        been running for a week should report that its request body no longer validates,
        not crash the loop that was going to tell somebody.
        """
        quotes = self._quotes(reader)
        moment = int(self._clock())
        try:
            spec = spec_from(activation.inputs, activation)
        except (KeyError, ValueError, TypeError) as exc:
            return Decision(
                kind="alert",
                summary=(
                    f"this grid's inputs no longer describe a runnable spec: "
                    f"{type(exc).__name__}: {exc}. Nothing is drafted"
                ),
                prepared=(),
                evidence=_no_spend(),
                observed_at="",
                block=0,
            )

        state = state_from(activation)
        session = (activation.session or {}).get("address")
        if session:
            state = self._reconcile(state, activation, spec, session, quotes)
        if not session:
            return Decision(
                kind="alert",
                summary=(
                    "this grid has no session address, so there is no account to name as "
                    "the recipient of a swap and nothing can be drafted"
                ),
                prepared=(),
                evidence=_no_spend(spec),
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
        # `token_amounts` is what this decision spends out of the session, keyed by token
        # address, and `slippage_bps` is the tolerance it was drafted against. The policy
        # engine reads both off the evidence and can see neither any other way, so they
        # are written whatever the decision turned out to be — a decision that spends
        # nothing says so with an empty mapping rather than by leaving the key out.
        kind = {
            "fire": "action",
            "alert": "alert",
            "noop": "noop",
            "cancel": "alert",
            "revoke": "alert",
        }[decision.kind]
        prepared = decision.prepared if kind == "action" else ()
        level = decision.level
        fires = kind == "action" and level is not None
        evidence = {
            "category_verb": CATEGORY_VERB,
            # Without the ladder: it is derived from four fields already in this record,
            # and repeating up to MAX_LEVELS of it every five minutes for the life of the
            # grid writes the same derivation into the activation row over and over.
            "spec": spec.as_record(with_levels=False),
            "grid_state": None
            if decision.state is None
            else decision.state.as_record(),
            "grid_decision": decision.kind,
            "no_resting_orders": grid_lifecycle.NO_RESTING_ORDERS,
            "source": decision.observation["source"],
            # The four keys the session plane reads and can see no other way.
            # `token_amounts` is the batch total; `token_amounts_by_call` is the same
            # split per call, because the policy charges per call and a batch total
            # applied to each one charges a two-call fire twice; `token_hints` carries
            # what no calldata does; `received_tokens` is what the session ends up
            # holding, so a revoke sweeps it rather than leaving it behind.
            "token_amounts": {level.token_in: str(level.size)} if fires else {},
            "token_amounts_by_call": _by_call(prepared, level) if fires else [],
            "token_hints": {"tokens": [spec.base, spec.quote]},
            "received_tokens": [spec.base, spec.quote],
            "slippage_bps": spec.max_slippage_bps,
        } | decision.evidence
        return Decision(
            kind=kind,
            summary=decision.reason,
            prepared=prepared,
            evidence=evidence,
            observed_at=_utc_now(),
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
        expires_at = policy.get("expires_at")
        if policy.get("emergency_pause"):
            return False, "the session policy is under an emergency pause"
        for call in decision.prepared:
            if call.selector not in ALLOWED_SELECTORS:
                return False, (
                    f"selector {call.selector} is not one this category emits "
                    f"({sorted(ALLOWED_SELECTORS)}); a grid that drafted another call is "
                    "a bug in the lifecycle, not a policy question"
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
            # `False` is the chain refusing. `None` is a call whose preflight could not
            # run yet because an earlier call in this same batch creates its
            # precondition — the allowance the swap needs. Only the first is a refusal.
            if call.simulation["ok"] is False:
                return False, (
                    "the chain disagreed with this call at simulation: "
                    f"{call.simulation['revert_reason']}"
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


register(CATEGORY, GridExecutor())
