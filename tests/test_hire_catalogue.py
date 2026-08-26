import json

import pytest

from docket.hire import catalogue
from docket.hire.catalogue import (
    SERVICE_BENCHMARK_FAMILIES,
    SERVICES,
    _benchmark_family,
    get_service,
)


def _benchmark_report():
    pairings = {
        "v3-01-range-doctor": ("range-doctor", "superseded_before_input_lock"),
        "v3-02-yield-router": ("yield-router", "registered_waiting_for_inputs"),
        "v3-03-warden-security": ("warden-scan", "superseded_before_input_lock"),
        "v3-04-warden-security": ("warden-scan", "registered_waiting_for_inputs"),
        "v3-05-range-doctor": ("range-doctor", "registered_waiting_for_inputs"),
    }
    return {
        "families": [
            {
                "spec_id": spec_id,
                "state": state,
                "spec": {
                    "execution_protocol": {"agent_service_id": service_id},
                },
            }
            for spec_id, (service_id, state) in pairings.items()
        ]
    }


def _benchmark_state(spec_id, state, *, quality=None, speed=None, unscored_reason=None):
    payload = _benchmark_report()
    family = next(row for row in payload["families"] if row["spec_id"] == spec_id)
    family.update(
        {
            "state": state,
            "quality": quality,
            "speed": speed,
            "unscored_reason": unscored_reason,
        }
    )
    return payload


def test_benchmark_mapping_resolves_only_its_registered_service_family():
    payload = _benchmark_report()

    for service_id, spec_id in SERVICE_BENCHMARK_FAMILIES.items():
        family = _benchmark_family(service_id, payload)
        assert family["spec_id"] == spec_id
        assert family["spec"]["execution_protocol"]["agent_service_id"] == service_id

    for service_id in ("grid-operator", "health-guard", "solvent-signal"):
        assert _benchmark_family(service_id, payload) is None


def test_benchmark_mapping_refuses_a_swapped_or_superseded_family(monkeypatch):
    payload = _benchmark_report()
    swapped = SERVICE_BENCHMARK_FAMILIES | {
        "range-doctor": "v3-02-yield-router"
    }
    monkeypatch.setattr(catalogue, "SERVICE_BENCHMARK_FAMILIES", swapped)

    with pytest.raises(RuntimeError, match="registered for yield-router, not range-doctor"):
        _benchmark_family("range-doctor", payload)

    superseded = SERVICE_BENCHMARK_FAMILIES | {
        "range-doctor": "v3-01-range-doctor"
    }
    monkeypatch.setattr(catalogue, "SERVICE_BENCHMARK_FAMILIES", superseded)

    with pytest.raises(RuntimeError, match="superseded"):
        _benchmark_family("range-doctor", payload)


def test_range_doctor_is_offered_and_describes_itself():
    svc = get_service("range-doctor")
    assert svc is not None
    assert svc.what_you_get and svc.typical_seconds > 0
    assert "wallet" in svc.input_schema


def test_range_doctor_can_bind_declared_economics_to_one_exact_position():
    schema = get_service("range-doctor").input_schema
    assert schema["token_id"]["required"] is False
    assert schema["declared_position_value_usd"]["required"] is False
    assert schema["estimated_recenter_cost_usd"]["required"] is False
    assert "caller-declared" in schema["declared_position_value_usd"]["description"]
    assert "not derived" in schema["estimated_recenter_cost_usd"]["description"]


def test_range_doctor_refuses_to_apply_one_declared_value_to_a_wallet(monkeypatch):
    """A wallet can hold many NFTs, so one dollar value without one token id is ambiguous."""
    monkeypatch.setattr(
        catalogue.doctor,
        "report",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("validation must happen before any upstream read")
        ),
    )
    with pytest.raises(ValueError, match="token_id"):
        get_service("range-doctor").run(
            {"wallet": "0xwallet", "declared_position_value_usd": 10_000}
        )


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("token_id", 0),
        ("declared_position_value_usd", 0),
        ("estimated_recenter_cost_usd", -1),
        ("declared_position_value_usd", float("inf")),
    ),
)
def test_range_doctor_refuses_invalid_declared_economic_inputs(
    field, value, monkeypatch
):
    monkeypatch.setattr(
        catalogue.doctor,
        "report",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("validation must happen before any upstream read")
        ),
    )
    payload = {"wallet": "0xwallet", "token_id": 7087132, field: value}
    with pytest.raises(ValueError, match=field):
        get_service("range-doctor").run(payload)


def test_range_doctor_times_this_run_and_leaves_the_unrun_v3_fields_empty(monkeypatch):
    calls = []

    def report(address, **kwargs):
        calls.append((address, kwargs))
        return {"address": address, "positions": []}

    clock = iter((100.0, 101.25))
    monkeypatch.setattr(catalogue.doctor, "report", report)
    monkeypatch.setattr(catalogue.time, "perf_counter", lambda: next(clock))
    monkeypatch.setattr(
        catalogue.v3_report,
        "report",
        lambda: _benchmark_state(
            "v3-05-range-doctor", "registered_waiting_for_inputs"
        ),
    )
    out = get_service("range-doctor").run(
        {
            "wallet": "0xwallet",
            "token_id": 7087132,
            "declared_position_value_usd": 10_000,
            "estimated_recenter_cost_usd": 25,
        }
    )

    assert calls == [
        (
            "0xwallet",
            {
                "limit": None,
                "token_id": 7087132,
                "observation_block": None,
                "declared_position_value_usd": 10_000.0,
                "estimated_recenter_cost_usd": 25.0,
            },
        )
    ]
    assert out["measured_value"]["this_run_seconds"] == 1.25
    assert out["measured_value"]["paired_manual_seconds"] is None
    assert out["measured_value"]["quality_result"] is None
    assert out["measured_value"]["report_url"] is None
    assert (
        out["measured_value"]["benchmark_unavailable_reason"]
        == "The v3 paired family v3-05-range-doctor has no locked inputs."
    )


