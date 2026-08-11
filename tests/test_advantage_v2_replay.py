"""A replay of a plan against recorded observations, and everything that keeps it one.

Nothing here is a trading record. No transaction was sent, none of the three arms touched a
chain, and the arithmetic below is what a plan already in the repository would have committed
to had somebody run it over a month of prices that had already happened. That sentence is not
a disclaimer bolted onto the end: it is asserted as the first sentence of the run record and
of every arm inside it, because a reader who lands on one arm and not on the record's preamble
must still meet it.

The traps these tests exist for are the ones that turn a replay into a fiction. A band chosen
after seeing where the price went would guarantee triggers, so the band is a function of the
first candle's open alone and that is asserted rather than described. A ladder that re-armed
would count the same level many times, so the first-touch behaviour is asserted on a series
where the price crosses a level twice. And a comparison against a null nobody can reproduce
would be a number to take on trust, so the random arm is asserted to be identical across two
calls at the registered seed.

The series is Binance's own public market-data endpoint, the window is closed, and the file is
the response body byte for byte — so its digest is checkable by re-fetching rather than only by
trusting this repository. That check ran during the recorded run and its result is in the
record; these tests check the local half, that the committed bytes still hash to what the
pre-registration cites.
"""

import hashlib
import json
from pathlib import Path


from docket.advantage.v2 import replay
from docket.advantage.v2.spec import load
from docket.agents.grid.plan import next_action

ROOT = Path(__file__).resolve().parents[1]
SERIES_PATH = ROOT / "docket/advantage/v2/corpus/series/bnbusdt-1h-2026-07.json"
SPEC_PATH = ROOT / "docket/advantage/v2/specs/04-grid-replay.json"
RUN_PATH = ROOT / "docket/advantage/v2/runs/04-grid-replay.json"

SERIES = replay.load_series(SERIES_PATH)
RUN = json.loads(RUN_PATH.read_text(encoding="utf-8"))
E18 = 10**18


def _series(*closes, first_open=600):
    """A hand-made series: one candle per close, all at the same hour spacing."""
    return tuple(
        {
            "open_time": 1_000 + index,
            "open": (first_open if index == 0 else closes[index - 1]) * E18,
            "high": close * E18,
            "low": close * E18,
            "close": close * E18,
        }
        for index, close in enumerate(closes)
    )


def test_a_price_string_becomes_atomic_units_without_going_through_a_float():
    """Binance serves prices as decimal strings and the grid takes integers of quote atomic
    units. Routing that through a float would put binary residue into a level comparison that
    is exact by design — 546.52 is not representable, and the plan's whole point is that its
    levels are the same integers on every machine."""
    assert replay.to_atomic("546.52000000") == 546_520_000_000_000_000_000
    assert replay.to_atomic("0.00000001") == 10_000_000_000
    assert replay.to_atomic("587.01000000") == 587_010_000_000_000_000_000


def test_the_committed_series_is_the_window_the_registration_names():
    """The file is the response body byte for byte, so this is the local half of the digest
    check: the bytes the pre-registration cites are still the bytes on disk. 744 hourly candles
    is July 2026 exactly — a closed window, which is what makes the same URL return the same
    bytes to anybody who re-fetches it."""
    spec = load(SPEC_PATH)

    assert len(SERIES) == spec.n_planned == 744
    assert spec.dataset_sha256 == hashlib.sha256(SERIES_PATH.read_bytes()).hexdigest()
    assert (ROOT / spec.dataset_ref).resolve() == SERIES_PATH.resolve()
    assert SERIES[0]["open_time"] == 1_782_864_000_000
    assert SERIES[-1]["open_time"] == 1_785_538_800_000
    assert SERIES[0]["open"] == replay.to_atomic("546.52000000")
    assert "data-api.binance.vision" in spec.stopping_rule
    assert "data-api.binance.vision" in replay.SERIES_URL


