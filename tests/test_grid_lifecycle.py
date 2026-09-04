"""The grid as a thing that runs, rather than a thing that is previewed once.

Four properties are asserted harder than the rest, because they are the four a reader
should press on.

**Nothing rests on chain, and every summary says so.** The category verb is "places and
manages automated grid orders" and PancakeSwap V2 has no order book, so the word "order"
is a level Docket watches. A build that stopped saying that would be selling a resting
order it does not have, and the disclosure is asserted here rather than reviewed.

**Every draft carries a floor.** No path produces a swap with `amountOutMin` of zero, and
the floor written into the calldata is the router's own live quote less exactly the
slippage the spec allows.

**Stop, expiry, pause and cancel are four different things and none of them is the
others.** Each has its own test, and each asserts what the grid does *next* as well as
what it returns.

**A fill is read off the chain, not assumed.** `detect_fills` decodes Transfer logs; a
receipt whose logs show nothing moving to or from the session is not turned into a fill.
"""

import pytest
from web3 import Web3

from docket.agents.grid.lifecycle import (
    DEADLINE_S,
    GAS_CEILING,
    MAX_LEVELS,
    NO_RESTING_ORDERS,
    Fill,
    Fired,
    GridRefused,
    GridSpec,
    GridState,
    cancel,
    detect_fills,
    evaluate,
    pause,
    record_fills,
    resume,
    revoke,
)
from docket.agents.grid.operator import Observation
from docket.execution.simulate import PANCAKE_V2_ROUTER, ROUTER_ABI

USDT = Web3.to_checksum_address("0x55d398326f99059fF775485246999027B3197955")
WBNB = Web3.to_checksum_address("0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c")
USDC = Web3.to_checksum_address("0x8AC76a51cc950d9822D68b83fE1Ad97B32Cd580d")
STRANGER = Web3.to_checksum_address("0x000000000000000000000000000000000000dEaD")
SESSION = Web3.to_checksum_address("0x429898ba0Fc5b9F1fF0a8f0BD1D6D3cB33B26DdD")
POOL = Web3.to_checksum_address("0x1111111111111111111111111111111111111111")
FROZEN_NOW = 2_000_000_000
E18 = 10**18
BLOCK = 40_000_000
_decoder = Web3().eth.contract(abi=ROUTER_ABI)


@pytest.fixture(autouse=True)
def frozen_clock(monkeypatch):
    for module in ("docket.execution.intent", "docket.execution.simulate"):
        monkeypatch.setattr(f"{module}.now", lambda: FROZEN_NOW)


