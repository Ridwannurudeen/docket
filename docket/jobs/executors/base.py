"""What an executor is allowed to be, and the two shapes it speaks in.

An executor reads a position and says what it thinks should happen. It never holds a key
and it never sends anything: the only module that signs is
`docket.sessions.executor.execute`, and the only thing an executor may hand it is a
`PreparedCall`. That separation is the whole reason this file is a Protocol rather than a
base class with a `send` method somebody could override.

A `PreparedCall` carries its own simulation, taken at a named block. A call whose
simulation is stale or absent is a call nobody has asked the chain about, and the
difference between those two is the difference between "the chain agrees" and "we did not
check" — which is why `simulation` is a required field rather than an optional one.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Protocol

BSC_CHAIN_ID = 56
DECISION_KINDS = ("noop", "alert", "action")


@dataclass(frozen=True)
class PreparedCall:
    """One transaction, ready to sign, with what the chain said about it.

    `data` is a 0x-prefixed hex string rather than bytes: this object is stored as JSON
    inside an activation and handed to a browser, and bytes that survive neither round
    trip would have to be re-encoded at every boundary.
    """

    to: str
    data: str
    value_atomic: str
    gas_ceiling: int
    deadline: int
    purpose: str
    simulation: dict
    chain_id: int = BSC_CHAIN_ID

    def __post_init__(self) -> None:
        if not self.data.startswith("0x"):
            raise ValueError("prepared calldata must be a 0x-prefixed hex string")
        if self.gas_ceiling <= 0:
            raise ValueError("a prepared call with no gas ceiling is unbounded")
        if not self.purpose.strip():
            raise ValueError("a prepared call must say what it is for")
        if "ok" not in self.simulation:
            raise ValueError(
                "a prepared call must carry its simulation: a call nobody asked the "
                "chain about is not the same thing as one the chain agreed to"
            )
        # Parsed rather than trusted, for the reason Quote gives: an atomic value travels
        # as a string and a string that is not a number must fail where it is built.
        int(self.value_atomic)

    @property
    def selector(self) -> str:
        """The 4-byte function selector this call invokes, lowercased."""
        return self.data[:10].lower()

    def to_dict(self) -> dict:
        return {
            "to": self.to,
            "data": self.data,
            "value_atomic": self.value_atomic,
            "chain_id": self.chain_id,
            "gas_ceiling": self.gas_ceiling,
            "deadline": self.deadline,
            "purpose": self.purpose,
            "simulation": self.simulation,
        }

    @classmethod
    def from_dict(cls, payload: dict) -> "PreparedCall":
        return cls(
            to=payload["to"],
            data=payload["data"],
            value_atomic=payload["value_atomic"],
            chain_id=payload.get("chain_id", BSC_CHAIN_ID),
            gas_ceiling=payload["gas_ceiling"],
            deadline=payload["deadline"],
            purpose=payload["purpose"],
            simulation=payload["simulation"],
        )


@dataclass(frozen=True)
class Decision:
    """What an executor concluded, and the evidence it concluded it from."""

    kind: str
    summary: str
    prepared: tuple[PreparedCall, ...]
    evidence: dict
    observed_at: str
    block: int

    def __post_init__(self) -> None:
        if self.kind not in DECISION_KINDS:
            raise ValueError(
                f"unknown decision kind {self.kind!r}; expected one of {DECISION_KINDS}"
            )
        if not self.summary.strip():
            raise ValueError("a decision must say what it decided")
        if self.kind == "action" and not self.prepared:
            raise ValueError("an action decision with no prepared call acts on nothing")
        if self.kind != "action" and self.prepared:
            raise ValueError(
                f"a {self.kind} decision carries prepared calls that nothing would send"
            )

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "summary": self.summary,
            "prepared": [call.to_dict() for call in self.prepared],
            "evidence": self.evidence,
            "observed_at": self.observed_at,
            "block": self.block,
        }


class Executor(Protocol):
    """One category's opinion, and its own reading of whether the policy permits it."""

    category: str

    def evaluate(self, activation, *, reader=None) -> Decision: ...

    def within_policy(self, activation, decision) -> tuple[bool, str]: ...


@dataclass(frozen=True)
class NoopExecutor:
    """An executor for a category that has nothing to do yet.

    It exists so the tick loop has something real to run against before a category's own
    executor lands, and so a test of the loop is a test of the loop rather than of a
    mock. It reads nothing and returns `noop` every time, and reports block 0 with its
    evidence saying why rather than a block number it never asked anybody for.
    """

    category: str
    summary: str = "nothing to do: this category has no executor of its own yet"
    evidence: dict = field(default_factory=dict)

    def evaluate(self, activation, *, reader=None) -> Decision:
        return Decision(
            kind="noop",
            summary=self.summary,
            prepared=(),
            evidence={
                **self.evidence,
                "read": "none: this executor makes no chain call",
            },
            observed_at=datetime.now(timezone.utc).isoformat(),
            block=0,
        )

    def within_policy(self, activation, decision) -> tuple[bool, str]:
        return False, "a noop decision proposes nothing for a policy to permit"
