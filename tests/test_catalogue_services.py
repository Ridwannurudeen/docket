"""The catalogue as a stranger's agent reads it, before anything is dispatched upstream.

Metadata only — no network. `GET /hire` is the whole contract for a caller that
has never seen this site, so the four things it answers (what exists, what
arrives, what to send, what it costs) are asserted here rather than reviewed.
The vocabulary ban lives with the other catalogue tests, where it covers every
service at once.
"""

import pytest

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


CONTROLLED = "0xe55816904796341bf8535e25f6c8b647927fc946"


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

    assert (
        get_service("grid-operator").input_schema["wallet"]["example_note"]
        == "Docket's own controlled wallet — replace with your address"
    )
    assert (
        get_service("health-guard").input_schema["wallet"]["example_note"]
        == "Docket's controlled wallet has no Venus position, so the honest result is no position — replace with your address"
    )


def test_warden_card_distinguishes_live_freshness_from_recorded_evidence():
    assert (
        "live upstream call; the recorded run is evidence, not freshness"
        in get_service("warden-scan").what_you_get.lower()
    )


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
            "Watches one Venus Core Pool position and prepares the least remedy that "
            "restores its ratio."
        ),
        "range-doctor": (
            "Watches one PancakeSwap v3 position and prepares the reset when its range "
            "is left."
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


def test_the_health_guard_answers_about_the_block_it_was_asked_about():
    """v3-09's agent contract is "the endpoint must answer about that account at that
    block". The harness posts observation_block and source_refs, so the runner has to
    carry both into the read and back into the response — an answer about a different
    block is a blocked contract rather than a worse answer."""
    from docket.hire import catalogue

    seen = {}

    class _Preview:
        def __init__(self, *, reader, policy):
            seen["policy"] = policy

        def preview(self, wallet, *, observation_block=None):
            seen["wallet"] = wallet
            seen["block"] = observation_block
            # The real `preview()` shape, including the nested assessment block that
            # Lane F's orchestrator reads the observed block out of. A fixture returning
            # only the top-level key would let a route that never filled the nested one
            # pass, and the harness would record a blocked contract instead.
            return {
                "address": wallet,
                "account": {"as_of_block": observation_block or 9, "address": wallet},
                "assessment": {
                    "address": wallet,
                    "as_of_block": observation_block or 9,
                    "status": "no_position",
                },
                "policy": {},
                "actions": [],
                "submitted": False,
            }

    import docket.agents.venus.guard as guard_module

    saved = guard_module.HealthGuardPreview
    guard_module.HealthGuardPreview = _Preview
    try:
        refs = [{"kind": "venus_frame", "url": "https://example/frame"}]
        result = catalogue._run_health_guard(
            {
                "wallet": CONTROLLED,
                "observation_block": 119_627_412,
                "source_refs": refs,
            }
        )
    finally:
        guard_module.HealthGuardPreview = saved

    assert seen["block"] == 119_627_412
    assert result["requested_observation_block"] == 119_627_412
    assert result["as_of_block"] == 119_627_412
    assert result["address"] == CONTROLLED
    assert result["sources"] == refs
    # Lane F's orchestrator reads the nested key, not only the top-level one.
    assert result["assessment"]["as_of_block"] == 119_627_412
    assert result["assessment"]["address"] == CONTROLLED
    assert result["account"]["as_of_block"] == 119_627_412


@pytest.mark.parametrize("bad", [0, -1, "latest", 1.5, True])
def test_a_block_that_is_not_a_positive_integer_is_refused(bad):
    from docket.hire import catalogue

    with pytest.raises(ValueError, match="positive integer block number"):
        catalogue._observation_block({"observation_block": bad})


def test_source_refs_must_be_a_list_of_references():
    from docket.hire import catalogue

    with pytest.raises(ValueError, match="source_refs must be a list"):
        catalogue._run_health_guard(
            {"wallet": CONTROLLED, "source_refs": {"kind": "venus_frame"}}
        )


def test_the_pinned_inputs_are_marked_for_the_advanced_disclosure():
    schema = get_service("health-guard").input_schema
    advanced = {name for name, field in schema.items() if field.get("advanced")}
    assert advanced == {"observation_block", "source_refs"}
    assert "observation_block_unsupported" in schema["observation_block"]["description"]
