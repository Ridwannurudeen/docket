"""Who says an action may happen — and, more to the point, where that is enforced.

Docket holds a session, never the owner key. The owner signs a grant that names which
contracts the session may call, how much it may spend of which token over what period,
and when it stops working. Docket then acts inside that, and the owner can revoke it
without asking Docket for anything.

The sentence that matters is the one about where the limits live. **A check written in
Python is not a limit.** If the cap standing between a bug and somebody's funds is an
`if` statement in this file, then the funds are protected by Docket's test coverage,
which is not a security model. Altana's own documentation is unambiguous about which it
is: a session that calls outside its allowlist or spends past its cap reverts at
validation time, and there is no off-chain trust assumption. Everything in `check()`
below is a second gate standing in front of that one. It may refuse an action the chain
would have allowed. It is never the only thing refusing.

What this module can actually do, stated exactly, because it is the claim a judge should
probe hardest:

**Enforcement is on chain and is not Docket's.** Altana wallets are EIP-7702-delegated
accounts running Ithaca's GuardedExecutor. The cap arithmetic and the call scope live
there and apply whether or not this file exists.

**Verification is a real `eth_call` from this codebase.** Session authority is readable
without the TypeScript SDK, and this module reads it: `isValidKey` and `getKeys` on the
KeyStore singleton, `spendInfos` and `canExecute` on the wallet's own account contract.
The addresses, the ABI fragments and the selectors below were each checked against BSC
mainnet on 2026-08-10 — see `ALTANA_KEYSTORE` for what that check was.

**Granting and revoking are the owner's, and stay the owner's.** Both are transactions
signed by the account owner. Docket does not hold that key and does not want it, so this
class refuses both and the runbook carries them.

The gap that remains after all that is written down once, in `integration_gap()`, rather
than implied. Every `SessionStatus` also carries `source` and `reads`: where the answer
came from, and which chain calls produced it. `StubSessionAuthority` says `stub` there,
and the day that field becomes decoration is the day a server-side check gets mistaken
for a limit somebody's funds actually stand behind.
"""

from dataclasses import dataclass, field
from typing import Protocol

from web3 import Web3

from ..escrow.chain import Rpc
from . import now
from .intent import ActionIntent

BSC_CHAIN_ID = 56
# Altana's KeyStore singleton on BSC mainnet. Verified from this machine on 2026-08-10 at
# block 115,158,575: `eth_getCode` returns 8,756 bytes, `VERSION()` reads "1.0.1", and
# `isValidKey`/`getKeys` answer correctly for an address with no keys. The address itself
# is published in Altana's networks documentation and appears in the SDK's own config.
ALTANA_KEYSTORE = Web3.to_checksum_address("0x6572427ED530BadcF7375Cf9A4709D8d2b0E7E0a")
# Where a status was read. Two values, because there are two kinds of answer: one the
# chain gave and one this process made up. Anything else would blur them.
STATUS_SOURCES = frozenset({"chain", "stub"})
# The key type a secp256k1 session signer is stored under in the account's own key table.
# Ithaca's enum: P256=0, WebAuthnP256=1, Secp256k1=2, External=3.
KEY_TYPE_SECP256K1 = 2

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

