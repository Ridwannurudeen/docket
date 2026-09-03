"""Session keys, the bounds around them, the one function that signs, and the sweep.

No test here touches a network. `FakeRpc` answers the same shape `escrow.chain.Rpc` does
— a callable taking `do(w3)` — so the code under test is the code that ships rather than
a variant written for a mock.
"""

import json
from datetime import datetime, timedelta, timezone

import pytest
from eth_account import Account
from web3 import Web3

from docket.execution.simulate import swap_calldata
from docket.jobs.executors.base import PreparedCall
from docket.jobs.models import (
    Activation,
    NextAction,
    Quote,
    new_activation_id,
)
from docket.sessions.executor import ExecutionFailed, execute
from docket.sessions.keys import (
    Session,
    SessionsUnavailable,
    create_session_key,
    master_password_from_env,
    unlock,
)
from docket.sessions.policy import NATIVE_TOKEN, SessionPolicy
from docket.sessions.spend import (
    UnmeasuredSpend,
    batch_spend,
    call_spend,
    needs_underlying,
)
from docket.sessions.sweep import SweepFailed, sweep

OWNER = "0x451871A1753903FB8fdd64a6B838E95aB8D5B80f"
ROUTER = Web3.to_checksum_address("0x10ED43C718714eb63d5aA57B78B54704E256024E")
USDT = Web3.to_checksum_address("0x55d398326f99059fF775485246999027B3197955")
WBNB = Web3.to_checksum_address("0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c")
SWAP_SELECTOR = "0x38ed1739"
# A distant fixed expiry, so a policy in these tests is live for the same reason in every
# run rather than because the machine clock happens to be where it is.
FAR_FUTURE = "2099-01-01T00:00:00+00:00"


def _policy(**overrides) -> SessionPolicy:
    fields = {
        "contract_allowlist": (ROUTER,),
        "function_allowlist": (SWAP_SELECTOR,),
        "token_allowlist": (USDT, NATIVE_TOKEN),
        "per_action_limit_atomic": {USDT: 100 * 10**18, NATIVE_TOKEN: 10**16},
        "total_cap_atomic": {USDT: 500 * 10**18, NATIVE_TOKEN: 10**17},
        "max_slippage_bps": 100,
        "max_gas_price_wei": 5 * 10**9,
        "expires_at": FAR_FUTURE,
        "emergency_pause": False,
    }
    fields.update(overrides)
    return SessionPolicy(**fields)


def _swap_data(amount_in: int, route=(USDT, WBNB)) -> str:
    """Real router calldata, built by the shipped builder.

    The spend a session is charged is now read out of these bytes, so a fixture carrying
    a selector and thirty-two zeroes would be testing a decoder against something no
    router would ever be sent."""
    return "0x" + swap_calldata(
        amount_in=amount_in,
        min_output=1,
        route=route,
        recipient=OWNER,
        deadline=4_102_444_800,
    ).hex()


def _call(amount_in: int = 10 * 10**18, **overrides) -> PreparedCall:
    fields = {
        "to": ROUTER,
        "data": _swap_data(amount_in),
        "value_atomic": "0",
        "gas_ceiling": 300_000,
        "deadline": 4_102_444_800,
        "purpose": "recenter the position",
        "simulation": {"ok": True, "gas_estimate": 180_000, "block": 1},
    }
    fields.update(overrides)
    return PreparedCall(**fields)


def _activation() -> Activation:
    return Activation(
        activation_id=new_activation_id(),
        service_id="range-doctor",
        category="rebalancing",
        kind="persistent",
        owner=OWNER,
        state="active",
        quote=Quote(USDT, "0", "free", None, "free_tier"),
        policy=_policy().to_dict(),
        session={"address": "0x0", "funded_atomic": {}, "spent_atomic": {}},
        inputs={"wallet": OWNER},
        result=None,
        receipts=(),
        events=(),
        next_action=NextAction("wait"),
        auth_nonce="n",
        created_at="2026-09-03T00:00:00+00:00",
        updated_at="2026-09-03T00:00:00+00:00",
        expires_at=FAR_FUTURE,
    )


