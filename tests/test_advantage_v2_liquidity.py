"""The two ways a published fee rate goes wrong, and which of them actually matters.

v1's task 01 found the manual arm computing 15.406% where the agent computed 15.399%, and
attributed the difference to PancakeSwap Info rounding $2,058 of fees to $2.06K. That is one
pair, and one pair cannot say whether display rounding is a hazard or a rounding error in the
ordinary sense. The same run recorded a second and much larger gap in passing: a reader who
annualises the fee the pool charged, without subtracting the cut the protocol takes, reads
22.99% where the net rate is 15.41%.

These tests guard the arithmetic that turns both into distributions over a registered pool
snapshot. The load-bearing one is the display model: `ui_display` is a claim about what
PancakeSwap Info prints, and it is pinned to the strings v1's manual arm actually read off
the screen rather than to a rule this repo invented. If that model is wrong the rounding
figure is measuring nothing, so it is asserted first and against observed output.

Nothing here touches a network. The snapshot, the pre-registration and the run record are all
files in the repository.
"""

import hashlib
import json
from pathlib import Path

import pytest

from docket.advantage.v2 import liquidity
from docket.advantage.v2.spec import load
from docket.agents.pancake.pools import net_fee_apr

ROOT = Path(__file__).resolve().parents[1]
DATASET_PATH = ROOT / "docket/advantage/v2/corpus/liquidity/pools.json"
SPEC_PATH = ROOT / "docket/advantage/v2/specs/01-liquidity-arithmetic.json"
RUN_PATH = ROOT / "docket/advantage/v2/runs/01-liquidity-arithmetic.json"

DATASET = json.loads(DATASET_PATH.read_text(encoding="utf-8"))
RUN = json.loads(RUN_PATH.read_text(encoding="utf-8"))


def test_the_display_model_reproduces_the_strings_v1_read_off_the_screen():
    """The whole rounding measurement rests on this. `ui_display` says what PancakeSwap Info
    prints for a dollar figure, and the only evidence for it is what the manual arm recorded
    reading: $2,058 of 24h fees shown as $2.06K, and $3,267,492 of TVL shown as $3.27M. Both
    are two decimals on a K/M/B mantissa rather than significant figures, which the pair
    settles — three significant figures would have printed $3.27M and $2.06K too, but the same
    run's $20.59M volume has four, and only the mantissa rule produces all three."""
    assert liquidity.ui_display(2058) == "$2.06K"
    assert liquidity.ui_display(3267492) == "$3.27M"
    # The third string v1 recorded, whose raw figure the run did not keep. The rule is checked
    # against it the only way that evidence allows: raw volumes inside the band it could have
    # come from print back as the string that was read.
    assert liquidity.ui_display(20_586_000) == "$20.59M"
    assert liquidity.ui_display(20_594_000) == "$20.59M"


def test_the_display_model_scales_at_each_boundary_and_keeps_small_figures_whole():
    """A figure just under a scale boundary must not borrow the scale above it, or a $999.99
    fee would print as $1.00K and the rounding gap would be measured against a display nobody
    saw. Below a thousand there is no suffix and the two decimals are the cents themselves."""
    assert liquidity.ui_display(428.2168178572) == "$428.22"
    assert liquidity.ui_display(999.994) == "$999.99"
    assert liquidity.ui_display(1000) == "$1.00K"
    assert liquidity.ui_display(1_000_000) == "$1.00M"
    assert liquidity.ui_display(1_000_000_000) == "$1.00B"
    assert liquidity.ui_display(0) == "$0.00"


def test_a_mantissa_that_rounds_up_to_a_thousand_is_the_models_own_choice():
    """Not evidence about PancakeSwap Info. Reaching this needs a figure within half a cent of
    a scale boundary, and v1's record has nothing that lands there, so the model promotes to
    the next scale rather than printing four digits and this test pins that choice as the
    model's. What keeps it out of the published figures is the second assertion: no pool in
    the registered snapshot is close enough to any boundary for the choice to change a rate."""
    assert liquidity.ui_display(999_999) == "$1.00M"
    assert liquidity.ui_display(999_999_999) == "$1.00B"

    for entry in DATASET["rows"]:
        if not entry["eligible"]:
            continue
        row = liquidity.pool_gaps(entry["pool"])
        for field, shown in row["displayed"].items():
            raw = row["raw"][field]
            scale = "" if raw < 1e3 else "K" if raw < 1e6 else "M" if raw < 1e9 else "B"
            assert (shown[-1] if shown[-1] in "KMB" else "") == scale, (row["pool"], field, shown)


