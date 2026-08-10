"""Who says an action may happen — and, more to the point, where that is enforced.

Docket holds a session, never the owner key. The owner signs a grant that names which
contracts the session may call, how much it may spend of which token over what period,
and when it stops working. Docket then acts inside that, and the owner can revoke it
without asking Docket for anything.

The sentence that matters is the one about where the limits live. **A check written in
Python is not a limit.** If the cap that stands between a bug and somebody's funds is
an `if` statement in this file, then the funds are protected by Docket's test coverage,
which is not a security model. The caps, the call allowlist and the expiry have to be
enforced by the session authority itself, on chain, reverting at validation time.
Everything in `check()` below is a second gate in front of that one: it may refuse an
action the chain would have allowed, and it must never be the only thing refusing.

So every `SessionStatus` carries the `source` it was read from, and the two values are
`chain` and `stub`. That field is not decoration — it is the difference between an
authority and a note-to-self, and `StubSessionAuthority` says `stub` in it.

What is live today, stated plainly rather than in a footnote: see
`AltanaSessionAuthority.integration_gap()`. The protocol, the checks and the state are
built; the on-chain read that would make them an authority is not, and the class
refuses to be constructed rather than answering `can_execute` out of local memory.
"""

from dataclasses import dataclass, field
from typing import Protocol

from web3 import Web3

from . import now
from .intent import ActionIntent

BSC_CHAIN_ID = 56
# Where a status was read. Two values, because there are two kinds of answer: one the
# chain gave and one this process made up. Anything else would blur them.
STATUS_SOURCES = frozenset({"chain", "stub"})

# The functions this build actually grants, with their full argument lists, so a
# permission written as a bare name still resolves to the selector a transaction
# carries. Bare names are a convenience with a closed vocabulary rather than a guess:
# hashing an unknown name would produce a selector no contract has, and a permission
# nothing can ever match reads as a permission that was granted.
KNOWN_SIGNATURES = {
    "approve": "approve(address,uint256)",
    "swapExactTokensForTokens": (
        "swapExactTokensForTokens(uint256,uint256,address[],address,uint256)"
    ),
}


class IntegrationGap(NotImplementedError):
    """Something this authority would need in order to be one, and does not have."""


def _selector(signature: str) -> str:
    full = KNOWN_SIGNATURES.get(signature, signature)
    if "(" not in full:
        raise ValueError(
            f"call permission: {signature!r} has no argument list and is not one of "
            f"{sorted(KNOWN_SIGNATURES)}. A selector hashed from a bare name matches no "
            "function, so the permission would never fire and would still read as granted."
        )
    return "0x" + Web3.keccak(text=full)[:4].hex()


@dataclass(frozen=True)
class CallPermission:
    """One entry in the session's call allowlist.

    `signature` absent is contract-level: any function on that contract. Present, it is
    method-level, and the two AND together — this contract, that function.
    """

    to: str
    signature: str | None = None
    # Derived from the signature rather than supplied, so the granted function and the
    # four bytes a transaction carries can never be written down as two different things.
    selector: str | None = field(init=False, default=None)

    def __post_init__(self) -> None:
        object.__setattr__(self, "to", Web3.to_checksum_address(self.to))
        object.__setattr__(
            self, "selector", None if self.signature is None else _selector(self.signature)
        )

    def permits(self, target: str, selector: str) -> bool:
        if Web3.to_checksum_address(target) != self.to:
            return False
        return self.selector is None or self.selector == selector


@dataclass(frozen=True)
class SpendPermission:
    """How much of one token may leave, per rolling period, in atomic units."""

    token: str
    limit: int
    period: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "token", Web3.to_checksum_address(self.token))
        if not isinstance(self.limit, int) or self.limit <= 0:
            raise ValueError(f"spend cap on {self.token}: limit must be a positive integer")
        if not isinstance(self.period, int) or self.period <= 0:
            raise ValueError(f"spend cap on {self.token}: period must be positive seconds")


