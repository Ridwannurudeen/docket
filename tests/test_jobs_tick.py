"""The tick loop: what it advances, what it refuses to crash on, and what it reports.

`EXECUTORS` is a module-level registry, so every test that touches it restores it. A
leaked registration would make the next test pass for the wrong reason.
"""

from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest
from web3 import Web3

from docket.hire.catalogue import get_service
from docket.jobs import tick
from docket.jobs.executors import EXECUTORS, NoopExecutor, register
from docket.jobs.executors.base import Decision, PreparedCall
from docket.jobs.service import ActivationService
from docket.store import Store
from tests.test_jobs_service import (
    NFPM,
    OWNER,
    PASSWORD,
    POLICY,
    ROUTER,
    USDT,
    FakeRpc,
    _transfer_receipt,
)


@pytest.fixture
def sessions_key(tmp_path):
    """The master password where the tick's own environment expects to find it.

    Passed as an environment rather than injected, so the file-reading path
    `docket-jobs.service` actually runs in production is the one under test."""
    key_file = tmp_path / "sessions.key"
    key_file.write_text(PASSWORD + "\n", encoding="utf-8")
    return {"DOCKET_SESSION_KEY_FILE": str(key_file)}


@pytest.fixture(autouse=True)
def clean_registry():
    saved = dict(EXECUTORS)
    EXECUTORS.clear()
    yield
    EXECUTORS.clear()
    EXECUTORS.update(saved)


class ActionExecutor:
    """One prepared swap, and a `within_policy` the test can flip."""

    category = "rebalancing"

    def __init__(self, *, permitted=True, kind="action", token_amount=10 * 10**18):
        self.permitted = permitted
        self.kind = kind
        self.token_amount = token_amount
        self.seen = []

    def evaluate(self, activation, *, reader=None):
        self.seen.append(activation.activation_id)
        prepared = (
            PreparedCall(
                to=ROUTER,
                data="0x38ed1739" + "00" * 32,
                value_atomic="0",
                gas_ceiling=300_000,
                deadline=4_102_444_800,
                purpose="recenter the position",
                simulation={"ok": True, "gas_estimate": 180_000, "block": 900},
            ),
        )
        return Decision(
            kind=self.kind,
            summary="the position is out of range",
            prepared=prepared if self.kind == "action" else (),
            evidence={"token_amounts": {USDT: self.token_amount}},
            observed_at="2026-09-03T00:00:00+00:00",
            block=900,
        )

    def within_policy(self, activation, decision):
        return self.permitted, (
            "inside the policy" if self.permitted else "above the per-action limit"
        )


class ExplodingExecutor:
    category = "rebalancing"

    def evaluate(self, activation, *, reader=None):
        raise RuntimeError("the reader would not answer")

    def within_policy(self, activation, decision):
        return False, "never reached"


def _service(store, rpc):
    return ActivationService(
        store,
        services={"range-doctor": get_service("range-doctor")},
        rpc=rpc,
        master_password=PASSWORD,
    )


def _active(store, rpc, *, policy=None):
    """One funded, active persistent activation, walked there through the real path."""
    service = _service(store, rpc)
    created = service.create(
        "range-doctor",
        kind="persistent",
        owner=OWNER,
        inputs={"wallet": OWNER},
        policy=POLICY if policy is None else policy,
    )
    tx_hash = "0x" + f"{len(rpc.w3.eth.receipts) + 1:064x}"
    rpc.w3.eth.receipts[tx_hash] = _transfer_receipt(created.session["address"])
    service.approve(created.activation_id, tx_hash=tx_hash)
    return service, store.get_activation(created.activation_id)


class SendingRpc(FakeRpc):
    """The funding-receipt fake, plus the calls `sessions.executor` makes to send."""

    def __init__(self):
        super().__init__()
        self.sent = []
        eth = self.w3.eth
        eth.call = lambda transaction: b""
        eth.estimate_gas = lambda transaction: 180_000
        eth.get_transaction_count = lambda address: 3
        eth.send_raw_transaction = self._send

    def _send(self, raw):
        tx_hash = "0x" + f"{0xE0 + len(self.sent):064x}"
        self.sent.append(tx_hash)
        self.w3.eth.receipts[tx_hash] = {
            "status": 1,
            "gasUsed": 190_000,
            "blockNumber": 901,
            "logs": [],
        }
        return tx_hash


