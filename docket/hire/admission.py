"""The paid-stock facts after the latest operational canary is applied."""

from dataclasses import replace
from datetime import datetime, timedelta, timezone

from .catalogue import PaidStockAdmission, Service

# A daily run gets twelve hours of scheduling and incident-recovery margin. Past that,
# yesterday's observation cannot admit paid work today.
CANARY_MAX_AGE_SECONDS = 36 * 60 * 60


def _fresh_passed_canary(latest_run: dict | None, now: datetime | None = None) -> bool:
    if not isinstance(latest_run, dict) or latest_run.get("verdict") != "passed":
        return False
    finished_at = latest_run.get("finished_at")
    if not isinstance(finished_at, str):
        return False
    try:
        finished = datetime.fromisoformat(finished_at.replace("Z", "+00:00"))
    except ValueError:
        return False
    if finished.tzinfo is None or finished.utcoffset() != timedelta(0):
        return False

    observed_now = now or datetime.now(timezone.utc)
    if observed_now.tzinfo is None:
        return False
    age_seconds = (observed_now.astimezone(timezone.utc) - finished).total_seconds()
    return 0 <= age_seconds <= CANARY_MAX_AGE_SECONDS


def resolve_admission(
    service: Service, latest_run: dict | None, *, now: datetime | None = None
) -> PaidStockAdmission:
    """Apply the latest canary to its one admission limb and leave the other facts intact."""
    return replace(
        service.admission,
        cold_canary=_fresh_passed_canary(latest_run, now),
    )
