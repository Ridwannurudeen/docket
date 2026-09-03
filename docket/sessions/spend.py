"""What one call spends, read out of its own bytes rather than taken on trust.

The bug this module exists to close: the tick used to hand `execute` the *batch* total
from the executor's evidence, once, and pass the same mapping to every call in the batch.
`SessionPolicy.allows` accumulates per call, so an eight-call rebalance charged eight
times its real spend against `total_cap_atomic` — refusing batches that were inside the
cap, and, in the other direction, letting a single large call clear a per-action limit it
should have failed because the number checked was the batch's rather than the call's.

So the number the policy checks is now derived from the calldata Docket is about to
broadcast. There is no path where a caller's own figure is what gets charged.

Two consequences worth stating plainly:

**The table is closed, and a call outside it is refused rather than guessed at.** A
selector nobody wrote down here, carrying value or aimed at a token the session may spend,
raises `UnmeasuredSpend`. Charging it zero would be the same failure in a quieter form:
an action inside no cap at all.

**The native leg is not returned here.** `SessionPolicy.allows` and
`docket.sessions.executor.execute` each fold `call.value_atomic` in under `BNB`
themselves, and returning it here as well would charge it twice. One owner for the native
leg, and it is the one that already existed.
"""

from web3 import Web3

# Every function Docket's own builders emit, plus the two ERC-20 calls any of them needs
# first. Written out here rather than imported from the agents, because this is the list
# the session is allowed to spend through and it should be readable in one place.
SPEND_ABI = [
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
    },
    {
        "name": "swapExactTokensForTokens",
        "type": "function",
        "stateMutability": "nonpayable",
        "inputs": [
            {"name": "amountIn", "type": "uint256"},
            {"name": "amountOutMin", "type": "uint256"},
            {"name": "path", "type": "address[]"},
            {"name": "to", "type": "address"},
            {"name": "deadline", "type": "uint256"},
        ],
        "outputs": [{"name": "amounts", "type": "uint256[]"}],
    },
    {
        "name": "repayBorrowBehalf",
        "type": "function",
        "stateMutability": "nonpayable",
        "inputs": [
            {"name": "borrower", "type": "address"},
            {"name": "repayAmount", "type": "uint256"},
        ],
        "outputs": [{"name": "", "type": "uint256"}],
    },
    {
        "name": "repayBorrow",
        "type": "function",
        "stateMutability": "nonpayable",
        "inputs": [{"name": "repayAmount", "type": "uint256"}],
        "outputs": [{"name": "", "type": "uint256"}],
    },
    {
        "name": "mint",
        "type": "function",
        "stateMutability": "nonpayable",
        "inputs": [{"name": "mintAmount", "type": "uint256"}],
        "outputs": [{"name": "", "type": "uint256"}],
    },
    {
        "name": "mint",
        "type": "function",
        "stateMutability": "payable",
        "inputs": [
            {
                "name": "params",
                "type": "tuple",
                "components": [
                    {"name": "token0", "type": "address"},
                    {"name": "token1", "type": "address"},
                    {"name": "fee", "type": "uint24"},
                    {"name": "tickLower", "type": "int24"},
                    {"name": "tickUpper", "type": "int24"},
                    {"name": "amount0Desired", "type": "uint256"},
                    {"name": "amount1Desired", "type": "uint256"},
                    {"name": "amount0Min", "type": "uint256"},
                    {"name": "amount1Min", "type": "uint256"},
                    {"name": "recipient", "type": "address"},
                    {"name": "deadline", "type": "uint256"},
                ],
            }
        ],
        "outputs": [],
    },
    {
        "name": "increaseLiquidity",
        "type": "function",
        "stateMutability": "payable",
        "inputs": [
            {
                "name": "params",
                "type": "tuple",
                "components": [
                    {"name": "tokenId", "type": "uint256"},
                    {"name": "amount0Desired", "type": "uint256"},
                    {"name": "amount1Desired", "type": "uint256"},
                    {"name": "amount0Min", "type": "uint256"},
                    {"name": "amount1Min", "type": "uint256"},
                    {"name": "deadline", "type": "uint256"},
                ],
            }
        ],
        "outputs": [],
    },
    {
        "name": "decreaseLiquidity",
        "type": "function",
        "stateMutability": "payable",
        "inputs": [
            {
                "name": "params",
                "type": "tuple",
                "components": [
                    {"name": "tokenId", "type": "uint256"},
                    {"name": "liquidity", "type": "uint128"},
                    {"name": "amount0Min", "type": "uint256"},
                    {"name": "amount1Min", "type": "uint256"},
                    {"name": "deadline", "type": "uint256"},
                ],
            }
        ],
        "outputs": [],
    },
    {
        "name": "collect",
        "type": "function",
        "stateMutability": "payable",
        "inputs": [
            {
                "name": "params",
                "type": "tuple",
                "components": [
                    {"name": "tokenId", "type": "uint256"},
                    {"name": "recipient", "type": "address"},
                    {"name": "amount0Max", "type": "uint128"},
                    {"name": "amount1Max", "type": "uint128"},
                ],
            }
        ],
        "outputs": [],
    },
]
_decoder = Web3().eth.contract(abi=SPEND_ABI)

APPROVE = "0x095ea7b3"
TRANSFER = "0xa9059cbb"
SWAP_EXACT_TOKENS_FOR_TOKENS = "0x38ed1739"
REPAY_BORROW_BEHALF = "0x2608f818"
REPAY_BORROW = "0x0e752702"
VTOKEN_MINT = "0xa0712d68"
NPM_MINT = "0x88316456"
NPM_INCREASE_LIQUIDITY = "0x219f5d17"
NPM_DECREASE_LIQUIDITY = "0x0c49ccbe"
NPM_COLLECT = "0xfc6f7865"