def test_a_category_with_no_executor_is_an_alert_rather_than_a_crash(tmp_path):
    """Lane D's executors land after this loop does. A tick that died on the gap would
    take every other owner's activation down with it for the days in between."""
    store = Store(tmp_path / "tick.sqlite3")
    _, activation = _active(store, FakeRpc())

    assert tick.run_once(store, rpc=FakeRpc()) == 0

    stored = store.get_activation(activation.activation_id)
    assert stored.state == "active"
    assert (
        "alert: no executor is registered for rebalancing" in stored.events[-1].reason
    )


def test_a_noop_decision_changes_nothing_at_all(tmp_path):
    store = Store(tmp_path / "tick.sqlite3")
    _, activation = _active(store, FakeRpc())
    register("rebalancing", NoopExecutor("rebalancing"))

    assert tick.run_once(store, rpc=FakeRpc()) == 0

    stored = store.get_activation(activation.activation_id)
    assert stored.updated_at == activation.updated_at
    assert stored.events == activation.events


def test_an_alert_decision_is_recorded_without_moving_the_activation(tmp_path):
    store = Store(tmp_path / "tick.sqlite3")
    _, activation = _active(store, FakeRpc())
    register("rebalancing", ActionExecutor(kind="alert"))

    assert tick.run_once(store, rpc=FakeRpc()) == 0

    stored = store.get_activation(activation.activation_id)
    assert stored.state == "active"
    assert "alert: the position is out of range (block 900)" in stored.events[-1].reason


def test_an_action_inside_the_policy_is_sent_by_the_session_and_receipted(
    tmp_path, sessions_key
):
    store = Store(tmp_path / "tick.sqlite3")
    rpc = SendingRpc()
    _, activation = _active(store, rpc)
    register("rebalancing", ActionExecutor())

    assert tick.run_once(store, rpc=rpc, environment=sessions_key) == 0

    stored = store.get_activation(activation.activation_id)
    assert stored.state == "active"
    assert len(rpc.sent) == 1
    assert stored.receipts[-1].execution["tx_hash"] == rpc.sent[0]
    assert stored.session["spent_atomic"] == {USDT: str(10 * 10**18)}


def test_an_action_outside_the_policy_is_handed_to_the_owner_to_sign(tmp_path):
    store = Store(tmp_path / "tick.sqlite3")
    rpc = SendingRpc()
    _, activation = _active(store, rpc)
    register("rebalancing", ActionExecutor(permitted=False))

    assert tick.run_once(store, rpc=rpc) == 0

    stored = store.get_activation(activation.activation_id)
    assert stored.state == "needs_approval"
    assert stored.next_action.kind == "sign_transaction"
    assert len(stored.next_action.detail["calls"]) == 1
    assert stored.next_action.detail["block"] == 900
    assert "above the per-action limit" in stored.events[-1].reason
    assert rpc.sent == []


def test_an_execution_that_fails_is_counted_and_recorded(tmp_path, sessions_key):
    store = Store(tmp_path / "tick.sqlite3")
    rpc = SendingRpc()
    _, activation = _active(store, rpc)
    rpc.w3.eth.call = lambda transaction: (_ for _ in ()).throw(
        RuntimeError("execution reverted")
    )
    register("rebalancing", ActionExecutor())

    assert tick.run_once(store, rpc=rpc, environment=sessions_key) == 1

    stored = store.get_activation(activation.activation_id)
    assert any("reverted in simulation" in event.reason for event in stored.events)
    assert rpc.sent == []


def test_a_paused_activation_is_left_alone(tmp_path):
    store = Store(tmp_path / "tick.sqlite3")
    rpc = SendingRpc()
    service, activation = _active(store, rpc)
    service.pause(activation.activation_id)
    executor = ActionExecutor()
    register("rebalancing", executor)

    assert tick.run_once(store, rpc=rpc) == 0

    assert executor.seen == []
    assert store.get_activation(activation.activation_id).state == "paused"


