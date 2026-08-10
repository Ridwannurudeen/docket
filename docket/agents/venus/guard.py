"""The Health Guard: what Venus published, what was derived from it, and by what formula.

The category this fills is called "health factor monitoring", and the shortest way to fill
it dishonestly is to print a number under that heading. **Venus publishes no health
factor.** Its comptroller answers `(error, liquidity, shortfall)` in 1e18-scaled USD and
nothing else about an account's condition. So this module does two separable things and
keeps them visibly separate: it repeats Venus's own figures verbatim under `venus`, and it
derives a collateral ratio under a key that says it is derived, with the formula, the
scales and the originating call for every input written into the output beside it.

The derivation is also checked against the protocol rather than merely asserted. Weighted
collateral minus borrows is the same quantity Venus publishes as liquidity minus
shortfall, so the two are computed independently and the gap between them is reported. A
difference that is not zero is the number a reader should distrust, and it is printed
rather than smoothed.

**Three things this module refuses.**

*It never claims a counterfactual.* A liquidation that did not happen is not an outcome
anybody observed. Nothing here says a position was made safer or that anything was
avoided; it says Venus reported a shortfall of X at block B, and that repaying Y retires Y
of borrow balance. `BANNED_CLAIMS` is scanned over every string the preview emits.

*It builds repay and supply-collateral actions and no others.* Borrowing and withdrawing
both make a position more liquidatable. There is no argument to any function below that
produces one — the module encodes two selectors and a test asserts the set.

*It cannot send anything.* There is no armed Venus operator in this build. `HealthGuardPreview`
holds a reader and a policy, and no sibling class exists that holds a session or a signer,
so unlike the grid there is not even a second class to be constructed by mistake. Acting on
any of these intents needs an execution path this stage did not build.

**Why `min_output` means two different things here.** The kernel's floor is "the least that
must come back", written for a swap. Supplying collateral is close enough — `mint` really
does return vTokens, and the floor is derived from the exchange rate with a haircut,
because in normal operation that rate only rises and so vTokens-per-unit only falls between
drafting and landing. Repaying returns nothing at all: `repayBorrow(amount)` is a call to
retire `amount` of borrow balance that hands back no token. The floor on a repay is
therefore the debt retired, `min_output == max_input`, and every repay action carries
`output_means` saying so in those words. A field that reads as a payout when it is a debit
is worth one sentence per action.

**And neither floor is enforced by the chain.** This is the half of the kernel's property
that does not survive the move off a router. A swap carries its floor in the calldata, so
the router itself reverts a trade that would land under it; Venus offers no such mechanism
to either of these calls. `mint` takes no minimum-out argument at all, and `repayBorrow`
caps the amount at what is owed rather than reverting — so a repay drafted for `amount` can
be mined successfully having retired less, if the debt shrank in between. Both calls also
signal failure by returning an error code rather than reverting, which means a confirmed
transaction is not by itself evidence that anything happened. These floors are commitments
recorded on the intent and checkable against the next account snapshot; they are not bounds
the chain will hold anyone to, and each action says so in its own words. A reader who
learned `min_output` on the grid would otherwise carry the enforcement across with the name.
"""

from dataclasses import dataclass

from web3 import Web3

from ...execution import now
from ...execution.intent import ActionIntent, Condition, commit

POLICY_VERSION = "health-guard/1"
# 0.5%, the grid's own default. Here it is not slippage in a pool: it is the haircut on a
# vToken floor, absorbing the exchange rate's drift between the draft and the block the
# mint lands in.
DEFAULT_SLIPPAGE_BPS = 50
# A Compound-V2 mint or repay is well under this. A ceiling, not an estimate.
DEFAULT_GAS_CEILING = 400_000
DEFAULT_DEADLINE_S = 600
E18 = 10**18

