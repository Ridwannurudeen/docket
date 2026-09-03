"""Getting an owner's money back out of a session key, and proving it came back.

Revocation is only as good as this file. A revoked session that still holds the float is
a session the owner cannot spend and Docket has promised not to, which is the worst of
both.

Three things this gets wrong if it is written the obvious way, and all three were:

**The BNB leg has to be sized after the token legs mine, not before.** Reading
`getBalance` at the top and subtracting one transfer's gas ignores the gas the token
transfers are about to burn. The BNB transfer is then over-sized by exactly that, and it
fails for insufficient funds — leaving the whole float behind. So the token legs are
broadcast, waited for, and only then is the balance re-read and the remainder sized.

**Broadcasting is not sweeping.** `send_raw_transaction` returns a hash, not an outcome.
Nothing here says the money is back; `residual_balances` does, by reading what is still
there at a later block, and the caller may not close the activation until that reads zero.

**Gas price is a spend.** A node quoting an absurd price would let the sweep burn the
float as fees, so the price is bounded by the same `max_gas_price_wei` the session policy
bounds everything else with.
"""

import time

from web3 import Web3

# The two functions a sweep touches, written out here rather than loaded from `abis/`,
# for the reason `escrow/chain.py` gives: that directory is a repo directory and does not
# exist on the deployed box.
ERC20_ABI = [
    {
        "name": "balanceOf",
        "type": "function",
        "stateMutability": "view",
        "inputs": [{"name": "account", "type": "address"}],
        "outputs": [{"name": "", "type": "uint256"}],
    },
    {
        "name": "transfer",
        "type": "function",
        "stateMutability": "nonpayable",
        "inputs": [
            {"name": "to", "type": "address"},
            {"name": "amount", "type": "uint256"},
        ],
        "outputs": [{"name": "", "type": "bool"}],
    },
]
_encoder = Web3().eth.contract(abi=ERC20_ABI)

BSC_CHAIN_ID = 56
NATIVE_TOKEN = "BNB"
# A plain value transfer to an account with no code.
NATIVE_TRANSFER_GAS = 21_000
# The same margin `sessions.executor` puts on an estimate, for the same reason: the state
# an estimate is taken against is one block older than the state the transaction runs in.
GAS_MARGIN_NUMERATOR = 12
GAS_MARGIN_DENOMINATOR = 10
# Bounded, like every other wait in this package. Twelve attempts five seconds apart is a
# minute, and the timer comes back in another one.
RECEIPT_ATTEMPTS = 12
RECEIPT_PAUSE_S = 5.0


class SweepFailed(RuntimeError):
    """One or more legs did not go out. `sent` names the ones that did."""

    def __init__(self, message: str, sent: list[str]) -> None:
        super().__init__(message)
        self.sent = sent


def _hex(value) -> str:
    if isinstance(value, (bytes, bytearray)):
        return "0x" + bytes(value).hex()
    text = str(value)
    return text if text.startswith("0x") else "0x" + text


def _gas_price(rpc, max_gas_price_wei) -> int:
    """What the node quotes, capped at what the policy permits.

    Capped rather than refused: a sweep is the owner asking for their money back, and a
    momentarily expensive block is a reason to pay less than the quote, not a reason to
    leave the float where it is. A transaction priced under the going rate waits; it does
    not lose anything.
    """
    quoted = int(rpc(lambda w3: w3.eth.gas_price))
    if max_gas_price_wei is None:
        return quoted
    return min(quoted, int(max_gas_price_wei))


def _tokens_of(session) -> tuple[str, ...]:
    """Every token this session could be holding.

    The allowlist is what it was permitted to spend, which is not the same set as what it
    can end up with: a swap's output token is received, never spent, and would sit in the
    session for ever if the sweep only looked at the spend side. So anything the executor
    named in evidence is swept too.
    """
    seen = []
    for token in tuple(session.token_allowlist) + tuple(
        getattr(session, "received_tokens", ()) or ()
    ):
        if token == NATIVE_TOKEN:
            continue
        try:
            checksummed = Web3.to_checksum_address(token)
        except Exception:
            continue
        if checksummed not in seen:
            seen.append(checksummed)
    return tuple(seen)


def _await_receipts(rpc, hashes, sleep) -> list[str]:
    """Wait for every broadcast leg, bounded. Returns the ones that did not appear."""
    pending = list(hashes)
    for attempt in range(RECEIPT_ATTEMPTS):
        still = []
        for tx_hash in pending:
            try:
                receipt = rpc(lambda w3, h=tx_hash: w3.eth.get_transaction_receipt(h))
            except Exception:
                receipt = None
            if receipt is None:
                still.append(tx_hash)
        pending = still
        if not pending:
            return []
        if attempt < RECEIPT_ATTEMPTS - 1:
            sleep(RECEIPT_PAUSE_S)
    return pending


