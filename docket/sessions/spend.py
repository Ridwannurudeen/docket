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
        "name": "exactInputSingle",
        "type": "function",
        "stateMutability": "payable",
        "inputs": [
            {
                "name": "params",
                "type": "tuple",
                "components": [
                    {"name": "tokenIn", "type": "address"},
                    {"name": "tokenOut", "type": "address"},
                    {"name": "fee", "type": "uint24"},
                    {"name": "recipient", "type": "address"},
                    {"name": "deadline", "type": "uint256"},
                    {"name": "amountIn", "type": "uint256"},
                    {"name": "amountOutMinimum", "type": "uint256"},
                    {"name": "sqrtPriceLimitX96", "type": "uint160"},
                ],
            }
        ],
        "outputs": [{"name": "amountOut", "type": "uint256"}],
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
# PancakeSwap's v3 SwapRouter, the eight-field Uniswap shape whose params carry a
# deadline. Lane D2's migration route and Lane D1's thin-pair swaps both send it.
EXACT_INPUT_SINGLE = "0x414bf389"
# The native coin, keyed the way `sessions.policy` keys it.
NATIVE_TOKEN = "BNB"

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
        EXACT_INPUT_SINGLE,
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


def _recipient_is_ours(recipient, owner, session) -> bool:
    """Whether a call's payout lands somewhere the owner still controls.

    A swap that routes its output to a stranger, or a `collect` that pays fees to one, is
    inside every cap this policy sets and still empties the session: the cap bounds what
    goes in, not where the proceeds come out. So the destination is checked against the
    only two addresses that are not a loss.
    """
    if owner is None and session is None:
        return True
    destination = _checksum(recipient)
    return destination is not None and destination in {
        address for address in (_checksum(owner), _checksum(session)) if address
    }


def call_spend(
    call,
    *,
    token_allowlist=(),
    contract_allowlist=(),
    token_hints=None,
    owner=None,
    session=None,
) -> dict[str, int]:
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

    _, arguments = _decoder.decode_function_input(call.data)

    if selector in WITHDRAWING_SELECTORS:
        # Nothing is spent, but something is received, and a `collect` naming a stranger
        # as its recipient hands the fees straight out of the session.
        if selector == NPM_COLLECT and not _recipient_is_ours(
            arguments["params"]["recipient"], owner, session
        ):
            raise UnmeasuredSpend(
                f"this collect pays out to {arguments['params']['recipient']}, which is "
                "neither the session nor the owner"
            )
        return {}

    if selector == APPROVE:
        # WHO is being authorised matters as much as how much. An approval is a standing
        # licence to pull, and one granted to an address the session may not even call is
        # a spend that leaves entirely outside every check this module makes: the pull
        # happens later, from somebody else's transaction, and nothing here ever sees it.
        spender = _checksum(arguments["spender"])
        allowed = {
            checksummed
            for checksummed in (_checksum(item) for item in contract_allowlist)
            if checksummed is not None
        }
        if target is None:
            raise UnmeasuredSpend(f"{call.to!r} is not a token address")
        if allowed and spender not in allowed:
            raise UnmeasuredSpend(
                f"this approval authorises {arguments['spender']} to pull "
                f"{arguments['amount']} of {call.to}, and that address is not in the "
                "policy's contract allowlist: the pull would happen in somebody else's "
                "transaction, where no cap of ours applies"
            )
        return _nonzero({target: int(arguments["amount"])})

    if selector == TRANSFER:
        if target is None:
            raise UnmeasuredSpend(f"{call.to!r} is not a token address")
        if not _recipient_is_ours(arguments["to"], owner, session):
            raise UnmeasuredSpend(
                f"this transfer sends {arguments['amount']} of {call.to} to "
                f"{arguments['to']}, which is neither the session nor the owner"
            )
        return _nonzero({target: int(arguments["amount"])})

    if selector == SWAP_EXACT_TOKENS_FOR_TOKENS:
        path = arguments["path"]
        if not path:
            raise UnmeasuredSpend("a swap with an empty path spends an unnamed token")
        if not _recipient_is_ours(arguments["to"], owner, session):
            raise UnmeasuredSpend(
                f"this swap pays out to {arguments['to']}, which is neither the session "
                "nor the owner: its whole output would leave inside every cap"
            )
        return _nonzero({_checksum(path[0]): int(arguments["amountIn"])})

    if selector == EXACT_INPUT_SINGLE:
        params = arguments["params"]
        if not _recipient_is_ours(params["recipient"], owner, session):
            raise UnmeasuredSpend(
                f"this swap pays out to {params['recipient']}, which is neither the "
                "session nor the owner"
            )
        return _nonzero({_checksum(params["tokenIn"]): int(params["amountIn"])})

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
        # The owner, and not the session. A minted position is an ERC-721 and the sweep
        # returns fungible balances: a position minted to the session address would sit
        # behind a revoked key with nothing able to move it.
        if _checksum(params["recipient"]) != _checksum(owner) and owner is not None:
            raise UnmeasuredSpend(
                f"this mint sends the position to {params['recipient']}; a minted "
                "position must go to the owner, because the sweep cannot return an NFT"
            )
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


