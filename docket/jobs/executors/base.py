"""What every category executor hands back, and the shape the tick loop calls it through.

One decision object, one prepared-call object, and a registry keyed by category. The
three exist so the loop never has to know which agent it is running: it looks up
`EXECUTORS[activation.category]`, asks for a decision, checks that decision against the
activation's own policy, and hands whatever came back to the session executor.

**An executor holds no key and sends nothing.** It reads, it decides, and it builds
calldata. `docket/sessions/executor.py` is the only thing that signs, which is why
`PreparedCall` carries its own simulation record: the decision to act and the evidence
that the chain agreed with it travel on the same object, so a call that was never
simulated cannot be mistaken for one that simulated clean.

`Activation` is Lane B's dataclass in `docket/jobs/models.py`. It is referenced here
under `TYPE_CHECKING` only, so this package imports before that module lands and an
executor can be exercised against any object carrying the attributes it actually reads:
`category`, `inputs`, `policy`, `session` and `owner`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:  # pragma: no cover - Lane B owns the model this annotates
    from ..models import Activation

BSC_CHAIN_ID = 56
# The three kinds a decision may be. Closed, because the loop dispatches on it: an
# unknown kind read through an `elif` chain would be treated as "not an action", which
# is the failure where an agent quietly stops working and nothing says so.
DECISION_KINDS = frozenset({"noop", "alert", "action"})
# The keys a simulation record must carry. Named rather than duck-typed because a
# half-written preflight reads exactly like one that passed.
SIMULATION_FIELDS = ("ok", "gas_estimate", "revert_reason", "observed_at", "block")


@dataclass(frozen=True)
class PreparedCall:
    """One transaction, fully built, with what the chain said about it attached."""

    to: str
    data: str
    value_atomic: int
    gas_ceiling: int
    deadline: int
    purpose: str
    simulation: dict
    chain_id: int = BSC_CHAIN_ID

    def __post_init__(self) -> None:
        if self.chain_id != BSC_CHAIN_ID:
            raise ValueError(
                f"prepared call {self.purpose!r}: chain_id {self.chain_id} is not "
                f"{BSC_CHAIN_ID}. Every address this package builds against was read "
                "from BSC mainnet; on another chain they name somebody else's contract."
            )
        if not isinstance(self.data, str) or not self.data.startswith("0x"):
            raise ValueError(
                f"prepared call {self.purpose!r}: data must be 0x-prefixed hex"
            )
        if self.gas_ceiling <= 0:
            raise ValueError(
                f"prepared call {self.purpose!r}: gas_ceiling must be positive"
            )
        missing = [key for key in SIMULATION_FIELDS if key not in self.simulation]
        if missing:
            raise ValueError(
                f"prepared call {self.purpose!r}: simulation is missing {missing}. A "
                "call whose preflight is half-recorded reads as one that passed."
            )

    def as_record(self) -> dict:
        return {
            "to": self.to,
            "data": self.data,
            "value_atomic": str(self.value_atomic),
            "chain_id": self.chain_id,
            "gas_ceiling": self.gas_ceiling,
            "deadline": self.deadline,
            "purpose": self.purpose,
            "simulation": dict(self.simulation),
        }


@dataclass(frozen=True)
class Decision:
    """One observation turned into nothing, a warning, or an ordered list of calls."""

    kind: str
    summary: str
    prepared: tuple[PreparedCall, ...] = ()
    evidence: dict = field(default_factory=dict)
    observed_at: str = ""
    block: int = 0

    def __post_init__(self) -> None:
        if self.kind not in DECISION_KINDS:
            raise ValueError(
                f"decision kind {self.kind!r} is not one of {sorted(DECISION_KINDS)}"
            )
        if self.kind != "action" and self.prepared:
            raise ValueError(
                f"a {self.kind!r} decision carries {len(self.prepared)} prepared calls. "
                "Only an action may carry calls; anything else hands the loop "
                "transactions under a heading that says not to send them."
            )
        if self.kind == "action" and not self.prepared:
            raise ValueError(
                "an action decision with no prepared calls is a decision to do nothing "
                "wearing the wrong label"
            )

    def as_record(self) -> dict:
        return {
            "kind": self.kind,
            "summary": self.summary,
            "prepared": [call.as_record() for call in self.prepared],
            "evidence": self.evidence,
            "observed_at": self.observed_at,
            "block": self.block,
        }


@runtime_checkable
class Executor(Protocol):
    """The whole surface the tick loop uses. Two methods, and neither one sends."""

    category: str

    def evaluate(self, activation: "Activation", *, reader=None) -> Decision: ...

    def within_policy(
        self, activation: "Activation", decision: Decision
    ) -> tuple[bool, str]: ...