class FakeEth:
    """Only the calls `executor.py` and `sweep.py` actually make."""

    def __init__(self, owner):
        self.owner = owner
        self.call_result = b""
        self.call_error = None
        self.gas_estimate = 180_000
        self.estimate_error = None
        self.gas_price = 10**9
        self.transaction_count = 7
        self.send_error = None
        self.receipts = {}
        self.missing_receipt_for = 0
        self.balances = {}
        self.token_balances = {}
        self.sent = []
        self._receipt_attempts = 0

    def call(self, transaction):
        if self.call_error is not None:
            raise self.call_error
        return self.call_result

    def estimate_gas(self, transaction):
        if self.estimate_error is not None:
            raise self.estimate_error
        return self.gas_estimate

    def get_transaction_count(self, address):
        return self.transaction_count

    def send_raw_transaction(self, raw):
        if self.send_error is not None:
            raise self.send_error
        tx_hash = "0x" + f"{len(self.sent) + 1:064x}"
        self.sent.append((tx_hash, bytes(raw)))
        return tx_hash

    def get_transaction_receipt(self, tx_hash):
        if self._receipt_attempts < self.missing_receipt_for:
            self._receipt_attempts += 1
            raise LookupError("not found")
        return self.receipts.get(
            tx_hash, {"status": 1, "gasUsed": 150_000, "blockNumber": 42}
        )

    def get_balance(self, address):
        return self.balances.get(address, 0)

    def contract(self, address=None, abi=None):
        return FakeContract(self, address)


class FakeContract:
    def __init__(self, eth, address):
        self.eth = eth
        self.address = address
        self.functions = self

    def balanceOf(self, account):  # noqa: N802 - the ERC-20 name
        return FakeCall(self.eth.token_balances.get(self.address, 0))


class FakeCall:
    def __init__(self, value):
        self.value = value

    def call(self):
        return self.value


class FakeW3:
    def __init__(self, owner):
        self.eth = FakeEth(owner)


class FakeRpc:
    """The `escrow.chain.Rpc` contract: a callable that runs `do(w3)`."""

    def __init__(self, w3):
        self.w3 = w3

    def __call__(self, do):
        return do(self.w3)


# -- keys ---------------------------------------------------------------------


def test_a_session_key_round_trips_through_its_keystore():
    address, keystore_json = create_session_key("correct horse battery staple")

    keystore = json.loads(keystore_json)
    assert keystore["version"] == 3
    assert "correct horse battery staple" not in keystore_json
    assert unlock(keystore_json, "correct horse battery staple").address == address


def test_the_plaintext_key_is_never_in_what_is_stored():
    address, keystore_json = create_session_key("pw")

    account = unlock(keystore_json, "pw")

    assert account.key.hex() not in keystore_json
    assert account.address == address


def test_a_wrong_password_does_not_quietly_open_the_keystore():
    _, keystore_json = create_session_key("pw")

    with pytest.raises(ValueError):
        unlock(keystore_json, "not the password")


def test_an_absent_key_file_refuses_sessions_and_never_defaults_a_password(tmp_path):
    with pytest.raises(SessionsUnavailable, match="DOCKET_SESSION_KEY_FILE is not set"):
        master_password_from_env({})
    with pytest.raises(SessionsUnavailable, match="could not be read"):
        master_password_from_env(
            {"DOCKET_SESSION_KEY_FILE": str(tmp_path / "absent.key")}
        )
    empty = tmp_path / "empty.key"
    empty.write_text("   \n", encoding="utf-8")
    with pytest.raises(SessionsUnavailable, match="is empty"):
        master_password_from_env({"DOCKET_SESSION_KEY_FILE": str(empty)})


