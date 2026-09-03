"""The state machine, and that it is the only thing deciding what may happen."""

import pytest

from docket.jobs.models import (
    ACTORS,
    CATEGORIES,
    NEXT_ACTION_KINDS,
    ONE_SHOT,
    ONE_SHOT_STATES,
    PERSISTENT,
    PERSISTENT_STATES,
    TRANSITIONS,
    Activation,
    Event,
    IllegalTransition,
    NextAction,
    Quote,
    Receipt,
    dumps,
    loads,
    new_activation_id,
    states_for,
    terminal_states_for,
)
from docket.marketplace.models import Category

FREE_QUOTE = Quote(
    asset="0x55d398326f99059fF775485246999027B3197955",
    amount_atomic="0",
    amount_display="free",
    pay_to=None,
    payment_scheme="free_tier",
)


def _activation(kind=ONE_SHOT, state="quoted", **overrides):
    fields = {
        "activation_id": new_activation_id(),
        "service_id": "range-doctor",
        "category": "rebalancing",
        "kind": kind,
        "owner": "0x451871A1753903FB8fdd64a6B838E95aB8D5B80f",
        "state": state,
        "quote": FREE_QUOTE,
        "policy": None,
        "session": None,
        "inputs": {"wallet": "0x1"},
        "result": None,
        "receipts": (),
        "events": (),
        "next_action": NextAction("connect_wallet"),
        "auth_nonce": "n",
        "created_at": "2026-09-03T00:00:00+00:00",
        "updated_at": "2026-09-03T00:00:00+00:00",
        "expires_at": None,
    }
    fields.update(overrides)
    return Activation(**fields)


def test_the_four_categories_are_the_four_the_marketplace_publishes():
    """Declared in `jobs.models` rather than imported so that module stays free of the
    catalogue. Pinned here, because two spellings of one taxonomy is the drift this
    duplication would otherwise buy."""
    assert set(CATEGORIES) == {category.value for category in Category}


def test_an_activation_id_is_a_prefix_and_twenty_four_hex_characters():
    ids = {new_activation_id() for _ in range(200)}

    assert len(ids) == 200
    for value in ids:
        assert value.startswith("act_")
        assert len(value) == 28
        assert all(character in "0123456789abcdef" for character in value[4:])


def test_every_declared_state_has_a_row_in_the_transition_table():
    """A state with no row is a state the machine can reach and never leave, and
    `may_move_to` would answer False for every move out of it without saying why."""
    assert set(TRANSITIONS[ONE_SHOT]) == set(ONE_SHOT_STATES)
    assert set(TRANSITIONS[PERSISTENT]) == set(PERSISTENT_STATES)
    for kind, states in ((ONE_SHOT, ONE_SHOT_STATES), (PERSISTENT, PERSISTENT_STATES)):
        for state, destinations in TRANSITIONS[kind].items():
            for destination in destinations:
                assert destination in states, f"{kind}:{state} -> {destination}"


def test_terminal_states_are_exactly_the_states_with_no_way_out():
    for kind in (ONE_SHOT, PERSISTENT):
        assert set(terminal_states_for(kind)) == {
            state for state, moves in TRANSITIONS[kind].items() if not moves
        }


def test_states_for_refuses_a_kind_that_does_not_exist():
    with pytest.raises(ValueError, match="unknown activation kind"):
        states_for("subscription")


def test_every_legal_transition_moves_and_records_who_moved_it():
    """The whole table walked, not a sample: the edge nobody tests is the edge that
    turns out to write the wrong `from_state` into somebody's history."""
    for kind, states in ((ONE_SHOT, ONE_SHOT_STATES), (PERSISTENT, PERSISTENT_STATES)):
        for state in states:
            for destination in TRANSITIONS[kind][state]:
                activation = _activation(kind=kind, state=state)
                activation.transition(
                    destination,
                    reason="walked",
                    actor="docket",
                    at="2026-09-03T01:00:00+00:00",
                )

                assert activation.state == destination
                assert activation.updated_at == "2026-09-03T01:00:00+00:00"
                assert activation.events[-1] == Event(
                    at="2026-09-03T01:00:00+00:00",
                    from_state=state,
                    to_state=destination,
                    reason="walked",
                    actor="docket",
                )


