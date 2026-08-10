"""The comparison, the cost of acting on it, and the candidate it would be flattering to drop.

Four properties, and the third is the one that makes this honest rather than persuasive.

**Net is not gross.** LPs keep roughly two thirds of the fee a pool charges. Quoting the
gross figure overstates a yield by about a half again, and the regression here is against
that specific overstatement rather than against a rounding error.

**Every rate carries its window and its denominator.** A 24h fee annualised by 365 is an
observation about one day, not a forecast, and it is a rate over the pool's TVL rather
than over anybody's position.

**A candidate that looks better and is not is shown anyway.** The highest observed APR in
the set can still be the wrong move once the switching cost is paid back over a stated
horizon. Filtering it out would leave a comparison that agrees with itself; it is present,
with the break-even that makes it look worse, and labelled.

**Nothing is recommended.** The order is by one named observed metric and the payload says
which, so a reader can tell an observation from an opinion.
"""

import re

import pytest
from web3 import Web3

from docket.agents.yield_router.router import (
    HORIZON_DAYS,
    MOVE_ASSETS,
    ORDERING,
    POLICY_VERSION,
    PREVIEW_REASON,
    YieldRouterPreview,
    break_even,
    compare,
    plan_move,
)
from docket.agents.yield_router.universe import eligible_pools
from docket.api.models import BANNED_FIELD_NAMES
from docket.execution.intent import ActionIntent
from docket.execution.simulate import PANCAKE_V2_ROUTER

USDT = "0x55d398326f99059ff775485246999027b3197955"
USDC = "0x8ac76a51cc950d9822d68b83fe1ad97b32cd580d"
WBNB = "0xbb4cdb9cbd36b01bd1cbaebf2de08d9173bc095c"
ALLOWLIST = {USDT, USDC, WBNB}
WALLET = Web3.to_checksum_address("0x429898ba0Fc5b9F1fF0a8f0BD1D6D3cB33B26DdD")
OBSERVED = "2026-08-10T00:00:00Z"
SOURCE = "explorer.pancakeswap.com/api/cached/pools/v3/bsc/list/top"
FROZEN_NOW = 2_000_000_000
E18 = 10**18


@pytest.fixture(autouse=True)
def frozen_clock(monkeypatch):
    for module in ("docket.execution.intent", "docket.agents.yield_router.router"):
        monkeypatch.setattr(f"{module}.now", lambda: FROZEN_NOW)


def _pool(pool_id, *, tvl="1000000", fee="250", protocol="82", volume="500000", pair=(USDT, USDC)):
    return {
        "id": pool_id,
        "feeTier": 500,
        "token0": {"symbol": "T0", "id": pair[0]},
        "token1": {"symbol": "T1", "id": pair[1]},
        "tvlUSD": tvl,
        "volumeUSD24h": volume,
        "feeUSD24h": fee,
        "protocolFeeUSD24h": protocol,
    }


# Fees chosen so the three rates are far apart and easy to read: the current pool earns
# 250-82 = 168/day on 1m, the richer one 900-300 = 600/day on 1m, and the thin one
# 600-200 = 400/day on only 60k, which is the highest rate in the set by a distance.
CURRENT = _pool("0xcurrent")
RICHER = _pool("0xricher", fee="900", protocol="300")
THIN = _pool("0xthin", tvl="60000", fee="600", protocol="200", volume="30000")


def _universe(pools=(CURRENT, RICHER, THIN)):
    return eligible_pools(pools, ALLOWLIST, source=SOURCE, observed_at=OBSERVED)


class _Reader:
    """A router that quotes and knows its block, and can do nothing else."""

    def __init__(self, quote=None, block=115_174_800):
        self._quote = quote
        self._block = block
        self.quoted: list[tuple] = []

    def amounts_out(self, amount_in, route):
        self.quoted.append((amount_in, tuple(route)))
        return [amount_in, self._quote if self._quote is not None else amount_in * 2]

    def block_number(self):
        return self._block


# ------------------------------------------------------------------------ compare


def test_the_net_rate_is_not_the_gross_one_and_the_gap_is_the_protocol_cut():
    """The pool charged 250 and the protocol kept 82, so quoting 250 would overstate what
    a liquidity provider keeps by about half again."""
    candidate = next(c for c in compare(CURRENT, _universe()) if c.pool_id == "0xcurrent")
    assert candidate.gross_fee_apr == pytest.approx(250 * 365 / 1_000_000)
    assert candidate.net_fee_apr == pytest.approx((250 - 82) * 365 / 1_000_000)
    assert candidate.net_fee_apr < candidate.gross_fee_apr
    assert candidate.gross_fee_apr / candidate.net_fee_apr > 1.4


