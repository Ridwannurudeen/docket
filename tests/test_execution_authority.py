"""Who says this action may happen, and where that answer is enforced.

The distinction these tests exist to keep visible: a check written in Python is not a
limit. The caps, the allowlist and the expiry have to be enforced by the session
authority on chain, which reverts at validation time; anything here is a second,
narrower gate that may only ever refuse more. So every status carries the `source` it
was read from, and the stub says `stub` in that field where a live authority would say
`chain` — a test asserts it, because the day that distinction becomes decoration is the
day a server-side check gets mistaken for safety.
"""

import re

import pytest

from docket.api.models import BANNED_FIELD_NAMES
from docket.execution.authority import (
    AltanaSessionAuthority,
    CallPermission,
    IntegrationGap,
    SessionPermissions,
    SessionRef,
    SessionStatus,
    SpendPermission,
    StubSessionAuthority,
    check,
)
from docket.execution.intent import ActionIntent, Condition, commit

ROUTER_V2 = "0x10ED43C718714eb63d5aA57B78B54704E256024E"
USDT = "0x55d398326f99059fF775485246999027B3197955"
WBNB = "0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c"
OWNER = "0x429898ba0Fc5b9F1fF0a8f0BD1D6D3cB33B26DdD"
SWAP_SELECTOR = "0x38ed1739"
APPROVE_SELECTOR = "0x095ea7b3"
CALLDATA = bytes.fromhex("38ed1739") + b"\x00" * 96
FROZEN_NOW = 2_000_000_000


