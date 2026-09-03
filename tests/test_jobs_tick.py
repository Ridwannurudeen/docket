"""The tick loop: what it advances, what it refuses to crash on, and what it reports.

`EXECUTORS` is a module-level registry, so every test that touches it restores it. A
leaked registration would make the next test pass for the wrong reason.
"""

from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest
from web3 import Web3

from docket.execution.simulate import swap_calldata
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
    WBNB,
    FakeRpc,
    _funding_transaction,
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


def _swap(amount_in: int) -> PreparedCall:
    """Real router calldata: the spend is now read out of these bytes."""
    return PreparedCall(
        to=ROUTER,
        data="0x"
        + swap_calldata(
            amount_in=amount_in,
            min_output=1,
            route=(USDT, WBNB),
            recipient=OWNER,
            deadline=4_102_444_800,
        ).hex(),
        value_atomic="0",
        gas_ceiling=300_000,
        deadline=4_102_444_800,
        purpose="recenter the position",
        simulation={"ok": True, "gas_estimate": 180_000, "block": 900},
    )


class ActionExecutor:
    """One or more prepared swaps, and a `within_policy` the test can flip."""

    category = "rebalancing"

    def __init__(
        self, *, permitted=True, kind="action", token_amount=10 * 10**18, calls=1
    ):
        self.permitted = permitted
        self.kind = kind
        self.token_amount = token_amount
        self.calls = calls
        self.seen = []

    def evaluate(self, activation, *, reader=None):
        self.seen.append(activation.activation_id)
        prepared = tuple(_swap(self.token_amount) for _ in range(self.calls))
        return Decision(
            kind=self.kind,
            summary="the position is out of range",
            prepared=prepared if self.kind == "action" else (),
            evidence={"observed_ticks": 1},
            observed_at="2026-09-03T00:00:00+00:00",
            block=900,
        )

    def within_policy(self, activation, decision):
        return self.permitted, (
            "inside the policy" if self.permitted else "above the per-action limit"
        )


class CarryOverExecutor:
    """Reads its own prior evidence back and counts how many passes it has seen.

    This is the shape every persistent executor has: constructed, asked once, dropped.
    If the tick does not persist `evidence`, `passes` is 1 for ever.
    """

    category = "rebalancing"

    def evaluate(self, activation, *, reader=None):
        previous = ((activation.result or {}).get("last_decision") or {}).get(
            "evidence"
        ) or {}
        passes = int(previous.get("passes", 0)) + 1
        return Decision(
            kind="noop",
            summary=f"seen {passes} passes",
            prepared=(),
            evidence={"passes": passes, "first_seen": previous.get("first_seen", "t0")},
            observed_at="2026-09-03T00:00:00+00:00",
            block=900,
        )

    def within_policy(self, activation, decision):
        return False, "a noop proposes nothing"


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
    """One funded, active persistent activation, walked there through the real path.

    Including the tick's own minting step: `create` leaves it in `awaiting_session` with
    no key, because the web process holds no master password.
    """
    service = _service(store, rpc)
    created = service.create(
        "range-doctor",
        kind="persistent",
        owner=OWNER,
        inputs={"wallet": OWNER},
        policy=POLICY if policy is None else policy,
    )
    expected = created.updated_at
    service.mint_session(created)
    store.save_activation(created, expected_updated_at=expected)
    tx_hash = "0x" + f"{len(rpc.w3.eth.receipts) + 1:064x}"
    rpc.w3.eth.receipts[tx_hash] = _transfer_receipt(created.session["address"])
    rpc.w3.eth.transactions[tx_hash] = _funding_transaction(created.session["address"])
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


def test_a_noop_records_its_observation_without_moving_the_activation(tmp_path):
    store = Store(tmp_path / "tick.sqlite3")
    _, activation = _active(store, FakeRpc())
    register("rebalancing", NoopExecutor("rebalancing"))

    assert tick.run_once(store, rpc=FakeRpc()) == 0

    stored = store.get_activation(activation.activation_id)
    assert stored.state == "active"
    assert [event.to_state for event in stored.events[len(activation.events) :]] == [
        "active"
    ]
    assert stored.result["last_decision"]["kind"] == "noop"
    assert stored.result["last_decision"]["evidence"]["read"].startswith("none")


