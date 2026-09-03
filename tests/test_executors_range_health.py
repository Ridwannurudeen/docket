"""The two executors: what they read, what they refuse, and what the session may send.

The contract this file holds them to is the one in
`docs/plans/2026-09-03-marketplace-pivot.md`: an executor evaluates against live state,
returns a `Decision`, and offers `prepared` calls only when the chain has agreed with every
one of them that it could be asked about.

**A simulation that reverts is never an action.** Asserted on both executors, because the
whole value of the preflight is that a batch which cannot land does not reach a signer.

**A read that failed is not a preflight that passed.** An endpoint that could not answer
produces an `alert` too. Reporting an outage as agreement is the mistake
`docket/escrow/chain.py` exists to stop.

**`within_policy` reads the contract and the selector together.** ERC-20 and ERC-721
`approve` share `0x095ea7b3`, so a session allowlisting the selector alone would be
allowing a call over the owner's position NFT.

Every reader and every RPC below is a fake. Nothing in this file touches a network.
"""

import dataclasses
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from web3 import Web3

from docket.agents.pancake.keeper import npm_encoder
from docket.agents.pancake.positions import NPM
from docket.jobs.executors import EXECUTORS, Decision, PreparedCall, register
from docket.jobs.executors.allowlists import defaults_for
from docket.jobs.executors.bounds import (
    APPROVE_SELECTOR,
    _same,
    approve_amount,
    parse_expiry,
    policy_field,
    token_spend,
    within_session_policy,
)
from docket.jobs.executors.health import HealthShieldExecutor
from docket.agents.pancake.keeper import V3_SWAP_ROUTER, v3_router_encoder
from docket.execution.simulate import PANCAKE_V2_ROUTER, SWAP_SIGNATURE
from docket.jobs.executors.bounds import simulate_call
from docket.jobs.executors.range import RangeKeeperExecutor
from tests.test_pancake_keeper import (
    OWNER,
    POOL_ABOVE,
    POOL_IN_RANGE,
    POSITION,
    ROW,
    SESSION,
)
from tests.test_venus_shield import (
    E18,
    SUPPLIED_VUSDC,
    USDC,
    USDC_RATE,
    USDT,
    USDT_RATE,
    VUSDC,
    VUSDT,
    _account,
    _row,
    _state,
    _totals,
)

NOW = datetime(2026, 9, 3, 12, 0, 0, tzinfo=timezone.utc)
DECREASE_SELECTOR = "0x0c49ccbe"
SWAP_SELECTOR = "0x" + Web3.keccak(text=SWAP_SIGNATURE)[:4].hex()
MINT_SELECTOR = "0x88316456"
GET_APPROVED = "0x" + Web3.keccak(text="getApproved(uint256)")[:4].hex()
IS_APPROVED_FOR_ALL = (
    "0x" + Web3.keccak(text="isApprovedForAll(address,address)")[:4].hex()
)
BALANCE_OF = "0x70a08231"
ZERO = "0x0000000000000000000000000000000000000000"
TOKEN0 = Web3.to_checksum_address(POSITION["token0"])
TOKEN1 = Web3.to_checksum_address(POSITION["token1"])
# The whole position comes back as token0: the price sits above the range, so the burn
# releases one side only. That is the shape the keeper actually meets.
BURN0 = 1_000_000_000_000_000_000
BURN1 = 0
# What the position's own v3 pool prices the half that gets sold at, and what a healthy
# V2 market quotes against it — 10bps down, inside any sane slippage bound.
FAIR_OUT = BURN0 // 2 * POOL_ABOVE["sqrt_price_x96"] ** 2 // 2**192
QUOTED_OUT = FAIR_OUT * 9_990 // 10_000
# A burn whose two sides are of equal value AT THIS POOL'S PRICE — not of equal count,
# which at any price but 1 is a different thing. This is the inventory that needs no leg.
BALANCED0 = BURN0 // 2
BALANCED1 = BALANCED0 * POOL_ABOVE["sqrt_price_x96"] ** 2 // 2**192


class _Revert(Exception):
    """What a contract refusing looks like coming back through web3."""


class _Eth:
    """A chain that answers the way the real one would, including who is asking.

    `tx["from"]` is honoured rather than ignored: the whole point of the deferral is that
    a call spending tokens the session does not hold yet reverts, and a fake that answered
    every sender identically would let a batch simulated from the wrong address pass.
    """

    def __init__(
        self, *, gas_price, block, reverts, gas, balanced, approved, holdings, authorized
    ):
        self.gas_price = gas_price
        self.block_number = block
        self._reverts = reverts
        self._gas = gas
        self._balanced = balanced
        self._approved = approved
        self._holdings = holdings
        self._authorized = authorized

    def call(self, tx):
        data = tx["data"]
        for selector, reason in self._reverts.items():
            if data.startswith(selector):
                raise _Revert(reason)
        if data.startswith(GET_APPROVED):
            operator = SESSION if self._approved else ZERO
            return bytes.fromhex(operator[2:].rjust(64, "0"))
        if data.startswith(IS_APPROVED_FOR_ALL):
            return (1 if self._approved else 0).to_bytes(32, "big")
        if data.startswith(BALANCE_OF):
            who = Web3.to_checksum_address("0x" + data[34:74])
            return self._holdings.get((tx["to"], who), 0).to_bytes(32, "big")
        sender = Web3.to_checksum_address(tx["from"])
        if data.startswith(DECREASE_SELECTOR):
            # Only the holder is authorised over the token, which is exactly why the close
            # and the collect are asked from that address rather than from the session.
            if sender not in self._authorized:
                raise _Revert("Not approved")
            if self._balanced:
                return BALANCED0.to_bytes(32, "big") + BALANCED1.to_bytes(32, "big")
            return BURN0.to_bytes(32, "big") + BURN1.to_bytes(32, "big")
        if data.startswith((SWAP_SELECTOR, MINT_SELECTOR)):
            # Only a sender that already holds something can spend it. With no holdings
            # the collect has not landed and the call reverts — the revert the deferral
            # exists to keep out of a decision. On a resumed batch the session does hold
            # the inventory, so the same call answers, which is what makes the resume path
            # distinguishable here rather than passing for the same reason as the rest.
            if not any(
                amount for (_, who), amount in self._holdings.items() if who == sender
            ):
                raise _Revert("TRANSFER_FROM_FAILED")
            return b""
        return b""

    def estimate_gas(self, tx):
        return self._gas


