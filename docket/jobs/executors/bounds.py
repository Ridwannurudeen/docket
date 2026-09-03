"""The bounds a session is held to, and the two readings every executor needs.

Three things live here because more than one module needs each of them and a second copy
is the one that goes stale.

`parse_expiry` is how every policy in this package reads an instant. A naive timestamp is
refused rather than assumed to be UTC: the difference between the two readings is however
many hours the writer's clock is offset by, and it decides whether a policy is live.

`APPROVE_ABI` is the one ERC-20 write both agents build. `approve(address,uint256)` is
also ERC-721's, with a token id where the amount is, so the two share the selector
`0x095ea7b3` and every check below reads the contract and the selector together. A policy
that allowlists a selector alone has allowlisted both.

`within_session_policy` is the walk both executors do over a decision's prepared calls. It
is a second, narrower gate in front of the session authority's own on-chain checks, in the
sense `docket/execution/__init__.py` sets out: it may refuse what the chain would have
allowed, and it is never the only thing standing between a bug and somebody's money.

`simulate_call` and `defer` are the preflight both executors run. They live here rather
than in either of them, so a Venus decision does not depend on the PancakeSwap module
importing cleanly and so the three verdicts stay one definition.

`base.py` holds nothing but the three records the plan specifies, so everything Docket
adds around them — this file's contents included — sits beside it rather than inside it.
"""

from datetime import datetime, timezone

from web3 import Web3

from .base import PreparedCall

# The one call flag that means "not the session's to send". A call carrying it is the
# account owner's own transaction, signed in their wallet, so the session's allowlists and
# caps have no opinion about it — they bound what Docket may do, not what the owner may.
OWNER_SIGNS = "owner_signs"
BSC_CHAIN_ID = 56
APPROVE_SIGNATURE = "approve(address,uint256)"
APPROVE_SELECTOR = "0x" + Web3.keccak(text=APPROVE_SIGNATURE)[:4].hex()
APPROVE_ABI = [
    {
        "name": "approve",
        "type": "function",
        "stateMutability": "nonpayable",
        "inputs": [
            {"name": "spender", "type": "address"},
            {"name": "value", "type": "uint256"},
        ],
        "outputs": [{"name": "", "type": "bool"}],
    }
]


