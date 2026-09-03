"""The executor contract: one prepared call, one decision, and the protocol between them.

An executor reads live state and computes; it holds no key, builds no signature and has
no method that sends. `docket/sessions/executor.py` is the only thing in Docket that
signs, and it re-simulates every call at send time rather than trusting a preflight taken
at evaluation.
"""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class PreparedCall:
    to: str
    data: str
    value_atomic: int
    chain_id: int
    gas_ceiling: int
    deadline: int
    purpose: str
    simulation: dict


@dataclass(frozen=True)
class Decision:
    kind: str
    summary: str
    prepared: tuple[PreparedCall, ...]
    evidence: dict
    observed_at: str
    block: int


class Executor(Protocol):
    category: str

    def evaluate(self, activation, *, reader=None) -> Decision: ...

    def within_policy(self, activation, decision: Decision) -> tuple[bool, str]: ...
