"""The two executors Lane B's tick loop dispatches to, and the policy gate in front.

An executor is the seam between an activation and an agent. It reads a spec out of a
request body, reads the chain, asks the agent what to do, and returns one decision. It
holds no key and there is no method on either class that sends anything.

The stub below is deliberately not Lane B's `Activation`: an executor reads five
attributes and nothing else, and pinning the tests to a dataclass this lane does not own
would make them fail on a field rename that changes nothing they are about. The five
attributes are the contract, and they are named here so that contract is visible.

Two properties are asserted on both executors:

**A decision the chain disagreed with is an `alert`, never an `action`.** The loop
dispatches on `kind`, so this is the difference between refusing and sending.

**`within_policy` reads the session's grant, not the user's request.** A decision that
satisfies the spec and not the policy is exactly what the gate exists to stop.
"""

from dataclasses import dataclass, field

import pytest
from web3 import Web3

from docket.agents.grid.lifecycle import GRID_ASSETS, NO_RESTING_ORDERS
from docket.agents.yield_router.migration import NPM
from docket.execution.simulate import PANCAKE_V2_ROUTER
from docket.jobs.executors import EXECUTORS, Decision, PreparedCall, register
from docket.jobs.executors.grid import GridExecutor
from docket.jobs.executors.yield_router import YieldRouteExecutor

from test_grid_lifecycle import BLOCK as GRID_BLOCK
from test_grid_lifecycle import FROZEN_NOW, Reader as GridReader
from test_yield_migration import (
    ALLOWLIST,
    CURRENT_POOL,
    DEST_POOL,
    OBSERVED,
    OWNER,
    SESSION as YIELD_SESSION,
    SOURCE,
    Reader as YieldReader,
    _position,
)

USDT = Web3.to_checksum_address("0x55d398326f99059fF775485246999027B3197955")
WBNB = Web3.to_checksum_address("0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c")
STRANGER = Web3.to_checksum_address("0x000000000000000000000000000000000000dEaD")
SESSION = Web3.to_checksum_address("0x429898ba0Fc5b9F1fF0a8f0BD1D6D3cB33B26DdD")
SWAP_SELECTOR = "0x38ed1739"
E18 = 10**18


@dataclass
class StubActivation:
    """The five attributes an executor reads. Lane B's model is a superset of this."""

    category: str
    inputs: dict
    owner: str = OWNER
    policy: dict | None = None
    session: dict | None = field(default=None)


def _grid_inputs(**overrides) -> dict:
    inputs = {
        "base": WBNB,
        "quote": USDT,
        "price_lower": str(500 * E18),
        "price_upper": str(700 * E18),
        "levels": 5,
        "amount_per_level_atomic": str(25 * E18),
        "total_cap_atomic": str(100 * E18),
        "expires_at": FROZEN_NOW + 86_400,
        "max_slippage_bps": 50,
        "grid_state": {"reference_price": str(620 * E18)},
    }
    inputs.update(overrides)
    return inputs


def _grid_activation(**overrides) -> StubActivation:
    return StubActivation(
        category="grid_trading",
        inputs=_grid_inputs(**overrides.pop("inputs", {})),
        session={"address": SESSION},
        **overrides,
    )


def _yield_activation(**overrides) -> StubActivation:
    inputs = {
        "pools": [CURRENT_POOL, DEST_POOL],
        "token_allowlist": sorted(ALLOWLIST),
        "source": SOURCE,
        "observed_at": OBSERVED,
        "position": _position(),
        "position_size_usd": 10_000.0,
        "switching_cost_usd": 15.0,
    }
    inputs.update(overrides.pop("inputs", {}))
    return StubActivation(
        category="yield_optimisation",
        inputs=inputs,
        session={"address": YIELD_SESSION},
        **overrides,
    )


@pytest.fixture(autouse=True)
def frozen_clock(monkeypatch):
    for module in ("docket.execution.intent", "docket.execution.simulate"):
        monkeypatch.setattr(f"{module}.now", lambda: FROZEN_NOW)


def _grid(**kwargs) -> GridExecutor:
    return GridExecutor(clock=lambda: FROZEN_NOW, **kwargs)


