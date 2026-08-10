"""What an autonomous action is allowed to be, written down before it is taken.

A session key with a call allowlist and a spend cap answers two questions: which
contract may be called, and how much may leave. It does not answer the one that
costs money. A swap to an allowlisted router, inside the cap, can still be executed
at a ruinous price — the allowlist has no opinion about what comes back. That gap is
where an automated trader gets sandwiched, and no amount of capping closes it.

So every action here carries a semantic commitment as well as a permission. The
condition that has to hold before it fires, the exact contract and function, a hash
of the calldata itself, the most that may go in, the least that must come back, the
route, the slippage bound, the deadline, a gas ceiling and a nonce. Two of those are
load-bearing beyond the rest:

`min_output` has no default and may not be zero. "Whatever the pool gives me" is the
single most expensive value in this file, and it is unreachable — construction
raises. Every other bound can be argued about; this one is refused outright.

`calldata_hash` is what makes a submitted transaction provably the authorised one.
Without it an intent says "call the router" and any call to the router satisfies it.
With it, `matches()` can be run against the bytes actually being sent, and a
transaction that is not the one that was reasoned about is not sent.

The record is frozen and holds integers throughout. Atomic units, never decimals:
this is hashed, and a float that round-trips differently on another machine is a
commitment that does not check. BSC's USDT is 18 decimals, not 6.
"""

from dataclasses import dataclass, fields

from web3 import Web3

from ..hire.receipts import canonical_hash
from . import now

BSC_CHAIN_ID = 56
# 5%. Not a policy — a wall. A grid that wants to trade through more slippage than
# this is not a grid whose author has thought about what fills it.
SLIPPAGE_BPS_CEILING = 500
# What an observed price may be compared against. Closed, because a free-text
# condition is one nobody can evaluate the same way twice — and an intent whose
# trigger cannot be re-evaluated by a reader is an intent nobody can audit.
CONDITION_KINDS = frozenset({"price_at_or_below", "price_at_or_above"})


def commit(calldata: bytes) -> str:
    """Keccak-256 over the exact calldata bytes, `0x`-prefixed.

    Keccak rather than the SHA-256 the receipts use, because this is the one hash in
    Docket that is chain-shaped: a contract asked to check an intent computes this
    with a single opcode, where SHA-256 would cost it a precompile call.
    """
    return "0x" + Web3.keccak(calldata).hex()


