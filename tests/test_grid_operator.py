"""The operator, end to end, and the four ways it declines to act.

Two properties are asserted harder than anything else here, because they are the two a
judge should press on.

**The preview cannot submit.** Not "is configured not to" — it holds no authority, no
session, no signer and no submitter, and there is no method on it that sends anything. A
bug in the operator cannot make one send, and no setting turns one into the other.

**Nothing is submitted that the chain disagreed with.** A simulation below the intent's
floor, an unreadable session, a refused session and a revoked one each stop the sequence
before the submitter is reached, and each test asserts the submitter was never called
rather than only that the result said no.
"""

import inspect
import os

import pytest
from web3 import Web3

from docket.agents.grid.operator import (
    DEFAULT_SLIPPAGE_BPS,
    SUBMITTER_CONTRACT,
    SWAP_SELECTOR,
    GridOperator,
    GridPreview,
    NoSession,
    NotArmed,
    observe_price,
)
from docket.agents.grid.plan import build_plan
from docket.execution.authority import (
    CallPermission,
    SessionPermissions,
    SpendPermission,
    StubSessionAuthority,
)
from docket.execution.receipts import EXECUTION_NOTE
from docket.execution.simulate import PANCAKE_V2_ROUTER
from docket.hire.receipts import canonical_hash

USDT = Web3.to_checksum_address("0x55d398326f99059fF775485246999027B3197955")
WBNB = Web3.to_checksum_address("0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c")
OWNER = "0x429898ba0Fc5b9F1fF0a8f0BD1D6D3cB33B26DdD"
FROZEN_NOW = 2_000_000_000
E18 = 10**18


@pytest.fixture(autouse=True)
def frozen_clock(monkeypatch):
    for module in (
        "docket.execution.intent",
        "docket.execution.simulate",
        "docket.execution.state",
        "docket.execution.authority",
        "docket.agents.grid.operator",
    ):
        monkeypatch.setattr(f"{module}.now", lambda: FROZEN_NOW)


class FakePool:
    """A constant-price pool, exact in both directions.

    `degrade_at` makes the nth quote come back 20% worse, which is how the "the price
    moved between drafting and simulating" path gets exercised without a network.
    """

    def __init__(self, price=600 * E18, base_decimals=18, gas=180_000, degrade_at=None):
        self.price = price
        self.base_decimals = base_decimals
        self.gas = gas
        self.degrade_at = degrade_at
        self.calls = 0
        self.asked = []

    def block_number(self):
        return 115_155_027

    def amounts_out(self, amount_in, route):
        self.calls += 1
        route = tuple(Web3.to_checksum_address(hop) for hop in route)
        self.asked.append((amount_in, route))
        unit = 10**self.base_decimals
        if route[0] == WBNB:
            out = amount_in * self.price // unit
        else:
            out = amount_in * unit // self.price
        if self.degrade_at is not None and self.calls == self.degrade_at:
            out = out * 8 // 10
        return [amount_in, out]

    def estimate_gas(self, sender, target, calldata):
        return self.gas


class Submitter:
    def __init__(self, tx_hash="0xdead"):
        self.tx_hash = tx_hash
        self.calls = []

    def __call__(self, intent, calldata):
        self.calls.append((intent, calldata))
        return self.tx_hash


def _plan(**overrides):
    fields = {
        "lower": 500 * E18,
        "upper": 700 * E18,
        "levels": 5,
        "size_per_level": 25 * E18,
        "base": WBNB,
        "quote": USDT,
        "base_decimals": 18,
        "reference": 620 * E18,
    }
    fields.update(overrides)
    return build_plan(**fields)


def _permissions():
    return SessionPermissions(
        calls=(CallPermission(to=PANCAKE_V2_ROUTER, signature="swapExactTokensForTokens"),),
        spend=(
            SpendPermission(token=USDT, limit=100 * E18, period=86_400),
            SpendPermission(token=WBNB, limit=E18, period=86_400),
        ),
    )


def _armed(pool=None, submitter=None, authority=None, ref=None):
    pool = pool or FakePool()
    submitter = submitter or Submitter()
    if authority is None:
        authority = StubSessionAuthority(account=OWNER)
        ref = authority.grant(_permissions(), expiry=FROZEN_NOW + 86_400)
    return (
        GridOperator(
            _plan(),
            reader=pool,
            authority=authority,
            ref=ref,
            permissions=_permissions(),
            submitter=submitter,
        ),
        pool,
        submitter,
        authority,
        ref,
    )


