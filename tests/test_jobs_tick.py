"""The tick loop: what it advances, what it refuses to crash on, and what it reports.

`EXECUTORS` is a module-level registry, so every test that touches it restores it. A
leaked registration would make the next test pass for the wrong reason.
"""

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from web3 import Web3

from docket.execution.simulate import swap_calldata
from docket.hire.catalogue import get_service
from docket.jobs import tick
from docket.jobs.executors import EXECUTORS, NoopExecutor, register
from docket.jobs.executors.base import Decision, PreparedCall
from docket.jobs.service import ActivationService
from docket.store import StaleActivation, Store
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
    soon = (datetime.now(UTC) + timedelta(seconds=1)).isoformat()
    service, activation = _active(store, rpc, policy={**POLICY, "expires_at": soon})
    past = (datetime.now(UTC) - timedelta(minutes=1)).isoformat()
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
    assert (
        minted.session["address"] == store.get_session(created.activation_id)["address"]
    )


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


def test_a_pass_that_broadcast_is_merged_rather_than_dropped_when_the_row_moved(
    tmp_path, sessions_key
):
    """The one case where losing a write loses money: the transactions are already on
    chain, and the record of them lives on the row the save was refused."""
    store = Store(tmp_path / "tick.sqlite3")
    rpc = SendingRpc()
    _, activation = _active(store, rpc)
    register("rebalancing", ActionExecutor())

    saves = {"n": 0}
    real_save = store.save_activation

    def racing_save(row, *, expected_updated_at):
        # The pass now writes three times: the pending record before the broadcast, the
        # hash after it, and the settled batch at the end. The third is the one that
        # carries the receipt, and it is the one raced here — a race on the first is a
        # refused send and is covered separately.
        saves["n"] += 1
        if saves["n"] == 3:
            other = store.get_activation(row.activation_id)
            other.note("another writer got here first", actor="user")
            real_save(other, expected_updated_at=expected_updated_at)
        return real_save(row, expected_updated_at=expected_updated_at)

    store.save_activation = racing_save
    tick.run_once(store, rpc=rpc, environment=sessions_key)
    store.save_activation = real_save

    stored = store.get_activation(activation.activation_id)
    assert len(rpc.sent) == 1
    assert stored.receipts[-1].execution["tx_hash"] == rpc.sent[0]
    assert stored.result["settled_sends"][-1]["tx_hash"] == rpc.sent[0]
    assert any("merged onto its record" in event.reason for event in stored.events)


def test_a_broadcast_is_written_down_before_it_is_sent(tmp_path, sessions_key):
    store = Store(tmp_path / "tick.sqlite3")
    rpc = SendingRpc()
    _, activation = _active(store, rpc)
    register("rebalancing", ActionExecutor())

    tick.run_once(store, rpc=rpc, environment=sessions_key)

    stored = store.get_activation(activation.activation_id)
    settled = stored.result["settled_sends"]
    assert stored.result["pending_sends"] == {}
    assert settled[-1]["status"] == 1
    assert settled[-1]["tx_hash"] == rpc.sent[0]
    assert int(settled[-1]["gas_atomic"]) > 0


def test_a_stale_write_conservatively_merges_allowance_reservations(tmp_path):
    store = Store(tmp_path / "tick.sqlite3")
    _, activation = _active(store, FakeRpc())
    expected = activation.updated_at
    ours = store.get_activation(activation.activation_id)
    current = store.get_activation(activation.activation_id)
    ours.session["reserved_atomic"] = {USDT: {ROUTER: "300"}}
    current.session["reserved_atomic"] = {USDT: {NPM_ADDRESS: "200"}}
    current.note("concurrent reservation", actor="docket")
    store.save_activation(current, expected_updated_at=expected)

    tick._save_sends(store, ours, expected, spent_baseline={})

    assert store.get_activation(activation.activation_id).session[
        "reserved_atomic"
    ] == {USDT: {ROUTER: "300", NPM_ADDRESS: "200"}}