def test_every_illegal_transition_is_refused_and_changes_nothing():
    for kind, states in ((ONE_SHOT, ONE_SHOT_STATES), (PERSISTENT, PERSISTENT_STATES)):
        for state in states:
            legal = set(TRANSITIONS[kind][state])
            for destination in set(states) - legal:
                activation = _activation(kind=kind, state=state)
                with pytest.raises(IllegalTransition):
                    activation.transition(destination, reason="attempted", actor="user")

                assert activation.state == state
                assert activation.events == ()
                assert activation.updated_at == "2026-09-03T00:00:00+00:00"


def test_a_one_shot_activation_has_no_persistent_state_and_the_reverse():
    with pytest.raises(ValueError, match="has no state 'active'"):
        _activation(kind=ONE_SHOT, state="active")
    with pytest.raises(ValueError, match="has no state 'completed'"):
        _activation(kind=PERSISTENT, state="completed")


def test_a_note_records_without_moving():
    activation = _activation(state="authorized")

    activation.note("read the chain and found nothing to do", actor="chain", at="t1")

    assert activation.state == "authorized"
    assert activation.events[-1].from_state == "authorized"
    assert activation.events[-1].to_state == "authorized"
    assert activation.updated_at == "t1"


def test_an_event_needs_a_known_actor_and_a_reason():
    with pytest.raises(ValueError, match="unknown event actor"):
        Event(at="t", from_state="a", to_state="b", reason="r", actor="operator")
    with pytest.raises(ValueError, match="records nothing worth keeping"):
        Event(at="t", from_state="a", to_state="b", reason="   ", actor="user")
    assert set(ACTORS) == {"user", "docket", "chain"}


def test_a_next_action_comes_from_the_closed_vocabulary():
    for kind in NEXT_ACTION_KINDS:
        assert NextAction(kind).kind == kind
    with pytest.raises(ValueError, match="unknown next action"):
        NextAction("call_the_owner")


def test_a_priced_quote_must_name_who_is_paid():
    with pytest.raises(ValueError, match="must name the address that is paid"):
        Quote(
            asset="0xasset",
            amount_atomic="1",
            amount_display="0.50 USDT",
            pay_to=None,
            payment_scheme="x402-exact",
        )
    with pytest.raises(ValueError, match="unknown payment scheme"):
        Quote(
            asset="0xasset",
            amount_atomic="1",
            amount_display="d",
            pay_to="0x1",
            payment_scheme="invoice",
        )


def test_a_hire_receipt_travels_through_an_activation_unreshaped():
    hire = {
        "service": "range-doctor",
        "input_hash": "0xin",
        "output_hash": "0xout",
        "delivered_at": "2026-09-03T00:00:00+00:00",
        "payment": {"status": "free_tier"},
    }

    receipt = Receipt.from_hire(hire)

    assert receipt.to_dict() == {**hire, "execution": None}


def test_an_activation_round_trips_through_json_with_everything_on_it():
    activation = _activation(state="quoted")
    activation.transition("awaiting_wallet", reason="signed", actor="user", at="t1")
    activation.add_receipt(
        Receipt(
            service="range-doctor",
            input_hash="0xin",
            output_hash="0xout",
            delivered_at="t1",
            payment=None,
            execution={"tx_hash": "0xabc"},
        )
    )
    activation.next_action = NextAction("wait", {"then": "the tick"})

    restored = Activation.from_dict(loads(dumps(activation.to_dict())))

    assert restored == activation


def test_an_unknown_category_is_refused_at_construction():
    with pytest.raises(ValueError, match="unknown category"):
        _activation(category="market_making")