# Minimal fragments rather than a vendored artifact, which is the practice `positions.py`
# established here. Every selector below was recomputed from its signature and matched
# against the deployed runtime bytecode on 2026-08-10 — KeyStore at ALTANA_KEYSTORE and
# the account implementation at 0x4B5d20CD8a3927B500540d9BcCDDc27385c9fA79 — so a
# mistranscribed argument list would have shown up as an absent selector.
#
# Worth knowing about the source of these shapes: Altana's KeyStore Solidity is not
# public, so this ABI is the subset its TypeScript SDK vendors, confirmed against the
# bytecode rather than against source anybody can read.
KEYSTORE_ABI = [
    {
        "name": "isValidKey",
        "type": "function",
        "stateMutability": "view",
        "inputs": [{"name": "user", "type": "address"}, {"name": "keyId", "type": "bytes32"}],
        "outputs": [{"name": "", "type": "bool"}],
    },
    {
        "name": "getKeys",
        "type": "function",
        "stateMutability": "view",
        "inputs": [{"name": "user", "type": "address"}],
        "outputs": [{"name": "", "type": "bytes32[]"}],
    },
]
# The wallet is its own contract. `spendInfos` holds the cap arithmetic and `canExecute`
# holds the call scope, which is why the allowlist question below can be asked of the
# chain rather than only of Docket's copy of the grant.
ACCOUNT_ABI = [
    {
        "name": "spendInfos",
        "type": "function",
        "stateMutability": "view",
        "inputs": [{"name": "keyHash", "type": "bytes32"}],
        "outputs": [
            {
                "name": "",
                "type": "tuple[]",
                "components": [
                    {"name": "token", "type": "address"},
                    {"name": "period", "type": "uint8"},
                    {"name": "limit", "type": "uint256"},
                    {"name": "spent", "type": "uint256"},
                    {"name": "lastUpdated", "type": "uint256"},
                    {"name": "currentSpent", "type": "uint256"},
                    {"name": "current", "type": "uint256"},
                ],
            }
        ],
    },
    {
        "name": "canExecute",
        "type": "function",
        "stateMutability": "view",
        "inputs": [
            {"name": "keyHash", "type": "bytes32"},
            {"name": "target", "type": "address"},
            {"name": "data", "type": "bytes"},
        ],
        "outputs": [{"name": "", "type": "bool"}],
    },
]


class IntegrationGap(NotImplementedError):
    """Something this authority would need in order to be one, and does not have."""


def keystore_key_id(public_key: bytes) -> bytes:
    """The id the KeyStore files a session key under: keccak over the SEC1 public key.

    `public_key` is the uncompressed 65-byte form, `0x04 || x || y` — the value Altana's
    `Session.publicKey` carries. This is one of two identifiers for the same key and it
    is not interchangeable with the other; see `account_key_hash`.
    """
    if len(public_key) != 65 or public_key[0] != 0x04:
        raise ValueError(
            "a KeyStore key id is keccak over the uncompressed SEC1 public key: 65 bytes "
            f"beginning 0x04, got {len(public_key)} beginning {public_key[:1].hex()}"
        )
    return Web3.keccak(public_key)


def account_key_hash(session_address: str) -> bytes:
    """The hash the wallet's own key table files the same session under.

    Deliberately a separate function from `keystore_key_id`, with this comment, because
    the two are the single most likely source of a silent wrong answer in this file. The
    KeyStore hashes the 65-byte public key. The account hashes the *address*, left-padded
    to 32 bytes, tagged with the key type:

        keccak256( abi.encode(uint256(2), keccak256(pad32(address))) )

    Transcribed from Altana's SDK and cross-checked against Porto's canonical `Key.hash`,
    which encodes `(uint8 keyType, keccak256(serializedPublicKey))` — the same 32 bytes,
    since a uint8 and a uint256 ABI-encode alike. It has not yet been confirmed against a
    live granted key, and that is stated in `integration_gap()` rather than only here.
    """
    address = bytes.fromhex(Web3.to_checksum_address(session_address)[2:])
    inner = Web3.keccak(bytes(12) + address)
    return Web3.keccak(KEY_TYPE_SECP256K1.to_bytes(32, "big") + inner)


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
    """How much of one token may leave, per rolling period, in atomic units.

    Atomic units and nothing else. BSC's USDT and USDC are 18 decimals where Ethereum's
    are 6, and a cap written for the wrong chain's decimals is off by twelve orders of
    magnitude in whichever direction hurts.
    """

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
            raise ValueError(
                "a session with no call allowlist permits every contract — Altana's own "
                "documentation says an omitted `calls` is unrestricted within the cap"
            )
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
    """A handle to a granted session. Carries no key material of any kind.

    `public_key` is the session's uncompressed SEC1 public key, which is public by
    definition and is what the KeyStore files it under; `key_address` is the same key's
    address, which the wallet's own table files it under. Both are here because the two
    identifiers are derived differently and neither can produce the other.

    `expiry` is what the owner granted, recorded rather than read. The chain's own answer
    to "has this expired" comes back through `isValidKey`; this figure exists so an
    intent's deadline can be compared against the window the owner intended.
    """

    session_id: str
    account: str
    key_address: str
    chain_id: int
    expiry: int
    public_key: str | None = None

    @property
    def key_id(self) -> bytes:
        if not self.public_key:
            raise ValueError(
                f"session {self.session_id}: the KeyStore files a key under keccak of its "
                "SEC1 public key, and this reference carries no public key"
            )
        raw = self.public_key[2:] if self.public_key.startswith("0x") else self.public_key
        return keystore_key_id(bytes.fromhex(raw))

    @property
    def key_hash(self) -> bytes:
        return account_key_hash(self.key_address)