def test_a_stale_settlement_supersedes_the_same_pending_transaction(tmp_path):
    store = Store(tmp_path / "tick.sqlite3")
    _, activation = _active(store, FakeRpc())
    expected = activation.updated_at
    ours = store.get_activation(activation.activation_id)
    current = store.get_activation(activation.activation_id)
    tx_hash = "0x" + "ab" * 32
    current.result = {
        **(current.result or {}),
        "pending_sends": {"7": {"nonce": 7, "tx_hash": tx_hash}},
    }
    current.note(
        "concurrent pending write",
        actor="docket",
        at=(datetime.now(UTC) + timedelta(seconds=1)).isoformat(),
    )
    store.save_activation(current, expected_updated_at=expected)
    ours.result = {
        **(ours.result or {}),
        "settled_sends": [
            {"nonce": 7, "tx_hash": tx_hash, "status": 0, "gas_atomic": "1"}
        ],
    }

    tick._save_sends(store, ours, expected, spent_baseline={})

    stored = store.get_activation(activation.activation_id)
    assert stored.result["pending_sends"] == {}
    assert stored.result["settled_sends"] == [
        {"nonce": 7, "tx_hash": tx_hash, "status": 0, "gas_atomic": "1"}
    ]


def test_stale_independently_settled_spends_stay_cumulative(tmp_path):
    store = Store(tmp_path / "tick.sqlite3")
    _, activation = _active(store, FakeRpc())
    expected = activation.updated_at
    ours = store.get_activation(activation.activation_id)
    current = store.get_activation(activation.activation_id)
    current.session["spent_atomic"] = {USDT: "200"}
    current.result = {
        **(current.result or {}),
        "settled_sends": [
            {"tx_hash": "0x" + "ab" * 32, "status": 1, "gas_atomic": "1"}
        ],
    }
    current.note(
        "concurrent settled spend",
        actor="docket",
        at=(datetime.now(UTC) + timedelta(seconds=1)).isoformat(),
    )
    store.save_activation(current, expected_updated_at=expected)
    assert store.get_activation(activation.activation_id).session["spent_atomic"] == {
        USDT: "200"
    }
    ours.session["spent_atomic"] = {USDT: "300"}
    ours.result = {
        **(ours.result or {}),
        "settled_sends": [
            {"tx_hash": "0x" + "cd" * 32, "status": 1, "gas_atomic": "1"}
        ],
    }

    tick._save_sends(store, ours, expected, spent_baseline={USDT: "0"})

    stored = store.get_activation(activation.activation_id)
    assert stored.session["spent_atomic"] == {USDT: "500"}
    assert [entry["tx_hash"] for entry in stored.result["settled_sends"]] == [
        "0x" + "ab" * 32,
        "0x" + "cd" * 32,
    ]


# -- durability, against a node that behaves like one --------------------------


class NodeRpc:
    """The audit's fake node, wired the way the tick wires a real one."""

    def __init__(self, node):
        self.node = node

    def __call__(self, do):
        return do(self.node.w3)


def _node_active(store, node, *, bnb=10**17, usdt=500 * 10**18, policy=None):
    from tests.test_jobs_service import _funding_transaction

    service = _service(store, NodeRpc(node))
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
    address = created.session["address"]
    tx_hash = "0x" + "ab" * 32
    node.receipts[tx_hash] = _transfer_receipt(address)
    node.txs[tx_hash] = _funding_transaction(address)
    service.approve(created.activation_id, tx_hash=tx_hash)
    node.bnb[address] = bnb
    node.tokens.setdefault(USDT, {})[address] = usdt
    return service, store.get_activation(created.activation_id)


