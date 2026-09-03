"""What an activation is, and which changes to it are legal.

An activation is the record of one owner asking one service to do one job. Two kinds,
because the two have almost nothing in common after the first three steps: a `one_shot`
runs once and hands back a result, and a `persistent` holds a bounded session key and
keeps acting until the owner stops it or its policy expires.

The state sets are closed and the transition table is explicit rather than derived. A
state machine written as a series of `if` statements scattered through the code that
mutates it is a machine nobody can read, and the first illegal move it permits is the one
nobody thought to forbid. `TRANSITIONS` is the whole of what may happen; anything absent
from it raises `IllegalTransition` and leaves the activation exactly as it was.

Every accepted change appends an `Event` carrying who made it — the owner, Docket's own
tick, or the chain answering a question Docket put to it. An activation therefore reads
as its own audit trail rather than as a current state with the history thrown away.

The four category strings are BNB's four. They are checked against
`docket.marketplace.models.Category` by a test rather than imported from it, so this
module stays free of the catalogue and the whole advantage stack standing behind it.
"""

import json
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timezone

ONE_SHOT = "one_shot"
PERSISTENT = "persistent"
KINDS = (ONE_SHOT, PERSISTENT)

CATEGORIES = ("rebalancing", "grid_trading", "yield_optimisation", "health_factor")

ONE_SHOT_STATES = (
    "quoted",
    "awaiting_wallet",
    "authorized",
    "paid_or_reserved",
    "queued",
    "running",
    "needs_approval",
    "completed",
    "failed",
    "refunded",
)
PERSISTENT_STATES = (
    "quoted",
    "awaiting_wallet",
    "authorized",
    "funded",
    "active",
    "paused",
    "needs_approval",
    "revoked",
    "expired",
)

# Named rather than inferred from an empty transition row: a reader asking whether an
# activation is finished should not have to know that "no outgoing edges" is what
# finished means here.
ONE_SHOT_TERMINAL = ("completed", "failed", "refunded")
PERSISTENT_TERMINAL = ("revoked", "expired")

TRANSITIONS: dict[str, dict[str, tuple[str, ...]]] = {
    ONE_SHOT: {
        "quoted": ("awaiting_wallet",),
        "awaiting_wallet": ("authorized",),
        "authorized": ("paid_or_reserved", "failed", "refunded"),
        "paid_or_reserved": ("queued", "failed", "refunded"),
        "queued": ("running", "failed", "refunded"),
        "running": ("needs_approval", "completed", "failed"),
        "needs_approval": ("running", "completed", "failed", "refunded"),
        "completed": (),
        "failed": (),
        "refunded": (),
    },
    PERSISTENT: {
        "quoted": ("awaiting_wallet",),
        "awaiting_wallet": ("authorized",),
        "authorized": ("funded", "revoked", "expired"),
        "funded": ("active", "revoked", "expired"),
        "active": ("paused", "needs_approval", "revoked", "expired"),
        "paused": ("active", "revoked", "expired"),
        "needs_approval": ("active", "paused", "revoked", "expired"),
        "revoked": (),
        "expired": (),
    },
}

ACTORS = ("user", "docket", "chain")
NEXT_ACTION_KINDS = (
    "connect_wallet",
    "approve_token",
    "sign_payment",
    "fund_session",
    "approve_nft",
    "sign_transaction",
    "wait",
    "none",
)
PAYMENT_SCHEMES = ("x402-exact", "free_tier")


class IllegalTransition(ValueError):
    """A move the state machine has no edge for."""


def new_activation_id() -> str:
    """`act_` and 24 hex characters from the system CSPRNG.

    Twelve random bytes rather than a counter: every mutating route reads an id out of
    the URL, and an id a stranger can guess is an id a stranger can quote back.
    """
    return "act_" + secrets.token_hex(12)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def states_for(kind: str) -> tuple[str, ...]:
    if kind == ONE_SHOT:
        return ONE_SHOT_STATES
    if kind == PERSISTENT:
        return PERSISTENT_STATES
    raise ValueError(f"unknown activation kind {kind!r}; expected one of {KINDS}")


def terminal_states_for(kind: str) -> tuple[str, ...]:
    if kind == ONE_SHOT:
        return ONE_SHOT_TERMINAL
    if kind == PERSISTENT:
        return PERSISTENT_TERMINAL
    raise ValueError(f"unknown activation kind {kind!r}; expected one of {KINDS}")