class _Rpc:
    """`escrow.chain.Rpc`'s shape: one callable that runs a read against a session."""

    # 50,000 gas is under every ceiling the two agents set, so a test that wants a
    # refusal has to ask for one rather than getting it from the fixture by accident.
    def __init__(
        self,
        *,
        gas_price=10**9,
        block=119_700_000,
        reverts=None,
        gas=50_000,
        balanced=False,
        approved=True,
        holdings=None,
        authorized=(),
    ):
        self._w3 = SimpleNamespace(
            eth=_Eth(
                gas_price=gas_price,
                block=block,
                reverts=reverts or {},
                gas=gas,
                balanced=balanced,
                approved=approved,
                holdings=holdings or {},
                authorized=set(authorized) or {OWNER},
            )
        )
        self.calls = 0

    def __call__(self, do):
        self.calls += 1
        return do(self._w3)


class _DeadRpc:
    def __call__(self, do):
        raise ConnectionError("every endpoint failed")


class _Positions:
    """`PositionReader`'s two methods, answering from fixtures."""

    def __init__(self, *, position=POSITION, pool=POOL_ABOVE, held=1):
        self._position = position
        self._pool = pool
        self._held = held

    def wallet_positions(self, address, *, token_id=None, observation_block=None, **_):
        found = [dict(self._position)] if self._position is not None else []
        return {
            "positions": found,
            "positions_held": self._held,
            "positions_examined": self._held,
            "closed_skipped": 0,
            "open_skipped": 0,
            "target_token_id": token_id,
            "target_found": bool(found),
            "observation_block": 119_700_000,
            "observation_time": "2026-09-03T11:59:00+00:00",
            "scan_complete": True,
            "stopped_by": None,
        }

    def pool_state(self, token0, token1, fee, **_):
        return dict(self._pool)


class _Pools:
    def top_pools(self):
        return [ROW]

    def token_allowlist(self):
        return {ROW["token0"]["id"], ROW["token1"]["id"]}


class _Quotes:
    """`BscQuoteReader`'s one method, answering from a fixture.

    `amounts_out` is a view call, which is why the leg can be priced at a block where the
    session holds nothing — every block before the burn lands.
    """

    def __init__(self, out=QUOTED_OUT):
        self._out = out
        self.asked = []

    def amounts_out(self, amount_in, route):
        self.asked.append((amount_in, tuple(route)))
        return [amount_in, self._out]


class _Venus:
    def __init__(self, state):
        self._state = state

    def account(self, address):
        return self._state


def _activation(**overrides):
    fields = {
        "activation_id": "act_" + "0" * 24,
        "service_id": "range-doctor",
        "category": "rebalancing",
        "kind": "persistent",
        "owner": OWNER,
        "state": "active",
        "policy": None,
        "session": {"address": SESSION},
        "inputs": {},
        "result": None,
        "expires_at": "2026-12-31T00:00:00Z",
    }
    fields.update(overrides)
    return SimpleNamespace(**fields)


def _range_inputs(**overrides):
    fields = {
        "wallet": OWNER,
        "token_id": POSITION["token_id"],
        "declared_position_value_usd": 10_000.0,
        "bnb_usd": 600.0,
        "out_of_range_minutes": 60,
        "min_net_benefit_multiple": 2.0,
        "max_notional_usd": 100_000.0,
        "expires_at": "2026-12-31T00:00:00Z",
    }
    fields.update(overrides)
    return fields


def _observations(minutes: int) -> dict:
    """An `activation.result` shaped the way the tick loop writes one.

    The carry-over lives at `result.last_decision.evidence`, not at `result` itself — a
    one-shot's result lives in the same field, and an executor that read the field
    directly would start every pass blind while looking like it had read something.
    """
    from datetime import timedelta

    return _result(
        {
            "observations": [
                {
                    "observed_at": (NOW - timedelta(minutes=minutes)).isoformat(),
                    "block": 119_600_000,
                    "tick": POOL_ABOVE["tick"],
                    "in_range": False,
                }
            ]
        }
    )


def _result(evidence: dict) -> dict:
    return {"last_decision": {"kind": "noop", "evidence": evidence}}


def _range(**overrides):
    return RangeKeeperExecutor(
        pools=_Pools(),
        rpc=overrides.pop("rpc", _Rpc()),
        quotes=overrides.pop("quotes", _Quotes()),
        clock=lambda: NOW,
        **overrides,
    )


def _session_policy(**overrides):
    fields = {
        "contract_allowlist": [NPM, TOKEN0, TOKEN1, PANCAKE_V2_ROUTER, V3_SWAP_ROUTER],
        "function_allowlist": [
            "0x095ea7b3",
            "0x0c49ccbe",
            "0xfc6f7865",
            "0x88316456",
            SWAP_SELECTOR,
        ],
        "token_allowlist": [TOKEN0, TOKEN1],
        "per_action_limit_atomic": {TOKEN0: 10**30, TOKEN1: 10**30},
        "total_cap_atomic": {TOKEN0: 10**30, TOKEN1: 10**30},
        "max_slippage_bps": 50,
        "max_gas_price_wei": 5 * 10**9,
        "expires_at": "2026-12-31T00:00:00Z",
        "emergency_pause": False,
    }
    fields.update(overrides)
    return fields


# --------------------------------------------------------------- the contract


def test_the_registry_binds_one_executor_to_each_official_category():
    assert EXECUTORS["rebalancing"].category == "rebalancing"
    assert EXECUTORS["health_factor"].category == "health_factor"
    assert isinstance(EXECUTORS["rebalancing"], RangeKeeperExecutor)
    assert isinstance(EXECUTORS["health_factor"], HealthShieldExecutor)


def test_a_second_executor_may_not_claim_a_category_that_is_already_served():
    class Impostor:
        category = "rebalancing"

    with pytest.raises(ValueError, match="already has a registered executor"):
        register("rebalancing", Impostor())
    assert isinstance(EXECUTORS["rebalancing"], RangeKeeperExecutor)


def test_the_two_records_carry_the_landed_field_names_in_the_landed_order():
    """`base.py` is Lane B's file, taken verbatim from `build/pivot-B`. Pinning the shape
    here is what catches the two branches drifting back apart: a field renamed or reordered
    on one side is a merge that resolves silently and a policy that reads the wrong number."""
    assert [f.name for f in dataclasses.fields(PreparedCall)] == [
        "to",
        "data",
        "value_atomic",
        "gas_ceiling",
        "deadline",
        "purpose",
        "simulation",
        "chain_id",
    ]
    assert [f.name for f in dataclasses.fields(Decision)] == [
        "kind",
        "summary",
        "prepared",
        "evidence",
        "observed_at",
        "block",
    ]


# ----------------------------------------------------------- range: decisions


