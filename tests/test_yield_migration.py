"""The whole move, not the swap leg: out of one v3 position and into another.

The category verb is "routes liquidity to the highest available APR", and until this
module existed Docket drafted the swap and said in `NOT_BUILT` that the rest was the
caller's. These tests are about the rest.

Five properties carry the weight.

**The selectors are recomputed, never transcribed.** Every four-byte selector in the
route is keccak'd here from the signature string beside it, and the encoded calldata is
checked to start with it. A transcribed selector nobody recomputes is a call to a
function that may not exist.

**No step carries a zero minimum.** The withdrawal, every swap leg and the mint each
insist on an amount derived from the chain's own price less exactly the stated slippage.

**Approvals are exact.** The ERC-20 allowances granted to the position manager are for
the amounts the mint pulls, to the wei, and never unlimited.

**The new position goes to the owner and the funds transit the session.** A mint to the
session would be a position the session's revocation could strand.

**A route that cannot run is refused before any bytes exist**, and the refusal names what
would have failed rather than letting the sequence die at its first call.
"""

import pytest
from web3 import Web3

from docket.agents.yield_router.migration import (
    ASSUMPTIONS,
    DEADLINE_S,
    NPM,
    SELECTORS,
    TICK_SPACINGS,
    UINT128_MAX,
    MigrationRefused,
    NftApprovalRequired,
    align_band,
    amounts_for_liquidity,
    match_current_pool,
    plan_full_route,
    sqrt_ratio_x96_at_tick,
)
from docket.agents.yield_router.universe import eligible_pools
from docket.execution.simulate import PANCAKE_V2_ROUTER, ROUTER_ABI

USDT = Web3.to_checksum_address("0x55d398326f99059fF775485246999027B3197955")
USDC = Web3.to_checksum_address("0x8AC76a51cc950d9822D68b83fE1Ad97B32Cd580d")
WBNB = Web3.to_checksum_address("0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c")
STRANGER = Web3.to_checksum_address("0x000000000000000000000000000000000000dEaD")
OWNER = Web3.to_checksum_address("0x429898ba0Fc5b9F1fF0a8f0BD1D6D3cB33B26DdD")
SESSION = Web3.to_checksum_address("0xe55816904796341bf8535e25f6c8b647927fc946")
ALLOWLIST = {USDT.lower(), USDC.lower(), WBNB.lower()}
OBSERVED = "2026-09-01T00:00:00Z"
SOURCE = "explorer.pancakeswap.com/api/cached/pools/v3/bsc/list/top"
FROZEN_NOW = 2_000_000_000
E18 = 10**18
Q96 = 2**96
BLOCK = 41_000_000
CHAIN_TIME = "2026-09-03T09:00:00+00:00"
DEST_TICK = -64_000
_router = Web3().eth.contract(abi=ROUTER_ABI)


def _pool(pool_id, token0, token1, *, fee_tier, tvl, volume, fee, protocol):
    return {
        "id": pool_id,
        "feeTier": fee_tier,
        "token0": {"symbol": "T0", "id": token0.lower()},
        "token1": {"symbol": "T1", "id": token1.lower()},
        "tvlUSD": str(tvl),
        "volumeUSD24h": str(volume),
        "feeUSD24h": str(fee),
        "protocolFeeUSD24h": str(protocol),
    }


CURRENT_POOL = _pool(
    "0xcurrent",
    USDT,
    USDC,
    fee_tier=100,
    tvl=1_000_000,
    volume=500_000,
    fee=100,
    protocol=33,
)
DEST_POOL = _pool(
    "0xdest",
    USDT,
    WBNB,
    fee_tier=500,
    tvl=2_000_000,
    volume=1_000_000,
    fee=900,
    protocol=300,
)


def _universe(pools=None):
    return eligible_pools(
        pools if pools is not None else [CURRENT_POOL, DEST_POOL],
        set(ALLOWLIST),
        source=SOURCE,
        observed_at=OBSERVED,
    )


def _position(**overrides):
    position = {
        "token_id": 7141050,
        "staked": False,
        "token0": USDT,
        "token1": USDC,
        "fee": 100,
        "tick_lower": -100,
        "tick_upper": 100,
        "liquidity": 10**22,
        "tokens_owed0": 0,
        "tokens_owed1": 0,
        "block_number": BLOCK,
        "observation_time": CHAIN_TIME,
    }
    position.update(overrides)
    return position


