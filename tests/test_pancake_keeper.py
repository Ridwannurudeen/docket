"""The Range Keeper: the selectors it encodes, the arithmetic it decides on, and its limits.

Four things this file exists to pin.

**Every selector is re-derived, never transcribed.** A one-character error in an ABI type
produces calldata for a function that does not exist, and the transaction reverts having
cost gas. So the four signatures are hashed here and compared against the four-byte
prefixes of the bytes the module actually builds.

**The new position NFT goes to the owner.** `mint`'s recipient is decoded out of the
calldata and compared to the owner, not to the session. Docket never receives it.

**A minimum is a minimum.** Every floor is checked against the slippage bound it was
derived from, because a floor computed the wrong way round is a call that accepts anything.

**Nothing here signs or sends.** Scanned against the source, the way the Venus guard's own
tests scan it.
"""

import inspect
from datetime import datetime, timedelta, timezone

import pytest
from web3 import Web3

from docket.agents.pancake import keeper as keeper_module
from docket.agents.pancake.keeper import (
    COLLECT_SIGNATURE,
    DECREASE_SIGNATURE,
    MAX_UINT128,
    MAX_TICK,
    MIN_TICK,
    MINT_SIGNATURE,
    PROJECTION_DAYS,
    REBALANCE_GAS_UNITS,
    TICK_SPACING_BY_FEE,
    KeeperPolicy,
    align_range,
    evaluate,
    npm_encoder,
    out_of_range_minutes,
    rebalance_calls,
    selector,
    tick_spacing,
)
from docket.agents.pancake.positions import NPM
from docket.jobs.executors.bounds import APPROVE_SIGNATURE

# The same 2026-08-08 mainnet reading `tests/test_pancake_doctor.py` uses: token 7087132 in
# the QQQB/USDT 0.01% pool, so the keeper and the doctor are judged on one position.
POSITION = {
    "token_id": 7087132,
    "staked": False,
    "token0": "0x205812CdBed920aFf76C6580abD681a46D11efc7",
    "token1": "0x55d398326f99059fF775485246999027B3197955",
    "fee": 100,
    "tick_lower": 65452,
    "tick_upper": 66052,
    "liquidity": 125256614773376725006,
    "tokens_owed0": 0,
    "tokens_owed1": 0,
    "block_number": 114739953,
    "observation_time": "2026-08-08T12:00:00+00:00",
}
POOL_IN_RANGE = {
    "address": "0xe531fcb1F5a195de7608B9F4f9518544C2cdB693",
    "tick": 65821,
    "sqrt_price_x96": 2128637418868180723784745824244,
    "liquidity": 21740148071633644244142639,
    "block_number": 114740301,
    "observation_time": "2026-08-08T12:01:00+00:00",
}
POOL_ABOVE = dict(POOL_IN_RANGE, tick=66100)
POOL_BELOW = dict(POOL_IN_RANGE, tick=65000)
ROW = {
    "id": "0xe531fcb1f5a195de7608b9f4f9518544c2cdb693",
    "feeTier": 100,
    "token0": {"symbol": "QQQB", "id": "0x205812cdbed920aff76c6580abd681a46d11efc7"},
    "token1": {"symbol": "USDT", "id": "0x55d398326f99059ff775485246999027b3197955"},
    "tvlUSD": "3306485.2014337434",
    "volumeUSD24h": "38737134.0108538",
    "feeUSD24h": "3873.71340108392",
    "protocolFeeUSD24h": "1278.40200556144",
}
STATS = {"row": ROW, "plausible": True, "reason": "ok"}
NET_APR = (3873.71340108392 - 1278.40200556144) * 365 / 3306485.2014337434

OWNER = Web3.to_checksum_address("0xe55816904796341bf8535e25f6c8b647927fc946")
SESSION = Web3.to_checksum_address("0x429898ba0Fc5b9F1fF0a8f0BD1D6D3cB33B26DdD")
NOW = datetime(2026, 9, 3, 12, 0, 0, tzinfo=timezone.utc)
ONE_GWEI = 10**9
BNB_USD = 600.0