def _whole_number(value, field: str, subject: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(
            f"{subject}: {field} must be an integer of atomic units, got {value!r}. "
            "Decimals are not carried here — this record is hashed, and a float is a "
            "commitment that checks on one machine and not on another."
        )


@dataclass(frozen=True)
class Condition:
    """The predicate that has to hold before an action may fire.

    Declarative on purpose: the operator evaluates it against an observation it just
    read, and a reader can evaluate the same predicate against the same observation
    and get the same answer. A condition expressed as a callable would be neither
    hashable nor auditable.
    """

    kind: str
    subject: str
    threshold: int

    def __post_init__(self) -> None:
        if self.kind not in CONDITION_KINDS:
            raise ValueError(
                f"condition kind {self.kind!r} is not one of {sorted(CONDITION_KINDS)}"
            )
        if not self.subject.strip():
            raise ValueError("condition: subject is required — a predicate about nothing")
        _whole_number(self.threshold, "threshold", f"condition {self.kind}")

    def holds(self, observed: int) -> bool:
        """Whether this predicate is true of an observed price, in the same atomic units.

        Both comparisons are inclusive. A grid level set exactly at the observed price
        is a level that has been reached, and excluding the boundary would mean a level
        that is hit precisely never fires.
        """
        _whole_number(observed, "observed", f"condition {self.kind}")
        if self.kind == "price_at_or_below":
            return observed <= self.threshold
        return observed >= self.threshold


# Everything that makes one action a different action from another. `intent_id` is a
# label and `evidence_block` is when the trigger was read, so neither is here: the
# same action derived twice at different blocks is one action and must key alike,
# while a re-priced one — a different min_output, a different deadline — must not.
_KEYED_FIELDS = (
    "chain_id",
    "target",
    "selector",
    "calldata_hash",
    "token_in",
    "token_out",
    "max_input",
    "min_output",
    "route",
    "slippage_bps",
    "deadline",
    "gas_ceiling",
    "nonce",
    "policy_version",
)


@dataclass(frozen=True)
class ActionIntent:
    """One action, fully bounded, before anybody has been asked to authorise it."""

    intent_id: str
    condition: Condition
    chain_id: int
    target: str
    selector: str
    calldata_hash: str
    token_in: str
    token_out: str
    max_input: int
    min_output: int
    route: tuple[str, ...]
    slippage_bps: int
    deadline: int
    gas_ceiling: int
    nonce: int
    policy_version: str
    evidence_block: int

    def __post_init__(self) -> None:
        subject = f"intent {self.intent_id!r}"
        if self.chain_id != BSC_CHAIN_ID:
            raise ValueError(
                f"{subject}: chain_id {self.chain_id} is not {BSC_CHAIN_ID}. Every address "
                "in this package was read from BSC mainnet; on another chain they name "
                "either nothing or somebody else's contract."
            )

        # Addresses first, so the checks below and the key are computed over one
        # spelling. A lowercased address and a checksummed one are the same account,
        # and if they hashed differently the key would let one action through twice.
        for field in ("target", "token_in", "token_out"):
            object.__setattr__(self, field, _address(getattr(self, field), field, subject))
        object.__setattr__(
            self, "route", tuple(_address(hop, "route", subject) for hop in self.route)
        )

        if not isinstance(self.selector, str) or not (
            self.selector.startswith("0x") and len(self.selector) == 10
        ):
            raise ValueError(f"{subject}: selector {self.selector!r} is not four hex bytes")
        try:
            bytes.fromhex(self.selector[2:])
        except ValueError:
            raise ValueError(
                f"{subject}: selector {self.selector!r} is not four hex bytes"
            ) from None

        # Through `_whole_number` like every other quantity here, and for one reason
        # beyond consistency: `True` is an `int` in Python and slips past a bare `> 0`,
        # so `min_output=True` would construct as a floor of one wei — a record that
        # reads as bounded and is not.
        if self.min_output is None:
            raise ValueError(
                f"{subject}: min_output must be a positive integer of atomic units. An "
                "action that accepts any output is an action that can be sandwiched to "
                "nothing, and there is no default for it here on purpose."
            )
        _whole_number(self.min_output, "min_output", subject)
        if self.min_output <= 0:
            raise ValueError(
                f"{subject}: min_output must be a positive integer of atomic units. An "
                "action that accepts any output is an action that can be sandwiched to "
                "nothing, and there is no default for it here on purpose."
            )
        _whole_number(self.max_input, "max_input", subject)
        if self.max_input <= 0:
            raise ValueError(f"{subject}: max_input must be positive")
        _whole_number(self.slippage_bps, "slippage_bps", subject)
        if not 0 <= self.slippage_bps <= SLIPPAGE_BPS_CEILING:
            raise ValueError(
                f"{subject}: slippage_bps {self.slippage_bps} is outside 0..{SLIPPAGE_BPS_CEILING}"
            )
        _whole_number(self.gas_ceiling, "gas_ceiling", subject)
        if self.gas_ceiling <= 0:
            raise ValueError(f"{subject}: gas_ceiling must be positive")
        # The nonce goes into the idempotency key, so a nonce of an unexpected shape is an
        # action that keys unlike every other one and therefore dedupes against nothing.
        _whole_number(self.nonce, "nonce", subject)
        if self.nonce < 0:
            raise ValueError(f"{subject}: nonce must not be negative")
        _whole_number(self.evidence_block, "evidence_block", subject)
        if self.evidence_block <= 0:
            raise ValueError(
                f"{subject}: evidence_block must name the block the condition was read at"
            )
        _whole_number(self.deadline, "deadline", subject)
        if self.deadline <= now():
            raise ValueError(
                f"{subject}: deadline {self.deadline} has already passed. A stale deadline "
                "does not fail closed — it fails at the router, after the transaction has "
                "been paid for."
            )

        if len(self.route) < 2:
            raise ValueError(f"{subject}: a route needs at least the two tokens being swapped")
        if self.route[0] != self.token_in or self.route[-1] != self.token_out:
            raise ValueError(
                f"{subject}: route {self.route} does not run from token_in to token_out. A "
                "route that ends somewhere else is a swap into a token nobody authorised."
            )
        if not self.policy_version.strip():
            raise ValueError(f"{subject}: policy_version is required")

    def matches(self, calldata: bytes) -> bool:
        """Whether these bytes are the call this intent committed to.

        Two independent statements have to agree: the declared selector against the
        first four bytes, and the calldata hash against the whole. The hash alone
        would be enough to prove identity — the selector check catches a record whose
        declared function and committed bytes were never the same call, which is a
        record describing one thing and authorising another.
        """
        if len(calldata) < 4:
            return False
        if "0x" + calldata[:4].hex() != self.selector:
            return False
        return commit(calldata) == self.calldata_hash

    @property
    def idempotency_key(self) -> str:
        """A stable digest of everything that makes this action this action.

        SHA-256 over canonical JSON, the recipe the hire receipts already use, so a
        third party recomputes it in three lines. Uniqueness of `nonce` stays the
        caller's job; what this gives them is a way to tell whether two records they
        are holding are the same action written twice or two actions that differ
        somewhere they did not look.
        """
        return canonical_hash(
            {name: _keyable(getattr(self, name)) for name in _KEYED_FIELDS}
            | {"condition": [self.condition.kind, self.condition.subject, self.condition.threshold]}
        )

    def as_record(self) -> dict:
        """The whole intent as plain JSON types, for a receipt or a preview."""
        out = {}
        for field in fields(self):
            value = getattr(self, field.name)
            out[field.name] = (
                {
                    "kind": value.kind,
                    "subject": value.subject,
                    "threshold": str(value.threshold),
                }
                if isinstance(value, Condition)
                else _keyable(value)
            )
        return out


def _address(value: str, field: str, subject: str) -> str:
    try:
        return Web3.to_checksum_address(value)
    except Exception:
        raise ValueError(f"{subject}: {field} {value!r} is not a BSC address") from None


def _keyable(value):
    """Integers become strings before they are hashed or served.

    A wei figure exceeds what JSON's number type is defined to carry, and a reader
    parsing the digest input in JavaScript would silently round it. Hashing the
    decimal string keeps the digest computable in any language.
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return str(value)
    if isinstance(value, tuple):
        return list(value)
    return value