def test_a_present_key_file_is_read_and_stripped(tmp_path):
    key_file = tmp_path / "sessions.key"
    key_file.write_text("  a-real-password\n", encoding="utf-8")

    assert (
        master_password_from_env({"DOCKET_SESSION_KEY_FILE": str(key_file)})
        == "a-real-password"
    )


def test_a_session_key_cannot_be_made_or_opened_with_an_empty_password():
    with pytest.raises(SessionsUnavailable):
        create_session_key("")
    with pytest.raises(SessionsUnavailable):
        unlock("{}", "")


# -- policy -------------------------------------------------------------------


def test_a_policy_that_bounds_nothing_is_refused_rather_than_read_as_permissive():
    for overrides, message in (
        ({"contract_allowlist": ()}, "naming no contract"),
        ({"function_allowlist": ()}, "naming no function"),
        ({"token_allowlist": ()}, "naming no token"),
        ({"per_action_limit_atomic": {}}, "not a bounded one"),
        ({"total_cap_atomic": {}}, "not a bounded one"),
    ):
        with pytest.raises(ValueError, match=message):
            _policy(**overrides).validate()


def test_a_policy_refuses_a_cap_without_its_pair_and_a_limit_above_its_cap():
    with pytest.raises(ValueError, match="has a per-action limit and no"):
        _policy(
            per_action_limit_atomic={USDT: 1, WBNB: 1},
            total_cap_atomic={USDT: 2},
            token_allowlist=(USDT, WBNB),
        ).validate()
    with pytest.raises(ValueError, match="has a total cap and no per-action"):
        _policy(
            per_action_limit_atomic={USDT: 1},
            total_cap_atomic={USDT: 2, WBNB: 2},
            token_allowlist=(USDT, WBNB),
        ).validate()
    with pytest.raises(ValueError, match="in one action against a total cap"):
        _policy(
            per_action_limit_atomic={USDT: 5},
            total_cap_atomic={USDT: 2},
            token_allowlist=(USDT,),
        ).validate()


def test_a_policy_refuses_a_malformed_address_selector_slippage_or_gas_ceiling():
    with pytest.raises(ValueError, match="is not an address"):
        _policy(contract_allowlist=("not-an-address",)).validate()
    with pytest.raises(ValueError, match="is not a 4-byte selector"):
        _policy(function_allowlist=("38ed1739",)).validate()
    with pytest.raises(ValueError, match="max_slippage_bps must be between"):
        _policy(max_slippage_bps=10_001).validate()
    with pytest.raises(ValueError, match="would refuse every transaction"):
        _policy(max_gas_price_wei=0).validate()
    with pytest.raises(ValueError, match="must carry a UTC offset"):
        _policy(expires_at="2099-01-01T00:00:00").validate()


def test_a_capped_token_outside_the_allowlist_is_refused():
    with pytest.raises(ValueError, match="capped but not in token_allowlist"):
        _policy(
            per_action_limit_atomic={WBNB: 1},
            total_cap_atomic={WBNB: 2},
        ).validate()


def test_a_call_inside_every_bound_is_allowed():
    permitted, reason = _policy().allows(
        _call(),
        spent={},
        token_amounts={USDT: 10 * 10**18},
        gas_price_wei=10**9,
        slippage_bps=50,
    )

    assert permitted, reason


def test_each_bound_refuses_on_its_own_and_says_which_one():
    policy = _policy()
    for kwargs, message in (
        (
            {"call": _call(to=WBNB), "token_amounts": {}},
            "is not in the contract allowlist",
        ),
        (
            {"call": _call(data="0xdeadbeef" + "00" * 32), "token_amounts": {}},
            "is not in the function allowlist",
        ),
        (
            {"call": _call(), "token_amounts": {WBNB: 1}},
            "is not in the token allowlist",
        ),
        (
            {"call": _call(), "token_amounts": {USDT: 101 * 10**18}},
            "above the per-action limit",
        ),
        (
            {"call": _call(chain_id=1), "token_amounts": {}},
            "is not BSC mainnet",
        ),
        (
            {"call": _call(), "token_amounts": {}, "gas_price_wei": 6 * 10**9},
            "above the policy ceiling of 5000000000 wei",
        ),
        (
            {"call": _call(), "token_amounts": {}, "slippage_bps": 500},
            "above the policy ceiling of 100 bps",
        ),
    ):
        call = kwargs.pop("call")
        permitted, reason = policy.allows(call, spent={}, **kwargs)

        assert not permitted
        assert message in reason


