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
from datetime import UTC, datetime, timedelta

import pytest
from web3 import Web3

from docket.agents.pancake import keeper as keeper_module
from docket.agents.pancake.keeper import (
    COLLECT_SIGNATURE,
    DECREASE_SIGNATURE,
    EXACT_INPUT_SINGLE_SIGNATURE,
    MAX_TICK,
    MAX_UINT128,
    MIN_TICK,
    MINT_SIGNATURE,
    PROJECTION_DAYS,
    REBALANCE_GAS_UNITS,
    TICK_SPACING_BY_FEE,
    V3_SWAP_ROUTER,
    KeeperPolicy,
    align_range,
    evaluate,
    npm_encoder,
    out_of_range_minutes,
    rebalance_calls,
    selector,
    swap_plan,
    tick_spacing,
    v3_router_encoder,
)
from docket.agents.pancake.positions import NPM
from docket.execution.simulate import (
    PANCAKE_V2_ROUTER,
    SWAP_SIGNATURE,
    swap_calldata,
)
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
NOW = datetime(2026, 9, 3, 12, 0, 0, tzinfo=UTC)
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
        "0x0c49ccbe",  # decreaseLiquidity
        "0xfc6f7865",  # collect
        "0x095ea7b3",  # ERC-20 approve, router
        "0x38ed1739",  # swapExactTokensForTokens
        "0x095ea7b3",  # ERC-20 approve, NPM, token0
        "0x095ea7b3",  # ERC-20 approve, NPM, token1
        "0x88316456",  # mint
    ]
    assert calls[3].data[:10] == "0x" + Web3.keccak(text=SWAP_SIGNATURE)[:4].hex()


def test_the_two_approve_shapes_still_share_one_selector_and_two_meanings():
    """0x095ea7b3 is ERC-20's approve and ERC-721's. The second argument is an amount on
    one and a token id on the other, which is why the session policy reads the contract and
    the selector together — and why the ERC-721 one is never in a batch a session sends."""
    from docket.jobs.executors.bounds import APPROVE_SELECTOR

    assert APPROVE_SELECTOR == "0x" + Web3.keccak(text=APPROVE_SIGNATURE)[:4].hex()
    erc20 = _calls()[2]
    assert erc20.data[:10] == APPROVE_SELECTOR
    assert erc20.to == Web3.to_checksum_address(POSITION["token0"])


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
    # Costed at PancakeSwap V2's own 25bps plus the slippage bound, not at the v3 pool's
    # 0.01% tier: the leg is quoted on V2 first, and a reset priced at the tier but
    # executed on V2 was understated fortyfold.
    swap_usd = 10_000 * 0.5 * (25 + 50) / 10_000
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
        "swap": {
            "venue": "v2",
            "token_in": "token0",
            "amount_in": 500_000,
            "min_output": MIN_OUT,
        },
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


# The floor the swap is held to, and therefore the token1 the mint may ask for.
MIN_OUT = 400_000 * 9_950 // 10_000


def test_the_batch_is_seven_session_calls_in_the_order_they_have_to_land():
    calls = _calls()
    assert [call.purpose for call in calls] == [
        "session_closes_position",
        "session_collects_to_fund_the_swap_and_the_mint",
        "session_approves_v2_router_exact",
        "session_balances_the_inventory_on_v2",
        "session_approves_token0_exact",
        "session_approves_token1_exact",
        "session_mints_replacement_to_owner",
    ]
    assert all(call.chain_id == 56 and call.value_atomic == "0" for call in calls)
    assert all(call.deadline == 1_800_000_000 for call in calls)


def test_no_call_in_the_batch_is_one_the_session_cannot_send():
    """Lane B's loop sends every prepared call from the session. An owner-signed ERC-721
    approval in that list is a call the session does not hold the right to make, so it is
    read at evaluate and reported instead of drafted — it is not in this batch at all."""
    calls = _calls()
    assert all(call.purpose != "owner_signs" for call in calls)
    # The only NPM calls left are the three a session may make under an approval.
    assert [c.purpose for c in calls if c.to == NPM] == [
        "session_closes_position",
        "session_collects_to_fund_the_swap_and_the_mint",
        "session_mints_replacement_to_owner",
    ]


