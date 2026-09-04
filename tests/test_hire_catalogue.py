import json

import pytest

from docket.advantage.v3 import report_snapshot
from docket.hire import catalogue
from docket.hire.catalogue import (
    SERVICE_BENCHMARK_FAMILIES,
    SERVICES,
    _benchmark_family,
    get_service,
)

RUBRIC_DESCRIPTION = "0-3 per criterion, summed per output."


def _rubric_scale(criteria_count):
    return {
        "description": RUBRIC_DESCRIPTION,
        "criterion_score_min": 0,
        "criterion_score_max": 3,
        "criteria_count": criteria_count,
        "maximum_total_per_output": 3 * criteria_count,
    }


def _benchmark_report():
    pairings = {
        "v3-01-range-doctor": (
            "range-doctor",
            "superseded_before_input_lock",
            5,
        ),
        "v3-02-yield-router": (
            "yield-router",
            "registered_waiting_for_inputs",
            5,
        ),
        "v3-06-yield-router-assisted": (
            "yield-router",
            "registered_waiting_for_inputs",
            5,
        ),
        "v3-03-warden-security": (
            "warden-scan",
            "superseded_before_input_lock",
            4,
        ),
        "v3-04-warden-security": (
            "warden-scan",
            "registered_waiting_for_inputs",
            4,
        ),
        "v3-05-range-doctor": (
            "range-doctor",
            "registered_waiting_for_inputs",
            5,
        ),
    }
    return {
        "families": [
            {
                "spec_id": spec_id,
                "state": state,
                "spec": {
                    "execution_protocol": {"agent_service_id": service_id},
                    "quality_rubric": {
                        "criteria": [
                            {"name": f"criterion-{index}"}
                            for index in range(criteria_count)
                        ],
                        "scale": RUBRIC_DESCRIPTION,
                    },
                },
            }
            for spec_id, (service_id, state, criteria_count) in pairings.items()
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
            "falsifier_result": None,
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
        report_snapshot,
        "get_report",
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
    assert out["measured_value"]["benchmark_state"] == "registered_waiting_for_inputs"
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
    monkeypatch.setattr(report_snapshot, "get_report", lambda: payload)

    out = get_service("range-doctor").run({"wallet": "0xwallet"})

    assert out["measured_value"] == {
        "this_run_seconds": 1.25,
        "paired_manual_seconds": 42.75,
        "quality_result": quality | {"rubric_scale": _rubric_scale(5)},
        "report_url": "/advantage/v3#v3-05-range-doctor",
        "benchmark_state": "not_refuted",
        "falsifier_result": None,
        "benchmark_unavailable_reason": None,
    }


def test_refuted_benchmark_exposes_overall_verdict_and_fired_checks(monkeypatch):
    quality = {"quality_refuted": False}
    falsifier = {
        "refuted": True,
        "checks": [
            {
                "name": "any_pair_is_incomplete",
                "refuted": True,
                "observed": {"complete_pairs": 2, "planned_pairs": 3},
            }
        ],
    }
    payload = _benchmark_state(
        "v3-05-range-doctor",
        "refuted",
        quality=quality,
        speed={"manual_median_seconds": 42.75},
    )
    family = next(
        row for row in payload["families"] if row["spec_id"] == "v3-05-range-doctor"
    )
    family["falsifier_result"] = falsifier
    monkeypatch.setattr(report_snapshot, "get_report", lambda: payload)

    measured = catalogue._measured_value("range-doctor", 1.25)

    assert measured["benchmark_state"] == "refuted"
    assert measured["falsifier_result"] == falsifier
    assert measured["quality_result"]["quality_refuted"] is False


@pytest.mark.parametrize("manual_median", [None, float("nan"), float("inf")])
def test_a_scored_family_without_a_finite_manual_median_is_unavailable(
    manual_median, monkeypatch
):
    payload = _benchmark_state(
        "v3-05-range-doctor",
        "refuted",
        quality={"quality_refuted": False},
        speed={"manual_median_seconds": manual_median},
    )
    monkeypatch.setattr(report_snapshot, "get_report", lambda: payload)

    measured = catalogue._measured_value("range-doctor", 1.25)

    assert measured == {
        "this_run_seconds": 1.25,
        "paired_manual_seconds": None,
        "quality_result": None,
        "report_url": None,
        "benchmark_state": "refuted",
        "benchmark_unavailable_reason": (
            "The v3 paired family v3-05-range-doctor is scored, but no complete "
            "manual pairs exist; no paired manual median is available."
        ),
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
            "The v3 paired family v3-05-range-doctor is complete but unscored: "
            "score_sheets_missing.",
        ),
    ),
)
def test_unavailable_v3_states_are_precise_and_never_borrow_v1(
    state, unscored_reason, expected_reason, monkeypatch
):
    monkeypatch.setattr(
        report_snapshot,
        "get_report",
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
        "benchmark_state": state,
        "benchmark_unavailable_reason": expected_reason,
    }
    assert "528.31" not in json.dumps(measured, sort_keys=True)


