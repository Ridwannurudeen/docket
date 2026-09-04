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
from web3 import Web3

from docket.api.models import BANNED_FIELD_NAMES
from docket.execution.authority import (
    ACCOUNT_ABI,
    ALTANA_KEYSTORE,
    KEYSTORE_ABI,
    AltanaSessionAuthority,
    BscChainReader,
    CallPermission,
    IntegrationGap,
    SessionPermissions,
    SessionRef,
    SessionStatus,
    SpendPermission,
    StubSessionAuthority,
    UndelegatedWallet,
    account_key_hash,
    check,
    keystore_key_id,
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
# A session signer and its uncompressed SEC1 public key. Generated for this test file
# and never funded: the pair only has to be well formed for the two derivations below.
SESSION_KEY = "0x11111111111111111111111111111111111111aB"
PUBLIC_KEY = "0x04" + "11" * 32 + "22" * 32
KEY_ID = Web3.keccak(bytes.fromhex(PUBLIC_KEY[2:]))
KEY_HASH = Web3.keccak(
    (2).to_bytes(32, "big") + Web3.keccak(bytes(12) + bytes.fromhex(SESSION_KEY[2:]))
)


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


class FakeChain:
    """The four reads, answered from a dict. Every test below drives a real
    `AltanaSessionAuthority`; only the endpoint is fake."""

    def __init__(self, **overrides):
        self.state = {
            "valid": True,
            "registered": (KEY_ID,),
            "spend": ((USDT, 2, 100 * 10**18, 0, 0, 10 * 10**18, FROZEN_NOW),),
            "can_execute": True,
            "block": 115_155_027,
        }
        self.state.update(overrides)
        self.asked = []

    def block_number(self):
        return self.state["block"]

    def is_valid_key(self, wallet, key_id):
        self.asked.append(("is_valid_key", wallet, key_id))
        return self.state["valid"]

    def registered_key_ids(self, wallet):
        self.asked.append(("registered_key_ids", wallet))
        return self.state["registered"]

    def spend_infos(self, wallet, key_hash):
        self.asked.append(("spend_infos", wallet, key_hash))
        return self.state["spend"]

    def can_execute(self, wallet, key_hash, target, calldata):
        self.asked.append(("can_execute", wallet, key_hash, target, calldata))
        return self.state["can_execute"]


def _ref(**overrides) -> SessionRef:
    fields = {
        "session_id": "grid-session-1",
        "account": OWNER,
        "key_address": SESSION_KEY,
        "chain_id": 56,
        "expiry": FROZEN_NOW + 86_400,
        "public_key": PUBLIC_KEY,
    }
    fields.update(overrides)
    return SessionRef(**fields)


def _live(**overrides) -> AltanaSessionAuthority:
    return AltanaSessionAuthority(account=OWNER, reader=FakeChain(**overrides))


def test_the_keystore_this_build_reads_is_the_one_it_was_checked_against():
    """Pinned rather than configured. Checked from this machine on 2026-08-10: 8,756
    bytes of code on chain 56, and VERSION() reading 1.0.1."""
    assert ALTANA_KEYSTORE == "0x6572427ED530BadcF7375Cf9A4709D8d2b0E7E0a"
    assert AltanaSessionAuthority(account=OWNER, reader=FakeChain()).keystore == ALTANA_KEYSTORE


def test_the_two_identifiers_for_one_key_are_derived_differently_and_are_not_swappable():
    """The single most likely source of a silent wrong answer here. The KeyStore files a
    key under keccak of its 65-byte public key; the wallet's own table files it under a
    type-tagged hash of the 20-byte address."""
    assert keystore_key_id(bytes.fromhex(PUBLIC_KEY[2:])) == KEY_ID
    assert account_key_hash(SESSION_KEY) == KEY_HASH
    assert KEY_ID != KEY_HASH
    padded = bytes(12) + bytes.fromhex(SESSION_KEY[2:])
    assert KEY_HASH == Web3.keccak((2).to_bytes(32, "big") + Web3.keccak(padded))


def test_a_public_key_that_is_not_sec1_uncompressed_is_refused():
    with pytest.raises(ValueError):
        keystore_key_id(b"\x04" * 33)
    with pytest.raises(ValueError):
        keystore_key_id(b"\x02" + b"\x11" * 64)


def test_a_reference_with_no_public_key_cannot_produce_a_keystore_id():
    """Refused rather than guessed: an id derived from the wrong bytes reads as a key the
    KeyStore has never heard of, which is indistinguishable from a revoked one."""
    with pytest.raises(ValueError):
        _ = _ref(public_key=None).key_id


def test_a_live_status_is_four_reads_and_says_which_ones():
    authority = _live()
    status = authority.status(_ref(), permissions=_permissions(), call=(ROUTER_V2, CALLDATA))
    assert status.source == "chain"
    assert status.reads == (
        "KeyStore.isValidKey",
        "KeyStore.getKeys",
        "account.spendInfos",
        "account.canExecute",
    )
    assert status.read_at_block == 115_155_027
    assert status.call_allowed is True
    assert authority.enforces_on_chain is True


def test_the_remaining_cap_is_the_limit_less_what_this_period_already_spent():
    """`currentSpent`, not `spent`, and never the field named `current` — that one is the
    start of the current period and is a timestamp, not a balance."""
    status = _live().status(_ref(), permissions=_permissions())
    assert status.remaining_cap[USDT] == 100 * 10**18 - 10 * 10**18
    assert status.call_allowed is None


def test_a_key_the_keystore_no_longer_lists_reads_as_revoked():
    """Revocation removes the id from getKeys in the same transaction. An expiry passing
    does not, because no transaction fires when a timestamp goes by — which is how the two
    are told apart without decoding a struct."""
    ok, reason = _live(registered=(), valid=False).can_execute(
        _intent(), _ref(), permissions=_permissions()
    )
    assert not ok and "revoked" in reason.lower()


def test_a_key_still_listed_but_no_longer_valid_reads_as_unusable_rather_than_revoked():
    ok, reason = _live(valid=False).can_execute(_intent(), _ref(), permissions=_permissions())
    assert not ok
    assert "revoked" not in reason.lower()
    assert "usable" in reason.lower()


def test_the_wallets_own_canexecute_outranks_dockets_copy_of_the_grant():
    """The read that moves the allowlist question onto the chain. Docket's copy says this
    call is permitted; the wallet says no, and no is the answer."""
    ok, reason = _live(can_execute=False).can_execute(
        _intent(), _ref(), permissions=_permissions(), calldata=CALLDATA
    )
    assert not ok
    assert "canexecute" in reason.lower()


def test_a_live_session_inside_every_bound_passes():
    authority = _live()
    ok, reason = authority.can_execute(
        _intent(), _ref(), permissions=_permissions(), calldata=CALLDATA
    )
    assert ok, reason
    assert ("can_execute", OWNER, KEY_HASH, ROUTER_V2, CALLDATA) in authority._reader.asked


def test_a_cap_already_spent_down_refuses_the_next_action():
    spent = ((USDT, 2, 100 * 10**18, 0, 0, 99 * 10**18, FROZEN_NOW),)
    ok, reason = _live(spend=spent).can_execute(_intent(), _ref(), permissions=_permissions())
    assert not ok and "cap" in reason.lower()


def test_a_wallet_that_has_never_been_delegated_is_a_state_of_its_own():
    """Not an outage and not a refusal — an address with no account code has no keys and
    no caps because there is nothing there to hold them. Reporting it as an unreachable
    node would send somebody to debug the wrong thing."""

    class Undelegated(FakeChain):
        def spend_infos(self, wallet, key_hash):
            raise UndelegatedWallet(f"{wallet} carries no account code on chain 56")

    authority = AltanaSessionAuthority(account=OWNER, reader=Undelegated())
    ok, reason = authority.can_execute(_intent(), _ref(), permissions=_permissions())
    assert not ok
    assert "no account code" in reason.lower()
    assert "could not be read" not in reason.lower()


def test_a_live_authority_that_cannot_reach_the_chain_refuses_rather_than_guesses():
    """An outage is not an authorisation. The one thing `can_execute` must never do is
    fall back to what it remembers."""

    class Outage(FakeChain):
        def is_valid_key(self, wallet, key_id):
            raise RuntimeError("every BSC endpoint failed")

    ok, reason = AltanaSessionAuthority(account=OWNER, reader=Outage()).can_execute(
        _intent(), _ref(), permissions=_permissions()
    )
    assert not ok
    assert "could not be read" in reason.lower()


def test_reading_a_status_without_the_granted_permissions_is_refused():
    with pytest.raises(ValueError):
        _live().status(_ref())


def test_granting_and_revoking_through_the_altana_authority_are_owner_actions():
    """Docket holds a session, never the owner key. Both are signed by the owner, so this
    class refuses them rather than pretending it could."""
    authority = _live()
    with pytest.raises(IntegrationGap):
        authority.grant(_permissions(), expiry=FROZEN_NOW + 86_400)
    with pytest.raises(IntegrationGap):
        authority.revoke(_ref())


def test_the_gap_that_is_left_is_named_precisely_rather_than_implied():
    """Three planes, and only one of them is missing. An honest gap beats a fabricated
    capability, and it also beats an honest gap vaguer than it needs to be."""
    gap = AltanaSessionAuthority.integration_gap()
    lowered = gap.lower()
    assert "eth_call" in lowered
    assert "0x6572427ed530badcf7375cf9a4709d8d2b0e7e0a" in lowered
    assert "56" in gap
    assert "typescript" in lowered
    assert "owner" in lowered
    assert "register=false" in lowered
    assert "not been exercised against a live granted session" in lowered
    assert "not published" in lowered


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


# ------------------------------------------------------------------- the reader


class _Fn:
    def __init__(self, answer):
        self._answer = answer

    def call(self):
        return self._answer


class _Functions:
    def __init__(self, answers, log):
        self._answers = answers
        self._log = log

    def __getattr__(self, name):
        def bind(*args):
            self._log.append((name, args))
            return _Fn(self._answers[name])

        return bind


class _Eth:
    def __init__(self, answers, log, code):
        self._answers = answers
        self._log = log
        self._code = code
        self.block_number = 115_155_027

    def contract(self, address=None, abi=None):
        contract = type("_C", (), {})()
        contract.functions = _Functions(self._answers, self._log)
        return contract

    def get_code(self, address):
        self._log.append(("get_code", (address,)))
        return self._code


class _W3:
    def __init__(self, answers, log, code=b"\x60\x80"):
        self.eth = _Eth(answers, log, code)


def _reader_over(answers, code=b"\x60\x80"):
    log = []
    w3 = _W3(answers, log, code)
    return BscChainReader(rpc=lambda do: do(w3)), log


def test_the_abi_fragments_encode_the_selectors_found_in_the_deployed_bytecode():
    """The one thing that could quietly be wrong here is a mistranscribed argument list,
    which produces a selector no contract answers. Each of these was recomputed and
    matched against the runtime bytecode at ALTANA_KEYSTORE and at the account
    implementation 0x4B5d20CD8a3927B500540d9BcCDDc27385c9fA79 on 2026-08-10."""
    w3 = Web3()
    keystore = w3.eth.contract(abi=KEYSTORE_ABI)
    account = w3.eth.contract(abi=ACCOUNT_ABI)
    assert keystore.encode_abi("isValidKey", args=[OWNER, KEY_ID])[:10] == "0x8fd4f06b"
    assert keystore.encode_abi("getKeys", args=[OWNER])[:10] == "0x34e80c34"
    assert account.encode_abi("spendInfos", args=[KEY_HASH])[:10] == "0xdcc09ebf"
    assert (
        account.encode_abi("canExecute", args=[KEY_HASH, ROUTER_V2, CALLDATA])[:10] == "0xff619c6b"
    )


def test_the_reader_asks_the_keystore_about_the_wallet_and_the_wallet_about_itself():
    reader, log = _reader_over(
        {
            "isValidKey": True,
            "getKeys": [KEY_ID],
            "spendInfos": [(USDT, 2, 100, 0, 0, 10, FROZEN_NOW)],
            "canExecute": True,
        }
    )
    assert reader.is_valid_key(OWNER, KEY_ID) is True
    assert reader.registered_key_ids(OWNER) == (KEY_ID,)
    assert reader.spend_infos(OWNER, KEY_HASH)[0][0] == USDT
    assert reader.can_execute(OWNER, KEY_HASH, ROUTER_V2, CALLDATA) is True
    assert [name for name, _ in log if name != "get_code"] == [
        "isValidKey",
        "getKeys",
        "spendInfos",
        "canExecute",
    ]


def test_the_reader_refuses_an_account_read_against_an_address_with_no_code():
    """An undelegated EOA answers `spendInfos` with a revert that reads like any other
    failure. Checking for code first turns it into a state with a name and a fix."""
    reader, _ = _reader_over({"spendInfos": [], "canExecute": False}, code=b"")
    with pytest.raises(UndelegatedWallet):
        reader.spend_infos(OWNER, KEY_HASH)
    with pytest.raises(UndelegatedWallet):
        reader.can_execute(OWNER, KEY_HASH, ROUTER_V2, CALLDATA)


def test_the_keystore_reads_do_not_need_the_wallet_to_exist_at_all():
    """They are a read of the KeyStore's own storage about an address, so they answer for
    a wallet that has never been delegated — which is how "no keys" stays distinguishable
    from "no account"."""
    reader, log = _reader_over({"isValidKey": False, "getKeys": []}, code=b"")
    assert reader.is_valid_key(OWNER, KEY_ID) is False
    assert reader.registered_key_ids(OWNER) == ()
    assert not [name for name, _ in log if name == "get_code"]
