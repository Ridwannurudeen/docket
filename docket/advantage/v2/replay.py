"""A plan replayed over prices that had already happened, and the fences that keep it one.

No transaction was sent. Every figure this module produces is what a plan already in this
repository would have committed to had somebody run it over a month of recorded prices, and
that sentence is `REPLAY_NOTICE` — carried on the record and on each of the three arms,
because a reader can land on an arm without meeting the preamble that wraps it.

Three fences, because a replay is the easiest experiment in this build to fake.

The **band is a function of the first candle's open and nothing later**. Every other input is
a constant registered before the run. A band chosen after seeing where the month went would
guarantee triggers, and the guarantee would be the finding; here a series whose later candles
are replaced wholesale still builds the same plan, and the test asserts exactly that rather
than trusting this paragraph.

The **ladder is one-shot**. `next_action` takes the set of levels already filled and returns
nothing for one of them, so a price that returns to a level a second time buys nothing. What
is counted is first-touch triggers, not trades, and a cycling grid would have counted the same
level all month.

The **nulls are computed, and the random one is seeded**. Buy-and-hold is the thing a ladder
is an alternative to; random entry holds the trade count, the size and the window fixed and
varies only which moments were chosen, which is the only one of the two that can separate the
rule from the mere act of spreading an entry out. The seed is in the pre-registration, so the
distribution is re-drawable rather than quotable.

Two arithmetic choices worth naming. Prices arrive from Binance as decimal strings and become
integers of quote atomic units without passing through a float: 546.52 is not representable in
binary, and the levels are exact integer comparisons on every machine by design. And where a
draw's average has to be summarised, the median of an even sample is the lower of its two
central draws rather than their mean — averaging two integer prices would report a price no
draw actually paid, which is the same objection that makes a rate over zero observations null
rather than zero.

What this module does not do is decide whether the claim held. It computes the figures, then
evaluates the registered falsifier clause by clause against them and reports the conjunction.
A falsifier nobody evaluates is a sentence in a file.
"""

import hashlib
import json
import random
import statistics
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx

from ...agents.grid.plan import build_plan, next_action
from ...hire.catalogue import GRID_BASE, GRID_BASE_DECIMALS, GRID_QUOTE
from .scoring import rate
from .spec import load

# The sentence every record and every arm opens with. It is a constant so that the record, the
# arms and the served page cannot each carry their own softer wording.
REPLAY_NOTICE = (
    "No transaction was sent. This is a replay of a plan against recorded observations, and it "
    "is not a trading record."
)

# The registered series, verbatim. The window is closed and entirely in the past, so the same
# URL returns the same bytes to anybody who re-fetches it — which is what makes the committed
# file's digest checkable rather than only citable.
SERIES_URL = (
    "https://data-api.binance.vision/api/v3/klines"
    "?symbol=BNBUSDT&interval=1h&startTime=1782864000000&endTime=1785542399999&limit=1000"
)
# Binance serves eight decimals; the grid's prices are quote atomic units per whole base, and
# BSC's USDT is 18 decimals rather than the 6 it carries on Ethereum.
PRICE_DECIMALS = 18
# The plan inputs, all registered before the run and none of them read from the series beyond
# its first observation.
BAND_PCT = 5
LEVELS = 11
SIZE_PER_LEVEL = 100 * 10**18
# The random null's registered draw count and seed. Both are in the pre-registration, so the
# whole distribution is reproducible by a reader who has only this file and the series.
DRAWS = 1000
SEED = 20260811
# One read-only GET, retried the way every other upstream in this build is retried.
MAX_ATTEMPTS = 4
BACKOFF_S = (1.0, 3.0, 8.0)