def test_the_total_cap_counts_what_was_already_spent():
    policy = _policy()

    permitted, reason = policy.allows(
        _call(), spent={USDT: 450 * 10**18}, token_amounts={USDT: 60 * 10**18}
    )

    assert not permitted
    assert "would pass the session cap of 500000000000000000000" in reason


def test_the_native_value_a_call_carries_is_folded_into_the_bnb_caps():
    permitted, reason = _policy().allows(
        _call(value_atomic=str(10**16)), spent={}, token_amounts={}
    )
    assert permitted, reason

    permitted, reason = _policy().allows(
        _call(value_atomic=str(2 * 10**16)), spent={}, token_amounts={}
    )
    assert not permitted
    assert "above the per-action limit" in reason


def test_an_emergency_pause_and_an_expiry_each_refuse_everything():
    permitted, reason = _policy(emergency_pause=True).allows(
        _call(), spent={}, token_amounts={}
    )
    assert not permitted and "emergency-paused" in reason

    past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    permitted, reason = _policy(expires_at=past).allows(
        _call(), spent={}, token_amounts={}
    )
    assert not permitted and "expired at" in reason


def test_a_policy_round_trips_through_json_with_its_atomic_amounts_intact():
    policy = _policy()

    restored = SessionPolicy.from_dict(json.loads(json.dumps(policy.to_dict())))

    assert restored == policy
    assert restored.total_cap_atomic[USDT] == 500 * 10**18


def test_a_policy_missing_a_field_names_the_field():
    payload = _policy().to_dict()
    del payload["max_gas_price_wei"]

    with pytest.raises(ValueError, match="missing max_gas_price_wei"):
        SessionPolicy.from_dict(payload)


# -- executor -----------------------------------------------------------------


def _session(w3=None, spent=None):
    account = Account.create()
    return Session(
        address=account.address,
        account=account,
        funded_atomic={USDT: 500 * 10**18},
        spent_atomic={} if spent is None else spent,
        token_allowlist=(USDT,),
    )


def test_execute_simulates_estimates_signs_sends_and_records_the_receipt():
    w3 = FakeW3(OWNER)
    session = _session()
    activation = _activation()

    receipt = execute(
        activation,
        _call(),
        session=session,
        rpc=FakeRpc(w3),
        policy=_policy(),
        sleep=lambda _: None,
    )

    assert len(w3.eth.sent) == 1
    assert receipt.execution["tx_hash"] == w3.eth.sent[0][0]
    assert receipt.execution["status"] == 1
    assert receipt.execution["gas_used"] == 150_000
    assert receipt.execution["block_number"] == 42
    assert session.spent_atomic == {USDT: 10 * 10**18}
    assert any("succeeded in block 42" in event.reason for event in activation.events)


def test_a_call_that_reverts_in_simulation_is_never_sent():
    w3 = FakeW3(OWNER)
    w3.eth.call_error = RuntimeError("execution reverted: STF")
    activation = _activation()

    with pytest.raises(ExecutionFailed, match="reverted in simulation"):
        execute(
            activation,
            _call(),
            session=_session(),
            rpc=FakeRpc(w3),
            policy=_policy(),
            sleep=lambda _: None,
        )

    assert w3.eth.sent == []
    assert any("reverted in simulation" in event.reason for event in activation.events)