def test_every_rate_carries_the_window_it_was_observed_over_and_what_it_is_over():
    record = compare(CURRENT, _universe())[0].as_record()
    assert "24h" in record["rate_window"]
    assert "not a forecast" in record["rate_window"].lower()
    assert "tvl" in record["rate_denominator"].lower()
    assert "position" in record["rate_denominator"].lower()


def test_a_candidate_carries_the_liquidity_and_turnover_behind_its_rate():
    record = next(c for c in compare(CURRENT, _universe()) if c.pool_id == "0xthin").as_record()
    assert record["tvl_usd"] == 60_000.0
    assert record["turnover"] == pytest.approx(0.5)
    assert record["fee_usd_24h"] == 600.0
    assert record["protocol_fee_usd_24h"] == 200.0


def test_the_comparison_is_ordered_by_one_named_observed_metric():
    """Not a recommendation. An order with no stated basis is the one a reader reads as
    Docket's opinion."""
    candidates = compare(CURRENT, _universe())
    assert [c.pool_id for c in candidates] == ["0xthin", "0xricher", "0xcurrent"]
    assert "net_fee_apr" in ORDERING
    assert "observed" in ORDERING.lower()


def test_each_candidate_states_how_far_its_rate_is_from_the_current_one():
    candidates = {c.pool_id: c for c in compare(CURRENT, _universe())}
    current = candidates["0xcurrent"]
    assert current.net_fee_apr_delta == pytest.approx(0.0)
    assert candidates["0xricher"].net_fee_apr_delta > 0
    assert candidates["0xricher"].net_fee_apr_delta == pytest.approx(
        candidates["0xricher"].net_fee_apr - current.net_fee_apr
    )


def test_a_current_pool_the_gate_turned_away_is_said_rather_than_compared_against():
    """The pool the capital sits in can itself fail the gate. Comparing against a rate
    that could not be computed would produce a delta out of a number nobody has."""
    broken = _pool("0xbroken", fee=None)
    candidates = compare(broken, _universe())
    assert all(c.net_fee_apr_delta is None for c in candidates)
    assert "could not be computed" in candidates[0].as_record()["delta_note"].lower()


# --------------------------------------------------------------------- break-even


def test_the_break_even_states_the_days_it_takes_to_recover_the_switching_cost():
    candidates = {c.pool_id: c for c in compare(CURRENT, _universe())}
    out = break_even(
        candidates["0xcurrent"],
        candidates["0xricher"],
        position_size_usd=10_000,
        switching_cost_usd=12,
    )
    extra_apr = candidates["0xricher"].net_fee_apr - candidates["0xcurrent"].net_fee_apr
    assert out["extra_usd_per_day"] == pytest.approx(10_000 * extra_apr / 365)
    assert out["days_to_recover"] == pytest.approx(12 / (10_000 * extra_apr / 365))
    assert out["within_horizon"] is True
    assert out["horizon_days"] == HORIZON_DAYS


def test_the_cost_the_caller_supplies_is_named_rather_than_invented():
    """Docket reads no BNB price and will not make one up, so the switching cost is the
    caller's figure — and the record says what that figure has to cover."""
    candidates = {c.pool_id: c for c in compare(CURRENT, _universe())}
    out = break_even(
        candidates["0xcurrent"],
        candidates["0xricher"],
        position_size_usd=10_000,
        switching_cost_usd=12,
    )
    covers = out["cost_covers"].lower()
    for term in ("gas", "price impact", "caller"):
        assert term in covers, term


def test_a_candidate_whose_rate_is_no_higher_recovers_nothing_and_says_so():
    candidates = {c.pool_id: c for c in compare(RICHER, _universe())}
    out = break_even(
        candidates["0xricher"],
        candidates["0xcurrent"],
        position_size_usd=10_000,
        switching_cost_usd=12,
    )
    assert out["days_to_recover"] is None
    assert out["within_horizon"] is False
    assert "not above" in out["reason"].lower()


def test_a_higher_rate_with_a_break_even_past_the_horizon_is_shown_and_labelled():
    """The failure this test exists to prevent is a comparison that quietly drops the
    candidate that would have embarrassed it."""
    candidates = {c.pool_id: c for c in compare(CURRENT, _universe())}
    out = break_even(
        candidates["0xcurrent"],
        candidates["0xthin"],
        position_size_usd=200,
        switching_cost_usd=40,
    )
    assert out["days_to_recover"] > HORIZON_DAYS
    assert out["within_horizon"] is False
    assert "horizon" in out["method"].lower()