REPAY_SIGNATURE = "repayBorrow(uint256)"
MINT_SIGNATURE = "mint(uint256)"
REPAY_SELECTOR = "0x" + Web3.keccak(text=REPAY_SIGNATURE)[:4].hex()
MINT_SELECTOR = "0x" + Web3.keccak(text=MINT_SIGNATURE)[:4].hex()
# The two write functions this module encodes, and the whole of its write surface. Both
# take one uint256 and return an error code; neither is quoted, because Venus is not a
# router and there is no view call that answers "what would this return".
WRITE_ABI = [
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
]
_encoder = Web3().eth.contract(abi=WRITE_ABI)

# The vocabulary of a claim about something that did not happen. Scanned over every string
# the preview emits, in addition to the project-wide verdict ban.
BANNED_CLAIMS = frozenset({"prevented", "prevent", "safe", "safer", "protected", "protect"})

# The closed status vocabulary. Five, not the three the plan named: an account that
# supplies and owes nothing is the commonest state a lender is in and belongs to none of
# the other four, and an account whose snapshot the chain refused to answer is a failure
# rather than a position.
STATUSES = {
    "no_position": "Venus reports no entered market and no balance for this address.",
    "supplied_no_borrow": (
        "Supplied into at least one market and owes nothing. There is no ratio to state, "
        "because nothing is owed to divide the collateral by."
    ),
    "borrowing_with_headroom": (
        "Borrowing, and the comptroller reports liquidity rather than shortfall — more "
        "could be borrowed against this collateral at this block."
    ),
    "shortfall": (
        "The comptroller reports a shortfall, which is the state in which this account is "
        "liquidatable now. It is Venus's own figure and not an estimate of one."
    ),
    "unreadable": (
        "At least one of the calls behind this state returned a nonzero error code, so the "
        "balances beside it describe nothing and are not interpreted."
    ),
}
RATIO_METHOD = (
    "collateral_ratio = weighted_collateral / borrowed, both in 1e18-scaled USD, computed "
    "here and not read from Venus — Venus publishes no such figure. Per market entered: "
    "weighted_collateral += vtoken_balance x exchange_rate / 1e18 x price / 1e18 x "
    "collateralFactor / 1e18, and borrowed += borrow_balance x price / 1e18. "
    "vtoken_balance, borrow_balance and exchange_rate come from vToken.getAccountSnapshot, "
    "collateralFactor from comptroller.markets, price from oracle.getUnderlyingPrice on the "
    "oracle comptroller.oracle names, and the set of markets from comptroller.getAssetsIn. "
    "Integer division throughout, truncating. A result below 1e18 means the weighted "
    "collateral no longer covers the debt."
)
NO_RATIO = (
    "No ratio is stated: nothing is owed, so there is no denominator. A collateral ratio "
    "over zero debt is not a large number, it is not a number."
)
CROSS_CHECK_METHOD = (
    "weighted_collateral - borrowed, derived here, against liquidity - shortfall, which is "
    "the same quantity the comptroller publishes. They are computed from the same inputs by "
    "two different parties, so the gap between them is what says whether the derived ratio "
    "can be leaned on. exactly_equal compares them for exact equality and nothing else — "
    "there is no tolerance here, because a tolerance is a judgement about how much "
    "disagreement is acceptable and this record does not make one. Read difference_usd "
    "against the two magnitudes printed beside it: three truncating integer divisions per "
    "market, in an order that need not match the comptroller's, put the last few units of "
    "1e-18 USD beyond reach, and the two reads can also land at different blocks. A "
    "difference of that size is arithmetic; a difference near the magnitudes themselves is "
    "a reason to distrust the ratio."
)
PREVIEW_REASON = (
    "This is a preview. It holds no session, no signer and no submitter, and there is no "
    "method on it that sends anything — and unlike the grid there is no armed counterpart "
    "class in this build at all. Acting on any of these needs an execution path this stage "
    "did not build, on top of a session the wallet's owner grants on chain."
)
ROUTER_NOT_APPLICABLE = (
    "No router quote was taken and none applies: a repay or a mint is a call to Venus, not "
    "a swap, and PancakeSwap's router has no answer about either. The checks that did run "
    "are listed beside this."
)
ACTION_NOTE = (
    "What an action of this kind does, exactly: it changes a balance Venus holds, at the "
    "block it lands in. It does not establish that a liquidation would otherwise have "
    "happened, because that is a claim about a world nobody observed. Whether the shortfall "
    "figure moves, and by how much, is arithmetic Venus performs at the next read — and the "
    "next read is a different observation from this one."
)