@dataclass(frozen=True)
class Quote:
    """What this activation costs and who is paid, stated before anything is signed."""

    asset: str
    amount_atomic: str
    amount_display: str
    pay_to: str | None
    payment_scheme: str

    def __post_init__(self) -> None:
        if self.payment_scheme not in PAYMENT_SCHEMES:
            raise ValueError(
                f"unknown payment scheme {self.payment_scheme!r}; "
                f"expected one of {PAYMENT_SCHEMES}"
            )
        if self.payment_scheme == "x402-exact" and not self.pay_to:
            raise ValueError("a priced quote must name the address that is paid")
        # Atomic amounts travel as strings so a 1e18-scaled figure survives JSON intact.
        # Parsed here so a quote that is not a number fails where it is built.
        int(self.amount_atomic)

    def to_dict(self) -> dict:
        return {
            "asset": self.asset,
            "amount_atomic": self.amount_atomic,
            "amount_display": self.amount_display,
            "pay_to": self.pay_to,
            "payment_scheme": self.payment_scheme,
        }

    @classmethod
    def from_dict(cls, payload: dict) -> "Quote":
        return cls(
            asset=payload["asset"],
            amount_atomic=payload["amount_atomic"],
            amount_display=payload["amount_display"],
            pay_to=payload["pay_to"],
            payment_scheme=payload["payment_scheme"],
        )


@dataclass(frozen=True)
class Receipt:
    """One delivered thing, bound to the request that asked for it.

    The first five fields are exactly what `docket.hire.receipts.build_receipt` returns,
    so a hire receipt travels through an activation unreshaped — re-serialising it would
    leave the buyer holding hashes that no longer check. `execution` carries the on-chain
    half of a receipt a session produced: the transaction, its gas and its status.
    """

    service: str
    input_hash: str
    output_hash: str
    delivered_at: str
    payment: dict | None = None
    execution: dict | None = None

    @classmethod
    def from_hire(cls, receipt: dict, *, execution: dict | None = None) -> "Receipt":
        return cls(
            service=receipt["service"],
            input_hash=receipt["input_hash"],
            output_hash=receipt["output_hash"],
            delivered_at=receipt["delivered_at"],
            payment=receipt.get("payment"),
            execution=execution,
        )

    def to_dict(self) -> dict:
        return {
            "service": self.service,
            "input_hash": self.input_hash,
            "output_hash": self.output_hash,
            "delivered_at": self.delivered_at,
            "payment": self.payment,
            "execution": self.execution,
        }

    @classmethod
    def from_dict(cls, payload: dict) -> "Receipt":
        return cls(
            service=payload["service"],
            input_hash=payload["input_hash"],
            output_hash=payload["output_hash"],
            delivered_at=payload["delivered_at"],
            payment=payload.get("payment"),
            execution=payload.get("execution"),
        )


@dataclass(frozen=True)
class Event:
    """One accepted change, and who made it."""

    at: str
    from_state: str
    to_state: str
    reason: str
    actor: str

    def __post_init__(self) -> None:
        if self.actor not in ACTORS:
            raise ValueError(
                f"unknown event actor {self.actor!r}; expected one of {ACTORS}"
            )
        if not self.reason.strip():
            raise ValueError("an event without a reason records nothing worth keeping")

    def to_dict(self) -> dict:
        return {
            "at": self.at,
            "from_state": self.from_state,
            "to_state": self.to_state,
            "reason": self.reason,
            "actor": self.actor,
        }

    @classmethod
    def from_dict(cls, payload: dict) -> "Event":
        return cls(
            at=payload["at"],
            from_state=payload["from_state"],
            to_state=payload["to_state"],
            reason=payload["reason"],
            actor=payload["actor"],
        )


@dataclass(frozen=True)
class NextAction:
    """The one thing that has to happen next, in terms a browser can act on."""

    kind: str
    detail: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.kind not in NEXT_ACTION_KINDS:
            raise ValueError(
                f"unknown next action {self.kind!r}; expected one of {NEXT_ACTION_KINDS}"
            )

    def to_dict(self) -> dict:
        return {"kind": self.kind, "detail": self.detail}

    @classmethod
    def from_dict(cls, payload: dict) -> "NextAction":
        return cls(kind=payload["kind"], detail=payload.get("detail") or {})