def test_an_executor_reads_its_own_prior_evidence_back_on_the_next_pass(tmp_path):
    """The defect this closes: evidence was computed and thrown away, so an executor that
    measures anything over time — how long a position has been out of range, which rung
    of a grid is filled — started every pass blind."""
    store = Store(tmp_path / "tick.sqlite3")
    _, activation = _active(store, FakeRpc())
    register("rebalancing", CarryOverExecutor())

    assert tick.run_once(store, rpc=FakeRpc()) == 0
    first = store.get_activation(activation.activation_id)
    assert first.result["last_decision"]["evidence"] == {
        "passes": 1,
        "first_seen": "t0",
    }

    assert tick.run_once(store, rpc=FakeRpc()) == 0
    second = store.get_activation(activation.activation_id)
    assert second.result["last_decision"]["evidence"]["passes"] == 2
    assert second.result["last_decision"]["summary"] == "seen 2 passes"


def test_a_kind_that_does_not_change_does_not_repeat_its_note(tmp_path):
    """A pass every five minutes would otherwise write an event every five minutes."""
    store = Store(tmp_path / "tick.sqlite3")
    _, activation = _active(store, FakeRpc())
    register("rebalancing", CarryOverExecutor())

    tick.run_once(store, rpc=FakeRpc())
    after_first = len(store.get_activation(activation.activation_id).events)
    tick.run_once(store, rpc=FakeRpc())
    tick.run_once(store, rpc=FakeRpc())

    assert len(store.get_activation(activation.activation_id).events) == after_first


def test_a_one_shot_result_is_not_overwritten_by_a_decision(tmp_path):
    """`result` carries a one-shot's own output under its own keys. The tick writes only
    `last_decision`, and a persistent activation never has the other keys — but the field
    is shared, so the merge is what keeps them from colliding."""
    store = Store(tmp_path / "tick.sqlite3")
    _, activation = _active(store, FakeRpc())
    stored = store.get_activation(activation.activation_id)
    expected = stored.updated_at
    stored.result = {"positions": [{"token_id": 1}]}
    store.save_activation(stored, expected_updated_at=expected)
    register("rebalancing", NoopExecutor("rebalancing"))

    tick.run_once(store, rpc=FakeRpc())

    result = store.get_activation(activation.activation_id).result
    assert result["positions"] == [{"token_id": 1}]
    assert result["last_decision"]["kind"] == "noop"


def test_an_alert_decision_is_recorded_without_moving_the_activation(tmp_path):
    store = Store(tmp_path / "tick.sqlite3")
    _, activation = _active(store, FakeRpc())
    register("rebalancing", ActionExecutor(kind="alert"))

    assert tick.run_once(store, rpc=FakeRpc()) == 0

    stored = store.get_activation(activation.activation_id)
    assert stored.state == "active"
    assert "alert: the position is out of range (block 900)" in stored.events[-1].reason
    assert stored.result["last_decision"]["evidence"] == {"observed_ticks": 1}


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
    # The fee is a spend like any other and is charged under the native key beside it.
    assert stored.session["spent_atomic"][USDT] == str(10 * 10**18)
    assert int(stored.session["spent_atomic"]["BNB"]) > 0


def test_a_batch_is_charged_once_per_call_and_not_once_per_call_times_the_batch(
    tmp_path, sessions_key
):
    """The defect this closes: the batch total from the evidence was passed to every
    call, and `allows` accumulates per call, so eight calls of 50 USDT were charged as
    eight times the batch — 3,200 against a 500 cap — and the batch was refused. Charged
    per call from its own calldata, the same eight calls total 400 and go out.

    The regression guard is the arithmetic beside it: 8 x 400 is 3,200, which is past the
    cap, so a run under the old behaviour could not reach these assertions.
    """
    store = Store(tmp_path / "tick.sqlite3")
    rpc = SendingRpc()
    _, activation = _active(store, rpc)
    register("rebalancing", ActionExecutor(token_amount=50 * 10**18, calls=8))

    assert tick.run_once(store, rpc=rpc, environment=sessions_key) == 0

    stored = store.get_activation(activation.activation_id)
    assert len(rpc.sent) == 8
    assert stored.session["spent_atomic"][USDT] == str(400 * 10**18)
    assert 8 * 400 * 10**18 > int(POLICY["total_cap_atomic"][USDT])
    assert len(stored.receipts) == 8


