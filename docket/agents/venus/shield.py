"""The Health Shield: the smallest remedy that restores a ratio, and the calls that make it.

`guard.py` reads a Venus account and drafts capped actions. The Shield asks the narrower
question a persistent hire has to answer: not "what may be done here" but "what is the
least that has to be done, right now, for this account's derived collateral ratio to be
back above the line its owner drew". The answer is one amount in one market, with the
integer arithmetic that produced it and the ratio recomputed after it.

**Venus publishes no health factor.** The category is named after one; the protocol does
not have one. Every figure below is Docket's own `collateral_ratio`, derived by the
formula stated in `docket/agents/venus/guard.py` (`RATIO_METHOD`) from
`vToken.getAccountSnapshot`, `comptroller.markets` and `oracle.getUnderlyingPrice`.
`min_health_factor` appears in the output only as an alias of `min_collateral_ratio`,
because that is the name a buyer arrives with, and it travels with the sentence saying
what it actually is.

**Nothing here signs or sends.** The module builds bytes and hands them back. There is no
key, no signer and no submitter in it, and no method that puts a transaction on a wire.

**Two remedies, and only one of them can be done for somebody else.**
`repayBorrowBehalf(address borrower, uint256 repayAmount)` exists precisely so a third
party can retire another account's debt: the payer supplies the tokens, the borrower's
balance falls. Supplying collateral has no such form. `mint(uint256)` credits the
*caller* with vTokens, so a session calling it would be buying vTokens for itself while
the borrower's collateral stayed exactly where it was — the borrower would be no better
off and the session's funds would be gone. So a collateral add is offered as an
owner-signed call only, and says why in the call's own purpose.

**Signature evidence for `repayBorrowBehalf`, read 2026-09-03.**

  * Source: Venus Protocol, `contracts/Tokens/VTokens/VBep20.sol` —
    `function repayBorrowBehalf(address borrower, uint repayAmount) external returns (uint)`,
    documented as "Returns 0 on success, otherwise returns a failure code (see
    ErrorReporter.sol for details)".
    https://github.com/VenusProtocol/venus-protocol/blob/develop/contracts/Tokens/VTokens/VBep20.sol
  * Selector: `keccak256("repayBorrowBehalf(address,uint256)")[:4]` = `0x2608f818`,
    re-derived in `tests/test_venus_shield.py` rather than transcribed.
  * On chain: the selector is in the runtime bytecode of vUSDT
    `0xfD5840Cd36d94D7229439859C0112a4185BC0255` and of the implementation it delegates
    to, `0xCDfea50f7CECCB24Fe804657DB8E6c93b689941e`, read at BSC block 119,695,469
    (chain 56). An `eth_call` of `repayBorrowBehalf(0xe558...c946, 0)` against vUSDT at
    block 119,695,550 returned `uint256 0`, Venus's NO_ERROR — the function exists and
    executes rather than merely appearing in a dispatch table.
  * BscScan's `module=contract&action=getabi` V1 endpoint was tried first and answered
    "You are using a deprecated V1 endpoint"; the bytecode and the call above are the
    primary source used in its place, and are stronger than a published ABI.

**The native market is refused rather than mis-encoded.** vBNB
`0xA07c5b74C9B40447a954e1466938b865b6BBea36` does not carry `0x2608f818` at all. Its
form is `repayBorrowBehalf(address)`, selector `0xe5974619`, payable — the value travels
as BNB rather than as an ERC-20 argument, and `underlying()` on it returns no bytes.
Encoding the two-argument call against it would produce calldata the contract has no
function for. Both facts were read at BSC block 119,697,338.
"""

from dataclasses import dataclass
from datetime import datetime

from web3 import Web3

from ...jobs.executors.base import PreparedCall
from ...jobs.executors.allowlists import REPAY_BORROW_BEHALF, VTOKEN_MINT
from ...jobs.executors.bounds import APPROVE_ABI, BSC_CHAIN_ID, parse_expiry
from .guard import E18, RATIO_METHOD, _supplied_underlying, _usd

MODES = ("repay", "add_collateral", "either")
REPAY_BEHALF_SIGNATURE = "repayBorrowBehalf(address,uint256)"
MINT_SIGNATURE = "mint(uint256)"
# Compound-V2 calls are well under this. A ceiling, not an estimate, in the sense
# `guard.py` uses the word.
REPAY_GAS = 400_000
MINT_GAS = 400_000
APPROVE_GAS = 60_000