def _policy(**overrides) -> KeeperPolicy:
    fields = {
        "out_of_range_minutes": 60,
        "min_net_benefit_multiple": 2.0,
        "max_slippage_bps": 50,
        "max_gas_price_wei": 5 * ONE_GWEI,
        "max_notional_usd": 100_000.0,
        "band_width_ticks": None,
        "expires_at": "2026-12-31T00:00:00Z",
    }
    fields.update(overrides)
    return KeeperPolicy(**fields)


def _valued(**overrides) -> dict:
    return dict(POSITION, declared_position_value_usd=10_000.0, **overrides)


def _history(minutes: int, *, in_range: bool = False) -> list[dict]:
    return [
        {
            "observed_at": (NOW - timedelta(minutes=minutes)).isoformat(),
            "block": 1,
            "tick": 66100,
            "in_range": in_range,
        }
    ]


# ------------------------------------------------------------------- selectors


def test_every_selector_is_the_keccak_of_the_signature_it_claims():
    """Not transcribed. Each of these was also found in the deployed position manager's
    runtime bytecode before it was written down, and the hash below is what stops a typo in
    an ABI type from surviving into calldata for a function that does not exist."""
    assert selector(DECREASE_SIGNATURE) == "0x0c49ccbe"
    assert selector(COLLECT_SIGNATURE) == "0xfc6f7865"
    assert selector(MINT_SIGNATURE) == "0x88316456"
    assert selector(APPROVE_SIGNATURE) == "0x095ea7b3"
    for signature in (
        DECREASE_SIGNATURE,
        COLLECT_SIGNATURE,
        MINT_SIGNATURE,
        APPROVE_SIGNATURE,
    ):
        assert selector(signature) == "0x" + Web3.keccak(text=signature)[:4].hex()


def test_the_bytes_the_module_builds_carry_those_exact_selectors():
    calls = _calls()
    assert [call.data[:10] for call in calls] == [
        "0x095ea7b3",
        "0x0c49ccbe",
        "0xfc6f7865",
        "0x095ea7b3",
        "0x095ea7b3",
        "0x88316456",
    ]


def test_the_erc721_and_erc20_approvals_share_one_selector_and_two_meanings():
    """0x095ea7b3 is ERC-20's approve and ERC-721's. The second argument is an amount on
    one and a token id on the other, so a policy that allowlists the selector without also
    pinning the contract has allowed both — which is why the first call goes to the
    position manager and the two after it go to the pool's tokens."""
    calls = _calls()
    assert calls[0].data[:10] == calls[3].data[:10] == "0x095ea7b3"
    assert calls[0].to == NPM
    assert calls[3].to == Web3.to_checksum_address(POSITION["token0"])
    assert int(calls[0].data[74:138], 16) == POSITION["token_id"]


# --------------------------------------------------------------- tick geometry


def test_the_spacing_map_is_the_one_the_v3_factory_answered():
    """Read from feeAmountTickSpacing at block 119,695,563. 3000 and 20000 answered 0 —
    PancakeSwap did not open Uniswap's 0.3% tier — so neither is in the map and a position
    claiming one is refused rather than aligned to a guess."""
    assert TICK_SPACING_BY_FEE == {100: 1, 500: 10, 2500: 50, 10000: 200}
    assert tick_spacing(2500) == 50
    with pytest.raises(ValueError, match="no tick spacing"):
        tick_spacing(3000)


def test_a_band_is_snapped_outward_so_it_never_comes_back_narrower_than_asked():
    lower, upper = align_range(65_821, 300, 50)
    assert lower % 50 == 0 and upper % 50 == 0
    assert lower <= 65_821 - 300 and upper >= 65_821 + 300
    assert lower == 65_500 and upper == 66_150