def test_a_position_inside_its_range_produces_no_prepared_call_at_all():
    decision = _range().evaluate(
        _activation(inputs=_range_inputs()), reader=_Positions(pool=POOL_IN_RANGE)
    )
    assert decision.kind == "noop"
    assert decision.prepared == ()


def test_a_position_that_is_due_a_reset_comes_back_with_seven_session_calls():
    """Seven, not eight: the owner's ERC-721 approval is read at evaluate and never
    drafted, because Lane B's loop sends everything in `prepared` from the session."""
    decision = _range().evaluate(
        _activation(inputs=_range_inputs(), result=_observations(180)),
        reader=_Positions(),
    )
    assert decision.kind == "action"
    assert [call.purpose for call in decision.prepared] == [
        "session_closes_position",
        "session_collects_to_fund_the_swap_and_the_mint",
        "session_approves_v2_router_exact",
        "session_balances_the_inventory_on_v2",
        "session_approves_token0_exact",
        "session_approves_token1_exact",
        "session_mints_replacement_to_owner",
    ]
    assert all(call.purpose != "owner_signs" for call in decision.prepared)
    assert decision.evidence["preflight"]["verdict"] == "passed"
    assert decision.block == 119_700_000


def test_the_calls_that_spend_what_the_collect_has_not_released_are_deferred():
    """The swap and the mint would revert with TRANSFER_FROM_FAILED against current state,
    from a session holding nothing until the collect lands. That is a fact about the
    ordering and not about the calls, so they carry `ok: None` and name what they wait on
    — simulating them anyway would end every mainnet tick as an alert."""
    decision = _range().evaluate(
        _activation(inputs=_range_inputs(), result=_observations(180)),
        reader=_Positions(),
    )
    assert [call.simulation["ok"] for call in decision.prepared] == [
        True,
        True,
        True,
        None,
        True,
        True,
        None,
    ]
    for index in (3, 6):
        reason = decision.prepared[index].simulation["revert_reason"]
        assert reason.startswith("deferred: depends on ")
        assert "session_collects_to_fund_the_swap_and_the_mint" in reason
    assert all(
        call.simulation["revert_reason"] is None
        for call in decision.prepared
        if call.simulation["ok"] is True
    )


def test_the_close_and_the_collect_are_asked_of_the_chain_as_the_holder():
    """The fake chain reverts a decreaseLiquidity from anyone but the holder, so a batch
    simulated from the session could not pass this by accident."""
    rpc = _Rpc()
    decision = _range(rpc=rpc).evaluate(
        _activation(inputs=_range_inputs(), result=_observations(180)),
        reader=_Positions(),
    )
    assert decision.kind == "action"
    assert decision.prepared[0].simulation["ok"] is True
    # And a batch whose position-manager calls were asked from anyone else would fail,
    # so this cannot pass by accident if the sender is ever wired up wrongly.
    assert rpc._w3.eth.call(
        {"from": OWNER, "to": NPM, "data": DECREASE_SELECTOR + "00" * 32}
    )
    stranger = Web3.to_checksum_address("0xE4fe23FB57dbb9AC2f685ea29B6b9A1409A0d359")
    with pytest.raises(_Revert):
        rpc._w3.eth.call(
            {"from": stranger, "to": NPM, "data": DECREASE_SELECTOR + "00" * 32}
        )


def test_a_session_the_owner_has_not_approved_over_the_nft_prepares_nothing():
    """An ERC-721 approval can only be made by the NFT's holder, so it is read rather than
    drafted, and the alert carries what the browser step needs to collect it."""
    decision = _range(rpc=_Rpc(approved=False)).evaluate(
        _activation(inputs=_range_inputs(), result=_observations(180)),
        reader=_Positions(),
    )
    assert decision.kind == "alert"
    assert decision.prepared == ()
    assert decision.evidence["needs_nft_approval"] == {
        "contract": NPM,
        "token_id": POSITION["token_id"],
        "session": SESSION,
        "holder": OWNER,
    }
    assert "only its holder can" in decision.summary