def test_the_break_even_method_is_stated_inline_with_its_arithmetic():
    candidates = {c.pool_id: c for c in compare(CURRENT, _universe())}
    method = break_even(
        candidates["0xcurrent"],
        candidates["0xricher"],
        position_size_usd=10_000,
        switching_cost_usd=12,
    )["method"]
    for term in ("365", "switching_cost", "position_size"):
        assert term in method, term


# ---------------------------------------------------------------------- plan_move


def _move(**overrides):
    fields = {
        "token_in": USDC,
        "token_out": WBNB,
        "amount": 1_000 * E18,
        "cap": 5_000 * E18,
        "reader": _Reader(),
        "wallet": WALLET,
    }
    fields.update(overrides)
    universe = fields.pop("universe", _universe())
    candidate = next(c for c in compare(CURRENT, universe) if c.pool_id == "0xricher")
    return plan_move(candidate, universe, **fields)


def test_a_move_is_one_swap_leg_built_through_the_stage_two_kernel():
    actions = _move()
    assert len(actions) == 1
    intent = actions[0].intent
    assert isinstance(intent, ActionIntent)
    assert intent.target == PANCAKE_V2_ROUTER
    assert intent.token_in == Web3.to_checksum_address(USDC)
    assert intent.token_out == Web3.to_checksum_address(WBNB)
    assert intent.policy_version == POLICY_VERSION
    assert intent.matches(actions[0].calldata)


def test_the_floor_comes_from_a_live_quote_less_the_slippage_allowed():
    reader = _Reader(quote=3 * E18)
    intent = _move(reader=reader, amount=1_000 * E18)[0].intent
    # Checksummed before the quote as well as before the encode, so the bytes that get
    # hashed into the commitment are the same however the caller spelled the addresses.
    checksummed = (Web3.to_checksum_address(USDC), Web3.to_checksum_address(WBNB))
    assert reader.quoted == [(1_000 * E18, checksummed)]
    assert intent.min_output == 3 * E18 * (10_000 - intent.slippage_bps) // 10_000


def test_the_move_says_the_liquidity_add_is_not_built_here():
    """Half the move is missing on purpose, and saying so is the difference between a
    bounded build and an overstated one."""
    action = _move()[0]
    lowered = action.not_built.lower()
    assert "liquidity" in lowered
    assert "not" in lowered


def test_a_destination_outside_the_stated_universe_is_refused():
    """The eligible set is the destination allowlist. A pool that did not clear the gate is
    not somewhere this build routes to, whatever its rate says."""
    thin_only = eligible_pools([THIN], ALLOWLIST, source=SOURCE, observed_at=OBSERVED)
    candidate = next(c for c in compare(CURRENT, _universe()) if c.pool_id == "0xricher")
    with pytest.raises(ValueError) as exc:
        plan_move(
            candidate,
            thin_only,
            token_in=USDC,
            token_out=WBNB,
            amount=E18,
            cap=E18,
            reader=_Reader(),
            wallet=WALLET,
        )
    assert "0xricher" in str(exc.value)


@pytest.mark.parametrize("field", ["token_in", "token_out"])
def test_an_asset_outside_the_allowlist_is_refused(field):
    with pytest.raises(ValueError) as exc:
        _move(**{field: "0x000000000000000000000000000000000000dEaD"})
    assert "allowlist" in str(exc.value).lower()


def test_an_amount_past_the_cap_is_refused_rather_than_trimmed():
    """Silently shrinking to the cap would send an action nobody asked for."""
    with pytest.raises(ValueError) as exc:
        _move(amount=6_000 * E18, cap=5_000 * E18)
    assert "cap" in str(exc.value).lower()


def test_the_allowlist_is_short_on_purpose_and_says_why():
    assert len(MOVE_ASSETS) <= 4
    assert all(a == Web3.to_checksum_address(a) for a in MOVE_ASSETS)


# ------------------------------------------------------------------------ preview


def _preview(**overrides):
    fields = {"universe": _universe(), "current": CURRENT}
    fields.update(overrides)
    return YieldRouterPreview(**fields)


def test_the_preview_is_a_full_comparison_with_no_wallet_anywhere_in_it():
    out = _preview().preview(position_size_usd=10_000, switching_cost_usd=12)
    assert out["submitted"] is False
    assert out["why_not_submitted"] == PREVIEW_REASON
    assert len(out["candidates"]) == 3
    assert out["actions"] == []
    assert out["universe"]["source"] == SOURCE