def test_a_kill_between_the_send_and_the_receipt_leaves_the_record_on_disk(
    tmp_path, sessions_key, monkeypatch
):
    """The transaction is on the wire. If the only record of it lives in memory, the pass
    that dies takes it with it and the next pass sends the same action again."""
    from tests.fakenode import Node

    monkeypatch.setattr("docket.sessions.executor.RECEIPT_PAUSE_S", 0)
    store = Store(tmp_path / "tick.sqlite3")
    node = Node(estimate=180_000)
    _, activation = _node_active(store, node)
    register("rebalancing", ActionExecutor())

    def die(n):
        raise KeyboardInterrupt("SIGTERM between the send and its receipt")

    node.on_receipt = die
    with pytest.raises(KeyboardInterrupt):
        tick.run_once(store, rpc=NodeRpc(node), environment=sessions_key)

    assert len(node.pending) == 1
    stored = store.get_activation(activation.activation_id)
    pending = stored.result["pending_sends"]
    assert len(pending) == 1
    entry = next(iter(pending.values()))
    assert entry["tx_hash"] == node.pending[0]["hash"]
    assert entry["purpose"] == "recenter the position"
    assert int(entry["estimated_fee_atomic"]) > 0
    assert entry["amounts"][USDT] == str(10 * 10**18)


def test_a_send_is_refused_when_another_writer_reached_the_row_first(
    tmp_path, sessions_key, monkeypatch
):
    """The persist before the broadcast is also the last chance to notice a concurrent
    writer. Its refusal must stop the send, not follow it."""
    from tests.fakenode import Node

    monkeypatch.setattr("docket.sessions.executor.RECEIPT_PAUSE_S", 0)
    store = Store(tmp_path / "tick.sqlite3")
    node = Node(estimate=180_000)
    _, activation = _node_active(store, node)
    aid = activation.activation_id
    register("rebalancing", ActionExecutor())
    other = Store(tmp_path / "tick.sqlite3")

    real_save = store.save_activation
    saves = {"n": 0}

    def racing_save(row, *, expected_updated_at):
        saves["n"] += 1
        if saves["n"] == 1:
            competitor = other.get_activation(aid)
            competitor.note("another writer", actor="user")
            real_save(competitor, expected_updated_at=expected_updated_at)
        return real_save(row, expected_updated_at=expected_updated_at)

    store.save_activation = racing_save
    errors = tick.run_once(store, rpc=NodeRpc(node), environment=sessions_key)
    store.save_activation = real_save

    assert errors == 1
    assert node.pending == []
    assert node.mined_order == []


def test_a_token_received_on_an_earlier_pass_is_still_swept_after_a_quiet_one(
    tmp_path, sessions_key, monkeypatch
):
    """The stranded-token scenario: a swap on pass N, a noop on N+1, then revoke. The
    union lives on the activation, so the quiet pass cannot forget the output token."""
    from docket.jobs.executors.base import Decision
    from tests.fakenode import Node

    monkeypatch.setattr("docket.sessions.executor.RECEIPT_PAUSE_S", 0)
    monkeypatch.setattr("docket.sessions.sweep.RECEIPT_PAUSE_S", 0)
    store = Store(tmp_path / "tick.sqlite3")
    node = Node()
    node.automine_on_receipt = True
    service, activation = _node_active(store, node, usdt=0, bnb=5 * 10**16)
    aid = activation.activation_id
    address = activation.session["address"]
    node.tokens.setdefault(WBNB, {})[address] = 3 * 10**18

    class Received(NoopExecutor):
        def evaluate(self, activation, *, reader=None):
            return Decision(
                kind="noop",
                summary="swapped earlier; holding WBNB",
                prepared=(),
                evidence={"received_tokens": [WBNB]},
                observed_at="t",
                block=1,
            )

    register("rebalancing", Received("rebalancing"))
    assert tick.run_once(store, rpc=NodeRpc(node), environment=sessions_key) == 0
    assert WBNB in store.get_activation(aid).session["received_tokens"]

    EXECUTORS.clear()
    register("rebalancing", NoopExecutor("rebalancing"))
    assert tick.run_once(store, rpc=NodeRpc(node), environment=sessions_key) == 0
    # The last decision has forgotten it; the activation has not.
    evidence = store.get_activation(aid).result["last_decision"]["evidence"]
    assert "received_tokens" not in evidence
    assert WBNB in store.get_activation(aid).session["received_tokens"]

    service.revoke(aid)
    for _ in range(3):
        tick.run_once(store, rpc=NodeRpc(node), environment=sessions_key)
        node.mine()

    assert store.get_activation(aid).state == "revoked"
    assert node.tokens[WBNB].get(address, 0) == 0
    assert node.tokens[WBNB][OWNER] == 3 * 10**18