def test_alignment_below_zero_floors_towards_negative_infinity():
    """Truncating towards zero here would put the lower bound *inside* the band on every
    negative tick, which is the half of the range a stablecoin pair spends its life in."""
    lower, upper = align_range(-1_001, 100, 50)
    assert lower == -1_150 and upper == -900
    assert lower <= -1_101 and upper >= -901


def test_a_band_is_clamped_to_the_ticks_the_pool_will_hold():
    lower, upper = align_range(0, 10**7, 200)
    assert lower >= MIN_TICK and upper <= MAX_TICK
    assert lower == -887_200 and upper == 887_200
    assert lower % 200 == 0 and upper % 200 == 0


# ------------------------------------------------------------- time out of range


def test_only_observed_time_outside_the_range_is_counted():
    assert out_of_range_minutes(_history(90), now=NOW, in_range=False) == pytest.approx(
        90
    )


def test_a_position_inside_its_range_has_been_outside_for_no_time_at_all():
    assert out_of_range_minutes(_history(90), now=NOW, in_range=True) == 0.0


def test_a_departure_nobody_observed_is_not_dated_from_a_guess():
    """The last observation saw it inside. It left somewhere between then and now, and the
    keeper claims none of that time rather than inventing a departure moment."""
    assert (
        out_of_range_minutes(_history(90, in_range=True), now=NOW, in_range=False)
        == 0.0
    )
    assert out_of_range_minutes([], now=NOW, in_range=False) == 0.0


def test_the_run_stops_at_the_last_observation_that_saw_it_inside():
    history = [
        {"observed_at": (NOW - timedelta(minutes=300)).isoformat(), "in_range": False},
        {"observed_at": (NOW - timedelta(minutes=200)).isoformat(), "in_range": True},
        {"observed_at": (NOW - timedelta(minutes=120)).isoformat(), "in_range": False},
        {"observed_at": (NOW - timedelta(minutes=60)).isoformat(), "in_range": False},
    ]
    assert out_of_range_minutes(history, now=NOW, in_range=False) == pytest.approx(120)


# -------------------------------------------------------------------- evaluate


def test_a_position_inside_its_range_is_left_alone():
    decision = evaluate(
        _valued(),
        POOL_IN_RANGE,
        STATS,
        _policy(),
        history=[],
        now=NOW,
        gas_price_wei=ONE_GWEI,
        bnb_usd=BNB_USD,
    )
    assert decision.kind == "noop"
    assert decision.evidence["economics"]["projected_recovery_usd"] is None


def test_a_position_outside_its_range_for_less_than_the_policy_waits_is_left_alone():
    decision = evaluate(
        _valued(),
        POOL_ABOVE,
        STATS,
        _policy(out_of_range_minutes=120),
        history=_history(30),
        now=NOW,
        gas_price_wei=ONE_GWEI,
        bnb_usd=BNB_USD,
    )
    assert decision.kind == "noop"
    assert decision.evidence["time_out_of_range"]["observed_minutes"] == pytest.approx(
        30
    )


def test_a_reset_that_pays_for_itself_is_offered_with_the_whole_arithmetic():
    decision = evaluate(
        _valued(),
        POOL_ABOVE,
        STATS,
        _policy(),
        history=_history(180),
        now=NOW,
        gas_price_wei=ONE_GWEI,
        bnb_usd=BNB_USD,
    )
    assert decision.kind == "action"
    economics = decision.evidence["economics"]
    assert economics["net_apr"] == pytest.approx(NET_APR)
    assert economics["projected_recovery_usd"] == pytest.approx(
        10_000 * NET_APR * PROJECTION_DAYS / 365
    )
    gas_usd = REBALANCE_GAS_UNITS * ONE_GWEI / 10**18 * BNB_USD
    swap_usd = 10_000 * 0.5 * (100 / 1_000_000 + 50 / 10_000)
    assert economics["gas_cost_usd"] == pytest.approx(gas_usd)
    assert economics["swap_cost_usd"] == pytest.approx(swap_usd)
    assert economics["total_cost_usd"] == pytest.approx(gas_usd + swap_usd)
    assert economics["net_benefit_multiple"] == pytest.approx(
        economics["projected_recovery_usd"] / economics["total_cost_usd"]
    )
    # Width kept, centred on the tick the price actually sits at, aligned to spacing 1.
    assert decision.new_tick_upper - decision.new_tick_lower == 600
    assert decision.new_tick_lower < POOL_ABOVE["tick"] < decision.new_tick_upper


