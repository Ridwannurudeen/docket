"""The semantic commitment an autonomous action travels under.

An allowlist and a spend cap say which contract may be called and how much may leave
the wallet. They say nothing about the price it leaves at, so a permitted swap can
still be a terrible one. These tests hold the record that closes that gap: every
bound an action must honour is on the intent, the mandatory ones cannot be omitted,
and the calldata that gets submitted can be proved to be the calldata that was
authorised.
"""

import re

import pytest
from web3 import Web3

from docket.api.models import BANNED_FIELD_NAMES
from docket.execution import now
from docket.execution.intent import (
    CONDITION_KINDS,
    SLIPPAGE_BPS_CEILING,
    ActionIntent,
    Condition,
    commit,
)

# The live BSC addresses this build was written against, mixed-case as BscScan prints
# them so the normalisation rule is exercised by the fixture rather than only by one test.
ROUTER_V2 = "0x10ED43C718714eb63d5aA57B78B54704E256024E"
USDT = "0x55d398326f99059fF775485246999027B3197955"
WBNB = "0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c"
# swapExactTokensForTokens(uint256,uint256,address[],address,uint256)
SWAP_SELECTOR = "0x38ed1739"
CALLDATA = bytes.fromhex("38ed1739") + b"\x00" * 96


def _condition(**overrides) -> Condition:
    fields = {
        "kind": "price_at_or_below",
        "subject": f"{USDT}/{WBNB}",
        "threshold": 600 * 10**18,
    }
    fields.update(overrides)
    return Condition(**fields)


def _intent(**overrides) -> ActionIntent:
    """An intent that satisfies every rule, so each test can break exactly one."""
    fields = {
        "intent_id": "grid-1-level-3",
        "condition": _condition(),
        "chain_id": 56,
        "target": ROUTER_V2,
        "selector": SWAP_SELECTOR,
        "calldata_hash": commit(CALLDATA),
        "token_in": USDT,
        "token_out": WBNB,
        # USDT is 18 decimals on BSC, not 6. 25 USDT in, at least 0.04 WBNB back.
        "max_input": 25 * 10**18,
        "min_output": 4 * 10**16,
        "route": (USDT, WBNB),
        "slippage_bps": 50,
        "deadline": now() + 600,
        "gas_ceiling": 300_000,
        "nonce": 1,
        "policy_version": "grid-operator/1",
        "evidence_block": 115_155_027,
    }
    fields.update(overrides)
    return ActionIntent(**fields)


# ------------------------------------------------------------------- conditions


def test_a_condition_is_one_of_a_closed_set_of_predicates():
    """A free-text condition is a condition nobody can evaluate the same way twice."""
    assert CONDITION_KINDS == frozenset({"price_at_or_below", "price_at_or_above"})
    with pytest.raises(ValueError):
        _condition(kind="feels_cheap")


def test_a_condition_answers_over_an_observed_price_and_nothing_else():
    below = _condition(kind="price_at_or_below", threshold=600 * 10**18)
    assert below.holds(599 * 10**18)
    assert below.holds(600 * 10**18)
    assert not below.holds(601 * 10**18)

    above = _condition(kind="price_at_or_above", threshold=600 * 10**18)
    assert above.holds(601 * 10**18)
    assert above.holds(600 * 10**18)
    assert not above.holds(599 * 10**18)


def test_a_condition_threshold_is_an_integer_of_atomic_units():
    """A float threshold is a rounding error inside a commitment that is hashed."""
    with pytest.raises(ValueError):
        _condition(threshold=600.5)


# --------------------------------------------------------------- the mandatory bounds


def test_a_fully_specified_intent_constructs():
    intent = _intent()
    assert intent.chain_id == 56
    assert intent.min_output > 0
    assert intent.max_input > 0


def test_an_intent_with_no_minimum_output_is_refused():
    """ "Any output" is the single most expensive default in this whole package: a
    permitted swap with no floor is a permitted swap that can be sandwiched to nothing."""
    with pytest.raises(ValueError):
        _intent(min_output=0)
    with pytest.raises(ValueError):
        _intent(min_output=None)


