"""The activation state machine end to end, and the store underneath it.

Nothing here reaches a network. The catalogue service is a real `Service` with its `run`
replaced, so the schema validation, the category lookup and the receipt hashing are the
shipped ones; only the work itself is stubbed.
"""

from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest
from web3 import Web3

from docket.hire.catalogue import SERVICES, PaidStockAdmission, get_service
from docket.hire.receipts import canonical_hash
from docket.jobs.models import IllegalTransition
from docket.jobs.service import (
    APPROVAL_TOPIC,
    TRANSFER_TOPIC,
    ActivationExpired,
    ActivationNotFound,
    ActivationService,
    MissingFields,
    PolicyViolation,
    SessionsUnavailable,
    SimulationFailed,
    UnknownService,
)
from docket.sessions.policy import NATIVE_TOKEN
from docket.store import StaleActivation, Store

OWNER = Web3.to_checksum_address("0x451871a1753903fb8fdd64a6b838e95ab8d5b80f")
STRANGER = Web3.to_checksum_address("0x0000000000000000000000000000000000009999")
ROUTER = Web3.to_checksum_address("0x10ED43C718714eb63d5aA57B78B54704E256024E")
NFPM = Web3.to_checksum_address("0x46A15B0b27311cedF172AB29E4f4766fbE7F4364")
USDT = Web3.to_checksum_address("0x55d398326f99059fF775485246999027B3197955")
PAY_TO = Web3.to_checksum_address("0xe55816904796341bf8535e25f6c8b647927fc946")
PASSWORD = "a-test-master-password"
FAR_FUTURE = "2099-01-01T00:00:00+00:00"

POLICY = {
    "contract_allowlist": [ROUTER, NFPM],
    "function_allowlist": ["0x38ed1739"],
    "token_allowlist": [USDT, NATIVE_TOKEN],
    "per_action_limit_atomic": {
        USDT: "100000000000000000000",
        NATIVE_TOKEN: "10000000000000000",
    },
    "total_cap_atomic": {
        USDT: "500000000000000000000",
        NATIVE_TOKEN: "100000000000000000",
    },
    "max_slippage_bps": 100,
    "max_gas_price_wei": "5000000000",
    "expires_at": FAR_FUTURE,
    "emergency_pause": False,
}


class FakeEth:
    def __init__(self):
        self.receipts = {}

    def get_transaction_receipt(self, tx_hash):
        return self.receipts.get(tx_hash)

    def gas_price_property(self):
        return 10**9

    @property
    def gas_price(self):
        return 10**9

    def get_transaction_count(self, address):
        return 0

    def get_balance(self, address):
        return 0

    def contract(self, address=None, abi=None):
        return FakeContract()

    def estimate_gas(self, transaction):
        return 60_000

    def send_raw_transaction(self, raw):
        return "0x" + "ab" * 32


class FakeContract:
    def __init__(self):
        self.functions = self

    def balanceOf(self, account):  # noqa: N802 - the ERC-20 name
        return FakeCall(0)


class FakeCall:
    def __init__(self, value):
        self.value = value

    def call(self):
        return self.value


class FakeW3:
    def __init__(self):
        self.eth = FakeEth()


class FakeRpc:
    def __init__(self):
        self.w3 = FakeW3()

    def __call__(self, do):
        return do(self.w3)


def _topic(address: str) -> str:
    return "0x" + "00" * 12 + address.removeprefix("0x").lower()


def _transfer_receipt(session_address, *, token=USDT, amount=500 * 10**18, status=1):
    return {
        "status": status,
        "gasUsed": 51_000,
        "blockNumber": 100,
        "logs": [
            {
                "address": token,
                "topics": [TRANSFER_TOPIC, _topic(OWNER), _topic(session_address)],
                "data": "0x" + f"{amount:064x}",
            }
        ],
    }


def _approval_receipt(session_address, *, contract=NFPM, token_id=7141050):
    return {
        "status": 1,
        "gasUsed": 51_000,
        "blockNumber": 101,
        "logs": [
            {
                "address": contract,
                "topics": [
                    APPROVAL_TOPIC,
                    _topic(OWNER),
                    _topic(session_address),
                    "0x" + f"{token_id:064x}",
                ],
                "data": "0x",
            }
        ],
    }


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / "activations.sqlite3")