def test_a_swap_output_is_remembered_from_the_calldata_even_if_nobody_declared_it(
    tmp_path, sessions_key, monkeypatch
):
    from tests.fakenode import Node

    monkeypatch.setattr("docket.sessions.executor.RECEIPT_PAUSE_S", 0)
    store = Store(tmp_path / "tick.sqlite3")
    node = Node(estimate=180_000)
    node.automine_on_receipt = True
    _, activation = _node_active(store, node)
    register("rebalancing", ActionExecutor())

    assert tick.run_once(store, rpc=NodeRpc(node), environment=sessions_key) == 0

    # The executor's evidence names no received token; the swap's own path does.
    stored = store.get_activation(activation.activation_id)
    assert WBNB in stored.session["received_tokens"]


def test_a_key_created_before_the_save_is_adopted_rather_than_replaced(
    tmp_path, sessions_key
):
    """A pass killed between writing the sessions row and saving the activation left a
    key that exists and an activation that did not know about it. Minting a second one
    would strand the first for ever."""
    from tests.fakenode import Node

    store = Store(tmp_path / "tick.sqlite3")
    node = Node()
    service = _service(store, NodeRpc(node))
    created = service.create(
        "range-doctor",
        kind="persistent",
        owner=OWNER,
        inputs={"wallet": OWNER},
        policy=POLICY,
    )
    aid = created.activation_id
    real_save = store.save_activation
    calls = {"n": 0}

    def dying_save(row, *, expected_updated_at):
        calls["n"] += 1
        if calls["n"] == 1:
            raise KeyboardInterrupt("killed after the sessions row was written")
        return real_save(row, expected_updated_at=expected_updated_at)

    store.save_activation = dying_save
    with pytest.raises(KeyboardInterrupt):
        tick.run_once(store, rpc=NodeRpc(node), environment=sessions_key)
    store.save_activation = real_save
    orphan = store.get_session(aid)["address"]

    assert tick.run_once(store, rpc=NodeRpc(node), environment=sessions_key) == 0

    stored = store.get_activation(aid)
    assert stored.session["address"] == orphan
    assert stored.next_action.kind == "fund_session"
    assert any("adopting the session key" in e.reason for e in stored.events)


# -- approvals across passes ----------------------------------------------------

NPM_ADDRESS = Web3.to_checksum_address("0x46A15B0b27311cedF172AB29E4f4766fbE7F4364")
ATTACKER = Web3.to_checksum_address("0x" + "a7" * 20)
_erc20_tick = Web3().eth.contract(
    abi=[
        {
            "name": "approve",
            "type": "function",
            "inputs": [
                {"name": "spender", "type": "address"},
                {"name": "amount", "type": "uint256"},
            ],
            "outputs": [{"name": "", "type": "bool"}],
        }
    ]
)


class ApprovingExecutor:
    """One approval and nothing else: the batch that stops before the pull."""

    category = "rebalancing"

    def __init__(self, *, spender=NPM_ADDRESS, amount=200 * 10**18, spenders=None):
        self.spender = spender
        self.amount = amount
        # One spender per pass, so the test can show what a SINGLE spender cannot: the
        # aggregate of several standing allowances.
        self.spenders = list(spenders or ())

    def evaluate(self, activation, *, reader=None):
        spender = self.spenders.pop(0) if self.spenders else self.spender
        call = PreparedCall(
            to=USDT,
            data=_erc20_tick.encode_abi("approve", args=[spender, self.amount]),
            value_atomic="0",
            gas_ceiling=300_000,
            deadline=4_102_444_800,
            purpose="authorise the position manager to pull the mint amount",
            simulation={"ok": True, "gas_estimate": 60_000, "block": 900},
        )
        return Decision(
            kind="action",
            summary="approve before the mint",
            prepared=(call,),
            evidence={},
            observed_at="2026-09-04T00:00:00+00:00",
            block=900,
        )

    def within_policy(self, activation, decision):
        return True, "inside the policy"