# The Venus Core Pool markets this build sizes a remedy in, each pair read from BSC
# mainnet at block 119,697,338 (chain 56, 2026-09-03) through `vToken.symbol()` and
# `vToken.underlying()`, and each confirmed to carry `repayBorrowBehalf(address,uint256)`
# in its runtime bytecode. A vToken outside this map is refused with its address named
# rather than sized against a guessed underlying: an approval drafted for the wrong token
# would pay the right contract in the wrong asset, and no later bound catches that.
UNDERLYING_BY_VTOKEN = {
    Web3.to_checksum_address("0xfD5840Cd36d94D7229439859C0112a4185BC0255"): (
        Web3.to_checksum_address("0x55d398326f99059fF775485246999027B3197955")
    ),
    Web3.to_checksum_address("0xecA88125a5ADbe82614ffC12D0DB554E2e2867C8"): (
        Web3.to_checksum_address("0x8AC76a51cc950d9822D68b83fE1Ad97B32Cd580d")
    ),
    Web3.to_checksum_address("0x95c78222B3D6e262426483D42CfA53685A67Ab9D"): (
        Web3.to_checksum_address("0xe9e7CEA3DedcA5984780Bafc599bD69ADd087D56")
    ),
    Web3.to_checksum_address("0x882C173bC7Ff3b7786CA16dfeD3DFFfb9Ee7847B"): (
        Web3.to_checksum_address("0x7130d2A12B9BCbFAe4f2634d864A1Ee1Ce3Ead9c")
    ),
    Web3.to_checksum_address("0xf508fCD89b8bd15579dc79A6827cB4686A3592c8"): (
        Web3.to_checksum_address("0x2170Ed0880ac9A755fd29B2688956BD959F933F8")
    ),
}
# vBNB, named so a refusal can say which market it is rather than only that it is unknown.
VBNB = Web3.to_checksum_address("0xA07c5b74C9B40447a954e1466938b865b6BBea36")

HEALTH_FACTOR_NOTE = (
    "min_health_factor is an alias of min_collateral_ratio and is offered under that name "
    "because it is the name a lender arrives with. Venus does not publish a health factor "
    "and no call in this package returns one. The figure is Docket's own collateral ratio, "
    "derived by the formula in docket/agents/venus/guard.py: " + RATIO_METHOD
)
REPAY_MEANS = (
    "repayBorrowBehalf(borrower, amount) retires amount of the borrower's debt in this "
    "market and hands back nothing. Venus caps a repay at what is owed rather than "
    "reverting, and signals failure by returning an error code rather than reverting, so a "
    "mined transaction is not by itself evidence of how much was retired — that is read "
    "from the next account snapshot."
)
COLLATERAL_MEANS = (
    "mint(amount) credits the caller with vTokens. There is no on-behalf form of it, so a "
    "session calling it would hold the vTokens itself while the borrower's collateral was "
    "unchanged. This call is therefore offered for the account owner to sign from their "
    "own wallet, and a session key is not permitted to send it."
)
POST_ACTION_MEANS = (
    "The post-action ratio is this module recomputing its own formula over the same rows "
    "with one balance changed. It is arithmetic about a state nobody has observed yet, not "
    "a reading of one, and Venus performs its own at the block any remedy lands in."
)
NATIVE_REFUSAL = (
    "the native market vBNB carries repayBorrowBehalf(address) rather than "
    "repayBorrowBehalf(address,uint256): the amount travels as BNB value, underlying() "
    "returns no bytes, and the two-argument calldata this module builds names a function "
    "that market does not have"
)

_erc20_encoder = Web3().eth.contract(abi=APPROVE_ABI)
VTOKEN_WRITE_ABI = [
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
        "name": "mint",
        "type": "function",
        "stateMutability": "nonpayable",
        "inputs": [{"name": "mintAmount", "type": "uint256"}],
        "outputs": [{"name": "", "type": "uint256"}],
    },
]
_vtoken_encoder = Web3().eth.contract(abi=VTOKEN_WRITE_ABI)


def selector(signature: str) -> str:
    return "0x" + Web3.keccak(text=signature)[:4].hex()