def _service(store, *, run=None, paid=False, pay_to=None, rpc=None, services=None):
    if services is None:
        base = get_service("range-doctor")
        services = {
            "range-doctor": replace(
                base,
                run=(lambda payload: {"summary": "read the position"})
                if run is None
                else run,
                admission=PaidStockAdmission(True, True, True, True)
                if paid
                else base.admission,
            )
        }
    return ActivationService(
        store,
        services=services,
        rpc=rpc,
        pay_to=pay_to,
        master_password=PASSWORD,
    )


def _settled_payment(store, *, inputs, service_id="range-doctor", payer=OWNER):
    nonce = "0x" + "05" * 32
    payment_id = "pay_" + "0" * 8
    store.reserve_payment(
        nonce=nonce,
        payment_id=payment_id,
        service_id=service_id,
        payer=payer,
        recipient=PAY_TO,
        asset=USDT,
        amount="500000000000000000",
        resource="http://testserver/hire/range-doctor",
        input_hash=canonical_hash(inputs),
    )
    result = {"summary": "the paid read"}
    store.record_payment_output(
        payment_id, output_hash=canonical_hash(result), result=result
    )
    store.begin_payment_settlement(payment_id)
    store.finish_payment(
        payment_id,
        transaction_id="0x" + "cd" * 32,
        network="eip155:56",
        receipt={
            "service": service_id,
            "input_hash": canonical_hash(inputs),
            "output_hash": canonical_hash(result),
            "delivered_at": "2026-09-03T00:00:00+00:00",
            "payment": {"status": "settled"},
        },
    )
    return payment_id, result


# -- quoting ------------------------------------------------------------------


def test_a_free_tier_quote_names_no_recipient_and_charges_nothing(store):
    activation = _service(store).quote(
        "range-doctor", "one_shot", OWNER, {"wallet": OWNER}, None
    )

    assert activation.state == "quoted"
    assert activation.category == "rebalancing"
    assert activation.quote.payment_scheme == "free_tier"
    assert activation.quote.amount_atomic == "0"
    assert activation.quote.pay_to is None
    assert activation.next_action.kind == "connect_wallet"


def test_a_paid_one_shot_quote_carries_the_price_and_the_recipient(store):
    activation = _service(store, paid=True, pay_to=PAY_TO).quote(
        "range-doctor", "one_shot", OWNER, {"wallet": OWNER}, None
    )

    assert activation.quote.payment_scheme == "x402-exact"
    assert activation.quote.amount_atomic == "500000000000000000"
    assert activation.quote.pay_to == PAY_TO


def test_a_persistent_activation_is_quoted_free_because_no_rail_charges_for_one(store):
    """x402 settles one request against one authorization. Quoting a standing session a
    price nothing in this build collects would be a figure with no rail behind it."""
    activation = _service(store, paid=True, pay_to=PAY_TO).quote(
        "range-doctor", "persistent", OWNER, {"wallet": OWNER}, POLICY
    )

    assert activation.quote.payment_scheme == "free_tier"
    assert activation.expires_at == FAR_FUTURE


def test_a_service_docket_declares_no_category_for_cannot_be_activated(store):
    """`solvent-signal` and `warden-scan` carry no category, and the activation model has
    only BNB's four. Filing one of them under a category it does not stand in would be
    exactly the overstatement `/categories` refuses to make."""
    service = ActivationService(
        store, services=SERVICES, rpc=None, master_password=PASSWORD
    )

    with pytest.raises(UnknownService):
        service.quote("solvent-signal", "one_shot", OWNER, {}, None)
    with pytest.raises(UnknownService):
        service.quote("no-such-service", "one_shot", OWNER, {}, None)


def test_a_request_missing_a_required_input_names_the_field(store):
    with pytest.raises(MissingFields) as raised:
        _service(store).quote("range-doctor", "one_shot", OWNER, {}, None)

    assert raised.value.fields == ["wallet"]


def test_a_persistent_activation_without_a_policy_is_refused(store):
    with pytest.raises(PolicyViolation, match="cannot exist without a"):
        _service(store).quote(
            "range-doctor", "persistent", OWNER, {"wallet": OWNER}, None
        )


def test_a_one_shot_activation_with_a_policy_is_refused(store):
    with pytest.raises(PolicyViolation, match="would bound nothing"):
        _service(store).quote(
            "range-doctor", "one_shot", OWNER, {"wallet": OWNER}, POLICY
        )