def _intent(**overrides) -> ActionIntent:
    fields = {
        "intent_id": "grid-1-level-3",
        "condition": Condition("price_at_or_below", f"{USDT}/{WBNB}", 600 * 10**18),
        "chain_id": 56,
        "target": ROUTER_V2,
        "selector": SWAP_SELECTOR,
        "calldata_hash": commit(CALLDATA),
        "token_in": USDT,
        "token_out": WBNB,
        "max_input": 25 * 10**18,
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


def _permissions(**overrides) -> SessionPermissions:
    fields = {
        "calls": (
            CallPermission(to=ROUTER_V2, signature="swapExactTokensForTokens"),
            CallPermission(to=USDT, signature="approve"),
        ),
        "spend": (SpendPermission(token=USDT, limit=100 * 10**18, period=86_400),),
    }
    fields.update(overrides)
    return SessionPermissions(**fields)


def _status(**overrides) -> SessionStatus:
    fields = {
        "valid": True,
        "revoked": False,
        "expiry": FROZEN_NOW + 86_400,
        "remaining_cap": {USDT: 100 * 10**18},
        "permissions": _permissions(),
        "chain_id": 56,
        "read_at_block": 115_155_027,
        "source": "chain",
    }
    fields.update(overrides)
    return SessionStatus(**fields)


@pytest.fixture(autouse=True)
def frozen_clock(monkeypatch):
    monkeypatch.setattr("docket.execution.authority.now", lambda: FROZEN_NOW)
    monkeypatch.setattr("docket.execution.intent.now", lambda: FROZEN_NOW)


# ------------------------------------------------------------- the permissions


def test_a_call_permission_may_be_contract_level_or_method_level():
    contract_only = CallPermission(to=ROUTER_V2)
    assert contract_only.signature is None
    assert contract_only.permits(ROUTER_V2, SWAP_SELECTOR)
    assert contract_only.permits(ROUTER_V2, APPROVE_SELECTOR)

    method_level = CallPermission(to=ROUTER_V2, signature="swapExactTokensForTokens")
    assert method_level.permits(ROUTER_V2, SWAP_SELECTOR)
    assert not method_level.permits(ROUTER_V2, APPROVE_SELECTOR)
    assert not method_level.permits(USDT, SWAP_SELECTOR)


def test_a_method_level_permission_resolves_its_own_selector_from_the_signature():
    """The signature is what a grant is written in; the selector is what a transaction
    carries. Deriving one from the other here means the two can never drift apart."""
    assert CallPermission(to=USDT, signature="approve(address,uint256)").selector == (
        APPROVE_SELECTOR
    )
    assert CallPermission(to=ROUTER_V2, signature="swapExactTokensForTokens").selector == (
        SWAP_SELECTOR
    )


def test_a_signature_with_no_known_argument_list_is_refused():
    """A bare name only works because this build pins the four functions it uses. An
    unknown one would otherwise hash to a selector no contract has."""
    with pytest.raises(ValueError):
        CallPermission(to=ROUTER_V2, signature="doWhateverYouLike")


def test_a_spend_cap_must_be_a_positive_amount_over_a_positive_period():
    SpendPermission(token=USDT, limit=1, period=1)
    for bad in ({"limit": 0}, {"limit": -1}, {"period": 0}):
        with pytest.raises(ValueError):
            SpendPermission(**{"token": USDT, "limit": 10, "period": 60} | bad)


def test_permissions_must_actually_permit_something():
    with pytest.raises(ValueError):
        SessionPermissions(calls=(), spend=(SpendPermission(USDT, 10, 60),))
    with pytest.raises(ValueError):
        SessionPermissions(calls=(CallPermission(to=ROUTER_V2),), spend=())


# ---------------------------------------------------------------- the check


def test_an_intent_inside_every_bound_passes():
    ok, reason = check(_intent(), _status())
    assert ok, reason


def test_a_revoked_session_refuses():
    ok, reason = check(_intent(), _status(revoked=True, valid=False))
    assert not ok
    assert "revoked" in reason.lower()


def test_an_expired_session_refuses():
    ok, reason = check(_intent(), _status(expiry=FROZEN_NOW - 1, valid=False))
    assert not ok
    assert "expired" in reason.lower()


def test_a_session_that_expires_before_the_intents_own_deadline_refuses():
    """A deadline the session does not outlive is an action that can be mined into a
    window where nothing authorises it. The router would still take it."""
    ok, reason = check(_intent(deadline=FROZEN_NOW + 600), _status(expiry=FROZEN_NOW + 300))
    assert not ok
    assert "deadline" in reason.lower()


def test_a_target_outside_the_allowlist_refuses():
    elsewhere = "0x2170Ed0880ac9A755fd29B2688956BD959F933F8"
    ok, reason = check(_intent(target=elsewhere), _status())
    assert not ok
    assert elsewhere.lower() in reason.lower()


def test_a_method_outside_a_method_level_allowlist_refuses():
    """The router is allowlisted; `approve` on the router is not the call that was granted."""
    ok, reason = check(_intent(selector=APPROVE_SELECTOR), _status())
    assert not ok
    assert APPROVE_SELECTOR in reason


def test_an_amount_beyond_the_remaining_cap_refuses():
    ok, reason = check(_intent(max_input=25 * 10**18), _status(remaining_cap={USDT: 24 * 10**18}))
    assert not ok
    assert "cap" in reason.lower()


def test_an_input_token_the_session_has_no_cap_for_refuses():
    """No cap is not an unlimited cap. A token the grant never mentioned is a token
    nothing on chain would stop this session spending down to zero if it were allowed."""
    ok, reason = check(_intent(token_in=WBNB, token_out=USDT, route=(WBNB, USDT)), _status())
    assert not ok
    assert "no spend cap" in reason.lower()


def test_a_session_on_another_chain_refuses():
    ok, reason = check(_intent(), _status(chain_id=97))
    assert not ok
    assert "chain" in reason.lower()


def test_a_status_that_says_it_is_not_valid_refuses_whatever_else_it_says():
    ok, reason = check(_intent(), _status(valid=False))
    assert not ok


def test_the_check_refuses_a_status_that_was_never_read_from_anywhere():
    """A status with no source is a status somebody made up."""
    with pytest.raises(ValueError):
        _status(source="")
    with pytest.raises(ValueError):
        _status(source="a good feeling")


# -------------------------------------------------------------------- the stub


def test_the_stub_says_in_its_own_data_that_it_enforces_nothing():
    """This is the field a judge should look at first. A stub whose status was
    indistinguishable from a live one is how a server-side check gets mistaken for a
    limit somebody's funds actually stand behind."""
    assert StubSessionAuthority.enforces_on_chain is False
    authority = StubSessionAuthority(account=OWNER)
    ref = authority.grant(_permissions(), expiry=FROZEN_NOW + 86_400)
    assert authority.status(ref).source == "stub"
    assert "enforces nothing" in StubSessionAuthority.__doc__.lower()


def test_the_stub_grants_reports_and_revokes():
    authority = StubSessionAuthority(account=OWNER)
    ref = authority.grant(_permissions(), expiry=FROZEN_NOW + 86_400)
    assert isinstance(ref, SessionRef)
    assert ref.chain_id == 56 and ref.account == OWNER

    status = authority.status(ref)
    assert status.valid and not status.revoked
    assert status.remaining_cap[USDT] == 100 * 10**18

    authority.revoke(ref)
    after = authority.status(ref)
    assert after.revoked and not after.valid


def test_revocation_is_monotonic_in_the_stub_as_it_is_on_chain():
    """Altana's revokeSession cannot be undone. A stub that could be un-revoked would be
    modelling a weaker authority than the one it stands in for, and every test written
    against it would be testing the wrong thing."""
    authority = StubSessionAuthority(account=OWNER)
    ref = authority.grant(_permissions(), expiry=FROZEN_NOW + 86_400)
    authority.revoke(ref)
    with pytest.raises(ValueError):
        authority.grant(_permissions(), expiry=FROZEN_NOW + 86_400, session_id=ref.session_id)
    assert authority.status(ref).revoked


def test_the_stub_refuses_an_intent_once_the_session_is_revoked():
    authority = StubSessionAuthority(account=OWNER)
    ref = authority.grant(_permissions(), expiry=FROZEN_NOW + 86_400)
    assert authority.can_execute(_intent(), ref)[0]
    authority.revoke(ref)
    ok, reason = authority.can_execute(_intent(), ref)
    assert not ok and "revoked" in reason.lower()


def test_the_stub_refuses_an_intent_once_the_session_has_expired(monkeypatch):
    authority = StubSessionAuthority(account=OWNER)
    ref = authority.grant(_permissions(), expiry=FROZEN_NOW + 60)
    monkeypatch.setattr("docket.execution.authority.now", lambda: FROZEN_NOW + 61)
    ok, reason = authority.can_execute(_intent(), ref)
    assert not ok and "expired" in reason.lower()


def test_the_stub_spends_its_cap_down_so_a_sequence_of_actions_can_be_exercised():
    authority = StubSessionAuthority(account=OWNER)
    ref = authority.grant(
        _permissions(spend=(SpendPermission(token=USDT, limit=30 * 10**18, period=86_400),)),
        expiry=FROZEN_NOW + 86_400,
    )
    assert authority.can_execute(_intent(max_input=25 * 10**18), ref)[0]
    authority.record_spend(ref, USDT, 25 * 10**18)
    ok, reason = authority.can_execute(_intent(max_input=25 * 10**18), ref)
    assert not ok and "cap" in reason.lower()


def test_an_unknown_session_is_refused_rather_than_treated_as_absent_limits():
    authority = StubSessionAuthority(account=OWNER)
    stranger = SessionRef(
        session_id="never-granted", account=OWNER, key_address=OWNER, chain_id=56, expiry=0
    )
    ok, reason = authority.can_execute(_intent(), stranger)
    assert not ok and "no session" in reason.lower()


# ------------------------------------------------------------------- the altana side


def test_the_altana_authority_cannot_be_built_without_a_chain_surface_to_read():
    """The gap, made structural. If Docket cannot read a session's revoked flag, expiry
    and remaining cap from the chain, then `can_execute` would be answering from local
    memory — which is the exact thing this package promised it would never present as a
    limit. So there is no constructor that produces one."""
    with pytest.raises(IntegrationGap) as exc:
        AltanaSessionAuthority(account=OWNER)
    message = str(exc.value)
    assert "session" in message.lower()
    for expected in ("address", "abi", "chain"):
        assert expected in message.lower(), expected


def test_the_gap_names_what_would_close_it():
    """An error that says only "not implemented" leaves the next person to rediscover
    the whole question."""
    gap = AltanaSessionAuthority.integration_gap()
    lowered = gap.lower()
    assert "typescript" in lowered or "sidecar" in lowered
    assert "eth_call" in lowered
    assert "56" in gap


def test_the_altana_authority_can_be_built_once_the_surface_is_supplied():
    """Given a session-manager address and the view ABI to read it with, the same class
    is a live authority: `status` becomes an eth_call and nothing else changes."""
    asked = []

    def reader(session_id, token):
        asked.append((session_id, token))
        return (False, FROZEN_NOW + 86_400, 100 * 10**18, 115_155_027)

    authority = AltanaSessionAuthority(
        account=OWNER,
        session_manager="0x1111111111111111111111111111111111111111",
        reader=reader,
    )
    assert authority.enforces_on_chain is True
    ref = SessionRef(
        session_id="0xabc",
        account=OWNER,
        key_address=OWNER,
        chain_id=56,
        expiry=FROZEN_NOW + 86_400,
    )
    status = authority.status(ref, permissions=_permissions())
    assert status.source == "chain"
    assert asked == [("0xabc", USDT)]
    assert status.remaining_cap[USDT] == 100 * 10**18
    assert status.read_at_block == 115_155_027
    assert authority.can_execute(_intent(), ref, permissions=_permissions())[0]


def test_a_live_authority_that_cannot_reach_the_chain_refuses_rather_than_guesses():
    """An outage is not an authorisation. The one thing `can_execute` must never do is
    fall back to what it remembers."""

    def broken(session_id, token):
        raise RuntimeError("every BSC endpoint failed")

    authority = AltanaSessionAuthority(
        account=OWNER,
        session_manager="0x1111111111111111111111111111111111111111",
        reader=broken,
    )
    ref = SessionRef(
        session_id="0xabc",
        account=OWNER,
        key_address=OWNER,
        chain_id=56,
        expiry=FROZEN_NOW + 86_400,
    )
    ok, reason = authority.can_execute(_intent(), ref, permissions=_permissions())
    assert not ok
    assert "could not be read" in reason.lower()


def test_granting_and_revoking_through_the_altana_authority_are_owner_actions():
    """Docket holds a session, never the owner key. Both of these are signed by the
    owner, so this class refuses them rather than pretending it could."""
    authority = AltanaSessionAuthority(
        account=OWNER,
        session_manager="0x1111111111111111111111111111111111111111",
        reader=lambda session_id, token: (False, FROZEN_NOW + 86_400, 10**18, 115_155_027),
    )
    ref = SessionRef(
        session_id="0xabc", account=OWNER, key_address=OWNER, chain_id=56, expiry=FROZEN_NOW + 1
    )
    with pytest.raises(IntegrationGap):
        authority.grant(_permissions(), expiry=FROZEN_NOW + 86_400)
    with pytest.raises(IntegrationGap):
        authority.revoke(ref)


# ------------------------------------------------------------------ no verdicts


def test_nothing_in_this_module_carries_verdict_language():
    values = [
        *SessionStatus.__dataclass_fields__,
        *SessionRef.__dataclass_fields__,
        *SessionPermissions.__dataclass_fields__,
        *CallPermission.__dataclass_fields__,
        *SpendPermission.__dataclass_fields__,
        check(_intent(), _status())[1],
        check(_intent(), _status(revoked=True, valid=False))[1],
        AltanaSessionAuthority.integration_gap(),
        StubSessionAuthority.__doc__,
    ]
    for value in values:
        for word in BANNED_FIELD_NAMES:
            assert not re.search(rf"\b{re.escape(word)}\b", value.lower()), (
                f"authority carries verdict language {word!r} in {value[:80]!r}"
            )