# Calls whose amount is denominated in the underlying of the vToken they are sent to. The
# vToken does not carry that address in its calldata, so it is read from the chain or
# supplied by the executor that drafted the call.
VTOKEN_SELECTORS = frozenset({REPAY_BORROW_BEHALF, REPAY_BORROW, VTOKEN_MINT})
# Calls that take liquidity out rather than putting it in. Zero spend, never negative:
# a session cap bounds what may leave the session, and a withdrawal is not that.
WITHDRAWING_SELECTORS = frozenset({NPM_DECREASE_LIQUIDITY, NPM_COLLECT})
MEASURED_SELECTORS = frozenset(
    {
        APPROVE,
        TRANSFER,
        SWAP_EXACT_TOKENS_FOR_TOKENS,
        NPM_MINT,
        NPM_INCREASE_LIQUIDITY,
    }
    | VTOKEN_SELECTORS
    | WITHDRAWING_SELECTORS
)


class UnmeasuredSpend(ValueError):
    """A call whose spend cannot be derived from its own bytes. Never charged as zero."""


def _checksum(address) -> str | None:
    try:
        return Web3.to_checksum_address(address)
    except Exception:
        return None


def needs_underlying(call) -> str | None:
    """The vToken whose underlying this call is denominated in, if it is one of those.

    Answered before `call_spend` rather than inside it, so the one module that talks to a
    node stays the one module that talks to a node.
    """
    if call.selector in VTOKEN_SELECTORS:
        return _checksum(call.to)
    return None


def call_spend(call, *, token_allowlist=(), token_hints=None) -> dict[str, int]:
    """What this one call moves out of the session, keyed by token address.

    `token_hints` carries the two facts no calldata contains:
    `{"underlying": {vToken: token}}` for Venus, and
    `{"position_tokens": {token_id: [token0, token1]}}` for an `increaseLiquidity`, whose
    params name a position id and no tokens at all. A hint that is needed and missing is
    an `UnmeasuredSpend`, not a zero.
    """
    hints = token_hints or {}
    underlying = {
        _checksum(key) or str(key): value
        for key, value in (hints.get("underlying") or {}).items()
    }
    positions = {
        str(key): value for key, value in (hints.get("position_tokens") or {}).items()
    }
    allowlisted = {
        checksummed
        for checksummed in (_checksum(token) for token in token_allowlist)
        if checksummed is not None
    }
    target = _checksum(call.to)
    selector = call.selector

    if selector not in MEASURED_SELECTORS:
        if int(call.value_atomic) != 0 or target in allowlisted:
            raise UnmeasuredSpend(
                f"{selector} is not a selector Docket can derive a spend from, and this "
                f"call carries {call.value_atomic} wei to {call.to}. Charging it zero "
                "would put it inside no cap at all."
            )
        return {}

    if selector in WITHDRAWING_SELECTORS:
        return {}

    _, arguments = _decoder.decode_function_input(call.data)

    if selector in (APPROVE, TRANSFER):
        if target is None:
            raise UnmeasuredSpend(f"{call.to!r} is not a token address")
        return _nonzero({target: int(arguments["amount"])})

    if selector == SWAP_EXACT_TOKENS_FOR_TOKENS:
        path = arguments["path"]
        if not path:
            raise UnmeasuredSpend("a swap with an empty path spends an unnamed token")
        return _nonzero({_checksum(path[0]): int(arguments["amountIn"])})

    if selector in VTOKEN_SELECTORS:
        token = _checksum(underlying.get(target))
        if token is None:
            raise UnmeasuredSpend(
                f"{call.to} is a vToken and its underlying was not supplied, so the "
                "amount in this call names no token"
            )
        amount = arguments.get("repayAmount", arguments.get("mintAmount"))
        return _nonzero({token: int(amount)})

    params = arguments["params"]
    if selector == NPM_MINT:
        return _nonzero(
            {
                _checksum(params["token0"]): int(params["amount0Desired"]),
                _checksum(params["token1"]): int(params["amount1Desired"]),
            }
        )

    pair = positions.get(str(params["tokenId"]))
    if not pair or len(pair) != 2:
        raise UnmeasuredSpend(
            f"increaseLiquidity names position {params['tokenId']} and no tokens; its "
            "token0 and token1 were not supplied, so the amounts name nothing"
        )
    return _nonzero(
        {
            _checksum(pair[0]): int(params["amount0Desired"]),
            _checksum(pair[1]): int(params["amount1Desired"]),
        }
    )


def _nonzero(spend: dict) -> dict[str, int]:
    """Drop the legs that move nothing, and refuse a leg naming no token."""
    for token, amount in spend.items():
        if token is None and amount:
            raise UnmeasuredSpend(
                f"this call moves {amount} of a token whose address could not be read"
            )
    return {token: amount for token, amount in spend.items() if token and amount}


def batch_spend(calls, *, token_allowlist=(), token_hints=None) -> dict[str, int]:
    """The whole batch's spend, so the total can be put to the cap once before any of it
    is sent. A batch refused halfway leaves a position half-rebalanced."""
    total: dict[str, int] = {}
    for call in calls:
        for token, amount in call_spend(
            call, token_allowlist=token_allowlist, token_hints=token_hints
        ).items():
            total[token] = total.get(token, 0) + amount
        value = int(call.value_atomic)
        if value:
            total["BNB"] = total.get("BNB", 0) + value
    return total