# Derived here, published in `docket/jobs/executors/allowlists.py` as the selectors a Venus
# session's default `function_allowlist` grants, and checked against each other at import.
assert selector(REPAY_BEHALF_SIGNATURE) == REPAY_BORROW_BEHALF, REPAY_BEHALF_SIGNATURE
assert selector(MINT_SIGNATURE) == VTOKEN_MINT, MINT_SIGNATURE


def _ceil_div(numerator: int, denominator: int) -> int:
    """Ceiling of a division of whole numbers, without touching a float.

    Every remedy below is sized by this rather than by rounding, because a remedy rounded
    down is one that lands a unit short of the line it was computed to clear.
    """
    return -((-numerator) // denominator)


@dataclass(frozen=True)
class ShieldPolicy:
    """What the owner permitted, before anybody looked at the account.

    `min_collateral_ratio` is a multiple of the debt, 1.0 being the point at which the
    weighted collateral exactly covers it. `max_rescue_atomic` is keyed by underlying
    token address in that token's own atomic units, because that is what an approval and a
    transfer are denominated in.
    """

    min_collateral_ratio: float
    max_rescue_atomic: dict[str, int]
    allowed_vtokens: tuple[str, ...]
    mode: str
    expires_at: str

    def validate(self) -> None:
        if (
            not isinstance(self.min_collateral_ratio, (int, float))
            or isinstance(self.min_collateral_ratio, bool)
            or self.min_collateral_ratio <= 0
        ):
            raise ValueError(
                "min_collateral_ratio must be a positive multiple of the debt"
            )
        if self.mode not in MODES:
            raise ValueError(f"mode must be one of {list(MODES)}, got {self.mode!r}")
        if not self.allowed_vtokens:
            raise ValueError(
                "a policy naming no vToken permits nothing while reading as a granted policy"
            )
        for vtoken in self.allowed_vtokens:
            address = Web3.to_checksum_address(vtoken)
            if address not in UNDERLYING_BY_VTOKEN:
                reason = (
                    NATIVE_REFUSAL
                    if address == VBNB
                    else (
                        "it is not one of the Venus Core Pool markets this build read an "
                        f"underlying for ({sorted(UNDERLYING_BY_VTOKEN)})"
                    )
                )
                raise ValueError(f"vToken {address} cannot be sized against: {reason}")
        if not self.max_rescue_atomic:
            raise ValueError(
                "max_rescue_atomic caps nothing, so no remedy could be sized under it"
            )
        for token, cap in self.max_rescue_atomic.items():
            Web3.to_checksum_address(token)
            if not isinstance(cap, int) or isinstance(cap, bool) or cap <= 0:
                raise ValueError(
                    f"{token}: max_rescue_atomic must be a positive whole number of atomic "
                    f"units, got {cap!r}"
                )
        parse_expiry(self.expires_at)

    def cap_for(self, underlying: str) -> int | None:
        wanted = Web3.to_checksum_address(underlying)
        for token, cap in self.max_rescue_atomic.items():
            if Web3.to_checksum_address(token) == wanted:
                return cap
        return None

    def as_record(self) -> dict:
        return {
            "min_collateral_ratio": self.min_collateral_ratio,
            "min_collateral_ratio_scale": "1e18 when compared against the derived ratio",
            "min_health_factor": self.min_collateral_ratio,
            "min_health_factor_note": HEALTH_FACTOR_NOTE,
            "publishes_health_factor": False,
            "max_rescue_atomic": {
                Web3.to_checksum_address(token): str(cap)
                for token, cap in self.max_rescue_atomic.items()
            },
            "allowed_vtokens": [
                Web3.to_checksum_address(v) for v in self.allowed_vtokens
            ],
            "mode": self.mode,
            "expires_at": self.expires_at,
        }


@dataclass(frozen=True)
class ShieldDecision:
    """What the shield concluded, the least remedy that clears the line, and the workings.

    `remedy` is `None` on every `noop` and on an `alert` that could size nothing. It is
    populated on an `alert` that sized a remedy the policy would not permit, so a reader
    sees the amount that was refused rather than only that something was.
    """

    kind: str
    summary: str
    evidence: dict
    remedy: dict | None


def _totals(state) -> tuple[int, int]:
    """Weighted collateral and borrows in 1e18 USD, by `guard.assess`'s own arithmetic."""
    weighted = 0
    borrowed = 0
    for row in state.rows:
        weighted += (
            _usd(_supplied_underlying(row), row.underlying_price_mantissa)
            * row.collateral_factor_mantissa
            // E18
        )
        borrowed += _usd(row.borrow_balance, row.underlying_price_mantissa)
    return weighted, borrowed


def _repay_remedy(
    state, policy: ShieldPolicy, target: int, weighted: int, borrowed: int
):
    """The smallest repay that lifts the derived ratio to `target`, in one market.

    Repaying reduces the denominator and leaves the numerator alone, so the borrow figure
    the account may carry at the target ratio is `weighted * 1e18 // target` — floored, so
    the resulting ratio lands at or above the target rather than a unit under it. The
    market is the largest allowed debt IN DOLLARS: a remedy split across markets is two
    transactions where one will do, and the largest debt is the one most likely to cover
    the whole shortfall on its own. Ranked by USD rather than by atomic balance, because
    atomic balances are not comparable across markets — 1 BTCB and 1 USDT are the same
    number and four orders of magnitude apart in value, so ranking on the raw figure would
    reach for the wrong market whenever the two prices differ.
    """
    allowed = {Web3.to_checksum_address(v) for v in policy.allowed_vtokens}
    candidates = [
        row
        for row in state.rows
        if row.borrow_balance > 0 and Web3.to_checksum_address(row.vtoken) in allowed
    ]
    if not candidates:
        return None, (
            "no market this account borrows in is named by the policy's allowed_vtokens"
        )
    candidates.sort(
        key=lambda row: (
            -_usd(row.borrow_balance, row.underlying_price_mantissa),
            row.vtoken,
        )
    )
    row = candidates[0]
    if row.underlying_price_mantissa <= 0:
        return (
            None,
            f"the oracle priced {row.symbol} at zero, so no amount can be sized",
        )

    permitted_borrow_usd = weighted * E18 // target
    needed_usd = borrowed - permitted_borrow_usd
    # `a * price // E18 >= needed_usd` holds exactly when `a * price >= needed_usd * E18`,
    # so the ceiling below is the least atomic amount that retires enough, with no slack.
    needed_atomic = _ceil_div(needed_usd * E18, row.underlying_price_mantissa)
    underlying = UNDERLYING_BY_VTOKEN[Web3.to_checksum_address(row.vtoken)]
    cap = policy.cap_for(underlying)
    limits = {
        "needed_atomic": needed_atomic,
        "borrow_balance": row.borrow_balance,
        "policy_cap": cap,
    }
    remedy = {
        "mode": "repay",
        "vtoken": Web3.to_checksum_address(row.vtoken),
        "symbol": row.symbol,
        "underlying": underlying,
        "amount_atomic": needed_atomic,
        "amount_usd": _usd(needed_atomic, row.underlying_price_mantissa),
        "needed_usd": needed_usd,
        "permitted_borrow_usd": permitted_borrow_usd,
        "underlying_price_mantissa": str(row.underlying_price_mantissa),
        "limits": {name: None if v is None else str(v) for name, v in limits.items()},
        "means": REPAY_MEANS,
    }
    remedy["post_action"] = _post_repay(weighted, borrowed, remedy["amount_usd"])
    if cap is None:
        return remedy, (
            f"the policy sets no max_rescue_atomic for {underlying}, the underlying of "
            f"{row.symbol}"
        )
    if needed_atomic > row.borrow_balance:
        return remedy, (
            f"the smallest repay that reaches the target is {needed_atomic} atomic units "
            f"of {row.symbol}'s underlying and only {row.borrow_balance} is owed in that "
            "market, so no single-market repay reaches it"
        )
    if needed_atomic > cap:
        return remedy, (
            f"the smallest repay that reaches the target is {needed_atomic} atomic units "
            f"and the policy caps a rescue in {underlying} at {cap}"
        )
    return remedy, None


def _collateral_remedy(
    state, policy: ShieldPolicy, target: int, weighted: int, borrowed: int
):
    """The smallest collateral add that lifts the derived ratio to `target`, in one market.

    Adding collateral raises the numerator. A supply of `a` atomic units contributes
    `a * price // 1e18 * cf // 1e18` of weighted collateral, and each of those floors is
    inverted by a ceiling here, so the amount is the least that clears the line rather
    than the least that would clear it if nothing truncated. The market is the allowed one
    with the highest collateral factor, because that is the one where a unit supplied
    counts for most and so the remedy is smallest.
    """
    allowed = {Web3.to_checksum_address(v) for v in policy.allowed_vtokens}
    candidates = [
        row
        for row in state.rows
        if Web3.to_checksum_address(row.vtoken) in allowed
        and row.collateral_factor_mantissa > 0
        and row.underlying_price_mantissa > 0
    ]
    if not candidates:
        return None, (
            "no market this account has entered is both named by allowed_vtokens and "
            "priced with a collateral factor above zero, so supplying into one would add "
            "no weighted collateral"
        )
    candidates.sort(key=lambda row: (-row.collateral_factor_mantissa, row.vtoken))
    row = candidates[0]

    needed_weighted = _ceil_div(target * borrowed, E18) - weighted
    needed_usd = _ceil_div(needed_weighted * E18, row.collateral_factor_mantissa)
    needed_atomic = _ceil_div(needed_usd * E18, row.underlying_price_mantissa)
    underlying = UNDERLYING_BY_VTOKEN[Web3.to_checksum_address(row.vtoken)]
    cap = policy.cap_for(underlying)
    remedy = {
        "mode": "add_collateral",
        "vtoken": Web3.to_checksum_address(row.vtoken),
        "symbol": row.symbol,
        "underlying": underlying,
        "amount_atomic": needed_atomic,
        "amount_usd": _usd(needed_atomic, row.underlying_price_mantissa),
        "needed_weighted_usd": needed_weighted,
        "needed_usd": needed_usd,
        "collateral_factor_mantissa": str(row.collateral_factor_mantissa),
        "underlying_price_mantissa": str(row.underlying_price_mantissa),
        "limits": {
            "needed_atomic": str(needed_atomic),
            "policy_cap": None if cap is None else str(cap),
        },
        "means": COLLATERAL_MEANS,
    }
    remedy["post_action"] = _post_collateral(
        weighted,
        borrowed,
        _usd(needed_atomic, row.underlying_price_mantissa),
        row.collateral_factor_mantissa,
    )
    if cap is None:
        return remedy, (
            f"the policy sets no max_rescue_atomic for {underlying}, the underlying of "
            f"{row.symbol}"
        )
    if needed_atomic > cap:
        return remedy, (
            f"the smallest collateral add that reaches the target is {needed_atomic} "
            f"atomic units and the policy caps a rescue in {underlying} at {cap}"
        )
    return remedy, None


def _post_repay(weighted: int, borrowed: int, repaid_usd: int) -> dict:
    remaining = borrowed - repaid_usd
    return {
        "weighted_collateral_usd": str(weighted),
        "borrowed_usd": str(remaining),
        "collateral_ratio": None
        if remaining <= 0
        else str(weighted * E18 // remaining),
        "collateral_ratio_note": (
            "the whole debt is retired, so there is no denominator and no ratio"
            if remaining <= 0
            else None
        ),
        "means": POST_ACTION_MEANS,
    }


def _post_collateral(weighted: int, borrowed: int, added_usd: int, cf: int) -> dict:
    raised = weighted + added_usd * cf // E18
    return {
        "weighted_collateral_usd": str(raised),
        "borrowed_usd": str(borrowed),
        "collateral_ratio": None if borrowed <= 0 else str(raised * E18 // borrowed),
        "collateral_ratio_note": None,
        "means": POST_ACTION_MEANS,
    }


def evaluate(state, policy: ShieldPolicy, *, now: datetime) -> ShieldDecision:
    """The least remedy that lifts this account's derived ratio back over the line.

    Pure: `state` is a `markets.AccountState` and nothing here reads a chain, so every
    branch is reachable from a fixture.

    Four shapes of answer. An account that owes nothing has no ratio and nothing is due.
    An account already above the line is a `noop` carrying the ratio that says so. An
    account below it with a permitted remedy is an `action`. An account below it whose
    remedy the policy will not cover, or whose snapshot the chain refused to stand behind,
    is an `alert` — and the alert carries the amount that was refused.
    """
    policy.validate()
    weighted, borrowed = _totals(state)
    target = int(policy.min_collateral_ratio * E18)
    ratio = None if borrowed <= 0 else weighted * E18 // borrowed
    evidence = {
        "address": state.address,
        "as_of_block": state.as_of_block,
        "policy": policy.as_record(),
        "weighted_collateral_usd": str(weighted),
        "borrowed_usd": str(borrowed),
        "collateral_ratio": None if ratio is None else str(ratio),
        "collateral_ratio_scale": "1e18",
        "collateral_ratio_is_derived": True,
        "collateral_ratio_method": RATIO_METHOD,
        "target_ratio": str(target),
        "venus": {
            "liquidity_usd": str(state.liquidity_usd),
            "shortfall_usd": str(state.shortfall_usd),
            "error_code": state.error_code,
            "scale": "1e18 USD",
            "source": "comptroller.getAccountLiquidity",
            "publishes_health_factor": False,
            "publishes_note": HEALTH_FACTOR_NOTE,
        },
        "markets_entered": len(state.rows),
        "complete": state.complete,
    }

    if not state.complete:
        return ShieldDecision(
            kind="alert",
            summary=(
                f"At least one call behind {state.address}'s snapshot at block "
                f"{state.as_of_block} returned a nonzero error code, so the balances beside "
                "it describe nothing and no remedy is sized from them."
            ),
            evidence=evidence,
            remedy=None,
        )
    if borrowed <= 0:
        return ShieldDecision(
            kind="noop",
            summary=(
                f"{state.address} owes nothing in the markets it has entered at block "
                f"{state.as_of_block}, so there is no denominator, no ratio, and nothing due."
            ),
            evidence=evidence,
            remedy=None,
        )
    if ratio >= target:
        return ShieldDecision(
            kind="noop",
            summary=(
                f"{state.address}'s derived collateral ratio at block {state.as_of_block} "
                f"is {ratio / E18:.4f} against the {policy.min_collateral_ratio:.4f} the "
                "policy asks for, so no remedy is sized."
            ),
            evidence=evidence,
            remedy=None,
        )

    expiry = parse_expiry(policy.expires_at)
    if now >= expiry:
        return ShieldDecision(
            kind="alert",
            summary=(
                f"{state.address}'s derived collateral ratio at block {state.as_of_block} "
                f"is {ratio / E18:.4f}, below the {policy.min_collateral_ratio:.4f} the "
                f"policy asks for, and the policy expired at {policy.expires_at}."
            ),
            evidence=evidence,
            remedy=None,
        )

    remedy, refusal = _choose(state, policy, target, weighted, borrowed)
    evidence["remedy"] = remedy
    evidence["refusal"] = refusal
    shortfall = (
        f"{state.address}'s derived collateral ratio at block {state.as_of_block} is "
        f"{ratio / E18:.4f}, below the {policy.min_collateral_ratio:.4f} the policy asks for"
    )
    if refusal is not None or remedy is None:
        return ShieldDecision(
            kind="alert",
            summary=f"{shortfall}, and no remedy is offered: {refusal}.",
            evidence=evidence,
            remedy=remedy,
        )
    after = remedy["post_action"]["collateral_ratio"]
    lands = (
        "the whole debt is retired"
        if after is None
        else f"the ratio lands at {int(after) / E18:.4f}"
    )
    return ShieldDecision(
        kind="action",
        summary=(
            f"{shortfall}. The least remedy is a {remedy['mode'].replace('_', ' ')} of "
            f"{remedy['amount_atomic']} atomic units of {remedy['underlying']} against "
            f"{remedy['symbol']}, after which {lands}."
        ),
        evidence=evidence,
        remedy=remedy,
    )


def _choose(state, policy: ShieldPolicy, target: int, weighted: int, borrowed: int):
    """The remedy the policy's mode asks for, or both tried in order under `either`.

    Under `either` a repay is tried first. It is the only one of the two that a third
    party can perform for the borrower, so it is the remedy a bounded session can actually
    complete; a collateral add always ends at the owner's own signature.
    """
    if policy.mode == "repay":
        return _repay_remedy(state, policy, target, weighted, borrowed)
    if policy.mode == "add_collateral":
        return _collateral_remedy(state, policy, target, weighted, borrowed)
    remedy, refusal = _repay_remedy(state, policy, target, weighted, borrowed)
    if refusal is None:
        return remedy, None
    fallback, fallback_refusal = _collateral_remedy(
        state, policy, target, weighted, borrowed
    )
    if fallback_refusal is None:
        return fallback, None
    return remedy or fallback, f"{refusal}; and {fallback_refusal}"


def _unsimulated() -> dict:
    return {
        "ok": None,
        "gas_estimate": None,
        "revert_reason": None,
        "observed_at": None,
        "block": None,
    }


def rescue_calls(
    state, decision: ShieldDecision, *, session: str, borrower: str
) -> list[PreparedCall]:
    """The exact calls one remedy is made of. Signs nothing, sends nothing.

    A repay is two calls from the session: an exact ERC-20 approval of the vToken for the
    underlying, then `repayBorrowBehalf(borrower, amount)` on the vToken itself. The
    approval is for the exact amount and never unlimited, which is the rule the payment
    rail already follows.

    A collateral add is two calls the owner signs from their own wallet. `mint(uint256)`
    credits its caller, and there is no on-behalf form of it, so a session sending it
    would buy vTokens for itself and leave the borrower's collateral where it was. Both
    calls carry `purpose: "owner_signs"` for that reason, stated on the call rather than
    only in prose.
    """
    remedy = decision.remedy
    if remedy is None:
        raise ValueError(
            f"decision {decision.kind!r} sized no remedy, so there are no calls to build"
        )
    vtoken = Web3.to_checksum_address(remedy["vtoken"])
    underlying = UNDERLYING_BY_VTOKEN.get(vtoken)
    if underlying is None:
        reason = (
            NATIVE_REFUSAL
            if vtoken == VBNB
            else "it is not one of the Venus Core Pool markets this build read an underlying for"
        )
        raise ValueError(f"no calls can be built against vToken {vtoken}: {reason}")
    amount = int(remedy["amount_atomic"])
    if amount <= 0:
        raise ValueError("a remedy of zero atomic units is not a remedy")
    account = Web3.to_checksum_address(borrower)
    if account != Web3.to_checksum_address(state.address):
        raise ValueError(
            f"borrower {account} is not the account this state was read for "
            f"({state.address}); calldata built from the two would name different accounts"
        )
    # The session is the address expected to hold the underlying and send the two calls
    # below. It appears in none of the calldata, which is exactly why it is checked here:
    # a malformed session address would otherwise surface only when the transaction was
    # already built and about to be signed.
    payer_address = Web3.to_checksum_address(session)
    if payer_address == account and remedy["mode"] == "repay":
        raise ValueError(
            f"the session address is the borrower {account}; repayBorrowBehalf exists to "
            "let a third party retire somebody else's debt, and an account repaying itself "
            "through it is repayBorrow with an extra argument"
        )
    payer = "owner_signs" if remedy["mode"] == "add_collateral" else "session"
    approve = PreparedCall(
        to=underlying,
        data=_erc20_encoder.encode_abi("approve", args=[vtoken, amount]),
        value_atomic="0",
        chain_id=BSC_CHAIN_ID,
        gas_ceiling=APPROVE_GAS,
        deadline=0,
        purpose=(
            "owner_signs" if payer == "owner_signs" else "session_approves_vtoken_exact"
        ),
        simulation=_unsimulated(),
    )
    if remedy["mode"] == "repay":
        return [
            approve,
            PreparedCall(
                to=vtoken,
                data=_vtoken_encoder.encode_abi(
                    "repayBorrowBehalf", args=[account, amount]
                ),
                value_atomic="0",
                chain_id=BSC_CHAIN_ID,
                gas_ceiling=REPAY_GAS,
                deadline=0,
                purpose="session_repays_on_behalf_of_borrower",
                simulation=_unsimulated(),
            ),
        ]
    return [
        approve,
        PreparedCall(
            to=vtoken,
            data=_vtoken_encoder.encode_abi("mint", args=[amount]),
            value_atomic="0",
            chain_id=BSC_CHAIN_ID,
            gas_ceiling=MINT_GAS,
            deadline=0,
            # `mint` credits its caller. A session sending it would hold the vTokens while
            # the borrower's collateral stayed where it was, so only the owner may send it.
            purpose="owner_signs",
            simulation=_unsimulated(),
        ),
    ]
