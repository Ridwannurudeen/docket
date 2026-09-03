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
from docket.jobs.executors.bounds import (
    APPROVE_SELECTOR,
    approve_amount,
    parse_expiry,
    policy_field,
    token_spend,
    within_session_policy,
)
from docket.jobs.executors.health import HealthShieldExecutor
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
TOKEN0 = Web3.to_checksum_address(POSITION["token0"])
TOKEN1 = Web3.to_checksum_address(POSITION["token1"])
# The whole position comes back as token0: the price sits above the range, so the burn
# releases one side only. That is the shape the keeper actually meets.
BURN0 = 1_000_000_000_000_000_000
BURN1 = 0
# What the fake router answers for the half that gets sold.
QUOTED_OUT = 321_000_000_000_000_000
# A burn whose two sides are of equal value AT THIS POOL'S PRICE — not of equal count,
# which at any price but 1 is a different thing. This is the inventory that needs no leg.
BALANCED0 = BURN0 // 2
BALANCED1 = BALANCED0 * POOL_ABOVE["sqrt_price_x96"] ** 2 // 2**192


class _Revert(Exception):
    """What a contract refusing looks like coming back through web3."""


class _Eth:
    def __init__(self, *, gas_price, block, reverts, gas, balanced):
        self.gas_price = gas_price
        self.block_number = block
        self._reverts = reverts
        self._gas = gas
        self._balanced = balanced

    def call(self, tx):
        for selector, reason in self._reverts.items():
            if tx["data"].startswith(selector):
                raise _Revert(reason)
        if tx["data"].startswith(DECREASE_SELECTOR):
            # decreaseLiquidity returns (amount0, amount1). `balanced` releases equal
            # value on both sides, which is the inventory that needs no leg.
            if self._balanced:
                return BALANCED0.to_bytes(32, "big") + BALANCED1.to_bytes(32, "big")
            return BURN0.to_bytes(32, "big") + BURN1.to_bytes(32, "big")
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
    ):
        self._w3 = SimpleNamespace(
            eth=_Eth(
                gas_price=gas_price,
                block=block,
                reverts=reverts or {},
                gas=gas,
                balanced=balanced,
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
    from datetime import timedelta

    return {
        "observations": [
            {
                "observed_at": (NOW - timedelta(minutes=minutes)).isoformat(),
                "block": 119_600_000,
                "tick": POOL_ABOVE["tick"],
                "in_range": False,
            }
        ]
    }


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
        "contract_allowlist": [NPM, TOKEN0, TOKEN1, PANCAKE_V2_ROUTER],
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


def test_a_position_that_is_due_a_reset_comes_back_with_the_whole_simulated_batch():
    """The whole ordered sequence, every call answered by the chain in its own right —
    nothing skipped, nothing inferred from a neighbour."""
    decision = _range().evaluate(
        _activation(inputs=_range_inputs(), result=_observations(180)),
        reader=_Positions(),
    )
    assert decision.kind == "action"
    assert [call.purpose for call in decision.prepared] == [
        "owner_signs",
        "session_closes_position",
        "session_collects_to_fund_the_swap_and_the_mint",
        "session_approves_router_exact",
        "session_balances_the_inventory",
        "session_approves_token0_exact",
        "session_approves_token1_exact",
        "session_mints_replacement_to_owner",
    ]
    assert decision.evidence["preflight"]["verdict"] == "passed"
    assert [call.simulation["ok"] for call in decision.prepared] == [True] * 8
    assert all(
        call.simulation["revert_reason"] is None for call in decision.prepared
    ), "nothing in the batch is deferred any more"
    assert all(call.simulation["block"] == 119_700_000 for call in decision.prepared)
    assert all(call.simulation["gas_estimate"] == 50_000 for call in decision.prepared)
    assert decision.block == 119_700_000


def test_the_router_leg_is_quoted_through_the_injected_quote_reader():
    quotes = _Quotes()
    decision = _range(quotes=quotes).evaluate(
        _activation(inputs=_range_inputs(), result=_observations(180)),
        reader=_Positions(),
    )
    assert decision.kind == "action"
    # Half the one-sided inventory, priced along the token0 -> token1 route.
    assert quotes.asked == [(BURN0 // 2, (TOKEN0, TOKEN1))]
    swap = decision.evidence["preflight"]["amounts"]["swap"]
    assert swap["token_in"] == "token0"
    assert swap["amount_in"] == BURN0 // 2
    assert swap["quoted_out"] == QUOTED_OUT
    assert swap["route"] == [TOKEN0, TOKEN1]
    assert decision.prepared[4].to == PANCAKE_V2_ROUTER
    assert decision.prepared[4].data[:10] == SWAP_SELECTOR


def test_the_mint_is_funded_by_the_floor_the_swap_is_held_to():
    """The mint asks for the swap's guaranteed minimum, not its quote. Asking for the
    quote would mean a mint that reverts every time the price moved against the leg."""
    decision = _range().evaluate(
        _activation(inputs=_range_inputs(), result=_observations(180)),
        reader=_Positions(),
    )
    amounts = decision.evidence["preflight"]["amounts"]
    assert amounts["burn0"] == str(BURN0)
    floor = QUOTED_OUT * 9_950 // 10_000
    _, mint = npm_encoder.decode_function_input(decision.prepared[7].data)
    assert mint["params"]["amount0Desired"] == BURN0 - BURN0 // 2
    assert mint["params"]["amount1Desired"] == floor
    assert mint["params"]["recipient"] == OWNER
    assert approve_amount(decision.prepared[6].data) == floor
    assert amounts["swap_plan"]["needed"] is True


def test_an_inventory_that_needs_no_trade_produces_a_six_call_batch_and_says_why():
    """Both sides already within the slippage bound. No leg, no router approval, and the
    plan's own reason travels in the evidence."""
    decision = _range(rpc=_Rpc(balanced=True)).evaluate(
        _activation(inputs=_range_inputs(), result=_observations(180)),
        reader=_Positions(),
    )
    assert decision.kind == "action"
    assert [call.purpose for call in decision.prepared] == [
        "owner_signs",
        "session_closes_position",
        "session_collects_to_fund_the_swap_and_the_mint",
        "session_approves_token0_exact",
        "session_approves_token1_exact",
        "session_mints_replacement_to_owner",
    ]
    assert [call.simulation["ok"] for call in decision.prepared] == [True] * 6
    amounts = decision.evidence["preflight"]["amounts"]
    assert amounts["swap"] is None
    assert amounts["swap_plan"]["needed"] is False
    assert "already tolerates" in amounts["swap_plan"]["reason"]


def test_a_swap_the_router_will_not_quote_prepares_nothing():
    class _Dead:
        def amounts_out(self, amount_in, route):
            raise RuntimeError("every endpoint failed")

    decision = _range(quotes=_Dead()).evaluate(
        _activation(inputs=_range_inputs(), result=_observations(180)),
        reader=_Positions(),
    )
    assert decision.kind == "alert"
    assert decision.prepared == ()
    assert decision.evidence["preflight"]["verdict"] == "unreadable"


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
        _activation(inputs=_range_inputs(), result=first.evidence), reader=_Positions()
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


def test_a_collateral_add_needs_no_session_because_the_owner_signs_both_calls():
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
    assert decision.kind == "action"
    assert [call.purpose for call in decision.prepared] == [
        "owner_signs",
        "owner_signs",
    ]


# ------------------------------------------------- what the policy engine reads


def test_the_batch_declares_what_it_lets_the_session_spend_per_token():
    """`SessionPolicy.allows` is handed this mapping and sees zero spend without it. Every
    figure in it is read back out of an approval in the batch, so the number the cap is
    checked against and the bytes that do the spending cannot describe different things."""
    decision = _action()
    spend = decision.evidence["token_amounts"]
    floor = QUOTED_OUT * 9_950 // 10_000
    # token0 is approved twice — once to the router for the leg, once to the position
    # manager for the mint — and the declared spend is the sum of the two.
    assert spend == {
        TOKEN0: str(BURN0 // 2 + (BURN0 - BURN0 // 2)),
        TOKEN1: str(floor),
    }
    assert int(spend[TOKEN0]) == BURN0
    assert decision.evidence["slippage_bps"] == 50
    # Derived from the calldata, not carried beside it.
    assert spend == token_spend(decision.prepared)


def test_the_owner_signed_approval_is_not_counted_as_a_session_spend():
    """The ERC-721 approval is the owner's own transaction over their own NFT. Folding its
    token id into a spend mapping would charge a session cap for something no session
    sends — and the id would be read as an amount."""
    decision = _action()
    assert decision.prepared[0].purpose == "owner_signs"
    assert decision.prepared[0].to == NPM
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


def test_a_collateral_add_declares_no_session_spend_because_the_owner_signs_it():
    decision = _health().evaluate(
        _activation(
            category="health_factor",
            inputs=_health_inputs(mode="add_collateral", max_rescue_atomic={USDC: 10**30}),
            session=None,
        ),
        reader=_Venus(_underwater()),
    )
    assert decision.kind == "action"
    assert decision.evidence["token_amounts"] == {}


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
    """As of `build/pivot-B` the tick loop returns without saving on a noop and never
    assigns `activation.result`, so the history is always empty and the threshold is never
    reached. Silently reporting "nothing due" would hide that; the summary names it."""
    decision = _range().evaluate(
        _activation(inputs=_range_inputs()), reader=_Positions()
    )
    assert decision.kind == "noop"
    assert decision.evidence["time_out_of_range"]["prior_observations"] == 0
    assert "No earlier observation was carried forward" in decision.summary
    assert "activation.result" in decision.summary
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


def test_calls_the_owner_signs_need_no_session_authority():
    """An owner-signed call leaves the owner's own wallet. A session policy that refused it
    would be refusing the owner permission to act on their own position."""
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
    ok, reason = _health().within_policy(_activation(policy=None), decision)
    assert ok is True
    assert "signed by the account owner" in reason


def test_the_erc721_approval_is_never_covered_by_an_erc20_token_cap():
    """ERC-20 and ERC-721 approve share 0x095ea7b3, and the ERC-721 second argument is a
    token id. A cap check that read the selector alone would compare a token id against a
    spend limit and pass whichever way the numbers happened to fall."""
    decision = _action()
    erc721 = decision.prepared[0]
    assert erc721.to == NPM and erc721.purpose == "owner_signs"
    assert approve_amount(erc721.data) == POSITION["token_id"]
    # The position manager is not a token, so no cap keyed by a token address covers it.
    policy = _session_policy()
    assert NPM not in policy["token_allowlist"]
    ok, _ = _range().within_policy(
        _activation(inputs=_range_inputs(), policy=policy), decision
    )
    assert ok is True


def test_an_approval_to_a_token_the_session_never_allowlisted_is_refused():
    """The approval is the one call in either batch that authorises a spend. An approval
    whose target is outside the token allowlist is bounded by no cap at all, so skipping
    the cap check for it would leave exactly the wrong call unbounded."""
    decision = _action()
    ok, reason = _range().within_policy(
        _activation(
            inputs=_range_inputs(), policy=_session_policy(token_allowlist=[TOKEN1])
        ),
        decision,
    )
    assert ok is False
    assert "is not on the session's token allowlist" in reason


def test_the_batch_is_built_for_the_wallet_that_holds_the_position():
    """The activation's creator and the address holding the NFT are two facts. Building the
    ERC-721 approval or the mint against the wrong one produces a call the holder cannot
    sign and a replacement position issued to somebody who does not own the old one."""
    holder = Web3.to_checksum_address("0x429898ba0Fc5b9F1fF0a8f0BD1D6D3cB33B26DdD")
    creator = Web3.to_checksum_address("0xE4fe23FB57dbb9AC2f685ea29B6b9A1409A0d359")
    assert holder != creator
    decision = _range().evaluate(
        _activation(
            owner=creator,
            inputs=_range_inputs(wallet=holder),
            result=_observations(180),
        ),
        reader=_Positions(),
    )
    assert decision.kind == "action"
    _, mint = npm_encoder.decode_function_input(decision.prepared[7].data)
    assert mint["params"]["recipient"] == holder
    assert mint["params"]["recipient"] != creator


def test_the_repay_names_the_account_that_was_actually_read():
    """`repayBorrowBehalf` names whose debt is retired. Taking that address from the
    activation rather than from the snapshot would retire a different account's."""
    creator = Web3.to_checksum_address("0xE4fe23FB57dbb9AC2f685ea29B6b9A1409A0d359")
    state = _underwater()
    assert state.address != creator
    decision = _health().evaluate(
        _activation(
            category="health_factor", owner=creator, inputs=_health_inputs(wallet=OWNER)
        ),
        reader=_Venus(state),
    )
    assert decision.kind == "action"
    repay = decision.prepared[1]
    assert int(repay.data[10:74], 16) == int(state.address, 16)
    assert int(repay.data[10:74], 16) != int(creator, 16)


def test_a_decision_that_prepared_nothing_says_so_rather_than_borrowing_a_reason():
    """A noop has no calls at all, which is not the same fact as a batch the owner signs.
    Two different decisions reading back one sentence is how a reader stops trusting it."""
    noop = _range().evaluate(
        _activation(inputs=_range_inputs()), reader=_Positions(pool=POOL_IN_RANGE)
    )
    assert noop.kind == "noop" and noop.prepared == ()
    ok, reason = _range().within_policy(_activation(inputs=_range_inputs()), noop)
    assert ok is True
    assert reason == "this decision prepared no call, so there is nothing to authorise"


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