def parse_expiry(value: str) -> datetime:
    """An ISO-8601 instant, timezone-aware, or a stated refusal."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError("an expiry must be a non-empty ISO-8601 instant")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"not an ISO-8601 instant: {value!r}") from exc
    if parsed.tzinfo is None:
        raise ValueError(
            f"the instant {value!r} carries no timezone, and reading it as UTC would be a "
            "guess about whose clock it was written on"
        )
    return parsed


def policy_field(policy, name: str, default=None):
    """One field of a session policy, whether it arrived as stored JSON or as an object.

    Activations round-trip through a JSON column, so a policy read back from the store is
    a mapping while one held in memory may be the dataclass. Both are read here rather
    than in each executor, so the two never disagree about which shape they accept.
    """
    if policy is None:
        return default
    if hasattr(policy, "get") and hasattr(policy, "keys"):
        return policy.get(name, default)
    return getattr(policy, name, default)


def approve_amount(data: str) -> int:
    """The `value` argument of an `approve(address,uint256)` call, read from its calldata.

    Read from the bytes rather than carried alongside them: the bytes are what gets sent,
    and a cap checked against a number travelling next to the calldata is a cap on a
    number nobody signs.
    """
    body = data[2:] if data.startswith("0x") else data
    if len(body) != 8 + 64 + 64:
        raise ValueError(
            f"calldata of {len(body) // 2} bytes is not an approve(address,uint256) call"
        )
    return int(body[72:136], 16)


def _same(left: str, right: str) -> bool:
    return Web3.to_checksum_address(left) == Web3.to_checksum_address(right)


def _listed(address: str, allowlist) -> bool:
    return any(_same(address, entry) for entry in allowlist or ())


def _cap(caps, token: str):
    for name, value in (caps or {}).items():
        if _same(name, token):
            return int(value)
    return None


def within_session_policy(policy, prepared, *, gas_price_wei: int, now: datetime):
    """Whether a bounded session may send this decision's calls, and why not if it may not.

    Calls flagged `owner_signs` are not checked against the allowlists: they leave the
    owner's wallet under the owner's own signature, and a session policy that refused them
    would be refusing the owner permission to act on their own position. Every other call
    has to name an allowlisted contract, an allowlisted selector, and — where it is an
    ERC-20 approval — an allowlisted token whose exact approved amount is inside both caps.
    """
    if not prepared:
        # A noop or an alert that offered nothing. True, because nothing is being asked
        # of the session — but said in its own words rather than borrowed from the
        # owner-signed case, which is a different fact about a different decision.
        return True, "this decision prepared no call, so there is nothing to authorise"
    session_calls = [call for call in prepared if call.purpose != OWNER_SIGNS]
    if not session_calls:
        return True, (
            "every prepared call is signed by the account owner from their own wallet, so "
            "no session authority is used"
        )
    if policy is None:
        return False, (
            "no session policy was granted, so nothing may be sent by a session on the "
            "owner's behalf"
        )
    if policy_field(policy, "emergency_pause", False):
        return False, "the session policy is paused"
    expires_at = policy_field(policy, "expires_at")
    if expires_at is None:
        return (
            False,
            "the session policy states no expiry, so its authority is unbounded",
        )
    if now >= parse_expiry(expires_at):
        return False, f"the session policy expired at {expires_at}"
    ceiling = policy_field(policy, "max_gas_price_wei")
    if ceiling is not None and gas_price_wei > int(ceiling):
        return False, (
            f"the gas price is {gas_price_wei} wei, above the session policy's ceiling of "
            f"{int(ceiling)}"
        )

    contracts = policy_field(policy, "contract_allowlist", ())
    functions = policy_field(policy, "function_allowlist", ())
    tokens = policy_field(policy, "token_allowlist", ())
    per_action = policy_field(policy, "per_action_limit_atomic", {})
    total = policy_field(policy, "total_cap_atomic", {})
    for call in session_calls:
        if not _listed(call.to, contracts):
            return False, f"{call.to} is not on the session's contract allowlist"
        selector = call.data[:10].lower()
        if not any(selector == str(entry).lower() for entry in functions or ()):
            return False, (
                f"selector {selector} ({call.purpose}) is not on the session's function "
                "allowlist"
            )
        if selector != APPROVE_SELECTOR:
            continue
        # An approval the session sends spends the session's own tokens, so the target has
        # to be an allowlisted token and the exact amount has to be inside both caps.
        # Skipping the cap check for an approval to an unlisted address would leave the one
        # call in either batch that actually authorises a spend unbounded.
        if not _listed(call.to, tokens):
            return False, (
                f"{call.to} is not on the session's token allowlist, so an approval sent "
                "to it is bounded by nothing"
            )
        amount = approve_amount(call.data)
        limit = _cap(per_action, call.to)
        if limit is None:
            return False, f"the session policy sets no per-action limit for {call.to}"
        if amount > limit:
            return False, (
                f"the approval of {amount} atomic units of {call.to} is above the "
                f"session's per-action limit of {limit}"
            )
        cap = _cap(total, call.to)
        if cap is None:
            return False, f"the session policy sets no total cap for {call.to}"
        if amount > cap:
            return False, (
                f"the approval of {amount} atomic units of {call.to} is above the "
                f"session's total cap of {cap}"
            )
    return True, (
        f"{len(session_calls)} session calls are inside the contract, function, token and "
        "cap bounds the owner granted"
    )


def with_simulation(call: PreparedCall, record: dict) -> PreparedCall:
    """The same call with what the chain said about it attached.

    `PreparedCall` is frozen, so a simulated call is a new record rather than a mutated
    one — the bytes a signer sees and the bytes that were simulated are then provably the
    same object's, and no code path can attach a result to calldata it did not run.
    """
    return PreparedCall(
        to=call.to,
        data=call.data,
        value_atomic=call.value_atomic,
        chain_id=call.chain_id,
        gas_ceiling=call.gas_ceiling,
        deadline=call.deadline,
        purpose=call.purpose,
        simulation=record,
    )


def now_utc() -> datetime:
    """The one clock both executors read, so a test can freeze time in one place."""
    return datetime.now(timezone.utc)


def simulate_call(call: PreparedCall, *, sender: str, rpc) -> tuple[dict, str]:
    """What the chain says about one call, and which question was actually put to it.

    Three verdicts, kept apart because they have different remedies. `passed` is an
    `eth_call` that returned and an estimate inside the call's own ceiling. `reverted` is
    the contract refusing, which is an answer. `unreadable` is the road to the contract
    failing, which is not — reporting an outage as a revert is the mistake
    `docket/escrow/chain.py` exists to stop, so an unreadable call is never treated as a
    passed one either.
    """
    record = {
        "ok": None,
        "gas_estimate": None,
        "revert_reason": None,
        "observed_at": None,
        "block": None,
    }
    tx = {
        "from": Web3.to_checksum_address(sender),
        "to": Web3.to_checksum_address(call.to),
        "data": call.data,
        "value": call.value_atomic,
    }
    try:
        block = rpc(lambda w3: w3.eth.block_number)
    except Exception as exc:
        record["revert_reason"] = f"the block number could not be read: {exc}"
        return record, "unreadable"
    record["block"] = int(block)
    record["observed_at"] = now_utc().isoformat()
    try:
        rpc(lambda w3: w3.eth.call(tx))
        gas = int(rpc(lambda w3: w3.eth.estimate_gas(tx)))
    except Exception as exc:
        record["ok"] = False
        record["revert_reason"] = f"{type(exc).__name__}: {exc}"
        return record, "reverted"
    record["gas_estimate"] = gas
    if gas > call.gas_ceiling:
        record["ok"] = False
        record["revert_reason"] = (
            f"the call estimates at {gas} gas, above its ceiling of {call.gas_ceiling}"
        )
        return record, "reverted"
    record["ok"] = True
    return record, "passed"


def defer(call: PreparedCall, *, depends_on: str, block: int) -> dict:
    """The simulation slot of a call whose only obstacle is one earlier in the batch.

    `ok` stays None rather than becoming False: the chain was never asked, and a call
    recorded as refused when nobody put it to a contract is a preflight lying about what
    it did.
    """
    return {
        "ok": None,
        "gas_estimate": None,
        "revert_reason": f"deferred: depends on {depends_on}",
        "observed_at": now_utc().isoformat(),
        "block": block,
    }