def repay_calldata(amount: int) -> bytes:
    return _abi("repayBorrow", amount)


def mint_calldata(amount: int) -> bytes:
    return _abi("mint", amount)


def _abi(name: str, amount: int) -> bytes:
    return bytes.fromhex(_encoder.encode_abi(name, args=[int(amount)])[2:])


@dataclass(frozen=True)
class MarketPolicy:
    """What the guard may do in one Venus market, in atomic units of its underlying.

    The underlying is named here rather than looked up, because it becomes the intent's
    `token_in` and is what an approval and a transfer would be denominated in. A lookup
    that returned the wrong address would draft an action paying the right contract in the
    wrong asset; naming it makes the policy author state it, and `HealthGuardPreview` reads
    the vToken's own `underlying()` and refuses where the two disagree.

    A cap of zero is not a permission of zero size — it means that action is not permitted
    in this market at all, which is how a policy allows repaying one asset without allowing
    the guard to supply it.
    """

    vtoken: str
    underlying: str
    max_repay: int = 0
    max_supply: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(self, "vtoken", Web3.to_checksum_address(self.vtoken))
        object.__setattr__(self, "underlying", Web3.to_checksum_address(self.underlying))
        for name in ("max_repay", "max_supply"):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise ValueError(
                    f"{self.vtoken}: {name} must be a whole number of atomic units, got {value!r}"
                )


@dataclass(frozen=True)
class GuardPolicy:
    """Everything the guard may do, bounded before it has looked at an account."""

    markets: tuple[MarketPolicy, ...]
    trigger_shortfall_usd: int
    slippage_bps: int = DEFAULT_SLIPPAGE_BPS
    gas_ceiling: int = DEFAULT_GAS_CEILING
    deadline_s: int = DEFAULT_DEADLINE_S
    version: str = POLICY_VERSION

    def __post_init__(self) -> None:
        if not self.markets:
            raise ValueError("a policy naming no market permits nothing and is not a policy")
        if not isinstance(self.trigger_shortfall_usd, int) or self.trigger_shortfall_usd <= 0:
            raise ValueError(
                "trigger_shortfall_usd must be a positive 1e18-scaled figure: a trigger of "
                "zero is a condition that holds of every account including one that owes "
                "nothing due, so the guard would draft a repay against a healthy position"
            )
        if not any(m.max_repay or m.max_supply for m in self.markets):
            raise ValueError(
                "every market in this policy caps both actions at zero, so it permits "
                "nothing while reading as a granted policy"
            )

    def for_market(self, vtoken: str) -> MarketPolicy | None:
        vtoken = Web3.to_checksum_address(vtoken)
        return next((m for m in self.markets if m.vtoken == vtoken), None)

    def as_record(self) -> dict:
        return {
            "version": self.version,
            "trigger_shortfall_usd": str(self.trigger_shortfall_usd),
            "trigger_scale": "1e18 USD, the scale the comptroller reports shortfall in",
            "slippage_bps": self.slippage_bps,
            "gas_ceiling": self.gas_ceiling,
            "markets": [
                {
                    "vtoken": m.vtoken,
                    "underlying": m.underlying,
                    "max_repay": str(m.max_repay),
                    "max_supply": str(m.max_supply),
                }
                for m in self.markets
            ],
        }


