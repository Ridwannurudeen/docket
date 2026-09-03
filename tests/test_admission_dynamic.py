"""Three limbs that were constants, and the artifacts they are now derived from.

A constant is a claim about the world that stops being checked the moment it is typed.
`fresh_paired_benchmark` and `true_settlement` were two of those; this file is the truth
table for what replaced them, limb by limb, in both directions, with the evidence string
naming the artifact that decided each one.

Every case pins `now`. The paired limb has a thirty-day window from an artifact's own
observation date, so a test that let the wall clock decide would pass today and fail in a
month for a reason that has nothing to do with the code.
"""

from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from docket.api import create_app
from docket.hire.admission import (
    CANARY_MAX_AGE_SECONDS,
    PAIRED_EVIDENCE_WINDOW_DAYS,
    PAIRED_EVIDENCE_WINDOW_SECONDS,
    TERMINAL_V3_STATES,
    resolve_admission,
)
from docket.hire.catalogue import (
    CONTROLLED_EXAMPLE_WALLET,
    USDT_TOKEN,
    PaidStockAdmission,
    get_service,
)
from docket.hire.x402 import B402_NETWORK
from docket.store import Store

NOW = datetime(2026, 9, 3, 12, tzinfo=timezone.utc)
OBSERVED = NOW - timedelta(days=2)
STALE = NOW - timedelta(days=PAIRED_EVIDENCE_WINDOW_DAYS + 1)
PAY_TO = "0x" + "11" * 20
LIMBS = (
    "fresh_paired_benchmark",
    "cold_canary",
    "decision_grade_presenter",
    "true_settlement",
)


def _v1(
    service_id="range-doctor",
    *,
    delivered=OBSERVED,
    agent_output=True,
    manual_output=True,
    error=None,
):
    return {
        "task_id": "01-liquidity",
        "agent_arm": {
            "name": "agent",
            "error": error,
            "seconds": 43.0,
            "output": (
                {
                    "receipt": {
                        "service": service_id,
                        "delivered_at": delivered.isoformat(),
                        "payment": {"status": "free_tier"},
                    },
                    "result": {},
                }
                if agent_output
                else None
            ),
        },
        "manual_arm": {
            "name": "manual",
            "error": error,
            "seconds": 528.0,
            "output": {"notes": "a human did it"} if manual_output else None,
        },
    }


def _v3(
    service_id="range-doctor",
    *,
    state="refuted",
    recorded=OBSERVED,
    spec_id="v3-90-fixture",
):
    return {
        "families": [
            {
                "spec_id": spec_id,
                "state": state,
                "spec": {"execution_protocol": {"agent_service_id": service_id}},
                "ledger": [
                    {
                        "kind": "run_opened",
                        "recorded_at": (recorded - timedelta(days=1)).isoformat(),
                    },
                    {"kind": "attempt_terminated", "recorded_at": recorded.isoformat()},
                ],
            }
        ]
    }


def _settled_store(
    tmp_path, name, *, service_id="range-doctor", payer=CONTROLLED_EXAMPLE_WALLET
):
    store = Store(tmp_path / f"{name}.sqlite3")
    store.reserve_payment(
        nonce="0x" + "5e" * 32,
        payment_id="0xseed",
        service_id=service_id,
        payer=payer,
        recipient=PAY_TO,
        asset=USDT_TOKEN,
        amount=str(5 * 10**17),
        resource=f"https://docket.example/hire/{service_id}",
        input_hash="0x" + "aa" * 32,
    )
    store.record_payment_output("0xseed", output_hash="0x" + "bb" * 32, result={})
    assert store.begin_payment_settlement("0xseed")
    store.finish_payment(
        "0xseed",
        transaction_id="0x" + "cc" * 32,
        network=B402_NETWORK,
        receipt={"settled": True},
    )
    return store


def _passed_run(finished=NOW - timedelta(hours=1)):
    return {
        "id": 18,
        "verdict": "passed",
        "finished_at": finished.isoformat(),
        "checks": [],
    }


def _resolve(**overrides):
    kwargs = {
        "service": get_service("range-doctor"),
        "latest_run": {},
        "store": None,
        "v3_report": None,
        "v1_experiments": (),
        "now": NOW,
    }
    kwargs.update(overrides)
    service = kwargs.pop("service")
    latest_run = kwargs.pop("latest_run")
    return resolve_admission(service, latest_run, **kwargs)


# ------------------------------------------------------------------ the truth table


