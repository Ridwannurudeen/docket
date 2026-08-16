"""The comparison table, and the cells it is not allowed to fill in.

The failure this guards against is not a wrong number. It is a table that looks complete —
every row populated, every service apparently measured — because an empty cell was filled
with a zero, a blank, or a figure that belongs to a different service. Three of the six
services have never been run against a human, and a reader comparing them has to be able to
see that rather than infer it from a suspiciously round number.
"""

import json

import pytest

from docket.hire import comparison


class _Service:
    def __init__(self, service_id, **overrides):
        self.id = service_id
        self.name = overrides.get("name", service_id.replace("-", " ").title())
        self.what_you_get = overrides.get("what_you_get", "a decision")
        self.price_display = overrides.get("price_display", "0.50 $U")
        self.asset = overrides.get("asset", "$U")
        self.typical_seconds = overrides.get("typical_seconds", 30)
        self.stock_status = overrides.get("stock_status", "candidate")
        self.admission = overrides.get(
            "admission",
            {
                "fresh_paired_benchmark": False,
                "cold_canary": False,
                "decision_grade_presenter": True,
                "true_settlement": False,
            },
        )
        self.paid_stock = overrides.get("paid_stock", False)


def _row(table, service_id):
    return next(row for row in table["rows"] if row["service_id"] == service_id)


def test_a_measured_service_carries_its_source_and_its_denominator():
    table = comparison.compare([_Service("range-doctor")])
    measured = _row(table, "range-doctor")["measured"]
    assert measured["available"] is True
    assert measured["agent_seconds"] == pytest.approx(43.062999999994645)
    assert measured["manual_seconds"] == pytest.approx(528.31)
    assert measured["seconds_saved"] == pytest.approx(528.31 - 43.062999999994645)
    # The denominator travels with the saving. One pair is not a rate.
    assert measured["sample_size"] == 1
    assert measured["source"].endswith("01-liquidity.json")


@pytest.mark.parametrize(
    "service_id", ["grid-operator", "yield-router", "health-guard"]
)
def test_an_unmeasured_service_states_the_reason_rather_than_showing_nothing(
    service_id,
):
    """The point of the table. A blank cell reads as 'nobody filled it in'; a zero reads as
    'this service saves no time'. Neither is true, and both are worse than the sentence."""
    measured = _row(comparison.compare([_Service(service_id)]), service_id)["measured"]
    assert measured["available"] is False
    assert measured["reason"] == comparison.NO_MEASUREMENT
    for absent in ("seconds_saved", "agent_seconds", "manual_seconds", "sample_size"):
        assert absent not in measured


def test_a_missing_recorded_run_is_reported_rather_than_treated_as_unmeasured(tmp_path):
    """Two different facts. 'This service was never measured' and 'the file that measured
    it is not in this build' must not collapse into the same sentence."""
    measured = _row(
        comparison.compare([_Service("range-doctor")], experiments=tmp_path),
        "range-doctor",
    )["measured"]
    assert measured["available"] is False
    assert "not present in this build" in measured["reason"]
    assert measured["reason"] != comparison.NO_MEASUREMENT


def test_an_arm_without_an_elapsed_time_is_not_silently_a_saving(tmp_path):
    (tmp_path / "01-liquidity.json").write_text(
        json.dumps({"agent_arm": {"seconds": 12.0}, "manual_arm": {}}),
        encoding="utf-8",
    )
    measured = _row(
        comparison.compare([_Service("range-doctor")], experiments=tmp_path),
        "range-doctor",
    )["measured"]
    assert measured["available"] is False
    assert "no elapsed time" in measured["reason"]


def test_the_failing_admission_limbs_are_named_not_counted():
    """A buyer deciding whether to pay wants to know which gate is open, not how many."""
    row = _row(comparison.compare([_Service("range-doctor")]), "range-doctor")
    assert row["admission_failing"] == [
        "cold_canary",
        "fresh_paired_benchmark",
        "true_settlement",
    ]


def test_the_summary_counts_only_services_with_a_real_pair():
    table = comparison.compare(
        [
            _Service("range-doctor"),
            _Service("warden-scan"),
            _Service("grid-operator"),
            _Service("yield-router"),
        ]
    )
    assert table["summary"]["services"] == 4
    assert table["summary"]["services_with_a_paired_measurement"] == 2
    assert "not a rate" in table["summary"]["reading"]


def test_every_measured_service_maps_to_a_run_that_actually_exists():
    """The map is a claim about the repository, so it is checked against it."""
    for filename in comparison.MEASURED_BY.values():
        assert (comparison.EXPERIMENTS / filename).is_file(), filename