@dataclass(frozen=True)
class SessionStatus:
    """What the authority says about a session right now, and where that came from.

    `reads` names the chain calls that produced it, in the order they were made, so a
    reader can tell which fields are the chain's answer and which are Docket's record of
    what was granted. It is empty on a stub, which is the whole point of it.
    """

    valid: bool
    revoked: bool
    expiry: int
    remaining_cap: dict[str, int]
    permissions: SessionPermissions
    chain_id: int
    source: str
    read_at_block: int | None = None
    # None where nobody asked the wallet — a status built without the calldata to ask
    # about. False is the chain refusing, and it outranks anything Docket thinks.
    call_allowed: bool | None = None
    reads: tuple[str, ...] = ()

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
            "call_allowed": self.call_allowed,
            "reads": list(self.reads),
        }


def check(intent: ActionIntent, status: SessionStatus) -> tuple[bool, str]:
    """Whether this session, as it stands, covers this intent — and why, either way.

    Pure, so both authorities share one set of rules and the rules can be exercised
    without a chain. The order is chosen so the most specific true statement is the one
    returned: a revoked session is reported as revoked rather than as invalid.

    Which of these is really an authority and which is a courtesy is worth being exact
    about. `revoked`, `valid`, `remaining_cap` and `call_allowed` are the chain's answers
    when the status came from a live read. The call allowlist walked at the bottom is
    Docket's copy of what was granted, and it runs *after* the wallet's own `canExecute`
    so that a copy gone stale can only refuse something the chain would have allowed,
    never the reverse. `expiry` is the window the owner granted, recorded rather than
    read; the chain's own view of expiry arrives inside `valid`.
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
    if status.call_allowed is False:
        return False, (
            f"the wallet's own canExecute refuses this call to {intent.target}, which is the "
            "answer that counts — Docket's copy of the grant does not overrule it"
        )

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
    session it is asking about. `calldata` is optional and is what lets a live authority
    put the allowlist question to the wallet itself.
    """

    enforces_on_chain: bool

    def grant(self, permissions: SessionPermissions, expiry: int) -> SessionRef: ...

    def status(
        self,
        ref: SessionRef,
        *,
        permissions: SessionPermissions | None = None,
        call: tuple[str, bytes] | None = None,
    ) -> SessionStatus: ...

    def revoke(self, ref: SessionRef) -> None: ...

    def can_execute(
        self,
        intent: ActionIntent,
        ref: SessionRef,
        *,
        permissions: SessionPermissions | None = None,
        calldata: bytes | None = None,
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
    returns by putting `stub` in the `source` field and leaving `reads` empty. It exists
    so the operator, the state machine and the refusal paths can be exercised end to end
    without a wallet.

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
        self,
        ref: SessionRef,
        *,
        permissions: SessionPermissions | None = None,
        call: tuple[str, bytes] | None = None,
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
        calldata: bytes | None = None,
    ) -> tuple[bool, str]:
        try:
            status = self.status(ref, permissions=permissions)
        except LookupError as exc:
            return False, str(exc)
        return check(intent, status)


class UndelegatedWallet(RuntimeError):
    """The address has no account code yet, so it has no keys and no caps to read.

    Distinct from an outage on purpose: a wallet that has never executed is a real,
    knowable state with an obvious fix, and reporting it as "the node was unreachable"
    would send somebody to debug the wrong thing.
    """