def test_the_v2_leg_is_the_shared_builder_against_the_shared_router():
    """Not a second copy of either. The bytes come from
    `docket/execution/simulate.py::swap_calldata`, which is what the grid and the yield
    router already send, and the target is the router constant defined beside it."""
    approve, swap = _calls()[2], _calls()[3]
    assert approve.to == Web3.to_checksum_address(POSITION["token0"])
    assert int(approve.data[10:74], 16) == int(PANCAKE_V2_ROUTER, 16)
    assert int(approve.data[74:138], 16) == 500_000
    assert swap.to == PANCAKE_V2_ROUTER
    assert swap.data[:10] == "0x" + Web3.keccak(text=SWAP_SIGNATURE)[:4].hex()
    assert swap.data == "0x" + swap_calldata(
        amount_in=500_000,
        min_output=MIN_OUT,
        route=(POSITION["token0"], POSITION["token1"]),
        recipient=SESSION,
        deadline=1_800_000_000,
    ).hex()


def test_the_v3_leg_trades_in_the_pool_the_position_was_minted_in():
    """For a pair whose V2 market is too thin to use. The router, the selector and the
    struct shape were all read off the deployed contract: PancakeSwap's v3 SwapRouter
    carries Uniswap's tuple with the deadline inside it, not the SmartRouter's."""
    calls = _calls(
        amounts={
            "swap": {
                "venue": "v3",
                "token_in": "token0",
                "amount_in": 500_000,
                "min_output": MIN_OUT,
            }
        }
    )
    approve, swap = calls[2], calls[3]
    assert approve.purpose == "session_approves_v3_router_exact"
    assert int(approve.data[10:74], 16) == int(V3_SWAP_ROUTER, 16)
    assert swap.to == V3_SWAP_ROUTER
    assert swap.data[:10] == "0x414bf389"
    assert selector(EXACT_INPUT_SINGLE_SIGNATURE) == "0x414bf389"
    _, args = v3_router_encoder.decode_function_input(swap.data)
    params = args["params"]
    assert params["tokenIn"] == Web3.to_checksum_address(POSITION["token0"])
    assert params["tokenOut"] == Web3.to_checksum_address(POSITION["token1"])
    assert params["fee"] == POSITION["fee"]
    assert params["recipient"] == SESSION
    assert params["deadline"] == 1_800_000_000
    assert params["amountIn"] == 500_000
    assert params["amountOutMinimum"] == MIN_OUT
    assert params["sqrtPriceLimitX96"] == 0


def test_a_venue_with_no_builder_is_refused_rather_than_guessed_at():
    with pytest.raises(ValueError, match="neither v2 nor v3"):
        _calls(
            amounts={
                "swap": {
                    "venue": "v4",
                    "token_in": "token0",
                    "amount_in": 1,
                    "min_output": 1,
                }
            }
        )


def test_the_swap_proceeds_are_paid_to_the_session_that_funds_the_mint():
    swap = _calls()[3]
    assert SESSION.lower()[2:] in swap.data.lower()
    assert OWNER.lower()[2:] not in swap.data.lower()


def test_a_position_holding_only_token0_sells_token0_and_the_mint_is_sized_on_the_floor():
    calls = _calls()
    _, mint = npm_encoder.decode_function_input(calls[6].data)
    params = mint["params"]
    assert params["amount0Desired"] == 500_000
    assert params["amount1Desired"] == MIN_OUT
    assert int(calls[4].data[74:138], 16) == 500_000
    assert int(calls[5].data[74:138], 16) == MIN_OUT