def test_the_router_leg_is_quoted_through_the_injected_quote_reader():
    quotes = _Quotes()
    decision = _range(quotes=quotes).evaluate(
        _activation(inputs=_range_inputs(), result=_observations(180)),
        reader=_Positions(),
    )
    assert decision.kind == "action"
    assert quotes.asked == [(BURN0 // 2, (TOKEN0, TOKEN1))]
    swap = decision.evidence["preflight"]["amounts"]["swap"]
    assert swap["venue"] == "v2"
    assert swap["token_in"] == "token0"
    assert swap["amount_in"] == BURN0 // 2
    assert decision.prepared[3].to == PANCAKE_V2_ROUTER
    assert decision.prepared[3].data[:10] == SWAP_SELECTOR


def test_a_venue_quoting_far_below_the_pools_own_price_is_not_used():
    """A pair can exist on V2 in name and be thin enough there to lose most of a position:
    the fixture pool's V2 market quotes 30% down for one unit and 97% down for a hundred.
    An amountOutMin derived from that quote is a floor under a number already wrong, so the
    leg is routed into the v3 pool the position was minted in instead."""
    fair = FAIR_OUT
    decision = _range(quotes=_Quotes(out=fair * 70 // 100)).evaluate(
        _activation(inputs=_range_inputs(), result=_observations(180)),
        reader=_Positions(),
    )
    assert decision.kind == "action"
    venue = decision.evidence["preflight"]["amounts"]["venue"]
    assert venue["venue"] == "v3"
    assert venue["v2_shortfall_bps"] >= 2_900
    assert "routed through the v3 SwapRouter" in venue["reason"]
    swap = decision.prepared[3]
    assert swap.to == V3_SWAP_ROUTER
    assert swap.data[:10] == "0x414bf389"
    assert decision.prepared[2].purpose == "session_approves_v3_router_exact"
    # And the floor is the pool's own price less its fee tier and the policy's bound,
    # never the V2 quote that was rejected.
    _, args = v3_router_encoder.decode_function_input(swap.data)
    floor = fair * 9_950 // 10_000 * (1_000_000 - POSITION["fee"]) // 1_000_000
    assert args["params"]["amountOutMinimum"] == floor
    assert floor > fair * 70 // 100


def test_a_venue_inside_the_bound_is_used_and_the_pools_price_is_still_the_floor():
    """The venue is chosen on its quote; the floor is taken from the pool's own price.
    A quote already inside the bound makes `fair * bound` the tighter of the two, and it
    is the number that does not move when the venue's own book does between the quote and
    the block the swap lands in."""
    quoted = QUOTED_OUT
    decision = _range(quotes=_Quotes(out=quoted)).evaluate(
        _activation(inputs=_range_inputs(), result=_observations(180)),
        reader=_Positions(),
    )
    venue = decision.evidence["preflight"]["amounts"]["venue"]
    assert venue["venue"] == "v2"
    assert venue["v2_shortfall_bps"] == 10
    assert decision.evidence["preflight"]["amounts"]["swap"]["min_output"] == (
        FAIR_OUT * 9_950 // 10_000
    )
    assert FAIR_OUT * 9_950 // 10_000 > quoted * 9_950 // 10_000


def test_the_mint_is_funded_by_the_floor_the_swap_is_held_to():
    """The mint asks for the swap's guaranteed minimum, not its quote. Asking for the
    quote would mean a mint that reverts every time the price moved against the leg."""
    decision = _range().evaluate(
        _activation(inputs=_range_inputs(), result=_observations(180)),
        reader=_Positions(),
    )
    amounts = decision.evidence["preflight"]["amounts"]
    assert amounts["burn0"] == str(BURN0)
    floor = amounts["swap"]["min_output"]
    _, mint = npm_encoder.decode_function_input(decision.prepared[6].data)
    assert mint["params"]["amount0Desired"] == BURN0 - BURN0 // 2
    assert mint["params"]["amount1Desired"] == floor
    assert mint["params"]["recipient"] == OWNER
    assert approve_amount(decision.prepared[5].data) == floor
    assert amounts["swap_plan"]["needed"] is True


def test_an_inventory_that_needs_no_trade_produces_a_five_call_batch_and_says_why():
    decision = _range(rpc=_Rpc(balanced=True)).evaluate(
        _activation(inputs=_range_inputs(), result=_observations(180)),
        reader=_Positions(),
    )
    assert decision.kind == "action"
    assert [call.purpose for call in decision.prepared] == [
        "session_closes_position",
        "session_collects_to_fund_the_swap_and_the_mint",
        "session_approves_token0_exact",
        "session_approves_token1_exact",
        "session_mints_replacement_to_owner",
    ]
    amounts = decision.evidence["preflight"]["amounts"]
    assert amounts["swap"] is None
    assert amounts["swap_plan"]["needed"] is False
    assert "already tolerates" in amounts["swap_plan"]["reason"]


def test_a_venue_that_cannot_quote_at_all_falls_back_to_the_positions_own_pool():
    """`exactInputSingle` routes by (tokenIn, tokenOut, fee) rather than by pool address,
    and the position exists — so its pool does. A V2 router that cannot answer is a reason
    to use the other venue, never a reason to abandon the reset."""

    class _Dead:
        def amounts_out(self, amount_in, route):
            raise RuntimeError("every endpoint failed")

    decision = _range(quotes=_Dead()).evaluate(
        _activation(inputs=_range_inputs(), result=_observations(180)),
        reader=_Positions(),
    )
    assert decision.kind == "action"
    venue = decision.evidence["preflight"]["amounts"]["venue"]
    assert venue["venue"] == "v3"
    assert venue["v2_quote"] is None
    assert "could not quote this route" in venue["reason"]
    assert decision.prepared[3].to == V3_SWAP_ROUTER


def test_a_staked_position_is_refused_because_the_farm_holds_its_nft():
    decision = _range().evaluate(
        _activation(inputs=_range_inputs(), result=_observations(180)),
        reader=_Positions(position=dict(POSITION, staked=True)),
    )
    assert decision.kind == "alert"
    assert decision.prepared == ()
    assert "Unstake from MasterChefV3 first" in decision.summary


def test_a_batch_that_stopped_after_the_collect_is_resumed_rather_than_restarted():
    """Liquidity zero and the tokens still in the session is a reset half done, not a
    position with nothing left to do. Starting again would burn what is already burnt."""
    holdings = {(TOKEN0, SESSION): BURN0, (TOKEN1, SESSION): 0}
    decision = _range(rpc=_Rpc(holdings=holdings)).evaluate(
        _activation(inputs=_range_inputs(), result=_observations(180)),
        reader=_Positions(position=dict(POSITION, liquidity=0)),
    )
    assert decision.kind == "action"
    assert [call.purpose for call in decision.prepared] == [
        "session_approves_v2_router_exact",
        "session_balances_the_inventory_on_v2",
        "session_approves_token0_exact",
        "session_approves_token1_exact",
        "session_mints_replacement_to_owner",
    ]
    assert decision.evidence["preflight"]["resumed"] is True
    assert decision.evidence["resuming"]["session_inventory"]["token0"] == str(BURN0)


def test_a_closed_position_the_session_holds_nothing_for_is_still_a_noop():
    decision = _range().evaluate(
        _activation(inputs=_range_inputs(), result=_observations(180)),
        reader=_Positions(position=dict(POSITION, liquidity=0)),
    )
    assert decision.kind == "noop"
    assert decision.prepared == ()


def test_a_call_the_chain_refuses_is_reported_as_an_alert_and_never_as_an_action():
    decision = _range(
        rpc=_Rpc(reverts={DECREASE_SELECTOR: "Price slippage check"})
    ).evaluate(
        _activation(inputs=_range_inputs(), result=_observations(180)),
        reader=_Positions(),
    )
    assert decision.kind == "alert"
    assert "Price slippage check" in decision.summary


def test_a_gas_estimate_above_a_calls_own_ceiling_is_refused():
    decision = _range(rpc=_Rpc(gas=10_000_000)).evaluate(
        _activation(inputs=_range_inputs(), result=_observations(180)),
        reader=_Positions(),
    )
    assert decision.kind == "alert"
    assert "above its ceiling" in decision.summary


def test_an_endpoint_that_could_not_answer_is_not_read_as_agreement():
    decision = _range(rpc=_DeadRpc()).evaluate(
        _activation(inputs=_range_inputs(), result=_observations(180)),
        reader=_Positions(),
    )
    assert decision.kind == "alert"
    assert decision.prepared == ()
    assert "gas price could not be read" in decision.summary


def test_a_reset_with_no_session_to_send_it_prepares_nothing():
    decision = _range().evaluate(
        _activation(inputs=_range_inputs(), result=_observations(180), session=None),
        reader=_Positions(),
    )
    assert decision.kind == "alert"
    assert decision.prepared == ()
    assert "funds a session" in decision.summary


def test_a_position_the_wallet_does_not_hold_is_reported_rather_than_acted_on():
    decision = _range().evaluate(
        _activation(inputs=_range_inputs()), reader=_Positions(position=None, held=4)
    )
    assert decision.kind == "alert"
    assert "was not found among the 4" in decision.summary


def test_each_evaluation_hands_its_observation_forward_for_the_next_one():
    """The tick loop is stateless, so time out of range can only be measured if the
    observation list travels through the activation's own result."""
    executor = _range()
    first = executor.evaluate(_activation(inputs=_range_inputs()), reader=_Positions())
    assert first.kind == "noop"
    assert len(first.evidence["observations"]) == 1
    assert first.evidence["observations"][0]["in_range"] is False
    second = executor.evaluate(
        _activation(inputs=_range_inputs(), result=_result(first.evidence)),
        reader=_Positions(),
    )
    assert len(second.evidence["observations"]) == 2


def test_a_simulation_records_which_question_the_chain_was_actually_asked():
    call = PreparedCall(
        to=TOKEN0,
        data="0x095ea7b3" + "00" * 64,
        value_atomic="0",
        chain_id=56,
        gas_ceiling=60_000,
        deadline=0,
        purpose="probe",
        # `PreparedCall` refuses a simulation slot with no `ok` in it: a call nobody asked
        # the chain about is not the same thing as one the chain agreed to.
        simulation={"ok": None},
    )
    record, outcome = simulate_call(call, sender=OWNER, rpc=_Rpc(gas=50_000))
    assert outcome == "passed"
    assert record == {
        "ok": True,
        "gas_estimate": 50_000,
        "revert_reason": None,
        "observed_at": record["observed_at"],
        "block": 119_700_000,
    }
    record, outcome = simulate_call(call, sender=OWNER, rpc=_DeadRpc())
    assert outcome == "unreadable"
    assert record["ok"] is None


# ------------------------------------------------------------ health: decisions


def _health(**overrides):
    return HealthShieldExecutor(
        rpc=overrides.pop("rpc", _Rpc()), clock=lambda: NOW, **overrides
    )


def _health_inputs(**overrides):
    fields = {
        "wallet": OWNER,
        "min_collateral_ratio": 1.25,
        "max_rescue_atomic": {USDT: 10**30, USDC: 10**30},
        "allowed_vtokens": [VUSDT, VUSDC],
        "mode": "repay",
        "expires_at": "2026-12-31T00:00:00Z",
    }
    fields.update(overrides)
    return fields


def _borrower(borrowed):
    return _state(
        _row(
            VUSDC,
            symbol="vUSDC",
            cf=825 * 10**15,
            supplied=SUPPLIED_VUSDC,
            rate=USDC_RATE,
        ),
        _row(VUSDT, symbol="vUSDT", cf=800 * 10**15, borrowed=borrowed, rate=USDT_RATE),
        address=OWNER,
    )


def _underwater():
    weighted, _ = _totals(_account(0))
    return _borrower(weighted)


def test_an_account_above_the_line_produces_no_prepared_call():
    decision = _health().evaluate(
        _activation(category="health_factor", inputs=_health_inputs()),
        reader=_Venus(_borrower(100 * E18)),
    )
    assert decision.kind == "noop"
    assert decision.prepared == ()


def test_an_account_below_the_line_comes_back_with_an_exact_approval_and_the_repay():
    decision = _health().evaluate(
        _activation(category="health_factor", inputs=_health_inputs()),
        reader=_Venus(_underwater()),
    )
    assert decision.kind == "action"
    approve, repay = decision.prepared
    assert approve.to == USDT and approve.purpose == "session_approves_vtoken_exact"
    assert repay.to == VUSDT and repay.data[:10] == "0x2608f818"
    assert approve.simulation["ok"] is True
    assert repay.simulation["ok"] is None
    assert "deferred: depends on" in repay.simulation["revert_reason"]
    assert int(decision.evidence["remedy"]["post_action"]["collateral_ratio"]) >= int(
        1.25 * E18
    )


def test_an_approval_the_chain_refuses_is_an_alert_and_never_an_action():
    decision = _health(
        rpc=_Rpc(reverts={APPROVE_SELECTOR: "SafeERC20: approve failed"})
    ).evaluate(
        _activation(category="health_factor", inputs=_health_inputs()),
        reader=_Venus(_underwater()),
    )
    assert decision.kind == "alert"
    assert "approve failed" in decision.summary


def test_a_repay_with_no_session_prepares_nothing():
    decision = _health().evaluate(
        _activation(category="health_factor", inputs=_health_inputs(), session=None),
        reader=_Venus(_underwater()),
    )
    assert decision.kind == "alert"
    assert "funds a session" in decision.summary


def test_a_collateral_add_is_reported_for_the_owner_and_never_offered_for_execution():
    """`mint` credits whoever sends it. A session sending one would buy vTokens for itself
    with the owner's float while the borrower's collateral stayed exactly where it was, and
    Lane B's loop sends everything in `prepared` from the session — so these two calls
    travel in evidence instead, ready for the owner to sign."""
    decision = _health().evaluate(
        _activation(
            category="health_factor",
            inputs=_health_inputs(
                mode="add_collateral", max_rescue_atomic={USDC: 10**30}
            ),
            session=None,
        ),
        reader=_Venus(_underwater()),
    )
    assert decision.kind == "alert"
    assert decision.prepared == ()
    owner_calls = decision.evidence["owner_calls"]
    assert [call["purpose"] for call in owner_calls] == ["owner_signs", "owner_signs"]
    assert owner_calls[1]["data"][:10] == "0xa0712d68"
    assert "no on-behalf form" in decision.summary
    assert decision.evidence.get("token_amounts", {}) == {}


# ------------------------------------------------- what the policy engine reads


def test_the_batch_declares_what_it_lets_the_session_spend_per_token():
    """`SessionPolicy.allows` is handed this mapping and sees zero spend without it. Every
    figure in it is read back out of an approval in the batch, so the number the cap is
    checked against and the bytes that do the spending cannot describe different things."""
    decision = _action()
    spend = decision.evidence["token_amounts"]
    floor = FAIR_OUT * 9_950 // 10_000
    # token0 is approved twice — once to the router for the leg, once to the position
    # manager for the mint — and the declared spend is the sum of the two.
    assert spend == {TOKEN0: str(BURN0), TOKEN1: str(floor)}
    assert int(spend[TOKEN0]) == BURN0
    # And per call, because the tick loop charges each call against the cap separately.
    by_call = decision.evidence["token_amounts_by_call"]
    assert [entry["purpose"] for entry in by_call] == [
        call.purpose for call in decision.prepared
    ]
    assert by_call[2]["spends"] == {TOKEN0: str(BURN0 // 2)}
    assert by_call[4]["spends"] == {TOKEN0: str(BURN0 - BURN0 // 2)}
    assert by_call[5]["spends"] == {TOKEN1: str(floor)}
    assert decision.evidence["slippage_bps"] == 50
    # Derived from the calldata, not carried beside it.
    assert spend == token_spend(decision.prepared)


def test_no_owner_signed_call_reaches_the_spend_mapping_because_none_is_prepared():
    """The ERC-721 approval is the owner's own transaction over their own NFT, and it is
    read at evaluate rather than drafted. Nothing in `prepared` is the owner's, so nothing
    in the spend mapping is either — and the NFT's token id is never read as an amount."""
    decision = _action()
    assert all(call.purpose != "owner_signs" for call in decision.prepared)
    assert NPM not in decision.evidence["token_amounts"]


def test_a_repay_declares_the_one_approval_it_makes():
    decision = _health().evaluate(
        _activation(category="health_factor", inputs=_health_inputs()),
        reader=_Venus(_underwater()),
    )
    assert decision.kind == "action"
    amount = decision.evidence["remedy"]["amount_atomic"]
    assert decision.evidence["token_amounts"] == {USDT: str(amount)}
    # No minimum-out argument exists on either Venus write, so there is no price to slip
    # against and zero is the fact rather than a default nobody set.
    assert decision.evidence["slippage_bps"] == 0
    assert "no minimum-out argument" in decision.evidence["slippage_bps_means"]


def test_a_collateral_add_declares_no_session_spend_because_no_session_sends_it():
    decision = _health().evaluate(
        _activation(
            category="health_factor",
            inputs=_health_inputs(mode="add_collateral", max_rescue_atomic={USDC: 10**30}),
            session=None,
        ),
        reader=_Venus(_underwater()),
    )
    assert decision.kind == "alert"
    assert decision.evidence.get("token_amounts", {}) == {}


def test_the_batch_names_the_tokens_the_spend_accounting_cannot_read():
    """`docket/sessions/spend.py` refuses a call it cannot derive a spend from, and a
    position id names no tokens at all. The hint carries the pair so the tick does not have
    to spend a chain read discovering it."""
    decision = _action()
    assert decision.evidence["token_hints"] == {
        "position_tokens": {str(POSITION["token_id"]): [TOKEN0, TOKEN1]}
    }
    assert set(decision.evidence["touched_tokens"]) >= {
        NPM,
        TOKEN0,
        TOKEN1,
        PANCAKE_V2_ROUTER,
    }


def test_the_batch_names_what_the_session_will_be_holding_afterwards():
    """A revoke sweeps what it is told to look for. The swap pays one side of the pair in,
    the collect sweeps fees in both, and whatever the mint does not consume stays put — so
    both tokens have to be named or the residue is stranded."""
    decision = _action()
    assert decision.evidence["received_tokens"] == [TOKEN0, TOKEN1]


def test_a_repay_names_the_underlying_its_amount_is_denominated_in():
    """A Venus amount is in the vToken's underlying and the calldata does not say so. An
    unhinted vToken is an UnmeasuredSpend rather than a zero, so the mapping travels."""
    decision = _health().evaluate(
        _activation(category="health_factor", inputs=_health_inputs()),
        reader=_Venus(_underwater()),
    )
    assert decision.evidence["token_hints"]["underlying"][VUSDT] == USDT
    # A repay hands nothing back, and the empty list says so rather than being omitted.
    assert decision.evidence["received_tokens"] == []
    assert set(decision.evidence["touched_tokens"]) == {USDT, VUSDT}


def test_every_call_the_batch_sends_is_one_the_category_default_already_allows():
    """Lane B's table is what a browser fills a session policy from. An executor whose
    target or selector is outside its own category's defaults is a session that silently
    cannot act — so the two are compared here rather than trusted to agree."""
    defaults = defaults_for("rebalancing")
    contracts = {Web3.to_checksum_address(a) for a in defaults["contract_allowlist"]}
    selectors = set(defaults["function_allowlist"])
    for call in _action().prepared:
        assert call.selector in selectors, call.purpose
        # TOKEN0/TOKEN1 are the fixture pair rather than the table's USDT/WBNB, so only
        # the contracts the table can name are compared.
        if Web3.to_checksum_address(call.to) in (TOKEN0, TOKEN1):
            continue
        assert Web3.to_checksum_address(call.to) in contracts, call.purpose

    health = defaults_for("health_factor")
    decision = _health().evaluate(
        _activation(category="health_factor", inputs=_health_inputs()),
        reader=_Venus(_underwater()),
    )
    for call in decision.prepared:
        assert call.selector in set(health["function_allowlist"]), call.purpose
        assert Web3.to_checksum_address(call.to) in {
            Web3.to_checksum_address(a) for a in health["contract_allowlist"]
        }, call.purpose


def test_the_v3_fallback_needs_the_router_and_its_selector_in_the_category_default():
    """The two entries Lane B is adding to `rebalancing`, asserted against the end state.

    The v3 leg exists because a pair can be untradeable on V2 — the fixture pair quotes 97%
    down for a hundred units — so a session granted the defaults must be able to send it.
    Marked `xfail(strict=True)`: it fails today for a reason named in the marker, and it
    turns red the moment it starts passing, which is the day the marker must come off.
    Lane B is also adding `exactInputSingle` to `spend.py MEASURED_SELECTORS`; without that
    the leg's spend is charged as zero, and this file cannot assert it from here.
    """
    defaults = defaults_for("rebalancing")
    contracts = {Web3.to_checksum_address(a) for a in defaults["contract_allowlist"]}
    assert V3_SWAP_ROUTER in contracts, (
        "allowlists.py must name the v3 SwapRouter for rebalancing"
    )
    assert "0x414bf389" in set(defaults["function_allowlist"]), (
        "allowlists.py must name exactInputSingle for rebalancing"
    )


test_the_v3_fallback_needs_the_router_and_its_selector_in_the_category_default = (
    pytest.mark.xfail(
        strict=True,
        reason=(
            "Lane B is adding V3_SWAP_ROUTER and 0x414bf389 to the rebalancing defaults "
            "and exactInputSingle to spend.py MEASURED_SELECTORS. Until both land, a v3 "
            "leg is built and then refused by the session's own policy, and its spend "
            "would be charged as zero. Remove this marker when they land."
        ),
    )(test_the_v3_fallback_needs_the_router_and_its_selector_in_the_category_default)
)


def test_a_v3_routed_batch_is_refused_by_the_defaults_until_that_lands():
    """The refusal a reader gets today, so the gap is visible rather than theoretical.
    It asserts the shape of the answer either way, so it keeps passing once B lands."""
    decision = _range(quotes=_Quotes(out=FAIR_OUT * 70 // 100)).evaluate(
        _activation(inputs=_range_inputs(), result=_observations(180)),
        reader=_Positions(),
    )
    assert decision.evidence["preflight"]["amounts"]["venue"]["venue"] == "v3"
    defaults = defaults_for("rebalancing")
    policy = dict(
        defaults,
        expires_at="2026-12-31T00:00:00Z",
        contract_allowlist=[*defaults["contract_allowlist"], TOKEN0, TOKEN1],
        token_allowlist=[*defaults["token_allowlist"], TOKEN0, TOKEN1],
        per_action_limit_atomic={
            **defaults["per_action_limit_atomic"],
            TOKEN0: 10**30,
            TOKEN1: 10**30,
        },
        total_cap_atomic={
            **defaults["total_cap_atomic"],
            TOKEN0: 10**30,
            TOKEN1: 10**30,
        },
    )
    ok, reason = _range().within_policy(
        _activation(inputs=_range_inputs(), policy=policy), decision
    )
    if V3_SWAP_ROUTER in {
        Web3.to_checksum_address(a) for a in defaults["contract_allowlist"]
    }:
        assert ok is True, reason
    else:
        assert ok is False
        assert V3_SWAP_ROUTER in reason


# --------------------------------------------------------- the native token key


def test_a_policy_that_caps_gas_does_not_take_the_whole_tick_down():
    """Gas is a spend like any other and `SessionPolicy.allows` folds it in under the
    native key `"BNB"`, which is not an address. Checksumming it raises, and this walk sits
    in front of every send with no try around it in `tick.py` — so a policy listing "BNB"
    before the token being checked would take down every other owner's activation on the
    same pass rather than refuse one call."""
    decision = _action()
    policy = _session_policy(
        token_allowlist=["BNB", TOKEN0, TOKEN1],
        per_action_limit_atomic={"BNB": 10**16, TOKEN0: 10**30, TOKEN1: 10**30},
        total_cap_atomic={"BNB": 10**17, TOKEN0: 10**30, TOKEN1: 10**30},
    )
    ok, reason = _range().within_policy(
        _activation(inputs=_range_inputs(), policy=policy), decision
    )
    assert ok is True, reason
    assert _same("BNB", "BNB") is True
    assert _same("BNB", TOKEN0) is False
    assert _same("not-an-address", TOKEN0) is False


# ------------------------------------------------- the cost the venue actually is


def test_a_v2_and_a_v3_routed_reset_are_not_priced_the_same():
    """`_economics` runs before a venue exists and assumes the worse of the two. Once the
    leg is priced the real cost is known, and publishing the assumption instead would
    publish a cost nobody is going to pay and a multiple computed from it."""
    on_v2 = _range().evaluate(
        _activation(inputs=_range_inputs(), result=_observations(180)),
        reader=_Positions(),
    )
    on_v3 = _range(quotes=_Quotes(out=FAIR_OUT * 70 // 100)).evaluate(
        _activation(inputs=_range_inputs(), result=_observations(180)),
        reader=_Positions(),
    )
    assert on_v2.kind == on_v3.kind == "action"
    v2 = on_v2.evidence["economics"]
    v3 = on_v3.evidence["economics"]
    assert v2["swap_venue"] == "v2" and v3["swap_venue"] == "v3"
    # V2 pays its own 25bps plus the shortfall its quote showed; the v3 leg pays the
    # pool's 0.01% tier, which is twenty-five times less.
    assert v2["swap_fee_bps_charged"] == 25 + v2["swap_shortfall_bps"]
    assert v3["swap_fee_bps_charged"] == POSITION["fee"] / 100 == 1.0
    assert v3["swap_cost_usd"] < v2["swap_cost_usd"]
    assert v3["net_benefit_multiple"] > v2["net_benefit_multiple"]
    # Both carry what they were authorised against, so the change is auditable.
    assert v2["recosted_from_assumption"]["swap_fee_bps"] == 25
    assert v3["total_cost_usd"] != v3["recosted_from_assumption"]["total_cost_usd"]


def test_a_reset_that_stops_clearing_its_multiple_at_the_real_venue_is_not_offered():
    """The decision was authorised against an assumed cost. A venue quoting worse can push
    the real cost past the multiple its owner set, and acting on the assumption would be
    acting on a number nobody is going to pay."""
    # The multiple the decision was AUTHORISED against — computed before a venue existed,
    # from V2's fee plus the policy's bound and no shortfall at all.
    assumed = _action().evidence["economics"]["recosted_from_assumption"][
        "net_benefit_multiple"
    ]
    # A policy set exactly at it: the assumption clears by a hair, and the shortfall the
    # venue's own quote shows is enough to put the real cost past it.
    decision = _range().evaluate(
        _activation(
            inputs=_range_inputs(min_net_benefit_multiple=assumed),
            result=_observations(180),
        ),
        reader=_Positions(),
    )
    assert decision.kind == "alert"
    assert decision.prepared == ()
    assert "is not offered at the venue it would actually use" in decision.summary
    assert decision.evidence["economics"]["net_benefit_multiple"] < assumed
    assert decision.evidence["economics"]["swap_shortfall_bps"] > 0


def test_a_refused_resume_says_where_the_money_is():
    """A burnt position whose inventory sits in Docket's session is not a quiet noop. An
    owner reading "no reset is offered" has to be told the tokens are not where they were."""
    holdings = {(TOKEN0, SESSION): BURN0, (TOKEN1, SESSION): 0}
    decision = _range(rpc=_Rpc(holdings=holdings)).evaluate(
        _activation(
            inputs=_range_inputs(min_net_benefit_multiple=10_000.0),
            result=_observations(180),
        ),
        reader=_Positions(position=dict(POSITION, liquidity=0)),
    )
    assert decision.kind == "alert"
    assert "already burnt" in decision.summary
    assert "sitting in Docket's session" in decision.summary
    assert "revoked, which sweeps it back to you" in decision.summary


def test_a_resumed_swap_waits_on_nothing_because_the_collect_is_not_in_the_batch():
    """Deferring against a call that is not in the list would report a preflight nobody
    could satisfy, and would hide a swap that genuinely cannot land."""
    holdings = {(TOKEN0, SESSION): BURN0, (TOKEN1, SESSION): 0}
    decision = _range(rpc=_Rpc(holdings=holdings)).evaluate(
        _activation(inputs=_range_inputs(), result=_observations(180)),
        reader=_Positions(position=dict(POSITION, liquidity=0)),
    )
    assert decision.kind == "action"
    swap = decision.prepared[1]
    assert swap.purpose == "session_balances_the_inventory_on_v2"
    assert swap.simulation["ok"] is True
    mint = decision.prepared[4]
    assert mint.simulation["ok"] is None
    assert mint.simulation["revert_reason"] == "deferred: depends on the swap that precedes it"


# ------------------------------------------------------- the tick loop's reader


class _BareRpc(_Rpc):
    """What `docket/jobs/tick.py` actually passes: the loop's own `escrow.chain.Rpc`.

    A bare callable with no reader methods on it at all, which is the whole point — an
    executor that assumed a `PositionReader` would fail on the first real tick.
    """

    def __getattr__(self, name):
        raise AttributeError(name)


def test_the_range_executor_builds_its_reader_from_a_bare_rpc(monkeypatch):
    rpc = _BareRpc()
    assert not hasattr(rpc, "wallet_positions")
    read = {}

    def _wallet_positions(self, address, *, token_id=None, observation_block=None, **_):
        read["through"] = self._through
        return _Positions().wallet_positions(
            address, token_id=token_id, observation_block=observation_block
        )

    monkeypatch.setattr(
        "docket.jobs.executors.range._RpcPositionReader.wallet_positions",
        _wallet_positions,
    )
    monkeypatch.setattr(
        "docket.jobs.executors.range._RpcPositionReader.pool_state",
        lambda self, *a, **k: dict(POOL_ABOVE),
    )
    executor = RangeKeeperExecutor(
        pools=_Pools(), quotes=_Quotes(), clock=lambda: NOW
    )
    decision = executor.evaluate(
        _activation(inputs=_range_inputs(), result=_observations(180)), reader=rpc
    )
    assert decision.kind == "action"
    # Every read went through the loop's own failover rather than a pool this module
    # opened for itself.
    assert read["through"] is rpc


def test_the_health_executor_builds_its_reader_from_a_bare_rpc(monkeypatch):
    rpc = _BareRpc()
    assert not hasattr(rpc, "account")
    built = {}

    class _Reader:
        def __init__(self, *args, **kwargs):
            built["rpc"] = kwargs.get("rpc")

        def account(self, address):
            return _underwater()

    monkeypatch.setattr("docket.jobs.executors.health.VenusReader", _Reader)
    decision = HealthShieldExecutor(clock=lambda: NOW).evaluate(
        _activation(category="health_factor", inputs=_health_inputs()), reader=rpc
    )
    assert built["rpc"] is rpc
    assert decision.kind == "action"


# --------------------------------------------------- the persistence dependency


def test_a_watch_with_no_carried_observation_says_so_rather_than_reading_as_nothing_due():
    """The first pass of a watch and a watch whose carry-over broke look identical from
    the outside, and both report zero elapsed time. Saying only "nothing due" would leave
    a reader unable to tell "it has not been out long enough" from "nothing was measured"."""
    decision = _range().evaluate(
        _activation(inputs=_range_inputs()), reader=_Positions()
    )
    assert decision.kind == "noop"
    assert decision.evidence["time_out_of_range"]["prior_observations"] == 0
    assert "No earlier observation is carried forward" in decision.summary
    assert "nothing to measure against" in decision.summary
    # And the moment one is carried forward, the sentence goes away.
    carried = _range().evaluate(
        _activation(inputs=_range_inputs(), result=_observations(30)),
        reader=_Positions(),
    )
    assert "No earlier observation was carried forward" not in carried.summary


# ---------------------------------------------------------------- policy gate


def _action():
    return _range().evaluate(
        _activation(inputs=_range_inputs(), result=_observations(180)),
        reader=_Positions(),
    )


def test_a_session_that_allowlists_every_contract_and_selector_covers_the_batch():
    decision = _action()
    ok, reason = _range().within_policy(
        _activation(inputs=_range_inputs(), policy=_session_policy()), decision
    )
    assert ok is True
    assert "inside the contract, function, token and cap bounds" in reason


@pytest.mark.parametrize(
    ("overrides", "fragment"),
    [
        (
            {"contract_allowlist": [TOKEN0, TOKEN1]},
            "is not on the session's contract allowlist",
        ),
        (
            {"function_allowlist": ["0x095ea7b3"]},
            "is not on the session's function allowlist",
        ),
        ({"per_action_limit_atomic": {TOKEN0: 1, TOKEN1: 1}}, "per-action limit"),
        ({"total_cap_atomic": {TOKEN0: 1, TOKEN1: 1}}, "total cap"),
        ({"emergency_pause": True}, "is paused"),
        ({"expires_at": "2026-01-01T00:00:00Z"}, "session policy expired"),
        ({"max_gas_price_wei": 1}, "above the session policy's ceiling"),
    ],
)
def test_a_session_that_does_not_cover_a_call_refuses_the_whole_batch(
    overrides, fragment
):
    decision = _action()
    ok, reason = _range().within_policy(
        _activation(inputs=_range_inputs(), policy=_session_policy(**overrides)),
        decision,
    )
    assert ok is False
    assert fragment in reason


def test_a_token_approved_twice_is_capped_on_the_sum_and_not_on_each_half():
    """The keeper approves token0 twice — for the router and for the position manager —
    and `docket/sessions/policy.py` is handed the sum. A gate that only ever looked at one
    approval at a time would pass a batch the chain side then refuses, and Docket's own
    checks must refuse more than the chain's, never less."""
    decision = _action()
    half = BURN0 // 2
    # Either half fits; the sum does not.
    policy = _session_policy(
        per_action_limit_atomic={TOKEN0: half + 1, TOKEN1: 10**30},
        total_cap_atomic={TOKEN0: 10**30, TOKEN1: 10**30},
    )
    ok, reason = _range().within_policy(
        _activation(inputs=_range_inputs(), policy=policy), decision
    )
    assert ok is False
    assert "across its approvals" in reason
    assert str(BURN0) in reason


def test_a_batch_with_no_session_policy_at_all_is_refused():
    ok, reason = _range().within_policy(_activation(inputs=_range_inputs()), _action())
    assert ok is False
    assert "no session policy was granted" in reason


def test_a_policy_is_read_the_same_whether_it_arrived_as_json_or_as_an_object():
    stored = _session_policy()
    hydrated = SimpleNamespace(**stored)
    for policy in (stored, hydrated):
        assert policy_field(policy, "max_slippage_bps") == 50
        ok, _ = within_session_policy(
            policy, _action().prepared, gas_price_wei=10**9, now=NOW
        )
        assert ok is True
    assert policy_field(None, "max_slippage_bps", 7) == 7


def test_an_instant_without_a_timezone_is_refused_rather_than_read_as_utc():
    with pytest.raises(ValueError, match="carries no timezone"):
        parse_expiry("2026-12-31T00:00:00")
    assert parse_expiry("2026-12-31T00:00:00Z").tzinfo is not None