# ------------------------------------------------------------------ observing


def test_the_price_is_what_one_whole_base_token_fetches_from_the_router():
    pool = FakePool(price=600 * E18)
    observation = observe_price(pool, base=WBNB, quote=USDT, base_decimals=18)
    assert observation.price == 600 * E18
    assert observation.source == "router.getAmountsOut"
    assert pool.asked[0] == (E18, (WBNB, USDT))


def test_the_observation_says_it_is_an_execution_price_rather_than_a_mid():
    observation = observe_price(FakePool(), base=WBNB, quote=USDT, base_decimals=18)
    note = observation.as_record()["note"].lower()
    assert "fee" in note and "not a mid price" in note


# -------------------------------------------------------------------- preview


def test_a_preview_drafts_every_level_and_quotes_each_one():
    preview = GridPreview(_plan(), reader=FakePool(), wallet=OWNER).preview()
    assert len(preview["levels"]) == 5
    for entry in preview["levels"]:
        assert entry["intent"] is not None
        assert entry["simulation"]["agrees"] is True
    assert preview["plan"]["plan_hash"] == _plan().plan_hash


def test_a_preview_never_submits_and_says_why_in_the_body():
    preview = GridPreview(_plan(), reader=FakePool(), wallet=OWNER).preview()
    assert preview["submitted"] is False
    assert preview["authority"] is None
    lowered = preview["why_not_submitted"].lower()
    assert "no session" in lowered and "no submitter" in lowered


def test_a_preview_holds_nothing_that_could_send_anything():
    """The guarantee is structural. There is no submitter to disable, no authority to
    hold a session, and no method that sends — so no setting turns this into a live run."""
    preview = GridPreview(_plan(), reader=FakePool(), wallet=OWNER)
    for forbidden in ("submit", "step", "send", "sign", "execute"):
        assert not hasattr(preview, forbidden), forbidden
    held = set(vars(preview))
    assert not held & {"_submitter", "_authority", "_ref", "_key", "_signer"}
    assert not issubclass(GridPreview, GridOperator)
    assert not issubclass(GridOperator, GridPreview)


def test_a_preview_runs_with_nothing_at_all_in_the_environment(monkeypatch):
    """A judge holding no wallet, no keys and no configuration sees the whole mechanism.
    Nothing here is armed by an environment variable, so emptying it changes nothing."""
    monkeypatch.setattr(os, "environ", {})
    preview = GridPreview(_plan(), reader=FakePool(), wallet=OWNER).preview()
    assert int(preview["levels"][0]["intent"]["min_output"]) > 0
    assert preview["submitted"] is False


def test_a_preview_estimates_no_gas_because_it_has_no_account_that_could_execute():
    preview = GridPreview(_plan(), reader=FakePool(), wallet=OWNER).preview()
    for entry in preview["levels"]:
        assert entry["simulation"]["gas"] is None
        assert entry["simulation"]["checks"] == ["intent.matches", "router.getAmountsOut"]


def test_a_preview_names_the_level_the_price_has_actually_reached():
    """At 550 the price has fallen to the 550 rung and past nothing else — the 500 rung
    is still below it and the two sell rungs are above. The nearest reached one leads."""
    preview = GridPreview(_plan(), reader=FakePool(price=550 * E18), wallet=OWNER).preview()
    assert preview["next_level"] == 2
    holding = [e["level"]["index"] for e in preview["levels"] if e["condition_holds"]]
    assert holding == [1, 2]


def test_a_preview_leaves_a_filled_level_out_rather_than_drafting_it_again():
    preview = GridPreview(_plan(), reader=FakePool(price=550 * E18), wallet=OWNER).preview(
        filled=(2,)
    )
    filled = next(e for e in preview["levels"] if e["level"]["index"] == 2)
    assert filled["intent"] is None
    assert filled["skipped"] == "already filled"
    assert preview["next_level"] == 1


def test_a_preview_carries_the_sentence_a_marketplace_leaves_off():
    assert GridPreview(_plan(), reader=FakePool(), wallet=OWNER).preview()["note"] == EXECUTION_NOTE
    assert "not show the action was worth taking" in EXECUTION_NOTE