class ApprovalBatchExecutor(ApprovingExecutor):
    def evaluate(self, activation, *, reader=None):
        calls = tuple(
            PreparedCall(
                to=USDT,
                data=_erc20_tick.encode_abi(
                    "approve", args=[spender, 300 * 10**18]
                ),
                value_atomic="0",
                gas_ceiling=300_000,
                deadline=4_102_444_800,
                purpose="authorise one spender",
                simulation={"ok": True},
            )
            for spender in (NPM_ADDRESS, ROUTER)
        )
        return Decision(
            kind="action",
            summary="authorise both spenders",
            prepared=calls,
            evidence={},
            observed_at="2026-09-04T00:00:00+00:00",
            block=900,
        )


def test_standing_approvals_add_up_against_the_lifetime_cap(
    tmp_path, sessions_key, monkeypatch
):
    """The blocker. Nothing MOVES when a batch approves and then stops, so durable spend
    stayed empty and the next pass approved again — and the aggregate on-chain allowance
    across spenders grew past the lifetime cap while every individual check passed.

    Two spenders, 300 each, against a 500 cap: the first pass grants, the second is
    refused, and nothing further is broadcast.
    """
    from tests.fakenode import Node

    monkeypatch.setattr("docket.sessions.executor.RECEIPT_PAUSE_S", 0)
    store = Store(tmp_path / "tick.sqlite3")
    node = Node(estimate=60_000)
    node.automine_on_receipt = True
    policy = {
        **POLICY,
        "per_action_limit_atomic": {
            **POLICY["per_action_limit_atomic"],
            USDT: "300000000000000000000",
        },
    }
    _, activation = _node_active(store, node, policy=policy)
    aid = activation.activation_id
    register(
        "rebalancing",
        ApprovingExecutor(
            amount=300 * 10**18, spenders=[NPM_ADDRESS, ROUTER, ROUTER]
        ),
    )

    assert tick.run_once(store, rpc=NodeRpc(node), environment=sessions_key) == 0
    first = store.get_activation(aid)
    address = first.session["address"]
    assert node.allowances[USDT][(address, NPM_ADDRESS)] == 300 * 10**18
    # Nothing has moved, and the exposure is recorded anyway.
    assert USDT not in first.session["spent_atomic"]
    assert first.session["reserved_atomic"][USDT][NPM_ADDRESS] == str(300 * 10**18)

    # A second spender would take the standing total to 600 against a cap of 500.
    assert tick.run_once(store, rpc=NodeRpc(node), environment=sessions_key) == 0
    second = store.get_activation(aid)
    assert second.state == "needs_approval"
    assert "past the session cap" in second.events[-1].reason
    assert (address, ROUTER) not in node.allowances.get(USDT, {})


def test_reapproving_the_same_amount_to_the_same_spender_is_a_replacement(
    tmp_path, sessions_key, monkeypatch
):
    from tests.fakenode import Node

    monkeypatch.setattr("docket.sessions.executor.RECEIPT_PAUSE_S", 0)
    store = Store(tmp_path / "tick.sqlite3")
    node = Node(estimate=60_000)
    node.automine_on_receipt = True
    policy = {
        **POLICY,
        "per_action_limit_atomic": {
            **POLICY["per_action_limit_atomic"],
            USDT: str(300 * 10**18),
        },
    }
    _, activation = _node_active(store, node, policy=policy)
    register("rebalancing", ApprovingExecutor(amount=300 * 10**18))

    assert tick.run_once(store, rpc=NodeRpc(node), environment=sessions_key) == 0
    assert tick.run_once(store, rpc=NodeRpc(node), environment=sessions_key) == 0

    stored = store.get_activation(activation.activation_id)
    assert len(node.mined_order) == 2
    assert stored.session["reserved_atomic"][USDT][NPM_ADDRESS] == str(300 * 10**18)


