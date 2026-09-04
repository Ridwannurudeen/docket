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
    USDC,
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
    """The six attributes an executor reads. Lane B's model is a superset of this.

    `result` is where the tick loop writes the previous decision's evidence, so it is
    where a running grid's own progress comes back from. On the first pass it is empty and
    the spec's opening state in `inputs` is what stands in.
    """

    category: str
    inputs: dict
    owner: str = OWNER
    policy: dict | None = None
    session: dict | None = field(default=None)
    result: dict | None = None
    receipts: tuple = ()
    expires_at: str | None = None


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


def _pending(decision) -> dict:
    """A `pending_sends` entry shaped the way `sessions.executor` writes one."""
    return {
        "nonce": 7,
        "purpose": decision.prepared[-1].purpose,
        "amounts": {},
        "broadcast_at": "2026-09-03T09:00:00+00:00",
    }


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

    with pytest.raises(ValueError, match="already has a registered executor"):
        register("grid_trading", Impostor())
    assert isinstance(EXECUTORS["grid_trading"], GridExecutor)


def test_a_category_the_marketplace_does_not_declare_cannot_be_registered():
    with pytest.raises(ValueError, match="unknown category"):
        register("day_trading", GridExecutor())


# ------------------------------------------------------------------ decision shape


def test_a_decision_that_is_not_an_action_may_not_carry_prepared_calls():
    call = PreparedCall(
        to=PANCAKE_V2_ROUTER,
        data="0x38ed1739",
        value_atomic="0",
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

    def _decision(**overrides):
        fields = {
            "kind": "noop",
            "summary": "nothing to do",
            "prepared": (),
            "evidence": {},
            "observed_at": "",
            "block": 0,
        }
        fields.update(overrides)
        return Decision(**fields)

    with pytest.raises(ValueError, match="nothing would send"):
        _decision(prepared=(call,))
    with pytest.raises(ValueError, match="acts on nothing"):
        _decision(kind="action")
    with pytest.raises(ValueError, match="unknown decision kind"):
        _decision(kind="send")
    with pytest.raises(ValueError, match="must say what it decided"):
        _decision(summary="   ")


def test_a_prepared_call_without_a_simulation_is_refused():
    with pytest.raises(ValueError, match="must carry its simulation"):
        PreparedCall(
            to=PANCAKE_V2_ROUTER,
            data="0x38ed1739",
            value_atomic="0",
            gas_ceiling=300_000,
            deadline=1,
            purpose="test",
            simulation={},
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
        _grid_activation(),
        Decision(
            kind="noop",
            summary="waiting",
            prepared=(),
            evidence={},
            observed_at="",
            block=0,
        ),
    )

    assert allowed is True
    assert "sends nothing" in why


# ------------------------------------------------------------------ yield executor


def test_the_yield_executor_builds_the_whole_route_when_the_move_pays_for_itself():
    decision = _yield().evaluate(_yield_activation(), reader=YieldReader())

    assert decision.kind == "action"
    assert len(decision.prepared) == 7
    assert not [c for c in decision.prepared if c.purpose.startswith("OWNER SIGNS:")]
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
    assert "disagreed with 1 of its 7 calls" in decision.summary
    assert decision.prepared == ()


# ------------------------------------------------------------------ yield policy gate


def _yield_action():
    return _yield().evaluate(_yield_activation(), reader=YieldReader())


def test_the_owners_own_nft_approval_is_not_in_the_batch_at_all():
    """It used to be exempted by name from inside the list. It is not in the list now: it
    is a precondition the route reads before it builds, so there is nothing to exempt."""
    activation = _yield_activation(
        policy={"contract_allowlist": [NPM, PANCAKE_V2_ROUTER, USDT, WBNB]}
    )

    allowed, why = _yield().within_policy(activation, _yield_action())

    assert allowed is True
    assert "not in this batch at all" in why


@pytest.mark.parametrize(
    ("policy", "fragment"),
    (
        ({"contract_allowlist": [PANCAKE_V2_ROUTER]}, "contract allowlist"),
        ({"function_allowlist": [SWAP_SELECTOR]}, "function allowlist"),
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


# ------------------------------------------------- the contract the tick loop reads


def test_every_grid_decision_carries_what_it_spends_and_at_what_tolerance():
    """`SessionPolicy.allows` reads spend and slippage off `Decision.evidence` and can
    see them no other way, so a decision that left either key out would be read as
    spending nothing — which is a spend cap that never binds."""
    fired = _grid().evaluate(_grid_activation(), reader=GridReader(price=540 * E18))
    waiting = _grid().evaluate(_grid_activation(), reader=GridReader(price=610 * E18))
    broken = _grid().evaluate(
        _grid_activation(inputs={"base": STRANGER}), reader=GridReader(price=540 * E18)
    )

    assert fired.evidence["token_amounts"] == {USDT: str(25 * E18)}
    assert fired.evidence["slippage_bps"] == 50
    assert waiting.evidence["token_amounts"] == {}
    assert waiting.evidence["slippage_bps"] == 50
    assert broken.evidence["token_amounts"] == {}
    assert broken.evidence["slippage_bps"] is None


def test_a_grid_sell_reports_the_base_token_as_what_it_spends():
    decision = _grid().evaluate(
        _grid_activation(inputs={"grid_state": {"reference_price": str(520 * E18)}}),
        reader=GridReader(price=690 * E18),
    )

    assert decision.kind == "action"
    (token,) = decision.evidence["token_amounts"]
    assert token == WBNB
    assert int(decision.evidence["token_amounts"][token]) > 0


def test_the_grid_reads_its_progress_back_from_the_previous_ticks_result():
    """Lane B writes each decision's evidence into `activation.result`, so that is where
    a running grid's state lives. Reading `inputs` in preference would restart the grid
    on every tick and re-fire levels that have already filled."""
    activation = _grid_activation()
    first = _grid().evaluate(activation, reader=GridReader(price=540 * E18))
    assert first.kind == "action"
    assert first.evidence["grid_state"]["spent_atomic"] == str(25 * E18)

    # The level stays fired because the send is still pending, which is what stops it
    # being drafted a second time, and the cap is at its ceiling.
    activation.result = {
        "last_decision": {
            "evidence": {
                "grid_state": {
                    **first.evidence["grid_state"],
                    "spent_atomic": str(100 * E18),
                }
            }
        },
        "pending_sends": {"7": _pending(first)},
    }
    second = _grid().evaluate(activation, reader=GridReader(price=540 * E18))

    assert second.kind == "noop"
    assert "refused rather than trimmed" in second.summary
    assert second.evidence["token_amounts"] == {}


def test_the_older_result_shape_is_still_read_for_one_release():
    """A grid mid-flight when this release lands must not restart from its opening
    state, so the shape this executor wrote before the contract settled is still read."""
    activation = _grid_activation()
    first = _grid().evaluate(activation, reader=GridReader(price=540 * E18))
    activation.result = {"grid_state": first.evidence["grid_state"]}
    activation.result["pending_sends"] = {"7": _pending(first)}

    second = _grid().evaluate(activation, reader=GridReader(price=540 * E18))

    assert [e["level"] for e in second.evidence["grid_state"]["fired"]] == [2, 1]


def test_the_grid_wraps_the_tick_loops_raw_rpc_into_a_router_reader(monkeypatch):
    """The loop hands over `escrow.chain.Rpc`, which is a failover callable rather than
    a reader. A caller's own reader is used as given; anything else is wrapped."""
    built = []
    passthrough = GridReader(price=610 * E18)

    class FakeQuoteReader:
        def __init__(self, rpc=None):
            built.append(rpc)
            self.block_number = passthrough.block_number
            self.amounts_out = passthrough.amounts_out
            self.estimate_gas = passthrough.estimate_gas

    monkeypatch.setattr("docket.jobs.executors.grid.BscQuoteReader", FakeQuoteReader)

    def rpc(read):  # the Rpc callable shape, with no amounts_out on it
        raise AssertionError("the executor must not drive the Rpc itself")

    wrapped = _grid().evaluate(_grid_activation(), reader=rpc)

    assert built == [rpc]
    assert wrapped.kind == "noop"

    _grid().evaluate(_grid_activation(), reader=passthrough)
    assert built == [rpc]


def test_every_yield_decision_carries_what_it_spends_and_at_what_tolerance():
    routed = _yield().evaluate(_yield_activation(), reader=YieldReader())
    staying = _yield().evaluate(
        _yield_activation(inputs={"switching_cost_usd": 5_000.0}),
        reader=YieldReader(),
    )
    refused = _yield().evaluate(
        _yield_activation(), reader=YieldReader(revert_on=("0x0c49ccbe",))
    )

    assert routed.evidence["token_amounts"]
    assert routed.evidence["slippage_bps"] == 50
    assert staying.evidence["token_amounts"] == {}
    assert staying.evidence["slippage_bps"] == 50
    assert refused.evidence["token_amounts"] == {}


def test_the_yield_spend_is_every_leg_plus_what_the_mint_pulls():
    decision = _yield().evaluate(_yield_activation(), reader=YieldReader())
    disclosure = decision.evidence["disclosure"]

    expected: dict[str, int] = {}
    for leg in disclosure["slippage"]["legs"]:
        expected[leg["token_in"]] = expected.get(leg["token_in"], 0) + int(
            leg["amount_in"]
        )
    expected[USDT] = expected.get(USDT, 0) + int(
        disclosure["position"]["mint_amount0_desired"]
    )
    expected[WBNB] = expected.get(WBNB, 0) + int(
        disclosure["position"]["mint_amount1_desired"]
    )

    assert decision.evidence["token_amounts"] == {
        token: str(amount) for token, amount in sorted(expected.items())
    }
    assert disclosure["session_spend_atomic"] == decision.evidence["token_amounts"]


def test_the_yield_route_wraps_the_tick_loops_raw_rpc(monkeypatch):
    built = []
    passthrough = YieldReader()

    class FakeMigrationReader:
        def __init__(self, positions=None, quotes=None, rpc=None):
            built.append(rpc)
            self.pool_state = passthrough.pool_state
            self.amounts_out = passthrough.amounts_out
            self.block_number = passthrough.block_number
            self.call = passthrough.call
            self.estimate_gas = passthrough.estimate_gas

    monkeypatch.setattr(
        "docket.agents.yield_router.migration.BscMigrationReader", FakeMigrationReader
    )

    def rpc(read):  # no pool_state on it
        raise AssertionError("the executor must not drive the Rpc itself")

    routed = _yield().evaluate(_yield_activation(), reader=rpc)

    assert built == [rpc]
    assert routed.kind == "action"

    _yield().evaluate(_yield_activation(), reader=passthrough)
    assert built == [rpc]


# ------------------------------------------- the four keys the session plane reads


SESSION_KEYS = (
    "token_amounts",
    "token_amounts_by_call",
    "token_hints",
    "received_tokens",
    "slippage_bps",
)


def test_every_decision_from_either_executor_carries_all_of_them():
    """`SessionPolicy.allows`, `sessions.spend` and `sessions.sweep` read these off the
    evidence and can see them no other way. An absent key is a spend of zero, a hint
    nobody supplied, or a token a revoke leaves behind."""
    decisions = [
        _grid().evaluate(_grid_activation(), reader=GridReader(price=540 * E18)),
        _grid().evaluate(_grid_activation(), reader=GridReader(price=610 * E18)),
        _grid().evaluate(
            _grid_activation(inputs={"base": STRANGER}),
            reader=GridReader(price=540 * E18),
        ),
        _yield().evaluate(_yield_activation(), reader=YieldReader()),
        _yield().evaluate(
            _yield_activation(inputs={"switching_cost_usd": 5_000.0}),
            reader=YieldReader(),
        ),
    ]

    for decision in decisions:
        assert set(SESSION_KEYS) <= set(decision.evidence), decision.summary
        assert isinstance(decision.evidence["token_amounts"], dict)
        assert isinstance(decision.evidence["token_amounts_by_call"], list)
        assert isinstance(decision.evidence["token_hints"], dict)
        assert isinstance(decision.evidence["received_tokens"], list)


def test_the_per_call_spend_lines_up_with_the_calls_it_describes():
    grid = _grid().evaluate(
        _grid_activation(), reader=GridReader(price=540 * E18, allowance=0)
    )
    route = _yield().evaluate(_yield_activation(), reader=YieldReader())

    assert len(grid.prepared) == 2
    assert grid.evidence["token_amounts_by_call"] == [{}, {USDT: str(25 * E18)}]
    assert len(route.evidence["token_amounts_by_call"]) == len(route.prepared)


def test_an_approval_in_the_batch_is_charged_as_authorisation_not_as_spend():
    """Charging it would bill the session twice for the same tokens: once for permitting
    the swap and once for the swap."""
    decision = _grid().evaluate(
        _grid_activation(), reader=GridReader(price=540 * E18, allowance=0)
    )
    approval, swap = decision.prepared
    by_call = decision.evidence["token_amounts_by_call"]

    assert approval.selector == "0x095ea7b3"
    assert by_call[0] == {}
    assert by_call[1] == {USDT: str(25 * E18)}
    assert decision.evidence["token_amounts"] == {USDT: str(25 * E18)}


def test_received_tokens_names_everything_a_revoke_has_to_sweep():
    grid = _grid().evaluate(_grid_activation(), reader=GridReader(price=540 * E18))
    route = _yield().evaluate(_yield_activation(), reader=YieldReader())

    assert set(grid.evidence["received_tokens"]) == {USDT, WBNB}
    assert set(route.evidence["received_tokens"]) >= {USDT, WBNB}


def test_observed_at_is_a_utc_timestamp_and_the_read_is_named_separately():
    from datetime import datetime, timezone

    decision = _grid().evaluate(_grid_activation(), reader=GridReader(price=540 * E18))

    moment = datetime.fromisoformat(decision.observed_at)
    assert moment.tzinfo is not None
    assert moment.utcoffset().total_seconds() == 0
    assert abs((datetime.now(timezone.utc) - moment).total_seconds()) < 60
    assert decision.evidence["source"] == "router.getAmountsOut"


def test_a_deferred_simulation_is_not_read_as_the_chain_refusing():
    """`ok: None` means an earlier call in the same batch creates the precondition. Only
    `ok: False` is a refusal, and treating the two alike would refuse every first fire."""
    decision = _grid().evaluate(
        _grid_activation(), reader=GridReader(price=540 * E18, allowance=0)
    )

    assert decision.prepared[-1].simulation["ok"] is None
    allowed, why = _grid().within_policy(_grid_activation(), decision)
    assert allowed is True, why


def test_the_grid_reads_a_receipt_back_and_closes_the_level_it_belonged_to():
    """The fire branch marks a level fired and only a receipt takes it off that list."""
    from types import SimpleNamespace

    tx = "0x" + "ab" * 32
    pad = lambda address: "0x" + "00" * 12 + address[2:].lower()  # noqa: E731
    transfer = Web3.keccak(text="Transfer(address,address,uint256)")
    receipt = {
        "logs": [
            {
                "address": USDT,
                "topics": [transfer, pad(SESSION), pad(STRANGER)],
                "data": "0x" + format(25 * E18, "064x"),
            },
            {
                "address": WBNB,
                "topics": [transfer, pad(STRANGER), pad(SESSION)],
                "data": "0x" + format(46 * 10**15, "064x"),
            },
        ],
        "transactionHash": tx,
        "blockNumber": GRID_BLOCK,
    }
    # A real first pass, so the `Fired` entry carries the real input hash rather than an
    # invented one. Nothing writes a transaction hash back into an executor's evidence —
    # that was the defect — so the join is `Receipt.input_hash`.
    activation = _grid_activation()
    first = _grid().evaluate(activation, reader=GridReader(price=540 * E18))
    fired = first.evidence["grid_state"]["fired"][0]
    assert fired["input_hash"]
    assert fired["tx_hash"] is None

    activation.result = {"last_decision": {"evidence": first.evidence}}
    activation.receipts = (
        SimpleNamespace(
            input_hash=fired["input_hash"],
            execution={
                "tx_hash": tx,
                "status": 1,
                "purpose": "grid level 2: buy, one PancakeSwap V2 exact-input swap",
            },
        ),
    )

    decision = _grid().evaluate(
        activation, reader=GridReader(price=540 * E18, receipts={tx: receipt})
    )
    state = decision.evidence["grid_state"]

    assert 2 not in [entry["level"] for entry in state["fired"]]
    assert [fill["level"] for fill in state["fills"]] == [2]
    assert state["fills"][0]["side"] == "buy"
    assert state["fills"][0]["amount_in"] == str(25 * E18)
    assert state["fills"][0]["tx_hash"] == tx
    assert [entry["level"] for entry in state["fired"]] == [1]


def test_the_fired_entry_carries_the_digest_the_receipt_will_be_keyed_by():
    """`Receipt.input_hash` is `canonical_hash(prepared.to_dict())`, so computing the same
    digest at draft time is the only key the two records share — the session plane writes
    nothing back into an executor's evidence."""
    from docket.hire.receipts import canonical_hash

    decision = _grid().evaluate(_grid_activation(), reader=GridReader(price=540 * E18))
    (entry,) = decision.evidence["grid_state"]["fired"]

    assert entry["input_hash"] == canonical_hash(decision.prepared[-1].to_dict())


def test_a_reverted_swap_is_read_off_settled_sends_and_refunds_the_cap():
    """A reverted send never becomes a `Receipt` at all — `execute` raises and the only
    record is a `settled_sends` entry with `status: 0`. Waiting for a receipt that will
    never exist is how the level stayed charged and closed for ever."""
    activation = _grid_activation()
    first = _grid().evaluate(activation, reader=GridReader(price=540 * E18))
    swap = first.prepared[-1]
    activation.result = {
        "last_decision": {
            "evidence": {
                **first.evidence,
                "grid_state": {
                    **first.evidence["grid_state"],
                    "spent_atomic": str(100 * E18),
                },
            }
        },
        "settled_sends": [
            {
                "nonce": 7,
                "purpose": swap.purpose,
                "tx_hash": "0x" + "cd" * 32,
                "status": 0,
                "gas_atomic": "21000",
            }
        ],
    }
    assert activation.receipts == ()

    # 610 crosses nothing with the reference at 620, so the refund is the only thing that
    # moves on this pass and it can be read on its own.
    waiting = _grid().evaluate(activation, reader=GridReader(price=610 * E18))
    state = waiting.evidence["grid_state"]

    assert waiting.kind == "noop"
    assert state["fired"] == []
    assert 2 in state["open_levels"]
    assert int(state["spent_atomic"]) == 100 * E18 - 25 * E18

    # And with the cap back under its ceiling, the level is drafted again.
    refired = _grid().evaluate(activation, reader=GridReader(price=540 * E18))
    assert refired.kind == "action"
    assert refired.evidence["grid_state"]["fired"][0]["level"] == 2


def test_a_settled_revert_wins_over_its_stale_pending_record():
    activation = _grid_activation()
    first = _grid().evaluate(activation, reader=GridReader(price=540 * E18))
    swap = first.prepared[-1]
    tx_hash = "0x" + "cd" * 32
    pending = _pending(first)
    pending["tx_hash"] = tx_hash
    activation.result = {
        "last_decision": {"evidence": first.evidence},
        "pending_sends": {"7": pending},
        "settled_sends": [
            {
                "nonce": 7,
                "purpose": swap.purpose,
                "tx_hash": tx_hash,
                "status": 0,
                "gas_atomic": "21000",
            }
        ],
    }

    waiting = _grid().evaluate(activation, reader=GridReader(price=610 * E18))
    state = waiting.evidence["grid_state"]

    assert waiting.kind == "noop"
    assert state["fired"] == []
    assert 2 in state["open_levels"]
    assert int(state["spent_atomic"]) == 0


def test_a_reverted_approval_is_not_mistaken_for_the_swap_reverting():
    """Both calls a level drafts open `grid level N:`, so a prefix match alone would read
    a failed approval as a failed swap — and reopen a level whose swap is still in
    flight, which is how the same size gets sent twice."""
    activation = _grid_activation()
    first = _grid().evaluate(
        activation, reader=GridReader(price=540 * E18, allowance=0)
    )
    approval, swap = first.prepared
    assert approval.purpose.startswith("grid level 2:")
    assert swap.purpose.startswith("grid level 2:")

    activation.result = {
        "last_decision": {"evidence": first.evidence},
        "settled_sends": [
            {"nonce": 6, "purpose": approval.purpose, "status": 0, "tx_hash": "0xa"}
        ],
        "pending_sends": {"7": {"nonce": 7, "purpose": swap.purpose}},
    }

    waiting = _grid().evaluate(activation, reader=GridReader(price=610 * E18))

    assert [e["level"] for e in waiting.evidence["grid_state"]["fired"]] == [2]
    assert int(waiting.evidence["grid_state"]["spent_atomic"]) == 25 * E18


def test_a_historical_revert_does_not_reopen_a_new_pending_attempt():
    activation = _grid_activation()
    first = _grid().evaluate(activation, reader=GridReader(price=540 * E18))
    historical_revert = {
        "nonce": 7,
        "purpose": first.prepared[-1].purpose,
        "status": 0,
        "tx_hash": "0xold",
    }
    activation.result = {
        "last_decision": {"evidence": first.evidence},
        "settled_sends": [historical_revert],
    }
    retry = _grid().evaluate(activation, reader=GridReader(price=540 * E18))
    assert retry.prepared[-1].purpose != first.prepared[-1].purpose

    activation.result = {
        "last_decision": {"evidence": retry.evidence},
        "settled_sends": [historical_revert],
        "pending_sends": {"8": _pending(retry)},
    }
    waiting = _grid().evaluate(activation, reader=GridReader(price=610 * E18))

    assert [entry["level"] for entry in waiting.evidence["grid_state"]["fired"]] == [2]
    assert int(waiting.evidence["grid_state"]["spent_atomic"]) == 25 * E18


def test_a_draft_refused_before_the_broadcast_is_swept_up_on_the_next_pass():
    """The decision is persisted before `execute` runs, so a draft the policy or the
    simulation refused leaves a `Fired` entry with no send behind it. Unswept, that level
    never fires again and its notional is charged against the cap for ever."""
    activation = _grid_activation()
    first = _grid().evaluate(activation, reader=GridReader(price=540 * E18))
    activation.result = {"last_decision": {"evidence": first.evidence}}

    assert activation.receipts == ()
    assert not (activation.result.get("pending_sends") or {})

    second = _grid().evaluate(activation, reader=GridReader(price=540 * E18))
    state = second.evidence["grid_state"]

    assert second.kind == "action"
    assert [entry["level"] for entry in state["fired"]] == [2]
    assert int(state["spent_atomic"]) == 25 * E18


def test_a_draft_waiting_on_the_owners_signature_is_not_swept_up():
    """`needs_approval` means the tick has asked the owner to sign the very call this
    level drafted. Reopening it would draft a second one alongside."""
    activation = _grid_activation()
    first = _grid().evaluate(activation, reader=GridReader(price=540 * E18))
    activation.result = {"last_decision": {"evidence": first.evidence}}
    activation.state = "needs_approval"

    second = _grid().evaluate(activation, reader=GridReader(price=610 * E18))
    state = second.evidence["grid_state"]

    assert [entry["level"] for entry in state["fired"]] == [2]
    assert int(state["spent_atomic"]) == 25 * E18
    assert second.evidence["awaiting_owner"] == [2]


def test_a_draft_still_pending_is_left_alone():
    activation = _grid_activation()
    first = _grid().evaluate(activation, reader=GridReader(price=540 * E18))
    activation.result = {
        "last_decision": {"evidence": first.evidence},
        "pending_sends": {"7": _pending(first)},
    }

    second = _grid().evaluate(activation, reader=GridReader(price=610 * E18))

    assert [e["level"] for e in second.evidence["grid_state"]["fired"]] == [2]
    assert int(second.evidence["grid_state"]["spent_atomic"]) == 25 * E18


def test_the_grid_takes_its_expiry_from_the_activation_not_the_request_body():
    """A grid outliving the session that funds it is what the expiry exists to stop, so
    a later date typed into the body cannot extend it."""
    activation = _grid_activation(inputs={"expires_at": FROZEN_NOW + 10**7})
    activation.expires_at = "2020-01-01T00:00:00+00:00"

    decision = _grid().evaluate(activation, reader=GridReader(price=540 * E18))

    assert decision.kind == "alert"
    assert decision.evidence["grid_decision"] == "revoke"
    assert "expired" in decision.summary


def test_a_stop_and_a_cancel_stay_stopped_across_passes():
    """The decision's own state is what gets persisted, so a stop is sticky by
    construction — and a grid that forgot it had been stopped would resume trading."""
    stopped = _grid().evaluate(
        _grid_activation(inputs={"stop_price": str(490 * E18)}),
        reader=GridReader(price=480 * E18),
    )
    assert stopped.evidence["grid_state"]["cancelled"] is True

    resumed = _grid_activation(inputs={"stop_price": str(490 * E18)})
    resumed.result = {"last_decision": {"evidence": stopped.evidence}}
    later = _grid().evaluate(resumed, reader=GridReader(price=540 * E18))

    assert later.kind == "noop"
    assert "cancelled" in later.summary
    assert later.evidence["grid_state"]["cancelled"] is True
    assert later.evidence["token_amounts"] == {}


def test_a_revoked_grid_stays_revoked_across_passes():
    revoked = _grid_activation()
    revoked.result = {
        "last_decision": {
            "evidence": {
                "grid_state": {"reference_price": str(620 * E18), "revoked": True}
            }
        }
    }

    decision = _grid().evaluate(revoked, reader=GridReader(price=540 * E18))

    assert decision.kind == "noop"
    assert "revoked" in decision.summary
    assert decision.prepared == ()


def test_a_route_that_has_already_moved_is_not_planned_a_second_time():
    """A finished move leaves a burned position and a mint receipt. Read live, because
    the executor holds no state between passes and would otherwise send the whole route
    again against a position with nothing left in it."""
    from types import SimpleNamespace

    activation = _yield_activation()
    activation.receipts = (
        SimpleNamespace(
            execution={
                "tx_hash": "0x" + "ef" * 32,
                "status": 1,
                "purpose": "mint into 0xdest over ticks",
            }
        ),
    )

    decision = _yield().evaluate(activation, reader=YieldReader(liquidity=0))

    assert decision.kind == "noop"
    assert "has already happened" in decision.summary
    assert decision.evidence["already_moved"] is True
    assert decision.prepared == ()


def test_a_burned_position_with_no_mint_receipt_resumes_instead_of_stopping():
    """Burned alone means halfway through, not finished."""
    decision = _yield().evaluate(
        _yield_activation(),
        reader=YieldReader(liquidity=0, balances={USDT: 5_000 * E18}),
    )

    assert decision.kind == "action"
    assert not [c for c in decision.prepared if "burn all" in c.purpose]
    assert decision.evidence["disclosure"]["resumed_from_chain"] is True


# ------------------------------------------- what a refusal has to hand the browser


def test_a_missing_nft_approval_reaches_the_evidence_as_something_to_act_on():
    """`NftApprovalRequired` is a `ValueError`, so a generic clause ahead of it swallowed
    the one thing the browser needs: what the owner has to sign."""
    decision = _yield().evaluate(
        _yield_activation(), reader=YieldReader(approved_to=None)
    )

    assert decision.kind == "alert"
    needed = decision.evidence["needs_nft_approval"]
    assert needed["contract"] == NPM
    assert needed["token_id"] == 7141050
    assert needed["session"] == YIELD_SESSION
    assert needed["function"] == "approve(address,uint256)"
    assert "owner approves the session" in decision.summary


def test_a_route_that_cannot_be_built_for_another_reason_still_alerts_generically():
    decision = _yield().evaluate(
        _yield_activation(inputs={"position": _position(staked=True)}),
        reader=YieldReader(),
    )

    assert decision.kind == "alert"
    assert "MasterChefV3" in decision.summary
    assert "needs_nft_approval" not in decision.evidence


# ------------------------------------------- received_tokens never goes empty


def test_a_yield_noop_still_names_every_token_a_sweep_has_to_look_for():
    """The session plane reads the LAST decision, so a route that stayed put and reported
    no tokens would leave a half-finished move's balances behind."""
    staying = _yield().evaluate(
        _yield_activation(inputs={"switching_cost_usd": 5_000.0}),
        reader=YieldReader(),
    )
    empty_set = _yield().evaluate(
        _yield_activation(inputs={"pools": [{**DEST_POOL, "tvlUSD": "10"}]}),
        reader=YieldReader(),
    )
    refused = _yield().evaluate(
        _yield_activation(), reader=YieldReader(approved_to=None)
    )

    for decision in (staying, empty_set, refused):
        assert set(decision.evidence["received_tokens"]) >= {USDT, USDC}, (
            decision.summary
        )


def test_a_yield_alert_on_a_broken_body_falls_back_to_the_previous_decision():
    activation = _yield_activation()
    activation.inputs["pools"] = None
    activation.result = {
        "last_decision": {"evidence": {"received_tokens": [USDT, WBNB]}}
    }

    decision = _yield().evaluate(activation, reader=YieldReader())

    assert decision.kind == "alert"
    assert set(decision.evidence["received_tokens"]) == {USDT, WBNB}


def test_a_grid_alert_keeps_its_state_its_tokens_and_a_real_timestamp():
    """An alert that dropped `grid_state` would erase the fills and the cap, and the pass
    after would start a traded grid from its opening state."""
    from datetime import datetime

    activation = _grid_activation()
    first = _grid().evaluate(activation, reader=GridReader(price=540 * E18))
    activation.result = {"last_decision": {"evidence": first.evidence}}
    activation.inputs["base"] = STRANGER

    decision = _grid().evaluate(activation, reader=GridReader(price=540 * E18))

    assert decision.kind == "alert"
    assert decision.evidence["grid_state"]["spent_atomic"] == str(25 * E18)
    assert [e["level"] for e in decision.evidence["grid_state"]["fired"]] == [2]
    assert set(decision.evidence["received_tokens"]) == {USDT, WBNB}
    assert datetime.fromisoformat(decision.observed_at).tzinfo is not None


def test_a_grid_alert_with_no_session_keeps_the_pair_from_its_own_spec():
    activation = _grid_activation()
    activation.session = None

    decision = _grid().evaluate(activation, reader=GridReader(price=540 * E18))

    assert decision.kind == "alert"
    assert set(decision.evidence["received_tokens"]) == {USDT, WBNB}
    assert decision.observed_at
