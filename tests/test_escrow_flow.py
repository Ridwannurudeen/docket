"""The hire sequence, checked as a sequence rather than as five separate encodings.

Every revert this builder exists to prevent was observed for real in E1/E1b, not
imagined: `RouterNotEvaluator` when the evaluator slot is anything but the router,
`PolicyNotSet` when fund precedes registerJob, `SubmissionTooLate` when submit misses
expiredAt. A builder that can emit an invalid order will eventually emit one, so the
order and the slots are asserted here, not left to the caller's care.
"""

import pytest
from web3 import Web3

from docket.escrow import constants as c
from docket.escrow.flow import ExpiryTooLong, hire_calls

PROVIDER = Web3.to_checksum_address("0x0936686CBaF6fF410AFE042B297D299afB46bfb0")
BUDGET = 10**16  # 0.01 $U


def _calls(**kw):
    return hire_calls(
        provider=kw.get("provider", PROVIDER),
        budget_atomic=kw.get("budget_atomic", BUDGET),
        expires_in_s=kw.get("expires_in_s", 7 * 86400),
        description=kw.get("description", "Docket escrow hire"),
        job_id=kw.get("job_id"),
    )


def test_the_order_is_the_one_that_actually_funds():
    assert [s["function"] for s in _calls()] == [
        "createJob",
        "registerJob",
        "setBudget",
        "approve",
        "fund",
    ]


def test_create_job_puts_the_router_in_both_the_evaluator_and_hook_slots():
    """E1b proved a plain EOA in the evaluator slot aborts the whole flow at
    registerJob with RouterNotEvaluator, so this is the one slot that cannot vary."""
    create = _calls()[0]
    assert create["args"]["evaluator"] == c.ROUTER
    assert create["args"]["hook"] == c.ROUTER
    assert create["args"]["provider"] == PROVIDER


def test_register_binds_the_whitelisted_policy_before_funding():
    steps = {s["function"]: i for i, s in enumerate(_calls())}
    assert steps["registerJob"] < steps["fund"]
    register = _calls()[1]
    assert register["args"]["policy"] == c.POLICY
    assert register["to"] == c.ROUTER


def test_approve_covers_the_budget_and_targets_the_commerce_contract():
    approve = next(s for s in _calls() if s["function"] == "approve")
    assert approve["to"] == c.PAYMENT_TOKEN
    assert approve["args"]["spender"] == c.COMMERCE
    assert int(approve["args"]["value"]) >= BUDGET


def test_an_expiry_past_the_kernel_maximum_is_refused_not_silently_clamped():
    """Clamping would hand back a job that expires on a date the caller never chose."""
    with pytest.raises(ExpiryTooLong):
        _calls(expires_in_s=c.MAX_EXPIRY_DURATION_S + 1)


def test_calldata_decodes_back_to_the_function_and_args_it_claims():
    """The encoded bytes are what actually gets signed; if they drift from the stated
    args, every other assertion here is decoration."""
    w3 = Web3()
    for step in _calls(job_id=4242):
        if step["calldata"] is None:
            continue
        contract = w3.eth.contract(abi=step["abi"])
        fn, args = contract.decode_function_input(step["calldata"])
        assert fn.fn_name == step["function"]
        for name, value in step["args"].items():
            assert args[name] == value


def test_steps_that_need_a_job_id_say_so_instead_of_guessing_one():
    """createJob's id is not known until the transaction lands, so the builder must not
    invent one; a fabricated id would encode a call against somebody else's job."""
    without = _calls()
    needs = [s for s in without if s["calldata"] is None]
    assert {s["function"] for s in needs} == {"registerJob", "setBudget", "fund"}
    assert all("job_id" in s["needs"] for s in needs)

    with_id = _calls(job_id=4242)
    assert all(s["calldata"] is not None for s in with_id)


def test_the_notes_state_the_window_and_the_submission_deadline():
    text = " ".join(s["note"] for s in _calls()).lower()
    assert "7 day" in text or "604800" in text
    assert "expiredat" in text or "expires" in text