def test_a_call_estimating_above_its_own_ceiling_is_never_sent():
    w3 = FakeW3(OWNER)
    w3.eth.gas_estimate = 400_000

    with pytest.raises(ExecutionFailed, match="above the prepared ceiling"):
        execute(
            _activation(),
            _call(gas_ceiling=300_000),
            session=_session(),
            rpc=FakeRpc(w3),
            policy=_policy(),
            sleep=lambda _: None,
        )

    assert w3.eth.sent == []


def test_a_call_outside_the_policy_is_never_sent_and_the_reason_is_recorded():
    w3 = FakeW3(OWNER)
    activation = _activation()

    with pytest.raises(ExecutionFailed, match="refused by the session policy"):
        execute(
            activation,
            _call(amount_in=200 * 10**18),
            session=_session(),
            rpc=FakeRpc(w3),
            policy=_policy(),
            sleep=lambda _: None,
        )

    assert w3.eth.sent == []
    assert any("per-action limit" in event.reason for event in activation.events)


def test_a_gas_price_above_the_policy_ceiling_is_refused_after_the_chain_reads():
    w3 = FakeW3(OWNER)
    w3.eth.gas_price = 9 * 10**9

    with pytest.raises(ExecutionFailed, match="above the policy ceiling"):
        execute(
            _activation(),
            _call(),
            session=_session(),
            rpc=FakeRpc(w3),
            policy=_policy(),
            sleep=lambda _: None,
        )

    assert w3.eth.sent == []


def test_a_mined_transaction_that_reverted_is_a_failure_and_nothing_is_marked_spent():
    w3 = FakeW3(OWNER)
    w3.eth.receipts = {
        "0x" + f"{1:064x}": {"status": 0, "gasUsed": 21_000, "blockNumber": 43}
    }
    session = _session()
    activation = _activation()

    with pytest.raises(ExecutionFailed, match="reverted on chain"):
        execute(
            activation,
            _call(),
            session=session,
            rpc=FakeRpc(w3),
            policy=_policy(),
            sleep=lambda _: None,
        )

    assert session.spent_atomic == {}
    assert any("and reverted" in event.reason for event in activation.events)


def test_the_receipt_wait_is_bounded_and_a_broadcast_is_not_repeated():
    w3 = FakeW3(OWNER)
    w3.eth.missing_receipt_for = 100
    pauses = []

    with pytest.raises(ExecutionFailed, match="no receipt appeared"):
        execute(
            _activation(),
            _call(),
            session=_session(),
            rpc=FakeRpc(w3),
            policy=_policy(),
            sleep=pauses.append,
        )

    assert len(w3.eth.sent) == 1
    assert len(pauses) == 19


def test_a_receipt_that_appears_late_is_still_accepted():
    w3 = FakeW3(OWNER)
    w3.eth.missing_receipt_for = 3

    receipt = execute(
        _activation(),
        _call(),
        session=_session(),
        rpc=FakeRpc(w3),
        policy=_policy(),
        sleep=lambda _: None,
    )

    assert receipt.execution["status"] == 1


# -- sweep --------------------------------------------------------------------


def test_a_sweep_returns_every_token_balance_and_the_bnb_minus_its_own_gas():
    w3 = FakeW3(OWNER)
    session = _session()
    w3.eth.token_balances[USDT] = 250 * 10**18
    w3.eth.balances[session.address] = 5 * 10**16
    w3.eth.gas_price = 10**9

    sent = sweep(session, OWNER, FakeRpc(w3))

    assert len(sent) == 2
    assert sent == [tx for tx, _ in w3.eth.sent]


def test_a_sweep_leaves_bnb_alone_when_it_cannot_pay_for_its_own_departure():
    w3 = FakeW3(OWNER)
    session = _session()
    w3.eth.token_balances[USDT] = 0
    w3.eth.gas_price = 10**9
    w3.eth.balances[session.address] = 21_000 * 10**9

    assert sweep(session, OWNER, FakeRpc(w3)) == []