def test_two_spender_approval_batch_is_refused_before_the_first_broadcast(
    tmp_path, sessions_key
):
    from tests.fakenode import Node

    store = Store(tmp_path / "tick.sqlite3")
    node = Node(estimate=60_000)
    policy = {
        **POLICY,
        "per_action_limit_atomic": {
            **POLICY["per_action_limit_atomic"],
            USDT: str(300 * 10**18),
        },
    }
    _, activation = _node_active(store, node, policy=policy)
    register("rebalancing", ApprovalBatchExecutor())

    assert tick.run_once(store, rpc=NodeRpc(node), environment=sessions_key) == 0

    stored = store.get_activation(activation.activation_id)
    assert stored.state == "needs_approval"
    assert node.pending == []
    assert node.mined_order == []


def test_an_external_pull_is_charged_before_the_next_evaluation(
    tmp_path, sessions_key
):
    from tests.fakenode import Node

    store = Store(tmp_path / "tick.sqlite3")
    node = Node(estimate=60_000)
    policy = {
        **POLICY,
        "per_action_limit_atomic": {
            **POLICY["per_action_limit_atomic"],
            USDT: str(300 * 10**18),
        },
    }
    _, activation = _node_active(store, node, policy=policy)
    aid = activation.activation_id
    address = activation.session["address"]
    activation.session["reserved_atomic"] = {
        USDT: {NPM_ADDRESS: str(300 * 10**18)}
    }
    store.save_activation(activation, expected_updated_at=activation.updated_at)
    node.allowances.setdefault(USDT, {})[(address, NPM_ADDRESS)] = 0

    class Interrupted(ApprovingExecutor):
        def evaluate(self, activation, *, reader=None):
            raise KeyboardInterrupt("stop after reconciliation")

    register("rebalancing", Interrupted())
    with pytest.raises(KeyboardInterrupt):
        tick.run_once(store, rpc=NodeRpc(node), environment=sessions_key)

    stored = store.get_activation(aid)
    assert stored.session["spent_atomic"][USDT] == str(300 * 10**18)
    assert stored.session["reserved_atomic"] == {}


def test_a_mined_approval_is_identifiable_if_the_pass_dies_before_its_receipt(
    tmp_path, sessions_key, monkeypatch
):
    from tests.fakenode import Node

    monkeypatch.setattr("docket.sessions.executor.RECEIPT_PAUSE_S", 0)
    store = Store(tmp_path / "tick.sqlite3")
    node = Node(estimate=60_000)
    policy = {
        **POLICY,
        "per_action_limit_atomic": {
            **POLICY["per_action_limit_atomic"],
            USDT: str(300 * 10**18),
        },
    }
    _, activation = _node_active(store, node, policy=policy)
    register("rebalancing", ApprovingExecutor(amount=300 * 10**18))

    def mine_then_die(current):
        current.on_receipt = None
        current.mine()
        raise KeyboardInterrupt("stop after mining")

    node.on_receipt = mine_then_die
    with pytest.raises(KeyboardInterrupt):
        tick.run_once(store, rpc=NodeRpc(node), environment=sessions_key)

    stored = store.get_activation(activation.activation_id)
    pending = next(iter(stored.result["pending_sends"].values()))
    assert pending["approval_token"] == USDT
    assert pending["approval_spender"] == NPM_ADDRESS
    assert pending["approval_amount"] == str(300 * 10**18)
    assert stored.session["reserved_atomic"][USDT][NPM_ADDRESS] == str(300 * 10**18)


def test_an_approval_to_a_stranger_is_never_broadcast(
    tmp_path, sessions_key, monkeypatch
):
    from tests.fakenode import Node

    monkeypatch.setattr("docket.sessions.executor.RECEIPT_PAUSE_S", 0)
    store = Store(tmp_path / "tick.sqlite3")
    node = Node(estimate=60_000)
    node.automine_on_receipt = True
    _, activation = _node_active(store, node)
    register("rebalancing", ApprovingExecutor(spender=ATTACKER, amount=10**18))

    assert tick.run_once(store, rpc=NodeRpc(node), environment=sessions_key) == 1

    stored = store.get_activation(activation.activation_id)
    assert node.mined_order == []
    assert node.allowances == {}
    assert any("unmeasured spend" in e.reason for e in stored.events)