@dataclass
class Activation:
    """One owner's standing instruction, with everything that has happened to it.

    Mutable, unlike most of this codebase: an activation is the one object here whose
    whole purpose is to change, and a frozen record replaced wholesale on every event
    would make the optimistic write in the store harder to read rather than easier.

    `result` holds two different things and the key says which. A one-shot's `result` is
    the service's own output. A persistent activation's `result["last_decision"]` is
    **the executor's carry-over state**:

        {"kind", "summary", "observed_at", "block", "evidence"}

    written by `docket.jobs.tick` on every pass, including a pass that decided to do
    nothing. An executor is constructed, asked once and dropped, so `evidence` is the only
    place a measurement survives to the next pass — time a position has spent out of
    range, the rung of a grid last filled, the price a comparison was made against. An
    executor reads its own prior `evidence` back from here; nothing else writes that key.
    """

    activation_id: str
    service_id: str
    category: str
    kind: str
    owner: str
    state: str
    quote: Quote
    policy: dict | None
    session: dict | None
    inputs: dict
    result: dict | None
    receipts: tuple[Receipt, ...]
    events: tuple[Event, ...]
    next_action: NextAction
    auth_nonce: str
    created_at: str
    updated_at: str
    expires_at: str | None

    def __post_init__(self) -> None:
        if self.kind not in KINDS:
            raise ValueError(
                f"unknown activation kind {self.kind!r}; expected one of {KINDS}"
            )
        if self.category not in CATEGORIES:
            raise ValueError(
                f"unknown category {self.category!r}; expected one of {CATEGORIES}"
            )
        if self.state not in states_for(self.kind):
            raise ValueError(
                f"a {self.kind} activation has no state {self.state!r}; "
                f"expected one of {states_for(self.kind)}"
            )

    @property
    def is_terminal(self) -> bool:
        return self.state in terminal_states_for(self.kind)

    def may_move_to(self, to_state: str) -> bool:
        return to_state in TRANSITIONS[self.kind].get(self.state, ())

    def transition(
        self, to_state: str, *, reason: str, actor: str, at: str | None = None
    ) -> None:
        """Move, or refuse and leave everything exactly where it was."""
        if not self.may_move_to(to_state):
            raise IllegalTransition(
                f"{self.activation_id}: a {self.kind} activation in {self.state!r} "
                f"cannot move to {to_state!r}; the legal moves from here are "
                f"{TRANSITIONS[self.kind].get(self.state, ())}"
            )
        moment = _now() if at is None else at
        self.events = self.events + (
            Event(
                at=moment,
                from_state=self.state,
                to_state=to_state,
                reason=reason,
                actor=actor,
            ),
        )
        self.state = to_state
        self.updated_at = moment

    def note(self, reason: str, *, actor: str, at: str | None = None) -> None:
        """Record something that happened without changing state.

        A failed execution and a category with no executor registered are both worth
        keeping and neither is a move. They go in the same list as the transitions, so an
        activation has one history rather than two half-histories a reader has to
        interleave by timestamp.
        """
        moment = _now() if at is None else at
        self.events = self.events + (
            Event(
                at=moment,
                from_state=self.state,
                to_state=self.state,
                reason=reason,
                actor=actor,
            ),
        )
        self.updated_at = moment

    def add_receipt(self, receipt: Receipt) -> None:
        self.receipts = self.receipts + (receipt,)

    def to_dict(self) -> dict:
        """The whole activation as JSON, which is also what the API serves."""
        return {
            "activation_id": self.activation_id,
            "service_id": self.service_id,
            "category": self.category,
            "kind": self.kind,
            "owner": self.owner,
            "state": self.state,
            "quote": self.quote.to_dict(),
            "policy": self.policy,
            "session": self.session,
            "inputs": self.inputs,
            "result": self.result,
            "receipts": [receipt.to_dict() for receipt in self.receipts],
            "events": [event.to_dict() for event in self.events],
            "next_action": self.next_action.to_dict(),
            "auth_nonce": self.auth_nonce,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "expires_at": self.expires_at,
        }

    @classmethod
    def from_dict(cls, payload: dict) -> "Activation":
        return cls(
            activation_id=payload["activation_id"],
            service_id=payload["service_id"],
            category=payload["category"],
            kind=payload["kind"],
            owner=payload["owner"],
            state=payload["state"],
            quote=Quote.from_dict(payload["quote"]),
            policy=payload["policy"],
            session=payload["session"],
            inputs=payload["inputs"],
            result=payload["result"],
            receipts=tuple(
                Receipt.from_dict(item) for item in payload.get("receipts") or ()
            ),
            events=tuple(Event.from_dict(item) for item in payload.get("events") or ()),
            next_action=NextAction.from_dict(payload["next_action"]),
            auth_nonce=payload["auth_nonce"],
            created_at=payload["created_at"],
            updated_at=payload["updated_at"],
            expires_at=payload["expires_at"],
        )


def dumps(value) -> str:
    """Canonical JSON for a stored column: sorted, finite, and never ASCII-escaped."""
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False)


def loads(blob: str | None, default=None):
    return default if blob is None else json.loads(blob)
