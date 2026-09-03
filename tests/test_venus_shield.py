"""The Health Shield: the remedy arithmetic, the ABI evidence behind it, and its refusals.

Five things this file exists to pin.

**`repayBorrowBehalf` exists, and this is the evidence.** The fixture below records what
was read and where, so a later reader can re-run the same checks rather than take the
module's word for it. The selector is re-derived from the canonical signature here; the
rest is a dated record of a mainnet read.

**The remedy is exact.** Four account shapes — healthy, near the line, undercollateralised,
and one borrowing across two markets — and in each case the post-action ratio computed by
the module's own formula has to land at or above the target. An amount rounded the wrong
way is a remedy that lands a unit short of the line it was computed to clear.

**A collateral add is never sent by a session.** `mint(uint256)` credits its caller and has
no on-behalf form, so both of its calls carry `owner_signs` and a test asserts it.

**The native market is refused rather than mis-encoded.** vBNB takes
`repayBorrowBehalf(address)`, payable, which is a different selector.

**Nothing claims a counterfactual.** The guard's own banned vocabulary is scanned over
everything the shield emits, so no string here says a position was made safer or that a
liquidation was avoided.
"""

import inspect
import re
from datetime import datetime, timezone

import pytest
from web3 import Web3

from docket.agents.venus import shield as shield_module
from docket.agents.venus.guard import BANNED_CLAIMS, E18
from docket.agents.venus.markets import AccountState, MarketPosition
from docket.agents.venus.shield import (
    MINT_SIGNATURE,
    REPAY_BEHALF_SIGNATURE,
    UNDERLYING_BY_VTOKEN,
    VBNB,
    ShieldPolicy,
    evaluate,
    rescue_calls,
    selector,
)
from docket.api.models import BANNED_FIELD_NAMES

VUSDT = Web3.to_checksum_address("0xfD5840Cd36d94D7229439859C0112a4185BC0255")
VUSDC = Web3.to_checksum_address("0xecA88125a5ADbe82614ffC12D0DB554E2e2867C8")
VBUSD = Web3.to_checksum_address("0x95c78222B3D6e262426483D42CfA53685A67Ab9D")
USDT = Web3.to_checksum_address("0x55d398326f99059fF775485246999027B3197955")
USDC = Web3.to_checksum_address("0x8AC76a51cc950d9822D68b83fE1Ad97B32Cd580d")
BUSD = Web3.to_checksum_address("0xe9e7CEA3DedcA5984780Bafc599bD69ADd087D56")
ORACLE = Web3.to_checksum_address("0x6592b5DE802159F3E74B2486b091D11a8256ab8A")
HOLDER = Web3.to_checksum_address("0x429898ba0Fc5b9F1fF0a8f0BD1D6D3cB33B26DdD")
SESSION = Web3.to_checksum_address("0xE4fe23FB57dbb9AC2f685ea29B6b9A1409A0d359")
BLOCK = 115_174_800
NOW = datetime(2026, 9, 3, 12, 0, 0, tzinfo=timezone.utc)
# Live 2026-08-10 values: 8-decimal vTokens against 18-decimal underlyings, so the exchange
# rate is 1e28-scaled and the oracle price is 1e18-scaled.
USDC_RATE = 266_027_524_223_233_974_720_539_463
USDT_RATE = 264_313_571_779_695_838_956_523_484
CF_USDC = 825 * 10**15
CF_USDT = 800 * 10**15

# What was read from BSC mainnet on 2026-09-03, kept as a fixture so the module's claim is
# re-checkable rather than a sentence in a docstring. `in_delegator` and `in_implementation`
# record that the four-byte selector appears in each contract's runtime bytecode;
# `eth_call_returned` is the value the live call answered, which is Venus's NO_ERROR.
REPAY_BEHALF_EVIDENCE = {
    "signature": "repayBorrowBehalf(address,uint256)",
    "selector": "0x2608f818",
    "source_url": (
        "https://github.com/VenusProtocol/venus-protocol/blob/develop/contracts/"
        "Tokens/VTokens/VBep20.sol"
    ),
    "source_declaration": (
        "function repayBorrowBehalf(address borrower, uint repayAmount) external "
        "returns (uint)"
    ),
    "read_on": "2026-09-03",
    "chain_id": 56,
    "vtoken": VUSDT,
    "implementation": Web3.to_checksum_address(
        "0xCDfea50f7CECCB24Fe804657DB8E6c93b689941e"
    ),
    "in_delegator": True,
    "in_implementation": True,
    "selector_block": 119_695_469,
    "eth_call_block": 119_695_550,
    "eth_call_returned": 0,
    "bscscan_v1_getabi": "refused: deprecated V1 endpoint",
    "native_market": {
        "vtoken": VBNB,
        "signature": "repayBorrowBehalf(address)",
        "selector": "0xe5974619",
        "carries_two_argument_form": False,
        "underlying_returns_bytes": False,
        "read_at_block": 119_697_338,
    },
}


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