def test_closing_zeroes_the_allowance_before_it_can_be_called_revoked(
    tmp_path, sessions_key, monkeypatch
):
    from tests.fakenode import Node

    monkeypatch.setattr("docket.sessions.executor.RECEIPT_PAUSE_S", 0)
    monkeypatch.setattr("docket.sessions.sweep.RECEIPT_PAUSE_S", 0)
    store = Store(tmp_path / "tick.sqlite3")
    node = Node(estimate=60_000)
    node.automine_on_receipt = True
    service, activation = _node_active(store, node, usdt=0, bnb=5 * 10**16)
    aid = activation.activation_id
    register("rebalancing", ApprovingExecutor(amount=100 * 10**18))

    assert tick.run_once(store, rpc=NodeRpc(node), environment=sessions_key) == 0
    address = store.get_activation(aid).session["address"]
    assert node.allowances[USDT][(address, NPM_ADDRESS)] == 100 * 10**18

    service.revoke(aid)
    for _ in range(4):
        tick.run_once(store, rpc=NodeRpc(node), environment=sessions_key)
        node.mine()

    assert node.allowances[USDT][(address, NPM_ADDRESS)] == 0
    assert store.get_activation(aid).state == "revoked"


def test_a_pass_stops_starting_new_activations_once_its_budget_is_gone(
    tmp_path, sessions_key, monkeypatch
):
    """One activation can hold a pass for about thirteen minutes, so the queue behind it
    has no wall-clock bound. The pass picks its own stopping point, between activations
    rather than inside a batch."""
    from tests.fakenode import Node

    store = Store(tmp_path / "tick.sqlite3")
    node = Node()
    for _ in range(3):
        _node_active(store, node)
    register("rebalancing", NoopExecutor("rebalancing"))

    clock = iter([0.0, 0.0, 10**9, 10**9])
    monkeypatch.setattr(tick.time, "monotonic", lambda: next(clock))

    assert tick.run_once(store, rpc=NodeRpc(node), environment=sessions_key) == 0

    # Only the first was started; the other two wait for the next timer.
    evaluated = [
        row
        for row in store.list_activations(state="active", limit=10)
        if (row.result or {}).get("last_decision")
    ]
    assert len(evaluated) == 1


def test_spend_already_checkpointed_by_this_pass_is_not_merged_a_second_time(
    tmp_path, sessions_key
):
    """The delta a stale merge adds is what is not yet saved, not the whole pass.

    `execute` persists before every broadcast, so by the final write part of this pass's
    spend is already on the row. A baseline frozen at the start of the pass would offer
    that part to the merge a second time, and the durable total would overstate what the
    session had spent — never a cap bypass, but a session disabled long before it had
    spent its float. Two swaps of ten each must read as twenty however the writes raced."""
    store = Store(tmp_path / "tick.sqlite3")
    rpc = SendingRpc()
    _, activation = _active(store, rpc)
    register("rebalancing", ActionExecutor(calls=2))

    saves = {"n": 0}
    real_save = store.save_activation

    def racing_save(row, *, expected_updated_at):
        # Two calls write five times: a pending record and a hash for each, then the
        # settled batch. The last one carries the whole pass's spend, and it is the one
        # raced here — by which point the first call's spend is already on the row.
        saves["n"] += 1
        if saves["n"] == 5:
            other = store.get_activation(row.activation_id)
            other.note("another writer got here first", actor="user")
            real_save(other, expected_updated_at=expected_updated_at)
        return real_save(row, expected_updated_at=expected_updated_at)

    store.save_activation = racing_save
    tick.run_once(store, rpc=rpc, environment=sessions_key)
    store.save_activation = real_save

    stored = store.get_activation(activation.activation_id)
    assert len(rpc.sent) == 2
    assert any("merged onto its record" in event.reason for event in stored.events)
    assert stored.session["spent_atomic"][USDT] == str(20 * 10**18)