def test_a_position_holding_only_token1_runs_the_leg_the_other_way():
    calls = _calls(
        amounts={
            "burn0": 0,
            "burn1": 1_000_000,
            "swap": {
                "venue": "v2",
                "token_in": "token1",
                "amount_in": 500_000,
                "min_output": MIN_OUT,
            },
        }
    )
    approve, swap = calls[2], calls[3]
    assert approve.to == Web3.to_checksum_address(POSITION["token1"])
    assert swap.data == "0x" + swap_calldata(
        amount_in=500_000,
        min_output=MIN_OUT,
        route=(POSITION["token1"], POSITION["token0"]),
        recipient=SESSION,
        deadline=1_800_000_000,
    ).hex()
    _, mint = npm_encoder.decode_function_input(calls[6].data)
    assert mint["params"]["amount0Desired"] == MIN_OUT
    assert mint["params"]["amount1Desired"] == 500_000


def test_an_inventory_that_needs_no_trade_is_minted_without_a_leg():
    calls = _calls(amounts={"burn0": 400_000, "burn1": 600_000, "swap": None})
    assert [call.purpose for call in calls] == [
        "session_closes_position",
        "session_collects_to_fund_the_swap_and_the_mint",
        "session_approves_token0_exact",
        "session_approves_token1_exact",
        "session_mints_replacement_to_owner",
    ]
    assert not any(call.to == PANCAKE_V2_ROUTER for call in calls)
    _, mint = npm_encoder.decode_function_input(calls[4].data)
    assert mint["params"]["amount0Desired"] == 400_000
    assert mint["params"]["amount1Desired"] == 600_000


def test_a_resumed_batch_does_not_burn_a_position_that_is_already_closed():
    """A batch that stopped after the collect left the NFT empty and the tokens in the
    session. Starting again would decrease liquidity that is already zero."""
    calls = rebalance_calls(
        dict(POSITION, liquidity=0),
        new_tick_lower=65_800,
        new_tick_upper=66_400,
        recipient=OWNER,
        session=SESSION,
        deadline=1_800_000_000,
        amounts={
            "max_slippage_bps": 50,
            "burn0": 1_000_000,
            "burn1": 0,
            "resume": True,
            "swap": {
                "venue": "v2",
                "token_in": "token0",
                "amount_in": 500_000,
                "min_output": MIN_OUT,
            },
        },
    )
    assert [call.purpose for call in calls] == [
        "session_approves_v2_router_exact",
        "session_balances_the_inventory_on_v2",
        "session_approves_token0_exact",
        "session_approves_token1_exact",
        "session_mints_replacement_to_owner",
    ]
    assert not any(call.purpose == "session_closes_position" for call in calls)


def test_collect_pays_the_session_because_the_session_funds_the_swap_and_the_mint():
    _, args = npm_encoder.decode_function_input(_calls()[1].data)
    params = args["params"]
    assert params["recipient"] == SESSION
    # Swept in full: a maximum below the ceiling would leave fees in the position being
    # closed, and there is no second chance to collect from a burnt one.
    assert params["amount0Max"] == params["amount1Max"] == MAX_UINT128


def test_the_new_position_nft_is_minted_to_the_owner_and_never_to_docket():
    _, args = npm_encoder.decode_function_input(_calls()[6].data)
    params = args["params"]
    assert params["recipient"] == OWNER
    assert params["recipient"] != SESSION
    assert params["tickLower"] == 65_800
    assert params["tickUpper"] == 66_400
    assert params["token0"] == Web3.to_checksum_address(POSITION["token0"])
    assert params["fee"] == POSITION["fee"]