def test_a_sweep_moves_bnb_only_above_the_exact_cost_of_moving_it():
    w3 = FakeW3(OWNER)
    session = _session()
    w3.eth.gas_price = 10**9
    w3.eth.balances[session.address] = 21_000 * 10**9 + 1

    assert len(sweep(session, OWNER, FakeRpc(w3))) == 1


def test_a_token_that_cannot_be_moved_does_not_strand_the_bnb():
    w3 = FakeW3(OWNER)
    session = _session()
    w3.eth.token_balances[USDT] = 250 * 10**18
    w3.eth.balances[session.address] = 5 * 10**16
    w3.eth.estimate_error = RuntimeError("execution reverted")

    with pytest.raises(SweepFailed) as raised:
        sweep(session, OWNER, FakeRpc(w3))

    assert len(raised.value.sent) == 1
    assert str(USDT) in str(raised.value)


def test_a_sweep_of_an_empty_session_sends_nothing():
    w3 = FakeW3(OWNER)

    assert sweep(_session(), OWNER, FakeRpc(w3)) == []


# -- deriving what a call spends ----------------------------------------------

VUSDT = Web3.to_checksum_address("0xfD5840Cd36d94D7229439859C0112a4185BC0255")
NPM = Web3.to_checksum_address("0x46A15B0b27311cedF172AB29E4f4766fbE7F4364")
_erc20 = Web3().eth.contract(
    abi=[
        {
            "name": "approve",
            "type": "function",
            "inputs": [
                {"name": "spender", "type": "address"},
                {"name": "amount", "type": "uint256"},
            ],
            "outputs": [{"name": "", "type": "bool"}],
        },
        {
            "name": "transfer",
            "type": "function",
            "inputs": [
                {"name": "to", "type": "address"},
                {"name": "amount", "type": "uint256"},
            ],
            "outputs": [{"name": "", "type": "bool"}],
        },
    ]
)
_venus = Web3().eth.contract(
    abi=[
        {
            "name": "repayBorrow",
            "type": "function",
            "inputs": [{"name": "repayAmount", "type": "uint256"}],
            "outputs": [{"name": "", "type": "uint256"}],
        },
        {
            "name": "repayBorrowBehalf",
            "type": "function",
            "inputs": [
                {"name": "borrower", "type": "address"},
                {"name": "repayAmount", "type": "uint256"},
            ],
            "outputs": [{"name": "", "type": "uint256"}],
        },
    ]
)
_npm = Web3().eth.contract(
    abi=[
        {
            "name": "mint",
            "type": "function",
            "inputs": [
                {
                    "name": "params",
                    "type": "tuple",
                    "components": [
                        {"name": "token0", "type": "address"},
                        {"name": "token1", "type": "address"},
                        {"name": "fee", "type": "uint24"},
                        {"name": "tickLower", "type": "int24"},
                        {"name": "tickUpper", "type": "int24"},
                        {"name": "amount0Desired", "type": "uint256"},
                        {"name": "amount1Desired", "type": "uint256"},
                        {"name": "amount0Min", "type": "uint256"},
                        {"name": "amount1Min", "type": "uint256"},
                        {"name": "recipient", "type": "address"},
                        {"name": "deadline", "type": "uint256"},
                    ],
                }
            ],
            "outputs": [],
        },
        {
            "name": "increaseLiquidity",
            "type": "function",
            "inputs": [
                {
                    "name": "params",
                    "type": "tuple",
                    "components": [
                        {"name": "tokenId", "type": "uint256"},
                        {"name": "amount0Desired", "type": "uint256"},
                        {"name": "amount1Desired", "type": "uint256"},
                        {"name": "amount0Min", "type": "uint256"},
                        {"name": "amount1Min", "type": "uint256"},
                        {"name": "deadline", "type": "uint256"},
                    ],
                }
            ],
            "outputs": [],
        },
        {
            "name": "collect",
            "type": "function",
            "inputs": [
                {
                    "name": "params",
                    "type": "tuple",
                    "components": [
                        {"name": "tokenId", "type": "uint256"},
                        {"name": "recipient", "type": "address"},
                        {"name": "amount0Max", "type": "uint128"},
                        {"name": "amount1Max", "type": "uint128"},
                    ],
                }
            ],
            "outputs": [],
        },
    ]
)


