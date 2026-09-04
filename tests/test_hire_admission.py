"""The cold-canary limb, and every shape of run that must not open it.

The other three limbs moved from constants to derivations and are exercised in
`test_admission_dynamic.py`; this file stays on the one limb it has always been about.
Each assertion reads `.admission.cold_canary` rather than comparing the whole record, so
a change to how another limb is derived cannot make a canary test fail for a reason that
has nothing to do with canaries.
"""

from datetime import UTC, datetime, timedelta

import pytest

from docket.hire.admission import CANARY_MAX_AGE_SECONDS, resolve_admission
from docket.hire.catalogue import get_service
from docket.store import Store

NOW = datetime(2026, 8, 15, 12, tzinfo=UTC)
PASSING_CHECKS = [
    {
        "leg": "complete_human_result",
        "checked": "the complete paid hire chain",
        "status": "passed",
        "observed": {"settlement_amount": "0.50", "replay_status": 409},
        "evidence": {"payment_id": "0xpayment", "transaction_id": "0xtx"},
    }
]


def _service():
    return get_service("range-doctor")


def _passed_run(finished_at: datetime) -> dict:
    return {
        "verdict": "passed",
        "finished_at": finished_at.isoformat(),
        "checks": PASSING_CHECKS,
    }


def _cold_canary(latest_run) -> bool:
    return resolve_admission(_service(), latest_run, now=NOW).admission.cold_canary


def test_empty_history_closes_the_cold_canary_limb():
    resolution = resolve_admission(_service(), {}, now=NOW)

    assert resolution.admission.cold_canary is False
    assert resolution.passes is False
    assert "no canary run has ever been recorded" in resolution.evidence["cold_canary"]


def test_a_fresh_passed_canary_opens_the_cold_canary_limb():
    resolution = resolve_admission(
        _service(), _passed_run(NOW - timedelta(hours=1)), now=NOW
    )

    assert resolution.admission.cold_canary is True
    assert "inside the" in resolution.evidence["cold_canary"]


def test_the_canary_is_still_fresh_at_the_exact_expiry_boundary():
    finished_at = NOW - timedelta(seconds=CANARY_MAX_AGE_SECONDS)

    assert _cold_canary(_passed_run(finished_at)) is True


def test_a_canary_one_second_past_expiry_closes_paid_admission():
    finished_at = NOW - timedelta(seconds=CANARY_MAX_AGE_SECONDS + 1)

    assert _cold_canary(_passed_run(finished_at)) is False


@pytest.mark.parametrize("verdict", ("running", "failed", "not_yet_exercised"))
def test_every_non_passing_verdict_closes_paid_admission(verdict: str):
    latest = {**_passed_run(NOW), "verdict": verdict}

    resolution = resolve_admission(_service(), latest, now=NOW)
    assert resolution.admission.cold_canary is False
    assert verdict in resolution.evidence["cold_canary"]


@pytest.mark.parametrize(
    "finished_at",
    (
        "",
        "not-a-timestamp",
        "2026-08-15T11:00:00",
        "2026-08-15T12:00:00+01:00",
        None,
    ),
)
def test_a_missing_malformed_or_non_utc_finish_time_closes_paid_admission(
    finished_at,
):
    latest = {**_passed_run(NOW), "finished_at": finished_at}

    assert _cold_canary(latest) is False


def test_an_explicitly_blank_persisted_finish_time_is_not_replaced_with_now(tmp_path):
    store = Store(tmp_path / "blank-finish.sqlite3")
    run_id = store.begin_canary_run("range-doctor", "https://docket.example")
    store.finish_canary_run(
        run_id,
        verdict="passed",
        checks=PASSING_CHECKS,
        finished_at="",
    )

    latest = store.latest_canary_run("range-doctor")
    assert latest["finished_at"] == ""
    assert _cold_canary(latest) is False


def test_a_finish_time_in_the_future_closes_paid_admission():
    latest = _passed_run(NOW + timedelta(seconds=1))

    assert _cold_canary(latest) is False


def test_a_crashed_new_run_overrides_an_older_pass(tmp_path):
    store = Store(tmp_path / "crashed-latest.sqlite3")
    passed = store.begin_canary_run("range-doctor", "https://docket.example")
    store.finish_canary_run(
        passed,
        verdict="passed",
        checks=PASSING_CHECKS,
        finished_at=(NOW - timedelta(hours=1)).isoformat(),
    )
    crashed = store.begin_canary_run("range-doctor", "https://docket.example")

    assert store.latest_canary_run("range-doctor")["id"] == crashed
    assert _cold_canary(store.latest_canary_run("range-doctor")) is False


def test_a_new_failure_overrides_an_older_pass(tmp_path):
    store = Store(tmp_path / "failed-latest.sqlite3")
    passed = store.begin_canary_run("range-doctor", "https://docket.example")
    store.finish_canary_run(
        passed,
        verdict="passed",
        checks=PASSING_CHECKS,
        finished_at=(NOW - timedelta(hours=1)).isoformat(),
    )
    failed = store.begin_canary_run("range-doctor", "https://docket.example")
    store.finish_canary_run(
        failed,
        verdict="failed",
        checks=[{**PASSING_CHECKS[0], "status": "failed"}],
        finished_at=NOW.isoformat(),
    )

    assert store.latest_canary_run("range-doctor")["id"] == failed
    assert _cold_canary(store.latest_canary_run("range-doctor")) is False