def test_every_minimum_is_the_quoted_amount_less_the_slippage_bound():
    calls = _calls(amounts={"max_slippage_bps": 200})
    _, burn = npm_encoder.decode_function_input(calls[0].data)
    assert burn["params"]["amount0Min"] == 1_000_000 * 9_800 // 10_000
    assert burn["params"]["amount1Min"] == 0
    _, mint = npm_encoder.decode_function_input(calls[6].data)
    assert mint["params"]["amount0Desired"] == 500_000
    assert mint["params"]["amount1Desired"] == MIN_OUT
    assert mint["params"]["amount0Min"] == 500_000 * 9_800 // 10_000
    assert mint["params"]["amount1Min"] == MIN_OUT * 9_800 // 10_000


def test_every_token_approval_is_exact_and_never_unlimited():
    calls = _calls()
    assert int(calls[2].data[74:138], 16) == 500_000
    assert int(calls[4].data[74:138], 16) == 500_000
    assert int(calls[5].data[74:138], 16) == MIN_OUT
    for index in (2, 4, 5):
        assert int(calls[index].data[74:138], 16) != 2**256 - 1


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
        (
            {
                "amounts": {
                    "swap": {
                        "venue": "v2",
                        "token_in": "token0",
                        "amount_in": 9_000_000,
                        "min_output": 1,
                    }
                }
            },
            "cannot spend what the session does not have",
        ),
        (
            {
                "amounts": {
                    "swap": {
                        "venue": "v2",
                        "token_in": "token2",
                        "amount_in": 1,
                        "min_output": 1,
                    }
                }
            },
            "neither token0 nor token1",
        ),
        (
            {
                "amounts": {
                    "swap": {
                        "venue": "v2",
                        "token_in": "token0",
                        "amount_in": 500_000,
                        "min_output": 0,
                    }
                }
            },
            "accepts any output at all",
        ),
    ],
)
def test_a_batch_that_could_not_land_is_refused_before_it_is_built(overrides, match):
    with pytest.raises(ValueError, match=match):
        _calls(**overrides)


def test_a_closed_position_has_nothing_to_reset_unless_a_batch_is_being_resumed():
    with pytest.raises(ValueError, match="holds no liquidity"):
        rebalance_calls(
            dict(POSITION, liquidity=0),
            new_tick_lower=65_800,
            new_tick_upper=66_400,
            recipient=OWNER,
            session=SESSION,
            deadline=1_800_000_000,
            amounts={"max_slippage_bps": 50, "burn0": 0, "burn1": 0, "swap": None},
        )


# ------------------------------------------------------------------- swap plan


def test_a_one_sided_token0_inventory_sells_half_of_itself():
    plan = swap_plan(1_000_000, 0, sqrt_price_x96=2**96, slippage_bps=50)
    assert plan["needed"] is True
    assert plan["token_in"] == "token0"
    assert plan["amount_in"] == 500_000
    assert "equal value" in plan["reason"]


def test_a_one_sided_token1_inventory_sells_half_of_itself():
    plan = swap_plan(0, 1_000_000, sqrt_price_x96=2**96, slippage_bps=50)
    assert plan["needed"] is True
    assert plan["token_in"] == "token1"
    assert plan["amount_in"] == 500_000


def test_an_inventory_already_within_the_slippage_bound_plans_no_trade():
    """Paying a fee and a spread to move less than the bound the mint already tolerates is
    a cost with nothing bought by it."""
    plan = swap_plan(500_000, 500_000, sqrt_price_x96=2**96, slippage_bps=50)
    assert plan["needed"] is False
    assert plan["amount_in"] == 0
    assert "inside the 50bps the policy already tolerates" in plan["reason"]
    # Just outside it, and a leg appears.
    assert swap_plan(510_000, 490_000, sqrt_price_x96=2**96, slippage_bps=50)["needed"]


def test_the_split_is_taken_at_the_pools_own_price_rather_than_at_parity():
    """sqrtP of 2**97 is a price of 4 token1 per token0, so 1,000,000 of token0 is worth
    4,000,000 of token1 and the sale is sized against that rather than against the raw
    token counts."""
    plan = swap_plan(1_000_000, 0, sqrt_price_x96=2**97, slippage_bps=50)
    assert plan["value1_of_token0"] == 4_000_000
    assert plan["total_value1"] == 4_000_000
    assert plan["amount_in"] == 500_000


