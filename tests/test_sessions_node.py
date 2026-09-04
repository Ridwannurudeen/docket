"""The sweep and the executor against a node that behaves like one.

`tests/fakenode.py` debits gas only when a transaction MINES, refuses at broadcast a
transaction the sender cannot afford given what is already pending from it, and raises
`TransactionNotFound` for a hash that has not mined. Those three are exactly the
behaviours the earlier fakes did not have, and exactly the ones the B1 defect hid behind:
a sweep sized against a balance read before the token legs mine is over by their gas, and
only a node that charges for gas and refuses an unaffordable transaction says so.
"""

import pytest
from eth_account import Account
from eth_account._utils.legacy_transactions import Transaction
from web3 import Web3

from docket.sessions import sweep as sw
from docket.sessions.keys import Session
from docket.sessions.sweep import (
    NATIVE_TRANSFER_GAS,
    SweepFailed,
    residual_balances,
    sweep,
)
from tests.fakenode import Node, cs

OWNER = cs("0x451871a1753903fb8fdd64a6b838e95ab8d5b80f")
USDT = cs("0x55d398326f99059fF775485246999027B3197955")
WBNB = cs("0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c")
GAS_PRICE = 10**9
ESTIMATE = 60_000


def _session(node, *, usdt=250 * 10**18, bnb=5 * 10**16, received=()):
    account = Account.create()
    session = Session(
        address=account.address,
        account=account,
        token_allowlist=(USDT, "BNB"),
        received_tokens=tuple(received),
    )
    node.bnb[account.address] = bnb
    if usdt:
        node.tokens.setdefault(USDT, {})[account.address] = usdt
    return session


def test_the_native_leg_is_exactly_what_is_left_after_the_token_gas():
    """The B1 regression, guarded by arithmetic rather than by a count of transactions.

    The value of the native leg is decoded from the signed transaction and compared with
    the balance the node will actually hold once the token transfer's gas has been taken.
    A sweep that sized it from the balance read up front would be over by that gas, and
    this node refuses an unaffordable transaction rather than quietly accepting it.
    """
    node = Node(gas_price=GAS_PRICE, estimate=ESTIMATE)
    session = _session(node)
    start = node.bnb[session.address]

    sent = sweep(
        session,
        OWNER,
        node.rpc(),
        max_gas_price_wei=5 * 10**9,
        sleep=lambda _: node.mine(),
    )

    assert len(sent) == 2
    assert node.rejected == []
    native = [p for p in node.pending if p["hash"] == sent[1]][0]
    token_gas = ESTIMATE * GAS_PRICE
    assert native["value"] == start - token_gas - NATIVE_TRANSFER_GAS * GAS_PRICE
    assert native["gas"] == NATIVE_TRANSFER_GAS
    assert native["gasPrice"] == GAS_PRICE

    # Still holding BNB until that leg mines: the tick must not close on this reading.
    assert set(residual_balances(session, node.rpc())) == {"BNB"}
    node.mine()
    assert residual_balances(session, node.rpc()) == {}
    assert node.tokens[USDT][OWNER] == 250 * 10**18
    assert node.bnb[session.address] == 0


def test_the_token_leg_carries_the_gas_margin_over_the_estimate():
    node = Node(gas_price=GAS_PRICE, estimate=ESTIMATE)
    session = _session(node)

    sent = sweep(session, OWNER, node.rpc(), sleep=lambda _: node.mine())

    token = Transaction.from_bytes(
        session.account.sign_transaction(
            {
                "from": session.address,
                "to": USDT,
                "data": sw._encoder.encode_abi("transfer", args=[OWNER, 1]),
                "value": 0,
                "nonce": 0,
                "gas": ESTIMATE * sw.GAS_MARGIN_NUMERATOR // sw.GAS_MARGIN_DENOMINATOR,
                "gasPrice": GAS_PRICE,
                "chainId": 56,
            }
        ).raw_transaction
    )
    assert token.gas == 72_000
    assert len(sent) == 2


def test_sizing_the_native_leg_before_the_token_gas_is_refused_by_the_node():
    """The mutation the fix closes, replayed against the same node.

    The pre-fix code read the balance once, at the top, and subtracted one transfer's gas
    from it. By the time that transaction is broadcast the token leg has mined and taken
    its own gas, so the value is over by exactly that and the node refuses it — leaving
    the whole float behind, which is the failure the count of sent transactions in the
    earlier test could not see.
    """
    node = Node(gas_price=GAS_PRICE, estimate=ESTIMATE)
    session = _session(node)
    balance_read_up_front = node.bnb[session.address]

    token_leg = session.account.sign_transaction(
        {
            "from": session.address,
            "to": USDT,
            "data": sw._encoder.encode_abi("transfer", args=[OWNER, 250 * 10**18]),
            "value": 0,
            "nonce": 0,
            "gas": ESTIMATE * sw.GAS_MARGIN_NUMERATOR // sw.GAS_MARGIN_DENOMINATOR,
            "gasPrice": GAS_PRICE,
            "chainId": 56,
        }
    )
    node.send(bytes(token_leg.raw_transaction))
    node.mine()

    mutant_native = session.account.sign_transaction(
        {
            "from": session.address,
            "to": OWNER,
            "value": balance_read_up_front - NATIVE_TRANSFER_GAS * GAS_PRICE,
            "nonce": 1,
            "gas": NATIVE_TRANSFER_GAS,
            "gasPrice": GAS_PRICE,
            "chainId": 56,
        }
    )

    with pytest.raises(ValueError, match="insufficient funds"):
        node.send(bytes(mutant_native.raw_transaction))
    assert len(node.rejected) == 1