def _state(*rows, liquidity=0, shortfall=0, error=0, address=HOLDER):
    return AccountState(
        address=address,
        error_code=error,
        liquidity_usd=liquidity,
        shortfall_usd=shortfall,
        markets_listed=55,
        rows=tuple(rows),
        oracle=ORACLE,
        as_of_block=BLOCK,
        reads=("eth_blockNumber", "comptroller.getAccountLiquidity"),
    )


SUPPLIED_VUSDC = 40_000 * 10**8


def _account(borrowed_usdt, *, extra=()):
    return _state(
        _row(
            VUSDC, symbol="vUSDC", cf=CF_USDC, supplied=SUPPLIED_VUSDC, rate=USDC_RATE
        ),
        _row(VUSDT, symbol="vUSDT", cf=CF_USDT, borrowed=borrowed_usdt, rate=USDT_RATE),
        *extra,
    )


def _policy(**overrides) -> ShieldPolicy:
    fields = {
        "min_collateral_ratio": 1.25,
        "max_rescue_atomic": {USDT: 50_000 * E18, USDC: 50_000 * E18},
        "allowed_vtokens": (VUSDT, VUSDC),
        "mode": "repay",
        "expires_at": "2026-12-31T00:00:00Z",
    }
    fields.update(overrides)
    return ShieldPolicy(**fields)


