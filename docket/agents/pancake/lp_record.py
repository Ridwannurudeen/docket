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

Nothing here interprets the sequence. It is state, diagnosis, an owner-entered decision,
and later state. Their association is observed, not causal evidence: the position sits in
a market that moves for its own reasons.
"""

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import doctor

RECORD_VERSION = "lp-record.v1"
CONTROLLED_TOKEN_ID = 7141050
OWNER_DECISIONS = ("WAIT", "RECENTER")


def _canonical_json(record: dict) -> str:
    return json.dumps(
        record, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )


def _record_sha256(record: dict) -> str:
    return hashlib.sha256(_canonical_json(record).encode("utf-8")).hexdigest()


def _validate_decided_at(decided_at: str) -> None:
    if not isinstance(decided_at, str):
        raise ValueError("lp record: decided_at must be an ISO-8601 UTC string")
    try:
        parsed = datetime.fromisoformat(decided_at)
    except ValueError as exc:
        raise ValueError("lp record: decided_at must be an ISO-8601 UTC string") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise ValueError("lp record: decided_at must be an ISO-8601 UTC string")


def _validate_owner_decision(record: dict, observation_hashes: set[str]) -> None:
    if record.get("decision") not in OWNER_DECISIONS:
        raise ValueError("lp record: decision must be WAIT or RECENTER")
    if not isinstance(record.get("rationale"), str) or not record["rationale"].strip():
        raise ValueError("lp record: rationale must be a non-empty string")
    _validate_decided_at(record.get("decided_at"))
    if record.get("token_id") != CONTROLLED_TOKEN_ID:
        raise ValueError(f"lp record: owner decision token_id must be {CONTROLLED_TOKEN_ID}")
    if not isinstance(record.get("alternatives"), list):
        raise ValueError("lp record: alternatives must be a list")
    if record.get("prior_observation_sha256") not in observation_hashes:
        raise ValueError(
            "lp record: prior observation hash does not match an earlier observation"
        )


def _verify_records(records: list[dict]) -> None:
    observation_hashes: set[str] = set()
    latest_decision_sha256 = None
    for line_number, record in enumerate(records, start=1):
        if not isinstance(record, dict):
            raise ValueError(f"lp record: line {line_number} is not a JSON object")
        if record.get("record_version") != RECORD_VERSION:
            raise ValueError(
                f"lp record: line {line_number} has an unknown record version"
            )

        kind = record.get("kind")
        if kind == "owner_decision":
            _validate_owner_decision(record, observation_hashes)
            latest_decision_sha256 = _record_sha256(record)
            continue
        if kind is not None:
            raise ValueError(f"lp record: line {line_number} has an unknown kind")

        answered = record.get("answers_decision_sha256")
        if latest_decision_sha256 is not None and answered != latest_decision_sha256:
            raise ValueError(
                f"lp record: line {line_number} does not answer the latest owner decision hash"
            )
        if latest_decision_sha256 is None and answered is not None:
            raise ValueError(
                f"lp record: line {line_number} references an unknown owner decision hash"
            )
        observation_hashes.add(_record_sha256(record))


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
    history = read_history(path)
    candidate = dict(record)
    if candidate.get("kind") is None:
        latest_decision = next(
            (
                earlier
                for earlier in reversed(history)
                if earlier.get("kind") == "owner_decision"
            ),
            None,
        )
        if latest_decision is not None:
            candidate["answers_decision_sha256"] = _record_sha256(latest_decision)
    _verify_records([*history, candidate])
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(_canonical_json(candidate) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    return path


def read_history(path: Path) -> list[dict]:
    path = Path(path)
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


read = read_history


def append_owner_decision(
    path: Path,
    *,
    decision: str,
    rationale: str,
    decided_at: str,
    prior_observation_sha256: str,
    alternatives: list,
) -> dict:
    record = {
        "record_version": RECORD_VERSION,
        "kind": "owner_decision",
        "decision": decision,
        "rationale": rationale,
        "decided_at": decided_at,
        "prior_observation_sha256": prior_observation_sha256,
        "alternatives": list(alternatives)
        if isinstance(alternatives, list)
        else alternatives,
        "token_id": CONTROLLED_TOKEN_ID,
    }
    append(record, path)
    return record


def verify_history(path: Path) -> None:
    _verify_records(read_history(path))


def main(argv: list[str] | None = None) -> int:
    """The entry point a timer runs, so the record exists rather than being intended."""
    parser = argparse.ArgumentParser(
        description="Record controlled v3 position observations and owner decisions."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    observe_parser = subparsers.add_parser("observe", help="append one observation")
    observe_parser.add_argument("wallet", help="the wallet holding the position")
    observe_parser.add_argument("token_id", type=int, help="the position NFT id")
    observe_parser.add_argument("out", help="the JSONL file to append to")
    observe_parser.add_argument("--declared-value-usd", type=float, default=None)
    observe_parser.add_argument("--recenter-cost-usd", type=float, default=None)
    observe_parser.add_argument("--horizon-days", type=int, default=None)

    decide_parser = subparsers.add_parser(
        "decide", help="append one owner-entered decision"
    )
    decide_parser.add_argument("--path", required=True, help="the JSONL record")
    decide_parser.add_argument("--decision", choices=OWNER_DECISIONS, required=True)
    decide_parser.add_argument("--rationale", required=True)
    decide_parser.add_argument("--decided-at", default=None)
    decide_parser.add_argument("--alternative", action="append", default=[])

    raw_args = list(sys.argv[1:] if argv is None else argv)
    if raw_args and raw_args[0] not in {"observe", "decide"}:
        raw_args.insert(0, "observe")
    args = parser.parse_args(raw_args)

    if args.command == "decide":
        path = Path(args.path)
        verify_history(path)
        prior_observation = next(
            (
                record
                for record in reversed(read_history(path))
                if record.get("kind") is None
            ),
            None,
        )
        if prior_observation is None:
            parser.error("decide requires an earlier observation in the record")
        decided_at = args.decided_at or datetime.now(timezone.utc).isoformat()
        decision = append_owner_decision(
            path,
            decision=args.decision,
            rationale=args.rationale,
            decided_at=decided_at,
            prior_observation_sha256=_record_sha256(prior_observation),
            alternatives=args.alternative,
        )
        print(
            f"recorded owner decision {decision['decision']} at "
            f"{decision['decided_at']}"
        )
        return 0

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
