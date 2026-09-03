"""The one function in Docket that signs and broadcasts on an owner's behalf.

Executors decide. This sends. Nothing else in `docket/jobs/` or `docket/agents/` holds a
key, and every path that reaches the chain with a write on it comes through here, so the
order below is the whole of Docket's send-side discipline and there is no second copy of
it to drift.

The order, and why each step is where it is:

  1. `eth_call` the exact bytes from the exact sender. A revert here is the contract
     saying no, before a fee is paid to find that out.
  2. `eth_estimateGas`, and refuse a call that estimates above the ceiling the decision
     committed to. A call that costs more than it was reasoned about is not that call.
  3. Read the gas price, then put it and the amounts to the policy. The policy check runs
     after the chain reads because two of its bounds — price and estimated cost — are
     facts about this moment rather than about the bytes.
  4. Sign, send, and wait for the receipt with a bounded wait.

A failure at any step is recorded on the activation and raised as `ExecutionFailed`. It
is never swallowed: an activation whose action silently did not happen is worse than one
that says why, because the owner is still reading it as live.
"""

import time
from datetime import datetime, timezone

from ..hire.receipts import canonical_hash
from ..jobs.models import Receipt
from .policy import NATIVE_TOKEN, token_key
from .spend import (
    UnmeasuredSpend,
    call_spend,
    is_authorisation_only,
    needs_underlying,
)

# Twenty attempts three seconds apart. BSC blocks land in about 0.75 s and a receipt that
# has not appeared in a minute is not appearing on this tick; the bound exists so a tick
# unit cannot hang past its timer.
# Ninety seconds, and then the pass gives up and says so. BSC blocks land in about
# 0.75 s; a receipt that has not appeared in a minute and a half is not appearing on
# this pass, and the timer comes back in another minute.
RECEIPT_ATTEMPTS = 30
RECEIPT_PAUSE_S = 3.0
# How many settled sends stay on the activation. Enough to reconcile a run of passes
# against the chain; not so many that one row grows without bound.
SETTLED_SENDS_KEPT = 50
# A margin over the estimate, because the state an estimate is taken against is one block
# older than the state the transaction executes in.
GAS_MARGIN_NUMERATOR = 12
GAS_MARGIN_DENOMINATOR = 10
# The one view a vToken has to answer before an amount sent to it can be given a token.
VTOKEN_ABI = [
    {
        "name": "underlying",
        "type": "function",
        "stateMutability": "view",
        "inputs": [],
        "outputs": [{"name": "", "type": "address"}],
    }
]


