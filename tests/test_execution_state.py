"""Which way an action may move, and the ways it may not.

The one that matters is the absence of an edge: there is no transition out of
`submitted`. A broadcast transaction is in the mempool, and a state machine that let
a record walk back to `authorized` would be describing a world where it could be
un-sent. The rest of the matrix is asserted exhaustively rather than by example,
because a state machine tested only on its happy path is a state machine whose
illegal edges nobody has looked at.
"""

import re

import pytest

from docket.api.models import BANNED_FIELD_NAMES
from docket.execution.state import (
    ALLOWED,
    PRE_SUBMISSION,
    TERMINAL,
    ActionLifecycle,
    ActionState,
    IllegalTransition,
)

HAPPY_PATH = (
    ActionState.SIMULATED,
    ActionState.AUTHORIZED,
    ActionState.ACTIVE,
    ActionState.SUBMITTED,
    ActionState.CONFIRMED,
)


def _walk(lifecycle: ActionLifecycle, *states: ActionState) -> ActionLifecycle:
    for state in states:
        lifecycle.transition(state, reason="walked in a test")
    return lifecycle


def _at(state: ActionState) -> ActionLifecycle:
    """A lifecycle standing in `state`, having got there the legal way."""
    routes = {
        ActionState.DRAFT: (),
        ActionState.SIMULATED: (ActionState.SIMULATED,),
        ActionState.AUTHORIZED: (ActionState.SIMULATED, ActionState.AUTHORIZED),
        ActionState.ACTIVE: (ActionState.SIMULATED, ActionState.AUTHORIZED, ActionState.ACTIVE),
        ActionState.SUBMITTED: HAPPY_PATH[:4],
        ActionState.CONFIRMED: HAPPY_PATH,
        ActionState.FAILED: HAPPY_PATH[:4] + (ActionState.FAILED,),
        ActionState.PAUSED: (ActionState.PAUSED,),
        ActionState.EXPIRED: (ActionState.EXPIRED,),
        ActionState.REVOKED: (ActionState.REVOKED,),
    }
    return _walk(ActionLifecycle("grid-1-level-3"), *routes[state])


# ------------------------------------------------------------------ the shape


def test_the_states_are_the_ten_this_plane_has_and_no_others():
    assert {state.value for state in ActionState} == {
        "draft",
        "simulated",
        "authorized",
        "active",
        "submitted",
        "confirmed",
        "failed",
        "paused",
        "expired",
        "revoked",
    }


def test_a_fresh_action_is_a_draft_that_has_not_moved():
    lifecycle = ActionLifecycle("grid-1-level-3")
    assert lifecycle.state is ActionState.DRAFT
    assert lifecycle.history == ()
    assert lifecycle.intent_id == "grid-1-level-3"


def test_the_pre_submission_states_are_the_four_an_action_can_still_be_stopped_in():
    assert PRE_SUBMISSION == frozenset(
        {
            ActionState.DRAFT,
            ActionState.SIMULATED,
            ActionState.AUTHORIZED,
            ActionState.ACTIVE,
        }
    )


def test_the_terminal_states_are_the_ones_nothing_leaves():
    """`submitted` is not among them — it has two outcomes. It is nonetheless a state
    with no way back, which is a different property and is asserted separately."""
    assert TERMINAL == frozenset(
        {
            ActionState.CONFIRMED,
            ActionState.FAILED,
            ActionState.EXPIRED,
            ActionState.REVOKED,
        }
    )
    for state in TERMINAL:
        assert ALLOWED[state] == frozenset(), state


# ------------------------------------------------------------- the legal walk


def test_an_action_walks_draft_to_confirmed():
    lifecycle = _walk(ActionLifecycle("grid-1-level-3"), *HAPPY_PATH)
    assert lifecycle.state is ActionState.CONFIRMED
    assert [step.to_state for step in lifecycle.history] == list(HAPPY_PATH)


def test_a_submitted_action_may_also_have_failed():
    lifecycle = _at(ActionState.SUBMITTED)
    lifecycle.transition(ActionState.FAILED, reason="the router reverted")
    assert lifecycle.state is ActionState.FAILED


def test_a_step_may_not_be_skipped():
    """Straight from draft to active would be an action nobody simulated and nobody
    authorised, which is the whole sequence this machine exists to require."""
    for target in (ActionState.AUTHORIZED, ActionState.ACTIVE, ActionState.SUBMITTED):
        with pytest.raises(IllegalTransition):
            ActionLifecycle("x").transition(target, reason="skipping")


# ------------------------------------------------------- there is no un-sending


def test_the_only_two_moves_out_of_submitted_are_the_two_things_the_chain_can_answer():
    """Confirmed or failed, and nothing else. Every other edge out of `submitted` would
    be Docket asserting an outcome the chain has not given it."""
    assert ALLOWED[ActionState.SUBMITTED] == frozenset({ActionState.CONFIRMED, ActionState.FAILED})


def test_a_submitted_action_can_never_return_to_authorized():
    """The headline absence. A transaction in the mempool is not recallable, and a
    record that said otherwise would be describing a state the chain does not have."""
    lifecycle = _at(ActionState.SUBMITTED)
    with pytest.raises(IllegalTransition):
        lifecycle.transition(ActionState.AUTHORIZED, reason="changed my mind")
    assert lifecycle.state is ActionState.SUBMITTED