def test_an_invalid_policy_is_refused_at_create_time(store):
    with pytest.raises(ValueError, match="naming no contract"):
        _service(store).quote(
            "range-doctor",
            "persistent",
            OWNER,
            {"wallet": OWNER},
            {**POLICY, "contract_allowlist": []},
        )


# -- one-shot -----------------------------------------------------------------


def test_create_walks_to_authorized_and_records_both_steps(store):
    activation = _service(store).create(
        "range-doctor", kind="one_shot", owner=OWNER, inputs={"wallet": OWNER}
    )

    assert activation.state == "authorized"
    assert [event.to_state for event in activation.events] == [
        "awaiting_wallet",
        "authorized",
    ]
    assert [event.actor for event in activation.events] == ["user", "docket"]
    assert store.get_activation(activation.activation_id).state == "authorized"


def test_a_free_tier_approve_runs_the_service_and_binds_the_result_to_the_input(store):
    service = _service(store, run=lambda payload: {"wallet": payload["wallet"]})
    created = service.create(
        "range-doctor", kind="one_shot", owner=OWNER, inputs={"wallet": OWNER}
    )

    activation = service.approve(created.activation_id)

    assert activation.state == "completed"
    assert activation.result == {"wallet": OWNER}
    assert [event.to_state for event in activation.events[2:]] == [
        "paid_or_reserved",
        "queued",
        "running",
        "completed",
    ]
    receipt = activation.receipts[0]
    assert receipt.input_hash == canonical_hash({"wallet": OWNER})
    assert receipt.output_hash == canonical_hash({"wallet": OWNER})
    assert receipt.payment is None
    assert activation.next_action.kind == "none"


def test_a_service_that_raises_fails_the_activation_and_records_why(store):
    def explode(payload):
        raise RuntimeError("the RPC would not answer")

    service = _service(store, run=explode)
    created = service.create(
        "range-doctor", kind="one_shot", owner=OWNER, inputs={"wallet": OWNER}
    )

    activation = service.approve(created.activation_id)

    assert activation.state == "failed"
    assert activation.result is None
    assert "RuntimeError: the RPC would not answer" in activation.events[-1].reason


def test_a_completed_activation_cannot_be_changed_again(store):
    service = _service(store)
    created = service.create(
        "range-doctor", kind="one_shot", owner=OWNER, inputs={"wallet": OWNER}
    )
    service.approve(created.activation_id)

    with pytest.raises(IllegalTransition, match="cannot be changed further"):
        service.approve(created.activation_id)


def test_a_one_shot_cancel_is_a_refund_that_says_nothing_was_charged(store):
    service = _service(store)
    created = service.create(
        "range-doctor", kind="one_shot", owner=OWNER, inputs={"wallet": OWNER}
    )

    activation = service.cancel(created.activation_id)

    assert activation.state == "refunded"
    assert "nothing is owed" in activation.events[-1].reason


def test_a_one_shot_cannot_be_paused_or_revoked(store):
    service = _service(store)
    created = service.create(
        "range-doctor", kind="one_shot", owner=OWNER, inputs={"wallet": OWNER}
    )

    with pytest.raises(IllegalTransition):
        service.pause(created.activation_id)
    with pytest.raises(IllegalTransition):
        service.revoke(created.activation_id)


def test_an_unknown_activation_is_not_found(store):
    with pytest.raises(ActivationNotFound):
        _service(store).approve("act_000000000000000000000000")


# -- the paid tier ------------------------------------------------------------


def test_a_settled_payment_binds_and_delivers_its_stored_result(store):
    inputs = {"wallet": OWNER}
    payment_id, result = _settled_payment(store, inputs=inputs)
    service = _service(store, paid=True, pay_to=PAY_TO)
    created = service.create(
        "range-doctor", kind="one_shot", owner=OWNER, inputs=inputs
    )
    assert created.next_action.kind == "sign_payment"

    activation = service.approve(created.activation_id, payment_id=payment_id)

    assert activation.state == "completed"
    assert activation.result == result
    assert activation.receipts[0].payment == {"status": "settled"}


def test_a_payment_bound_to_different_work_is_a_policy_violation(store):
    payment_id, _ = _settled_payment(store, inputs={"wallet": OWNER, "limit": 3})
    service = _service(store, paid=True, pay_to=PAY_TO)
    created = service.create(
        "range-doctor", kind="one_shot", owner=OWNER, inputs={"wallet": OWNER}
    )

    with pytest.raises(PolicyViolation, match="bound to a different request body"):
        service.approve(created.activation_id, payment_id=payment_id)

    assert store.get_activation(created.activation_id).state == "authorized"


