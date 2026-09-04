"""Session keys: created on the server, stored encrypted, and never a default.

A persistent activation acts through its own throwaway EOA. The key is generated here,
encrypted immediately into a Web3 Secret Storage keystore, and only the keystore is
persisted — the plaintext key exists inside one function call and is never returned, never
logged and never written down.

The master password comes from a file the operator puts on the box and names in
`DOCKET_SESSION_KEY_FILE`. There is no fallback and no default. A missing file raises
`SessionsUnavailable` and persistent activations are refused for as long as it is
missing, because the alternative — a built-in password — would mean every copy of this
source could decrypt every session on every deployment of it.

`Session` is the unlocked working object: the address, the account that can sign for it,
and what it was funded with against what it has spent. It exists only inside a tick or a
revoke, and it is never serialised.
"""

import json
import os
import threading
from dataclasses import dataclass, field
from pathlib import Path

from eth_account import Account

# scrypt at n=2**14 rather than eth_account's 2**18 default. The default is sized for a
# password a person chose and costs about 256 MiB and half a second per call, which is a
# denial-of-service surface on a box carrying eighteen other projects. What this encrypts
# is 48 bytes from /dev/urandom — the work factor is protecting a key nobody can guess in
# the first place, and the memory is the part that actually hurts here.
KDF = "scrypt"
KDF_ITERATIONS = 2**14
# Two at a time. Even at 2**14 an unbounded burst of keystore work would hold the whole
# box; the tick is a batch job and can wait its turn.
_kdf_seats = threading.Semaphore(2)


class SessionsUnavailable(RuntimeError):
    """No master password is configured, so no session key can be made or opened."""


@dataclass
class Session:
    """One unlocked session key and the bounds it acts inside.

    `spent_atomic` is updated by `docket.sessions.executor.execute` as each transaction
    lands, and the caller persists it back onto the activation. `token_allowlist` travels
    with the session because a sweep has to know which tokens to look for and the policy
    is not passed to it.
    """

    address: str
    account: object
    funded_atomic: dict[str, int] = field(default_factory=dict)
    spent_atomic: dict[str, int] = field(default_factory=dict)
    token_allowlist: tuple[str, ...] = ()
    # Tokens the session can end up holding without ever being allowed to spend them — a
    # swap's output side. The allowlist bounds what may leave; this is what has to be
    # swept back, and the two are different sets.
    received_tokens: tuple[str, ...] = ()
    # Live approvals, `{token: {spender: amount}}`. An approval that has been granted and
    # not yet pulled is money that can still leave without another transaction of ours, so
    # it is held against the lifetime cap exactly as spend is — and released when the pull
    # lands, so the pair is never charged twice.
    reserved_atomic: dict = field(default_factory=dict)

    def committed_atomic(self) -> dict[str, int]:
        """Everything this session has spent OR authorised, per token.

        The figure the cap has to be read against. Spend alone understates it: a batch
        that approves and then stops leaves an allowance standing, and a pass that counted
        only what had moved would approve the same amount again next minute.
        """
        committed = {token: int(amount) for token, amount in self.spent_atomic.items()}
        for token, spenders in self.reserved_atomic.items():
            outstanding = sum(int(amount) for amount in spenders.values())
            if outstanding:
                committed[token] = committed.get(token, 0) + outstanding
        return committed

    def reserve(self, token: str, spender: str, amount: int) -> None:
        """Record the exact allowance for one token/spender pair."""
        held = dict(self.reserved_atomic.get(token) or {})
        if int(amount) > 0:
            held[spender] = int(amount)
        else:
            held.pop(spender, None)
        reserved = {**self.reserved_atomic}
        if held:
            reserved[token] = held
        else:
            reserved.pop(token, None)
        self.reserved_atomic = reserved

    def release(self, token: str, spender: str) -> None:
        """Drop the reservation a successful pull has consumed."""
        held = dict(self.reserved_atomic.get(token) or {})
        if held.pop(spender, None) is None:
            return
        reserved = {**self.reserved_atomic}
        if held:
            reserved[token] = held
        else:
            reserved.pop(token, None)
        self.reserved_atomic = reserved


def master_password_from_env(environment=None) -> str:
    """Read the master password out of the file the environment names.

    Every failure is `SessionsUnavailable` rather than a value: an unset variable, a file
    that is not there, and a file that is there and empty are three ways of saying the
    same thing, and none of them may be answered with a password this module invented.
    """
    environment = os.environ if environment is None else environment
    path = (environment.get("DOCKET_SESSION_KEY_FILE") or "").strip()
    if not path:
        raise SessionsUnavailable(
            "DOCKET_SESSION_KEY_FILE is not set, so Docket holds no master password and "
            "will not create or open a session key. Sessions stay refused until the "
            "operator supplies the file; there is no default password."
        )
    try:
        password = Path(path).read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise SessionsUnavailable(
            f"the session master password file named by DOCKET_SESSION_KEY_FILE could "
            f"not be read ({type(exc).__name__})"
        ) from exc
    if not password:
        raise SessionsUnavailable(
            "the session master password file is empty; an empty password is refused "
            "rather than treated as one"
        )
    return password


def create_session_key(master_password: str) -> tuple[str, str]:
    """A fresh EOA, returned as its address and its encrypted keystore.

    The private key is never returned. A caller that wants to sign asks `unlock` for an
    account, which puts the plaintext key inside that call and nowhere else.
    """
    if not master_password:
        raise SessionsUnavailable("a session key cannot be encrypted with no password")
    account = Account.create()
    with _kdf_seats:
        keystore = Account.encrypt(
            account.key, master_password, kdf=KDF, iterations=KDF_ITERATIONS
        )
    return account.address, json.dumps(keystore, sort_keys=True, ensure_ascii=False)


def unlock(keystore_json: str, master_password: str):
    """The signing account behind one stored keystore.

    A wrong password raises `ValueError` from `eth_account` and is left to propagate: an
    unlock that quietly returns nothing would be indistinguishable from a session that
    had no key, and the two want opposite responses.
    """
    if not master_password:
        raise SessionsUnavailable("a session key cannot be opened with no password")
    with _kdf_seats:
        key = Account.decrypt(json.loads(keystore_json), master_password)
    return Account.from_key(key)