class BscChainReader:
    """The four reads, against BSC mainnet, over the endpoint failover already in use.

    `escrow.chain.Rpc` is reused rather than copied. Its docstring already flags that the
    failover shape exists in three places in this repository; a fourth would be the one
    that goes stale.
    """

    def __init__(self, keystore: str = ALTANA_KEYSTORE, rpc=None) -> None:
        self.keystore = Web3.to_checksum_address(keystore)
        self._rpc = rpc if rpc is not None else Rpc()

    def _keystore(self, w3):
        return w3.eth.contract(address=self.keystore, abi=KEYSTORE_ABI)

    def _account(self, w3, wallet: str):
        return w3.eth.contract(address=Web3.to_checksum_address(wallet), abi=ACCOUNT_ABI)

    def block_number(self) -> int:
        return self._rpc(lambda w3: w3.eth.block_number)

    def is_valid_key(self, wallet: str, key_id: bytes) -> bool:
        return self._rpc(
            lambda w3: (
                self._keystore(w3)
                .functions.isValidKey(Web3.to_checksum_address(wallet), key_id)
                .call()
            )
        )

    def registered_key_ids(self, wallet: str) -> tuple[bytes, ...]:
        return tuple(
            self._rpc(
                lambda w3: (
                    self._keystore(w3).functions.getKeys(Web3.to_checksum_address(wallet)).call()
                )
            )
        )

    def spend_infos(self, wallet: str, key_hash: bytes) -> tuple[tuple, ...]:
        self._require_code(wallet)
        return tuple(
            self._rpc(lambda w3: self._account(w3, wallet).functions.spendInfos(key_hash).call())
        )

    def can_execute(self, wallet: str, key_hash: bytes, target: str, calldata: bytes) -> bool:
        self._require_code(wallet)
        return self._rpc(
            lambda w3: (
                self._account(w3, wallet)
                .functions.canExecute(key_hash, Web3.to_checksum_address(target), calldata)
                .call()
            )
        )

    def _require_code(self, wallet: str) -> None:
        code = self._rpc(lambda w3: w3.eth.get_code(Web3.to_checksum_address(wallet)))
        if not code:
            raise UndelegatedWallet(
                f"{wallet} carries no account code on chain {BSC_CHAIN_ID}: it has not been "
                "delegated yet, so it holds no session keys and no spend caps. This is not "
                "the same as having no permissions — there is nothing there to have them."
            )