def test_only_mapped_warden_and_yield_runners_gain_measured_value(monkeypatch):
    quality = {"quality_refuted": False}
    payload = _benchmark_report()
    manual_seconds = {
        "v3-06-yield-router-assisted": 61.5,
        "v3-04-warden-security": 27.25,
    }
    for family in payload["families"]:
        if family["spec_id"] in manual_seconds:
            family.update(
                {
                    "state": "refuted",
                    "quality": quality,
                    "speed": {
                        "manual_median_seconds": manual_seconds[family["spec_id"]]
                    },
                    "falsifier_result": {"refuted": True, "checks": []},
                }
            )
    clock = iter((10.0, 11.0, 20.0, 22.5))
    monkeypatch.setattr(catalogue.time, "perf_counter", lambda: next(clock))
    monkeypatch.setattr(report_snapshot, "get_report", lambda: payload)
    monkeypatch.setattr(
        catalogue,
        "_call_upstream",
        lambda method, url, body=None: (
            {"verdict": "ALLOW"} if method == "POST" else {"regime": "neutral"}
        ),
    )

    class PoolClient:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def top_pools_snapshot(self):
            return [], b"[]"

        def token_allowlist_snapshot(self):
            return set(), b'{"tokens":[]}'

    class EmptyUniverse:
        included = ()

        def as_record(self):
            return {"included": []}

    class GridPreview:
        def __init__(self, *args, **kwargs):
            pass

        def preview(self, *, filled):
            return {"kind": "grid", "filled": list(filled)}

    class HealthGuardPreview:
        def __init__(self, *args, **kwargs):
            pass

        def preview(self, wallet, *, observation_block=None):
            return {
                "kind": "health",
                "wallet": wallet,
                "account": {"as_of_block": 1, "address": wallet},
            }

    class Record:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    monkeypatch.setattr("docket.agents.pancake.pools.PoolClient", PoolClient)
    monkeypatch.setattr(
        "docket.agents.yield_router.universe.eligible_pools",
        lambda *args, **kwargs: EmptyUniverse(),
    )
    monkeypatch.setattr(
        "docket.agents.grid.operator.observe_price",
        lambda *args, **kwargs: Record(price=100),
    )
    monkeypatch.setattr("docket.agents.grid.operator.GridPreview", GridPreview)
    monkeypatch.setattr(
        "docket.agents.grid.plan.build_plan", lambda **kwargs: kwargs
    )
    monkeypatch.setattr("docket.execution.simulate.BscQuoteReader", object)
    monkeypatch.setattr(
        "docket.agents.venus.guard.HealthGuardPreview", HealthGuardPreview
    )
    monkeypatch.setattr("docket.agents.venus.guard.GuardPolicy", Record)
    monkeypatch.setattr("docket.agents.venus.guard.MarketPolicy", Record)
    monkeypatch.setattr("docket.agents.venus.markets.VenusReader", object)

    warden = get_service("warden-scan").run({"payload": "hello"})
    yield_result = get_service("yield-router").run({})
    grid = get_service("grid-operator").run({"wallet": "0xwallet"})
    health = get_service("health-guard").run({"wallet": "0xwallet"})
    solvent = get_service("solvent-signal").run({})

    assert grid == {"kind": "grid", "filled": []}
    # The runner adds the four fields v3-09 reads: which block it answered about, the
    # address it answered for, and the source references it was handed.
    assert health["kind"] == "health"
    assert health["wallet"] == "0xwallet"
    assert health["requested_observation_block"] is None
    assert health["as_of_block"] == 1
    assert health["address"] == "0xwallet"
    assert health["sources"] is None
    assert solvent == {"regime": "neutral"}
    assert "measured_value" not in grid | health | solvent
    assert warden["measured_value"] == {
        "this_run_seconds": 1.0,
        "paired_manual_seconds": 27.25,
        "quality_result": quality | {"rubric_scale": _rubric_scale(4)},
        "report_url": "/advantage/v3#v3-04-warden-security",
        "benchmark_state": "refuted",
        "falsifier_result": {"refuted": True, "checks": []},
        "benchmark_unavailable_reason": None,
    }
    assert yield_result["measured_value"] == {
        "this_run_seconds": 2.5,
        "paired_manual_seconds": 61.5,
        "quality_result": quality | {"rubric_scale": _rubric_scale(5)},
        "report_url": "/advantage/v3#v3-06-yield-router-assisted",
        "benchmark_state": "refuted",
        "falsifier_result": {"refuted": True, "checks": []},
        "benchmark_unavailable_reason": None,
    }