class ExecutionFailed(RuntimeError):
    """A send that did not happen, or happened and reverted. Never silent."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _hex(value) -> str:
    """One spelling for a hash, whatever web3 handed back."""
    if isinstance(value, (bytes, bytearray)):
        return "0x" + bytes(value).hex()
    text = str(value)
    return text if text.startswith("0x") else "0x" + text


def _record_pending(activation, entry: dict) -> None:
    """Keep one in-flight broadcast on the activation, keyed by its account nonce.

    Written and PERSISTED before the transaction is sent, then updated when its receipt
    is read, so a pass that dies between the two leaves a durable record naming what left
    rather than nothing at all. Keyed by nonce, because that is the one identifier that
    exists before the hash does — and it is the account nonce, so a later pass can tell a
    send that landed from one that never left.
    """
    result = dict(activation.result or {})
    pending = dict(result.get("pending_sends") or {})
    key = str(entry["nonce"])
    pending[key] = {**(pending.get(key) or {}), **entry}
    result["pending_sends"] = pending
    activation.result = result


def _forget_pending(activation, nonce) -> None:
    """Drop a pending entry for a transaction that turned out never to be broadcast."""
    result = dict(activation.result or {})
    pending = dict(result.get("pending_sends") or {})
    pending.pop(str(nonce), None)
    result["pending_sends"] = pending
    activation.result = result


def _settle_pending(activation, nonce, *, tx_hash, status, gas_atomic) -> None:
    """Move one in-flight broadcast into the settled record, with its outcome."""
    result = dict(activation.result or {})
    pending = dict(result.get("pending_sends") or {})
    entry = pending.pop(str(nonce), {"nonce": nonce})
    result["pending_sends"] = pending
    settled = list(result.get("settled_sends") or ())
    settled.append(
        {**entry, "tx_hash": tx_hash, "status": status, "gas_atomic": gas_atomic}
    )
    result["settled_sends"] = settled[-SETTLED_SENDS_KEPT:]
    activation.result = result


def execute(
    activation,
    prepared,
    *,
    session,
    rpc,
    policy,
    token_hints=None,
    slippage_bps=None,
    persist=None,
    sleep=time.sleep,
) -> Receipt:
    """Simulate, check, sign, send, and wait — or fail loudly having sent nothing.

    What this call spends is DERIVED, from the bytes about to be broadcast, by
    `docket.sessions.spend.call_spend`. It is never taken from a caller: the batch total
    the tick used to pass was charged once per call, so an eight-call rebalance was
    checked against eight times its own spend. `token_hints` carries only the two facts no
    calldata contains — a vToken's underlying and a v3 position's token pair — and a hint
    that is needed and missing refuses the call rather than charging it zero.

    `persist` writes the activation to the database, and is called with the pending record
    on it and BEFORE the transaction is broadcast. That order is the whole of this
    function's crash-safety: a pass killed between the send and its receipt has already
    left a durable record of what went out, so the next pass reconciles instead of sending
    the same action a second time. A `persist` that refuses — another writer reached the
    row first — refuses the send with it.
    """
    hints = dict(token_hints or {})
    vtoken = needs_underlying(prepared)
    if vtoken is not None and vtoken not in (hints.get("underlying") or {}):
        # One read, and only where the calldata genuinely cannot say. `underlying()` is a
        # view on the vToken itself, so the answer comes from the contract being paid
        # rather than from a table that could name the wrong token.
        try:
            resolved = rpc(
                lambda w3: w3.eth.contract(address=vtoken, abi=VTOKEN_ABI)
                .functions.underlying()
                .call()
            )
        except Exception as exc:
            activation.note(
                f"{prepared.purpose}: {vtoken} is a vToken and its underlying could not "
                f"be read ({type(exc).__name__}), so nothing was sent",
                actor="docket",
            )
            raise ExecutionFailed(
                f"{prepared.purpose}: the underlying of {vtoken} could not be read"
            ) from exc
        hints["underlying"] = {**(hints.get("underlying") or {}), vtoken: resolved}

    try:
        amounts = {
            token_key(token): int(amount)
            for token, amount in call_spend(
                prepared,
                token_allowlist=policy.token_allowlist,
                token_hints=hints,
                owner=activation.owner,
                session=session.address,
            ).items()
        }
    except UnmeasuredSpend as exc:
        activation.note(
            f"{prepared.purpose}: refused as unmeasured spend — {exc}",
            actor="docket",
        )
        raise ExecutionFailed(
            f"{prepared.purpose}: unmeasured spend — {exc}"
        ) from exc

    transaction = {
        "from": session.address,
        "to": prepared.to,
        "data": prepared.data,
        "value": int(prepared.value_atomic),
    }

    def fail(reason: str) -> None:
        activation.note(reason, actor="docket")
        raise ExecutionFailed(reason)

    try:
        rpc(lambda w3: w3.eth.call(transaction))
    except Exception as exc:
        fail(
            f"{prepared.purpose}: the call reverted in simulation and was not sent "
            f"({type(exc).__name__}: {exc})"
        )
    try:
        estimated = int(rpc(lambda w3: w3.eth.estimate_gas(transaction)))
    except Exception as exc:
        fail(
            f"{prepared.purpose}: the call could not be estimated and was not sent "
            f"({type(exc).__name__}: {exc})"
        )
    if estimated > prepared.gas_ceiling:
        fail(
            f"{prepared.purpose}: estimates at {estimated} gas, above the prepared "
            f"ceiling of {prepared.gas_ceiling}"
        )
    try:
        gas_price = int(rpc(lambda w3: w3.eth.gas_price))
    except Exception as exc:
        fail(
            f"{prepared.purpose}: the gas price could not be read and nothing was sent "
            f"({type(exc).__name__}: {exc})"
        )

    gas_limit = min(
        prepared.gas_ceiling,
        estimated * GAS_MARGIN_NUMERATOR // GAS_MARGIN_DENOMINATOR,
    )
    # Gas leaves the session like anything else. A cap that bounds the tokens and not the
    # fees is a cap a long enough run of expensive no-op transactions walks straight
    # through, so the fee this call can cost is charged against the native cap with it.
    charged = dict(amounts)
    charged[NATIVE_TOKEN] = charged.get(NATIVE_TOKEN, 0) + gas_limit * gas_price

    permitted, reason = policy.allows(
        prepared,
        spent=session.spent_atomic,
        token_amounts=charged,
        gas_price_wei=gas_price,
        slippage_bps=slippage_bps,
    )
    if not permitted:
        fail(f"{prepared.purpose}: refused by the session policy — {reason}")

    try:
        nonce = int(rpc(lambda w3: w3.eth.get_transaction_count(session.address)))
        signed = session.account.sign_transaction(
            {
                **transaction,
                "nonce": nonce,
                "gas": gas_limit,
                "gasPrice": gas_price,
                "chainId": prepared.chain_id,
            }
        )
        # Written down, and WRITTEN OUT, before the send. A broadcast whose receipt is
        # never read is money that left with no record of leaving; a record that exists
        # only in memory is not a record — a SIGTERM between the send and the end of the
        # batch would take it with it, and the next pass would send the action again.
        _record_pending(
            activation,
            {
                "nonce": nonce,
                "purpose": prepared.purpose,
                "amounts": {token: str(amount) for token, amount in charged.items()},
                "estimated_fee_atomic": str(gas_limit * gas_price),
                "gas_limit": gas_limit,
                "gas_price_wei": str(gas_price),
                "broadcast_at": _now(),
            },
        )
    except Exception as exc:
        fail(
            f"{prepared.purpose}: the transaction could not be signed "
            f"({type(exc).__name__}: {exc})"
        )

    if persist is not None:
        # Outside the guard on purpose. A refusal here means another writer reached this
        # activation first, and the right answer to that is to send nothing at all.
        persist()

    try:
        tx_hash = _hex(
            rpc(lambda w3: w3.eth.send_raw_transaction(signed.raw_transaction))
        )
    except Exception as exc:
        _forget_pending(activation, nonce)
        if persist is not None:
            try:
                persist()
            except Exception:
                pass
        fail(
            f"{prepared.purpose}: the transaction was not broadcast "
            f"({type(exc).__name__}: {exc})"
        )

    _record_pending(activation, {"nonce": nonce, "tx_hash": tx_hash})
    if persist is not None:
        # The transaction is on the wire now, so a refusal here must not lose it and must
        # not stop the pass: it is noted, and the merge at the end of the batch reconciles.
        try:
            persist()
        except Exception as exc:
            activation.note(
                f"{prepared.purpose}: {tx_hash} was broadcast and its hash could not be "
                f"written down immediately ({type(exc).__name__})",
                actor="docket",
            )

    receipt = None
    for attempt in range(RECEIPT_ATTEMPTS):
        try:
            receipt = rpc(lambda w3: w3.eth.get_transaction_receipt(tx_hash))
        except Exception:
            receipt = None
        if receipt is not None:
            break
        if attempt < RECEIPT_ATTEMPTS - 1:
            sleep(RECEIPT_PAUSE_S)
    if receipt is None:
        fail(
            f"{prepared.purpose}: broadcast {tx_hash} and no receipt appeared within "
            f"{int(RECEIPT_ATTEMPTS * RECEIPT_PAUSE_S)}s. The transaction may still "
            "land; Docket will not send it again."
        )

    status = int(receipt["status"])
    gas_used = int(receipt["gasUsed"])
    block_number = int(receipt["blockNumber"])
    execution = {
        "tx_hash": tx_hash,
        "status": status,
        "gas_used": gas_used,
        "gas_price_wei": str(gas_price),
        "block_number": block_number,
        "chain_id": prepared.chain_id,
        "purpose": prepared.purpose,
        "session": session.address,
        "token_amounts": {token: str(amount) for token, amount in amounts.items()},
    }
    # The fee is taken whether or not the call succeeded, so it is charged either way.
    spent_gas = gas_used * gas_price
    session.spent_atomic[NATIVE_TOKEN] = (
        session.spent_atomic.get(NATIVE_TOKEN, 0) + spent_gas
    )
    if status != 1:
        _settle_pending(
            activation, nonce, tx_hash=tx_hash, status=0, gas_atomic=str(spent_gas)
        )
        activation.note(
            f"{prepared.purpose}: {tx_hash} was mined in block {block_number} and "
            "reverted; only its gas was spent",
            actor="chain",
        )
        raise ExecutionFailed(f"{tx_hash} reverted on chain")

    # An approval moves nothing. It was counted in the batch total, because a session that
    # cannot cover it cannot complete the batch, but charging it here as well as the
    # transfer it authorises would bill one movement twice.
    if not is_authorisation_only(prepared):
        for token, amount in amounts.items():
            session.spent_atomic[token] = session.spent_atomic.get(token, 0) + int(
                amount
            )
        value = int(prepared.value_atomic)
        if value:
            session.spent_atomic[NATIVE_TOKEN] = (
                session.spent_atomic.get(NATIVE_TOKEN, 0) + value
            )
    _settle_pending(
        activation, nonce, tx_hash=tx_hash, status=1, gas_atomic=str(spent_gas)
    )

    activation.note(
        f"{prepared.purpose}: {tx_hash} succeeded in block {block_number} using "
        f"{gas_used} gas",
        actor="chain",
    )
    return Receipt(
        service=activation.service_id,
        input_hash=canonical_hash(prepared.to_dict()),
        output_hash=canonical_hash(execution),
        delivered_at=_now(),
        payment=None,
        execution=execution,
    )