def test_an_expired_policy_is_closed_and_swept_by_the_tick(tmp_path, sessions_key):
    store = Store(tmp_path / "tick.sqlite3")
    rpc = SendingRpc()
    soon = (datetime.now(timezone.utc) + timedelta(seconds=1)).isoformat()
    service, activation = _active(store, rpc, policy={**POLICY, "expires_at": soon})
    past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    stored = store.get_activation(activation.activation_id)
    expected = stored.updated_at
    stored.expires_at = past
    store.save_activation(stored, expected_updated_at=expected)
    register("rebalancing", ActionExecutor())

    assert tick.run_once(store, rpc=rpc, environment=sessions_key) == 0

    closed = store.get_activation(activation.activation_id)
    assert closed.state == "expired"
    assert store.get_session(activation.activation_id)["revoked_at"] is not None


def test_one_activation_failing_never_stops_the_next(tmp_path):
    store = Store(tmp_path / "tick.sqlite3")
    rpc = SendingRpc()
    _active(store, rpc)
    _active(store, rpc)
    _active(store, rpc)
    register("rebalancing", ExplodingExecutor())

    assert tick.run_once(store, rpc=rpc) == 3


def test_a_one_shot_activation_is_never_the_ticks_business(tmp_path):
    store = Store(tmp_path / "tick.sqlite3")
    service = ActivationService(
        store,
        services={
            "range-doctor": replace(
                get_service("range-doctor"), run=lambda payload: {"summary": "read"}
            )
        },
        master_password=PASSWORD,
    )
    service.create(
        "range-doctor", kind="one_shot", owner=OWNER, inputs={"wallet": OWNER}
    )
    executor = ActionExecutor()
    register("rebalancing", executor)

    assert tick.run_once(store, rpc=FakeRpc()) == 0
    assert executor.seen == []


def test_main_exits_zero_on_a_clean_pass_and_one_when_an_activation_errored(
    tmp_path, capsys
):
    store = Store(tmp_path / "tick.sqlite3")
    _active(store, FakeRpc())
    register("rebalancing", NoopExecutor("rebalancing"))

    assert tick.main(["--db", str(tmp_path / "tick.sqlite3")]) == 0
    assert "0 activations errored" in capsys.readouterr().out

    EXECUTORS.clear()
    register("rebalancing", ExplodingExecutor())
    assert tick.main(["--db", str(tmp_path / "tick.sqlite3")]) == 1


def test_main_refuses_to_run_without_a_database(tmp_path, monkeypatch):
    monkeypatch.delenv("DOCKET_DB", raising=False)

    assert tick.main([]) == 1


def test_the_registry_refuses_an_unknown_category_and_a_second_claim():
    register("rebalancing", NoopExecutor("rebalancing"))

    with pytest.raises(ValueError, match="already has a registered executor"):
        register("rebalancing", NoopExecutor("rebalancing"))
    with pytest.raises(ValueError, match="unknown category"):
        register("market_making", NoopExecutor("rebalancing"))


def test_a_noop_executor_reports_the_block_it_never_asked_for_as_zero():
    decision = NoopExecutor("rebalancing").evaluate(None)

    assert decision.kind == "noop"
    assert decision.block == 0
    assert "no chain call" in decision.evidence["read"]


def test_a_decision_cannot_claim_an_action_with_nothing_to_send():
    with pytest.raises(ValueError, match="acts on nothing"):
        Decision(
            kind="action",
            summary="something",
            prepared=(),
            evidence={},
            observed_at="t",
            block=1,
        )
    with pytest.raises(ValueError, match="nothing would send"):
        Decision(
            kind="noop",
            summary="something",
            prepared=(
                PreparedCall(
                    to=NFPM,
                    data="0x38ed1739",
                    value_atomic="0",
                    gas_ceiling=1,
                    deadline=1,
                    purpose="p",
                    simulation={"ok": True},
                ),
            ),
            evidence={},
            observed_at="t",
            block=1,
        )


def test_a_prepared_call_must_carry_its_own_simulation():
    with pytest.raises(ValueError, match="must carry its simulation"):
        PreparedCall(
            to=Web3.to_checksum_address(ROUTER),
            data="0x38ed1739",
            value_atomic="0",
            gas_ceiling=1,
            deadline=1,
            purpose="p",
            simulation={},
        )
    with pytest.raises(ValueError, match="0x-prefixed hex"):
        PreparedCall(
            to=ROUTER,
            data="38ed1739",
            value_atomic="0",
            gas_ceiling=1,
            deadline=1,
            purpose="p",
            simulation={"ok": True},
        )
