from web3 import Web3

from docket.escrow import constants as c


def test_every_address_is_checksummed():
    """A non-checksummed address is accepted by some tooling and rejected by web3's
    contract factory, so the failure would surface far from the typo."""
    for name in ("COMMERCE", "ROUTER", "POLICY", "PAYMENT_TOKEN"):
        addr = getattr(c, name)
        assert addr == Web3.to_checksum_address(addr), f"{name} is not checksummed"


def test_the_windows_are_the_ones_read_from_chain():
    assert c.CHAIN_ID == 56
    assert c.DISPUTE_WINDOW_S == 604800  # 7.0 days, read from the live policy
    assert c.MAX_EXPIRY_DURATION_S == 31536000  # 365 days, from commerce
    assert c.PAYMENT_TOKEN_DECIMALS == 18


def test_the_constants_say_when_they_were_checked():
    """A constant copied out of a spec with no date is one nobody can re-verify."""
    assert c.VERIFIED_ON == "2026-08-10"
    assert c.EVIDENCE.endswith("e1c-result.json")


def test_no_testnet_constants_are_offered():
    """Testnet's only policy is de-whitelisted and the router owner is not ours, so
    there is no testnet rail. Shipping the addresses anyway invites someone to try."""
    names = [n for n in dir(c) if not n.startswith("_")]
    assert not [n for n in names if "TESTNET" in n.upper()]
    assert 97 not in [getattr(c, n) for n in names if isinstance(getattr(c, n), int)]