# ------------------------------------------------------------- what it refuses


def test_an_operator_without_a_session_is_refused_before_a_node_is_contacted():
    pool = FakePool()
    with pytest.raises(NoSession):
        GridOperator(_plan(), reader=pool, submitter=Submitter())
    with pytest.raises(NoSession):
        GridOperator(
            _plan(),
            reader=pool,
            authority=StubSessionAuthority(account=OWNER),
            permissions=_permissions(),
            submitter=Submitter(),
        )
    assert pool.calls == 0


def test_an_operator_with_a_session_and_no_submitter_is_refused_too():
    authority = StubSessionAuthority(account=OWNER)
    ref = authority.grant(_permissions(), expiry=FROZEN_NOW + 86_400)
    pool = FakePool()
    with pytest.raises(NotArmed) as exc:
        GridOperator(_plan(), reader=pool, authority=authority, ref=ref, permissions=_permissions())
    assert "ships none" in str(exc.value).lower()
    assert pool.calls == 0


def test_a_price_outside_the_band_acts_on_nothing():
    operator, _, submitter, _, _ = _armed(pool=FakePool(price=800 * E18))
    out = operator.step()
    assert out["acted"] is False and out["submitted"] is False
    assert "waiting" in out["reason"]
    assert submitter.calls == []


def test_a_simulation_that_disagrees_with_the_intent_is_never_submitted():
    """The rule the whole stage turns on. The quote used to draft the floor was better
    than the quote taken a moment later, and the difference is the action not happening."""
    operator, _, submitter, _, _ = _armed(pool=FakePool(price=600 * E18, degrade_at=3))
    out = operator.step()
    assert out["submitted"] is False
    assert submitter.calls == []
    receipt = out["receipt"]
    assert receipt["simulation"]["agrees"] is False
    assert "min_output" in receipt["simulation"]["reason"]
    assert receipt["lifecycle"]["state"] == "paused"
    assert receipt["tx_hash"] is None


def test_a_revoked_session_is_never_submitted_against():
    authority = StubSessionAuthority(account=OWNER)
    ref = authority.grant(_permissions(), expiry=FROZEN_NOW + 86_400)
    authority.revoke(ref)
    operator, _, submitter, _, _ = _armed(authority=authority, ref=ref)
    out = operator.step()
    assert out["submitted"] is False
    assert submitter.calls == []
    assert "revoked" in out["receipt"]["lifecycle"]["history"][-1]["reason"].lower()


def test_a_cap_too_small_for_the_level_is_never_submitted_against():
    authority = StubSessionAuthority(account=OWNER)
    small = SessionPermissions(
        calls=(CallPermission(to=PANCAKE_V2_ROUTER, signature="swapExactTokensForTokens"),),
        spend=(SpendPermission(token=USDT, limit=E18, period=86_400),),
    )
    ref = authority.grant(small, expiry=FROZEN_NOW + 86_400)
    operator = GridOperator(
        _plan(),
        reader=FakePool(price=600 * E18),
        authority=authority,
        ref=ref,
        permissions=small,
        submitter=(submitter := Submitter()),
    )
    out = operator.step()
    assert out["submitted"] is False
    assert submitter.calls == []
    assert "cap" in out["receipt"]["lifecycle"]["history"][-1]["reason"].lower()


def test_a_session_whose_state_cannot_be_read_is_never_submitted_against():
    """An outage is not an authorisation."""

    class Unreadable(StubSessionAuthority):
        def status(self, ref, *, permissions=None, call=None):
            raise RuntimeError("every BSC endpoint failed")

    authority = Unreadable(account=OWNER)
    ref = authority.grant(_permissions(), expiry=FROZEN_NOW + 86_400)
    operator, _, submitter, _, _ = _armed(authority=authority, ref=ref)
    out = operator.step()
    assert out["submitted"] is False
    assert submitter.calls == []
    assert out["receipt"]["authority"] is None
    assert "could not be read" in out["receipt"]["lifecycle"]["history"][-1]["reason"]


# ------------------------------------------------------------------- acting