def test_the_band_is_derived_from_the_first_observation_and_nothing_later():
    """The pre-registration's defence against a band tuned to the window. Every input to the
    plan is a constant or a function of candle zero's open, so a series whose later candles are
    replaced wholesale must build the identical plan — asserted by doing exactly that."""
    plan = replay.build_replay_plan(SERIES)
    reference = SERIES[0]["open"]

    assert plan.reference == reference
    assert plan.lower == reference * 95 // 100
    assert plan.upper == reference * 105 // 100
    assert plan.requested_levels == 11
    assert plan.size_per_level == 100 * E18
    rewritten = (SERIES[0],) + tuple(dict(candle, close=1) for candle in SERIES[1:])
    assert replay.build_replay_plan(rewritten).plan_hash == plan.plan_hash


def test_a_level_fires_once_and_the_ladder_never_re_arms():
    """A cycling grid would count the same level every time the price came back to it, and this
    plan does not cycle: `next_action` takes the filled set and returns nothing for a level
    already in it. The series here crosses the same level three times and the replay counts one
    trigger, which is what makes the reported number first-touch triggers of a one-shot ladder
    rather than a trade count."""
    plan = replay.build_replay_plan(_series(600, first_open=600))
    once = 594  # one percent under the reference, so exactly the first buy level

    fired = replay.replay(plan, _series(once, 600, once, 600, once))

    assert [trigger["level_index"] for trigger in fired["triggers"]] == [4]
    assert fired["triggers"][0]["side"] == "buy"
    assert fired["n_candles"] == 5
    # And the same fact one level down: `next_action` itself refuses a filled index.
    level = plan.levels[4]
    assert next_action(plan, level.price, filled=(4,)) is None


def test_a_price_outside_the_band_fires_nothing_at_either_end():
    """`next_action` returns None outside `[lower, upper]`, so a price that gapped clean through
    the ladder triggers no level at all rather than the nearest one. It is a property of the
    shipped plan and the replay inherits it, so the record's trigger count means "levels the
    price came to rest on inside the band" and not "levels the price passed"."""
    plan = replay.build_replay_plan(_series(600, first_open=600))

    assert replay.replay(plan, _series(400, 900))["triggers"] == []


def test_buy_and_hold_commits_the_same_quote_at_the_first_close():
    """Same money, one trade, first hour. Holding the total fixed is what makes the two average
    prices comparable at all — an arm that deployed more or less would differ in size as well
    as in timing, and the comparison would not be about timing."""
    series = _series(600, 500, 700)

    arm = replay.buy_and_hold(series, 500 * E18)

    assert arm["quote_committed"] == 500 * E18
    assert arm["average_buy_price"] == 600 * E18
    assert arm["base_acquired"] == 500 * E18 * E18 // (600 * E18)
    assert arm["method"].startswith(replay.REPLAY_NOTICE)


def test_the_random_arm_is_reproducible_from_the_registered_seed():
    """A null nobody can re-run is a number to take on trust. Two calls at the registered seed
    have to be identical, and a different seed has to move — otherwise the seed is decoration
    and the distribution could have been drawn until it flattered the replay."""
    series = _series(*range(590, 620))

    first = replay.random_entry(series, trades=3, draws=50, seed=20260811)
    again = replay.random_entry(series, trades=3, draws=50, seed=20260811)
    other = replay.random_entry(series, trades=3, draws=50, seed=1)

    assert first == again
    assert first["average_buy_price"] != other["average_buy_price"]
    assert first["average_buy_price"]["n"] == 50
    assert first["trades"] == 3
    assert first["method"].startswith(replay.REPLAY_NOTICE)


def test_an_average_price_over_no_buys_is_null_and_the_comparison_says_it_is_empty():
    """The third way the falsifier can fire. A window the ladder never reached leaves nothing to
    compare, and a zero there would be a price nobody paid — so the average is null, the share
    of draws that did worse is a rate over a denominator of zero, and the record says the
    comparison is empty rather than reporting a result."""
    plan = replay.build_replay_plan(_series(600, first_open=600))

    measured = replay.measure(_series(600, 601, 602), plan=plan)

    assert measured["replay"]["n_buy_triggers"] == 0
    assert measured["replay"]["average_buy_price"] is None
    assert measured["random_entry"]["draws_worse_than_the_replay"]["denominator"] == 0
    assert measured["random_entry"]["draws_worse_than_the_replay"]["value"] is None
    assert measured["comparison_is_empty"] is True
    assert measured["falsifier_result"]["refuted"] is True


