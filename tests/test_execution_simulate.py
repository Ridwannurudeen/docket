"""The preflight that stands between an authorised action and a bad one.

A session key with an allowlist and a cap will happily let a permitted swap execute at a
ruinous price. The intent carries the bounds that would catch that; this is where the
bounds get compared against what the chain says right now, and the rule the whole stage
turns on is asserted here: an action whose simulation disagrees with its intent is not
submitted. Not warned about, not submitted with a note — not submitted.
"""

import pytest
from web3 import Web3

from docket.execution.intent import ActionIntent, Condition, commit
from docket.execution.simulate import (
    PANCAKE_V2_ROUTER,
    ROUTER_ABI,
    SWAP_SIGNATURE,
    Simulation,
    simulate,
    swap_calldata,
)

USDT = "0x55d398326f99059fF775485246999027B3197955"
WBNB = "0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c"
WALLET = "0x429898ba0Fc5b9F1fF0a8f0BD1D6D3cB33B26DdD"
FROZEN_NOW = 2_000_000_000
E18 = 10**18

CALLDATA = swap_calldata(
    amount_in=25 * E18,
    min_output=4 * 10**16,
    route=(USDT, WBNB),
    recipient=WALLET,
    deadline=FROZEN_NOW + 600,
)


@pytest.fixture(autouse=True)
def frozen_clock(monkeypatch):
    monkeypatch.setattr("docket.execution.intent.now", lambda: FROZEN_NOW)
    monkeypatch.setattr("docket.execution.simulate.now", lambda: FROZEN_NOW)


def _intent(**overrides) -> ActionIntent:
    fields = {
        "intent_id": "grid-1-level-2",
        "condition": Condition("price_at_or_below", f"{WBNB}/{USDT}", 600 * E18),
        "chain_id": 56,
        "target": PANCAKE_V2_ROUTER,
        "selector": "0x38ed1739",
        "calldata_hash": commit(CALLDATA),
        "token_in": USDT,
        "token_out": WBNB,
        "max_input": 25 * E18,
        "min_output": 4 * 10**16,
        "route": (USDT, WBNB),
        "slippage_bps": 50,
        "deadline": FROZEN_NOW + 600,
        "gas_ceiling": 300_000,
        "nonce": 1,
        "policy_version": "grid-operator/1",
        "evidence_block": 115_155_027,
    }
    fields.update(overrides)
    return ActionIntent(**fields)


class FakeQuotes:
    def __init__(self, out=5 * 10**16, gas=180_000, raises=None, gas_raises=None):
        self._out = out
        self._gas = gas
        self._raises = raises
        self._gas_raises = gas_raises
        self.asked = []

    def block_number(self):
        return 115_155_027

    def amounts_out(self, amount_in, route):
        self.asked.append(("amounts_out", amount_in, tuple(route)))
        if self._raises is not None:
            raise self._raises
        return [amount_in, self._out]

    def estimate_gas(self, sender, target, calldata):
        self.asked.append(("estimate_gas", sender, target))
        if self._gas_raises is not None:
            raise self._gas_raises
        return self._gas


# --------------------------------------------------------------- the calldata


def test_the_calldata_is_the_v2_exact_input_swap_and_nothing_else():
    assert SWAP_SIGNATURE == ("swapExactTokensForTokens(uint256,uint256,address[],address,uint256)")
    assert CALLDATA[:4].hex() == "38ed1739"
    decoded = Web3().eth.contract(abi=ROUTER_ABI).decode_function_input(CALLDATA)[1]
    assert decoded["amountIn"] == 25 * E18
    assert decoded["amountOutMin"] == 4 * 10**16
    assert decoded["path"] == [Web3.to_checksum_address(USDT), Web3.to_checksum_address(WBNB)]
    assert decoded["to"] == Web3.to_checksum_address(WALLET)


def test_calldata_built_from_the_same_arguments_is_byte_identical():
    """It is hashed into the intent, so a builder that varied would break the one
    property that makes a submitted transaction provably the authorised one."""
    again = swap_calldata(
        amount_in=25 * E18,
        min_output=4 * 10**16,
        route=(USDT.lower(), WBNB.lower()),
        recipient=WALLET.lower(),
        deadline=FROZEN_NOW + 600,
    )
    assert again == CALLDATA


def test_calldata_for_a_swap_with_no_floor_cannot_be_built():
    with pytest.raises(ValueError):
        swap_calldata(
            amount_in=25 * E18,
            min_output=0,
            route=(USDT, WBNB),
            recipient=WALLET,
            deadline=FROZEN_NOW + 600,
        )


# ------------------------------------------------------------- what agreement is


