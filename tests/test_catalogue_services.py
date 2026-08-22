"""The catalogue as a stranger's agent reads it, before anything is dispatched upstream.

Metadata only — no network. `GET /hire` is the whole contract for a caller that
has never seen this site, so the four things it answers (what exists, what
arrives, what to send, what it costs) are asserted here rather than reviewed.
The vocabulary ban lives with the other catalogue tests, where it covers every
service at once.
"""

from docket.hire.catalogue import SERVICES, get_service

OFFERED = ("range-doctor", "solvent-signal", "warden-scan")


def test_all_three_advantage_tasks_are_hireable():
    """One service per report task: liquidity, trading, security."""
    for service_id in OFFERED:
        assert get_service(service_id) is not None, f"{service_id} is not offered"


def test_every_service_states_what_arrives_what_to_send_and_what_it_costs():
    for svc in SERVICES.values():
        assert svc.what_you_get.strip(), f"{svc.id} says nothing about what arrives"
        # Checked by type, not truthiness: taking no arguments is a schema, not a gap.
        assert isinstance(svc.input_schema, dict), f"{svc.id} declares no input schema"
        assert svc.typical_seconds > 0
        assert svc.price_display and svc.price_atomic and svc.asset


def test_solvent_signal_takes_no_arguments():
    """The signal is whatever SOLVENT published last; a caller has nothing to supply."""
    assert get_service("solvent-signal").input_schema == {}


def test_the_solvent_signal_is_offered_as_a_historical_record():
    """SOLVENT completed its scored window on 2026-06-28 and has published nothing since.

    What it sells is the provenance, not freshness — a dated claim nobody can back-date.
    A catalogue entry that read as a live feed would be selling a six-week-old regime
    call as today's, so the disclosure is asserted rather than left to the prose.
    """
    text = get_service("solvent-signal").what_you_get.lower()
    assert "historical record, not a live feed" in text
    assert "has published nothing since" in text


def test_warden_scan_requires_the_untrusted_text():
    assert get_service("warden-scan").input_schema["payload"]["required"] is True


def test_the_two_shelves_stocked_last_are_hireable_and_wired_to_their_previews():
    """A marketplace record for something nobody can call is the split-brain the
    marketplace package closes. These are the two ends of that seam."""
    from docket.hire.catalogue import _run_health_guard, _run_yield_router

    assert get_service("health-guard").run is _run_health_guard
    assert get_service("yield-router").run is _run_yield_router


def test_the_health_guard_reads_one_address_and_takes_nothing_else_required():
    schema = get_service("health-guard").input_schema
    assert schema["wallet"]["required"] is True
    assert schema["trigger_shortfall_usd"]["required"] is False
    assert "never touched" in schema["wallet"]["description"]


def test_grid_filled_is_an_array_of_integer_level_indexes():
    schema = get_service("grid-operator").input_schema["filled"]
    assert schema["type"] == "array"
    assert schema["items"] == {"type": "integer"}


def test_the_yield_comparison_needs_no_wallet_and_the_draft_declares_every_input():
    """The comparison stays a read, while the optional draft has a complete contract."""
    schema = get_service("yield-router").input_schema
    assert not any(field.get("required") for field in schema.values())
    for field in ("wallet", "token_in", "token_out", "amount", "cap"):
        assert field in schema
    assert "supplied rather than derived" in schema["switching_cost_usd"]["description"]


def test_the_controlled_examples_are_prefilled_without_weakening_required_inputs():
    wallet = "0xe55816904796341bf8535e25f6c8b647927fc946"
    range_schema = get_service("range-doctor").input_schema
    assert range_schema["wallet"] == {
        "type": "string",
        "required": True,
        "default": wallet,
        "example_note": "Docket's own controlled position — replace with your address",
        "description": "the 0x-prefixed BSC address whose v3 positions to read",
    }
    assert range_schema["token_id"]["default"] == 7141050
    assert range_schema["declared_position_value_usd"]["default"] == 50.55
    assert range_schema["estimated_recenter_cost_usd"]["default"] == 1.0
    assert range_schema["decision_horizon_days"]["default"] == 30
    assert "default" not in range_schema["limit"]

    for service_id in ("grid-operator", "health-guard"):
        schema = get_service(service_id).input_schema
        assert schema["wallet"]["required"] is True
        assert schema["wallet"]["default"] == wallet


def test_range_reproducibility_inputs_are_marked_for_the_advanced_disclosure():
    schema = get_service("range-doctor").input_schema
    advanced = {name for name, field in schema.items() if field.get("advanced")}
    assert advanced == {
        "observation_block",
        "pool_snapshot",
        "position_manager",
        "source_refs",
        "token_list_snapshot",
    }


def test_every_service_has_a_one_clause_job_summary():
    expected = {
        "grid-operator": "Builds a read-only PancakeSwap V2 grid preview for one wallet.",
        "health-guard": (
            "Reads one wallet's Venus Core Pool position and drafts bounded protective actions."
        ),
        "range-doctor": (
            "Diagnoses one wallet's PancakeSwap v3 position range and fee economics."
        ),
        "solvent-signal": (
            "Relays SOLVENT's last published historical regime signal and provenance."
        ),
        "warden-scan": "Scans one untrusted payload and returns Warden's live telemetry.",
        "yield-router": (
            "Compares an eligible PancakeSwap v3 pool set and states switching break-even."
        ),
    }
    assert {
        service_id: service.job_summary for service_id, service in SERVICES.items()
    } == expected