def to_atomic(text: str) -> int:
    """A decimal price string as an integer of quote atomic units.

    String arithmetic rather than `float(text) * 10**18`: the levels are exact integer
    comparisons, and a binary residue in one of them would make a trigger a property of the
    machine that computed it.
    """
    whole, _, fraction = str(text).partition(".")
    if len(fraction) > PRICE_DECIMALS:
        raise ValueError(
            f"replay: {text!r} carries more than {PRICE_DECIMALS} decimals — truncating it "
            "would move a price silently, and the series is meant to be the response verbatim"
        )
    return int(whole) * 10**PRICE_DECIMALS + int((fraction + "0" * PRICE_DECIMALS)[:PRICE_DECIMALS])


def _as_decimal(atomic: int) -> str:
    """An atomic price back as a decimal string, for prose. Exact, so no float appears here."""
    whole, fraction = divmod(atomic, 10**PRICE_DECIMALS)
    return f"{whole}.{fraction:0{PRICE_DECIMALS}d}".rstrip("0").rstrip(".")


def load_series(path) -> tuple[dict, ...]:
    """The committed response body as candles, in the order Binance served them.

    Binance's kline rows are positional arrays; the four prices and the open time are what a
    replay needs, and the rest of each row travels in the committed file for a reader who wants
    to check it. Highs and lows are read and are deliberately not offered to the plan — see
    `replay`, where that choice is stated as the understatement it is.
    """
    rows = json.loads(Path(path).read_text(encoding="utf-8"))
    return tuple(
        {
            "open_time": row[0],
            "open": to_atomic(row[1]),
            "high": to_atomic(row[2]),
            "low": to_atomic(row[3]),
            "close": to_atomic(row[4]),
        }
        for row in rows
    )


def build_replay_plan(series):
    """The shipped grid plan, built from candle zero's open and registered constants.

    `build_plan` is the module the marketplace sells, not a copy of it: a replay of a
    re-implementation would be evidence about the re-implementation. The pair is the one the
    grid preview defaults to, imported rather than retyped so a changed address changes the
    plan hash the run record carries.
    """
    reference = series[0]["open"]
    return build_plan(
        lower=reference * (100 - BAND_PCT) // 100,
        upper=reference * (100 + BAND_PCT) // 100,
        levels=LEVELS,
        size_per_level=SIZE_PER_LEVEL,
        base=GRID_BASE,
        quote=GRID_QUOTE,
        base_decimals=GRID_BASE_DECIMALS,
        reference=reference,
    )


def replay(plan, series) -> dict:
    """Walk the candles once, offering each close to the plan and recording what it fires.

    Only the close is offered. A venue would have filled on an intra-hour wick, so this
    understates triggers against one that did — the direction of the error is stated because it
    is the direction that flatters nothing here.

    `filled` is the caller's memory, which is what keeps `next_action` a function: a level that
    has fired is passed back in and is never returned again, so the count is first-touch
    triggers of a one-shot ladder rather than a trade count.
    """
    filled: list[int] = []
    triggers = []
    for index, candle in enumerate(series):
        level = next_action(plan, candle["close"], filled=filled)
        if level is None:
            continue
        filled.append(level.index)
        trigger = {
            "candle_index": index,
            "open_time": candle["open_time"],
            "level_index": level.index,
            "side": level.side,
            "price": level.price,
            "close": candle["close"],
        }
        if level.side == "buy":
            trigger["quote_committed"] = level.size
            trigger["base_acquired"] = level.size * 10**GRID_BASE_DECIMALS // level.price
        else:
            trigger["base_offered"] = level.size
        triggers.append(trigger)
    return {"n_candles": len(series), "triggers": triggers}


def buy_and_hold(series, quote: int) -> dict:
    """The whole allocation, in one trade, at the first candle's close.

    The arm the ladder is an alternative to, and the one that says what a lower average price
    does not mean: this null is in the market from the first hour and a ladder is not, so the
    two carry different exposure for the same money. The base it acquired is reported beside
    the price it paid for exactly that reason.
    """
    price = series[0]["close"]
    return {
        "trades": 1,
        "quote_committed": quote,
        "average_buy_price": price,
        "base_acquired": quote * 10**GRID_BASE_DECIMALS // price,
        "method": (
            f"{REPLAY_NOTICE} The whole allocation of {_as_decimal(quote)} quote committed once "
            f"at the first candle's close, {_as_decimal(price)}, and held to the end of the "
            "window. Its average buy price is that close by construction. Base acquired floors "
            "at the fill, as it does in every arm here."
        ),
    }