def test_a_reset_that_does_not_clear_the_multiple_is_an_alert_carrying_the_shortfall():
    decision = evaluate(
        _valued(),
        POOL_ABOVE,
        STATS,
        _policy(min_net_benefit_multiple=1_000.0),
        history=_history(180),
        now=NOW,
        gas_price_wei=ONE_GWEI,
        bnb_usd=BNB_USD,
    )
    assert decision.kind == "alert"
    assert decision.evidence["economics"]["net_benefit_multiple"] < 1_000.0
    assert "1000.00 the policy requires" in decision.summary


@pytest.mark.parametrize(
    ("overrides", "policy_overrides", "gas_price", "fragment"),
    [
        ({}, {}, 6 * ONE_GWEI, "above the policy ceiling"),
        ({}, {"expires_at": "2026-01-01T00:00:00Z"}, ONE_GWEI, "policy expired"),
        ({}, {"max_notional_usd": 100.0}, ONE_GWEI, "above the policy's"),
    ],
)
def test_a_reset_the_policy_forbids_is_refused_with_the_reason_named(
    overrides, policy_overrides, gas_price, fragment
):
    decision = evaluate(
        _valued(**overrides),
        POOL_BELOW,
        STATS,
        _policy(**policy_overrides),
        history=_history(180),
        now=NOW,
        gas_price_wei=gas_price,
        bnb_usd=BNB_USD,
    )
    assert decision.kind == "alert"
    assert fragment in decision.summary
    assert decision.evidence["economics"]["net_benefit_multiple"] is None


def test_a_position_with_no_declared_value_is_never_reset_on_a_guessed_one():
    """Docket has no trusted first-party source for a position NFT's USD value, which is
    the same reason the Range Doctor refuses to invent one."""
    decision = evaluate(
        dict(POSITION),
        POOL_ABOVE,
        STATS,
        _policy(),
        history=_history(180),
        now=NOW,
        gas_price_wei=ONE_GWEI,
        bnb_usd=BNB_USD,
    )
    assert decision.kind == "alert"
    assert "declared_position_value_usd was not supplied" in decision.summary


def test_a_reset_is_never_priced_against_a_bnb_price_nobody_supplied():
    """A gas cost of zero clears any benefit multiple. The missing input refuses rather
    than discounting the half of the cost it cannot convert."""
    decision = evaluate(
        _valued(),
        POOL_ABOVE,
        STATS,
        _policy(),
        history=_history(180),
        now=NOW,
        gas_price_wei=ONE_GWEI,
        bnb_usd=0.0,
    )
    assert decision.kind == "alert"
    assert "bnb_usd was not supplied" in decision.summary


def test_a_pool_whose_row_failed_the_plausibility_gate_yields_no_rate_to_project_from():
    decision = evaluate(
        _valued(),
        POOL_ABOVE,
        {"row": ROW, "plausible": False, "reason": "turnover is not plausible"},
        _policy(),
        history=_history(180),
        now=NOW,
        gas_price_wei=ONE_GWEI,
        bnb_usd=BNB_USD,
    )
    assert decision.kind == "alert"
    assert "plausibility gate" in decision.summary