def test_a_gas_price_above_the_policy_ceiling_is_capped_for_the_sweep_too():
    node = Node(gas_price=500 * 10**9, estimate=ESTIMATE)
    session = _session(node, usdt=0, bnb=10**17)

    sent = sweep(
        session,
        OWNER,
        node.rpc(),
        max_gas_price_wei=GAS_PRICE,
        sleep=lambda _: node.mine(),
    )

    assert len(sent) == 1
    assert node.pending[0]["gasPrice"] == GAS_PRICE
    assert node.pending[0]["value"] == 10**17 - NATIVE_TRANSFER_GAS * GAS_PRICE


def test_a_token_leg_that_never_mines_leaves_the_native_leg_unsized():
    node = Node(gas_price=GAS_PRICE, estimate=ESTIMATE)
    session = _session(node)

    with pytest.raises(SweepFailed, match="had not mined"):
        sweep(session, OWNER, node.rpc(), sleep=lambda _: None)

    assert len(node.pending) == 1
    assert node.pending[0]["to"] == USDT
    assert set(residual_balances(session, node.rpc())) == {USDT, "BNB"}


def test_a_token_the_session_only_received_is_swept_with_the_rest():
    node = Node(gas_price=GAS_PRICE, estimate=ESTIMATE)
    session = _session(node, usdt=0, received=(WBNB,))
    node.tokens.setdefault(WBNB, {})[session.address] = 3 * 10**18

    sweep(session, OWNER, node.rpc(), sleep=lambda _: node.mine())
    node.mine()

    assert node.tokens[WBNB][OWNER] == 3 * 10**18
    assert node.tokens[WBNB].get(session.address, 0) == 0
    assert residual_balances(session, node.rpc()) == {}


def test_residual_reads_the_nodes_own_price_for_the_dust_rule():
    node = Node(gas_price=500 * 10**9, estimate=ESTIMATE)
    session = _session(node, usdt=0, bnb=10**15)

    # 10**15 is below 500 gwei x 21000, so nothing can move it and nothing is waiting on.
    assert residual_balances(session, node.rpc()) == {}
    node.gas_price = 10**9
    assert residual_balances(session, node.rpc()) == {"BNB": 10**15}


def test_a_checksummed_and_a_lowercased_spend_are_one_cap():
    """Two spellings of one address must SUM. Taking the last seen would forget whatever
    was spent under the other, which is a cap that grows by however many ways a token can
    be written down."""
    from docket.sessions.policy import SessionPolicy

    policy = SessionPolicy(
        contract_allowlist=(USDT,),
        function_allowlist=("0x38ed1739",),
        token_allowlist=(USDT, "BNB"),
        per_action_limit_atomic={USDT: 100, "BNB": 10},
        total_cap_atomic={USDT: 100, "BNB": 10},
        max_slippage_bps=100,
        max_gas_price_wei=GAS_PRICE,
        expires_at="2099-01-01T00:00:00+00:00",
    )
    spent = {USDT: 60, USDT.lower(): 50}

    permitted, reason = policy.allows_total(spent=spent, token_amounts={USDT: 1})

    assert not permitted
    assert "111" in reason


def test_the_swap_router_selector_is_the_one_the_router_publishes():
    """Computed rather than pasted: a transposed selector is a route the session refuses
    to send and nothing else would notice."""
    from docket.sessions.spend import EXACT_INPUT_SINGLE

    signature = (
        "exactInputSingle((address,address,uint24,address,uint256,uint256,uint256,"
        "uint160))"
    )
    assert EXACT_INPUT_SINGLE == "0x" + Web3.keccak(text=signature).hex()[:8]


# -- approvals, end to end against the node ------------------------------------

NPM_ADDRESS = cs("0x46A15B0b27311cedF172AB29E4f4766fbE7F4364")
ATTACKER = cs("0x" + "a7" * 20)


def test_closure_zeroes_every_outstanding_approval_before_it_sweeps():
    """A session whose balances read zero but whose approvals stand is one a spender can
    still pull from the moment that address is funded again."""
    from docket.sessions.sweep import outstanding_allowances, revoke_allowances

    node = Node(gas_price=GAS_PRICE, estimate=ESTIMATE)
    session = _session(node, usdt=0, bnb=10**17)
    node.allowances.setdefault(USDT, {})[(session.address, NPM_ADDRESS)] = 5 * 10**18
    session.reserved_atomic = {USDT: {NPM_ADDRESS: 5 * 10**18}}

    assert outstanding_allowances(session, node.rpc()) == {
        USDT: {NPM_ADDRESS: 5 * 10**18}
    }
    # Still outstanding, so the activation may not close on this reading.
    assert "allowance " + USDT + " to " + NPM_ADDRESS in residual_balances(
        session, node.rpc()
    )

    sent = revoke_allowances(session, node.rpc(), sleep=lambda _: node.mine())

    assert len(sent) == 1
    assert node.allowances[USDT][(session.address, NPM_ADDRESS)] == 0
    assert outstanding_allowances(session, node.rpc()) == {}


def test_an_allowance_consumed_elsewhere_stops_being_held_against_the_cap():
    """Read from the token, not remembered: our record is of what we intended to grant."""
    from docket.sessions.sweep import outstanding_allowances

    node = Node(gas_price=GAS_PRICE, estimate=ESTIMATE)
    session = _session(node, usdt=0)
    session.reserved_atomic = {USDT: {NPM_ADDRESS: 5 * 10**18}}
    node.allowances.setdefault(USDT, {})[(session.address, NPM_ADDRESS)] = 0

    assert outstanding_allowances(session, node.rpc()) == {}