def test_every_candidate_in_the_preview_carries_its_own_break_even():
    out = _preview().preview(position_size_usd=200, switching_cost_usd=40)
    for candidate in out["candidates"]:
        assert "break_even" in candidate
        assert candidate["break_even"]["horizon_days"] == HORIZON_DAYS
    beyond = [c for c in out["candidates"] if c["break_even"]["within_horizon"] is False]
    assert beyond, "this test means nothing if every candidate pays for itself"


def test_the_preview_carries_the_universe_that_bounds_every_claim_in_it():
    out = _preview().preview(position_size_usd=10_000, switching_cost_usd=12)
    assert out["universe"]["size"] == 3
    assert "within" in out["universe"]["bound"].lower()
    assert out["ordering"] == ORDERING


def test_a_preview_handed_a_recipient_drafts_the_swap_leg_and_still_sends_nothing():
    out = _preview(reader=_Reader()).preview(
        position_size_usd=10_000,
        switching_cost_usd=12,
        wallet=WALLET,
        token_in=USDC,
        token_out=WBNB,
        amount=1_000 * E18,
        cap=5_000 * E18,
    )
    assert out["submitted"] is False
    assert len(out["actions"]) == 1
    assert out["actions"][0]["intent"]["token_out"] == Web3.to_checksum_address(WBNB)


def test_the_preview_holds_nothing_that_could_send_a_transaction():
    preview = _preview()
    for attribute in ("submit", "step", "send", "_submitter", "_authority", "_signer"):
        assert not hasattr(preview, attribute), attribute


# ------------------------------------------------------------------ what it may say


def _strings(value):
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [s for k, v in value.items() for s in _strings(k) + _strings(v)]
    if isinstance(value, list):
        return [s for v in value for s in _strings(v)]
    return []


# -------------------------------------------------------------------- the hire path


class _PoolClient:
    """The explorer, stubbed. No request leaves this file."""

    def __init__(self, *a, **kw):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return None

    def top_pools(self, chain="bsc", version="v3"):
        return [CURRENT, RICHER, THIN]

    def token_allowlist(self):
        return set(ALLOWLIST)


@pytest.fixture
def hire(monkeypatch):
    from docket.hire.catalogue import _run_yield_router

    monkeypatch.setattr("docket.agents.pancake.pools.PoolClient", _PoolClient)
    return _run_yield_router


def test_the_hire_names_which_pool_it_used_as_the_baseline(hire):
    out = hire({"pool": "0xricher"})
    assert out["current"]["pool_id"] == "0xricher"
    assert "0xricher" in out["current_pool_chosen_by"]


def test_a_baseline_named_in_another_casing_is_still_the_pool_it_names(hire):
    """The explorer serves ids lowercase and a caller pasting a checksummed address is
    naming the same pool. Failing to match it would silently compare against a different
    baseline."""
    out = hire({"pool": "0xRICHER"})
    assert out["current"]["pool_id"] == "0xricher"


def test_a_baseline_that_is_not_in_the_set_is_said_rather_than_quietly_substituted(hire):
    """The failure this test exists to prevent: a named pool that is not in the eligible
    set falling back to the deepest one while the payload reports that no pool was named.
    Every delta in the response is measured from this row, so a false sentence about which
    row it is misdescribes the whole comparison."""
    out = hire({"pool": "0xnowhere"})
    said = out["current_pool_chosen_by"]
    assert out["current"]["pool_id"] == "0xcurrent"
    assert "0xnowhere" in said
    assert "not in the eligible set" in said
    assert "no pool was named" not in said


def test_a_hire_that_names_no_pool_says_the_baseline_stood_in(hire):
    out = hire({})
    assert out["current"]["pool_id"] == "0xcurrent"
    assert "no pool was named" in out["current_pool_chosen_by"]
    assert "not a pool anybody is known to be in" in out["current_pool_chosen_by"]


def test_the_hire_needs_no_wallet_and_drafts_nothing(hire):
    out = hire({})
    assert out["actions"] == []
    assert out["submitted"] is False


# ------------------------------------------------------------------ what it may say


def test_no_string_in_the_output_implies_a_docket_recommendation():
    out = _preview(reader=_Reader()).preview(
        position_size_usd=200,
        switching_cost_usd=40,
        wallet=WALLET,
        token_in=USDC,
        token_out=WBNB,
        amount=E18,
        cap=E18,
    )
    for text in _strings(out):
        for word in BANNED_FIELD_NAMES:
            assert not re.search(rf"\b{re.escape(word)}\b", text.lower()), (
                f"the router carries verdict language {word!r} in {text[:70]!r}"
            )
    for word in ("optimal", "should move", "we suggest"):
        assert not any(word in text.lower() for text in _strings(out)), word