def test_a_band_width_the_owner_named_is_the_half_width_of_the_new_range():
    decision = evaluate(
        _valued(fee=2500),
        POOL_ABOVE,
        STATS,
        _policy(band_width_ticks=300),
        history=_history(180),
        now=NOW,
        gas_price_wei=ONE_GWEI,
        bnb_usd=BNB_USD,
    )
    assert decision.new_tick_lower % 50 == 0
    assert decision.new_tick_upper % 50 == 0
    assert decision.new_tick_lower <= POOL_ABOVE["tick"] - 300
    assert decision.new_tick_upper >= POOL_ABOVE["tick"] + 300


# ---------------------------------------------------------------------- policy


@pytest.mark.parametrize(
    ("overrides", "match"),
    [
        ({"out_of_range_minutes": 0}, "must be positive"),
        ({"min_net_benefit_multiple": 0.5}, "at least 1"),
        ({"max_slippage_bps": 0}, "between 1 and 1000"),
        ({"max_slippage_bps": 2000}, "between 1 and 1000"),
        ({"max_gas_price_wei": 0}, "positive number of wei"),
        ({"max_notional_usd": 0}, "positive USD figure"),
        ({"band_width_ticks": 0}, "positive half-width"),
        ({"expires_at": "2026-12-31T00:00:00"}, "carries no timezone"),
        ({"expires_at": "soon"}, "not an ISO-8601 instant"),
    ],
)
def test_a_policy_that_bounds_nothing_is_refused(overrides, match):
    with pytest.raises(ValueError, match=match):
        _policy(**overrides).validate()


# -------------------------------------------------------------- prepared calls


def _calls(**overrides):
    amounts = {
        "max_slippage_bps": 50,
        "burn0": 1_000_000,
        "burn1": 0,
        "desired0": 500_000,
        "desired1": 400_000,
    }
    amounts.update(overrides.pop("amounts", {}))
    fields = {
        "new_tick_lower": 65_800,
        "new_tick_upper": 66_400,
        "recipient": OWNER,
        "session": SESSION,
        "deadline": 1_800_000_000,
        "amounts": amounts,
    }
    fields.update(overrides)
    return rebalance_calls(POSITION, **fields)


def test_the_batch_is_six_calls_in_the_order_they_have_to_land():
    calls = _calls()
    assert [call.purpose for call in calls] == [
        "owner_signs",
        "session_closes_position",
        "session_collects_to_fund_mint",
        "session_approves_token0_exact",
        "session_approves_token1_exact",
        "session_mints_replacement_to_owner",
    ]
    assert all(call.chain_id == 56 and call.value_atomic == 0 for call in calls)


def test_the_first_call_is_the_owners_because_only_an_owner_may_approve_their_own_nft():
    approve = _calls()[0]
    assert approve.purpose == "owner_signs"
    assert approve.to == NPM
    _, args = npm_encoder.decode_function_input(
        _calls()[1].data
    )  # the call the approval unlocks
    assert args["params"]["tokenId"] == POSITION["token_id"]


def test_collect_pays_the_session_because_the_session_funds_the_mint():
    _, args = npm_encoder.decode_function_input(_calls()[2].data)
    params = args["params"]
    assert params["recipient"] == SESSION
    # Swept in full: a maximum below the ceiling would leave fees in the position being
    # closed, and there is no second chance to collect from a burnt one.
    assert params["amount0Max"] == params["amount1Max"] == MAX_UINT128


def test_the_new_position_nft_is_minted_to_the_owner_and_never_to_docket():
    _, args = npm_encoder.decode_function_input(_calls()[5].data)
    params = args["params"]
    assert params["recipient"] == OWNER
    assert params["recipient"] != SESSION
    assert params["tickLower"] == 65_800
    assert params["tickUpper"] == 66_400
    assert params["token0"] == Web3.to_checksum_address(POSITION["token0"])
    assert params["fee"] == POSITION["fee"]


