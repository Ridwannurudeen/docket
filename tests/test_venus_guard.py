"""The Health Guard, and the four things it is not allowed to say or do.

**It does not publish a health factor.** Venus does not have one. The guard derives a
collateral ratio and carries the formula and every input beside it, and a test asserts the
word never appears as a figure anywhere in the output.

**It never claims a counterfactual.** A liquidation that did not happen is not an
achievement anybody observed. The guard reports a state Venus published and an action that
changes a number, and the banned scan at the bottom of this file holds "prevented",
"safe" and "protected" out of every string it emits.

**It builds two kinds of action and no others.** Repay and supply-collateral. Borrowing
and withdrawing both make a position more liquidatable, and there is no argument to any
function here that produces one — asserted against the selectors, not against the prose.

**It cannot send anything.** There is no armed Venus operator in this build at all. The
preview holds no session, no signer and no submitter, and no sibling class exists that
does, so nothing here is one setting away from acting.
"""

import inspect
import re

import pytest
from web3 import Web3

from docket.agents.venus import guard as guard_module
from docket.agents.venus.guard import (
    BANNED_CLAIMS,
    MINT_SELECTOR,
    POLICY_VERSION,
    PREVIEW_REASON,
    REPAY_SELECTOR,
    GuardPolicy,
    HealthGuardPreview,
    MarketPolicy,
    assess,
    plan_actions,
)
from docket.agents.venus.markets import AccountState, MarketPosition
from docket.api.models import BANNED_FIELD_NAMES
from docket.execution.intent import ActionIntent

VUSDT = Web3.to_checksum_address("0xfD5840Cd36d94D7229439859C0112a4185BC0255")
VUSDC = Web3.to_checksum_address("0xecA88125a5ADbe82614ffC12D0DB554E2e2867C8")
USDT = Web3.to_checksum_address("0x55d398326f99059fF775485246999027B3197955")
USDC = Web3.to_checksum_address("0x8AC76a51cc950d9822D68b83fE1Ad97B32Cd580d")
ORACLE = Web3.to_checksum_address("0x6592b5DE802159F3E74B2486b091D11a8256ab8A")
HOLDER = Web3.to_checksum_address("0x429898ba0Fc5b9F1fF0a8f0BD1D6D3cB33B26DdD")
BLOCK = 115_174_800
FROZEN_NOW = 2_000_000_000
E18 = 10**18
# Live values, 2026-08-10: 8-decimal vTokens against 18-decimal underlyings, so the
# exchange rate is 1e28-scaled and the oracle price is 1e18-scaled.
USDC_RATE = 266_027_524_223_233_974_720_539_463
USDT_RATE = 264_313_571_779_695_838_956_523_484
CF_USDC = 825 * 10**15
CF_USDT = 800 * 10**15


@pytest.fixture(autouse=True)
def frozen_clock(monkeypatch):
    for module in ("docket.execution.intent", "docket.agents.venus.guard"):
        monkeypatch.setattr(f"{module}.now", lambda: FROZEN_NOW)


def _row(vtoken, *, symbol, cf, supplied=0, borrowed=0, rate, price=E18, error=0):
    return MarketPosition(
        vtoken=vtoken,
        symbol=symbol,
        collateral_factor_mantissa=cf,
        snapshot_error=error,
        vtoken_balance=supplied,
        borrow_balance=borrowed,
        exchange_rate_mantissa=rate,
        underlying_price_mantissa=price,
        as_of_block=BLOCK,
    )


def _state(*rows, liquidity=0, shortfall=0, error=0):
    return AccountState(
        address=HOLDER,
        error_code=error,
        liquidity_usd=liquidity,
        shortfall_usd=shortfall,
        markets_listed=52,
        rows=tuple(rows),
        oracle=ORACLE,
        as_of_block=BLOCK,
        reads=("eth_blockNumber", "comptroller.getAccountLiquidity"),
    )


# 40,000 atomic vUSDC supplied and 1,000 USDT owed, written out here rather than taken
# from the module, so the module's arithmetic is checked against a second computation.
SUPPLIED_VUSDC = 40_000 * 10**8
BORROWED_USDT = 1_000 * E18
COLLATERAL_USD = SUPPLIED_VUSDC * USDC_RATE // E18 * E18 // E18
WEIGHTED_USD = COLLATERAL_USD * CF_USDC // E18
BORROWED_USD = BORROWED_USDT * E18 // E18
SHORTFALL_USD = BORROWED_USD - WEIGHTED_USD