@dataclass(frozen=True)
class SessionPermissions:
    """The whole of what one session may do."""

    calls: tuple[CallPermission, ...]
    spend: tuple[SpendPermission, ...]

    def __post_init__(self) -> None:
        if not self.calls:
            raise ValueError("a session with no call allowlist permits every contract")
        if not self.spend:
            raise ValueError("a session with no spend cap permits every amount")

    def as_record(self) -> dict:
        return {
            "calls": [
                {"to": call.to, "signature": call.signature, "selector": call.selector}
                for call in self.calls
            ],
            "spend": [
                {"token": cap.token, "limit": str(cap.limit), "period": cap.period}
                for cap in self.spend
            ],
        }


@dataclass(frozen=True)
class SessionRef:
    """A handle to a granted session. Carries no key material of any kind."""

    session_id: str
    account: str
    key_address: str
    chain_id: int
    expiry: int


@dataclass(frozen=True)
class SessionStatus:
    """What the authority says about a session right now, and where that came from."""

    valid: bool
    revoked: bool
    expiry: int
    remaining_cap: dict[str, int]
    permissions: SessionPermissions
    chain_id: int
    source: str
    read_at_block: int | None = None

    def __post_init__(self) -> None:
        if self.source not in STATUS_SOURCES:
            raise ValueError(
                f"session status source {self.source!r} is not one of {sorted(STATUS_SOURCES)}. "
                "A status with no stated origin is a status nobody can weigh."
            )
        object.__setattr__(
            self,
            "remaining_cap",
            {
                Web3.to_checksum_address(token): amount
                for token, amount in self.remaining_cap.items()
            },
        )

    def as_record(self) -> dict:
        return {
            "valid": self.valid,
            "revoked": self.revoked,
            "expiry": self.expiry,
            "remaining_cap": {token: str(amount) for token, amount in self.remaining_cap.items()},
            "permissions": self.permissions.as_record(),
            "chain_id": self.chain_id,
            "source": self.source,
            "read_at_block": self.read_at_block,
        }


def check(intent: ActionIntent, status: SessionStatus) -> tuple[bool, str]:
    """Whether this session, as it stands, covers this intent — and why, either way.

    Pure, so both authorities share one set of rules and the rules can be exercised
    without a chain. The order is chosen so the most specific true statement is the one
    returned: a revoked session is reported as revoked rather than as invalid.

    Note what the allowlist check is actually reading. The caps and the revoked flag can
    come from the chain; the call allowlist here is Docket's copy of what was granted.
    That copy going stale can only cause this function to refuse something the chain
    would have allowed, never the reverse — the chain has its own copy and reverts on it.
    """
    if status.chain_id != intent.chain_id:
        return False, (
            f"the session is on chain {status.chain_id} and the intent is on {intent.chain_id}"
        )
    if status.revoked:
        return False, "the session has been revoked, and a revoked session is not reinstatable"
    if status.expiry <= now():
        return False, f"the session expired at {status.expiry}"
    if intent.deadline > status.expiry:
        return False, (
            f"the intent's deadline {intent.deadline} outlives the session, which expires at "
            f"{status.expiry}: a transaction mined after that has nothing authorising it"
        )
    if not status.valid:
        return False, "the authority does not report this session as usable"

    at_target = [call for call in status.permissions.calls if call.to == intent.target]
    if not at_target:
        return False, f"{intent.target} is not in the session's call allowlist"
    if not any(call.permits(intent.target, intent.selector) for call in at_target):
        return False, f"{intent.selector} on {intent.target} is not in the session's call allowlist"

    remaining = status.remaining_cap.get(intent.token_in)
    if remaining is None:
        return False, (
            f"the session has no spend cap for {intent.token_in}, and no cap is not an "
            "unlimited one"
        )
    if intent.max_input > remaining:
        return False, (
            f"max_input {intent.max_input} is beyond the {remaining} left on this "
            f"period's cap for {intent.token_in}"
        )
    return True, (
        f"within the session's allowlist and within the {remaining} left on this period's "
        f"cap, read from {status.source}"
    )


class SessionAuthority(Protocol):
    """What the operator needs from whoever is holding the authority.

    `can_execute` takes the ref explicitly rather than the authority holding one, so a
    single authority can front several sessions and so no call is ambiguous about which
    session it is asking about.
    """

    enforces_on_chain: bool

    def grant(self, permissions: SessionPermissions, expiry: int) -> SessionRef: ...

    def status(
        self, ref: SessionRef, *, permissions: SessionPermissions | None = None
    ) -> SessionStatus: ...

    def revoke(self, ref: SessionRef) -> None: ...

    def can_execute(
        self,
        intent: ActionIntent,
        ref: SessionRef,
        *,
        permissions: SessionPermissions | None = None,
    ) -> tuple[bool, str]: ...