def test_the_rounded_value_is_the_number_behind_the_string_it_displays():
    """`ui_rounded` is what a reader keying the displayed figure into a calculator has, so it
    has to be the string's own value and not a second rule that happens to agree most of the
    time. Asserted by reading the number back out of the string."""
    for raw in (2058, 3267492, 428.2168178572, 40_036_756.05753184, 0.0):
        shown = liquidity.ui_display(raw)
        mantissa, scale = shown.lstrip("$"), 1
        for suffix, factor in (("B", 1e9), ("M", 1e6), ("K", 1e3)):
            if mantissa.endswith(suffix):
                mantissa, scale = mantissa[:-1], factor
                break
        assert liquidity.ui_rounded(raw) == pytest.approx(float(mantissa) * scale)


def test_the_rounded_arm_runs_the_same_net_formula_the_raw_arm_runs():
    """The rounding arm isolates the display and nothing else. A pool whose three figures are
    already at display precision has to score identically under both, or the arm would be
    measuring some second difference in the formula rather than the rounding."""
    already_displayed = {
        "feeUSD24h": "2060",
        "protocolFeeUSD24h": "680",
        "tvlUSD": "3270000",
    }

    assert liquidity.ui_rounded_net_fee_apr(already_displayed) == net_fee_apr(already_displayed)
    assert liquidity.rounded_pool(already_displayed) == {
        "feeUSD24h": 2060.0,
        "protocolFeeUSD24h": 680.0,
        "tvlUSD": 3_270_000.0,
    }


def test_the_gross_arm_is_the_fee_the_pool_charged_over_the_same_tvl():
    """v1's number, recomputed: $2,058 of fees on $3,267,492 of TVL annualises to 22.99% gross
    against 15.40% net, because $679 of that day's fee went to the protocol. The gross arm
    takes no view on the split — it is what a reader publishes who never learns there is one."""
    pool = {"feeUSD24h": "2058", "protocolFeeUSD24h": "679", "tvlUSD": "3267492"}

    assert liquidity.gross_fee_apr(pool) == pytest.approx(2058 * 365 / 3_267_492)
    assert liquidity.gross_fee_apr(pool) == pytest.approx(0.229892, abs=1e-6)
    assert net_fee_apr(pool) == pytest.approx(0.154043, abs=1e-6)
    # A pool with no TVL has no rate at all, and zero would be a rate somebody could quote.
    assert liquidity.gross_fee_apr({"feeUSD24h": "10", "tvlUSD": "0"}) == 0.0


def test_a_gap_relative_to_a_zero_rate_is_null_and_never_a_number():
    """A pool that charged nothing has a net rate of zero, and every relative gap against it is
    a division nobody can do. It reports null, for the reason a rate over zero observations
    does: an infinity or a substituted zero would both be figures nobody measured."""
    idle = {"id": "0xidle", "feeUSD24h": "0", "protocolFeeUSD24h": "0", "tvlUSD": "1000000"}

    gaps = liquidity.pool_gaps(idle)

    assert gaps["net_fee_apr"] == 0.0
    assert gaps["rounding_gap_pp"] == 0.0
    assert gaps["gross_gap_pp"] == 0.0
    assert gaps["rounding_gap_relative"] is None
    assert gaps["gross_gap_relative"] is None


def test_a_distribution_carries_the_count_it_was_computed_over():
    """An aggregate without its n is the shape this whole stage exists to refuse, and an
    aggregate over nothing is null rather than zero."""
    assert liquidity.distribution([3.0, 1.0, 2.0]) == {
        "n": 3,
        "min": 1.0,
        "median": 2.0,
        "max": 3.0,
    }
    assert liquidity.distribution([]) == {"n": 0, "min": None, "median": None, "max": None}


def test_the_registered_spec_carries_the_digest_of_the_snapshot_on_disk():
    """The pre-registration names a file and a digest, and the digest is what stops the file
    being the thing that moved. It also fixes n at the eligible count, which was settled inside
    the snapshot before the registration was written — a pool admitted after its gap was
    visible is the post-hoc selection this stage exists to rule out."""
    spec = load(SPEC_PATH)
    eligible = [row for row in DATASET["rows"] if row["eligible"]]

    assert spec.spec_id == "01-liquidity-arithmetic"
    assert spec.dataset_ref == "docket/advantage/v2/corpus/liquidity/pools.json"
    assert spec.dataset_sha256 == hashlib.sha256(DATASET_PATH.read_bytes()).hexdigest()
    assert (ROOT / spec.dataset_ref).resolve() == DATASET_PATH.resolve()
    assert spec.n_planned == len(eligible) == 22
    assert len(DATASET["rows"]) == 28
    assert [baseline["name"] for baseline in spec.null_baselines] == [
        "quote_ui_rounded",
        "quote_gross",
    ]
    # The falsifier has to be able to fire on either limb, and the spec pre-commits to
    # publishing whichever effect turns out to be larger rather than the flattering one.
    assert "refuted" in spec.falsifier
    assert "not a disappointment" in spec.falsifier


