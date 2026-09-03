"""Proving that the owner asked for this, without holding anything of the owner's.

Every mutating activation call carries an EIP-191 `personal_sign` over the exact string
the server issued. The server recovers the signer and compares it to the owner the
activation names. Docket never sees a key and never stores one; what it stores is the
address that signed, which is a public fact about a signature anybody can recheck.

Two message shapes, both fixed here so the browser and the server cannot drift into
signing and verifying different sentences:

    Docket activation create {service_id} {nonce}
    Docket activation {activation_id} {action} {nonce}

The nonce is single-use. Its purpose is not secrecy — the activation serves its own
current nonce to anyone who asks — but replay: a signature over a message that has
already been spent proves the owner said something once, not that they are saying it
again.
"""

import hmac
import secrets

from eth_account import Account
from eth_account.messages import encode_defunct
from web3 import Web3

ACTIONS = ("create", "approve", "pause", "cancel", "revoke")


def new_nonce() -> str:
    """32 hex characters from the system CSPRNG."""
    return secrets.token_hex(16)


def create_message(service_id: str, nonce: str) -> str:
    return f"Docket activation create {service_id} {nonce}"


def action_message(activation_id: str, action: str, nonce: str) -> str:
    if action not in ACTIONS:
        raise ValueError(f"unknown activation action {action!r}; expected {ACTIONS}")
    return f"Docket activation {activation_id} {action} {nonce}"


def recover_signer(message: str, signature: str) -> str | None:
    """The checksummed address behind this signature, or None if there is not one.

    Everything the caller supplied is untrusted: a signature of the wrong length, bytes
    that are not hex, a recovery that lands on no key at all. Each is `None` rather than
    an exception a route has to translate, and `None` means exactly one thing — nothing
    was proven — which is a different answer from "somebody else signed this".
    """
    try:
        return Account.recover_message(
            encode_defunct(text=message), signature=signature
        )
    except Exception:
        return None


def same_address(left: str, right: str) -> bool:
    """Checksummed comparison through `compare_digest`, so neither case nor timing
    distinguishes a near miss from a wrong answer."""
    try:
        one = Web3.to_checksum_address(left)
        two = Web3.to_checksum_address(right)
    except Exception:
        return False
    return hmac.compare_digest(one.encode("ascii"), two.encode("ascii"))


def verify_owner_signature(owner: str, message: str, signature: str) -> bool:
    """Whether `signature` over `message` recovers to `owner`."""
    recovered = recover_signer(message, signature)
    return recovered is not None and same_address(owner, recovered)