@dataclass
class _Grant:
    permissions: SessionPermissions
    expiry: int
    remaining: dict[str, int] = field(default_factory=dict)


class StubSessionAuthority:
    """An authority that enforces nothing, for tests and for the preview.

    Everything it reports comes out of this process's memory. It is not a limit, it does
    not stand between anything and anybody's funds, and it says so in every status it
    returns by putting `stub` in the `source` field. It exists so the operator, the
    state machine and the refusal paths can be exercised end to end without a wallet.

    One property it does copy from the real thing: revocation is monotonic. A session id
    that has been revoked cannot be granted again. Modelling that as reversible would
    make every test written against this class a test of a weaker authority than the one
    it stands in for.
    """

    enforces_on_chain = False

    def __init__(self, account: str, chain_id: int = BSC_CHAIN_ID) -> None:
        self.account = Web3.to_checksum_address(account)
        self.chain_id = chain_id
        self._grants: dict[str, _Grant] = {}
        self._revoked: set[str] = set()
        self._next = 0

    def grant(
        self,
        permissions: SessionPermissions,
        expiry: int,
        *,
        session_id: str | None = None,
    ) -> SessionRef:
        if session_id is None:
            self._next += 1
            session_id = f"stub-session-{self._next}"
        if session_id in self._revoked:
            raise ValueError(
                f"session {session_id} was revoked, and revocation does not reverse — "
                "granting again would model an authority weaker than the one on chain"
            )
        self._grants[session_id] = _Grant(
            permissions=permissions,
            expiry=expiry,
            remaining={cap.token: cap.limit for cap in permissions.spend},
        )
        return SessionRef(
            session_id=session_id,
            account=self.account,
            # No key is generated: this stub never signs anything, so the field carries
            # the account rather than a fabricated address that looks like a key.
            key_address=self.account,
            chain_id=self.chain_id,
            expiry=expiry,
        )

    def status(
        self, ref: SessionRef, *, permissions: SessionPermissions | None = None
    ) -> SessionStatus:
        grant = self._grants.get(ref.session_id)
        if grant is None:
            raise LookupError(f"no session {ref.session_id} has been granted here")
        revoked = ref.session_id in self._revoked
        return SessionStatus(
            valid=not revoked and grant.expiry > now(),
            revoked=revoked,
            expiry=grant.expiry,
            remaining_cap=dict(grant.remaining),
            permissions=permissions or grant.permissions,
            chain_id=self.chain_id,
            source="stub",
        )

    def revoke(self, ref: SessionRef) -> None:
        self._revoked.add(ref.session_id)

    def record_spend(self, ref: SessionRef, token: str, amount: int) -> None:
        """Draw down the remembered cap, so a sequence of actions can be walked.

        The real cap is decremented by the chain when a transaction validates. This is
        the same arithmetic done from the outside, and it is only ever a simulation of
        the accounting — which is the whole point of the class.
        """
        grant = self._grants[ref.session_id]
        token = Web3.to_checksum_address(token)
        grant.remaining[token] = grant.remaining.get(token, 0) - amount

    def can_execute(
        self,
        intent: ActionIntent,
        ref: SessionRef,
        *,
        permissions: SessionPermissions | None = None,
    ) -> tuple[bool, str]:
        try:
            status = self.status(ref, permissions=permissions)
        except LookupError as exc:
            return False, str(exc)
        return check(intent, status)