def _yield(**kwargs) -> YieldRouteExecutor:
    return YieldRouteExecutor(clock=lambda: FROZEN_NOW, **kwargs)


# ------------------------------------------------------------------ the registry


def test_both_categories_are_registered_under_the_official_verbs():
    assert set(EXECUTORS) >= {"grid_trading", "yield_optimisation"}
    assert isinstance(EXECUTORS["grid_trading"], GridExecutor)
    assert isinstance(EXECUTORS["yield_optimisation"], YieldRouteExecutor)


def test_a_second_executor_cannot_quietly_take_over_a_registered_category():
    class Impostor:
        category = "grid_trading"

        def evaluate(self, activation, *, reader=None):  # pragma: no cover
            raise AssertionError("never reached")

        def within_policy(self, activation, decision):  # pragma: no cover
            raise AssertionError("never reached")

    with pytest.raises(ValueError, match="already served by"):
        register(Impostor())
    assert isinstance(EXECUTORS["grid_trading"], GridExecutor)


def test_re_registering_the_same_executor_class_changes_nothing():
    register(GridExecutor())

    assert isinstance(EXECUTORS["grid_trading"], GridExecutor)


# ------------------------------------------------------------------ decision shape


def test_a_decision_that_is_not_an_action_may_not_carry_prepared_calls():
    call = PreparedCall(
        to=PANCAKE_V2_ROUTER,
        data="0x38ed1739",
        value_atomic=0,
        gas_ceiling=300_000,
        deadline=FROZEN_NOW + 600,
        purpose="test",
        simulation={
            "ok": True,
            "gas_estimate": 1,
            "revert_reason": None,
            "observed_at": "",
            "block": 1,
        },
    )

    with pytest.raises(ValueError, match="Only an action may carry calls"):
        Decision(kind="noop", summary="", prepared=(call,))
    with pytest.raises(ValueError, match="wearing the wrong label"):
        Decision(kind="action", summary="")
    with pytest.raises(ValueError, match="not one of"):
        Decision(kind="send", summary="")


def test_a_prepared_call_with_a_half_written_simulation_is_refused():
    with pytest.raises(ValueError, match="simulation is missing"):
        PreparedCall(
            to=PANCAKE_V2_ROUTER,
            data="0x38ed1739",
            value_atomic=0,
            gas_ceiling=300_000,
            deadline=1,
            purpose="test",
            simulation={"ok": True},
        )


# ------------------------------------------------------------------ grid executor


def test_the_grid_executor_turns_a_crossing_into_one_bounded_action():
    decision = _grid().evaluate(_grid_activation(), reader=GridReader(price=540 * E18))

    assert decision.kind == "action"
    assert len(decision.prepared) == 1
    assert decision.prepared[0].to == PANCAKE_V2_ROUTER
    assert decision.block == GRID_BLOCK
    assert (
        decision.evidence["category_verb"] == "Places and manages automated grid orders"
    )
    assert decision.evidence["no_resting_orders"] == NO_RESTING_ORDERS
    assert decision.evidence["grid_state"]["spent_atomic"] == str(25 * E18)


def test_the_grid_executor_waits_without_drafting_anything():
    """610 sits between the highest buy level (600) and the lowest sell level (650) with
    the reference at 620, so it crosses nothing."""
    decision = _grid().evaluate(_grid_activation(), reader=GridReader(price=610 * E18))

    assert decision.kind == "noop"
    assert decision.prepared == ()


def test_a_grid_whose_inputs_stopped_validating_alerts_rather_than_crashing_the_loop():
    decision = _grid().evaluate(
        _grid_activation(inputs={"base": STRANGER}), reader=GridReader(price=540 * E18)
    )

    assert decision.kind == "alert"
    assert "asset allowlist" in decision.summary
    assert decision.prepared == ()


def test_a_grid_with_no_session_cannot_name_a_recipient_and_says_so():
    activation = _grid_activation()
    activation.session = None

    decision = _grid().evaluate(activation, reader=GridReader(price=540 * E18))

    assert decision.kind == "alert"
    assert "no session address" in decision.summary