def test_with_nothing_supplied_every_derived_limb_is_closed_and_says_why():
    resolution = _resolve()

    assert asdict(resolution.admission) == {
        "fresh_paired_benchmark": False,
        "cold_canary": False,
        "decision_grade_presenter": True,
        "true_settlement": False,
    }
    assert resolution.passes is False
    assert "no payment store was supplied" in resolution.evidence["true_settlement"]
    assert "no v1 experiment names" in resolution.evidence["fresh_paired_benchmark"]
    assert "could not be reconstructed" in resolution.evidence["fresh_paired_benchmark"]


def test_all_four_limbs_open_together_and_only_then_is_a_service_for_sale(tmp_path):
    resolution = _resolve(
        latest_run=_passed_run(),
        store=_settled_store(tmp_path, "all-four"),
        v1_experiments=[_v1()],
    )

    assert asdict(resolution.admission) == dict.fromkeys(LIMBS, True)
    assert resolution.passes is True


@pytest.mark.parametrize("closed", LIMBS)
def test_closing_any_one_limb_closes_the_sale(tmp_path, closed):
    """`passes` is a conjunction. Four separate cases rather than one, because a bug that
    dropped a limb from the conjunction would still pass a test that only ever closed
    the same one."""
    opened = {
        "latest_run": _passed_run(),
        "store": _settled_store(tmp_path, f"minus-{closed}"),
        "v1_experiments": [_v1()],
    }
    if closed == "cold_canary":
        opened["latest_run"] = {}
    elif closed == "true_settlement":
        opened["store"] = None
    elif closed == "fresh_paired_benchmark":
        opened["v1_experiments"] = ()
    else:
        opened["service"] = replace(
            get_service("range-doctor"),
            admission=replace(
                get_service("range-doctor").admission, decision_grade_presenter=False
            ),
        )

    resolution = _resolve(**opened)

    assert getattr(resolution.admission, closed) is False
    assert resolution.passes is False


# ------------------------------------------------------------------ the paired limb


def test_a_v1_experiment_with_both_arms_inside_the_window_opens_the_paired_limb():
    resolution = _resolve(v1_experiments=[_v1()])

    assert resolution.admission.fresh_paired_benchmark is True
    evidence = resolution.evidence["fresh_paired_benchmark"]
    assert "v1 experiment 01-liquidity" in evidence
    assert "both arms with outputs and no error" in evidence
    assert OBSERVED.isoformat() in evidence
    assert "'free_tier' tier" in evidence
    assert f"{PAIRED_EVIDENCE_WINDOW_DAYS}-day window" in evidence
    assert (
        OBSERVED + timedelta(seconds=PAIRED_EVIDENCE_WINDOW_SECONDS)
    ).isoformat() in evidence


def test_the_evidence_says_the_manual_arm_carries_no_timestamp_of_its_own():
    """The window is measured off the agent arm's receipt because it is the only date in
    the file, and a reader should not have to guess that."""
    evidence = _resolve(v1_experiments=[_v1()]).evidence["fresh_paired_benchmark"]

    assert "the manual arm carries none" in evidence


@pytest.mark.parametrize(
    ("experiment", "fragment"),
    (
        (_v1(delivered=STALE), "outside the disclosed"),
        (_v1(delivered=NOW + timedelta(days=1)), "outside the disclosed"),
        (_v1(agent_output=False), "no v1 experiment names"),
        (_v1(manual_output=False), "no v1 experiment names"),
        (_v1(error="timed out"), "no v1 experiment names"),
        (_v1(service_id="grid-operator"), "no v1 experiment names"),
    ),
)
def test_a_v1_experiment_that_is_stale_unpaired_or_failed_opens_nothing(
    experiment, fragment
):
    resolution = _resolve(v1_experiments=[experiment])

    assert resolution.admission.fresh_paired_benchmark is False
    assert fragment in resolution.evidence["fresh_paired_benchmark"]


@pytest.mark.parametrize("state", TERMINAL_V3_STATES)
def test_every_terminal_v3_state_opens_the_paired_limb_including_a_refuted_one(state):
    """The written definition is "produces a paired benchmark", not "passes one". A limb
    that required `not_refuted` would mean "we won" rather than "we measured"."""
    resolution = _resolve(v3_report=_v3(state=state))

    assert resolution.admission.fresh_paired_benchmark is True
    assert state in resolution.evidence["fresh_paired_benchmark"]
    assert "v3-90-fixture" in resolution.evidence["fresh_paired_benchmark"]