def test_a_payment_made_by_somebody_else_is_a_policy_violation(store):
    inputs = {"wallet": OWNER}
    payment_id, _ = _settled_payment(store, inputs=inputs, payer=STRANGER)
    service = _service(store, paid=True, pay_to=PAY_TO)
    created = service.create(
        "range-doctor", kind="one_shot", owner=OWNER, inputs=inputs
    )

    with pytest.raises(PolicyViolation, match="was made by"):
        service.approve(created.activation_id, payment_id=payment_id)


def test_an_unsettled_or_missing_payment_is_a_policy_violation(store):
    inputs = {"wallet": OWNER}
    service = _service(store, paid=True, pay_to=PAY_TO)
    created = service.create(
        "range-doctor", kind="one_shot", owner=OWNER, inputs=inputs
    )

    with pytest.raises(PolicyViolation, match="no payment"):
        service.approve(created.activation_id, payment_id="pay_nothing")
    with pytest.raises(PolicyViolation, match="needs the payment_id"):
        service.approve(created.activation_id)

    store.reserve_payment(
        nonce="0x" + "06" * 32,
        payment_id="pay_open",
        service_id="range-doctor",
        payer=OWNER,
        recipient=PAY_TO,
        asset=USDT,
        amount="500000000000000000",
        resource="r",
        input_hash=canonical_hash(inputs),
    )
    with pytest.raises(PolicyViolation, match="is verified, not settled"):
        service.approve(created.activation_id, payment_id="pay_open")


# -- persistent ---------------------------------------------------------------


def _persistent(store, rpc=None):
    service = _service(store, rpc=rpc)
    created = service.create(
        "range-doctor",
        kind="persistent",
        owner=OWNER,
        inputs={"wallet": OWNER},
        policy=POLICY,
    )
    return service, created


def test_a_persistent_create_makes_a_session_key_and_keeps_the_keystore_out_of_it(
    store,
):
    service, created = _persistent(store)

    row = store.get_session(created.activation_id)
    assert row["address"] == created.session["address"]
    assert row["revoked_at"] is None
    assert "keystore" not in created.to_dict()["session"]
    assert set(created.to_dict()["session"]) == {
        "address",
        "funded_atomic",
        "spent_atomic",
    }
    assert created.next_action.kind == "fund_session"
    assert [item["token"] for item in created.next_action.detail["requirements"]] == [
        USDT
    ]


def test_the_native_gas_allowance_is_not_a_funding_requirement(store):
    """BNB is capped like every other token, but it is sent as the gas allowance the
    next_action already names rather than as a transfer with a Transfer log to match."""
    _, created = _persistent(store)

    assert created.next_action.detail["gas_allowance_wei"] == "10000000000000000"
    assert all(
        item["token"] != NATIVE_TOKEN
        for item in created.next_action.detail["requirements"]
    )


def test_no_master_password_refuses_a_persistent_activation_outright(store, tmp_path):
    service = ActivationService(
        store, services={"range-doctor": get_service("range-doctor")}, environment={}
    )

    with pytest.raises(SessionsUnavailable):
        service.create(
            "range-doctor",
            kind="persistent",
            owner=OWNER,
            inputs={"wallet": OWNER},
            policy=POLICY,
        )
    assert store.count_activations() == 0


def test_a_matching_funding_transfer_moves_the_session_to_active(store):
    rpc = FakeRpc()
    service, created = _persistent(store, rpc=rpc)
    tx_hash = "0x" + "11" * 32
    rpc.w3.eth.receipts[tx_hash] = _transfer_receipt(created.session["address"])

    activation = service.approve(created.activation_id, tx_hash=tx_hash)

    assert activation.state == "active"
    assert [event.to_state for event in activation.events[-2:]] == ["funded", "active"]
    assert activation.session["funded_atomic"] == {USDT: "500000000000000000000"}
    assert activation.next_action.kind == "wait"