def test_a_batch_whose_total_passes_the_cap_is_refused_before_anything_is_sent(
    tmp_path, sessions_key
):
    """Refused at zero transactions rather than three, which would leave the position
    half-rebalanced and the owner holding a state nobody chose."""
    store = Store(tmp_path / "tick.sqlite3")
    rpc = SendingRpc()
    _, activation = _active(store, rpc)
    register("rebalancing", ActionExecutor(token_amount=100 * 10**18, calls=8))

    assert tick.run_once(store, rpc=rpc, environment=sessions_key) == 0

    stored = store.get_activation(activation.activation_id)
    assert rpc.sent == []
    assert stored.state == "needs_approval"
    assert stored.next_action.detail["batch_spend_atomic"] == {USDT: str(800 * 10**18)}
    assert "past the session cap" in stored.events[-1].reason


def test_a_call_whose_spend_cannot_be_derived_is_refused(tmp_path, sessions_key):
    store = Store(tmp_path / "tick.sqlite3")
    rpc = SendingRpc()
    _, activation = _active(store, rpc)

    class OpaqueExecutor(ActionExecutor):
        def evaluate(self, activation, *, reader=None):
            decision = super().evaluate(activation, reader=reader)
            opaque = PreparedCall(
                to=ROUTER,
                data="0xdeadbeef",
                value_atomic=str(10**15),
                gas_ceiling=300_000,
                deadline=4_102_444_800,
                purpose="something Docket did not build",
                simulation={"ok": True, "gas_estimate": 100_000, "block": 900},
            )
            return Decision(
                kind="action",
                summary=decision.summary,
                prepared=(opaque,),
                evidence=decision.evidence,
                observed_at=decision.observed_at,
                block=decision.block,
            )

    register("rebalancing", OpaqueExecutor())

    assert tick.run_once(store, rpc=rpc, environment=sessions_key) == 1

    stored = store.get_activation(activation.activation_id)
    assert rpc.sent == []
    assert any("unmeasured spend" in event.reason for event in stored.events)


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
    """Two passes, and the second is the one that may say the money is back: the first
    marks it for closing and sweeps, the second reads the balances and closes."""
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
    marked = store.get_activation(activation.activation_id)
    assert marked.state == "revoking"
    assert store.get_session(activation.activation_id)["revoked_at"] is None

    assert tick.run_once(store, rpc=rpc, environment=sessions_key) == 0
    closed = store.get_activation(activation.activation_id)
    assert closed.state == "expired"
    assert store.get_session(activation.activation_id)["revoked_at"] is not None


def test_the_tick_mints_a_key_for_an_activation_the_web_process_could_not(
    tmp_path, sessions_key
):
    store = Store(tmp_path / "tick.sqlite3")
    service = _service(store, FakeRpc())
    created = service.create(
        "range-doctor",
        kind="persistent",
        owner=OWNER,
        inputs={"wallet": OWNER},
        policy=POLICY,
    )
    assert created.session is None

    assert tick.run_once(store, rpc=FakeRpc(), environment=sessions_key) == 0

    minted = store.get_activation(created.activation_id)
    assert minted.state == "awaiting_session"
    assert minted.next_action.kind == "fund_session"
    assert minted.session["address"] == store.get_session(created.activation_id)[
        "address"
    ]


def test_a_close_that_cannot_open_the_keystore_stays_revoking_for_the_next_pass(
    tmp_path, sessions_key
):
    """Never left `active`, and never closed on a reading nobody could take."""
    store = Store(tmp_path / "tick.sqlite3")
    rpc = SendingRpc()
    service, activation = _active(store, rpc)
    service.revoke(activation.activation_id)

    assert tick.run_once(store, rpc=rpc, environment={}) == 1

    stored = store.get_activation(activation.activation_id)
    assert stored.state == "revoking"
    assert any("did not complete" in event.reason for event in stored.events)


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