class Reader:
    """The five reads `plan_full_route` needs, priced off two synthetic pools."""

    # Per-selector, because one flat figure would either sit above every ceiling in the
    # route or below every one of them, and a test that cannot fail a gas ceiling is not
    # checking that the ceilings are there.
    GAS = {
        "0x095ea7b3": 50_000,
        "0x0c49ccbe": 250_000,
        "0xfc6f7865": 190_000,
        "0x38ed1739": 210_000,
        "0x88316456": 620_000,
    }

    GET_APPROVED = "0x081812fc"
    IS_APPROVED_FOR_ALL = "0xe985e9c5"
    BALANCE_OF = "0x70a08231"
    POSITIONS = "0x99fbab88"

    def __init__(
        self,
        *,
        revert_on=None,
        gas=None,
        dest_tick=DEST_TICK,
        approved_to=SESSION,
        approved_for_all=False,
        liquidity=None,
        owed=(0, 0),
        balances=None,
    ):
        self.revert_on = revert_on or ()
        self.gas = gas
        self.dest_tick = dest_tick
        # Approved by default: the owner signing for the session is the precondition of
        # every route, not the thing under test in most of these. `approved_to=None` is
        # the ungranted case.
        self.approved_to = approved_to
        self.approved_for_all = approved_for_all
        self.liquidity = liquidity
        self.owed = owed
        self.balances = balances or {}
        self.calls: list[tuple] = []
        self.estimates: list[tuple] = []

    def block_number(self):
        return BLOCK

    def pool_state(self, token0, token1, fee):
        pair = {Web3.to_checksum_address(token0), Web3.to_checksum_address(token1)}
        if pair == {USDT, USDC}:
            tick = 0
        elif pair == {USDT, WBNB}:
            tick = self.dest_tick
        else:
            return {
                "address": None,
                "tick": None,
                "sqrt_price_x96": None,
                "liquidity": None,
                "block_number": None,
                "observation_time": None,
            }
        return {
            "address": Web3.to_checksum_address("0x" + "22" * 20),
            "tick": tick,
            "sqrt_price_x96": sqrt_ratio_x96_at_tick(tick),
            "liquidity": 10**24,
            "block_number": BLOCK,
            "observation_time": CHAIN_TIME,
        }

    def amounts_out(self, amount_in, route):
        route = tuple(Web3.to_checksum_address(hop) for hop in route)
        rates = {
            (USDC, USDT): (1, 1),
            (USDT, USDC): (1, 1),
            (USDT, WBNB): (1, 600),
            (WBNB, USDT): (600, 1),
            (USDC, WBNB): (1, 600),
        }
        if route not in rates:
            raise AssertionError(f"unexpected route {route}")
        num, den = rates[route]
        return [amount_in, amount_in * num // den]

    def call(self, sender, target, calldata):
        self.calls.append((sender, target, calldata))
        selector = "0x" + calldata[:4].hex()
        if selector in self.revert_on:
            raise RuntimeError("execution reverted: Not approved")
        if selector == self.GET_APPROVED:
            if self.approved_to is None:
                return bytes(32)
            return bytes(12) + bytes.fromhex(self.approved_to[2:])
        if selector == self.IS_APPROVED_FOR_ALL:
            return int(bool(self.approved_for_all)).to_bytes(32, "big")
        if selector == self.BALANCE_OF:
            token = Web3.to_checksum_address(target)
            return int(self.balances.get(token, 0)).to_bytes(32, "big")
        if selector == self.POSITIONS:
            if self.liquidity is None:
                return b""
            words = [bytes(32)] * 12
            words[7] = int(self.liquidity).to_bytes(32, "big")
            words[10] = int(self.owed[0]).to_bytes(32, "big")
            words[11] = int(self.owed[1]).to_bytes(32, "big")
            return b"".join(words)
        return b""

    def estimate_gas(self, sender, target, calldata):
        self.estimates.append((sender, target, calldata))
        if self.gas is not None:
            return self.gas
        return self.GAS["0x" + calldata[:4].hex()]


def _plan(**overrides):
    kwargs = {
        "universe": _universe(),
        "reader": Reader(),
        "owner": OWNER,
        "session": SESSION,
        "position_size_usd": 10_000.0,
        "switching_cost_usd": 15.0,
        "max_slippage_bps": 50,
        "band_width_ticks": 1_000,
        "now": FROZEN_NOW,
    }
    position = overrides.pop("position", None) or _position()
    destination = overrides.pop("destination", None) or DEST_POOL
    kwargs.update(overrides)
    return plan_full_route(position, destination, **kwargs)


def _selector(call):
    return call.data[:10]


# ------------------------------------------------------------------ tick arithmetic


def test_the_sqrt_ratio_reproduces_the_published_tick_math_constants():
    """Tick 0 is exact, and the two extremes agree with the on-chain library to within
    far less than the slippage haircut every minimum derived from them carries."""
    assert sqrt_ratio_x96_at_tick(0) == Q96

    minimum = sqrt_ratio_x96_at_tick(-887272)
    maximum = sqrt_ratio_x96_at_tick(887272)
    assert abs(minimum - 4295128739) <= 1
    published_max = 1461446703485210103287273052203988822378723970342
    assert abs(maximum - published_max) / published_max < 1e-18


def test_a_tick_outside_the_representable_range_is_refused():
    with pytest.raises(MigrationRefused, match="outside"):
        sqrt_ratio_x96_at_tick(887273)


def test_liquidity_prices_to_one_token_when_the_price_has_left_the_band():
    low = sqrt_ratio_x96_at_tick(-100)
    high = sqrt_ratio_x96_at_tick(100)

    below = amounts_for_liquidity(10**20, sqrt_ratio_x96_at_tick(-500), low, high)
    inside = amounts_for_liquidity(10**20, Q96, low, high)
    above = amounts_for_liquidity(10**20, sqrt_ratio_x96_at_tick(500), low, high)

    assert below[1] == 0 and below[0] > 0
    assert inside[0] > 0 and inside[1] > 0
    assert above[0] == 0 and above[1] > 0


def test_the_band_is_aligned_outward_so_it_is_never_narrower_than_asked():
    lower, upper = align_band(-64_003, 1_000, 10)

    assert lower % 10 == 0 and upper % 10 == 0
    assert lower <= -64_003 - 1_000
    assert upper >= -64_003 + 1_000


@pytest.mark.parametrize("bad", (0, -1))
def test_a_band_with_no_width_is_refused(bad):
    with pytest.raises(MigrationRefused, match="band_width_ticks"):
        align_band(0, bad, 10)


# ------------------------------------------------------------------ the ABI


def test_every_selector_is_the_keccak_of_the_signature_written_beside_it():
    expected = {
        name: "0x" + Web3.keccak(text=signature)[:4].hex()
        for name, signature in SELECTORS.items()
    }
    plan = _plan()
    selectors = [_selector(call) for call in plan.calls]

    assert expected["npm.approve"] == "0x095ea7b3"
    assert expected["npm.decreaseLiquidity"] == "0x0c49ccbe"
    assert expected["npm.collect"] == "0xfc6f7865"
    assert expected["npm.mint"] == "0x88316456"
    assert expected["npm.positions"] == "0x99fbab88"
    assert expected["npm.getApproved"] == "0x081812fc"
    assert expected["npm.isApprovedForAll"] == "0xe985e9c5"
    assert selectors[0] == expected["npm.decreaseLiquidity"]
    assert selectors[1] == expected["npm.collect"]
    assert selectors[-1] == expected["npm.mint"]
    assert plan.verification.data[:10] == expected["npm.positions"]
    assert not [
        call
        for call in plan.calls
        if call.to == NPM and call.selector == expected["npm.approve"]
    ]


# ------------------------------------------------------------------ the route


def test_the_route_runs_in_the_one_order_that_can_work():
    plan = _plan()
    purposes = [call.purpose for call in plan.calls]

    assert len(plan.calls) == 7
    assert "burn all" in purposes[0]
    assert "collect everything" in purposes[1]
    assert purposes[2].startswith("swap")
    assert purposes[3].startswith("swap")
    assert "approve the position manager for exactly" in purposes[4]
    assert "approve the position manager for exactly" in purposes[5]
    assert purposes[6].startswith("mint into 0xdest")
    assert [call.to for call in plan.calls[:2]] == [NPM, NPM]
    assert [call.to for call in plan.calls[2:4]] == [PANCAKE_V2_ROUTER] * 2
    assert [call.to for call in plan.calls[4:6]] == [USDT, WBNB]
    assert plan.calls[6].to == NPM


def test_no_call_in_the_batch_is_the_owners_to_sign():
    """Every call is broadcast from the session key, so an owner-signed approval sitting
    in the list would be signed by an account that does not own the NFT and would revert
    at what looks like the route's own first step."""
    plan = _plan()

    assert not [c for c in plan.calls if c.purpose.startswith("OWNER SIGNS:")]
    assert not [c for c in plan.calls if c.to == NPM and c.selector == "0x095ea7b3"]
    assert "not in the sequence below" in plan.disclosure["nft_approval_precondition"]
    assert "owner's own signature" in plan.disclosure["nft_approval_precondition"]


def test_a_session_the_owner_has_not_approved_is_refused_before_any_bytes_exist():
    with pytest.raises(NftApprovalRequired, match="is not approved for position NFT"):
        _plan(reader=Reader(approved_to=None))


def test_the_refusal_names_exactly_what_the_owner_has_to_sign():
    detail = None
    try:
        _plan(reader=Reader(approved_to=None))
    except NftApprovalRequired as exc:
        detail = exc.detail

    assert detail is not None
    assert detail["contract"] == NPM
    assert detail["token_id"] == 7141050
    assert detail["session"] == SESSION
    assert detail["owner"] == OWNER
    assert detail["function"] == "approve(address,uint256)"
    assert "setApprovalForAll" in detail["note"]


def test_a_blanket_approval_for_all_positions_also_satisfies_the_precondition():
    plan = _plan(reader=Reader(approved_to=None, approved_for_all=True))

    assert len(plan.calls) == 7


def test_the_withdrawal_insists_on_the_pools_own_amounts_less_the_stated_slippage():
    plan = _plan()
    disclosure = plan.disclosure["position"]

    removed0 = int(disclosure["removed_amount0"])
    removed1 = int(disclosure["removed_amount1"])
    assert removed0 > 0 and removed1 > 0
    assert int(disclosure["withdrawal_floor0"]) == removed0 * 9_950 // 10_000
    assert int(disclosure["withdrawal_floor1"]) == removed1 * 9_950 // 10_000
    assert int(disclosure["withdrawal_floor0"]) > 0
    assert int(disclosure["withdrawal_floor1"]) > 0


def test_the_collect_names_the_session_and_takes_everything_the_position_owes():
    plan = _plan()
    data = bytes.fromhex(plan.calls[1].data[10:])
    token_id, recipient, max0, max1 = (
        int.from_bytes(data[0:32], "big"),
        Web3.to_checksum_address("0x" + data[32:64].hex()[-40:]),
        int.from_bytes(data[64:96], "big"),
        int.from_bytes(data[96:128], "big"),
    )

    assert token_id == 7141050
    assert recipient == SESSION
    assert max0 == UINT128_MAX
    assert max1 == UINT128_MAX


def test_a_token_the_destination_does_not_hold_is_routed_into_one_it_does():
    plan = _plan()
    first = _router.decode_function_input(plan.calls[2].data)[1]

    assert first["path"] == [USDC, USDT]
    assert first["to"] == SESSION
    assert first["amountOutMin"] > 0
    # Call index 2 in the batch, so three windows out: they are mined in order and a
    # later call carrying an earlier one's deadline expires waiting its turn.
    assert first["deadline"] == FROZEN_NOW + 3 * DEADLINE_S
    assert plan.calls[2].deadline == first["deadline"]


def test_the_balancing_leg_buys_the_side_the_destination_band_is_short_of():
    plan = _plan()
    second = _router.decode_function_input(plan.calls[3].data)[1]

    assert second["path"] == [USDT, WBNB]
    assert second["amountOutMin"] > 0
    assert "needs more token1" in plan.calls[3].purpose


def test_every_swap_leg_is_floored_at_the_live_quote_less_the_stated_slippage():
    plan = _plan(max_slippage_bps=200)

    for leg in plan.disclosure["slippage"]["legs"]:
        quoted = int(leg["quoted_out"])
        assert int(leg["min_out"]) == quoted * 9_800 // 10_000
        assert int(leg["min_out"]) > 0


def test_the_approvals_are_for_exactly_what_the_mint_pulls_and_never_unlimited():
    plan = _plan()
    approvals = {
        call.to: int(bytes.fromhex(call.data[10:])[32:64].hex(), 16)
        for call in plan.calls
        if call.data.startswith("0x095ea7b3") and call.to != NPM
    }
    spender = {
        call.to: Web3.to_checksum_address("0x" + call.data[10:74][-40:])
        for call in plan.calls
        if call.data.startswith("0x095ea7b3") and call.to != NPM
    }
    desired0 = int(plan.disclosure["position"]["mint_amount0_desired"])
    desired1 = int(plan.disclosure["position"]["mint_amount1_desired"])

    assert set(spender.values()) == {NPM}
    assert approvals[USDT] == desired0
    assert approvals[WBNB] == desired1
    assert UINT128_MAX not in approvals.values()
    assert 2**256 - 1 not in approvals.values()


def test_the_mint_lands_in_the_owners_wallet_over_the_aligned_band():
    plan = _plan()
    data = bytes.fromhex(plan.calls[-1].data[10:])
    words = [data[i : i + 32] for i in range(0, len(data), 32)]
    token0 = Web3.to_checksum_address("0x" + words[0].hex()[-40:])
    token1 = Web3.to_checksum_address("0x" + words[1].hex()[-40:])
    fee = int.from_bytes(words[2], "big")
    tick_lower = int.from_bytes(words[3], "big", signed=True)
    tick_upper = int.from_bytes(words[4], "big", signed=True)
    desired0 = int.from_bytes(words[5], "big")
    desired1 = int.from_bytes(words[6], "big")
    min0 = int.from_bytes(words[7], "big")
    min1 = int.from_bytes(words[8], "big")
    recipient = Web3.to_checksum_address("0x" + words[9].hex()[-40:])

    assert (token0, token1, fee) == (USDT, WBNB, 500)
    assert (tick_lower, tick_upper) == align_band(DEST_TICK, 1_000, TICK_SPACINGS[500])
    assert tick_lower % TICK_SPACINGS[500] == 0
    assert tick_upper % TICK_SPACINGS[500] == 0
    assert recipient == OWNER
    assert recipient != SESSION
    assert min0 == desired0 * 9_950 // 10_000
    assert min1 == desired1 * 9_950 // 10_000
    assert min0 > 0 and min1 > 0
    assert int.from_bytes(words[10], "big") == FROZEN_NOW + 7 * DEADLINE_S
    assert plan.calls[-1].deadline == FROZEN_NOW + 7 * DEADLINE_S


def test_the_mint_asks_for_the_floors_of_every_step_before_it():
    """Planning on the expected output would build a mint the session cannot cover when
    a leg fills at its floor; planning on the floor leaves dust instead of a revert."""
    plan = _plan()
    legs = plan.disclosure["slippage"]["legs"]
    desired1 = int(plan.disclosure["position"]["mint_amount1_desired"])

    assert desired1 == int(legs[-1]["min_out"])
    assert desired1 < int(legs[-1]["quoted_out"])


# ------------------------------------------------------------------ simulation


def test_the_calls_that_can_be_preflighted_are_and_the_rest_say_why_not():
    reader = Reader()
    plan = _plan(reader=reader)

    decrease, collect = plan.calls[0], plan.calls[1]
    assert decrease.simulation["checks"][-2:] == ["eth_call", "eth_estimateGas"]
    assert decrease.simulation["ok"] is True
    assert collect.simulation["deferred"]
    assert plan.calls[-1].simulation["deferred"]
    assert plan.calls[2].simulation["deferred"]
    assert any("getAmountsOut" in check for check in plan.calls[2].simulation["checks"])
    assert plan.simulation_ok is True
    assert {sender for sender, _target, _data in reader.calls} == {OWNER, SESSION}


def test_a_call_whose_estimate_exceeds_its_ceiling_fails_rather_than_passing():
    plan = _plan(reader=Reader(gas=900_000))

    over = [call for call in plan.calls if call.simulation["ok"] is False]
    assert over
    assert "above the ceiling" in over[0].simulation["revert_reason"]
    assert plan.simulation_ok is False


def test_a_call_the_chain_reverts_is_recorded_as_failed_rather_than_dropped():
    plan = _plan(reader=Reader(revert_on=("0x0c49ccbe",)))

    decrease = plan.calls[0]
    assert decrease.simulation["ok"] is False
    assert "Not approved" in decrease.simulation["revert_reason"]
    assert plan.simulation_ok is False


# ------------------------------------------------------------------ the disclosure


def test_the_disclosure_answers_every_question_a_signer_should_ask():
    plan = _plan()
    disclosure = plan.disclosure

    assert disclosure["current_apr"]["net_fee_apr"] == pytest.approx(
        (100 - 33) * 365 / 1_000_000
    )
    assert disclosure["proposed_apr"]["net_fee_apr"] == pytest.approx(
        (900 - 300) * 365 / 2_000_000
    )
    assert disclosure["data_timestamp"]["pool_statistics_observed_at"] == OBSERVED
    assert disclosure["data_timestamp"]["pool_statistics_source"] == SOURCE
    assert disclosure["data_timestamp"]["chain_block"] == BLOCK
    assert disclosure["liquidity_and_capacity"]["destination_tvl_usd"] == 2_000_000
    assert disclosure["liquidity_and_capacity"]["share_of_pool"] == pytest.approx(0.005)
    assert "does not audit" in disclosure["protocol_risk"]
    assert disclosure["estimated_gas"]["sum_of_estimates"] > 0
    assert disclosure["estimated_gas"]["calls_not_estimated"] > 0
    assert disclosure["slippage"]["max_slippage_bps"] == 50
    assert disclosure["expected_payback_period_days"] > 0
    assert (
        disclosure["minimum_holding_period_days"]
        == disclosure["expected_payback_period_days"]
    )
    assert len(disclosure["transaction_sequence"]) == len(plan.calls)
    assert [step["step"] for step in disclosure["transaction_sequence"]] == list(
        range(1, len(plan.calls) + 1)
    )
    assert disclosure["assumptions_that_could_invalidate_this"] == list(ASSUMPTIONS)
    assert any(
        "Impermanent loss is not modelled" in line
        for line in disclosure["assumptions_that_could_invalidate_this"]
    )
    assert any(
        "24h observation" in line
        for line in disclosure["assumptions_that_could_invalidate_this"]
    )
    assert any(
        "caller's own figure" in line
        for line in disclosure["assumptions_that_could_invalidate_this"]
    )


def test_the_payback_period_is_the_routers_own_break_even_arithmetic():
    from docket.agents.yield_router.router import break_even, compare

    universe = _universe()
    candidates = compare(CURRENT_POOL, universe)
    destination = next(c for c in candidates if c.pool_id == "0xdest")
    current = next(c for c in candidates if c.pool_id == "0xcurrent")
    expected = break_even(
        current, destination, position_size_usd=10_000.0, switching_cost_usd=15.0
    )

    plan = _plan()
    assert plan.disclosure["break_even"]["days_to_recover"] == pytest.approx(
        expected["days_to_recover"]
    )
    assert plan.disclosure["break_even"]["within_horizon"] is True


def test_a_current_pool_outside_the_eligible_set_reports_no_rate_rather_than_zero():
    plan = _plan(universe=_universe([DEST_POOL]))

    current = plan.disclosure["current_apr"]
    assert current["net_fee_apr"] is None
    assert "not in the eligible set" in current["unavailable_reason"]
    assert plan.disclosure["break_even"]["within_horizon"] is False


def test_the_current_pool_is_matched_on_both_tokens_and_the_fee_tier():
    universe = _universe()

    assert match_current_pool(_position(), universe) is CURRENT_POOL
    assert match_current_pool(_position(fee=500), universe) is None
    assert match_current_pool(_position(token1=WBNB, fee=500), universe) is DEST_POOL


def test_the_verification_read_names_the_log_that_identifies_the_new_position():
    plan = _plan()

    assert plan.verification.target == NPM
    assert plan.verification.function == "positions(uint256)"
    assert "IncreaseLiquidity" in plan.verification.identified_by
    assert "Transfer" in plan.verification.identified_by
    assert "needs nothing from Docket" in plan.verification.note


def test_the_plan_hashes_over_everything_it_publishes():
    first = _plan()
    second = _plan()
    moved = _plan(band_width_ticks=2_000)

    assert first.plan_hash == second.plan_hash
    assert first.plan_hash != moved.plan_hash


# ------------------------------------------------------------------ refusals


def test_a_staked_position_is_refused_rather_than_planned_around():
    """MasterChefV3 owns a staked NFT, so the owner cannot approve it and the route
    would die at its first call."""
    with pytest.raises(MigrationRefused, match="MasterChefV3"):
        _plan(position=_position(staked=True))


def test_a_destination_outside_the_eligible_set_is_not_a_destination():
    outsider = _pool(
        "0xoutside",
        USDT,
        WBNB,
        fee_tier=500,
        tvl=5_000_000,
        volume=1,
        fee=9,
        protocol=3,
    )

    with pytest.raises(MigrationRefused, match="not in the eligible set"):
        _plan(destination=outsider)


def test_an_asset_off_the_move_allowlist_is_refused_on_either_side():
    stranger_pool = _pool(
        "0xstranger",
        USDT,
        STRANGER,
        fee_tier=500,
        tvl=2_000_000,
        volume=1_000_000,
        fee=900,
        protocol=300,
    )
    universe = eligible_pools(
        [CURRENT_POOL, stranger_pool],
        set(ALLOWLIST) | {STRANGER.lower()},
        source=SOURCE,
        observed_at=OBSERVED,
    )

    with pytest.raises(MigrationRefused, match="move allowlist"):
        _plan(destination=stranger_pool, universe=universe)


def test_an_unknown_fee_tier_is_refused_rather_than_given_a_guessed_spacing():
    odd = _pool(
        "0xodd",
        USDT,
        WBNB,
        fee_tier=3_000,
        tvl=2_000_000,
        volume=1_000,
        fee=9,
        protocol=3,
    )
    universe = _universe([CURRENT_POOL, odd])

    with pytest.raises(MigrationRefused, match="fee tier 3000"):
        _plan(destination=odd, universe=universe)


def test_a_position_with_no_liquidity_has_nothing_to_move():
    with pytest.raises(MigrationRefused, match="no liquidity"):
        _plan(position=_position(liquidity=0))


def test_the_owner_and_the_session_may_not_be_the_same_address():
    with pytest.raises(MigrationRefused, match="same address"):
        _plan(session=OWNER)


def test_slippage_outside_the_repositorys_own_ceiling_is_refused():
    for bad in (0, 501):
        with pytest.raises(MigrationRefused, match="max_slippage_bps"):
            _plan(max_slippage_bps=bad)


def test_a_pair_the_factory_names_no_pool_for_is_refused_before_any_bytes():
    class Blind(Reader):
        def pool_state(self, token0, token1, fee):
            return {
                "address": None,
                "tick": None,
                "sqrt_price_x96": None,
                "liquidity": None,
                "block_number": None,
                "observation_time": None,
            }

    with pytest.raises(MigrationRefused, match="could not be read"):
        _plan(reader=Blind())


# ------------------------------------------------------------------ resuming


def test_a_route_interrupted_after_the_collect_resumes_from_the_session_balances():
    """The liquidity is read live rather than taken from the caller's snapshot, so a run
    that burned its position and died before the mint picks up where the chain is."""
    plan = _plan(
        reader=Reader(
            liquidity=0,
            balances={USDT: 5_000 * E18, USDC: 5_000 * E18},
        )
    )
    purposes = [call.purpose for call in plan.calls]

    assert not [p for p in purposes if "burn all" in p]
    assert not [p for p in purposes if "collect everything" in p]
    assert purposes[0].startswith("swap")
    assert purposes[-1].startswith("mint into 0xdest")
    assert plan.disclosure["resumed_from_chain"] is True
    assert "already burned" in plan.disclosure["resume_note"]
    assert plan.disclosure["position"]["removed_amount0"] == str(5_000 * E18)


def test_a_resumed_route_estimates_its_legs_live_because_the_session_holds_them():
    plan = _plan(reader=Reader(liquidity=0, balances={USDT: 5_000 * E18}))

    (leg,) = [c for c in plan.calls if c.to == PANCAKE_V2_ROUTER]
    assert leg.simulation["deferred"] == []
    assert "eth_estimateGas" in leg.simulation["checks"]
    assert leg.simulation["ok"] is True


def test_a_burned_position_whose_session_holds_nothing_has_nothing_to_resume():
    with pytest.raises(MigrationRefused, match="nothing to resume from"):
        _plan(reader=Reader(liquidity=0, balances={}))


def test_a_position_that_still_holds_liquidity_runs_the_whole_route():
    plan = _plan(reader=Reader(liquidity=10**22))

    assert plan.disclosure["resumed_from_chain"] is False
    assert "still holds liquidity" in plan.disclosure["resume_note"]
    assert len(plan.calls) == 7


# ------------------------------------------------------------------ per-call spend


def test_the_spend_is_published_per_call_as_well_as_per_batch():
    """`SessionPolicy.allows` runs once per call, so the batch total handed to every call
    charged an eight-call route eight times what it spends."""
    plan = _plan()
    by_call = plan.session_spend_by_call

    assert len(by_call) == len(plan.calls)
    assert by_call[0] == {}  # decreaseLiquidity takes liquidity out
    assert by_call[1] == {}  # collect takes it out too
    assert set(by_call[2]) == {USDC}
    assert set(by_call[3]) == {USDT}
    assert by_call[4] == {}  # an approval authorises; it does not spend
    assert by_call[5] == {}
    assert set(by_call[6]) == {USDT, WBNB}

    total: dict[str, int] = {}
    for entry in by_call:
        for token, amount in entry.items():
            total[token] = total.get(token, 0) + int(amount)
    assert {token: str(amount) for token, amount in sorted(total.items())} == (
        plan.session_spend
    )


def test_the_per_call_spend_travels_on_the_plan_record():
    plan = _plan()

    assert plan.as_record()["session_spend_by_call"] == [
        dict(entry) for entry in plan.session_spend_by_call
    ]


# ------------------------------------------------------------------ the minors


def test_the_published_gas_ceilings_are_keyed_by_batch_position():
    """Truncating the purpose collided the moment two calls opened with the same words —
    the two exact-amount approvals do — and a collision dropped one silently."""
    plan = _plan()
    ceilings = plan.disclosure["estimated_gas"]["ceilings"]

    assert list(ceilings) == [str(index) for index in range(len(plan.calls))]
    assert ceilings["4"]["to"] == USDT
    assert ceilings["5"]["to"] == WBNB
    assert ceilings["4"]["gas_ceiling"] == ceilings["5"]["gas_ceiling"]


def test_the_verification_read_names_the_right_topic_for_each_log():
    plan = _plan()

    assert "topics[1] of the IncreaseLiquidity log" in plan.verification.identified_by
    assert "topics[3] of the ERC-721 Transfer log" in plan.verification.identified_by
    assert "topics[1] and\ntopics[2]" in plan.verification.identified_by or (
        "topics[1] and topics[2]" in plan.verification.identified_by
    )


# --------------------------------------------- resuming between the two withdrawal calls


def test_a_route_stopped_between_the_burn_and_the_collect_resumes_at_the_collect():
    """Liquidity alone cannot tell the two apart. `decreaseLiquidity` burns into the
    manager's own accounting and `collect` moves it out, so between them the position
    reads zero liquidity and non-zero owed — and a route that looked only at liquidity
    would plan swaps for balances still sitting in the position manager."""
    plan = _plan(reader=Reader(liquidity=0, owed=(4_000 * E18, 4_000 * E18)))
    purposes = [call.purpose for call in plan.calls]

    assert not [p for p in purposes if "burn all" in p]
    assert "collect everything" in purposes[0]
    assert plan.disclosure["position"]["removed_amount0"] == str(4_000 * E18)
    assert plan.disclosure["position"]["removed_amount1"] == str(4_000 * E18)
    assert plan.disclosure["resumed_from_chain"] is False


def test_the_owed_amounts_are_what_the_manager_says_it_owes_not_a_projection():
    plan = _plan(reader=Reader(liquidity=0, owed=(7 * E18, 3 * E18)))

    assert plan.disclosure["position"]["withdrawal_floor0"] == str(7 * E18)
    assert plan.disclosure["position"]["withdrawal_floor1"] == str(3 * E18)


def test_a_destination_token_an_interrupted_leg_already_bought_is_not_bought_again():
    """A resumed route that ignored it would buy the same side twice and leave the first
    purchase stranded in the session."""
    without = _plan(reader=Reader(liquidity=0, balances={USDT: 6_000 * E18}))
    with_wbnb = _plan(
        reader=Reader(liquidity=0, balances={USDT: 6_000 * E18, WBNB: 5 * E18})
    )

    assert int(with_wbnb.disclosure["position"]["mint_amount1_desired"]) > int(
        without.disclosure["position"]["mint_amount1_desired"]
    )


def test_a_position_with_nothing_anywhere_has_nothing_to_resume():
    with pytest.raises(MigrationRefused, match="nothing to resume from"):
        _plan(reader=Reader(liquidity=0, owed=(0, 0), balances={}))


def test_position_state_reads_all_three_words_it_needs():
    from docket.agents.yield_router.migration import position_liquidity, position_state

    reader = Reader(liquidity=99, owed=(11, 22))

    assert position_state(reader, 7141050, owner=OWNER) == (99, 11, 22)
    assert position_liquidity(reader, 7141050, owner=OWNER) == 99
    assert position_state(Reader(liquidity=None), 1, owner=OWNER) is None