def test_warden_payload_limit_preserves_the_exact_text_or_rejects_before_upstream(
    monkeypatch,
):
    calls = []

    def call_upstream(method, url, body=None):
        calls.append((method, url, body))
        return {"verdict": "ALLOW"}

    monkeypatch.setattr(catalogue, "_call_upstream", call_upstream)
    maximum = "x" * catalogue.WARDEN_MAX_PAYLOAD_CHARACTERS

    get_service("warden-scan").run({"payload": maximum})

    assert calls == [("POST", catalogue.WARDEN_SCAN_URL, {"payload": maximum})]
    assert get_service("warden-scan").input_schema["payload"]["maxLength"] == 4_000

    with pytest.raises(ValueError, match="must not exceed 4000 characters"):
        get_service("warden-scan").run({"payload": maximum + "x"})
    assert len(calls) == 1


def test_hire_uses_the_process_pinned_report_until_reset(monkeypatch):
    waiting = _benchmark_state(
        "v3-05-range-doctor", "registered_waiting_for_inputs"
    )
    quality = {"quality_refuted": False}
    scored = _benchmark_state(
        "v3-05-range-doctor",
        "not_refuted",
        quality=quality,
        speed={"manual_median_seconds": 42.75},
    )
    reports = iter((waiting, scored))
    builds = []

    def build_report():
        builds.append("built")
        return next(reports)

    monkeypatch.setattr(report_snapshot.report_module, "report", build_report)
    report_snapshot._reset_for_testing()

    first = catalogue._measured_value("range-doctor", 1.0)
    second = catalogue._measured_value("range-doctor", 2.0)

    assert first["benchmark_state"] == "registered_waiting_for_inputs"
    assert second["benchmark_state"] == "registered_waiting_for_inputs"
    assert report_snapshot.get_report() is waiting
    assert builds == ["built"]

    report_snapshot._reset_for_testing()
    available = catalogue._measured_value("range-doctor", 3.0)

    assert available == {
        "this_run_seconds": 3.0,
        "paired_manual_seconds": 42.75,
        "quality_result": quality | {"rubric_scale": _rubric_scale(5)},
        "report_url": "/advantage/v3#v3-05-range-doctor",
        "benchmark_state": "not_refuted",
        "falsifier_result": None,
        "benchmark_unavailable_reason": None,
    }
    assert report_snapshot.get_report() is scored
    assert builds == ["built", "built"]
    report_snapshot._reset_for_testing()


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