def test_a_transaction_that_did_not_succeed_funds_nothing(store):
    rpc = FakeRpc()
    service, created = _persistent(store, rpc=rpc)
    tx_hash = "0x" + "12" * 32
    rpc.w3.eth.receipts[tx_hash] = _transfer_receipt(
        created.session["address"], status=0
    )

    with pytest.raises(PolicyViolation, match="did not succeed on chain"):
        service.approve(created.activation_id, tx_hash=tx_hash)

    assert store.get_activation(created.activation_id).state == "authorized"


def test_a_transfer_to_somebody_else_or_short_of_the_cap_funds_nothing(store):
    rpc = FakeRpc()
    service, created = _persistent(store, rpc=rpc)
    wrong_recipient = "0x" + "13" * 32
    rpc.w3.eth.receipts[wrong_recipient] = _transfer_receipt(STRANGER)
    short = "0x" + "14" * 32
    rpc.w3.eth.receipts[short] = _transfer_receipt(
        created.session["address"], amount=10**18
    )
    wrong_token = "0x" + "15" * 32
    rpc.w3.eth.receipts[wrong_token] = _transfer_receipt(
        created.session["address"], token=ROUTER
    )

    for tx_hash in (wrong_recipient, short, wrong_token):
        with pytest.raises(PolicyViolation, match="carries no log matching"):
            service.approve(created.activation_id, tx_hash=tx_hash)

    assert store.get_activation(created.activation_id).state == "authorized"


def test_a_transaction_the_chain_has_not_mined_is_refused_rather_than_a_crash(store):
    """The ordinary case: an owner approves a second after sending. web3 raises for a hash
    with no receipt, and `escrow.chain.Rpc` would turn that into a retry storm and a
    RuntimeError no route can translate — so it is caught and named here instead."""

    class UnminedRpc(FakeRpc):
        def __init__(self):
            super().__init__()
            self.w3.eth.get_transaction_receipt = self._raise

        def _raise(self, tx_hash):
            raise ValueError({"code": -32000, "message": "transaction not found"})

    service, created = _persistent(store, rpc=UnminedRpc())

    with pytest.raises(PolicyViolation, match="not mined yet, or no node answered"):
        service.approve(created.activation_id, tx_hash="0x" + "99" * 32)

    assert store.get_activation(created.activation_id).state == "authorized"


def test_a_transaction_with_no_receipt_at_all_is_refused(store):
    service, created = _persistent(store, rpc=FakeRpc())

    with pytest.raises(PolicyViolation, match="has no receipt on chain"):
        service.approve(created.activation_id, tx_hash="0x" + "98" * 32)

    assert store.get_activation(created.activation_id).state == "authorized"


def test_approving_a_persistent_activation_with_no_transaction_is_refused(store):
    service, created = _persistent(store, rpc=FakeRpc())

    with pytest.raises(PolicyViolation, match="only against a mined"):
        service.approve(created.activation_id)


def test_an_nft_approval_requirement_is_matched_by_its_own_erc721_log(store):
    rpc = FakeRpc()
    service = _service(store, rpc=rpc)
    created = service.create(
        "range-doctor",
        kind="persistent",
        owner=OWNER,
        inputs={"wallet": OWNER},
        policy=POLICY,
        nft_approvals=({"contract": NFPM, "token_id": 7141050},),
    )
    assert len(created.next_action.detail["requirements"]) == 2

    funding = "0x" + "21" * 32
    rpc.w3.eth.receipts[funding] = _transfer_receipt(created.session["address"])
    partly = service.approve(created.activation_id, tx_hash=funding)
    assert partly.state == "authorized"
    assert partly.next_action.kind == "approve_nft"

    approval = "0x" + "22" * 32
    rpc.w3.eth.receipts[approval] = _approval_receipt(created.session["address"])
    activation = service.approve(created.activation_id, tx_hash=approval)

    assert activation.state == "active"


def test_an_nft_approval_outside_the_contract_allowlist_is_refused(store):
    service = _service(store, rpc=FakeRpc())

    with pytest.raises(PolicyViolation, match="not in the policy's contract allowlist"):
        service.create(
            "range-doctor",
            kind="persistent",
            owner=OWNER,
            inputs={"wallet": OWNER},
            policy=POLICY,
            nft_approvals=({"contract": USDT, "token_id": 1},),
        )


