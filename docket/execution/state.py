"""Where an action is in its life, and the edges that do not exist.

The table below is the whole module, and its most important entries are the empty
ones. `submitted` leads to `confirmed` or `failed` and to nothing else: a broadcast
transaction is in somebody's mempool, and a machine that let a record walk back to
`authorized` would be modelling a chain that can un-send. `revoked` and `expired`
lead nowhere at all, which mirrors the authority standing behind them — a revoked
session key cannot be reactivated on chain, so a revoked record is not reactivated
here either. If the two disagreed, the softer one would be the one somebody trusted.

`paused` is the single reversible stop, and it rewinds to `draft` rather than to
where it was paused. An action resumed straight into `active` would be acting on a
simulation taken before whatever caused the pause, and what usually causes a pause is
the market moving. Starting over costs one `eth_call`.

Every move records when it happened and why, because a history of bare state names is
a history nobody can read a week later.
"""

from dataclasses import dataclass
from enum import Enum

from . import now


class ActionState(str, Enum):
    """A str enum so a state survives a round trip through JSON as itself."""

    DRAFT = "draft"
    SIMULATED = "simulated"
    AUTHORIZED = "authorized"
    ACTIVE = "active"
    SUBMITTED = "submitted"
    CONFIRMED = "confirmed"
    FAILED = "failed"
    PAUSED = "paused"
    EXPIRED = "expired"
    REVOKED = "revoked"


# The four states an action can still be stopped in for free — nothing has been
# broadcast, so stopping costs nothing and changes nothing on chain.
PRE_SUBMISSION = frozenset(
    {
        ActionState.DRAFT,
        ActionState.SIMULATED,
        ActionState.AUTHORIZED,
        ActionState.ACTIVE,
    }
)
# The ways a pre-submission action can be stopped. `paused` is reversible; the other
# two are not, and that asymmetry is deliberate.
STOPS = frozenset({ActionState.PAUSED, ActionState.EXPIRED, ActionState.REVOKED})
# Nothing leaves these. `submitted` is not among them — it has two outcomes — but it
# has no way back either, which is asserted by the table rather than by this set.
TERMINAL = frozenset(
    {
        ActionState.CONFIRMED,
        ActionState.FAILED,
        ActionState.EXPIRED,
        ActionState.REVOKED,
    }
)

ALLOWED: dict[ActionState, frozenset[ActionState]] = {
    ActionState.DRAFT: frozenset({ActionState.SIMULATED}) | STOPS,
    ActionState.SIMULATED: frozenset({ActionState.AUTHORIZED}) | STOPS,
    ActionState.AUTHORIZED: frozenset({ActionState.ACTIVE}) | STOPS,
    ActionState.ACTIVE: frozenset({ActionState.SUBMITTED}) | STOPS,
    ActionState.SUBMITTED: frozenset({ActionState.CONFIRMED, ActionState.FAILED}),
    ActionState.CONFIRMED: frozenset(),
    ActionState.FAILED: frozenset(),
    # Re-simulate or nothing.
    ActionState.PAUSED: frozenset({ActionState.DRAFT}),
    ActionState.EXPIRED: frozenset(),
    ActionState.REVOKED: frozenset(),
}


class IllegalTransition(RuntimeError):
    """A move the table does not have an edge for. The action does not move."""


@dataclass(frozen=True)
class Transition:
    from_state: ActionState
    to_state: ActionState
    at: int
    reason: str

    def as_record(self) -> dict:
        return {
            "from_state": self.from_state.value,
            "to_state": self.to_state.value,
            "at": self.at,
            "reason": self.reason,
        }


class ActionLifecycle:
    """One intent's position in the table, with the history of how it got there.

    Holds no intent and no calldata — only the id, so a receipt can bind the two. The
    intent is frozen and this is not; keeping them apart means the mutable half cannot
    quietly rewrite a bound.
    """

    def __init__(self, intent_id: str, *, state: ActionState = ActionState.DRAFT) -> None:
        if not intent_id.strip():
            raise ValueError("a lifecycle must name the intent it tracks")
        self.intent_id = intent_id
        self._state = state
        self._history: list[Transition] = []

    @property
    def state(self) -> ActionState:
        return self._state

    @property
    def history(self) -> tuple[Transition, ...]:
        """A snapshot, not the list. A caller holding the live list could append to it."""
        return tuple(self._history)

    def transition(self, to_state: ActionState, *, reason: str) -> Transition:
        """Move, or raise and stay exactly where it was.

        The reason is required and checked before the edge is, so a caller cannot get a
        legal move recorded with no explanation of why it was made.
        """
        if not reason.strip():
            raise ValueError(
                f"{self.intent_id}: a transition to {to_state.value} needs a reason — a "
                "history of bare state names cannot be read afterwards"
            )
        if to_state not in ALLOWED[self._state]:
            raise IllegalTransition(
                f"{self.intent_id}: {self._state.value} -> {to_state.value} is not a "
                f"transition this machine has. From {self._state.value} the only moves are "
                f"{sorted(s.value for s in ALLOWED[self._state]) or 'none'}."
            )
        step = Transition(
            from_state=self._state, to_state=to_state, at=now(), reason=reason.strip()
        )
        self._state = to_state
        self._history.append(step)
        return step

    def as_record(self) -> dict:
        return {
            "intent_id": self.intent_id,
            "state": self._state.value,
            "history": [step.as_record() for step in self._history],
        }