@pytest.mark.parametrize(
    "state",
    (
        "registered_waiting_for_inputs",
        "locked_not_run",
        "running",
        "superseded_before_input_lock",
        "abandoned_after_failed_primary",
    ),
)
def test_a_v3_family_that_has_not_finished_pairing_opens_nothing(state):
    resolution = _resolve(v3_report=_v3(state=state))

    assert resolution.admission.fresh_paired_benchmark is False
    assert "terminal state" in resolution.evidence["fresh_paired_benchmark"]


def test_a_terminal_v3_family_outside_the_window_is_named_as_stale():
    resolution = _resolve(v3_report=_v3(recorded=STALE))

    assert resolution.admission.fresh_paired_benchmark is False
    assert "outside the disclosed" in resolution.evidence["fresh_paired_benchmark"]


def test_a_v3_family_registered_for_another_service_does_not_open_this_one():
    resolution = _resolve(v3_report=_v3(service_id="warden-scan"))

    assert resolution.admission.fresh_paired_benchmark is False
    assert (
        "no v3 family registered for range-doctor"
        in (resolution.evidence["fresh_paired_benchmark"])
    )


def test_a_terminal_v3_family_is_named_ahead_of_a_v1_experiment():
    resolution = _resolve(v3_report=_v3(), v1_experiments=[_v1()])

    assert resolution.admission.fresh_paired_benchmark is True
    assert "v3 family" in resolution.evidence["fresh_paired_benchmark"]
    assert "v1 experiment" not in resolution.evidence["fresh_paired_benchmark"]


def test_the_committed_artifacts_on_disk_are_read_the_same_way_the_fixtures_are():
    """The fixtures above are shaped by hand; this reads the real files, so a change to
    either the experiment format or the v3 report shape shows up here."""
    from dataclasses import asdict as _asdict
    from pathlib import Path

    from docket.advantage.harness import load
    from docket.advantage.v3 import report as v3_report

    experiments = [
        _asdict(load(path))
        for path in sorted(Path("docket/advantage/experiments").glob("*.json"))
    ]
    report = v3_report.report()

    range_doctor = resolve_admission(
        get_service("range-doctor"),
        {},
        v3_report=report,
        v1_experiments=experiments,
        now=datetime(2026, 9, 3, 12, tzinfo=timezone.utc),
    )
    grid = resolve_admission(
        get_service("grid-operator"),
        {},
        v3_report=report,
        v1_experiments=experiments,
        now=datetime(2026, 9, 3, 12, tzinfo=timezone.utc),
    )

    assert range_doctor.admission.fresh_paired_benchmark is True
    assert "01-liquidity" in range_doctor.evidence["fresh_paired_benchmark"]
    assert grid.admission.fresh_paired_benchmark is False
    assert range_doctor.passes is False
    assert grid.passes is False


# ------------------------------------------------------------------ the settlement limb


def test_a_settled_row_opens_the_limb_and_names_whose_wallet_paid(tmp_path):
    resolution = _resolve(store=_settled_store(tmp_path, "settled"))

    assert resolution.admission.true_settlement is True
    evidence = resolution.evidence["true_settlement"]
    assert "0xseed" in evidence
    assert "0x" + "cc" * 32 in evidence
    assert "Docket's own operator-run canary, not a third party's purchase" in evidence


def test_a_settlement_by_somebody_else_is_named_as_not_dockets_own(tmp_path):
    stranger = "0x" + "77" * 20
    resolution = _resolve(store=_settled_store(tmp_path, "stranger", payer=stranger))

    assert resolution.admission.true_settlement is True
    assert stranger in resolution.evidence["true_settlement"]
    assert (
        "not Docket's published operator address"
        in (resolution.evidence["true_settlement"])
    )


def test_a_settlement_for_another_service_does_not_open_this_ones_limb(tmp_path):
    resolution = _resolve(
        store=_settled_store(tmp_path, "other-service", service_id="warden-scan")
    )

    assert resolution.admission.true_settlement is False
    assert "has reached 'settled'" in resolution.evidence["true_settlement"]


def test_a_payment_stuck_short_of_settled_is_not_a_settlement(tmp_path):
    store = Store(tmp_path / "unknown.sqlite3")
    store.reserve_payment(
        nonce="0x" + "5f" * 32,
        payment_id="0xpending",
        service_id="range-doctor",
        payer=CONTROLLED_EXAMPLE_WALLET,
        recipient=PAY_TO,
        asset=USDT_TOKEN,
        amount=str(5 * 10**17),
        resource="https://docket.example/hire/range-doctor",
        input_hash="0x" + "aa" * 32,
    )
    store.record_payment_output("0xpending", output_hash="0x" + "bb" * 32, result={})
    assert store.begin_payment_settlement("0xpending")
    store.fail_payment(
        "0xpending",
        status="settlement_unknown",
        error="the facilitator never answered",
        receipt={"status": "unknown"},
    )

    resolution = _resolve(store=store)

    assert resolution.admission.true_settlement is False
    assert "settlement_unknown" in resolution.evidence["true_settlement"]


