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

from ..jobs.models import Receipt
from ..hire.receipts import canonical_hash

# Twenty attempts three seconds apart. BSC blocks land in about 0.75 s and a receipt that
# has not appeared in a minute is not appearing on this tick; the bound exists so a tick
# unit cannot hang past its timer.
RECEIPT_ATTEMPTS = 20
RECEIPT_PAUSE_S = 3.0
# A margin over the estimate, because the state an estimate is taken against is one block
# older than the state the transaction executes in.
GAS_MARGIN_NUMERATOR = 12
GAS_MARGIN_DENOMINATOR = 10


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


def execute(
    activation,
    prepared,
    *,
    session,
    rpc,
    policy,
    token_amounts=None,
    slippage_bps=None,
    sleep=time.sleep,
) -> Receipt:
    """Simulate, check, sign, send, and wait — or fail loudly having sent nothing.

    `token_amounts` is what this call spends, keyed by token address, and the caller
    supplies it because the calldata alone does not say: a router swap's input is inside
    ABI-encoded bytes this module deliberately does not decode. The tick loop reads it out
    of the decision's own evidence, so the number the policy checks is the number the
    executor reasoned about.
    """
    amounts = {} if token_amounts is None else dict(token_amounts)
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

    permitted, reason = policy.allows(
        prepared,
        spent=session.spent_atomic,
        token_amounts=amounts,
        gas_price_wei=gas_price,
        slippage_bps=slippage_bps,
    )
    if not permitted:
        fail(f"{prepared.purpose}: refused by the session policy — {reason}")

    gas_limit = min(
        prepared.gas_ceiling,
        estimated * GAS_MARGIN_NUMERATOR // GAS_MARGIN_DENOMINATOR,
    )
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
        tx_hash = _hex(
            rpc(lambda w3: w3.eth.send_raw_transaction(signed.raw_transaction))
        )
    except Exception as exc:
        fail(
            f"{prepared.purpose}: the transaction could not be signed or broadcast "
            f"({type(exc).__name__}: {exc})"
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
    if status != 1:
        activation.note(
            f"{prepared.purpose}: {tx_hash} was mined in block {block_number} and "
            "reverted",
            actor="chain",
        )
        raise ExecutionFailed(f"{tx_hash} reverted on chain")

    for token, amount in amounts.items():
        session.spent_atomic[token] = session.spent_atomic.get(token, 0) + int(amount)
    value = int(prepared.value_atomic)
    if value:
        session.spent_atomic["BNB"] = session.spent_atomic.get("BNB", 0) + value

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