@dataclass(frozen=True)
class GuardAction:
    """One drafted action, with the sentence the kernel's own record cannot carry.

    `ActionIntent` is a fixed set of bounds and has nowhere to say what a bound means in a
    context it was not written for. That is what `output_means` and `bound_by` are: the
    reinterpretation of `min_output` on a repay, and what actually decided the size.
    """

    intent: ActionIntent
    calldata: bytes
    kind: str
    output_means: str
    bound_by: str
    checks: tuple[str, ...]

    def as_record(self) -> dict:
        return {
            "kind": self.kind,
            "intent": self.intent.as_record(),
            "intent_key": self.intent.idempotency_key,
            "calldata": "0x" + self.calldata.hex(),
            "output_means": self.output_means,
            "bound_by": self.bound_by,
            "checks": list(self.checks),
            "router_simulation": ROUTER_NOT_APPLICABLE,
            "note": ACTION_NOTE,
        }


def _usd(atomic: int, price_mantissa: int) -> int:
    """One balance in 1e18-scaled USD.

    The oracle prices an underlying at 1e(36 − its decimals), so multiplying an atomic
    balance by it and dividing by 1e18 lands on 1e18 whatever the token's decimals are.
    That cancellation is why nothing in this package reads an underlying's decimals.
    """
    return atomic * price_mantissa // E18


def _supplied_underlying(row) -> int:
    """vToken balance turned into the underlying it is a claim on, at the stored rate."""
    return row.vtoken_balance * row.exchange_rate_mantissa // E18