def test_a_grid_stop_or_expiry_is_reported_as_an_alert_rather_than_a_silent_noop():
    stopped = _grid().evaluate(
        _grid_activation(inputs={"stop_price": str(490 * E18)}),
        reader=GridReader(price=480 * E18),
    )
    expired = _grid().evaluate(
        _grid_activation(inputs={"expires_at": FROZEN_NOW - 1}),
        reader=GridReader(price=540 * E18),
    )

    assert stopped.kind == "alert"
    assert stopped.evidence["grid_decision"] == "cancel"
    assert expired.kind == "alert"
    assert expired.evidence["grid_decision"] == "revoke"


def test_the_grid_executor_refuses_a_call_the_chain_disagreed_with():
    decision = _grid().evaluate(
        _grid_activation(), reader=GridReader(price=540 * E18, fail_estimate=True)
    )

    assert decision.kind == "alert"
    assert decision.prepared == ()


def test_integer_fields_arrive_as_strings_or_integers_and_mean_the_same_thing():
    as_strings = _grid().evaluate(
        _grid_activation(), reader=GridReader(price=540 * E18)
    )
    as_integers = _grid().evaluate(
        _grid_activation(
            inputs={
                "price_lower": 500 * E18,
                "price_upper": 700 * E18,
                "amount_per_level_atomic": 25 * E18,
                "total_cap_atomic": 100 * E18,
            }
        ),
        reader=GridReader(price=540 * E18),
    )

    assert as_strings.prepared[0].data == as_integers.prepared[0].data


def test_a_float_where_an_integer_belongs_is_refused_rather_than_rounded():
    decision = _grid().evaluate(
        _grid_activation(inputs={"amount_per_level_atomic": 25.5}),
        reader=GridReader(price=540 * E18),
    )

    assert decision.kind == "alert"
    assert "must be an integer" in decision.summary


# ------------------------------------------------------------------ grid policy gate


def _grid_action():
    return _grid().evaluate(_grid_activation(), reader=GridReader(price=540 * E18))


def test_a_grid_action_inside_its_session_grant_passes_the_gate():
    activation = _grid_activation(
        policy={
            "contract_allowlist": [PANCAKE_V2_ROUTER],
            "function_allowlist": [SWAP_SELECTOR],
            "token_allowlist": sorted(GRID_ASSETS),
            "per_action_limit_atomic": {USDT: str(30 * E18)},
            "max_gas_price_wei": 400_000,
        }
    )

    allowed, why = _grid().within_policy(activation, _grid_action())

    assert allowed is True
    assert "allowlisted router" in why


@pytest.mark.parametrize(
    ("policy", "fragment"),
    (
        ({"contract_allowlist": [STRANGER]}, "contract allowlist"),
        ({"function_allowlist": ["0xdeadbeef"]}, "function allowlist"),
        ({"token_allowlist": [STRANGER]}, "token allowlist"),
        ({"per_action_limit_atomic": {USDT: str(E18)}}, "per-action limit"),
        ({"max_gas_price_wei": 1_000}, "gas ceiling"),
        ({"emergency_pause": True}, "emergency pause"),
    ),
)
def test_every_way_a_grid_action_can_fall_outside_its_grant_is_refused(
    policy, fragment
):
    allowed, why = _grid().within_policy(
        _grid_activation(policy=policy), _grid_action()
    )

    assert allowed is False
    assert fragment in why


def test_a_decision_that_sends_nothing_passes_the_gate_trivially():
    allowed, why = _grid().within_policy(
        _grid_activation(), Decision(kind="noop", summary="waiting")
    )

    assert allowed is True
    assert "sends nothing" in why


# ------------------------------------------------------------------ yield executor


def test_the_yield_executor_builds_the_whole_route_when_the_move_pays_for_itself():
    decision = _yield().evaluate(_yield_activation(), reader=YieldReader())

    assert decision.kind == "action"
    assert len(decision.prepared) == 8
    assert decision.prepared[0].purpose.startswith("OWNER SIGNS:")
    assert decision.prepared[-1].to == NPM
    assert decision.evidence["category_verb"] == (
        "Routes liquidity to the highest available APR"
    )
    assert decision.evidence["disclosure"]["expected_payback_period_days"] > 0
    assert "0xdest" in decision.summary


