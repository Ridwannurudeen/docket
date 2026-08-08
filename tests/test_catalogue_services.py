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