class Reader:
    """A router that prices one pair, an allowance, and a count of what it was asked.

    `allowance` defaults to unlimited so most tests exercise the settled case, where the
    session has already approved the router and one swap is the whole batch. Setting it
    short is what draws the exact-amount approval out in front.
    """

    def __init__(
        self,
        price: int,
        *,
        gas: int = 180_000,
        fail_estimate: bool = False,
        allowance: int | None = 2**255,
        receipts: dict | None = None,
    ):
        self.price = price
        self.gas = gas
        self.fail_estimate = fail_estimate
        self.allowance = allowance
        self.receipts = receipts or {}
        self.estimates: list[tuple] = []
        self.reads: list[tuple] = []

    def block_number(self) -> int:
        return BLOCK

    def call(self, sender, target, calldata):
        self.reads.append((sender, target, calldata))
        assert (
            calldata[:4].hex()
            == Web3.keccak(text="allowance(address,address)")[:4].hex()
        )
        if self.allowance is None:
            raise RuntimeError("the node did not answer")
        return self.allowance.to_bytes(32, "big")

    def transaction_receipt(self, tx_hash):
        return self.receipts.get(tx_hash)

    def amounts_out(self, amount_in, route):
        route = tuple(Web3.to_checksum_address(hop) for hop in route)
        if route == (WBNB, USDT):
            return [amount_in, amount_in * self.price // E18]
        if route == (USDT, WBNB):
            return [amount_in, amount_in * E18 // self.price]
        raise AssertionError(f"unexpected route {route}")

    def estimate_gas(self, sender, target, calldata):
        self.estimates.append((sender, target, calldata))
        if self.fail_estimate:
            raise RuntimeError("execution reverted: TRANSFER_FROM_FAILED")
        # An approval is one storage write and a swap is not. A single flat figure would
        # either sit above every ceiling in the batch or below every one of them, and a
        # fixture that cannot fail a ceiling is not checking the ceilings are there.
        if calldata[:4].hex() == "095ea7b3":
            return 46_000
        return self.gas


def _spec(**overrides) -> GridSpec:
    fields = {
        "base": WBNB,
        "quote": USDT,
        "price_lower": 500 * E18,
        "price_upper": 700 * E18,
        "levels": 5,
        "amount_per_level_atomic": 25 * E18,
        "total_cap_atomic": 100 * E18,
        "expires_at": FROZEN_NOW + 86_400,
        "max_slippage_bps": 50,
    }
    fields.update(overrides)
    return GridSpec(**fields)


def _observed(price: int) -> Observation:
    return Observation(price=price, block_number=BLOCK, source="router.getAmountsOut")


def _decode_swap(call):
    return _decoder.decode_function_input(call.data)[1]


def _swap(decision):
    """The swap is always the last call in a fire: an approval only ever precedes it."""
    return decision.prepared[-1]


# ------------------------------------------------------------------ the spec itself


def test_the_ladder_lands_exactly_on_both_ends_of_the_band():
    prices = _spec().level_prices()

    assert prices[0] == 500 * E18
    assert prices[-1] == 700 * E18
    assert prices == (500 * E18, 550 * E18, 600 * E18, 650 * E18, 700 * E18)


def test_the_spec_publishes_that_no_order_rests_on_chain():
    record = _spec().as_record()

    assert record["no_resting_orders"] == NO_RESTING_ORDERS
    assert "no order book" in NO_RESTING_ORDERS
    assert "Cancelling costs no gas" in NO_RESTING_ORDERS


@pytest.mark.parametrize(
    ("overrides", "fragment"),
    (
        ({"base": STRANGER}, "asset allowlist"),
        ({"quote": STRANGER}, "asset allowlist"),
        ({"base": USDT}, "same token"),
        ({"price_lower": 0}, "positive price"),
        ({"price_upper": 400 * E18}, "not above"),
        ({"levels": 1}, "at least two levels"),
        ({"amount_per_level_atomic": 0}, "must be positive"),
        ({"total_cap_atomic": E18}, "below one level"),
        ({"max_slippage_bps": 0}, "outside 1..500"),
        ({"max_slippage_bps": 501}, "outside 1..500"),
        ({"expires_at": 0}, "unix second"),
        ({"direction_rule": "sell_below_buy_above"}, "direction_rule"),
        ({"stop_price": 600 * E18}, "inside the band"),
        ({"stop_price": -1}, "positive price"),
        ({"levels": 5.0}, "must be an integer"),
    ),
)
def test_every_unrunnable_spec_is_refused_with_the_field_that_made_it_so(
    overrides, fragment
):
    with pytest.raises(GridRefused, match=fragment):
        _spec(**overrides).validate()


# ------------------------------------------------------------------ firing rules


def test_a_price_below_the_reference_fires_the_buy_level_nearest_the_reference():
    """The first level crossed, not the best one on offer.

    Taking the far level would fill at the deepest discount and leave every level in
    between waiting for a price they have already passed.
    """
    reader = Reader(price=540 * E18)
    state = GridState(reference_price=620 * E18)

    decision = evaluate(
        state,
        _observed(540 * E18),
        _spec(),
        reader=reader,
        session_address=SESSION,
        now=FROZEN_NOW,
    )

    assert decision.kind == "fire"
    assert decision.level.side == "buy"
    assert decision.level.price == 600 * E18
    assert decision.level.token_in == USDT
    assert decision.level.token_out == WBNB


def test_a_price_above_the_reference_fires_the_sell_level_nearest_the_reference():
    reader = Reader(price=690 * E18)
    state = GridState(reference_price=520 * E18)

    decision = evaluate(
        state,
        _observed(690 * E18),
        _spec(),
        reader=reader,
        session_address=SESSION,
        now=FROZEN_NOW,
    )

    assert decision.kind == "fire"
    assert decision.level.side == "sell"
    assert decision.level.price == 550 * E18
    assert decision.level.token_in == WBNB


def test_the_first_observation_fixes_the_reference_the_sides_are_computed_against():
    """Sides re-derived against every new observation would never fire anything: a level
    below "current" stops being below it the moment current moves down to meet it."""
    reader = Reader(price=600 * E18)

    decision = evaluate(
        GridState(),
        _observed(600 * E18),
        _spec(),
        reader=reader,
        session_address=SESSION,
        now=FROZEN_NOW,
    )

    assert decision.state.reference_price == 600 * E18


def test_a_price_inside_the_band_that_reaches_nothing_waits():
    reader = Reader(price=600 * E18)

    decision = evaluate(
        GridState(reference_price=600 * E18),
        _observed(600 * E18),
        _spec(),
        reader=reader,
        session_address=SESSION,
        now=FROZEN_NOW,
    )

    assert decision.kind == "noop"
    assert "waiting" in decision.reason
    assert decision.prepared == ()


def test_a_level_that_already_filled_is_not_drafted_again():
    reader = Reader(price=540 * E18)
    state = GridState(
        reference_price=620 * E18,
        fills=(
            Fill(
                level=2,
                side="buy",
                amount_in=25 * E18,
                amount_out=E18 // 20,
                tx_hash="0xabc",
                block=BLOCK - 10,
            ),
        ),
    )

    decision = evaluate(
        state,
        _observed(540 * E18),
        _spec(),
        reader=reader,
        session_address=SESSION,
        now=FROZEN_NOW,
    )

    assert decision.kind == "fire"
    assert decision.level.index == 1
    assert decision.level.price == 550 * E18


# ------------------------------------------------------------------ the drafted swap


def test_the_drafted_swap_carries_the_live_quote_less_exactly_the_stated_slippage():
    reader = Reader(price=540 * E18)

    decision = evaluate(
        GridState(reference_price=620 * E18),
        _observed(540 * E18),
        _spec(max_slippage_bps=125),
        reader=reader,
        session_address=SESSION,
        now=FROZEN_NOW,
    )

    quoted = 25 * E18 * E18 // (540 * E18)
    args = _decode_swap(_swap(decision))
    assert args["amountIn"] == 25 * E18
    assert args["amountOutMin"] == quoted * (10_000 - 125) // 10_000
    assert args["amountOutMin"] > 0
    assert args["path"] == [USDT, WBNB]
    assert args["to"] == SESSION
    assert args["deadline"] == FROZEN_NOW + DEADLINE_S
    assert _swap(decision).to == PANCAKE_V2_ROUTER
    assert _swap(decision).gas_ceiling == GAS_CEILING
    assert _swap(decision).value_atomic == "0"


def test_the_prepared_call_records_the_simulation_that_ran_and_its_block():
    reader = Reader(price=540 * E18)

    decision = evaluate(
        GridState(reference_price=620 * E18),
        _observed(540 * E18),
        _spec(),
        reader=reader,
        session_address=SESSION,
        now=FROZEN_NOW,
    )

    simulation = _swap(decision).simulation
    assert simulation["ok"] is True
    assert simulation["gas_estimate"] == 180_000
    assert simulation["revert_reason"] is None
    assert simulation["block"] == BLOCK
    assert "router.getAmountsOut" in simulation["checks"]
    assert "eth_estimateGas" in simulation["checks"]
    assert reader.estimates[0][0] == SESSION


def test_a_swap_the_chain_refuses_comes_back_as_an_alert_and_never_as_a_fire():
    reader = Reader(price=540 * E18, fail_estimate=True)

    decision = evaluate(
        GridState(reference_price=620 * E18),
        _observed(540 * E18),
        _spec(),
        reader=reader,
        session_address=SESSION,
        now=FROZEN_NOW,
    )

    assert decision.kind == "alert"
    assert _swap(decision).simulation["ok"] is False
    assert "TRANSFER_FROM_FAILED" in _swap(decision).simulation["revert_reason"]
    assert decision.state.spent_atomic == 0


def test_a_quote_too_small_to_leave_a_floor_is_refused_rather_than_floored_to_zero():
    """`amountOutMin` of zero is the one value no action in this package may carry."""
    reader = Reader(price=10**40)

    decision = evaluate(
        GridState(reference_price=620 * E18),
        _observed(540 * E18),
        _spec(),
        reader=reader,
        session_address=SESSION,
        now=FROZEN_NOW,
    )

    assert decision.kind == "alert"
    assert "no floor at all" in decision.reason
    assert decision.prepared == ()


def test_every_fired_summary_repeats_that_nothing_rested_on_chain():
    reader = Reader(price=540 * E18)

    decision = evaluate(
        GridState(reference_price=620 * E18),
        _observed(540 * E18),
        _spec(),
        reader=reader,
        session_address=SESSION,
        now=FROZEN_NOW,
    )

    assert decision.evidence["no_resting_orders"] == NO_RESTING_ORDERS
    assert decision.as_record()["no_resting_orders"] == NO_RESTING_ORDERS
    assert "No order rests on chain" in _swap(decision).purpose


# ------------------------------------------------------------------ the four stops


def test_the_stop_price_cancels_the_remaining_levels_and_sends_nothing():
    reader = Reader(price=480 * E18)

    decision = evaluate(
        GridState(reference_price=620 * E18),
        _observed(480 * E18),
        _spec(stop_price=490 * E18),
        reader=reader,
        session_address=SESSION,
        now=FROZEN_NOW,
    )

    assert decision.kind == "cancel"
    assert decision.prepared == ()
    assert decision.state.cancelled is True
    assert decision.state.open_levels == ()
    assert decision.state.revoked is False
    assert "not a stop order" in decision.reason


def test_a_stop_above_the_band_fires_on_the_way_up_instead():
    reader = Reader(price=760 * E18)

    decision = evaluate(
        GridState(reference_price=620 * E18),
        _observed(760 * E18),
        _spec(stop_price=750 * E18),
        reader=reader,
        session_address=SESSION,
        now=FROZEN_NOW,
    )

    assert decision.kind == "cancel"


def test_expiry_reaches_the_revoke_path_on_its_own():
    """A session that outlives the spec justifying it is what the expiry exists to stop,
    so an expired grid asks to be swept rather than merely stopping."""
    reader = Reader(price=540 * E18)

    decision = evaluate(
        GridState(reference_price=620 * E18),
        _observed(540 * E18),
        _spec(expires_at=FROZEN_NOW - 1),
        reader=reader,
        session_address=SESSION,
        now=FROZEN_NOW,
    )

    assert decision.kind == "revoke"
    assert decision.state.revoked is True
    assert decision.prepared == ()


def test_expiry_still_revokes_a_grid_that_was_paused_or_cancelled_first():
    reader = Reader(price=540 * E18)

    for state in (
        GridState(reference_price=620 * E18, paused=True),
        GridState(reference_price=620 * E18, cancelled=True),
    ):
        decision = evaluate(
            state,
            _observed(540 * E18),
            _spec(expires_at=FROZEN_NOW - 1),
            reader=reader,
            session_address=SESSION,
            now=FROZEN_NOW,
        )
        assert decision.kind == "revoke"


def test_a_paused_grid_fires_nothing_and_keeps_its_levels():
    reader = Reader(price=540 * E18)

    decision = evaluate(
        pause(GridState(reference_price=620 * E18)),
        _observed(540 * E18),
        _spec(),
        reader=reader,
        session_address=SESSION,
        now=FROZEN_NOW,
    )

    assert decision.kind == "noop"
    assert "paused" in decision.reason
    assert decision.state.cancelled is False
    assert decision.state.revoked is False


def test_a_cancelled_grid_keeps_its_funds_and_a_revoked_one_does_not():
    cancelled = cancel(GridState(reference_price=620 * E18, open_levels=(0, 1, 2)))
    revoked = revoke(cancelled)

    assert cancelled.cancelled is True and cancelled.revoked is False
    assert cancelled.open_levels == ()
    assert revoked.revoked is True

    reader = Reader(price=540 * E18)
    for state, fragment in (
        (cancelled, "cancelling is a decision"),
        (revoked, "swept"),
    ):
        decision = evaluate(
            state,
            _observed(540 * E18),
            _spec(),
            reader=reader,
            session_address=SESSION,
            now=FROZEN_NOW,
        )
        assert decision.kind == "noop"
        assert fragment in decision.reason


def test_pause_is_the_reversible_one_and_the_others_are_not():
    resumed = resume(pause(GridState()))
    assert resumed.paused is False

    with pytest.raises(GridRefused, match="cancelled or revoked"):
        resume(cancel(GridState()))
    with pytest.raises(GridRefused, match="already retired"):
        cancel(revoke(GridState()))
    with pytest.raises(GridRefused, match="nothing to pause"):
        pause(revoke(GridState()))


# ------------------------------------------------------------------ the cap


def test_a_level_past_the_total_cap_is_refused_rather_than_trimmed_to_what_is_left():
    reader = Reader(price=540 * E18)
    state = GridState(reference_price=620 * E18, spent_atomic=90 * E18)

    decision = evaluate(
        state,
        _observed(540 * E18),
        _spec(),
        reader=reader,
        session_address=SESSION,
        now=FROZEN_NOW,
    )

    assert decision.kind == "noop"
    assert "refused rather than trimmed" in decision.reason
    assert decision.prepared == ()


def test_the_cap_moves_when_a_level_fires_and_not_when_it_fills():
    reader = Reader(price=540 * E18)

    fired = evaluate(
        GridState(reference_price=620 * E18),
        _observed(540 * E18),
        _spec(),
        reader=reader,
        session_address=SESSION,
        now=FROZEN_NOW,
    )
    assert fired.state.spent_atomic == 25 * E18

    filled = record_fills(
        fired.state,
        [Fill(1, "buy", 25 * E18, E18 // 20, "0xabc", BLOCK)],
    )
    assert filled.spent_atomic == 25 * E18
    assert filled.filled_levels == (1,)


# ------------------------------------------------------------------ fills off the chain


def _transfer_log(token: str, frm: str, to: str, value: int) -> dict:
    pad = lambda address: "0x" + "00" * 12 + address[2:].lower()  # noqa: E731
    return {
        "address": token,
        "topics": [
            "0x" + Web3.keccak(text="Transfer(address,address,uint256)").hex(),
            pad(frm),
            pad(to),
        ],
        "data": "0x" + format(value, "064x"),
    }


def _receipt(logs, *, level=None, tx="0xfeed", block=BLOCK):
    receipt = {"logs": logs, "transactionHash": tx, "blockNumber": block}
    if level is not None:
        receipt["level"] = level
    return receipt


def test_a_buy_is_read_off_the_transfer_logs_rather_than_taken_on_trust():
    receipt = _receipt(
        [
            _transfer_log(USDT, SESSION, POOL, 25 * E18),
            _transfer_log(WBNB, POOL, SESSION, 46 * 10**15),
        ],
        level=1,
    )

    (fill,) = detect_fills([receipt], _spec(), recipient=SESSION)

    assert fill.side == "buy"
    assert fill.amount_in == 25 * E18
    assert fill.amount_out == 46 * 10**15
    assert fill.level == 1
    assert fill.tx_hash == "0xfeed"
    assert fill.block == BLOCK


def test_a_sell_is_read_the_other_way_round():
    receipt = _receipt(
        [
            _transfer_log(WBNB, SESSION, POOL, 40 * 10**15),
            _transfer_log(USDT, POOL, SESSION, 27 * E18),
        ],
        level=3,
    )

    (fill,) = detect_fills([receipt], _spec(), recipient=SESSION)

    assert fill.side == "sell"
    assert fill.amount_in == 40 * 10**15
    assert fill.amount_out == 27 * E18


def test_the_pools_own_side_of_the_same_swap_is_not_read_as_a_fill_for_the_session():
    """Seen from the pool, a buy looks exactly like a sell. That is why the recipient is
    a required argument rather than something inferred from the logs."""
    receipt = _receipt(
        [
            _transfer_log(USDT, SESSION, POOL, 25 * E18),
            _transfer_log(WBNB, POOL, SESSION, 46 * 10**15),
        ]
    )

    (from_session,) = detect_fills([receipt], _spec(), recipient=SESSION)
    (from_pool,) = detect_fills([receipt], _spec(), recipient=POOL)

    assert from_session.side == "buy"
    assert from_pool.side == "sell"


def test_a_receipt_with_no_movement_for_the_session_is_not_invented_into_a_fill():
    receipts = [
        _receipt([]),
        _receipt([_transfer_log(USDT, STRANGER, POOL, 5 * E18)]),
        _receipt([_transfer_log(USDC, SESSION, POOL, 5 * E18)]),
        _receipt(
            [
                {
                    "address": USDT,
                    "topics": ["0x" + "11" * 32, "0x" + "00" * 32, "0x" + "00" * 32],
                    "data": "0x" + "00" * 32,
                }
            ]
        ),
    ]

    assert detect_fills(receipts, _spec(), recipient=SESSION) == ()


def test_a_receipt_without_a_level_yields_a_fill_with_no_invented_index():
    receipt = _receipt(
        [
            _transfer_log(USDT, SESSION, POOL, 25 * E18),
            _transfer_log(WBNB, POOL, SESSION, 46 * 10**15),
        ]
    )

    (fill,) = detect_fills([receipt], _spec(), recipient=SESSION)

    assert fill.level is None
    assert fill.as_record()["level"] is None


def test_byte_shaped_topics_and_hashes_decode_the_same_as_hex_ones():
    """web3 hands back `HexBytes` where a fixture hands back strings, and a decoder that
    only understood one of them would work in tests and fail against a node."""
    receipt = {
        "logs": [
            {
                "address": USDT,
                "topics": [
                    Web3.keccak(text="Transfer(address,address,uint256)"),
                    bytes(12) + bytes.fromhex(SESSION[2:]),
                    bytes(12) + bytes.fromhex(POOL[2:]),
                ],
                "data": (25 * E18).to_bytes(32, "big"),
            },
            {
                "address": WBNB,
                "topics": [
                    Web3.keccak(text="Transfer(address,address,uint256)"),
                    bytes(12) + bytes.fromhex(POOL[2:]),
                    bytes(12) + bytes.fromhex(SESSION[2:]),
                ],
                "data": (46 * 10**15).to_bytes(32, "big"),
            },
        ],
        "transactionHash": bytes.fromhex("ab" * 32),
        "blockNumber": BLOCK,
    }

    (fill,) = detect_fills([receipt], _spec(), recipient=SESSION)

    assert fill.side == "buy"
    assert fill.amount_in == 25 * E18
    assert fill.tx_hash == "0x" + "ab" * 32


# ------------------------------------------- a fired level does not fire again


def _fire(state, reader, spec=None):
    return evaluate(
        state,
        _observed(540 * E18),
        spec or _spec(),
        reader=reader,
        session_address=SESSION,
        now=FROZEN_NOW,
    )


def test_a_fired_level_is_out_of_play_before_its_receipt_is_read():
    """The defect this closes: a level whose swap is in flight read as open, so the next
    pass drafted it again, and the one after that, until the cap ran out."""
    reader = Reader(price=540 * E18)
    first = _fire(GridState(reference_price=620 * E18), reader)

    assert first.kind == "fire"
    assert first.level.index == 2
    assert [entry.level for entry in first.state.fired] == [2]
    assert first.state.fired[0].intent_key
    assert first.state.fired[0].input_hash
    assert first.state.fired[0].tx_hash is None
    assert 2 not in first.state.open_levels

    second = _fire(first.state, reader)
    assert second.kind == "fire"
    assert second.level.index == 1

    # 540 has crossed the levels at 600 and 550 and no others, so with both of them out
    # of play the grid waits — where before this it fired 600 again, and again.
    for state in (second.state,) * 3:
        waiting = _fire(state, reader)
        assert waiting.kind == "noop"
        assert "waiting" in waiting.reason


def test_a_confirmed_fill_moves_a_level_from_fired_to_filled_permanently():
    fired = GridState(
        reference_price=620 * E18,
        spent_atomic=25 * E18,
        fired=(Fired(level=2, intent_key="0xkey", input_hash="0xh2", tx_hash="0xfeed"),),
        open_levels=(0, 1, 3, 4),
    )

    settled = record_fills(
        fired,
        [Fill(2, "buy", 25 * E18, 46 * 10**15, "0xfeed", BLOCK)],
        notional_atomic=25 * E18,
    )

    assert settled.fired == ()
    assert settled.filled_levels == (2,)
    assert settled.closed_levels == (2,)
    assert settled.spent_atomic == 25 * E18
    assert 2 not in settled.open_levels


def test_a_reverted_swap_puts_its_level_back_and_gives_the_cap_back():
    """A swap that reverted traded nothing, so keeping it charged against the cap would
    spend the session's allowance on transactions that never happened."""
    fired = GridState(
        reference_price=620 * E18,
        spent_atomic=25 * E18,
        fired=(Fired(level=2, intent_key="0xkey", input_hash="0xh2", tx_hash="0xdead"),),
        open_levels=(0, 1, 3, 4),
    )

    reopened = record_fills(fired, [], reverted=[2], notional_atomic=25 * E18)

    assert reopened.fired == ()
    assert reopened.filled_levels == ()
    assert 2 in reopened.open_levels
    assert reopened.spent_atomic == 0

    again = _fire(reopened, Reader(price=540 * E18))
    assert again.kind == "fire"
    assert again.level.index == 2


def test_a_level_still_in_flight_is_neither_reopened_nor_filled():
    fired = GridState(
        reference_price=620 * E18,
        fired=(
            Fired(level=2, intent_key="0xkey", input_hash="0xh2", tx_hash="0xpending"),
            Fired(level=1, intent_key="0xkey2", input_hash="0xh1", tx_hash=None),
        ),
    )

    unchanged = record_fills(fired, [], notional_atomic=25 * E18)

    assert [entry.level for entry in unchanged.fired] == [2, 1]
    assert unchanged.closed_levels == (1, 2)


# ------------------------------------------- the allowance the router needs


def test_a_short_allowance_puts_an_exact_approval_in_front_of_the_swap():
    """Without it the swap reverts as TransferHelper: TRANSFER_FROM_FAILED — a
    transaction drafted, simulated, broadcast and paid for that could never have worked."""
    decision = _fire(
        GridState(reference_price=620 * E18), Reader(price=540 * E18, allowance=0)
    )

    assert decision.kind == "fire"
    assert len(decision.prepared) == 2
    approval, swap = decision.prepared
    assert approval.to == USDT
    assert approval.data.startswith("0x095ea7b3")
    assert Web3.to_checksum_address("0x" + approval.data[10:74][-40:]) == (
        PANCAKE_V2_ROUTER
    )
    amount = int(approval.data[74:138], 16)
    assert amount == 25 * E18
    assert amount != 2**256 - 1
    assert swap.to == PANCAKE_V2_ROUTER
    assert decision.evidence["approval_drafted"] is True
    assert decision.evidence["router_allowance"] == "0"


def test_an_allowance_that_already_covers_the_level_drafts_no_approval():
    decision = _fire(
        GridState(reference_price=620 * E18),
        Reader(price=540 * E18, allowance=25 * E18),
    )

    assert len(decision.prepared) == 1
    assert decision.prepared[0].to == PANCAKE_V2_ROUTER
    assert decision.evidence["approval_drafted"] is False


def test_the_swap_is_deferred_rather_than_failed_while_the_allowance_is_short():
    """`ok: None` is a third state from True and False, and the honest one here: what
    could be checked passed, and the estimate that could not is named with what lifts it."""
    reader = Reader(price=540 * E18, allowance=0)
    decision = _fire(GridState(reference_price=620 * E18), reader)
    swap = decision.prepared[-1]

    assert swap.simulation["ok"] is None
    assert swap.simulation["revert_reason"] is None
    assert "allowance" in swap.simulation["deferred"][0]
    assert "eth_estimateGas" not in swap.simulation["checks"]
    assert all(target == USDT for _sender, target, _data in reader.estimates)


def test_an_unreadable_allowance_drafts_the_approval_and_says_it_was_unreadable():
    """Zero and unknown are different: both draft the approval, which is the safe
    direction, but only one of them is a fact about the chain."""
    decision = _fire(
        GridState(reference_price=620 * E18), Reader(price=540 * E18, allowance=None)
    )

    assert len(decision.prepared) == 2
    assert decision.evidence["router_allowance"] is None
    assert decision.evidence["approval_drafted"] is True


def test_each_call_carries_its_own_deadline_a_window_further_out():
    decision = _fire(
        GridState(reference_price=620 * E18), Reader(price=540 * E18, allowance=0)
    )
    approval, swap = decision.prepared

    assert approval.deadline == FROZEN_NOW + DEADLINE_S
    assert swap.deadline == FROZEN_NOW + 2 * DEADLINE_S
    assert _decode_swap(swap)["deadline"] == swap.deadline


# ------------------------------------------- the remaining minors


def test_a_ladder_longer_than_the_ceiling_is_refused():
    with pytest.raises(GridRefused, match="above the ceiling"):
        _spec(levels=MAX_LEVELS + 1).validate()
    assert _spec(levels=MAX_LEVELS).validate().levels == MAX_LEVELS


def test_the_spec_record_can_leave_the_derived_ladder_out():
    spec = _spec()

    assert "level_prices" in spec.as_record()
    assert "level_prices" not in spec.as_record(with_levels=False)
    assert spec.as_record(with_levels=False)["price_lower"] == str(500 * E18)


def test_a_transfer_whose_hex_ends_in_zeros_is_not_read_as_nothing():
    """`text.strip("0x")` strips every leading and trailing 0 and x, so a value whose hex
    ends in zeros answered "nothing to parse" and a real transfer read as none."""
    receipt = _receipt(
        [
            _transfer_log(USDT, SESSION, POOL, 16**8),
            _transfer_log(WBNB, POOL, SESSION, 10**18),
        ],
        level=1,
    )

    (fill,) = detect_fills([receipt], _spec(), recipient=SESSION)

    assert fill.amount_in == 16**8
    assert fill.amount_out == 10**18