def test_a_move_that_does_not_pay_for_itself_is_a_noop_with_the_arithmetic_attached():
    decision = _yield().evaluate(
        _yield_activation(inputs={"switching_cost_usd": 5_000.0}),
        reader=YieldReader(),
    )

    assert decision.kind == "noop"
    assert decision.prepared == ()
    assert decision.evidence["break_even"]["within_horizon"] is False
    assert decision.evidence["break_even"]["days_to_recover"] > 30
    assert decision.evidence["candidates"]


def test_the_comparison_is_bounded_by_a_set_the_caller_supplied_and_can_reproduce():
    decision = _yield().evaluate(_yield_activation(), reader=YieldReader())
    universe = decision.evidence["universe"]

    assert universe["source"] == SOURCE
    assert universe["observed_at"] == OBSERVED
    assert universe["size"] == 2
    assert "not a claim about every pool" in universe["bound"]


def test_an_activation_with_no_population_is_refused_rather_than_fetching_one():
    """A comparison whose set was fetched at decision time cannot be reproduced by a
    reader who was not there."""
    for missing in ("pools", "token_allowlist"):
        activation = _yield_activation()
        activation.inputs[missing] = None
        decision = _yield().evaluate(activation, reader=YieldReader())

        assert decision.kind == "alert"
        assert missing in decision.summary


def test_an_empty_eligible_set_names_no_highest():
    thin = {**DEST_POOL, "tvlUSD": "10"}
    decision = _yield().evaluate(
        _yield_activation(inputs={"pools": [thin]}), reader=YieldReader()
    )

    assert decision.kind == "noop"
    assert "no highest to route to" in decision.summary


def test_a_route_that_cannot_be_built_alerts_and_keeps_the_comparison():
    decision = _yield().evaluate(
        _yield_activation(inputs={"position": _position(staked=True)}),
        reader=YieldReader(),
    )

    assert decision.kind == "alert"
    assert "MasterChefV3" in decision.summary
    assert decision.evidence["break_even"]["within_horizon"] is True


def test_the_yield_executor_refuses_a_route_the_chain_disagreed_with():
    decision = _yield().evaluate(
        _yield_activation(), reader=YieldReader(revert_on=("0x0c49ccbe",))
    )

    assert decision.kind == "alert"
    assert "disagreed with 1 of its 8 calls" in decision.summary
    assert decision.prepared == ()


# ------------------------------------------------------------------ yield policy gate


def _yield_action():
    return _yield().evaluate(_yield_activation(), reader=YieldReader())


def test_the_owners_own_nft_approval_is_outside_the_sessions_grant_by_design():
    """The session is never granted the position manager's ERC-721 approve; exempting it
    by the purpose it declares rather than by its index means a reordered route cannot
    slip a session call past this gate."""
    activation = _yield_activation(
        policy={
            "contract_allowlist": [NPM, PANCAKE_V2_ROUTER, USDT, WBNB],
            "max_gas_price_wei": 1_000_000,
        }
    )

    allowed, why = _yield().within_policy(activation, _yield_action())

    assert allowed is True
    assert "outside the session's authority by design" in why


@pytest.mark.parametrize(
    ("policy", "fragment"),
    (
        ({"contract_allowlist": [PANCAKE_V2_ROUTER]}, "contract allowlist"),
        ({"function_allowlist": [SWAP_SELECTOR]}, "function allowlist"),
        ({"max_gas_price_wei": 100_000}, "gas ceiling"),
        ({"emergency_pause": True}, "emergency pause"),
    ),
)
def test_every_way_a_route_can_fall_outside_its_grant_is_refused(policy, fragment):
    allowed, why = _yield().within_policy(
        _yield_activation(policy=policy), _yield_action()
    )

    assert allowed is False
    assert fragment in why


def test_a_token_the_session_may_not_touch_stops_the_route():
    activation = _yield_activation(policy={"token_allowlist": [USDT]})

    allowed, why = _yield().within_policy(activation, _yield_action())

    assert allowed is False
    assert "token allowlist" in why
