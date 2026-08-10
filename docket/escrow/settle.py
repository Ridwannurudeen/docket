"""Closing a ripe job.

`settle()` on the router turns out not to care who calls it — a stranger address, party
to nothing, settles a ripe job in `eth_call` (E1c, against live job 56585). That single
fact is what makes a 7-day dispute window survivable as a product: Docket can close a
buyer's job the moment it ripens instead of asking them to come back a week later.

Which also makes this the one module in the escrow rail that can spend money, so it
ships disarmed. Without `DOCKET_SETTLE_KEY` in the environment the broadcast path is not
merely refused, it is never reached — no node is contacted, no transaction is built.
Arming it needs a funded Docket EOA on BSC mainnet, which is a user action.

The dry run is free and always available: `can_settle` is an `eth_call`, so anyone can
ask whether a job is closable without holding anything at all.
"""

import os

from web3 import Web3

from . import constants as c
from .chain import Rpc

ROUTER_ABI = [
    {
        "name": "settle",
        "type": "function",
        "stateMutability": "nonpayable",
        "inputs": [
            {"name": "jobId", "type": "uint256"},
            {"name": "evidence", "type": "bytes"},
        ],
        "outputs": [],
    }
]

# Reverts a settle attempt can realistically come back with, in words a buyer can act
# on. Anything unlisted falls through to the contract's own error name, which is still
# better than a bare selector.
REVERT_MEANINGS = {
    "NotDecided": (
        "the dispute window has not elapsed yet, so the policy has not reached a "
        "verdict; this job is not closable until its settle_at timestamp"
    ),
    "PolicyNotSet": (
        "this job was never registered with the router, so no policy governs it and "
        "there is nothing to settle"
    ),
    "EnforcedPause": "the router is paused",
    "JobNotOpen": "the job is not in a state that can be settled",
}

# A minimal ABI carries no error entries, so web3 surfaces a custom error as a bare
# selector: an OPEN job's settle attempt comes back as ContractCustomError('0x17be5b7b')
# rather than "NotDecided". Naming them from signatures is cheaper than inlining 27 ABI
# error objects, and `test_abis.py` checks every signature below against the artifact.
ROUTER_ERROR_SIGNATURES = (
    "NotDecided()",
    "PolicyNotSet()",
    "PolicyNotWhitelisted()",
    "PolicyAlreadySet()",
    "JobNotOpen()",
    "EnforcedPause()",
    "NotCommerce()",
    "NotJobClient()",
    "NotExpired()",
    "RouterNotEvaluator()",
    "RouterNotHook()",
    "UnknownVerdict(uint8)",
    "ZeroAddress()",
)
_w3_encoder = Web3()
ERROR_BY_SELECTOR = {
    "0x" + Web3.keccak(text=sig)[:4].hex(): sig.split("(")[0]
    for sig in ROUTER_ERROR_SIGNATURES
}


class NotArmed(RuntimeError):
    """Settling would broadcast a transaction, and no signing key is configured."""


def settle_calldata(job_id: int) -> dict:
    """The exact call, for a caller who would rather send it themselves."""
    contract = _w3_encoder.eth.contract(abi=ROUTER_ABI)
    return {
        "to": c.ROUTER,
        "function": "settle",
        "args": {"jobId": int(job_id), "evidence": b""},
        "calldata": contract.encode_abi("settle", args=[int(job_id), b""]),
        "note": (
            "Permissionless: any address may call this once the dispute window has "
            "elapsed and the job is undisputed. It moves the escrowed budget to the "
            "provider; the caller pays only gas."
        ),
    }


def _error_name(exc: Exception) -> str | None:
    """The contract's own name for this revert, from the error name if web3 could
    decode it, otherwise from the raw selector it fell back to."""
    text = str(exc)
    for selector, name in ERROR_BY_SELECTOR.items():
        if selector in text or name in text:
            return name
    return None


def _explain(exc: Exception) -> str:
    name = _error_name(exc)
    if name is None:
        return "the call reverted"
    return REVERT_MEANINGS.get(name, f"the call reverted with {name}")


def can_settle(job_id: int, w3=None) -> dict:
    """A free `eth_call` dry run. Never broadcasts, never needs a key."""

    def dry_run(session):
        router = session.eth.contract(address=c.ROUTER, abi=ROUTER_ABI)
        router.functions.settle(int(job_id), b"").call()
        return {"ready": True, "reason": None}

    try:
        if w3 is not None:
            return dry_run(w3)
        return Rpc()(dry_run)
    except Exception as exc:  # ContractLogicError and outages both land here
        return {"ready": False, "reason": _explain(exc)}


def settle(job_id: int, w3=None) -> dict:
    """Broadcast the settle transaction. Refuses unless explicitly armed.

    The key check comes first, before any node is contacted, so an unarmed call cannot
    reach the network even to ask a question.
    """
    key = os.environ.get("DOCKET_SETTLE_KEY")
    if not key:
        raise NotArmed(
            "settling broadcasts a transaction and DOCKET_SETTLE_KEY is not set. "
            "Docket ships this disarmed on purpose; arming it needs a funded BSC "
            "mainnet EOA (gas only). can_settle() answers the same question for free."
        )

    from eth_account import Account

    account = Account.from_key(key)
    session = w3 if w3 is not None else Rpc()(lambda s: s)
    router = session.eth.contract(address=c.ROUTER, abi=ROUTER_ABI)
    tx = router.functions.settle(int(job_id), b"").build_transaction(
        {
            "from": account.address,
            "nonce": session.eth.get_transaction_count(account.address),
            "chainId": c.CHAIN_ID,
        }
    )
    signed = account.sign_transaction(tx)
    tx_hash = session.eth.send_raw_transaction(signed.raw_transaction)
    return {"job_id": int(job_id), "tx_hash": tx_hash.hex(), "sent_by": account.address}