def test_every_arm_in_the_committed_record_opens_with_the_same_sentence():
    """A reader can land on any arm of this record, in the JSON or on the page, without having
    read the preamble first. So the sentence is on the record, on its method, and on each of the
    three arms — and it says what it says with no hedge: nothing was sent."""
    assert RUN["notice"] == replay.REPLAY_NOTICE
    assert RUN["method"].startswith(replay.REPLAY_NOTICE)
    for arm in ("replay", "buy_and_hold", "random_entry"):
        assert RUN[arm]["method"].startswith(replay.REPLAY_NOTICE), arm
    assert "not a trading record" in replay.REPLAY_NOTICE


def test_the_record_cites_the_registration_and_recomputes_to_the_same_figures():
    """The record's figures, recomputed from the series it cites. Everything here is
    deterministic — the plan, the trigger rule and the seeded draws alike — so a recompute that
    disagreed would mean the published numbers came from something other than the committed
    code and the committed series.

    The figures are the ones the run actually produced, and they refute the claim: over this
    window the lowest close is 542.21 and the highest buy level is 541.0548, so not one of the
    five buy levels fired and there is no average buy price to place against either null. Four
    of the five sell levels did fire, against base the ladder never bought. This test asserts
    that outcome rather than the one the registration hoped for, because pinning the counts is
    what stops a later edit turning an empty comparison into a quiet one."""
    spec = load(SPEC_PATH)
    recomputed = replay.measure(SERIES)

    assert RUN["spec_hash"] == spec.spec_hash
    assert RUN["spec_id"] == spec.spec_id == "04-grid-replay"
    assert RUN["dataset_sha256"] == spec.dataset_sha256
    for arm in ("replay", "buy_and_hold", "random_entry"):
        assert RUN[arm] == recomputed[arm], arm
    assert RUN["falsifier_result"] == recomputed["falsifier_result"]
    assert RUN["comparison_is_empty"] == recomputed["comparison_is_empty"] is True
    assert RUN["replay"]["n_buy_triggers"] == 0
    assert RUN["replay"]["n_sell_triggers"] == 4
    assert RUN["replay"]["average_buy_price"] is None


def test_the_record_names_the_assumptions_that_move_the_number():
    """Each of these changes the answer, so each is stated inline rather than in a footnote: the
    fills are free and exact, which no real fill is; the series is a centralised venue's and the
    plan addresses an on-chain pair; and the two arms hold different amounts of base for the
    same allocation, which is a different position rather than a better one. Over this window
    that last one is at its extreme — the ladder deployed nothing at all and holds no base,
    where the null put the whole allocation in at the first close and holds 0.9126 of it."""
    method = RUN["method"]

    assert "no fee, no slippage" in method
    assert "centralised" in method
    assert "not a better outcome" in method
    assert RUN["replay"]["base_acquired"] < RUN["buy_and_hold"]["base_acquired"]


def test_the_falsifier_result_is_computed_from_the_figures_and_not_asserted():
    """A falsifier nobody evaluates is a sentence. This one is evaluated clause by clause
    against the measured numbers, each clause carrying what was observed, and the record's
    verdict on itself is the conjunction of them rather than a claim written by hand.

    It fired. It fired in the third way the registration named — no buy level fired at all — and
    the other two clauses fire with it, because a ladder that bought nothing did not obtain a
    lower average price than either null; it obtained no average price. The record says the
    claim is refuted and does not restate it as though it had been established, which is the
    property this test exists to hold on to."""
    result = RUN["falsifier_result"]

    assert {clause["clause"] for clause in result["checks"]} == {
        "no_buy_level_fired",
        "average_buy_price_not_below_buy_and_hold",
        "fewer_than_half_the_draws_did_worse",
    }
    assert result["refuted"] == any(clause["refuted"] for clause in result["checks"])
    assert result["refuted"] is True
    assert RUN["claim_refuted"] is True
    assert [clause["refuted"] for clause in result["checks"]] == [True, True, True]
    for clause in result["checks"]:
        assert clause["observed"].strip()