def _bare(to, data, value="0") -> PreparedCall:
    return PreparedCall(
        to=to,
        data=data,
        value_atomic=value,
        gas_ceiling=300_000,
        deadline=4_102_444_800,
        purpose="a call",
        simulation={"ok": True},
    )


def test_an_erc20_approval_and_transfer_are_denominated_in_the_contract_they_call():
    approval = _bare(USDT, _erc20.encode_abi("approve", args=[ROUTER, 25 * 10**18]))
    transfer = _bare(USDT, _erc20.encode_abi("transfer", args=[OWNER, 7 * 10**18]))

    assert call_spend(approval) == {USDT: 25 * 10**18}
    assert call_spend(transfer) == {USDT: 7 * 10**18}


def test_a_swap_is_denominated_in_the_first_hop_of_its_own_path():
    call = _bare(ROUTER, _swap_data(31 * 10**18, route=(USDT, WBNB)))

    assert call_spend(call) == {USDT: 31 * 10**18}


def test_a_venus_repay_is_denominated_in_the_vtokens_underlying():
    behalf = _bare(
        VUSDT, _venus.encode_abi("repayBorrowBehalf", args=[OWNER, 4 * 10**18])
    )
    direct = _bare(VUSDT, _venus.encode_abi("repayBorrow", args=[5 * 10**18]))
    hints = {"underlying": {VUSDT: USDT}}

    assert needs_underlying(behalf) == VUSDT
    assert call_spend(behalf, token_hints=hints) == {USDT: 4 * 10**18}
    assert call_spend(direct, token_hints=hints) == {USDT: 5 * 10**18}


def test_a_venus_call_with_no_underlying_supplied_is_unmeasured_not_zero():
    call = _bare(VUSDT, _venus.encode_abi("repayBorrow", args=[5 * 10**18]))

    with pytest.raises(UnmeasuredSpend, match="its underlying was not supplied"):
        call_spend(call)


def test_an_npm_mint_names_both_of_its_own_tokens():
    call = _bare(
        NPM,
        _npm.encode_abi(
            "mint",
            args=[(USDT, WBNB, 500, -100, 100, 11 * 10**18, 2 * 10**18, 1, 1, OWNER, 9)],
        ),
    )

    assert call_spend(call) == {USDT: 11 * 10**18, WBNB: 2 * 10**18}


def test_increase_liquidity_names_a_position_and_no_tokens_so_it_needs_the_pair():
    call = _bare(
        NPM,
        _npm.encode_abi(
            "increaseLiquidity", args=[(7141050, 3 * 10**18, 4 * 10**18, 1, 1, 9)]
        ),
    )

    with pytest.raises(UnmeasuredSpend, match="token0 and token1 were not supplied"):
        call_spend(call)
    assert call_spend(
        call, token_hints={"position_tokens": {"7141050": [USDT, WBNB]}}
    ) == {USDT: 3 * 10**18, WBNB: 4 * 10**18}


def test_taking_liquidity_out_spends_nothing():
    collect = _bare(
        NPM, _npm.encode_abi("collect", args=[(7141050, OWNER, 2**127, 2**127)])
    )

    assert call_spend(collect) == {}