def test_a_reached_level_inside_every_bound_is_drafted_simulated_authorised_and_sent():
    operator, pool, submitter, _, _ = _armed(pool=FakePool(price=600 * E18))
    out = operator.step()
    assert out["acted"] and out["submitted"]
    assert len(submitter.calls) == 1
    intent, calldata = submitter.calls[0]
    assert intent.matches(calldata)
    assert intent.target == PANCAKE_V2_ROUTER
    assert intent.selector == SWAP_SELECTOR
    assert intent.token_in == USDT and intent.token_out == WBNB
    assert intent.max_input == 25 * E18


def test_the_floor_is_the_routers_own_quote_less_the_slippage_the_plan_tolerates():
    operator, _, submitter, _, _ = _armed(pool=FakePool(price=600 * E18))
    operator.step()
    intent, _ = submitter.calls[0]
    quoted = 25 * E18 * E18 // (600 * E18)
    assert intent.min_output == quoted * (10_000 - DEFAULT_SLIPPAGE_BPS) // 10_000
    assert intent.min_output > 0


def test_the_lifecycle_on_the_receipt_shows_every_state_it_passed_through():
    operator, _, _, _, _ = _armed(pool=FakePool(price=600 * E18))
    lifecycle = operator.step()["receipt"]["lifecycle"]
    assert [step["to_state"] for step in lifecycle["history"]] == [
        "simulated",
        "authorized",
        "active",
        "submitted",
    ]
    assert lifecycle["state"] == "submitted"


def test_the_receipt_binds_the_plan_the_intent_the_simulation_and_the_authority():
    operator, _, _, _, _ = _armed(pool=FakePool(price=600 * E18))
    receipt = operator.step()["receipt"]
    assert receipt["plan_hash"] == _plan().plan_hash
    assert receipt["policy_version"] == "grid-operator/1"
    assert receipt["intent_key"].startswith("0x")
    assert receipt["simulation"]["agrees"] is True
    assert receipt["observation"]["price"] == str(600 * E18)
    assert receipt["tx_hash"] == "0xdead"
    assert receipt["note"] == EXECUTION_NOTE


def test_the_receipt_says_where_the_limits_behind_the_action_were_read():
    """A stub authority produces a receipt that says `stub`. That field is how anybody
    reading a receipt tells an enforced limit from a remembered one."""
    operator, _, _, _, _ = _armed(pool=FakePool(price=600 * E18))
    assert operator.step()["receipt"]["authority"]["source"] == "stub"


def test_the_receipt_records_the_cap_before_and_what_the_action_committed_of_it():
    operator, _, _, _, _ = _armed(pool=FakePool(price=600 * E18))
    cap = operator.step()["receipt"]["cap"]
    assert cap["token"] == USDT
    assert cap["remaining_before"] == str(100 * E18)
    assert cap["committed"] == str(25 * E18)
    assert "not knowable yet" in cap["note"]


def test_the_receipt_hash_is_recomputable_by_whoever_holds_the_receipt():
    operator, _, _, _, _ = _armed(pool=FakePool(price=600 * E18))
    receipt = dict(operator.step()["receipt"])
    issued = receipt.pop("issued_at")
    digest = receipt.pop("receipt_hash")
    assert canonical_hash(receipt) == digest
    assert issued.endswith("+00:00")


# ------------------------------------------------------- the hire and the shelf


def test_the_hire_runs_the_preview_and_has_no_way_to_run_the_armed_operator(monkeypatch):
    """`/hire/grid-operator` is the path a stranger's agent reaches, so it is the one that
    most needs to be incapable rather than merely configured. It builds a `GridPreview`,
    and the armed class is not reachable from this function at all."""
    import docket.execution.simulate as simulate_module
    from docket.hire.catalogue import SERVICES as HIRE
    from docket.hire.catalogue import _run_grid_operator

    monkeypatch.setattr(simulate_module, "BscQuoteReader", lambda *a, **k: FakePool())
    assert HIRE["grid-operator"].run is _run_grid_operator

    source = inspect.getsource(_run_grid_operator)
    assert "GridPreview" in source
    assert "GridOperator" not in source

    out = _run_grid_operator({"wallet": OWNER})
    assert out["submitted"] is False
    assert out["authority"] is None
    assert out["note"] == EXECUTION_NOTE
    # Six by default and all six drafted: an even count straddles the centre of the band
    # rather than putting a sideless level exactly on it.
    assert len(out["levels"]) == 6
    assert out["plan"]["skipped_at_reference"] == 0
    sides = [entry["level"]["side"] for entry in out["levels"]]
    assert sides == ["buy", "buy", "buy", "sell", "sell", "sell"]