def test_range_doctor_populates_only_its_scored_v3_family(monkeypatch):
    quality = {
        "arms": {
            "agent": {"median_total": 15.0},
            "manual": {"median_total": 10.0},
        },
        "quality_refuted": False,
    }
    payload = _benchmark_state(
        "v3-05-range-doctor",
        "not_refuted",
        quality=quality,
        speed={"manual_median_seconds": 42.75},
    )
    clock = iter((100.0, 101.25))
    monkeypatch.setattr(
        catalogue.doctor,
        "report",
        lambda *args, **kwargs: {"positions": []},
    )
    monkeypatch.setattr(catalogue.time, "perf_counter", lambda: next(clock))
    monkeypatch.setattr(catalogue.v3_report, "report", lambda: payload)

    out = get_service("range-doctor").run({"wallet": "0xwallet"})

    assert out["measured_value"] == {
        "this_run_seconds": 1.25,
        "paired_manual_seconds": 42.75,
        "quality_result": quality,
        "report_url": "/advantage/v3#v3-05-range-doctor",
        "benchmark_unavailable_reason": None,
    }


@pytest.mark.parametrize(
    ("state", "unscored_reason", "expected_reason"),
    (
        (
            "registered_waiting_for_inputs",
            None,
            "The v3 paired family v3-05-range-doctor has no locked inputs.",
        ),
        (
            "locked_not_run",
            None,
            "The v3 paired family v3-05-range-doctor has locked inputs but has not run.",
        ),
        (
            "running",
            None,
            "The v3 paired family v3-05-range-doctor is still running.",
        ),
        (
            "complete_unscored",
            "score_sheets_missing",
            "The v3 paired family v3-05-range-doctor is complete but unscored: score_sheets_missing.",
        ),
    ),
)
def test_unavailable_v3_states_are_precise_and_never_borrow_v1(
    state, unscored_reason, expected_reason, monkeypatch
):
    monkeypatch.setattr(
        catalogue.v3_report,
        "report",
        lambda: _benchmark_state(
            "v3-05-range-doctor", state, unscored_reason=unscored_reason
        ),
    )

    measured = catalogue._measured_value("range-doctor", 1.25)

    assert measured == {
        "this_run_seconds": 1.25,
        "paired_manual_seconds": None,
        "quality_result": None,
        "report_url": None,
        "benchmark_unavailable_reason": expected_reason,
    }
    assert "528.31" not in json.dumps(measured, sort_keys=True)


def test_unknown_service_returns_none():
    assert get_service("nope") is None


def test_every_personalized_offer_uses_the_flat_half_usdt_price():
    for svc in SERVICES.values():
        assert svc.price_display == "0.50 USDT"
        assert svc.price_atomic == 5 * 10**17
        assert svc.asset == catalogue.USDT_TOKEN


def test_paid_stock_is_closed_until_all_four_admission_facts_pass():
    """A price is not an admission. Every service must clear the fresh benchmark, cold
    canary, presenter and true-settlement gates before any surface can sell it."""
    assert all(service.paid_stock is False for service in SERVICES.values())
    assert get_service("range-doctor").stock_status == "candidate"
    assert get_service("grid-operator").stock_status == "preview"
    assert get_service("health-guard").stock_status == "preview"
    assert get_service("solvent-signal").stock_status == "research"
    assert get_service("warden-scan").stock_status == "beta"


def test_no_service_promises_an_outcome():
    """Docket sells work performed, not results achieved.

    `advice`, `signal to trade` and `will` joined the list when a market-regime read
    entered the catalogue: a trading signal is the easiest thing here to describe as
    an instruction, and the description is the contract.
    """
    banned = (
        "guaranteed",
        "profit",
        "best",
        "safe",
        "will increase",
        "recommended",
        "advice",
        "signal to trade",
        "will",
    )
    for svc in SERVICES.values():
        blob = f"{svc.name} {svc.what_you_get}".lower()
        for word in banned:
            assert word not in blob, f"{svc.id} promises: {word}"


def test_range_doctor_accepts_an_observation_block_and_passes_it_down(monkeypatch):
    """Two readers at different times get the same answer only if they name the same block.

    Without this input a buyer can ask what is true now but not what was true at the moment
    both arms of a comparison looked, and only the second is reproducible.
    """
    calls: list[tuple] = []

    def _fake_report(wallet, **kwargs):
        calls.append((wallet, kwargs))
        return {"positions": [], "coverage": "none", "scan_complete": True}

    monkeypatch.setattr("docket.hire.catalogue.doctor.report", _fake_report)
    SERVICES["range-doctor"].run(
        {"wallet": "0xwallet", "observation_block": 114_000_000}
    )
    assert calls[0][1]["observation_block"] == 114_000_000


@pytest.mark.parametrize("bad", [0, -1, True, 1.5, "latest", "0x1"])
def test_range_doctor_refuses_a_block_that_is_not_a_positive_integer(bad):
    """A silently coerced block reads a different chain state than the caller named, and the
    answer looks exactly as authoritative as a correct one."""
    with pytest.raises(
        ValueError, match="observation_block must be a positive integer"
    ):
        SERVICES["range-doctor"].run({"wallet": "0xwallet", "observation_block": bad})