def assess(state) -> dict:
    """Venus's own answer, the ratio derived from it, and the formula that derived it."""
    weighted = 0
    borrowed = 0
    for row in state.rows:
        weighted += (
            _usd(_supplied_underlying(row), row.underlying_price_mantissa)
            * row.collateral_factor_mantissa
            // E18
        )
        borrowed += _usd(row.borrow_balance, row.underlying_price_mantissa)

    if not state.complete:
        status = "unreadable"
    elif not state.rows or not (weighted or borrowed):
        status = "no_position"
    elif not borrowed:
        status = "supplied_no_borrow"
    elif state.shortfall_usd > 0:
        status = "shortfall"
    else:
        status = "borrowing_with_headroom"

    ratio = None
    method = NO_RATIO
    if status in ("shortfall", "borrowing_with_headroom"):
        ratio = str(weighted * E18 // borrowed)
        method = RATIO_METHOD

    derived_headroom = weighted - borrowed
    venus_headroom = state.liquidity_usd - state.shortfall_usd
    return {
        "address": state.address,
        "as_of_block": state.as_of_block,
        "status": status,
        "status_means": STATUSES[status],
        "status_vocabulary": sorted(STATUSES),
        "venus": {
            "liquidity_usd": str(state.liquidity_usd),
            "shortfall_usd": str(state.shortfall_usd),
            "error_code": state.error_code,
            "scale": "1e18 USD",
            "source": "comptroller.getAccountLiquidity",
            # The single most important field on this record. Venus answers liquidity and
            # shortfall and nothing else about an account's condition, and a reader coming
            # from Aave will assume otherwise unless told here.
            "publishes_health_factor": False,
            "publishes_note": (
                "Venus publishes liquidity and shortfall in USD. It does not publish a "
                "health factor, and no call in this package returns one. The ratio beside "
                "this was computed here from the inputs its method names."
            ),
        },
        "weighted_collateral_usd": str(weighted),
        "borrowed_usd": str(borrowed),
        "collateral_ratio": ratio,
        "collateral_ratio_scale": "1e18",
        "collateral_ratio_method": method,
        "collateral_ratio_is_derived": True,
        "cross_check": {
            "derived_headroom_usd": str(derived_headroom),
            "venus_headroom_usd": str(venus_headroom),
            "difference_usd": str(abs(derived_headroom - venus_headroom)),
            # `exactly_equal` rather than `agrees`, because the two are different claims
            # and only this one is checkable without a judgement. A live account read on
            # 2026-08-10 came back 245 units of 1e-18 USD apart on a headroom of 1.2e11 —
            # truncation, and a field called `agrees` would have reported that correct
            # derivation as a disagreement.
            "exactly_equal": derived_headroom == venus_headroom,
            "method": CROSS_CHECK_METHOD,
        },
    }


def plan_actions(state, policy: GuardPolicy) -> list[GuardAction]:
    """Repay and supply-collateral drafts for an account Venus reports a shortfall for.

    Nothing is drafted for any other status. A shortfall is Venus's own statement that the
    account is liquidatable at this block, and it is the only observation this build treats
    as grounds for an action — an account with headroom has nothing due, and drafting for
    it would be the guard inventing urgency.

    Both actions are drafted only into markets the account has already entered, because
    those are the only rows there are. That is the conservative answer rather than a
    limitation worked around: supplying into a market the account has not entered adds no
    collateral until `enterMarkets` is called, and calling it would be a third kind of
    action this build does not encode.
    """
    if state.shortfall_usd < policy.trigger_shortfall_usd or not state.complete:
        return []

    condition = Condition(
        kind="shortfall_at_or_above",
        subject=f"venus shortfall for {state.address}, 1e18 usd",
        threshold=policy.trigger_shortfall_usd,
    )
    deadline = now() + policy.deadline_s
    actions: list[GuardAction] = []
    for nonce, row in enumerate(state.rows):
        market = policy.for_market(row.vtoken)
        if market is None:
            continue
        if market.max_repay and row.borrow_balance:
            actions.append(_repay(row, market, policy, condition, deadline, state, nonce))
        if market.max_supply:
            actions.append(_supply(row, market, policy, condition, deadline, state, nonce))
    return actions


def _repay(row, market, policy, condition, deadline, state, nonce) -> GuardAction:
    """Retire borrow balance in one market, capped by the policy and by what is owed."""
    amount = min(market.max_repay, row.borrow_balance)
    bound_by = (
        f"the policy caps a repay in {row.symbol} at {market.max_repay} and the borrow "
        f"balance read at block {row.as_of_block} was {row.borrow_balance}; the smaller of "
        "the two is what this action commits"
    )
    calldata = repay_calldata(amount)
    intent = ActionIntent(
        intent_id=f"health-guard-{state.address[:10]}-repay-{row.symbol}-{nonce}",
        condition=condition,
        chain_id=56,
        target=row.vtoken,
        selector=REPAY_SELECTOR,
        calldata_hash=commit(calldata),
        token_in=market.underlying,
        # Nothing comes back from a repay, so the route is the one token in and the same
        # token out. Degenerate on purpose, and `output_means` says what the floor is.
        token_out=market.underlying,
        max_input=amount,
        min_output=amount,
        route=(market.underlying, market.underlying),
        slippage_bps=0,
        deadline=deadline,
        gas_ceiling=policy.gas_ceiling,
        nonce=nonce,
        policy_version=policy.version,
        evidence_block=state.as_of_block,
    )
    return GuardAction(
        intent=intent,
        calldata=calldata,
        kind="repay",
        output_means=(
            "min_output here is the borrow balance this call retires, not a token received: "
            f"repayBorrow({amount}) is a call to retire {amount} of debt in {row.symbol} "
            "that hands back nothing. The floor equals the input for that reason, and "
            "slippage_bps is zero because there is no price in this call to slip against. "
            "No chain mechanism enforces that floor, unlike a swap's: Venus caps a repay at "
            "what is owed rather than reverting, so if the debt shrank before this landed "
            f"the call succeeds having retired less than {amount}, and it signals failure by "
            "returning an error code rather than reverting. What was actually retired is "
            "read from the next account snapshot, not from the transaction succeeding."
        ),
        bound_by=bound_by,
        checks=(
            f"policy cap for {row.symbol}: {market.max_repay}",
            f"borrow balance at block {row.as_of_block}: {row.borrow_balance}",
            f"committed amount: {amount}",
            "calldata committed by keccak and re-checkable with intent.matches",
        ),
    )


def _supply(row, market, policy, condition, deadline, state, nonce) -> GuardAction:
    """Add collateral in one market. The floor is vTokens, haircut for a drifting rate."""
    amount = market.max_supply
    exact = amount * E18 // row.exchange_rate_mantissa
    floor = exact * (10_000 - policy.slippage_bps) // 10_000
    if floor <= 0:
        raise ValueError(
            f"supplying {amount} to {row.symbol} at the rate read at block "
            f"{row.as_of_block} mints {exact} vTokens, which leaves no floor once "
            f"{policy.slippage_bps}bps is allowed for the rate moving"
        )
    calldata = mint_calldata(amount)
    intent = ActionIntent(
        intent_id=f"health-guard-{state.address[:10]}-supply-{row.symbol}-{nonce}",
        condition=condition,
        chain_id=56,
        target=row.vtoken,
        selector=MINT_SELECTOR,
        calldata_hash=commit(calldata),
        token_in=market.underlying,
        token_out=row.vtoken,
        max_input=amount,
        min_output=floor,
        route=(market.underlying, row.vtoken),
        slippage_bps=policy.slippage_bps,
        deadline=deadline,
        gas_ceiling=policy.gas_ceiling,
        nonce=nonce,
        policy_version=policy.version,
        evidence_block=state.as_of_block,
    )
    return GuardAction(
        intent=intent,
        calldata=calldata,
        kind="supply_collateral",
        output_means=(
            f"min_output is the fewest {row.symbol} this mint may return. At the exchange "
            f"rate read at block {row.as_of_block} it would return {exact}; the floor is "
            f"{policy.slippage_bps}bps below that because in normal operation the rate only "
            "rises, so vTokens per unit supplied only falls between this draft and the block "
            "it lands in. Nothing on chain enforces that floor: Venus's mint takes no "
            "minimum-out argument and signals failure by returning an error code rather than "
            "reverting, so the floor is a commitment recorded here and checked against the "
            "next account snapshot, not a bound the call itself would revert against."
        ),
        bound_by=f"the policy caps a supply in {row.symbol} at {market.max_supply}",
        checks=(
            f"policy cap for {row.symbol}: {market.max_supply}",
            f"exchange rate at block {row.as_of_block}: {row.exchange_rate_mantissa}",
            f"vtokens at that rate: {exact}, floored at {floor}",
            "calldata committed by keccak and re-checkable with intent.matches",
        ),
    )


class HealthGuardPreview:
    """The whole guard, with nothing anywhere in this build that could send it.

    Deliberately the only class in this module. The grid ships a preview and an armed
    operator and keeps them apart structurally; this ships the preview alone, because no
    execution path for a Venus call exists here and a class that implied one would be
    describing work that has not been done.
    """

    def __init__(self, *, reader, policy: GuardPolicy) -> None:
        self._reader = reader
        self._policy = policy

    def preview(self, address: str) -> dict:
        """Read the account, assess it, draft what the policy permits, send nothing.

        The policy's underlyings are checked against each vToken's own `underlying()`
        before anything is drafted. `token_in` comes from the policy, so a policy naming
        the wrong token would produce an action paying the right contract in the wrong
        asset — and that is a mistake no later bound would catch.
        """
        for market in self._policy.markets:
            on_chain = self._reader.underlying_of(market.vtoken)
            if on_chain is None or Web3.to_checksum_address(on_chain) != market.underlying:
                raise ValueError(
                    f"policy market {market.vtoken} names {market.underlying} as its "
                    f"underlying and the vToken's own underlying() answers {on_chain}. An "
                    "action drafted from this would pay the right contract in the wrong "
                    "asset, so nothing is drafted."
                )

        state = self._reader.account(address)
        actions = plan_actions(state, self._policy)
        return {
            "address": state.address,
            "account": state.as_record(),
            "assessment": assess(state),
            "policy": self._policy.as_record(),
            "actions": [action.as_record() for action in actions],
            "submitted": False,
            "why_not_submitted": PREVIEW_REASON,
            "note": ACTION_NOTE,
        }