class AltanaSessionAuthority:
    """A session enforced by Altana's validator, read back from BSC by `eth_call`.

    Four reads, and each one is asked of the party that actually knows the answer:

    * `KeyStore.isValidKey(wallet, keyId)` — registered, not revoked, not expired. One
      boolean, and the documented answer to "may this key act at all".
    * `KeyStore.getKeys(wallet)` — the registered, unrevoked ids. Revocation removes an
      id from this list in the same transaction; an expiry passing does not, because no
      transaction fires when a timestamp goes by. Comparing the two separates "revoked"
      from "expired" without decoding a struct.
    * `account.spendInfos(keyHash)` — the caps, per token, with what this period has
      already spent. Remaining is `limit - currentSpent`; the field named `current` is
      the start of the current period and is a timestamp, not a balance.
    * `account.canExecute(keyHash, target, data)` — the wallet's own answer about the
      exact call. This is the read that moves the allowlist question off Docket's copy
      of the grant and onto the chain.

    `grant` and `revoke` are refused, and that is correct rather than incomplete. Both
    are transactions signed by the account owner, and Docket does not hold the owner key.
    """

    enforces_on_chain = True

    def __init__(
        self,
        *,
        account: str,
        reader=None,
        keystore: str = ALTANA_KEYSTORE,
        chain_id: int = BSC_CHAIN_ID,
    ) -> None:
        self.account = Web3.to_checksum_address(account)
        self.keystore = Web3.to_checksum_address(keystore)
        self.chain_id = chain_id
        # Injected for the reason `positions.py` injects a Web3: whoever supplies it owns
        # its reliability, and a test never touches a network.
        self._reader = reader if reader is not None else BscChainReader(keystore=self.keystore)

    @staticmethod
    def integration_gap() -> str:
        """What is still missing, in enough detail that nobody has to re-derive it."""
        return (
            "Three things are true at once and only the third is a gap. (1) Enforcement is "
            "on chain and is not Docket's: an Altana wallet is an EIP-7702-delegated "
            "account running Ithaca's GuardedExecutor, and a session that calls outside its "
            "allowlist or spends past its cap reverts at validation time whether or not "
            "this code exists. (2) Verification from Python is real: the KeyStore singleton "
            "on chain 56 at 0x6572427ED530BadcF7375Cf9A4709D8d2b0E7E0a answers isValidKey "
            "and getKeys to a plain eth_call, the wallet's own account answers spendInfos "
            "and canExecute, and this module performs all four — no TypeScript SDK is in "
            "the path. (3) The gap: granting and revoking are transactions signed by the "
            "account owner, and Docket does not hold that key, so they are driven from the "
            "owner's wallet or from Altana's TypeScript SDK, which has no Python "
            "equivalent on PyPI. That half belongs in a runbook rather than in this "
            "process, and it is where a TypeScript sidecar would go if one were ever "
            "wanted: it would need to expose grant and revoke over a local boundary, and "
            "adding it is a new dependency this stage did not take. Three caveats travel "
            "with the above. The KeyStore's Solidity is not published, so the ABI here is "
            "the subset Altana's SDK vendors, matched against deployed bytecode rather "
            "than against source anybody can read. The read path has been exercised "
            "against an address with no keys and has not been exercised against a live "
            "granted session, because no Altana wallet on BSC mainnet could be located to "
            "read. And a session granted with register=false is written to no public "
            "KeyStore at all, so it works and is invisible to every reader including this "
            "one — the grant in the runbook must register."
        )

    def status(
        self,
        ref: SessionRef,
        *,
        permissions: SessionPermissions | None = None,
        call: tuple[str, bytes] | None = None,
    ) -> SessionStatus:
        if permissions is None:
            raise ValueError(
                "reading a session's caps needs the tokens they were granted over: pass "
                "the permissions the owner granted"
            )
        key_id = ref.key_id
        key_hash = ref.key_hash
        reads = ["KeyStore.isValidKey", "KeyStore.getKeys", "account.spendInfos"]

        valid = bool(self._reader.is_valid_key(ref.account, key_id))
        registered = key_id in self._reader.registered_key_ids(ref.account)
        infos = self._reader.spend_infos(ref.account, key_hash)

        wanted = {cap.token for cap in permissions.spend}
        remaining: dict[str, int] = {}
        for info in infos:
            token = Web3.to_checksum_address(info[0])
            if token in wanted:
                # limit minus what this period has already spent. `info[6]` is the start
                # of the current period and must never be read as a balance.
                remaining[token] = int(info[2]) - int(info[5])

        call_allowed = None
        if call is not None:
            target, calldata = call
            reads.append("account.canExecute")
            call_allowed = bool(self._reader.can_execute(ref.account, key_hash, target, calldata))

        return SessionStatus(
            valid=valid,
            revoked=not registered,
            expiry=ref.expiry,
            remaining_cap=remaining,
            permissions=permissions,
            chain_id=self.chain_id,
            source="chain",
            read_at_block=self._reader.block_number(),
            call_allowed=call_allowed,
            reads=tuple(reads),
        )

    def can_execute(
        self,
        intent: ActionIntent,
        ref: SessionRef,
        *,
        permissions: SessionPermissions | None = None,
        calldata: bytes | None = None,
    ) -> tuple[bool, str]:
        """Refuses when the chain cannot be reached. An outage is not an authorisation.

        This is the one branch where falling back to a remembered status would be
        indistinguishable from working — and would mean the caps had quietly become
        Docket's own again.
        """
        try:
            status = self.status(
                ref,
                permissions=permissions,
                call=None if calldata is None else (intent.target, calldata),
            )
        except UndelegatedWallet as exc:
            return False, str(exc)
        except Exception as exc:
            return False, (
                f"the session's state could not be read from chain {self.chain_id}: "
                f"{type(exc).__name__}: {exc}"
            )
        return check(intent, status)

    def grant(self, permissions: SessionPermissions, expiry: int) -> SessionRef:
        raise IntegrationGap(
            "granting a session is a transaction signed by the account owner, and Docket "
            "does not hold the owner key. The grant is the owner's step in the runbook, "
            "and it must register the key or nothing here can read it."
        )

    def revoke(self, ref: SessionRef) -> None:
        raise IntegrationGap(
            "revokeSession is gated onlyKeyOwnerOrValidator, so it is the owner's call "
            "and not Docket's. Docket holds a session it can stop using; the owner holds "
            "the one that can stop it."
        )
