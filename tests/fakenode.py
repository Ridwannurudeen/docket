"""A fake BSC node for the audit.

Unlike the builder's fakes it behaves like a node on the two points that matter for a
sweep: it debits gas (and value) only when a transaction is MINED, it refuses at
broadcast a transaction the sender cannot afford given what is already pending from it,
and it raises `TransactionNotFound` for a hash that has not mined. Mining happens only
when `mine()` is called, so "a later block" is a thing a test controls.
"""

from types import SimpleNamespace

from eth_account import Account
from eth_account._utils.legacy_transactions import Transaction
from eth_utils import keccak, to_checksum_address
from web3 import Web3
from web3.exceptions import TransactionNotFound

ERC20_ABI = [
    {
        "name": "approve",
        "type": "function",
        "stateMutability": "nonpayable",
        "inputs": [
            {"name": "spender", "type": "address"},
            {"name": "amount", "type": "uint256"},
        ],
        "outputs": [{"name": "", "type": "bool"}],
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
    }
]
_erc20 = Web3().eth.contract(abi=ERC20_ABI)
TRANSFER = "0xa9059cbb"
APPROVE = "0x095ea7b3"
NATIVE_GAS = 21_000


def cs(address):
    return to_checksum_address(address)


class _Fn:
    def __init__(self, value):
        self.value = value

    def call(self):
        if isinstance(self.value, Exception):
            raise self.value
        return self.value


class _Functions:
    def __init__(self, node, address):
        self.node = node
        self.address = address

    def balanceOf(self, account):  # noqa: N802
        return _Fn(self.node.tokens.get(self.address, {}).get(cs(account), 0))

    def allowance(self, owner, spender):
        granted = self.node.allowances.get(self.address, {})
        return _Fn(granted.get((cs(owner), cs(spender)), 0))

    def underlying(self):
        return _Fn(self.node.underlying.get(self.address, ValueError("no underlying")))


class _Contract:
    def __init__(self, node, address):
        self.functions = _Functions(node, cs(address))


class _Eth:
    def __init__(self, node):
        self.node = node

    @property
    def gas_price(self):
        return self.node.gas_price

    def call(self, transaction):
        return b""

    def estimate_gas(self, transaction):
        return self.node.estimate

    def get_transaction_count(self, address):
        return self.node.nonces.get(cs(address), 0)

    def get_balance(self, address):
        return self.node.bnb.get(cs(address), 0)

    def contract(self, address=None, abi=None):
        return _Contract(self.node, address)

    def send_raw_transaction(self, raw):
        return self.node.send(bytes(raw))

    def get_transaction_receipt(self, tx_hash):
        node = self.node
        node.receipt_calls += 1
        if node.on_receipt is not None:
            node.on_receipt(node)
        if node.automine_on_receipt and node.pending:
            node.mine()
        key = tx_hash if isinstance(tx_hash, str) else "0x" + bytes(tx_hash).hex()
        if key in node.receipts:
            return node.receipts[key]
        raise TransactionNotFound(key)

    def get_transaction(self, tx_hash):
        return self.node.txs.get(tx_hash)


class Node:
    def __init__(self, *, gas_price=10**9, estimate=60_000):
        self.gas_price = gas_price
        self.estimate = estimate
        self.bnb = {}
        self.tokens = {}
        self.allowances = {}
        self.underlying = {}
        self.nonces = {}
        self.pending = []
        self.receipts = {}
        self.txs = {}
        self.mined_order = []
        self.rejected = []
        self.block = 100
        self.force_status = None
        self.on_receipt = None
        self.automine_on_receipt = False
        self.receipt_calls = 0
        self.eth = _Eth(self)
        self.w3 = SimpleNamespace(eth=self.eth)

    def rpc(self):
        return lambda do: do(self.w3)

    def send(self, raw):
        tx = Transaction.from_bytes(raw)
        sender = cs(Account.recover_transaction(raw))
        expected = self.nonces.get(sender, 0) + sum(
            1 for p in self.pending if p["from"] == sender
        )
        if tx.nonce != expected:
            raise ValueError(f"nonce too low/high: {tx.nonce} vs expected {expected}")
        cost = tx.gas * tx.gasPrice + tx.value
        committed = sum(
            p["gas"] * p["gasPrice"] + p["value"]
            for p in self.pending
            if p["from"] == sender
        )
        available = self.bnb.get(sender, 0) - committed
        if cost > available:
            self.rejected.append((sender, tx.nonce, cost, available))
            raise ValueError(
                f"insufficient funds for gas * price + value: have {available} "
                f"want {cost}"
            )
        tx_hash = "0x" + keccak(raw).hex()
        to = cs(tx.to) if tx.to else None
        entry = {
            "hash": tx_hash,
            "from": sender,
            "to": to,
            "nonce": tx.nonce,
            "gas": tx.gas,
            "gasPrice": tx.gasPrice,
            "value": tx.value,
            "data": "0x" + bytes(tx.data).hex(),
        }
        self.pending.append(entry)
        self.txs[tx_hash] = {
            "from": sender,
            "to": to,
            "input": entry["data"],
            "value": tx.value,
            "hash": tx_hash,
        }
        return tx_hash

    def mine(self):
        self.block += 1
        for p in self.pending:
            status = 1 if self.force_status is None else self.force_status
            gas_used = (
                NATIVE_GAS if p["data"] in ("0x", "") else min(p["gas"], self.estimate)
            )
            self.bnb[p["from"]] = self.bnb.get(p["from"], 0) - gas_used * p["gasPrice"]
            if p["value"] and status == 1:
                self.bnb[p["from"]] -= p["value"]
                self.bnb[p["to"]] = self.bnb.get(p["to"], 0) + p["value"]
            if p["data"].startswith(APPROVE) and status == 1:
                _, args = _erc20.decode_function_input(p["data"])
                self.allowances.setdefault(p["to"], {})[
                    (p["from"], cs(args["spender"]))
                ] = args["amount"]
            if p["data"].startswith(TRANSFER) and status == 1:
                _, args = _erc20.decode_function_input(p["data"])
                balances = self.tokens.setdefault(p["to"], {})
                if balances.get(p["from"], 0) >= args["amount"]:
                    balances[p["from"]] -= args["amount"]
                    recipient = cs(args["to"])
                    balances[recipient] = balances.get(recipient, 0) + args["amount"]
                else:
                    status = 0
            self.nonces[p["from"]] = p["nonce"] + 1
            self.receipts[p["hash"]] = {
                "status": status,
                "gasUsed": gas_used,
                "blockNumber": self.block,
                "logs": [],
            }
            self.mined_order.append(p["hash"])
        self.pending = []
