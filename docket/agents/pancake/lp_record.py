"""A daily record of the controlled position, written as the product's own output.

The experiment party holds one live v3 position so the flagship has an input a stranger can
reproduce. That is only worth something if its history is kept while it happens: a position
observed once on the day of judging is a screenshot, and a position observed every day from
the day it was funded is a record. The difference cannot be manufactured afterwards, which
is the whole reason this runs now rather than later.

What it records is `doctor.report` — the same call the hire route makes, not a second
implementation of it. A parallel reader would eventually disagree with the product about
the product's own position, and the day it did would be the day the record stopped being
evidence about anything.

Two rules the shape of this file exists to keep.

A failed observation is written down. If the endpoints are unreachable the record says so,
with the error, at the time it happened. Silence would leave a gap that reads identically
to nobody having run it, and a reader cannot audit an absence.

Nothing here interprets the sequence. It is state, diagnosis, and later state. Whether the
owner acted, and whether acting turned out well, is not a claim this record makes or is
able to support — the position sits in a market that moves for its own reasons.
"""

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from . import doctor

RECORD_VERSION = "lp-record.v1"


def observe(
    wallet: str,
    token_id: int,
    *,
    declared_position_value_usd: float | None = None,
    estimated_recenter_cost_usd: float | None = None,
    decision_horizon_days: int | None = None,
    reporter=None,
    now=None,
) -> dict:
    """One observation, successful or not, as the line that will be appended.

    `reporter` is resolved here rather than defaulted in the signature: a default binds at
    import, which would silently pin the real network call and leave the seam unpatchable —
    a caller that thought it had substituted a reader would reach the chain instead.
    """
    reporter = reporter or doctor.report
    observed_at = (now or datetime.now(timezone.utc)).isoformat()
    record = {
        "record_version": RECORD_VERSION,
        "observed_at": observed_at,
        "wallet": wallet,
        "token_id": token_id,
    }
    try:
        report = reporter(
            wallet,
            token_id=token_id,
            declared_position_value_usd=declared_position_value_usd,
            estimated_recenter_cost_usd=estimated_recenter_cost_usd,
            decision_horizon_days=decision_horizon_days,
        )
    except Exception as exc:
        # The read failing is itself an observation about the day. Recording the exception
        # type and message keeps a later reader from having to guess whether the endpoints
        # were down, the position was gone, or nobody ran anything.
        record["observed"] = False
        record["error"] = f"{type(exc).__name__}: {exc}"
        return record

    record["observed"] = True
    # About THIS token, not about the wallet. Reading `positions_held` meant a wallet that
    # had transferred the tracked position away but still held any other NFT recorded
    # `still_held: true` — the one day the record exists to catch, reported as a normal day.
    record["target_found"] = bool(report.get("target_found"))
    record["still_held"] = record["target_found"]
    record["wallet_positions_held"] = report.get("positions_held", 0)
    record["report"] = report
    return record


def append(record: dict, path: Path) -> Path:
    """Append one line. The file is the history; nothing rewrites an earlier day."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(record, sort_keys=True) + "\n")
    return path


def read(path: Path) -> list[dict]:
    path = Path(path)
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def main(argv: list[str] | None = None) -> int:
    """The entry point a timer runs, so the record exists rather than being intended."""
    parser = argparse.ArgumentParser(
        description="Record one day's state of the controlled v3 position."
    )
    parser.add_argument("wallet", help="the wallet holding the position")
    parser.add_argument("token_id", type=int, help="the position NFT id")
    parser.add_argument("out", help="the JSONL file to append to")
    parser.add_argument("--declared-value-usd", type=float, default=None)
    parser.add_argument("--recenter-cost-usd", type=float, default=None)
    parser.add_argument("--horizon-days", type=int, default=None)
    args = parser.parse_args(argv)

    record = observe(
        args.wallet,
        args.token_id,
        declared_position_value_usd=args.declared_value_usd,
        estimated_recenter_cost_usd=args.recenter_cost_usd,
        decision_horizon_days=args.horizon_days,
    )
    append(record, Path(args.out))

    if not record["observed"]:
        print(f"observation failed and was recorded: {record['error']}")
        # A failed read is recorded, not swallowed, but the timer should still see that the
        # day did not produce a diagnosis.
        return 1
    if not record["target_found"]:
        print(f"position {args.token_id} was not found under {args.wallet}")
        return 1
    print(f"recorded {args.token_id} at {record['observed_at']}")
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised by the systemd unit
    raise SystemExit(main())