def _underwater(**overrides):
    fields = {
        "liquidity": 0,
        "shortfall": SHORTFALL_USD,
    }
    fields.update(overrides)
    return _state(
        _row(VUSDC, symbol="vUSDC", cf=CF_USDC, supplied=SUPPLIED_VUSDC, rate=USDC_RATE),
        _row(VUSDT, symbol="vUSDT", cf=CF_USDT, borrowed=BORROWED_USDT, rate=USDT_RATE),
        **fields,
    )


def _policy(**overrides):
    fields = {
        "markets": (
            MarketPolicy(vtoken=VUSDT, underlying=USDT, max_repay=200 * E18, max_supply=0),
            MarketPolicy(vtoken=VUSDC, underlying=USDC, max_repay=0, max_supply=500 * E18),
        ),
        "trigger_shortfall_usd": E18,
    }
    fields.update(overrides)
    return GuardPolicy(**fields)


# ------------------------------------------------------------------------- assess


def test_an_account_with_nothing_in_venus_is_reported_as_holding_nothing():
    out = assess(_state())
    assert out["status"] == "no_position"
    assert out["collateral_ratio"] is None
    assert out["as_of_block"] == BLOCK


def test_an_account_that_supplies_and_owes_nothing_has_a_status_of_its_own():
    """Neither "no position" nor "borrowing": the commonest state a supplier is in, and
    the one a three-value vocabulary would have had to file under a wrong label."""
    out = assess(
        _state(_row(VUSDC, symbol="vUSDC", cf=CF_USDC, supplied=SUPPLIED_VUSDC, rate=USDC_RATE))
    )
    assert out["status"] == "supplied_no_borrow"
    assert out["collateral_ratio"] is None
    assert "nothing is owed" in out["collateral_ratio_method"].lower()


def test_a_borrowing_account_venus_reports_headroom_for_is_reported_as_such():
    state = _state(
        _row(VUSDC, symbol="vUSDC", cf=CF_USDC, supplied=SUPPLIED_VUSDC, rate=USDC_RATE),
        _row(VUSDT, symbol="vUSDT", cf=CF_USDT, borrowed=10 * E18, rate=USDT_RATE),
        liquidity=WEIGHTED_USD - 10 * E18,
    )
    assert assess(state)["status"] == "borrowing_with_headroom"


def test_an_account_venus_reports_a_shortfall_for_is_reported_as_liquidatable_now():
    out = assess(_underwater())
    assert out["status"] == "shortfall"
    assert "liquidatable" in out["status_means"].lower()


def test_a_snapshot_the_chain_refused_to_answer_is_not_read_as_a_position():
    """A nonzero snapshot error means the balances beside it describe nothing. Reporting
    "no position" for that would be inventing an answer out of a failure."""
    out = assess(_state(_row(VUSDT, symbol="vUSDT", cf=CF_USDT, rate=USDT_RATE, error=9)))
    assert out["status"] == "unreadable"
    assert out["collateral_ratio"] is None


def test_venus_s_own_figures_travel_into_the_assessment_verbatim():
    out = assess(_underwater())
    assert out["venus"]["shortfall_usd"] == str(SHORTFALL_USD)
    assert out["venus"]["liquidity_usd"] == "0"
    assert out["venus"]["source"] == "comptroller.getAccountLiquidity"
    assert out["venus"]["publishes_health_factor"] is False