def residual_balances(session, rpc) -> dict[str, int]:
    """What the session still holds, read now. Empty means the float is back.

    BNB below the cost of one transfer counts as nothing: it cannot pay for its own
    departure, so no sweep will ever move it and holding the activation open waiting for
    it to leave would keep it open for ever. Every ERC-20 has to read exactly zero,
    because a token transfer's gas is paid in BNB and a token balance is always movable.
    """
    address = Web3.to_checksum_address(session.address)
    residual: dict[str, int] = {}
    for token in _tokens_of(session):
        balance = int(
            rpc(
                lambda w3, token=token: (
                    w3.eth.contract(address=token, abi=ERC20_ABI)
                    .functions.balanceOf(address)
                    .call()
                )
            )
        )
        if balance > 0:
            residual[token] = balance
    native = int(rpc(lambda w3: w3.eth.get_balance(address)))
    gas_price = int(rpc(lambda w3: w3.eth.gas_price))
    if native > gas_price * NATIVE_TRANSFER_GAS:
        residual[NATIVE_TOKEN] = native
    return residual


def sweep(
    session, owner, rpc, *, max_gas_price_wei=None, sleep=time.sleep
) -> list[str]:
    """Return every token balance and then the spare BNB. Returns the tx hashes sent.

    The order is the whole of the fix: tokens first, waited for, and the native leg sized
    against a balance re-read after their gas has actually been taken. Sweeping BNB first
    would take the gas the token transfers need with it, and sizing it up front would
    over-spend by however much they burn.
    """
    recipient = Web3.to_checksum_address(owner)
    sender = Web3.to_checksum_address(session.address)
    sent: list[str] = []
    failures: list[str] = []

    gas_price = _gas_price(rpc, max_gas_price_wei)
    nonce = int(rpc(lambda w3: w3.eth.get_transaction_count(sender)))

    for token in _tokens_of(session):
        try:
            balance = int(
                rpc(
                    lambda w3, token=token: (
                        w3.eth.contract(address=token, abi=ERC20_ABI)
                        .functions.balanceOf(sender)
                        .call()
                    )
                )
            )
            if balance <= 0:
                continue
            data = _encoder.encode_abi("transfer", args=[recipient, balance])
            transaction = {"from": sender, "to": token, "data": data, "value": 0}
            estimated = int(rpc(lambda w3, tx=transaction: w3.eth.estimate_gas(tx)))
            gas = estimated * GAS_MARGIN_NUMERATOR // GAS_MARGIN_DENOMINATOR
            signed = session.account.sign_transaction(
                {
                    **transaction,
                    "nonce": nonce,
                    "gas": gas,
                    "gasPrice": gas_price,
                    "chainId": BSC_CHAIN_ID,
                }
            )
            sent.append(
                _hex(
                    rpc(
                        lambda w3, raw=signed.raw_transaction: (
                            w3.eth.send_raw_transaction(raw)
                        )
                    )
                )
            )
            nonce += 1
        except Exception as exc:
            failures.append(f"{token}: {type(exc).__name__}: {exc}")

    # The token legs have to be mined before the balance below means anything: until they
    # are, their gas has not been taken and the remainder is an over-estimate.
    unmined = _await_receipts(rpc, sent, sleep)
    if unmined:
        failures.append(
            f"{len(unmined)} token transfers had not mined in "
            f"{int(RECEIPT_ATTEMPTS * RECEIPT_PAUSE_S)}s, so the BNB leg was not sized"
        )
    else:
        try:
            balance = int(rpc(lambda w3: w3.eth.get_balance(sender)))
            cost = gas_price * NATIVE_TRANSFER_GAS
            if balance > cost:
                signed = session.account.sign_transaction(
                    {
                        "from": sender,
                        "to": recipient,
                        "value": balance - cost,
                        "nonce": nonce,
                        "gas": NATIVE_TRANSFER_GAS,
                        "gasPrice": gas_price,
                        "chainId": BSC_CHAIN_ID,
                    }
                )
                sent.append(
                    _hex(
                        rpc(
                            lambda w3, raw=signed.raw_transaction: (
                                w3.eth.send_raw_transaction(raw)
                            )
                        )
                    )
                )
        except Exception as exc:
            failures.append(f"{NATIVE_TOKEN}: {type(exc).__name__}: {exc}")

    if failures:
        raise SweepFailed(
            "the session was not fully swept: " + "; ".join(failures), sent
        )
    return sent
