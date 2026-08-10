"""Settling a ripe job, and refusing to when nobody armed it.

The safety property here is not "settle behaves well" but "settle cannot fire by
accident". A signing path that is merely unlikely to run is one that runs eventually, so
the unarmed case is asserted to make no network call at all rather than to fail politely
after connecting.
"""

import pytest
from web3.exceptions import ContractLogicError

from docket.escrow import constants as c
from docket.escrow.settle import NotArmed, can_settle, settle, settle_calldata


class _Exploding:
    """Any attribute access is a test failure: proves the unarmed path never reaches a
    node, rather than merely failing once it gets there."""

    def __getattr__(self, name):
        raise AssertionError(f"unarmed settle touched the network ({name})")


def test_settle_calldata_targets_the_router_and_encodes_empty_evidence():
    call = settle_calldata(4242)
    assert call["to"] == c.ROUTER
    assert call["function"] == "settle"
    assert call["args"] == {"jobId": 4242, "evidence": b""}
    assert call["calldata"].startswith("0x")


def test_settle_refuses_without_a_key_and_never_opens_a_connection(monkeypatch):
    monkeypatch.delenv("DOCKET_SETTLE_KEY", raising=False)
    with pytest.raises(NotArmed):
        settle(4242, w3=_Exploding())


def test_the_suite_never_arms_settling(monkeypatch):
    """A stray DOCKET_SETTLE_KEY in a developer's shell must not turn the test run into
    a broadcaster."""
    import os

    assert "DOCKET_SETTLE_KEY" not in os.environ


def test_can_settle_reports_ready_when_the_dry_run_succeeds():
    class _W3:
        class eth:
            @staticmethod
            def contract(address=None, abi=None):
                return type(
                    "C",
                    (),
                    {
                        "functions": type(
                            "F",
                            (),
                            {
                                "settle": staticmethod(
                                    lambda *a: type(
                                        "X",
                                        (),
                                        {"call": staticmethod(lambda *a, **k: None)},
                                    )()
                                )
                            },
                        )()
                    },
                )()

    out = can_settle(4242, w3=_W3())
    assert out["ready"] is True
    assert out["reason"] is None


def test_can_settle_turns_a_revert_into_a_sentence_not_a_selector():
    """'NotDecided' is a contract's word. A buyer reading the job page needs to know the
    window has not elapsed."""

    class _W3:
        class eth:
            @staticmethod
            def contract(address=None, abi=None):
                def boom(*a, **k):
                    raise ContractLogicError("execution reverted: NotDecided()")

                return type(
                    "C",
                    (),
                    {
                        "functions": type(
                            "F",
                            (),
                            {
                                "settle": staticmethod(
                                    lambda *a: type(
                                        "X", (), {"call": staticmethod(boom)}
                                    )()
                                )
                            },
                        )()
                    },
                )()

    out = can_settle(4242, w3=_W3())
    assert out["ready"] is False
    assert "dispute window" in out["reason"].lower()
    assert "0x" not in out["reason"]
