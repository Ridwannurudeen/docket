"""What each category's session is allowed to touch, in one place.

A browser cannot know which contracts a rebalancing session needs to call, and it should
not have to: the answer is a property of the work Docket does, not of the owner's
intentions. Asking a wallet to compose a `contract_allowlist` from memory is how an owner
ends up either unable to activate anything or pasting in an allowlist far wider than the
job needs.

So the defaults live here, keyed by category, and there is exactly one copy. The API
serves them at `GET /api/activations/policy-defaults`, `ActivationService.create` fills
them in where a body omits them, and **Lane D's executors import them rather than writing
the same addresses down again** — an executor whose target is not in the table its own
category publishes is a bug in one of the two, and a second copy would hide it.

Every address is imported from the module that already owns it rather than retyped. A
transposed digit in an allowlist is a session that silently cannot act, or one that can
act somewhere nobody meant.

The caps are deliberately small. They are a starting point an owner is expected to raise
knowingly, and the loss ceiling is the float — so the default is the amount somebody can
lose while they are still finding out whether this works.
"""

from web3 import Web3

from ...agents.pancake.positions import MASTER_CHEF_V3, NPM
from ...execution.simulate import PANCAKE_V2_ROUTER
from ...hire.catalogue import (
    GRID_BASE,
    USDT_TOKEN,
    VENUS_USDC,
    VENUS_USDT,
    VENUS_VUSDC,
    VENUS_VUSDT,
)
from ...sessions.policy import NATIVE_TOKEN

USDT = Web3.to_checksum_address(USDT_TOKEN)
WBNB = Web3.to_checksum_address(GRID_BASE)
USDC = Web3.to_checksum_address(VENUS_USDC)
VUSDT = Web3.to_checksum_address(VENUS_VUSDT)
VUSDC = Web3.to_checksum_address(VENUS_VUSDC)
VENUS_UNDERLYING = {
    VUSDT: Web3.to_checksum_address(VENUS_USDT),
    VUSDC: USDC,
}

# The selectors `docket.sessions.spend` can derive a spend from. A default allowlist may
# not name a function the session could send but nothing could measure.
APPROVE = "0x095ea7b3"
TRANSFER = "0xa9059cbb"
SWAP_EXACT_TOKENS_FOR_TOKENS = "0x38ed1739"
NPM_MINT = "0x88316456"
NPM_INCREASE_LIQUIDITY = "0x219f5d17"
NPM_DECREASE_LIQUIDITY = "0x0c49ccbe"
NPM_COLLECT = "0xfc6f7865"
VTOKEN_MINT = "0xa0712d68"
REPAY_BORROW = "0x0e752702"
REPAY_BORROW_BEHALF = "0x2608f818"

# 100 USDT an action against a 500 USDT session, 1 WBNB against 5, and 0.01 BNB of gas an
# action against 0.1 for the session's life. Small on purpose: see the module docstring.
_USDT_CAPS = ("100000000000000000000", "500000000000000000000")
_WBNB_CAPS = ("1000000000000000000", "5000000000000000000")
_USDC_CAPS = ("100000000000000000000", "500000000000000000000")
_GAS_CAPS = ("10000000000000000", "100000000000000000")
# One percent, and five gwei. BSC has been settling under one gwei for months; five is
# headroom for a busy block rather than a licence to pay anything.
DEFAULT_MAX_SLIPPAGE_BPS = 100
DEFAULT_MAX_GAS_PRICE_WEI = "5000000000"


def _caps(*pairs):
    per_action = {token: caps[0] for token, caps in pairs}
    total = {token: caps[1] for token, caps in pairs}
    return per_action, total


def _policy(contracts, selectors, pairs):
    per_action, total = _caps(*pairs)
    return {
        "contract_allowlist": [Web3.to_checksum_address(a) for a in contracts],
        "function_allowlist": list(selectors),
        "token_allowlist": [token for token, _ in pairs],
        "per_action_limit_atomic": per_action,
        "total_cap_atomic": total,
        "max_slippage_bps": DEFAULT_MAX_SLIPPAGE_BPS,
        "max_gas_price_wei": DEFAULT_MAX_GAS_PRICE_WEI,
        "emergency_pause": False,
    }


# Keyed by BNB's four categories. `expires_at` is deliberately absent from every entry:
# how long a session may run is the one bound only the owner can set, and a default there
# would be Docket choosing how long to hold somebody's money.
CATEGORY_POLICY_DEFAULTS: dict[str, dict] = {
    "rebalancing": _policy(
        (NPM, MASTER_CHEF_V3, PANCAKE_V2_ROUTER, USDT, WBNB),
        (
            APPROVE,
            SWAP_EXACT_TOKENS_FOR_TOKENS,
            NPM_MINT,
            NPM_INCREASE_LIQUIDITY,
            NPM_DECREASE_LIQUIDITY,
            NPM_COLLECT,
        ),
        ((USDT, _USDT_CAPS), (WBNB, _WBNB_CAPS), (NATIVE_TOKEN, _GAS_CAPS)),
    ),
    "grid_trading": _policy(
        (PANCAKE_V2_ROUTER, USDT, WBNB),
        (APPROVE, SWAP_EXACT_TOKENS_FOR_TOKENS),
        ((USDT, _USDT_CAPS), (WBNB, _WBNB_CAPS), (NATIVE_TOKEN, _GAS_CAPS)),
    ),
    "yield_optimisation": _policy(
        (PANCAKE_V2_ROUTER, USDT, WBNB),
        (APPROVE, TRANSFER, SWAP_EXACT_TOKENS_FOR_TOKENS),
        ((USDT, _USDT_CAPS), (WBNB, _WBNB_CAPS), (NATIVE_TOKEN, _GAS_CAPS)),
    ),
    "health_factor": _policy(
        (VUSDT, VUSDC, USDT, USDC),
        (APPROVE, VTOKEN_MINT, REPAY_BORROW, REPAY_BORROW_BEHALF),
        ((USDT, _USDT_CAPS), (USDC, _USDC_CAPS), (NATIVE_TOKEN, _GAS_CAPS)),
    ),
}

# The lists a browser cannot compose for itself. Named rather than inferred, because these
# are exactly the three `SessionPolicy.validate` refuses to leave empty.
FILLABLE_FIELDS = ("contract_allowlist", "function_allowlist", "token_allowlist")


def defaults_for(category: str) -> dict:
    """The policy skeleton for one category. Raises for a category Docket does not run."""
    try:
        return {
            key: (list(value) if isinstance(value, list) else dict(value))
            if isinstance(value, (list, dict))
            else value
            for key, value in CATEGORY_POLICY_DEFAULTS[category].items()
        }
    except KeyError:
        raise KeyError(category) from None


def token_hints_for(category: str) -> dict:
    """The two facts no calldata carries, for the contracts these defaults allow.

    Venus amounts are denominated in a vToken's underlying and the vToken does not say so
    in its calldata. Supplying it here means the executor does not have to, and the tick
    does not have to spend a chain read discovering it.
    """
    if category == "health_factor":
        return {"underlying": dict(VENUS_UNDERLYING)}
    return {}
