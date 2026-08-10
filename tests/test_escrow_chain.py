"""Reading a job without a chain, and telling an outage apart from an answer.

The injected-Web3 seam is the one `positions.py` already established: a supplied `w3` is
used as given, with no failover, so nothing here touches a network.

The classification test is the one that earns its place. E1c published
"settle is not permissionless" because a pruned node's `missing trie node` was recorded
as a contract verdict. A revert is the contract answering; anything else is the road to
it failing, and a reader that blurs the two reports fiction with a straight face.
"""

import pytest
from web3.exceptions import ContractLogicError

from docket.escrow import constants as c
from docket.escrow.chain import JobReader, Rpc

NOW = 1786400000
SUBMITTED_AT = NOW - c.DISPUTE_WINDOW_S - 60  # ripe: submitted just over a window ago
CLIENT = "0x000000000000000000000000000000000000C11e"
PROVIDER = "0x000000000000000000000000000000000000B0b0"


def _job(status, submitted_at=0, expired_at=NOW + 86400, budget=10**16):
    """struct IACP.Job in declaration order: jobId, client, provider, evaluator,
    description, budget, expiredAt, status, hook, submittedAt, deliverable."""
    return [
        1,
        CLIENT,
        PROVIDER,
        c.ROUTER,
        "a job",
        budget,
        expired_at,
        status,
        c.ROUTER,
        submitted_at,
        b"\x00" * 32,
    ]


class _Call:
    def __init__(self, result):
        self._result = result

    def call(self, *a, **kw):
        if isinstance(self._result, Exception):
            raise self._result
        return self._result


class _Functions:
    def __init__(self, results):
        self._results = results

    def __getattr__(self, name):
        def fn(*args):
            return _Call(self._results[name])

        return fn


class _Eth:
    def __init__(self, results, block=115000000):
        self._results = results
        self.block_number = block

    def contract(self, address=None, abi=None):
        kind = (
            "commerce"
            if address == c.COMMERCE
            else "router"
            if address == c.ROUTER
            else "policy"
        )
        return type("C", (), {"functions": _Functions(self._results[kind])})()

    def get_block(self, _which):
        return {"timestamp": NOW}


class _W3:
    def __init__(self, results, block=115000000):
        self.eth = _Eth(results, block)


def _w3(status=2, submitted_at=SUBMITTED_AT, disputed=False, policy=None):
    return _W3(
        {
            "commerce": {"getJob": _job(status, submitted_at)},
            "router": {"jobPolicy": c.POLICY if policy is None else policy},
            "policy": {"disputed": disputed},
        }
    )


def test_status_is_reported_by_name_not_as_a_bare_enum():
    state = JobReader(w3=_w3(status=1, submitted_at=0)).job_state(1)
    assert state["status"] == "FUNDED"


def test_settle_at_is_the_window_after_submission():
    state = JobReader(w3=_w3()).job_state(1)
    assert state["settle_at"] == SUBMITTED_AT + c.DISPUTE_WINDOW_S
    assert state["settle_ready"] is True


def test_an_unsubmitted_job_has_no_settle_time_rather_than_a_zero_one():
    """settle_at = 0 would render as 1970 and read as 'ready now', which is the exact
    opposite of the truth for a job nobody has delivered yet."""
    state = JobReader(w3=_w3(status=1, submitted_at=0)).job_state(1)
    assert state["submitted_at"] is None
    assert state["settle_at"] is None
    assert state["settle_ready"] is False


def test_a_disputed_job_is_not_settle_ready_even_past_its_window():
    state = JobReader(w3=_w3(disputed=True)).job_state(1)
    assert state["disputed"] is True
    assert state["settle_ready"] is False


def test_a_job_still_inside_its_window_is_not_ready():
    state = JobReader(w3=_w3(submitted_at=NOW - 60)).job_state(1)
    assert state["settle_ready"] is False
    assert state["settle_at"] == NOW - 60 + c.DISPUTE_WINDOW_S


def test_an_unbound_job_reports_no_policy_without_asking_it_about_disputes():
    zero = "0x" + "0" * 40
    state = JobReader(w3=_w3(status=0, submitted_at=0, policy=zero)).job_state(1)
    assert state["policy"] is None
    assert state["disputed"] is False


def test_an_outage_raises_rather_than_returning_a_job_that_looks_unfunded():
    """Swallowing the error and returning zeros would render a funded job as OPEN with a
    zero budget — a wrong answer is worse here than no answer."""
    broken = _W3(
        {
            "commerce": {"getJob": ConnectionError("node down")},
            "router": {"jobPolicy": c.POLICY},
            "policy": {"disputed": False},
        }
    )
    with pytest.raises(ConnectionError):
        JobReader(w3=broken).job_state(1)


def test_failover_retries_an_outage_but_never_a_revert():
    """A revert is deterministic: asking three more nodes gets the same answer, and
    wrapping it as 'every endpoint failed' turns a verdict into a fake outage."""
    attempts = []

    def outage(_w3):
        attempts.append("outage")
        raise ConnectionError("down")

    rpc = Rpc(["a", "b"], session_factory=lambda url: url)
    with pytest.raises(RuntimeError, match="every endpoint failed"):
        rpc(outage)
    assert len(attempts) == 4  # two endpoints, two attempts each

    reverts = []

    def revert(_w3):
        reverts.append("revert")
        raise ContractLogicError("execution reverted: NotDecided()")

    with pytest.raises(ContractLogicError):
        rpc(revert)
    assert len(reverts) == 1
