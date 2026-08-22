"""One table a buyer can compare services in, including the services that lose.

The marketplace criterion is that someone can find, compare and hire without instructions.
Comparison is the part Docket was worst at: the catalogue said what each service does and
what it costs, and left the reader to work out which of them had ever been measured against
a human doing the same job. Three have. Three have not, and the honest table is the one that
says which is which rather than the one where every row is populated.

So the rule this module exists to keep: a cell is either a measurement with its source and
its sample size, or a stated reason there is none. It is never blank, never zero, and never
a number carried over from a different service because the column looked empty.

Sample sizes here are 1. That is not a typo and it is not hidden — the v1 runs are single
paired tasks, and a reader comparing services deserves to see the denominator rather than a
time saving presented as though it were a rate.
"""

import json
from pathlib import Path

EXPERIMENTS = Path(__file__).resolve().parent.parent / "advantage" / "experiments"

# Which v1 paired experiment, if any, measured each service. A service absent from this map
# has no paired run at all, which is a fact about the service rather than a gap in the map.
MEASURED_BY = {
    "range-doctor": "01-liquidity.json",
    "solvent-signal": "02-trading.json",
    "warden-scan": "03-security.json",
}

NO_MEASUREMENT = "No paired run against a human exists for this service, so no time saving is claimed."

LIVE_READ_FRESHNESS = {
    "grid-operator": "Live BSC read at hire time.",
    "health-guard": "Live BSC read at hire time.",
    "warden-scan": (
        "Live upstream call at hire time; the recorded run is evidence, not freshness."
    ),
    "yield-router": "Live PancakeSwap explorer and BSC reads at hire time.",
}


def _measurement(service_id: str, experiments: Path) -> dict:
    filename = MEASURED_BY.get(service_id)
    if filename is None:
        return {"available": False, "reason": NO_MEASUREMENT}
    path = Path(experiments) / filename
    if not path.is_file():
        return {
            "available": False,
            "reason": f"the recorded run {filename!r} is not present in this build",
        }
    body = json.loads(path.read_text(encoding="utf-8"))
    agent = body.get("agent_arm") or {}
    manual = body.get("manual_arm") or {}
    agent_seconds = agent.get("seconds")
    manual_seconds = manual.get("seconds")
    if not isinstance(agent_seconds, (int, float)) or not isinstance(
        manual_seconds, (int, float)
    ):
        return {
            "available": False,
            "reason": f"{filename!r} records no elapsed time for one of its two arms",
        }
    output = agent.get("output") or {}
    receipt = output.get("receipt") or {}
    result = output.get("result") or {}
    delivered_at = receipt.get("delivered_at")
    recorded_at = delivered_at
    observation_block = None
    if service_id == "range-doctor":
        recorded_at = result.get("computed_at") or recorded_at
        positions = result.get("positions") or []
        if positions:
            observation_block = (positions[0].get("diagnosis") or {}).get("as_of_block")
    elif service_id == "solvent-signal":
        recorded_at = result.get("generated_at") or recorded_at
    measured_date = (
        str(delivered_at)[:10] if isinstance(delivered_at, str) else "date not recorded"
    )
    if observation_block is not None:
        freshness = f"Recorded BSC block {observation_block} at {recorded_at}."
    elif recorded_at is not None:
        prefix = (
            "Historical source generated"
            if service_id == "solvent-signal"
            else "Recorded run delivered"
        )
        freshness = f"{prefix} at {recorded_at}."
    else:
        freshness = "Recorded run; time not recorded."
    return {
        "available": True,
        "agent_seconds": float(agent_seconds),
        "manual_seconds": float(manual_seconds),
        "seconds_saved": float(manual_seconds) - float(agent_seconds),
        "sample_size": 1,
        "source": f"docket/advantage/experiments/{filename}",
        "task_id": body.get("task_id"),
        "basis": f"measured, n=1, {measured_date}",
        "freshness": freshness,
        # The manual arm's own cost, which is usually zero and usually the more honest
        # comparison: the alternative to hiring is often free, just slow.
        "manual_cost": (manual.get("cost") or {}).get("amount"),
        "manual_cost_unit": (manual.get("cost") or {}).get("unit"),
    }


def _failing_limbs(admission) -> list[str]:
    limbs = admission if isinstance(admission, dict) else vars(admission)
    return sorted(name for name, passed in limbs.items() if passed is False)


def compare(services, *, experiments: Path = EXPERIMENTS) -> dict:
    """Build the comparison rows from the catalogue and the recorded runs.

    Nothing here reaches a network or a chain. It reads what the catalogue already declares
    and what the repository already recorded, so the table cannot say something the rest of
    the product does not.
    """
    rows = []
    for service in services:
        admission = getattr(service, "admission", None)
        measured = _measurement(service.id, experiments)
        evidence = (
            {
                "available": True,
                "url": f"/advantage#{measured['task_id']}",
                "label": "Paired run, n=1",
            }
            if measured["available"]
            else {"available": False, "reason": measured["reason"]}
        )
        rows.append(
            {
                "service_id": service.id,
                "name": service.name,
                "job": service.job_summary,
                "price_display": service.price_display,
                "asset": service.asset,
                "typical_seconds": service.typical_seconds,
                "typical_seconds_basis": "declared",
                "stock_status": service.stock_status,
                "paid_stock": bool(getattr(service, "paid_stock", False)),
                "admission_failing": _failing_limbs(admission) if admission else [],
                "measured": measured,
                "freshness": LIVE_READ_FRESHNESS.get(
                    service.id,
                    measured["freshness"]
                    if measured["available"]
                    else "No data-recency statement is recorded for this service.",
                ),
                "evidence": evidence,
            }
        )
    measured = [row for row in rows if row["measured"]["available"]]
    return {
        "rows": rows,
        "summary": {
            "services": len(rows),
            "services_with_a_paired_measurement": len(measured),
            "largest_sample_size": max((1 for _ in measured), default=0),
            "reading": (
                "Time saved is measured against one human doing the same task once. "
                "A single pair is evidence that the work was done both ways, not a rate, "
                "and services with no pair make no speed claim at all."
            ),
        },
    }
