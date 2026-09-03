"""Getting an owner's money back out of a session key.

Revocation is only as good as this file. A revoked session that still holds the float is
a session the owner cannot spend and Docket has promised not to, which is the worst of
both. So revoke sweeps: every allowlisted token with a balance goes back to the owner,
and then the remaining BNB minus exactly the gas the last transfer costs.

Every leg is attempted even when an earlier one fails, because a token that cannot be
moved is no reason to strand the ones that can. Failures are collected and raised
together as `SweepFailed`, which carries the transactions that did go out — a sweep that
half worked has to say which half.

The BNB leg is last and is sized as `balance - gas_price * 21000`. A plain transfer to an
EOA is exactly 21,000 gas, so the remainder is the largest amount that can leave and
still pay for its own departure. Sweeping BNB first would take the gas the token
transfers need with it.
"""

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


def sweep(session, owner, rpc) -> list[str]:
    """Return every token balance and the spare BNB to `owner`. Returns the tx hashes."""
    recipient = Web3.to_checksum_address(owner)
    sender = Web3.to_checksum_address(session.address)
    sent: list[str] = []
    failures: list[str] = []

    gas_price = int(rpc(lambda w3: w3.eth.gas_price))
    nonce = int(rpc(lambda w3: w3.eth.get_transaction_count(sender)))

    for token in session.token_allowlist:
        if token == NATIVE_TOKEN:
            continue
        try:
            address = Web3.to_checksum_address(token)
            balance = int(
                rpc(
                    lambda w3, address=address: (
                        w3.eth.contract(address=address, abi=ERC20_ABI)
                        .functions.balanceOf(sender)
                        .call()
                    )
                )
            )
            if balance <= 0:
                continue
            data = _encoder.encode_abi("transfer", args=[recipient, balance])
            transaction = {
                "from": sender,
                "to": address,
                "data": data,
                "value": 0,
            }
            gas = int(rpc(lambda w3, tx=transaction: w3.eth.estimate_gas(tx)))
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