def test_a_minimum_output_cannot_simply_be_left_off():
    fields = {
        "intent_id": "x",
        "condition": _condition(),
        "chain_id": 56,
        "target": ROUTER_V2,
        "selector": SWAP_SELECTOR,
        "calldata_hash": commit(CALLDATA),
        "token_in": USDT,
        "token_out": WBNB,
        "max_input": 25 * 10**18,
        "route": (USDT, WBNB),
        "slippage_bps": 50,
        "deadline": now() + 600,
        "gas_ceiling": 300_000,
        "nonce": 1,
        "policy_version": "grid-operator/1",
        "evidence_block": 115_155_027,
    }
    with pytest.raises(TypeError):
        ActionIntent(**fields)


def test_an_intent_with_no_maximum_input_is_refused():
    with pytest.raises(ValueError):
        _intent(max_input=0)


def test_slippage_beyond_the_hard_ceiling_is_refused_and_the_ceiling_itself_is_allowed():
    assert SLIPPAGE_BPS_CEILING == 500
    _intent(slippage_bps=SLIPPAGE_BPS_CEILING)
    with pytest.raises(ValueError):
        _intent(slippage_bps=SLIPPAGE_BPS_CEILING + 1)
    with pytest.raises(ValueError):
        _intent(slippage_bps=-1)


def test_a_deadline_already_past_is_refused():
    with pytest.raises(ValueError):
        _intent(deadline=now() - 1)


def test_a_deadline_is_read_from_the_packages_one_clock(monkeypatch):
    """Frozen so the check is the clock's and not the test runner's luck."""
    monkeypatch.setattr("docket.execution.intent.now", lambda: 2_000_000_000)
    _intent(deadline=2_000_000_060)
    with pytest.raises(ValueError):
        _intent(deadline=1_999_999_999)


def test_a_zero_gas_ceiling_is_refused():
    with pytest.raises(ValueError):
        _intent(gas_ceiling=0)


def test_any_chain_other_than_bsc_mainnet_is_refused():
    """This build has been exercised against one chain. An intent naming another is an
    intent whose router address means nothing."""
    for chain_id in (1, 97, 8453):
        with pytest.raises(ValueError):
            _intent(chain_id=chain_id)


def test_the_evidence_block_the_condition_was_read_at_is_required_to_be_real():
    with pytest.raises(ValueError):
        _intent(evidence_block=0)


# ------------------------------------------------------------- the route and the target


def test_a_route_must_begin_at_the_input_token_and_end_at_the_output_token():
    with pytest.raises(ValueError):
        _intent(route=(WBNB, USDT))
    with pytest.raises(ValueError):
        _intent(route=(USDT,))
    # A hop through an intermediate is fine as long as the ends are the declared tokens.
    hop = "0x2170Ed0880ac9A755fd29B2688956BD959F933F8"
    assert _intent(route=(USDT, hop, WBNB)).route[1] == hop


def test_addresses_are_normalised_so_the_same_intent_written_two_ways_is_one_intent():
    """A lowercased address and a checksummed one are the same account. If they hashed
    differently, the idempotency key would let the same action through twice."""
    lower = _intent(
        target=ROUTER_V2.lower(),
        token_in=USDT.lower(),
        token_out=WBNB.lower(),
        route=(USDT.lower(), WBNB.lower()),
    )
    assert lower.target == Web3.to_checksum_address(ROUTER_V2)
    assert lower.route == (Web3.to_checksum_address(USDT), Web3.to_checksum_address(WBNB))
    assert lower.idempotency_key == _intent().idempotency_key


def test_an_address_that_is_not_an_address_is_refused():
    with pytest.raises(ValueError):
        _intent(target="0xnot-an-address")


def test_a_selector_must_be_four_bytes():
    with pytest.raises(ValueError):
        _intent(selector="0x38ed17")
    with pytest.raises(ValueError):
        _intent(selector="38ed1739")


# ------------------------------------------------------- the calldata commitment


