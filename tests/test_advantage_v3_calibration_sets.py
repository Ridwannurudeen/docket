import json
from pathlib import Path

import pytest

from docket.advantage.v3 import calibration
from docket.advantage.v3.spec import (
    _calibration_truth_matches,
    _computed_calibration_truth,
    load,
)

ROOT = Path(__file__).resolve().parents[1]
SPECS_DIR = ROOT / "docket/advantage/v3/specs"
SOURCES_DIR = ROOT / "docket/advantage/v3/sources"

RANGE_INPUT_FIELDS = {
    "current_tick",
    "tick_lower",
    "tick_upper",
    "fee_usd_24h",
    "protocol_fee_usd_24h",
    "tvl_usd",
    "declared_position_value_usd",
    "estimated_recenter_cost_usd",
}
YIELD_INPUT_FIELDS = {
    "allowlist",
    "current_pool",
    "destination_pool",
    "position_value_usd",
    "switching_cost_usd",
    "decision_horizon_days",
}
YIELD_POOL_FIELDS = {
    "token0",
    "token1",
    "tvlUSD",
    "volumeUSD24h",
    "feeUSD24h",
    "protocolFeeUSD24h",
}

SETS = (
    (
        "range-v5-calibration-set.json",
        "v3-05-range-doctor.json",
        "v3-05-range-doctor",
        RANGE_INPUT_FIELDS,
    ),
    (
        "yield-v2-calibration-set.json",
        "v3-02-yield-router.json",
        "v3-02-yield-router",
        YIELD_INPUT_FIELDS,
    ),
)


def _load_set(filename: str) -> tuple[bytes, dict]:
    raw = (SOURCES_DIR / filename).read_bytes()
    return raw, json.loads(raw.decode("utf-8"))


@pytest.mark.parametrize(
    ("set_filename", "spec_filename", "spec_id", "input_fields"), SETS
)
def test_calibration_set_contract_and_truth(
    set_filename, spec_filename, spec_id, input_fields
):
    raw, body = _load_set(set_filename)
    spec = load(SPECS_DIR / spec_filename)

    assert set(body) == {"authored_at", "spec_id", "cases"}
    assert body["spec_id"] == spec_id == spec.spec_id
    assert len(body["cases"]) == 8
    case_ids = [case["case_id"] for case in body["cases"]]
    assert all(isinstance(case_id, str) and case_id.strip() for case_id in case_ids)
    assert len(case_ids) == len(set(case_ids))

    for case in body["cases"]:
        assert set(case) == {"case_id", "input", "expected"}
        assert set(case["input"]) == input_fields
        if spec_id == "v3-02-yield-router":
            for pool_name in ("current_pool", "destination_pool"):
                pool = case["input"][pool_name]
                assert set(pool) == YIELD_POOL_FIELDS
                assert set(pool["token0"]) == {"id"}
                assert set(pool["token1"]) == {"id"}
        computed = _computed_calibration_truth(spec, case["input"])
        assert computed is not None
        assert _calibration_truth_matches(case["expected"], computed)

    assert isinstance(calibration.derive_prompt(spec, raw, "seat-a"), bytes)


def test_range_calibration_covers_every_range_state():
    _, body = _load_set("range-v5-calibration-set.json")

    assert {case["expected"]["range_status"] for case in body["cases"]} == {
        "in_range",
        "above_range",
        "below_range",
    }


def test_yield_calibration_covers_eligibility_and_exclusions():
    _, body = _load_set("yield-v2-calibration-set.json")
    gates = {
        case["expected"]["current_first_failed_gate"] for case in body["cases"]
    }

    assert None in gates
    assert len(gates) >= 3


@pytest.mark.parametrize(
    ("set_filename", "spec_filename", "expected_field"),
    (
        (
            "range-v5-calibration-set.json",
            "v3-05-range-doctor.json",
            "range_status",
        ),
        (
            "yield-v2-calibration-set.json",
            "v3-02-yield-router.json",
            "decision",
        ),
    ),
)
def test_corrupted_expected_value_fails_the_real_match_check(
    set_filename, spec_filename, expected_field
):
    _, body = _load_set(set_filename)
    spec = load(SPECS_DIR / spec_filename)
    case = body["cases"][0]
    computed = _computed_calibration_truth(spec, case["input"])

    case["expected"][expected_field] = "corrupt"

    assert not _calibration_truth_matches(case["expected"], computed)
