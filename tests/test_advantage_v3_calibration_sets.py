import hashlib
import json
from base64 import b64encode
from pathlib import Path

import pytest

from docket.advantage.v3 import calibration
from docket.hire.receipts import canonical_hash
from docket.advantage.v3.spec import (
    _calibration_truth_matches,
    _computed_calibration_truth,
    _validate_evaluator_calibration,
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


def _canonicalize(value):
    if isinstance(value, float):
        return round(value, 12)
    if isinstance(value, dict):
        return {name: _canonicalize(item) for name, item in value.items()}
    if isinstance(value, list):
        return [_canonicalize(item) for item in value]
    return value


def _range_truth_from_prompt(inputs: dict) -> dict:
    current = inputs["current_tick"]
    lower = inputs["tick_lower"]
    upper = inputs["tick_upper"]
    status = (
        "below_range"
        if current < lower
        else "above_range"
        if current >= upper
        else "in_range"
    )
    gross_apr = inputs["fee_usd_24h"] * 365 / inputs["tvl_usd"]
    net_apr = (
        (inputs["fee_usd_24h"] - inputs["protocol_fee_usd_24h"])
        * 365
        / inputs["tvl_usd"]
    )
    position_value = inputs["declared_position_value_usd"]
    return {
        "range_status": status,
        "gross_apr": gross_apr,
        "net_apr": net_apr,
        "annual_gross_usd": position_value * gross_apr,
        "annual_net_usd": position_value * net_apr,
        "annual_overstatement_usd": position_value * (gross_apr - net_apr),
        "cost_only_break_even_days": (
            inputs["estimated_recenter_cost_usd"] / (position_value * net_apr / 365)
            if net_apr > 0
            else None
        ),
    }


def _yield_first_failed_gate_from_prompt(pool: dict, allowlist: set[str]):
    if pool["token0"]["id"].lower() not in allowlist:
        return "token0_allowlist"
    if pool["token1"]["id"].lower() not in allowlist:
        return "token1_allowlist"
    if pool["tvlUSD"] < 10000:
        return "tvl_floor"
    if pool["volumeUSD24h"] / pool["tvlUSD"] > 50:
        return "turnover_ceiling"
    if pool["feeUSD24h"] is None:
        return "feeUSD24h_non_null"
    if pool["protocolFeeUSD24h"] is None:
        return "protocolFeeUSD24h_non_null"
    return None


def _yield_truth_from_prompt(inputs: dict) -> dict:
    allowlist = {address.lower() for address in inputs["allowlist"]}
    current = inputs["current_pool"]
    destination = inputs["destination_pool"]
    current_gate = _yield_first_failed_gate_from_prompt(current, allowlist)
    destination_gate = _yield_first_failed_gate_from_prompt(destination, allowlist)
    current_net = (
        (current["feeUSD24h"] - current["protocolFeeUSD24h"]) * 365 / current["tvlUSD"]
        if current_gate is None
        else None
    )
    destination_net = (
        (destination["feeUSD24h"] - destination["protocolFeeUSD24h"])
        * 365
        / destination["tvlUSD"]
        if destination_gate is None
        else None
    )
    extra_per_day = (
        inputs["position_value_usd"] * (destination_net - current_net) / 365
        if current_net is not None and destination_net is not None
        else None
    )
    days = (
        inputs["switching_cost_usd"] / extra_per_day
        if extra_per_day is not None and extra_per_day > 0
        else None
    )
    decision = (
        None
        if current_gate is not None or destination_gate is not None
        else "MOVE"
        if days is not None and days <= inputs["decision_horizon_days"]
        else "STAY"
    )
    return {
        "current_first_failed_gate": current_gate,
        "destination_first_failed_gate": destination_gate,
        "current_net_apr": current_net,
        "destination_net_apr": destination_net,
        "extra_usd_per_day": extra_per_day,
        "days_to_recover": days,
        "decision": decision,
    }


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
        assert case["expected"] == _canonicalize(computed), case["case_id"]
        assert _calibration_truth_matches(case["expected"], computed), case["case_id"]

    assert isinstance(calibration.derive_prompt(spec, raw, "seat-a"), bytes)


@pytest.mark.parametrize(
    ("set_filename", "spec_filename", "truth_from_prompt", "declarations"),
    (
        (
            "range-v5-calibration-set.json",
            "v3-05-range-doctor.json",
            _range_truth_from_prompt,
            (
                "range_status, gross_apr, net_apr, annual_gross_usd, "
                "annual_net_usd, annual_overstatement_usd, "
                "cost_only_break_even_days",
                "current_tick >= tick_upper",
                "gross_apr = fee_usd_24h * 365 / tvl_usd",
                "net_apr = (fee_usd_24h - protocol_fee_usd_24h) * 365 / tvl_usd",
            ),
        ),
        (
            "yield-v2-calibration-set.json",
            "v3-02-yield-router.json",
            _yield_truth_from_prompt,
            (
                "current_first_failed_gate, destination_first_failed_gate, "
                "current_net_apr, destination_net_apr, extra_usd_per_day, "
                "days_to_recover, decision",
                "token0_allowlist, token1_allowlist, tvl_floor, turnover_ceiling, "
                "feeUSD24h_non_null, protocolFeeUSD24h_non_null",
                "days_to_recover <= decision_horizon_days",
            ),
        ),
    ),
)
def test_prompt_only_seat_reproduces_every_canonical_answer(
    set_filename, spec_filename, truth_from_prompt, declarations
):
    raw, answer_key = _load_set(set_filename)
    spec = load(SPECS_DIR / spec_filename)
    prompt = json.loads(calibration.derive_prompt(spec, raw, "seat-a"))

    assert prompt["prompt_version"] == "v3.calibration-prompt.v5"
    assert all(text in prompt["instruction"] for text in declarations)
    assert (
        "round every fractional number to 12 decimal places " in prompt["instruction"]
    )
    assert "Python round(x, 12)" in prompt["instruction"]
    assert all("expected" not in case for case in prompt["cases"])

    expected_by_id = {case["case_id"]: case["expected"] for case in answer_key["cases"]}
    unrounded = {
        case["case_id"]: truth_from_prompt(case["input"]) for case in prompt["cases"]
    }
    rounded = {case_id: _canonicalize(answer) for case_id, answer in unrounded.items()}

    assert (
        sum(
            rounded[case_id] == expected for case_id, expected in expected_by_id.items()
        )
        == 8
    )
    assert any(
        unrounded[case_id] != expected for case_id, expected in expected_by_id.items()
    )


@pytest.mark.parametrize(
    ("set_filename", "spec_filename"),
    ((item[0], item[1]) for item in SETS),
)
def test_canonical_set_passes_real_assembled_calibration_validation(
    set_filename, spec_filename
):
    raw, body = _load_set(set_filename)
    spec = load(SPECS_DIR / spec_filename)
    rows = []
    for ordinal, seat in enumerate(spec.scoring["evaluator_roster"], start=1):
        rows.append(
            {
                "evaluator_id": seat["evaluator_id"],
                "model_build": f"stub-build-{ordinal}",
                "session_id": f"stub-session-{ordinal}",
                "rubric_anchor_hash": canonical_hash(spec.quality_rubric["criteria"]),
                "calibration_results": [
                    {
                        "case_id": case["case_id"],
                        "input": case["input"],
                        "expected": case["expected"],
                        "submitted": case["expected"],
                    }
                    for case in body["cases"]
                ],
            }
        )
    envelope = {
        "calibration_set": {
            "sha256": hashlib.sha256(raw).hexdigest(),
            "body_base64": b64encode(raw).decode("ascii"),
        },
        "evaluator_calibration": rows,
    }

    _validate_evaluator_calibration(spec, envelope, [], ROOT)


def test_range_calibration_covers_every_range_state():
    _, body = _load_set("range-v5-calibration-set.json")

    assert [case["case_id"] for case in body["cases"]] == [
        f"r5-cal-{ordinal:02d}" for ordinal in range(1, 9)
    ]
    assert {case["expected"]["range_status"] for case in body["cases"]} == {
        "in_range",
        "above_range",
        "below_range",
    }
    below, baseline = body["cases"][:2]
    below_net_fee_ratio = (
        below["input"]["fee_usd_24h"] - below["input"]["protocol_fee_usd_24h"]
    ) / below["input"]["tvl_usd"]
    baseline_net_fee_ratio = (
        baseline["input"]["fee_usd_24h"]
        - baseline["input"]["protocol_fee_usd_24h"]
    ) / baseline["input"]["tvl_usd"]
    assert below_net_fee_ratio != baseline_net_fee_ratio


def test_yield_calibration_covers_eligibility_and_exclusions():
    _, body = _load_set("yield-v2-calibration-set.json")
    gates = {case["expected"]["current_first_failed_gate"] for case in body["cases"]}

    assert [case["case_id"] for case in body["cases"]] == [
        f"y2-cal-{ordinal:02d}" for ordinal in range(1, 9)
    ]
    assert None in gates
    assert len(gates) >= 3
    assert [
        case["expected"]["current_first_failed_gate"] for case in body["cases"]
    ] == [
        None,
        "token0_allowlist",
        "tvl_floor",
        None,
        "turnover_ceiling",
        None,
        "feeUSD24h_non_null",
        "protocolFeeUSD24h_non_null",
    ]


def test_yield_calibration_exercises_first_gate_precedence_and_varied_fees():
    _, body = _load_set("yield-v2-calibration-set.json")
    by_id = {case["case_id"]: case for case in body["cases"]}

    token0_then_tvl = by_id["y2-cal-02"]
    assert token0_then_tvl["input"]["current_pool"]["token0"]["id"] not in {
        address.lower() for address in token0_then_tvl["input"]["allowlist"]
    }
    assert token0_then_tvl["input"]["current_pool"]["tvlUSD"] < 10000
    assert token0_then_tvl["expected"]["current_first_failed_gate"] == (
        "token0_allowlist"
    )

    tvl_then_turnover = by_id["y2-cal-03"]
    current_pool = tvl_then_turnover["input"]["current_pool"]
    assert current_pool["tvlUSD"] < 10000
    assert current_pool["volumeUSD24h"] / current_pool["tvlUSD"] > 50
    assert tvl_then_turnover["expected"]["current_first_failed_gate"] == "tvl_floor"

    assert token0_then_tvl["input"]["destination_pool"]["feeUSD24h"] == 135
    assert tvl_then_turnover["input"]["destination_pool"]["feeUSD24h"] == 145

    boundary = by_id["y2-cal-06"]["input"]
    current_net_fee = (
        boundary["current_pool"]["feeUSD24h"]
        - boundary["current_pool"]["protocolFeeUSD24h"]
    )
    destination_net_fee = (
        boundary["destination_pool"]["feeUSD24h"]
        - boundary["destination_pool"]["protocolFeeUSD24h"]
    )
    assert boundary["current_pool"]["feeUSD24h"] > 0
    assert boundary["destination_pool"]["feeUSD24h"] > 0
    assert destination_net_fee - current_net_fee == 1


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
