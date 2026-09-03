"""Owner proof: real signatures, and the two ways a request can fail to carry one."""

import pytest
from eth_account import Account
from eth_account.messages import encode_defunct

from docket.jobs.auth import (
    ACTIONS,
    action_message,
    create_message,
    new_nonce,
    recover_signer,
    same_address,
    verify_owner_signature,
)

OWNER = Account.from_key("0x" + "11" * 32)
STRANGER = Account.from_key("0x" + "22" * 32)


def _sign(account, message: str) -> str:
    return account.sign_message(encode_defunct(text=message)).signature.hex()


def test_the_two_message_shapes_are_exactly_what_the_contract_fixed():
    assert (
        create_message("range-doctor", "abc")
        == "Docket activation create range-doctor abc"
    )
    assert (
        action_message("act_1", "revoke", "abc") == "Docket activation act_1 revoke abc"
    )


def test_an_action_message_refuses_a_verb_no_route_serves():
    """The message is the contract. A verb nobody serves would produce a signature over a
    sentence no route will ever check, which reads to a client as a rejected wallet."""
    assert set(ACTIONS) == {"create", "approve", "pause", "cancel", "revoke"}
    with pytest.raises(ValueError, match="unknown activation action"):
        action_message("act_1", "delete", "abc")


def test_a_real_signature_from_the_owner_verifies():
    message = create_message("range-doctor", new_nonce())

    assert verify_owner_signature(OWNER.address, message, _sign(OWNER, message))


def test_the_recovered_address_is_returned_so_a_route_can_tell_the_two_failures_apart():
    message = action_message("act_1", "pause", "n")
    signature = _sign(STRANGER, message)

    assert recover_signer(message, signature) == STRANGER.address
    assert recover_signer(message, "0xnot-a-signature") is None
    assert not verify_owner_signature(OWNER.address, message, signature)


def test_verification_accepts_a_signature_with_or_without_the_0x_prefix():
    message = action_message("act_1", "approve", "n")
    signature = _sign(OWNER, message)

    assert verify_owner_signature(OWNER.address, message, signature)
    assert verify_owner_signature(
        OWNER.address, message, "0x" + signature.removeprefix("0x")
    )


def test_a_signature_over_a_different_message_does_not_verify():
    """Which is the whole of replay protection at this layer: the nonce is inside the
    string, so a signature for one nonce cannot be presented for another."""
    signed = action_message("act_1", "approve", "nonce-one")
    presented = action_message("act_1", "approve", "nonce-two")

    assert not verify_owner_signature(OWNER.address, presented, _sign(OWNER, signed))


def test_the_owner_may_be_written_in_any_case():
    message = create_message("range-doctor", "n")
    signature = _sign(OWNER, message)

    assert verify_owner_signature(OWNER.address.lower(), message, signature)
    assert verify_owner_signature(
        OWNER.address.upper().replace("0X", "0x"), message, signature
    )


def test_nothing_a_caller_can_send_raises_out_of_verification():
    message = create_message("range-doctor", "n")

    for owner, signature in (
        ("not-an-address", _sign(OWNER, message)),
        (OWNER.address, ""),
        (OWNER.address, "0x00"),
        (OWNER.address, "0x" + "00" * 65),
        ("", ""),
    ):
        assert verify_owner_signature(owner, message, signature) is False


def test_same_address_refuses_anything_that_is_not_one():
    assert same_address(OWNER.address, OWNER.address.lower())
    assert not same_address(OWNER.address, STRANGER.address)
    assert not same_address(OWNER.address, "0xnope")


def test_a_nonce_is_thirty_two_hex_characters_and_never_repeats():
    nonces = {new_nonce() for _ in range(200)}

    assert len(nonces) == 200
    for nonce in nonces:
        assert len(nonce) == 32
        assert all(character in "0123456789abcdef" for character in nonce)