def test_a_selector_docket_cannot_read_is_refused_where_it_could_be_spending():
    with pytest.raises(UnmeasuredSpend, match="not a selector Docket can derive"):
        call_spend(_bare(ROUTER, "0xdeadbeef", value=str(10**15)))
    with pytest.raises(UnmeasuredSpend, match="not a selector Docket can derive"):
        call_spend(_bare(USDT, "0xdeadbeef"), token_allowlist=(USDT, NATIVE_TOKEN))
    # Nothing to spend and nothing to spend it on: not every call moves money.
    assert call_spend(_bare(ROUTER, "0xdeadbeef"), token_allowlist=(USDT,)) == {}


def test_a_zero_leg_is_dropped_rather_than_charged():
    call = _bare(
        NPM,
        _npm.encode_abi(
            "mint", args=[(USDT, WBNB, 500, -100, 100, 11 * 10**18, 0, 1, 1, OWNER, 9)]
        ),
    )

    assert call_spend(call) == {USDT: 11 * 10**18}


def test_a_batch_total_is_the_sum_of_its_calls_including_the_native_legs():
    calls = [
        _bare(ROUTER, _swap_data(10 * 10**18)),
        _bare(ROUTER, _swap_data(15 * 10**18)),
        _bare(ROUTER, _swap_data(5 * 10**18), value=str(10**16)),
    ]

    assert batch_spend(calls) == {USDT: 30 * 10**18, NATIVE_TOKEN: 10**16}


def test_a_batch_total_and_the_session_cap_are_asked_once():
    policy = _policy()

    permitted, reason = policy.allows_total(
        spent={}, token_amounts={USDT: 400 * 10**18}
    )
    assert permitted, reason

    permitted, reason = policy.allows_total(
        spent={USDT: 200 * 10**18}, token_amounts={USDT: 400 * 10**18}
    )
    assert not permitted
    assert "past the session cap" in reason

    permitted, reason = policy.allows_total(spent={}, token_amounts={WBNB: 1})
    assert not permitted
    assert "not in the token allowlist" in reason


def test_a_native_value_is_charged_exactly_once():
    """`call_spend` deliberately leaves the native leg out: `allows` and `execute` each
    fold `value_atomic` in themselves, and returning it here too would charge it twice."""
    w3 = FakeW3(OWNER)
    session = _session()
    call = _call(amount_in=10 * 10**18, value_atomic=str(10**16))

    assert call_spend(call) == {USDT: 10 * 10**18}
    execute(
        _activation(),
        call,
        session=session,
        rpc=FakeRpc(w3),
        policy=_policy(),
        sleep=lambda _: None,
    )

    assert session.spent_atomic == {USDT: 10 * 10**18, NATIVE_TOKEN: 10**16}


def test_execute_reads_a_vtokens_underlying_off_the_chain_when_it_was_not_supplied():
    w3 = FakeW3(OWNER)
    w3.eth.contract = lambda address=None, abi=None: _UnderlyingContract(USDT)
    session = _session()
    policy = _policy(contract_allowlist=(VUSDT,), function_allowlist=("0x0e752702",))
    call = _bare(VUSDT, _venus.encode_abi("repayBorrow", args=[5 * 10**18]))

    execute(
        _activation(),
        call,
        session=session,
        rpc=FakeRpc(w3),
        policy=policy,
        sleep=lambda _: None,
    )

    assert session.spent_atomic == {USDT: 5 * 10**18}


class _UnderlyingContract:
    def __init__(self, token):
        self.token = token
        self.functions = self

    def underlying(self):
        return FakeCall(self.token)


def test_a_call_docket_cannot_measure_is_never_broadcast():
    w3 = FakeW3(OWNER)
    activation = _activation()

    with pytest.raises(ExecutionFailed, match="unmeasured spend"):
        execute(
            activation,
            _bare(ROUTER, "0xdeadbeef", value=str(10**15)),
            session=_session(),
            rpc=FakeRpc(w3),
            policy=_policy(),
            sleep=lambda _: None,
        )

    assert w3.eth.sent == []
    assert any("unmeasured spend" in event.reason for event in activation.events)