def test_two_writes_inside_one_microsecond_cannot_both_win(tmp_path):
    """The compare-and-swap is a timestamp, so the timestamp has to move.

    Two writers reading the same row and mutating it within one clock tick used to hold
    the same `updated_at`, which made them indistinguishable to the guard: the second
    write matched the row the first had already changed and silently discarded it. The
    stored stamp is now forced past the one it replaced, so the second writer is refused
    and takes the merge path that keeps both records."""
    store = Store(tmp_path / "tick.sqlite3")
    _, activation = _active(store, FakeRpc())
    expected = activation.updated_at

    first = store.get_activation(activation.activation_id)
    second = store.get_activation(activation.activation_id)

    # Both mutate without the clock advancing between them.
    frozen = first.updated_at
    first.note("first writer", actor="docket", at=frozen)
    second.note("second writer", actor="docket", at=frozen)

    store.save_activation(first, expected_updated_at=expected)
    assert first.updated_at > expected

    with pytest.raises(StaleActivation):
        store.save_activation(second, expected_updated_at=expected)

    kept = store.get_activation(activation.activation_id)
    assert [event.reason for event in kept.events][-1] == "first writer"


def test_a_stamp_this_module_did_not_write_is_replaced_rather_than_kept(tmp_path):
    """The concurrency token is the store's, not the caller's.

    `at=` lets a caller supply its own stamp, and nothing promises that string is a
    timestamp — or that it carries a timezone, which is enough to make it incomparable
    with one that does. A value that cannot be ordered cannot be reasoned about, and
    leaving one on the row invites the shape this guard exists to stop: the same value
    coming back around for a writer still holding it to match a second time. So the row
    takes a stamp this module made, and stays parseable and monotonic whatever a caller
    passes."""
    store = Store(tmp_path / "tick.sqlite3")
    _, activation = _active(store, FakeRpc())

    for supplied in ("the-clock-said-so", "2026-01-01T00:00:00"):
        row = store.get_activation(activation.activation_id)
        held = row.updated_at
        # A distinct reason each time: identical consecutive notes are dropped, and a
        # dropped note would leave `updated_at` untouched and prove nothing. `at=` is not
        # a test-only affordance — `service.py` passes its own injectable clock through
        # it on every transition, so these are the shapes production can really produce.
        row.note(f"a caller supplied {supplied}", actor="user", at=supplied)
        store.save_activation(row, expected_updated_at=held)

        stored = store.get_activation(activation.activation_id)
        assert stored.updated_at != supplied
        # Parseable, timezone-aware, and after the value it replaced.
        assert datetime.fromisoformat(stored.updated_at) > datetime.fromisoformat(held)

        stale = store.get_activation(activation.activation_id)
        stale.updated_at = held
        with pytest.raises(StaleActivation):
            store.save_activation(stale, expected_updated_at=held)


def test_a_replaced_stamp_never_moves_the_row_backwards(tmp_path):
    """Callers pass their own clock, and a clock can be frozen or wrong.

    When a stamp cannot be ordered the row takes a different one, but reaching for the
    wall clock alone would not do: a caller whose clock runs ahead leaves the row on a
    future value, and replacing that with the real time now would move the row *behind*
    a value a reader may still hold — which is exactly how a stale write gets to match a
    second time. The replacement is whichever of the two is later, so the column only
    ever moves forwards."""
    store = Store(tmp_path / "tick.sqlite3")
    _, activation = _active(store, FakeRpc())

    ahead = "2099-01-01T00:00:00+00:00"
    row = store.get_activation(activation.activation_id)
    held = row.updated_at
    row.note("a clock that runs ahead", actor="user", at=ahead)
    store.save_activation(row, expected_updated_at=held)
    assert store.get_activation(activation.activation_id).updated_at == ahead

    # Now an unorderable stamp arrives while the row sits in the future.
    row = store.get_activation(activation.activation_id)
    row.note("a stamp that is not a time", actor="user", at="the-clock-said-so")
    store.save_activation(row, expected_updated_at=ahead)

    stored = store.get_activation(activation.activation_id).updated_at
    assert datetime.fromisoformat(stored) > datetime.fromisoformat(ahead)

    stale = store.get_activation(activation.activation_id)
    stale.updated_at = ahead
    with pytest.raises(StaleActivation):
        store.save_activation(stale, expected_updated_at=ahead)