def test_pause_stops_the_session_and_approve_resumes_it(store):
    rpc = FakeRpc()
    service, created = _persistent(store, rpc=rpc)
    tx_hash = "0x" + "31" * 32
    rpc.w3.eth.receipts[tx_hash] = _transfer_receipt(created.session["address"])
    service.approve(created.activation_id, tx_hash=tx_hash)

    paused = service.pause(created.activation_id)
    assert paused.state == "paused"

    resumed = service.approve(created.activation_id)
    assert resumed.state == "active"
    assert "resumed the session" in resumed.events[-1].reason


def test_revoke_sweeps_the_session_and_closes_the_key(store):
    rpc = FakeRpc()
    service, created = _persistent(store, rpc=rpc)

    activation = service.revoke(created.activation_id)

    assert activation.state == "revoked"
    assert store.get_session(created.activation_id)["revoked_at"] is not None


def test_cancelling_a_persistent_activation_revokes_it(store):
    service, created = _persistent(store, rpc=FakeRpc())

    activation = service.cancel(created.activation_id)

    assert activation.state == "revoked"


def test_a_sweep_that_fails_is_recorded_and_does_not_block_the_revocation(store):
    class BrokenRpc(FakeRpc):
        def __call__(self, do):
            raise RuntimeError("every endpoint failed")

    service, created = _persistent(store, rpc=BrokenRpc())

    activation = service.revoke(created.activation_id)

    assert activation.state == "revoked"
    assert any("could not be swept" in event.reason for event in activation.events)


def test_an_expired_policy_closes_the_activation_and_refuses_the_call(store):
    past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    service = _service(store, rpc=FakeRpc())
    created = service.create(
        "range-doctor",
        kind="persistent",
        owner=OWNER,
        inputs={"wallet": OWNER},
        policy={**POLICY, "expires_at": past},
    )

    with pytest.raises(ActivationExpired):
        service.pause(created.activation_id)

    stored = store.get_activation(created.activation_id)
    assert stored.state == "expired"
    assert stored.next_action.kind == "none"


# -- prepared calls -----------------------------------------------------------


def _needs_approval(store, simulation):
    rpc = FakeRpc()
    service, created = _persistent(store, rpc=rpc)
    tx_hash = "0x" + "41" * 32
    rpc.w3.eth.receipts[tx_hash] = _transfer_receipt(created.session["address"])
    service.approve(created.activation_id, tx_hash=tx_hash)
    activation = store.get_activation(created.activation_id)
    expected = activation.updated_at
    activation.transition(
        "needs_approval", reason="the owner must sign this", actor="docket"
    )
    from docket.jobs.models import NextAction

    activation.next_action = NextAction(
        "sign_transaction",
        {
            "purpose": "recenter",
            "calls": [
                {
                    "to": ROUTER,
                    "data": "0x38ed1739" + "00" * 32,
                    "value_atomic": "0",
                    "chain_id": 56,
                    "gas_ceiling": 300_000,
                    "deadline": 4_102_444_800,
                    "purpose": "recenter",
                    "simulation": simulation,
                }
            ],
        },
    )
    store.save_activation(activation, expected_updated_at=expected)
    return service, created


def test_prepared_calls_are_served_when_the_chain_agreed_to_them(store):
    service, created = _needs_approval(store, {"ok": True, "gas_estimate": 180_000})

    calls = service.prepared_calls(created.activation_id)

    assert len(calls) == 1
    assert calls[0].selector == "0x38ed1739"
    assert calls[0].chain_id == 56


def test_a_call_the_chain_refused_is_never_handed_over_to_be_signed(store):
    service, created = _needs_approval(
        store, {"ok": False, "revert_reason": "INSUFFICIENT_OUTPUT_AMOUNT"}
    )

    with pytest.raises(SimulationFailed, match="INSUFFICIENT_OUTPUT_AMOUNT"):
        service.prepared_calls(created.activation_id)


def test_an_owner_signed_action_returns_the_session_to_active(store):
    service, created = _needs_approval(store, {"ok": True, "gas_estimate": 180_000})
    tx_hash = "0x" + "51" * 32
    service.rpc.w3.eth.receipts[tx_hash] = {
        "status": 1,
        "gasUsed": 210_000,
        "blockNumber": 200,
        "logs": [],
    }

    activation = service.approve(created.activation_id, tx_hash=tx_hash)

    assert activation.state == "active"
    assert activation.receipts[-1].execution["signed_by"] == "owner"
    assert activation.receipts[-1].execution["gas_used"] == 210_000