@pytest.mark.parametrize("stop", [ActionState.PAUSED, ActionState.EXPIRED, ActionState.REVOKED])
def test_a_submitted_action_cannot_be_paused_expired_or_revoked_after_the_fact(stop):
    lifecycle = _at(ActionState.SUBMITTED)
    with pytest.raises(IllegalTransition):
        lifecycle.transition(stop, reason="too late")


# --------------------------------------------------------- the ways out, early


@pytest.mark.parametrize("start", sorted(PRE_SUBMISSION, key=lambda s: s.value))
@pytest.mark.parametrize("stop", [ActionState.PAUSED, ActionState.EXPIRED, ActionState.REVOKED])
def test_every_pre_submission_state_can_be_stopped(start, stop):
    lifecycle = _at(start)
    lifecycle.transition(stop, reason="stopped in a test")
    assert lifecycle.state is stop


def test_a_revoked_action_can_never_reach_submitted():
    """Monotonic, matching the session authority it stands in front of: a revoked key
    cannot be reactivated on chain, so a revoked record must not be reactivated here."""
    lifecycle = _at(ActionState.REVOKED)
    for target in ActionState:
        with pytest.raises(IllegalTransition):
            lifecycle.transition(target, reason="reactivating")
    assert lifecycle.state is ActionState.REVOKED


def test_an_expired_action_can_never_reach_submitted():
    lifecycle = _at(ActionState.EXPIRED)
    for target in ActionState:
        with pytest.raises(IllegalTransition):
            lifecycle.transition(target, reason="reviving")
    assert lifecycle.state is ActionState.EXPIRED


def test_a_paused_action_resumes_only_by_starting_over():
    """Pause is the one reversible stop, and it rewinds all the way to draft. An action
    resumed straight into active would be acting on a simulation taken before whatever
    caused the pause — which is the market it was paused for having moved."""
    assert ALLOWED[ActionState.PAUSED] == frozenset({ActionState.DRAFT})
    lifecycle = _at(ActionState.PAUSED)
    with pytest.raises(IllegalTransition):
        lifecycle.transition(ActionState.ACTIVE, reason="resuming")
    lifecycle.transition(ActionState.DRAFT, reason="resuming from the top")
    assert lifecycle.state is ActionState.DRAFT


# --------------------------------------------------- the exhaustive illegal matrix


def test_every_transition_the_table_does_not_permit_raises():
    """All hundred pairs, not the handful anybody thought of."""
    checked = 0
    for start in ActionState:
        for target in ActionState:
            if target in ALLOWED[start]:
                continue
            checked += 1
            lifecycle = _at(start)
            with pytest.raises(IllegalTransition):
                lifecycle.transition(target, reason="illegal")
            assert lifecycle.state is start, f"{start} moved on a refused transition to {target}"
    assert checked == len(ActionState) ** 2 - sum(len(ALLOWED[s]) for s in ActionState)


def test_a_refused_transition_names_both_ends_so_the_error_can_be_acted_on():
    with pytest.raises(IllegalTransition) as exc:
        ActionLifecycle("x").transition(ActionState.SUBMITTED, reason="nope")
    assert "draft" in str(exc.value) and "submitted" in str(exc.value)


# ------------------------------------------------------------------ the record


def test_every_transition_records_when_it_happened_and_why(monkeypatch):
    monkeypatch.setattr("docket.execution.state.now", lambda: 2_000_000_000)
    lifecycle = ActionLifecycle("grid-1-level-3")
    lifecycle.transition(ActionState.SIMULATED, reason="eth_call agreed with the bounds")
    step = lifecycle.history[-1]
    assert step.from_state is ActionState.DRAFT
    assert step.to_state is ActionState.SIMULATED
    assert step.at == 2_000_000_000
    assert step.reason == "eth_call agreed with the bounds"


def test_a_transition_with_no_reason_is_refused():
    """A history of states with no reasons is a history that cannot be read afterwards."""
    with pytest.raises(ValueError):
        ActionLifecycle("x").transition(ActionState.SIMULATED, reason="   ")


def test_the_history_cannot_be_edited_from_outside():
    lifecycle = _walk(ActionLifecycle("x"), ActionState.SIMULATED)
    history = lifecycle.history
    assert isinstance(history, tuple)
    history_again = lifecycle.history
    lifecycle.transition(ActionState.AUTHORIZED, reason="granted")
    assert len(history_again) == 1 and len(lifecycle.history) == 2


def test_the_record_serialises_to_plain_types_for_a_receipt(monkeypatch):
    monkeypatch.setattr("docket.execution.state.now", lambda: 2_000_000_000)
    lifecycle = _walk(ActionLifecycle("grid-1-level-3"), *HAPPY_PATH)
    record = lifecycle.as_record()
    assert record["intent_id"] == "grid-1-level-3"
    assert record["state"] == "confirmed"
    assert record["history"][0] == {
        "from_state": "draft",
        "to_state": "simulated",
        "at": 2_000_000_000,
        "reason": "walked in a test",
    }


def test_no_state_or_field_name_carries_verdict_language():
    names = [state.value for state in ActionState] + [
        "from_state",
        "to_state",
        "at",
        "reason",
        "intent_id",
        "state",
        "history",
    ]
    for name in names:
        for word in BANNED_FIELD_NAMES:
            assert not re.search(rf"\b{re.escape(word)}\b", name.lower()), name