def test_a_position_releasing_nothing_plans_no_trade():
    plan = swap_plan(0, 0, sqrt_price_x96=2**96, slippage_bps=50)
    assert plan["needed"] is False
    assert "no inventory to rebalance" in plan["reason"]


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


def test_the_catalogue_describes_the_bundle_the_batch_actually_contains():
    """The description is the contract. It names the swap as part of the sequence, says
    where its floor comes from, says which calls are not simulated and why, and does not
    claim the session's caps are enforced by a chain."""
    from docket.hire.catalogue import SERVICES

    copy = SERVICES["range-doctor"].what_you_get
    for phrase in (
        "the whole reset is prepared as exact calls, in the order they have to land",
        "rebalance the inventory through one exact-input swap",
        "Its venue is chosen rather than assumed",
        "the mint is sized against that minimum rather than a quote",
        "minted without a swap",
        "exact amount and never unlimited",
        "marked as waiting on it rather than tested against a state that does not exist",
        "can only be made by the wallet holding it",
        "checked by Docket before every send rather than enforced by a chain",
        "how much you fund the session with",
    ):
        assert phrase in copy, phrase
    for gone in ("priced but not prepared", "yours to make"):
        assert gone not in copy, gone
    assert "The leg is part of the batch." in keeper_module.SWAP_NOTE


def test_a_multiple_exactly_at_the_threshold_is_acted_on_rather_than_refused():
    """The boundary the whole benefit test turns on. `>=` and `>` differ by exactly the
    case where the projection covers the cost by the multiple asked for and no more, and a
    policy that refused that would be refusing the thing it was configured to permit."""
    base = evaluate(
        _valued(),
        POOL_ABOVE,
        STATS,
        _policy(),
        history=_history(180),
        now=NOW,
        gas_price_wei=ONE_GWEI,
        bnb_usd=BNB_USD,
    )
    achieved = base.evidence["economics"]["net_benefit_multiple"]
    at = evaluate(
        _valued(),
        POOL_ABOVE,
        STATS,
        _policy(min_net_benefit_multiple=achieved),
        history=_history(180),
        now=NOW,
        gas_price_wei=ONE_GWEI,
        bnb_usd=BNB_USD,
    )
    assert at.kind == "action"
    just_above = evaluate(
        _valued(),
        POOL_ABOVE,
        STATS,
        _policy(min_net_benefit_multiple=achieved * 1.000001),
        history=_history(180),
        now=NOW,
        gas_price_wei=ONE_GWEI,
        bnb_usd=BNB_USD,
    )
    assert just_above.kind == "alert"


def test_a_staked_position_is_never_reset_because_the_farm_holds_its_nft():
    decision = evaluate(
        _valued(staked=True),
        POOL_ABOVE,
        STATS,
        _policy(),
        history=_history(180),
        now=NOW,
        gas_price_wei=ONE_GWEI,
        bnb_usd=BNB_USD,
    )
    assert decision.kind == "alert"
    assert "Unstake from MasterChefV3 first" in decision.summary
    assert decision.evidence["staked"] is True


def test_a_pool_that_could_not_be_read_is_not_counted_as_time_outside_a_range():
    """`unknown_pool` observed no price at all, so it says nothing about whether the
    position was outside its range. Counting it would date a departure from a read that
    failed."""
    decision = evaluate(
        _valued(),
        {"address": None, "tick": None, "sqrt_price_x96": None, "liquidity": None,
         "block_number": None, "observation_time": None},
        None,
        _policy(),
        history=_history(600),
        now=NOW,
        gas_price_wei=ONE_GWEI,
        bnb_usd=BNB_USD,
    )
    assert decision.kind == "noop"
    assert decision.evidence["time_out_of_range"]["observed_minutes"] == 0.0