def _distribution(values) -> dict:
    """The spread and the count it came from, kept in exact integers.

    `liquidity.distribution` does this job for float rates; prices here are atomic integers
    around 1e20, where a mean of two central draws would both lose precision and report a price
    no draw paid. So the median is the lower of the two central draws, and it is a price
    somebody's draw actually obtained.
    """
    values = list(values)
    return {
        "n": len(values),
        "min": min(values) if values else None,
        "median": statistics.median_low(values) if values else None,
        "max": max(values) if values else None,
    }


def random_entry(series, *, trades: int, draws: int, seed: int, size_per_trade=SIZE_PER_LEVEL):
    """The same money, in the same number of trades, at moments nobody chose.

    Each draw takes `trades` distinct candles uniformly without replacement from the window and
    buys `size_per_trade` of quote at each of their closes. The trade count, the size and the
    window are held to the replay's, so the only thing that varies is which moments were
    picked — which is the one thing the grid claims to choose well.

    Every draw is kept, not only the summary. A distribution quoted without the draws behind it
    is a number a reader cannot contest, and the seed is registered so those draws can be
    re-produced rather than trusted.

    A replay that never bought leaves nothing to match: `trades` is zero, no draw is taken, and
    the emptiness is reported rather than filled in with a distribution over trades of nothing.
    """
    closes = [candle["close"] for candle in series]
    generator = random.Random(seed)
    drawn = []
    if trades > 0:
        for index in range(draws):
            picked = generator.sample(range(len(closes)), trades)
            base = sum(size_per_trade * 10**GRID_BASE_DECIMALS // closes[pick] for pick in picked)
            drawn.append(
                {
                    "draw_index": index,
                    "candle_indices": sorted(picked),
                    "quote_committed": size_per_trade * trades,
                    "base_acquired": base,
                    "average_buy_price": size_per_trade * trades * 10**GRID_BASE_DECIMALS // base,
                }
            )
    return {
        "trades": trades,
        "size_per_trade": size_per_trade,
        "quote_committed": size_per_trade * trades,
        "seed": seed,
        "draws_planned": draws,
        "n_drawn": len(drawn),
        "draws": drawn,
        "average_buy_price": _distribution([draw["average_buy_price"] for draw in drawn]),
        "method": (
            f"{REPLAY_NOTICE} {len(drawn)} draws of the planned {draws} from "
            f"random.Random({seed}), each committing {_as_decimal(size_per_trade)} of quote at "
            f"each of {trades} candle closes drawn uniformly without replacement from the "
            f"{len(closes)} in the window. Every draw is listed with the candles it picked, so "
            "the distribution can be re-drawn rather than taken on trust; the median of an even "
            "sample is the lower of its two central draws, which is a price a draw obtained "
            "rather than the mean of two that no draw paid."
            + (
                ""
                if trades > 0
                else " No draw was taken: the replay bought at no level, so there is no trade "
                "count to match and no total to commit. That is reported as an empty comparison "
                "rather than as a distribution over trades of nothing."
            )
        ),
    }


def _falsifier_checks(*, buys, average, hold_price, worse) -> list[dict]:
    """The registered falsifier, clause by clause, each carrying what was observed.

    Every clause is evaluated against the measured figures rather than written by hand, and the
    record's verdict on itself is their conjunction. The middle and last clauses are refuted
    where the first one is, because a ladder that never bought did not obtain a lower average
    price than either null — it obtained no average price at all, and reporting the two clauses
    as unrefuted would read as a claim that survived them.
    """
    empty = average is None
    share = worse["value"]
    return [
        {
            "clause": "no_buy_level_fired",
            "refuted": empty,
            "observed": (
                f"{len(buys)} buy levels fired over the window."
                if not empty
                else "No buy level fired over the window, so the ladder committed nothing and "
                "there is no average buy price to compare against either null."
            ),
        },
        {
            "clause": "average_buy_price_not_below_buy_and_hold",
            "refuted": empty or average >= hold_price,
            "observed": (
                f"The replay's average buy price is {_as_decimal(average)} against "
                f"{_as_decimal(hold_price)} at the first close."
                if not empty
                else f"There is no replayed average buy price to place against the first "
                f"close, {_as_decimal(hold_price)}."
            ),
        },
        {
            "clause": "fewer_than_half_the_draws_did_worse",
            "refuted": share is None or share < 0.5,
            "observed": (
                f"{worse['numerator']} of {worse['denominator']} seeded draws obtained a higher "
                "average buy price than the replay."
                if share is not None
                else "No draw was comparable: the replay bought at no level, so the share of "
                "draws that did worse is a rate over a denominator of zero and is reported null."
            ),
        },
    ]


def measure(series, *, plan=None) -> dict:
    """The three arms over one series, and the falsifier evaluated against them.

    Deterministic in the series alone — the plan, the trigger rule and the seeded draws all
    are — so a recompute that disagreed with the committed record would mean the published
    figures came from something other than this code and that series. Nothing observed while
    the run happened (a clock, a re-fetch) is folded in here for that reason; those belong to
    the record, not to an arm.

    Buy-and-hold commits the ladder's whole buy-side capacity rather than only the part the
    ladder managed to deploy. That is a reading of the registered baseline and it is the only
    one under which its own registered sentence — in the market from the first hour, different
    exposure for the same money — is true of a window where few levels or none of them fill.
    It moves no bar: the falsifier compares average prices, and an average price is unchanged
    by how much was committed at it.
    """
    plan = plan or build_replay_plan(series)
    fired = replay(plan, series)
    buys = [trigger for trigger in fired["triggers"] if trigger["side"] == "buy"]
    sells = [trigger for trigger in fired["triggers"] if trigger["side"] == "sell"]
    quote = sum(trigger["quote_committed"] for trigger in buys)
    base = sum(trigger["base_acquired"] for trigger in buys)
    average = quote * 10**GRID_BASE_DECIMALS // base if base else None
    buy_levels = [level for level in plan.levels if level.side == "buy"]

    hold = buy_and_hold(series, len(buy_levels) * plan.size_per_level)
    drawn = random_entry(
        series, trades=len(buys), draws=DRAWS, seed=SEED, size_per_trade=plan.size_per_level
    )
    worse = rate(
        sum(1 for draw in drawn["draws"] if draw["average_buy_price"] > average)
        if average is not None
        else 0,
        drawn["n_drawn"],
    )
    drawn["draws_worse_than_the_replay"] = worse
    checks = _falsifier_checks(
        buys=buys, average=average, hold_price=hold["average_buy_price"], worse=worse
    )
    lowest_close = min(candle["close"] for candle in series)
    highest_buy = max((level.price for level in buy_levels), default=0)
    return {
        "replay": fired
        | {
            "plan_hash": plan.plan_hash,
            "n_buy_levels": len(buy_levels),
            "n_sell_levels": len(plan.levels) - len(buy_levels),
            "n_buy_triggers": len(buys),
            "n_sell_triggers": len(sells),
            "quote_committed": quote,
            "base_acquired": base,
            "average_buy_price": average,
            "method": (
                f"{REPLAY_NOTICE} The plan is docket.agents.grid.plan.build_plan at plan hash "
                f"{plan.plan_hash}, its band a function of the first candle's open "
                f"({_as_decimal(plan.reference)}) and of registered constants alone. Each of "
                f"the {fired['n_candles']} candles offers its close, and only its close, to "
                "docket.agents.grid.plan.next_action with the levels already filled; intra-hour "
                "highs and lows are not offered, which understates triggers against a venue "
                "that would have filled on a wick. A filled level never re-arms and a price "
                "outside the band fires nothing, so this is a first-touch count over a one-shot "
                f"ladder and not a trade count. The window's lowest close is "
                f"{_as_decimal(lowest_close)} against a highest buy level of "
                f"{_as_decimal(highest_buy)}. Fills are at the level price with no fee, no "
                "slippage and no partial fill, each of which would raise a real buyer's average "
                "price; base acquired floors at every fill."
            ),
        },
        "buy_and_hold": hold,
        "random_entry": drawn,
        "comparison_is_empty": average is None,
        "falsifier_result": {
            "checks": checks,
            "refuted": any(check["refuted"] for check in checks),
        },
    }


def recheck_dataset(path, *, url: str = SERIES_URL) -> dict:
    """Re-fetch the registered URL and compare its bytes to the committed file.

    The half of the digest check this repository cannot do for itself. A closed window returns
    the same bytes to anybody, so a match means a reader can obtain the series rather than only
    trust it — and a mismatch or a failure is recorded as what it is. Read-only: one GET, no
    credential, nothing sent.
    """
    committed = hashlib.sha256(Path(path).read_bytes()).hexdigest()
    attempts = []
    for attempt in range(MAX_ATTEMPTS):
        try:
            response = httpx.get(url, timeout=30.0, headers={"accept": "application/json"})
            response.raise_for_status()
            fetched = hashlib.sha256(response.content).hexdigest()
            return {
                "url": url,
                "attempts": attempts + [{"attempt": attempt + 1, "error": None}],
                "sha256_committed": committed,
                "sha256_fetched": fetched,
                "bytes_fetched": len(response.content),
                "matches": fetched == committed,
            }
        except httpx.HTTPError as exc:
            attempts.append({"attempt": attempt + 1, "error": f"{type(exc).__name__}: {exc}"})
        if attempt < MAX_ATTEMPTS - 1:
            time.sleep(BACKOFF_S[min(attempt, len(BACKOFF_S) - 1)])
    return {
        "url": url,
        "attempts": attempts,
        "sha256_committed": committed,
        "sha256_fetched": None,
        "bytes_fetched": None,
        "matches": None,
    }


def build_run_record(spec, series, *, started_at: str, finished_at: str, recheck: dict) -> dict:
    """The record, assembled around `measure` by the code that produced it.

    Committed for the reason the arms are: a record whose producer is not in the repository is
    a record nobody can reproduce or review. Everything observed rather than computed — the
    clock, the re-fetch — lives out here at the top level, so the three arms stay pure
    functions of the series and a recompute can check them figure for figure.
    """
    plan = build_replay_plan(series)
    measured = measure(series, plan=plan)
    result = measured["falsifier_result"]
    return measured | {
        "spec_id": spec.spec_id,
        "spec_hash": spec.spec_hash,
        "dataset_ref": spec.dataset_ref,
        "dataset_sha256": spec.dataset_sha256,
        "dataset_recheck": recheck,
        "series_url": SERIES_URL,
        "n_planned": spec.n_planned,
        "n_candles": measured["replay"]["n_candles"],
        "started_at": started_at,
        "finished_at": finished_at,
        "notice": REPLAY_NOTICE,
        "plan": plan.as_record(),
        "claim_refuted": result["refuted"],
        "finding": _finding(measured, recheck),
        "method": (
            f"{REPLAY_NOTICE} Nothing here is an outcome anybody obtained: it is what the "
            "committed grid plan would have committed to over a window of prices that had "
            "already closed. The venue is the assumption a reader must meet before any figure "
            "below — the series is Binance's BNBUSDT, a centralised exchange's order book, "
            "while the plan addresses the WBNB/USDT pair on BSC through PancakeSwap. Replaying "
            "one against the other assumes the two prices track, which is an assumption and not "
            "a fact; the two books are close but they are not the same book, and no figure here "
            "is evidence about the venue the plan trades. Fills are at the level price with no "
            "fee, no slippage and no partial fill, all three of which would raise a real "
            "buyer's average price. Only candle closes are offered to the plan, so a venue that "
            "would have filled on an intra-hour wick would have triggered more levels than are "
            "counted here. Base acquired floors at every fill in every arm. Buy-and-hold "
            "commits the ladder's whole buy-side capacity rather than the part the ladder "
            "deployed, which is the reading under which the registered baseline's own sentence "
            "— in the market from the first hour, different exposure for the same money — is "
            "true; it moves nothing the falsifier tests, which compares average prices, and an "
            "average price does not depend on how much was committed at it. A lower average "
            "price is not a better outcome: it is a different position, held in less base for "
            "less money, and the base each arm acquired is reported beside the price each paid. "
            "The falsifier was evaluated clause by clause against the measured figures rather "
            "than restated, and its result is below."
        ),
    }


def _finding(measured: dict, recheck: dict) -> str:
    """What the run found, in the falsifier's own terms and in the direction it came out."""
    fired = measured["replay"]
    hold = measured["buy_and_hold"]
    refetched = {True: "matched", False: "did NOT match", None: "could not be re-fetched"}[
        recheck["matches"]
    ]
    verdict = (
        "The claim is REFUTED."
        if measured["falsifier_result"]["refuted"]
        else "The claim survived its falsifier."
    )
    clauses = " ".join(check["observed"] for check in measured["falsifier_result"]["checks"])
    return (
        f"{verdict} Over the {fired['n_candles']} candles of the registered window, "
        f"{fired['n_buy_triggers']} of the plan's {fired['n_buy_levels']} buy levels fired and "
        f"{fired['n_sell_triggers']} of its {fired['n_sell_levels']} sell levels did. {clauses} "
        f"The comparison is {'empty' if measured['comparison_is_empty'] else 'not empty'}. "
        f"Buy-and-hold committed {_as_decimal(hold['quote_committed'])} of quote at "
        f"{_as_decimal(hold['average_buy_price'])} and held "
        f"{_as_decimal(hold['base_acquired'])} of base against the replay's "
        f"{_as_decimal(fired['base_acquired'])}. The series was re-fetched from the registered "
        f"Binance URL during this run and its digest {refetched} the committed file's, so the "
        "window is obtainable rather than only citable. The series is a centralised venue's and "
        "the plan addresses an on-chain pair, which is an assumption stated in the method above "
        "and not a fact established here. This is the result the pre-registration committed to "
        "publishing whichever way it came out, and it is published as it came out."
    )


def save_run(record: dict, path) -> None:
    """Sorted, indented, LF — the recipe `spec.save` and `harness.save` already use."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    blob = json.dumps(record, sort_keys=True, indent=2, ensure_ascii=False)
    path.write_text(blob + "\n", encoding="utf-8", newline="\n")


if __name__ == "__main__":
    # `python -m docket.advantage.v2.replay` is what produced the committed record, and it is
    # here so that sentence is checkable. The two stamps bracket the run's observations — the
    # re-fetch is the only one; everything after it is arithmetic a reader can redo from the
    # committed series and get the same figures.
    root = Path(__file__).resolve().parents[3]
    registration = load(root / "docket/advantage/v2/specs/04-grid-replay.json")
    started = datetime.now(UTC).isoformat(timespec="seconds")
    checked = recheck_dataset(root / registration.dataset_ref)
    record = build_run_record(
        registration,
        load_series(root / registration.dataset_ref),
        started_at=started,
        finished_at=datetime.now(UTC).isoformat(timespec="seconds"),
        recheck=checked,
    )
    save_run(record, root / "docket/advantage/v2/runs/04-grid-replay.json")
    print(record["finding"])