def test_the_run_record_cites_the_registration_and_every_eligible_pool():
    """A record is evidence for this experiment only if it names the registration it ran
    against, and the registration is worth citing only if the snapshot under it has not moved.
    The row count is checked too: 22 eligible pools of 28 in the snapshot, each with the raw
    figures it was computed from, so the whole thing can be redone by hand from the record."""
    spec = load(SPEC_PATH)
    eligible = [row["pool"]["id"] for row in DATASET["rows"] if row["eligible"]]

    assert RUN["spec_hash"] == spec.spec_hash
    assert RUN["spec_id"] == spec.spec_id
    assert RUN["dataset_sha256"] == spec.dataset_sha256
    assert [row["pool"] for row in RUN["pools"]] == eligible
    assert len(RUN["pools"]) == RUN["n_planned"] == 22
    for row in RUN["pools"]:
        assert set(row["raw"]) == {"feeUSD24h", "protocolFeeUSD24h", "tvlUSD"}
        assert set(row["displayed"]) == set(row["raw"])


def test_the_published_distributions_are_what_the_committed_snapshot_recomputes_to():
    """The record's figures, recomputed from the snapshot it cites. A published aggregate that
    can drift from its evidence is one nobody downstream can check, and this is what would
    catch it: the snapshot, the arithmetic and the record all in the repository, agreeing."""
    recomputed = liquidity.measure(DATASET)

    for field in (
        "rounding_gap_pp",
        "gross_gap_pp",
        "rounding_gap_relative",
        "gross_gap_relative",
        "pools_where_gross_gap_exceeds_rounding_gap",
    ):
        assert RUN[field] == recomputed[field], field
    assert RUN["pools"] == recomputed["pools"]


def test_the_rounding_gap_is_noise_against_the_gross_gap_on_every_pool():
    """The measured answer, and it is not the one v1's narrative leads with. v1 opened on the
    rounding — 15.406% against 15.399% — and mentioned the protocol cut in passing. Over 22
    pools the median absolute rounding gap is nine ten-thousandths of a percentage point and
    the median absolute gross gap is 1.27 points, the gross gap is larger on all 22, and
    quoting gross overstates the rate a liquidity provider earns by about half.

    The claim's first limb survives rather than being vindicated: the rounding gap is not zero,
    it is simply too small to matter. Both are stated because the pre-registration committed to
    stating whichever dominated."""
    rounding = RUN["rounding_gap_pp"]
    gross = RUN["gross_gap_pp"]

    assert rounding["n"] == gross["n"] == 22
    assert rounding["median"] == pytest.approx(0.000904, abs=5e-7)
    assert gross["median"] == pytest.approx(1.2678, abs=5e-5)
    assert rounding["max"] == pytest.approx(0.08298, abs=5e-6)
    assert gross["max"] == pytest.approx(101.799, abs=5e-4)
    assert rounding["min"] > 0
    assert RUN["pools_where_gross_gap_exceeds_rounding_gap"] == {
        "numerator": 22,
        "denominator": 22,
        "value": 1.0,
    }
    # As a share of the rate itself: the protocol takes between 47% and 52% on top of what an
    # LP keeps, where the display costs at most seven thousandths of a percent.
    assert RUN["gross_gap_relative"]["median"] == pytest.approx(0.4927, abs=5e-5)
    assert RUN["gross_gap_relative"]["min"] > 0.47
    assert RUN["rounding_gap_relative"]["max"] < 0.007
    assert "quoting gross moves the published net fee rate further" in RUN["finding"]


def test_the_record_says_it_read_a_file_and_sent_nothing():
    """Two things a reader has to be able to check without trusting the narrative: that the
    arithmetic ran over the committed snapshot rather than over a live call whose figures
    nobody kept, and that the rate is a property of a pool over one day and not a forecast or
    anybody's realised yield."""
    assert "No network call was made while this record was computed" in RUN["method"]
    assert "no transaction of any kind was made" in RUN["method"]
    assert "one 24h window" in RUN["method"]
    assert "not of any position" in RUN["method"]