def test_the_hire_draws_its_own_band_around_the_price_when_it_is_given_none(monkeypatch):
    """A judge holding nothing but an address gets the whole mechanism from one call."""
    import docket.execution.simulate as simulate_module
    from docket.hire.catalogue import _run_grid_operator

    monkeypatch.setattr(simulate_module, "BscQuoteReader", lambda *a, **k: FakePool(600 * E18))
    plan = _run_grid_operator({"wallet": OWNER})["plan"]
    assert plan["reference"] == str(600 * E18)
    assert plan["lower"] == str(540 * E18)
    assert plan["upper"] == str(660 * E18)


def test_the_hire_uses_the_band_it_is_given_and_infers_nothing(monkeypatch):
    import docket.execution.simulate as simulate_module
    from docket.hire.catalogue import _run_grid_operator

    monkeypatch.setattr(simulate_module, "BscQuoteReader", lambda *a, **k: FakePool(600 * E18))
    plan = _run_grid_operator(
        {
            "wallet": OWNER,
            "lower": 500 * E18,
            "upper": 700 * E18,
            "levels": 5,
            "size_per_level": 25 * E18,
            "reference": 620 * E18,
        }
    )["plan"]
    assert plan["plan_hash"] == _plan().plan_hash


def test_the_grid_shelf_is_stocked_by_this_service_and_by_nothing_borrowed():
    from docket.marketplace.models import Category
    from docket.marketplace.registry import records_in

    assert [r.service_id for r in records_in(Category.GRID_TRADING)] == ["grid-operator"]


# ------------------------------------------------- the hazard Docket cannot see


def test_the_submitter_contract_names_the_owner_key_hazard():
    """The one failure this design cannot detect from the inside, stated where somebody
    wiring a submitter will read it.

    `canExecute` in the wallet's own executor returns true unconditionally for a zero
    keyHash and for super-admin keys. A submitter that signs with the OWNER key therefore
    passes every on-chain guard — not because the guards allowed it, but because they
    never applied — and at that point Docket's Python checks are the only thing left,
    which is the exact inversion this whole package exists to avoid. The submitter is an
    opaque callable, so nothing here can tell the two apart before the fact.
    """
    contract = SUBMITTER_CONTRACT.lower()
    assert "session key" in contract
    assert "owner key" in contract
    assert "super-admin" in contract or "super admin" in contract
    assert "canexecute" in contract
    # Named at the point of failure as well as in the documentation, because the moment
    # somebody is looking for a submitter to supply is the moment this has to be read.
    assert SUBMITTER_CONTRACT in GridOperator.__doc__
    with pytest.raises(NotArmed) as exc:
        authority = StubSessionAuthority(account=OWNER)
        GridOperator(
            _plan(),
            reader=FakePool(),
            authority=authority,
            ref=authority.grant(_permissions(), expiry=FROZEN_NOW + 86_400),
            permissions=_permissions(),
        )
    assert SUBMITTER_CONTRACT in str(exc.value)


def test_the_step_docstring_admits_it_keeps_no_ledger_of_what_has_filled():
    """`filled` is the caller's to carry. A loop that forgot would re-fire a level every
    tick, and `step` does not hand back the index it fired, so the caller has to read it
    off the receipt. Said out loud rather than left as a trap for the next person."""
    doc = GridOperator.step.__doc__.lower()
    assert "keeps no ledger" in doc
    assert "filled" in doc


def test_the_decision_and_the_receipt_are_made_on_one_and_the_same_chain_read():
    """A receipt that bound an earlier read than the one the decision used would be
    evidence about a different moment. One read, used for both."""

    class Counting(StubSessionAuthority):
        reads = 0

        def status(self, ref, *, permissions=None, call=None):
            Counting.reads += 1
            return super().status(ref, permissions=permissions, call=call)

    Counting.reads = 0
    authority = Counting(account=OWNER)
    ref = authority.grant(_permissions(), expiry=FROZEN_NOW + 86_400)
    operator, _, submitter, _, _ = _armed(
        pool=FakePool(price=600 * E18), authority=authority, ref=ref
    )
    out = operator.step()
    assert out["submitted"] is True
    assert Counting.reads == 1
    assert out["receipt"]["authority"]["source"] == "stub"