class AltanaSessionAuthority:
    """A session enforced by Altana's own validator, read back from the chain.

    Constructing one requires the two things that make it an authority rather than a
    memo: the address of the contract that holds session state on BSC, and a reader that
    performs the `eth_call` against it. Without them the constructor raises — see
    `integration_gap()` — because a `can_execute` answering out of local memory while
    wearing this class's name is the single most misleading thing this package could do.

    `grant` and `revoke` are refused outright, and that is correct rather than
    incomplete. Both are transactions signed by the account owner, and Docket does not
    hold the owner key. They belong in the runbook the owner runs, not here.
    """

    enforces_on_chain = True

    def __init__(
        self,
        *,
        account: str,
        session_manager: str | None = None,
        reader=None,
        chain_id: int = BSC_CHAIN_ID,
    ) -> None:
        if session_manager is None or reader is None:
            raise IntegrationGap(self.integration_gap())
        self.account = Web3.to_checksum_address(account)
        self.session_manager = Web3.to_checksum_address(session_manager)
        # reader(session_id, token) -> (revoked, expiry, remaining_cap, block_number).
        # Injected for the reason positions.py injects a Web3: whoever supplies it owns
        # its failover, and a test never touches a network.
        self._reader = reader
        self.chain_id = chain_id

    @staticmethod
    def integration_gap() -> str:
        """What is missing, in enough detail that the next person does not re-derive it."""
        return (
            "No on-chain session surface has been established for Altana on BSC mainnet "
            "(chain 56) from this codebase. To construct this authority, three things are "
            "needed and none of them is in the repository today: (1) the address of the "
            "session-manager or validator contract that holds session state on chain 56; "
            "(2) the ABI of its view functions for a session's revoked flag, expiry and "
            "remaining spend cap, so `status()` is an eth_call and not a recollection; "
            "(3) code at that address, checked with eth_getCode over the BSC failover "
            "list. Altana publishes a TypeScript SDK and no Python package exists on "
            "PyPI, so grantSession and revokeSession are driven either from the owner's "
            "own wallet or from a TypeScript sidecar; a sidecar would need to expose "
            "grant, revoke and a status read over a local HTTP or stdio boundary, and "
            "adding one is a new dependency this stage was not authorised to take. Note "
            "which half of the problem that is: initiating a grant is legitimately the "
            "owner's action and belongs in a runbook. The half that is missing is the "
            "read — until status() is an eth_call, every cap this package reports is "
            "Docket's own bookkeeping, and Docket's bookkeeping is not what stands "
            "between a bug and somebody's funds."
        )

    def status(
        self, ref: SessionRef, *, permissions: SessionPermissions | None = None
    ) -> SessionStatus:
        if permissions is None:
            raise ValueError(
                "reading a session's caps needs the tokens they were granted over: pass "
                "the permissions the owner granted"
            )
        revoked = False
        expiry = ref.expiry
        remaining: dict[str, int] = {}
        block: int | None = None
        for cap in permissions.spend:
            flag, session_expiry, left, at_block = self._reader(ref.session_id, cap.token)
            revoked = revoked or bool(flag)
            expiry = int(session_expiry)
            remaining[cap.token] = int(left)
            block = int(at_block)
        return SessionStatus(
            valid=not revoked and expiry > now(),
            revoked=revoked,
            expiry=expiry,
            remaining_cap=remaining,
            permissions=permissions,
            chain_id=self.chain_id,
            source="chain",
            read_at_block=block,
        )

    def can_execute(
        self,
        intent: ActionIntent,
        ref: SessionRef,
        *,
        permissions: SessionPermissions | None = None,
    ) -> tuple[bool, str]:
        """Refuses when the chain cannot be reached. An outage is not an authorisation.

        This is the one branch where falling back to a remembered status would be
        indistinguishable from working — and would mean the caps had quietly become
        Docket's own again.
        """
        try:
            status = self.status(ref, permissions=permissions)
        except Exception as exc:
            return False, (
                f"the session's state could not be read from chain {self.chain_id}: "
                f"{type(exc).__name__}: {exc}"
            )
        return check(intent, status)

    def grant(self, permissions: SessionPermissions, expiry: int) -> SessionRef:
        raise IntegrationGap(
            "granting a session is a transaction signed by the account owner, and Docket "
            "does not hold the owner key. The grant is the owner's step in the runbook."
        )

    def revoke(self, ref: SessionRef) -> None:
        raise IntegrationGap(
            "revokeSession is gated onlyKeyOwnerOrValidator, so it is the owner's call "
            "and not Docket's. Docket holds a session it can stop using; the owner holds "
            "the one that can stop it."
        )