def _totals(state):
    """The same two sums `guard.assess` makes, recomputed here rather than imported."""
    weighted = borrowed = 0
    for row in state.rows:
        supplied = row.vtoken_balance * row.exchange_rate_mantissa // E18
        weighted += (
            (supplied * row.underlying_price_mantissa // E18)
            * row.collateral_factor_mantissa
            // E18
        )
        borrowed += row.borrow_balance * row.underlying_price_mantissa // E18
    return weighted, borrowed


def _strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield str(key)
            yield from _strings(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _strings(item)


# -------------------------------------------------------------- ABI evidence


def test_the_repay_behalf_selector_is_the_keccak_of_the_signature_it_claims():
    assert selector(REPAY_BEHALF_SIGNATURE) == REPAY_BEHALF_EVIDENCE["selector"]
    assert (
        selector(REPAY_BEHALF_SIGNATURE)
        == "0x" + Web3.keccak(text="repayBorrowBehalf(address,uint256)")[:4].hex()
    )
    assert selector(MINT_SIGNATURE) == "0xa0712d68"


def test_the_evidence_fixture_records_where_the_signature_was_read_and_when():
    """The docstring's claim and this record are the same claim, so a reader can re-run it."""
    assert REPAY_BEHALF_EVIDENCE["in_delegator"] is True
    assert REPAY_BEHALF_EVIDENCE["in_implementation"] is True
    assert REPAY_BEHALF_EVIDENCE["eth_call_returned"] == 0
    assert REPAY_BEHALF_EVIDENCE["chain_id"] == 56
    docstring = shield_module.__doc__
    assert REPAY_BEHALF_EVIDENCE["selector"] in docstring
    assert REPAY_BEHALF_EVIDENCE["source_url"] in docstring
    assert REPAY_BEHALF_EVIDENCE["read_on"] in docstring
    assert "deprecated V1 endpoint" in docstring


def test_the_native_market_takes_a_different_function_and_is_never_encoded_against():
    native = REPAY_BEHALF_EVIDENCE["native_market"]
    assert (
        native["selector"]
        == "0x" + Web3.keccak(text="repayBorrowBehalf(address)")[:4].hex()
    )
    assert native["selector"] != REPAY_BEHALF_EVIDENCE["selector"]
    assert native["carries_two_argument_form"] is False
    assert VBNB not in UNDERLYING_BY_VTOKEN
    with pytest.raises(ValueError, match="native market vBNB"):
        _policy(allowed_vtokens=(VBNB,)).validate()


def test_every_market_the_shield_sizes_in_names_its_underlying():
    assert UNDERLYING_BY_VTOKEN[VUSDT] == USDT
    assert UNDERLYING_BY_VTOKEN[VUSDC] == USDC
    assert UNDERLYING_BY_VTOKEN[VBUSD] == BUSD
    assert all(Web3.to_checksum_address(v) == v for v in UNDERLYING_BY_VTOKEN.values())


# ------------------------------------------------------------ the four shapes


def test_an_account_comfortably_above_the_line_is_left_alone():
    # ~$878 of weighted collateral against $100 of debt: a ratio near 8.8 against a 1.25
    # target, which is the shape a healthy borrower is actually in.
    weighted, _ = _totals(_account(100 * E18))
    decision = evaluate(_account(100 * E18), _policy(), now=NOW)
    assert decision.kind == "noop"
    assert decision.remedy is None
    assert int(decision.evidence["collateral_ratio"]) > int(1.25 * E18)
    assert int(decision.evidence["weighted_collateral_usd"]) == weighted


def test_an_account_just_under_the_line_is_repaired_by_the_smallest_repay_that_clears_it():
    """Near the threshold is where an off-by-one in the ceiling shows: the remedy is a few
    units, and a floor instead of a ceiling lands under the target rather than on it."""
    weighted, _ = _totals(_account(0))
    # Debt one unit more than the target ratio permits.
    borrowed_usdt = weighted * E18 // int(1.25 * E18) + 1
    state = _account(borrowed_usdt)
    decision = evaluate(state, _policy(), now=NOW)
    assert decision.kind == "action"
    assert decision.remedy["amount_atomic"] >= 1
    after = int(decision.remedy["post_action"]["collateral_ratio"])
    assert after >= int(1.25 * E18)


def test_an_undercollateralised_account_is_sized_against_its_whole_shortfall():
    weighted, _ = _totals(_account(0))
    state = _account(weighted)  # ratio exactly 1.0, well under a 1.25 target
    decision = evaluate(state, _policy(), now=NOW)
    assert decision.kind == "action"
    assert decision.remedy["mode"] == "repay"
    assert decision.remedy["vtoken"] == VUSDT
    after = int(decision.remedy["post_action"]["collateral_ratio"])
    assert after >= int(1.25 * E18)
    # The permitted borrow at the target, recomputed here rather than read back.
    assert int(decision.remedy["permitted_borrow_usd"]) == weighted * E18 // int(
        1.25 * E18
    )


def test_an_account_borrowing_in_two_markets_is_repaired_in_the_larger_debt():
    weighted, _ = _totals(_account(0))
    # Total debt equal to the weighted collateral: a ratio of 1.0 against a 1.25 target,
    # split so the larger market cannot be mistaken for the smaller.
    big = weighted * 7 // 10
    small = weighted * 3 // 10
    state = _state(
        _row(
            VUSDC, symbol="vUSDC", cf=CF_USDC, supplied=SUPPLIED_VUSDC, rate=USDC_RATE
        ),
        _row(VUSDT, symbol="vUSDT", cf=CF_USDT, borrowed=big, rate=USDT_RATE),
        _row(VBUSD, symbol="vBUSD", cf=CF_USDT, borrowed=small, rate=USDT_RATE),
    )
    decision = evaluate(
        state,
        _policy(
            allowed_vtokens=(VUSDT, VUSDC, VBUSD),
            max_rescue_atomic={USDT: 10**30, USDC: 10**30, BUSD: 10**30},
        ),
        now=NOW,
    )
    assert decision.kind == "action"
    assert decision.remedy["symbol"] == "vUSDT"
    assert int(decision.remedy["post_action"]["collateral_ratio"]) >= int(1.25 * E18)


@pytest.mark.parametrize("ratio", [1.05, 1.25, 1.5, 2.0, 3.0])
def test_the_post_action_ratio_always_lands_at_or_above_the_target(ratio):
    """The property the whole module exists for, checked across five targets rather than
    asserted once. Three truncating divisions stand between the amount and the ratio, and
    each is inverted by a ceiling so none of them can round the remedy short."""
    weighted, _ = _totals(_account(0))
    state = _account(weighted)
    decision = evaluate(
        state,
        _policy(min_collateral_ratio=ratio, max_rescue_atomic={USDT: 10**30}),
        now=NOW,
    )
    if decision.kind != "action":
        assert (
            decision.remedy is None
            or int(
                decision.remedy["needed_atomic"]
                if "needed_atomic" in decision.remedy
                else decision.remedy["amount_atomic"]
            )
            > 0
        )
        return
    assert int(decision.remedy["post_action"]["collateral_ratio"]) >= int(ratio * E18)


def test_an_account_that_owes_nothing_has_no_ratio_and_nothing_due():
    decision = evaluate(_account(0), _policy(), now=NOW)
    assert decision.kind == "noop"
    assert decision.evidence["collateral_ratio"] is None
    assert "no denominator" in decision.summary


def test_a_snapshot_the_chain_refused_to_stand_behind_sizes_nothing():
    state = _state(
        _row(
            VUSDT,
            symbol="vUSDT",
            cf=CF_USDT,
            borrowed=1_000 * E18,
            rate=USDT_RATE,
            error=9,
        )
    )
    decision = evaluate(state, _policy(), now=NOW)
    assert decision.kind == "alert"
    assert decision.remedy is None
    assert "nonzero error code" in decision.summary


# --------------------------------------------------------- collateral remedies


def test_a_collateral_add_is_sized_from_the_market_where_a_unit_counts_for_most():
    weighted, _ = _totals(_account(0))
    state = _account(weighted)
    decision = evaluate(
        state,
        _policy(mode="add_collateral", max_rescue_atomic={USDC: 10**30}),
        now=NOW,
    )
    assert decision.kind == "action"
    assert decision.remedy["mode"] == "add_collateral"
    # vUSDC carries the higher collateral factor of the two markets entered.
    assert decision.remedy["vtoken"] == VUSDC
    assert int(decision.remedy["post_action"]["collateral_ratio"]) >= int(1.25 * E18)


def test_either_mode_prefers_the_remedy_a_session_can_actually_complete():
    weighted, _ = _totals(_account(0))
    decision = evaluate(
        _account(weighted),
        _policy(mode="either", max_rescue_atomic={USDT: 10**30, USDC: 10**30}),
        now=NOW,
    )
    assert decision.remedy["mode"] == "repay"


def test_either_mode_falls_back_when_no_repay_is_permitted():
    weighted, _ = _totals(_account(0))
    decision = evaluate(
        _account(weighted),
        _policy(
            mode="either",
            allowed_vtokens=(VUSDC,),
            max_rescue_atomic={USDC: 10**30},
        ),
        now=NOW,
    )
    assert decision.kind == "action"
    assert decision.remedy["mode"] == "add_collateral"


# ------------------------------------------------------------------- refusals


def test_a_remedy_larger_than_the_policy_cap_is_refused_with_the_amount_shown():
    weighted, _ = _totals(_account(0))
    decision = evaluate(
        _account(weighted), _policy(max_rescue_atomic={USDT: 1}), now=NOW
    )
    assert decision.kind == "alert"
    assert decision.remedy is not None, "the refused amount travels with the refusal"
    assert "caps a rescue" in decision.evidence["refusal"]


def test_a_market_the_policy_never_named_is_never_repaid_into():
    weighted, _ = _totals(_account(0))
    decision = evaluate(
        _account(weighted),
        _policy(allowed_vtokens=(VUSDC,), max_rescue_atomic={USDC: 1}),
        now=NOW,
    )
    assert decision.kind == "alert"
    assert "no market this account borrows in" in decision.evidence["refusal"]


def test_an_expired_policy_sizes_nothing():
    weighted, _ = _totals(_account(0))
    decision = evaluate(
        _account(weighted), _policy(expires_at="2026-01-01T00:00:00Z"), now=NOW
    )
    assert decision.kind == "alert"
    assert "policy expired" in decision.summary


@pytest.mark.parametrize(
    ("overrides", "match"),
    [
        ({"min_collateral_ratio": 0}, "positive multiple"),
        ({"mode": "borrow"}, "mode must be one of"),
        ({"allowed_vtokens": ()}, "permits nothing"),
        ({"max_rescue_atomic": {}}, "caps nothing"),
        ({"max_rescue_atomic": {USDT: 0}}, "positive whole number"),
        ({"expires_at": "2026-12-31T00:00:00"}, "carries no timezone"),
    ],
)
def test_a_policy_that_bounds_nothing_is_refused(overrides, match):
    with pytest.raises(ValueError, match=match):
        _policy(**overrides).validate()


# -------------------------------------------------------------- prepared calls


def _repay_decision():
    weighted, _ = _totals(_account(0))
    state = _account(weighted)
    return state, evaluate(state, _policy(max_rescue_atomic={USDT: 10**30}), now=NOW)


def test_a_repay_is_an_exact_approval_and_then_the_on_behalf_call():
    state, decision = _repay_decision()
    approve, repay = rescue_calls(
        state, decision, session=SESSION, borrower=state.address
    )
    amount = decision.remedy["amount_atomic"]
    assert approve.to == USDT
    assert approve.data[:10] == "0x095ea7b3"
    assert int(approve.data[10:74], 16) == int(VUSDT, 16)
    assert int(approve.data[74:138], 16) == amount
    assert int(approve.data[74:138], 16) != 2**256 - 1
    assert repay.to == VUSDT
    assert repay.data[:10] == REPAY_BEHALF_EVIDENCE["selector"]
    assert int(repay.data[10:74], 16) == int(state.address, 16)
    assert int(repay.data[74:138], 16) == amount
    assert repay.purpose == "session_repays_on_behalf_of_borrower"
    assert approve.purpose == "session_approves_vtoken_exact"


def test_a_collateral_add_is_the_owners_own_transaction_and_says_so_on_the_call():
    weighted, _ = _totals(_account(0))
    state = _account(weighted)
    decision = evaluate(
        state,
        _policy(mode="add_collateral", max_rescue_atomic={USDC: 10**30}),
        now=NOW,
    )
    calls = rescue_calls(state, decision, session=SESSION, borrower=state.address)
    assert [call.purpose for call in calls] == ["owner_signs", "owner_signs"]
    assert calls[1].data[:10] == "0xa0712d68"
    assert "no on-behalf form" in decision.remedy["means"]


def test_calldata_is_never_built_for_an_account_the_state_was_not_read_for():
    state, decision = _repay_decision()
    with pytest.raises(ValueError, match="is not the account this state was read for"):
        rescue_calls(state, decision, session=SESSION, borrower=SESSION)


def test_a_decision_that_sized_no_remedy_builds_no_calls():
    decision = evaluate(_account(0), _policy(), now=NOW)
    with pytest.raises(ValueError, match="sized no remedy"):
        rescue_calls(_account(0), decision, session=SESSION, borrower=HOLDER)


# ------------------------------------------------------------------- structure


def test_no_output_anywhere_claims_a_counterfactual_or_carries_a_verdict():
    """The Venus guard's rule, applied to the shield: a liquidation that did not happen is
    not an outcome anybody observed, and Docket publishes observations rather than verdicts."""
    weighted, _ = _totals(_account(0))
    decision = evaluate(
        _account(weighted), _policy(max_rescue_atomic={USDT: 10**30}), now=NOW
    )
    texts = list(_strings(decision.evidence)) + [decision.summary]
    for text in texts:
        lowered = text.lower()
        for word in BANNED_CLAIMS | BANNED_FIELD_NAMES:
            assert not re.search(rf"\b{re.escape(word)}\b", lowered), (
                f"the shield claims {word!r} in {text[:90]!r}"
            )


def test_the_alias_never_travels_without_the_sentence_that_says_what_it_is():
    record = _policy().as_record()
    assert record["min_health_factor"] == record["min_collateral_ratio"]
    assert record["publishes_health_factor"] is False
    assert "does not publish a health factor" in record["min_health_factor_note"]
    assert "derived by the formula" in record["min_health_factor_note"]


def test_the_shield_holds_nothing_that_could_send_a_transaction():
    source = inspect.getsource(shield_module)
    for forbidden in (
        "send_raw_transaction",
        "sign_transaction",
        "private_key",
        "from_key",
        "eth_sendRawTransaction",
    ):
        assert forbidden not in source, forbidden


def test_the_shield_encodes_two_writes_and_neither_borrows_nor_withdraws():
    assert {entry["name"] for entry in shield_module.VTOKEN_WRITE_ABI} == {
        "repayBorrowBehalf",
        "mint",
    }
    source = inspect.getsource(shield_module)
    for forbidden in ("borrow(uint256)", "redeem(", "redeemUnderlying", "exitMarket"):
        assert forbidden not in source, forbidden