def test_every_minimum_is_the_quoted_amount_less_the_slippage_bound():
    calls = _calls(amounts={"max_slippage_bps": 200})
    _, burn = npm_encoder.decode_function_input(calls[1].data)
    assert burn["params"]["amount0Min"] == 1_000_000 * 9_800 // 10_000
    assert burn["params"]["amount1Min"] == 0
    _, mint = npm_encoder.decode_function_input(calls[5].data)
    assert mint["params"]["amount0Min"] == 500_000 * 9_800 // 10_000
    assert mint["params"]["amount1Min"] == 400_000 * 9_800 // 10_000
    assert mint["params"]["amount0Desired"] == 500_000


def test_the_token_approvals_are_exact_and_never_unlimited():
    calls = _calls()
    assert int(calls[3].data[74:138], 16) == 500_000
    assert int(calls[4].data[74:138], 16) == 400_000
    assert int(calls[3].data[74:138], 16) != 2**256 - 1


def test_no_call_arrives_carrying_a_simulation_nobody_ran():
    for call in _calls():
        assert call.simulation == {
            "ok": None,
            "gas_estimate": None,
            "revert_reason": None,
            "observed_at": None,
            "block": None,
        }


@pytest.mark.parametrize(
    ("overrides", "match"),
    [
        ({"amounts": {"max_slippage_bps": 0}}, "outside 1..1000"),
        ({"new_tick_lower": 66_400, "new_tick_upper": 66_400}, "is empty"),
    ],
)
def test_a_batch_that_could_not_land_is_refused_before_it_is_built(overrides, match):
    with pytest.raises(ValueError, match=match):
        _calls(**overrides)


def test_a_closed_position_has_nothing_to_reset():
    with pytest.raises(ValueError, match="holds no liquidity"):
        rebalance_calls(
            dict(POSITION, liquidity=0),
            new_tick_lower=65_800,
            new_tick_upper=66_400,
            recipient=OWNER,
            session=SESSION,
            deadline=1_800_000_000,
            amounts={
                "max_slippage_bps": 50,
                "burn0": 0,
                "burn1": 0,
                "desired0": 0,
                "desired1": 0,
            },
        )


# ------------------------------------------------------------------- structure


def test_the_keeper_holds_nothing_that_could_send_a_transaction():
    """Not "is configured not to". There is no signer and no submitter in this module, and
    no float path into transaction sizing either — `tickmath` is never reached from here."""
    source = inspect.getsource(keeper_module)
    for forbidden in (
        "send_raw_transaction",
        "sign_transaction",
        "private_key",
        "from_key",
        "eth_sendRawTransaction",
    ):
        assert forbidden not in source, forbidden
    # The float module is named in the prose that says it is not used; what must not appear
    # is the import that would make it reachable.
    for forbidden in ("from .tickmath", "import tickmath", "tickmath."):
        assert forbidden not in source, forbidden


def test_the_catalogue_names_the_step_the_batch_does_not_build():
    """The batch is six calls and a rebalance is seven steps. The trade between the collect
    and the mint is priced into the decision and left to the owner, and a description that
    listed only the six would read as a sequence that lands on its own."""
    from docket.hire.catalogue import SERVICES

    copy = SERVICES["range-doctor"].what_you_get
    assert "priced but not prepared" in copy
    assert "yours to make" in copy
    assert "half of it has to be traded" in copy
    # And the module's own evidence says the same thing to a machine reader.
    assert "not among the calls this module builds" in keeper_module.SWAP_PREREQUISITE
    decision = evaluate(
        _valued(),
        POOL_ABOVE,
        STATS,
        _policy(),
        history=_history(180),
        now=NOW,
        gas_price_wei=ONE_GWEI,
        bnb_usd=BNB_USD,
    )
    assert decision.evidence["swap_prerequisite"] == keeper_module.SWAP_PREREQUISITE
    assert decision.evidence["economics"]["swap_cost_usd"] > 0