def test_the_newest_settlement_is_the_one_reported(tmp_path):
    store = _settled_store(tmp_path, "newest")
    store.reserve_payment(
        nonce="0x" + "60" * 32,
        payment_id="0xlater",
        service_id="range-doctor",
        payer=CONTROLLED_EXAMPLE_WALLET,
        recipient=PAY_TO,
        asset=USDT_TOKEN,
        amount=str(5 * 10**17),
        resource="https://docket.example/hire/range-doctor",
        input_hash="0x" + "ab" * 32,
    )
    store.record_payment_output("0xlater", output_hash="0x" + "bc" * 32, result={})
    assert store.begin_payment_settlement("0xlater")
    store.finish_payment(
        "0xlater",
        transaction_id="0x" + "dd" * 32,
        network=B402_NETWORK,
        receipt={"settled": True},
    )

    assert store.latest_settled_payment("range-doctor")["payment_id"] == "0xlater"
    assert "0xlater" in _resolve(store=store).evidence["true_settlement"]


# ------------------------------------------------------------------ the served payload


@pytest.fixture()
def client(tmp_path):
    return TestClient(create_app(tmp_path / "services.sqlite3"))


def test_every_services_card_carries_the_four_limbs_and_the_evidence_beside_them(
    client,
):
    cards = client.get("/services").json()["services"]

    assert cards
    for card in cards:
        assert set(card["admission"]) == set(LIMBS)
        assert set(card["admission_evidence"]) == set(LIMBS) | {"window"}
        assert all(isinstance(value, bool) for value in card["admission"].values())
        assert all(value.strip() for value in card["admission_evidence"].values())
        assert card["paid_stock"] is False


def test_a_closed_limb_says_what_would_open_it_rather_than_only_that_it_is_closed(
    client,
):
    card = client.get("/services/grid-operator").json()

    assert card["admission"]["fresh_paired_benchmark"] is False
    assert (
        "no v1 experiment names grid-operator"
        in (card["admission_evidence"]["fresh_paired_benchmark"])
    )
    assert (
        "no hire_payments row for grid-operator"
        in (card["admission_evidence"]["true_settlement"])
    )
    assert (
        "no canary run has ever been recorded"
        in (card["admission_evidence"]["cold_canary"])
    )


def test_the_canary_page_publishes_both_windows_and_the_same_evidence(client):
    body = client.get("/canary?service_id=range-doctor").json()

    assert body["admission_max_age_seconds"] == CANARY_MAX_AGE_SECONDS
    assert body["paired_evidence_window_days"] == PAIRED_EVIDENCE_WINDOW_DAYS
    assert set(body["admission"]) == set(LIMBS)
    assert set(body["admission_evidence"]) == set(LIMBS) | {"window"}
    assert body["paid_stock"] is False


def test_the_release_smoke_fields_survive_the_new_evidence_key(client):
    """`deploy/release.sh` checks a subset of keys on `/services`; adding a sibling must
    not move any of the ones it pins."""
    body = client.get("/services").json()

    assert {"services", "total", "category", "ordering", "declaration"} <= set(body)
    for row in body["services"]:
        assert {"service_id", "paid_stock", "stock_status", "admission"} <= set(row)
        assert set(LIMBS) <= set(row["admission"])
    assert body["total"] == 6
    assert {row["service_id"] for row in body["services"]} == {
        "grid-operator",
        "health-guard",
        "range-doctor",
        "solvent-signal",
        "warden-scan",
        "yield-router",
    }


def test_the_static_catalogue_constant_still_carries_the_presenter_limb():
    """It is the one limb nothing in the store observes, so it stays stated per service —
    and a service that never had it must not gain it from a derivation."""
    assert get_service("range-doctor").admission.decision_grade_presenter is True
    assert get_service("solvent-signal").admission.decision_grade_presenter is False
    assert isinstance(get_service("grid-operator").admission, PaidStockAdmission)
    assert (
        _resolve(
            service=get_service("solvent-signal")
        ).admission.decision_grade_presenter
        is False
    )