def received_tokens(call, *, token_hints=None) -> tuple[str, ...]:
    """Tokens this call pays INTO the session, read out of its own bytes.

    The allowlist bounds what a session may spend; it says nothing about what a session
    ends up holding. A swap's output side, and the two sides of a position being closed,
    arrive without ever being spendable — and a sweep that only looked at the spend side
    would leave them behind a revoked key for ever.
    """
    hints = token_hints or {}
    positions = {
        str(key): value for key, value in (hints.get("position_tokens") or {}).items()
    }
    selector = call.selector
    if selector not in MEASURED_SELECTORS:
        return ()
    _, arguments = _decoder.decode_function_input(call.data)
    if selector == SWAP_EXACT_TOKENS_FOR_TOKENS:
        path = arguments["path"]
        return (_checksum(path[-1]),) if path else ()
    if selector == EXACT_INPUT_SINGLE:
        return (_checksum(arguments["params"]["tokenOut"]),)
    if selector in WITHDRAWING_SELECTORS:
        pair = positions.get(str(arguments["params"]["tokenId"]))
        if not pair:
            return ()
        return tuple(token for token in (_checksum(item) for item in pair) if token)
    if selector in VTOKEN_SELECTORS:
        # A mint pays the session in vTokens; a repay can refund the over-payment in the
        # underlying and leaves the vToken position itself behind. Either way the vToken
        # is a balance the session can end up holding, and a sweep that never looked at it
        # would leave it behind a revoked key.
        return (_checksum(call.to),)
    return ()


def approval_granted(call, *, token_hints=None) -> tuple[str, str, int] | None:
    """The (token, spender, amount) an `approve` grants, or None for anything else.

    An approval is not a payment and is not charged as one, but it IS an exposure: until
    it is pulled or zeroed, that much of the token can leave without another transaction
    of ours. It is reserved against the lifetime cap, and released when the pull lands.
    """
    if call.selector != APPROVE:
        return None
    _, arguments = _decoder.decode_function_input(call.data)
    token = _checksum(call.to)
    spender = _checksum(arguments["spender"])
    if token is None or spender is None:
        return None
    return token, spender, int(arguments["amount"])


def batch_spend(
    calls,
    *,
    token_allowlist=(),
    contract_allowlist=(),
    token_hints=None,
    owner=None,
    session=None,
) -> dict[str, int]:
    """The whole batch's spend, so the total can be put to the cap once before any of it
    is sent. A batch refused halfway leaves a position half-rebalanced.

    An `approve` is an authorisation, not a payment, and the two are accumulated
    separately: spends are summed, approvals are taken at their maximum, and each token's
    total is the larger of the two. A migration route approves exactly what its mint will
    pull, so adding the approval to the mint would bill one movement twice and halve the
    cap; ignoring it would let a batch approve more than the session could ever cover.
    The exposure is whichever is bigger, and that is what the cap has to hold.
    """
    spends: dict[str, int] = {}
    approvals: dict[str, int] = {}
    for call in calls:
        derived = call_spend(
            call,
            token_allowlist=token_allowlist,
            contract_allowlist=contract_allowlist,
            token_hints=token_hints,
            owner=owner,
            session=session,
        )
        target = approvals if call.selector == APPROVE else spends
        for token, amount in derived.items():
            if call.selector == APPROVE:
                target[token] = max(target.get(token, 0), amount)
            else:
                target[token] = target.get(token, 0) + amount
        value = int(call.value_atomic)
        if value:
            spends[NATIVE_TOKEN] = spends.get(NATIVE_TOKEN, 0) + value
    return {
        token: max(spends.get(token, 0), approvals.get(token, 0))
        for token in set(spends) | set(approvals)
    }