def test_an_owner_signed_action_that_reverted_leaves_the_activation_waiting(store):
    service, created = _needs_approval(store, {"ok": True, "gas_estimate": 180_000})
    tx_hash = "0x" + "52" * 32
    service.rpc.w3.eth.receipts[tx_hash] = {
        "status": 0,
        "gasUsed": 210_000,
        "blockNumber": 201,
        "logs": [],
    }

    with pytest.raises(PolicyViolation, match="the action did not happen"):
        service.approve(created.activation_id, tx_hash=tx_hash)

    assert store.get_activation(created.activation_id).state == "needs_approval"


# -- the store underneath -----------------------------------------------------


def test_a_write_against_a_row_that_moved_is_refused(store):
    """Driven by a clock that always advances, because the guard is a timestamp: on a
    coarse system clock two writes can share one, and a test that depended on the
    machine's resolution would pass or fail for reasons that are not this code's."""
    ticks = iter(f"2026-09-03T00:00:{second:02d}+00:00" for second in range(1, 60))
    service = _service(store)
    service.now = lambda: next(ticks)
    created = service.create(
        "range-doctor", kind="one_shot", owner=OWNER, inputs={"wallet": OWNER}
    )
    stale = store.get_activation(created.activation_id)
    service.cancel(created.activation_id)

    stale.transition("refunded", reason="a second writer", actor="user")
    with pytest.raises(StaleActivation):
        store.save_activation(stale, expected_updated_at=created.updated_at)


def test_a_nonce_can_be_rotated_once_and_only_by_whoever_holds_the_current_one(store):
    created = _service(store).create(
        "range-doctor", kind="one_shot", owner=OWNER, inputs={"wallet": OWNER}
    )

    assert store.rotate_auth_nonce(
        created.activation_id, expected_nonce=created.auth_nonce, new_nonce="next"
    )
    assert not store.rotate_auth_nonce(
        created.activation_id, expected_nonce=created.auth_nonce, new_nonce="again"
    )
    assert store.get_activation(created.activation_id).auth_nonce == "next"


def test_rotating_a_nonce_does_not_disturb_the_optimistic_write_it_authorizes(store):
    service = _service(store)
    created = service.create(
        "range-doctor", kind="one_shot", owner=OWNER, inputs={"wallet": OWNER}
    )
    store.rotate_auth_nonce(
        created.activation_id, expected_nonce=created.auth_nonce, new_nonce="next"
    )

    assert store.get_activation(created.activation_id).updated_at == created.updated_at
    assert service.approve(created.activation_id).state == "completed"


def test_a_create_nonce_is_single_use_and_expires(store):
    now = datetime(2026, 9, 3, tzinfo=timezone.utc)
    store.issue_activation_nonce(nonce="n1", owner=OWNER, message="m", now=now)

    assert store.consume_activation_nonce("n1", OWNER, now)
    assert not store.consume_activation_nonce("n1", OWNER, now)

    store.issue_activation_nonce(nonce="n2", owner=OWNER, message="m", now=now)
    assert not store.consume_activation_nonce("n2", STRANGER, now)
    assert not store.consume_activation_nonce("n2", OWNER, now + timedelta(seconds=601))


def test_activations_are_listed_newest_first_and_filtered_by_owner_and_state(store):
    service = _service(store)
    first = service.create(
        "range-doctor", kind="one_shot", owner=OWNER, inputs={"wallet": OWNER}
    )
    second = service.create(
        "range-doctor", kind="one_shot", owner=STRANGER, inputs={"wallet": OWNER}
    )
    service.approve(first.activation_id)

    assert [row.activation_id for row in store.list_activations(owner=OWNER)] == [
        first.activation_id
    ]
    assert [
        row.activation_id for row in store.list_activations(state="authorized")
    ] == [second.activation_id]
    assert store.count_activations() == 2
    assert store.activations_by_state() == {"completed": 1, "authorized": 1}


def test_a_page_outside_its_bounds_is_refused(store):
    with pytest.raises(ValueError, match="page size must be between"):
        store.list_activations(limit=0)
    with pytest.raises(ValueError, match="offset cannot be negative"):
        store.list_activations(offset=-1)


def test_an_activation_id_cannot_be_created_twice(store):
    service = _service(store)
    created = service.create(
        "range-doctor", kind="one_shot", owner=OWNER, inputs={"wallet": OWNER}
    )

    with pytest.raises(ValueError, match="already exists"):
        store.create_activation(created)