def test_a_quote_above_the_floor_agrees():
    sim = simulate(_intent(), CALLDATA, reader=FakeQuotes(out=5 * 10**16))
    assert sim.agrees, sim.reason
    assert sim.expected_output == 5 * 10**16
    assert sim.block_number == 115_155_027
    assert sim.checks == ("intent.matches", "router.getAmountsOut")


def test_a_quote_below_the_floor_does_not_agree():
    """The whole point. An allowlisted, capped, funded swap that returns less than the
    intent's minimum is exactly the trade nobody would have authorised on purpose."""
    sim = simulate(_intent(), CALLDATA, reader=FakeQuotes(out=3 * 10**16))
    assert not sim.agrees
    assert "min_output" in sim.reason
    assert sim.expected_output == 3 * 10**16


def test_a_quote_exactly_at_the_floor_agrees():
    assert simulate(_intent(), CALLDATA, reader=FakeQuotes(out=4 * 10**16)).agrees


def test_calldata_that_is_not_the_committed_calldata_never_reaches_the_chain():
    """Refused before a single call is made, because a mismatch means the record being
    checked and the bytes being sent are two different actions."""
    reader = FakeQuotes()
    sim = simulate(_intent(), CALLDATA + b"\x01", reader=reader)
    assert not sim.agrees
    assert "calldata" in sim.reason.lower()
    assert reader.asked == []
    assert sim.checks == ("intent.matches",)


def test_a_reverting_quote_does_not_agree_and_says_what_failed():
    sim = simulate(
        _intent(), CALLDATA, reader=FakeQuotes(raises=RuntimeError("INSUFFICIENT_LIQUIDITY"))
    )
    assert not sim.agrees
    assert "INSUFFICIENT_LIQUIDITY" in sim.reason
    assert sim.expected_output is None


def test_an_intent_whose_deadline_has_passed_does_not_agree():
    """Checked here as well as at construction: an intent built a minute ago and reached
    now is a different question from an intent built with a stale deadline."""
    intent = _intent()
    sim = simulate(intent, CALLDATA, reader=FakeQuotes(), now_override=FROZEN_NOW + 601)
    assert not sim.agrees
    assert "deadline" in sim.reason.lower()


def test_the_quote_is_asked_for_the_intents_own_input_and_route():
    reader = FakeQuotes()
    simulate(_intent(), CALLDATA, reader=reader)
    assert reader.asked[0] == (
        "amounts_out",
        25 * E18,
        (Web3.to_checksum_address(USDT), Web3.to_checksum_address(WBNB)),
    )


# --------------------------------------------------------------------- the gas


def test_no_sender_means_no_gas_estimate_and_the_record_says_which_checks_ran():
    """A preview has no account that could execute the swap, so the estimate is not
    attempted rather than guessed. What was and was not checked is on the record."""
    sim = simulate(_intent(), CALLDATA, reader=FakeQuotes())
    assert sim.gas is None
    assert "eth_estimateGas" not in sim.checks


def test_a_sender_gets_an_estimate_and_the_ceiling_is_enforced():
    sim = simulate(_intent(), CALLDATA, reader=FakeQuotes(gas=180_000), sender=WALLET)
    assert sim.agrees and sim.gas == 180_000
    assert sim.checks == ("intent.matches", "router.getAmountsOut", "eth_estimateGas")

    over = simulate(_intent(), CALLDATA, reader=FakeQuotes(gas=400_000), sender=WALLET)
    assert not over.agrees
    assert "gas_ceiling" in over.reason


def test_a_reverting_estimate_does_not_agree():
    sim = simulate(
        _intent(),
        CALLDATA,
        reader=FakeQuotes(gas_raises=RuntimeError("TRANSFER_FROM_FAILED")),
        sender=WALLET,
    )
    assert not sim.agrees
    assert "TRANSFER_FROM_FAILED" in sim.reason


# ------------------------------------------------------------------ the record


def test_a_simulation_serialises_to_plain_types():
    record = simulate(_intent(), CALLDATA, reader=FakeQuotes(), sender=WALLET).as_record()
    assert record["agrees"] is True
    assert record["expected_output"] == str(5 * 10**16)
    assert record["gas"] == 180_000
    assert record["checks"] == [
        "intent.matches",
        "router.getAmountsOut",
        "eth_estimateGas",
    ]


def test_a_simulation_cannot_claim_agreement_with_no_output_at_all():
    """Belt and braces on the one field a caller keys off. A record that agreed while
    knowing nothing about the output would be the exact failure this module prevents."""
    with pytest.raises(ValueError):
        Simulation(
            agrees=True,
            reason="fine",
            expected_output=None,
            gas=None,
            block_number=1,
            checks=(),
        )


def test_the_router_this_build_quotes_against_is_the_verified_one():
    assert PANCAKE_V2_ROUTER == "0x10ED43C718714eb63d5aA57B78B54704E256024E"
