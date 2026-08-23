import pytest

from docket.hire import catalogue
from docket.hire.catalogue import SERVICES, get_service


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
    assert "has not run" in out["measured_value"]["benchmark_unavailable_reason"]


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