def test_the_derived_ratio_states_the_formula_and_every_input_it_used():
    out = assess(_underwater())
    method = out["collateral_ratio_method"]
    assert method.strip()
    for term in ("collateralFactor", "getAccountSnapshot", "getUnderlyingPrice", "1e18"):
        assert term in method, term
    assert out["collateral_ratio"] == str(WEIGHTED_USD * E18 // BORROWED_USD)
    assert out["collateral_ratio_scale"] == "1e18"


def test_the_derivation_is_cross_checked_against_venus_s_own_answer():
    """Weighted collateral minus borrows is the same quantity Venus publishes as liquidity
    minus shortfall. Computing it twice and reporting the gap is what makes the derived
    ratio checkable instead of merely stated."""
    check = assess(_underwater())["cross_check"]
    assert check["derived_headroom_usd"] == str(WEIGHTED_USD - BORROWED_USD)
    assert check["venus_headroom_usd"] == str(-SHORTFALL_USD)
    assert check["difference_usd"] == "0"
    assert check["exactly_equal"] is True


def test_a_derivation_that_disagrees_with_venus_reports_the_gap_rather_than_hiding_it():
    state = _underwater(shortfall=SHORTFALL_USD + 7 * E18)
    check = assess(state)["cross_check"]
    assert check["difference_usd"] == str(7 * E18)
    assert check["exactly_equal"] is False
    assert "no tolerance here" in check["method"]


def _keys(value) -> list[str]:
    if isinstance(value, dict):
        return [k for key, item in value.items() for k in [key] + _keys(item)]
    if isinstance(value, list):
        return [k for item in value for k in _keys(item)]
    return []


def test_no_figure_anywhere_in_the_assessment_is_labelled_a_health_factor():
    """Venus publishes none. A key with that name would make a derived ratio read as a
    figure the protocol produced. The phrase is allowed in exactly one place — the flag
    and the sentence that say Venus does not publish one."""
    out = assess(_underwater())
    carrying = [key for key in _keys(out) if "health_factor" in key or "healthFactor" in key]
    assert carrying == ["publishes_health_factor"]
    assert out["venus"]["publishes_health_factor"] is False
    assert "does not publish a health factor" in out["venus"]["publishes_note"]
    assert out["collateral_ratio_is_derived"] is True


# -------------------------------------------------------------------- plan_actions


def test_a_healthy_account_produces_no_actions_at_all():
    state = _state(
        _row(VUSDC, symbol="vUSDC", cf=CF_USDC, supplied=SUPPLIED_VUSDC, rate=USDC_RATE),
        _row(VUSDT, symbol="vUSDT", cf=CF_USDT, borrowed=10 * E18, rate=USDT_RATE),
        liquidity=WEIGHTED_USD - 10 * E18,
    )
    assert plan_actions(state, _policy()) == []


def test_a_shortfall_account_produces_a_repay_intent_bounded_by_the_policy():
    actions = plan_actions(_underwater(), _policy())
    repay = next(a for a in actions if a.intent.selector == REPAY_SELECTOR)
    assert isinstance(repay.intent, ActionIntent)
    assert repay.intent.target == VUSDT
    assert repay.intent.token_in == USDT
    assert repay.intent.max_input == 200 * E18
    assert repay.intent.policy_version == POLICY_VERSION


def test_the_repay_amount_never_exceeds_the_balance_actually_owed_at_that_block():
    """A cap larger than the debt is not a licence to send the cap."""
    policy = _policy(
        markets=(MarketPolicy(vtoken=VUSDT, underlying=USDT, max_repay=10_000 * E18),),
        trigger_shortfall_usd=E18,
    )
    repay = plan_actions(_underwater(), policy)[0]
    assert repay.intent.max_input == BORROWED_USDT
    assert "borrow balance" in repay.bound_by.lower()


def test_the_repay_floor_is_the_debt_it_retires_and_says_so_in_those_words():
    """`min_output` on a swap is tokens received. On a repay nothing comes back, so the
    floor is the borrow balance the call extinguishes — which has to be said, or the field
    reads as a payout."""
    repay = next(
        a for a in plan_actions(_underwater(), _policy()) if a.intent.selector == REPAY_SELECTOR
    )
    assert repay.intent.min_output == repay.intent.max_input
    assert repay.intent.slippage_bps == 0
    assert "retire" in repay.output_means.lower()
    assert "not a token received" in repay.output_means.lower()


def test_the_ratio_names_the_one_debt_venus_counts_and_this_derivation_does_not():
    """Venus adds VAIController.getVAIRepayAmount to the borrow side of its own liquidity
    figure; this sum walks the per-market rows only. For an account that has minted VAI the
    ratio is therefore too favourable, and the cross-check gap is that debt rather than the
    truncation its method otherwise blames. Both strings have to name it, because the
    cross-check fires loudest on exactly the accounts the cause inventory omitted."""
    assessment = assess(_underwater())
    for method in (
        assessment["collateral_ratio_method"],
        assessment["cross_check"]["method"],
    ):
        assert "vai" in method.lower(), method


def test_neither_venus_floor_claims_an_enforcement_the_chain_does_not_offer():
    """Stage 2's floor rides in the calldata and the router reverts a trade that lands
    under it. Neither Venus call offers that: `mint` takes no minimum-out argument, and
    `repayBorrow` caps the amount at what is owed instead of reverting, so a repay drafted
    for `amount` can be mined having retired less. A reader who learned the field on the
    grid will carry the enforcement across unless each action says otherwise."""
    for action in plan_actions(_underwater(), _policy()):
        said = action.output_means.lower()
        assert "no chain mechanism enforces" in said or "nothing on chain enforces" in said
        assert "next account snapshot" in said or "next snapshot" in said
    repay = next(
        a for a in plan_actions(_underwater(), _policy()) if a.intent.selector == REPAY_SELECTOR
    )
    assert "caps a repay at what is owed" in repay.output_means.lower()
    supply = next(
        a for a in plan_actions(_underwater(), _policy()) if a.intent.selector == MINT_SELECTOR
    )
    assert "takes no minimum-out argument" in supply.output_means.lower()


def test_a_supply_collateral_intent_floors_the_vtokens_it_expects_and_haircuts_them():
    """The exchange rate only rises, so vTokens per unit supplied only falls between the
    draft and the block it lands in. A floor taken straight off the current rate is stale
    within blocks."""
    supply = next(
        a for a in plan_actions(_underwater(), _policy()) if a.intent.selector == MINT_SELECTOR
    )
    exact = supply.intent.max_input * E18 // USDC_RATE
    assert supply.intent.token_in == USDC
    assert supply.intent.token_out == VUSDC
    assert supply.intent.min_output < exact
    assert supply.intent.min_output == exact * (10_000 - supply.intent.slippage_bps) // 10_000


def test_every_action_carries_a_condition_over_the_shortfall_venus_published():
    repay = plan_actions(_underwater(), _policy())[0]
    assert repay.intent.condition.kind == "shortfall_at_or_above"
    assert repay.intent.condition.threshold == E18
    assert repay.intent.condition.holds(SHORTFALL_USD)
    assert not repay.intent.condition.holds(0)


def test_the_intents_are_the_stage_two_kernel_rather_than_a_second_record():
    for action in plan_actions(_underwater(), _policy()):
        assert isinstance(action.intent, ActionIntent)
        assert action.intent.chain_id == 56
        assert action.intent.min_output > 0
        assert action.intent.calldata_hash == "0x" + Web3.keccak(action.calldata).hex()
        assert action.intent.matches(action.calldata)


def test_the_guard_builds_no_borrow_and_no_withdraw_action_in_any_branch():
    """Both make a position more liquidatable, and neither is reachable from here. Checked
    against the write surface the module actually encodes rather than against its prose:
    the encoder holds two functions, and calldata for anything else cannot be built."""
    assert {entry["name"] for entry in guard_module.WRITE_ABI} == {"repayBorrow", "mint"}
    assert guard_module.REPAY_SIGNATURE == "repayBorrow(uint256)"
    assert guard_module.MINT_SIGNATURE == "mint(uint256)"
    source = inspect.getsource(guard_module)
    for forbidden in ("borrow(uint256)", "redeem(", "redeemUnderlying", "exitMarket"):
        assert forbidden not in source, forbidden


def test_a_market_the_policy_never_named_produces_no_action():
    policy = _policy(markets=(MarketPolicy(vtoken=VUSDC, underlying=USDC, max_supply=500 * E18),))
    assert [a.intent.target for a in plan_actions(_underwater(), policy)] == [VUSDC]


def test_a_policy_with_no_trigger_at_all_is_refused():
    """A trigger of zero is a condition that holds on every account including a healthy
    one, so the guard would draft a repay for somebody who owes nothing that is due."""
    with pytest.raises(ValueError):
        _policy(trigger_shortfall_usd=0)


def test_a_policy_that_permits_nothing_anywhere_is_refused():
    with pytest.raises(ValueError):
        GuardPolicy(
            markets=(MarketPolicy(vtoken=VUSDT, underlying=USDT),),
            trigger_shortfall_usd=E18,
        )


# ------------------------------------------------------------------------ preview


class _Reader:
    """Answers the two questions the preview asks, and holds nothing that could send."""

    def __init__(self, state, underlyings):
        self._state = state
        self._underlyings = underlyings
        self.asked: list[str] = []

    def account(self, address):
        self.asked.append("account")
        return self._state

    def underlying_of(self, vtoken):
        self.asked.append("underlying_of")
        return self._underlyings[Web3.to_checksum_address(vtoken)]


def _preview(state=None, underlyings=None, policy=None) -> tuple[HealthGuardPreview, _Reader]:
    reader = _Reader(
        _underwater() if state is None else state,
        {VUSDT: USDT, VUSDC: USDC} if underlyings is None else underlyings,
    )
    return HealthGuardPreview(reader=reader, policy=policy or _policy()), reader


def test_the_preview_runs_the_whole_thing_with_no_wallet_and_no_session():
    preview, _ = _preview()
    out = preview.preview(HOLDER)
    assert out["submitted"] is False
    assert out["why_not_submitted"] == PREVIEW_REASON
    assert out["assessment"]["status"] == "shortfall"
    assert len(out["actions"]) == 2
    assert out["account"]["as_of_block"] == BLOCK


def test_the_preview_holds_nothing_that_could_send_a_transaction():
    """Not "is configured not to" — there is no submitter, no signer and no armed sibling
    class anywhere in this module."""
    preview, _ = _preview()
    for attribute in ("submit", "step", "send", "_submitter", "_authority", "_signer"):
        assert not hasattr(preview, attribute), attribute
    # The word appears in the prose that says there is none; what must not appear is the
    # code that would hold one.
    source = inspect.getsource(guard_module)
    for forbidden in (
        "send_raw_transaction",
        "sign_transaction",
        "private_key",
        "submitter=",
        "self._submitter",
    ):
        assert forbidden not in source, forbidden
    assert [c.__name__ for c in vars(guard_module).values() if inspect.isclass(c)].count(
        "HealthGuardPreview"
    ) == 1


def test_each_action_says_which_checks_ran_and_that_a_router_quote_is_not_one_of_them():
    """The grid's preflight quotes the swap against PancakeSwap. A repay is not a swap and
    that router has no answer about it, so the check is declared inapplicable rather than
    quietly omitted."""
    preview, _ = _preview()
    action = preview.preview(HOLDER)["actions"][0]
    assert "policy cap" in " ".join(action["checks"]).lower()
    assert "router" in action["router_simulation"].lower()
    assert "not" in action["router_simulation"].lower()


def test_a_policy_market_whose_underlying_disagrees_with_the_chain_is_refused():
    """token_in comes from the policy, so a policy naming the wrong token would draft an
    action that pays the right contract in the wrong asset."""
    preview, _ = _preview(underlyings={VUSDT: USDC, VUSDC: USDC})
    with pytest.raises(ValueError) as exc:
        preview.preview(HOLDER)
    assert VUSDT.lower() in str(exc.value).lower()


def test_the_preview_names_the_universe_and_the_block_it_read_at():
    preview, _ = _preview()
    out = preview.preview(HOLDER)
    assert out["account"]["markets_listed"] == 52
    assert out["account"]["markets_entered"] == 2


# ------------------------------------------------------------------- what it may say


def _every_string(value) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [s for key, item in value.items() for s in _every_string(key) + _every_string(item)]
    if isinstance(value, list):
        return [s for item in value for s in _every_string(item)]
    return []


def test_no_output_anywhere_claims_a_counterfactual():
    """A liquidation that did not happen is not an outcome anybody observed. The guard
    reports a state Venus published and an action that changes a number, and these three
    words are the ones that would turn that into a claim about what was avoided."""
    assert BANNED_CLAIMS >= frozenset({"prevented", "safe", "protected"})
    preview, _ = _preview()
    for text in _every_string(preview.preview(HOLDER)):
        for word in BANNED_CLAIMS:
            assert not re.search(rf"\b{re.escape(word)}\b", text.lower()), (
                f"the guard claims {word!r} in {text[:80]!r}"
            )


def test_no_output_anywhere_carries_the_verdict_vocabulary_either():
    preview, _ = _preview()
    for text in _every_string(preview.preview(HOLDER)):
        for word in BANNED_FIELD_NAMES:
            assert not re.search(rf"\b{re.escape(word)}\b", text.lower()), (
                f"the guard carries verdict language {word!r} in {text[:80]!r}"
            )


def test_the_preview_says_what_an_action_does_not_establish():
    preview, _ = _preview()
    note = preview.preview(HOLDER)["note"].lower()
    assert "does not" in note