def test_the_calldata_that_was_authorised_can_be_told_from_calldata_that_was_not():
    """This is what makes a submitted transaction provably the authorised one rather
    than merely a call to an allowlisted contract."""
    intent = _intent()
    assert intent.matches(CALLDATA)
    assert not intent.matches(CALLDATA + b"\x01")
    assert not intent.matches(bytes.fromhex("38ed1739") + b"\xff" * 96)


def test_commit_is_keccak_over_the_exact_bytes():
    """Keccak because this is a chain-shaped commitment: a contract asked to check it
    computes the same digest with one opcode."""
    assert commit(CALLDATA) == "0x" + Web3.keccak(CALLDATA).hex()
    assert commit(b"") != commit(b"\x00")


def test_calldata_whose_selector_is_not_the_declared_one_does_not_match():
    """The declared selector is a second, independent statement about the call. If the
    bytes disagree with it, the record is describing something other than what it commits
    to, and the honest answer is no."""
    other = bytes.fromhex("18cbafe5") + b"\x00" * 96
    intent = _intent(selector="0x38ed1739", calldata_hash=commit(other))
    assert not intent.matches(other)


def test_calldata_shorter_than_a_selector_does_not_match():
    intent = _intent(calldata_hash=commit(b"\x38\xed"))
    assert not intent.matches(b"\x38\xed")


# -------------------------------------------------------------- idempotency key


def test_the_same_intent_always_produces_the_same_key():
    assert _intent().idempotency_key == _intent().idempotency_key


def test_a_different_nonce_is_a_different_action():
    assert _intent(nonce=1).idempotency_key != _intent(nonce=2).idempotency_key


@pytest.mark.parametrize(
    "field,value",
    [
        ("min_output", 5 * 10**16),
        ("max_input", 26 * 10**18),
        ("deadline", now() + 900),
        ("gas_ceiling", 400_000),
        ("target", "0x2170Ed0880ac9A755fd29B2688956BD959F933F8"),
        ("calldata_hash", commit(b"different")),
        ("policy_version", "grid-operator/2"),
        ("slippage_bps", 60),
    ],
)
def test_every_bound_is_inside_the_key_so_a_changed_bound_is_a_different_action(field, value):
    """A key that ignored min_output would let a re-priced action reuse the authorisation
    granted to a better one."""
    assert _intent(**{field: value}).idempotency_key != _intent().idempotency_key


def test_the_key_is_a_hash_a_third_party_can_recompute():
    key = _intent().idempotency_key
    assert key.startswith("0x") and len(key) == 66


# ------------------------------------------------------------------ no verdicts


def test_no_field_or_value_on_an_intent_carries_verdict_language():
    """The no-verdict contract binds this package too. An action record that called
    itself safe would be the one claim Docket has least standing to make."""
    intent = _intent()
    values = [
        intent.intent_id,
        intent.policy_version,
        intent.condition.kind,
        intent.condition.subject,
        *ActionIntent.__dataclass_fields__,
        *Condition.__dataclass_fields__,
        *CONDITION_KINDS,
    ]
    for value in values:
        for word in BANNED_FIELD_NAMES:
            assert not re.search(rf"\b{re.escape(word)}\b", value.lower()), (
                f"intent carries verdict language {word!r} in {value!r}"
            )


def test_a_boolean_is_not_a_quantity_of_anything():
    """`True` is an `int` in Python and passes an unwary `> 0`, so `min_output=True` would
    construct as a floor of one wei — an intent that reads as bounded and is not. Every
    other integer field on this record already refuses a bool; this one now does too."""
    for field in ("min_output", "max_input", "gas_ceiling", "slippage_bps", "nonce"):
        with pytest.raises(ValueError):
            _intent(**{field: True})


def test_a_nonce_must_be_a_whole_non_negative_number():
    """It goes into the idempotency key, so a nonce of a shape nobody expected is an
    action that keys unlike every other one and dedupes against nothing."""
    _intent(nonce=0)
    for bad in (-1, "1", 1.0, None):
        with pytest.raises((ValueError, TypeError)):
            _intent(nonce=bad)
