"""Record one catalogue service read without turning it into a paired benchmark."""

import argparse
import json
import time
from datetime import UTC, datetime
from pathlib import Path

from ..hire.catalogue import get_service
from ..hire.receipts import canonical_hash, is_human_readable_result

SINGLE_READ = "single recorded read; no paired run against a person"
RUN_FILES = {
    "health-guard": "05-health-guard-read.json",
    "grid-operator": "06-grid-preview-read.json",
    "yield-router": "07-yield-router-read.json",
}
RUN_DEFINITIONS = {
    "health-guard": {
        "task_id": "05-health-guard-read",
        "category": "health factor",
        "question": "What Venus Core Pool position does this wallet have at the recorded read?",
    },
    "grid-operator": {
        "task_id": "06-grid-preview-read",
        "category": "grid trading",
        "question": "What hash-bound grid actions do live PancakeSwap V2 quotes produce?",
    },
    "yield-router": {
        "task_id": "07-yield-router-read",
        "category": "yield optimisation",
        "question": "What does the live eligible PancakeSwap V3 pool set contain?",
    },
}
RECORDED_RUNS = Path(__file__).resolve().parent / "recorded_runs"


def load_record(service_id: str) -> dict:
    """Load one committed single-read record by catalogue service id."""
    try:
        filename = RUN_FILES[service_id]
    except KeyError as exc:
        raise ValueError(
            f"no recorded category run is defined for {service_id!r}"
        ) from exc
    return json.loads((RECORDED_RUNS / filename).read_text(encoding="utf-8"))


def _observation(service_id: str, result: dict, recorded_at: str) -> dict:
    if service_id == "health-guard":
        account = result.get("account")
        if not isinstance(account, dict) or account.get("complete") is not True:
            raise ValueError("record refused: the Venus account read is incomplete")
        rows = account.get("rows")
        if not isinstance(rows, list) or not rows:
            raise ValueError(
                "record refused: the Venus result contains no entered market"
            )
        borrowed = sum(int(row.get("borrow_balance") or 0) > 0 for row in rows)
        if not borrowed:
            raise ValueError(
                "record refused: the Venus result contains no borrow balance"
            )
        block = account.get("as_of_block")
        if not isinstance(block, int) or block <= 0:
            raise ValueError(
                "record refused: the Venus result reports no observation block"
            )
        entered = account.get("markets_entered")
        listed = account.get("markets_listed")
        return {
            "block": block,
            "observed_at": recorded_at,
            "time_source": (
                "recorder completion time; the service reports a block but no block timestamp"
            ),
            "window": (
                f"{SINGLE_READ}; one wallet across {entered} entered Venus Core Pool "
                "markets"
            ),
            "population": (
                f"{borrowed} entered markets with a non-zero borrow balance of {entered} "
                f"entered, from {listed} Venus Core Pool markets listed at block {block}"
            ),
            "method": (
                "The catalogue health-guard runner read Unitroller.getAccountLiquidity, "
                "getAssetsIn, each entered vToken snapshot, and the current Venus oracle; "
                f"the service stamped the read at BSC block {block}."
            ),
            "does_not_show": (
                "It does not show a liquidation, a future account state, or a paired run "
                "against a person; the block is a provenance stamp, not an atomic block-tagged "
                "snapshot of every RPC call."
            ),
        }

    if service_id == "grid-operator":
        observation = result.get("observation")
        levels = result.get("levels")
        plan = result.get("plan")
        if (
            not isinstance(observation, dict)
            or not isinstance(levels, list)
            or not levels
        ):
            raise ValueError("record refused: the grid result contains no quoted level")
        if not isinstance(plan, dict) or not isinstance(
            plan.get("requested_levels"), int
        ):
            raise ValueError(
                "record refused: the grid result contains no requested population"
            )
        quoted = sum(
            bool(
                level.get("intent")
                and level.get("simulation")
                and level["simulation"].get("agrees") is True
            )
            for level in levels
            if isinstance(level, dict)
        )
        if not quoted:
            raise ValueError(
                "record refused: no grid level has a usable quote and simulation"
            )
        block = observation.get("block_number")
        if not isinstance(block, int) or block <= 0:
            raise ValueError(
                "record refused: the grid result reports no observation block"
            )
        requested = plan["requested_levels"]
        return {
            "block": block,
            "observed_at": recorded_at,
            "time_source": (
                "recorder completion time; the service reports a block but no block timestamp"
            ),
            "window": f"{SINGLE_READ}; one {requested}-level grid preview",
            "population": (
                f"{quoted} quoted and simulation-matched levels of {requested} requested "
                f"levels for the recorded wallet at BSC block {block}"
            ),
            "method": (
                "The catalogue grid-operator runner built its deterministic WBNB/USDT band, "
                "asked PancakeSwap V2 Router.getAmountsOut for the observation and each level, "
                f"and hash-bound every usable action; the service reported BSC block {block}."
            ),
            "does_not_show": (
                "It does not show a submitted transaction, fill, gain, adaptive trading "
                "decision, or paired run against a person."
            ),
        }

    universe = result.get("universe")
    candidates = result.get("candidates")
    if (
        not isinstance(universe, dict)
        or not isinstance(candidates, list)
        or not candidates
    ):
        raise ValueError("record refused: the yield result contains no compared pool")
    size = universe.get("size")
    considered = universe.get("considered")
    source = universe.get("source")
    observed_at = universe.get("observed_at")
    if (
        not isinstance(size, int)
        or size <= 0
        or not isinstance(considered, int)
        or considered < size
        or not isinstance(source, str)
        or not source.strip()
        or not isinstance(observed_at, str)
        or not observed_at.strip()
    ):
        raise ValueError(
            "record refused: the yield result has no complete source population"
        )
    return {
        "block": None,
        "observed_at": observed_at,
        "time_source": "PancakeSwap explorer snapshot time reported by the service",
        "window": f"{SINGLE_READ}; one explorer top-pools snapshot",
        "population": (
            f"{size} eligible pools of {considered} considered from {source} at {observed_at}"
        ),
        "method": (
            f"The catalogue yield-router runner read the PancakeSwap explorer top list and "
            f"token allowlist at {observed_at}, applied the stated TVL, turnover, token, and "
            f"fee-data gates, and compared {size} eligible pools of {considered} considered. "
            "The comparison-only path made no BSC eth_call, so it reports no chain block."
        ),
        "does_not_show": (
            "It does not show another venue, future yield, position-specific earnings, a "
            "submitted move, or a paired run against a person."
        ),
    }


def record(service_id: str, payload: dict, *, out_path, clock) -> dict:
    """Run the catalogue callable once and persist one honest, hash-bound read."""
    if service_id not in RUN_DEFINITIONS:
        raise ValueError(
            f"record refused: no category-read definition for {service_id!r}"
        )
    if not isinstance(payload, dict):
        raise ValueError("record refused: payload must be a JSON object")
    service = get_service(service_id)
    if service is None:
        raise ValueError(f"record refused: no catalogue service {service_id!r}")
    request_payload = json.loads(json.dumps(payload, ensure_ascii=False))
    input_hash = canonical_hash(request_payload)

    checked_at = clock()
    if not isinstance(checked_at, datetime) or checked_at.tzinfo is None:
        raise ValueError("record refused: clock must return a timezone-aware datetime")
    started = time.perf_counter()
    result = service.run(payload)
    elapsed = max(0.0, time.perf_counter() - started)
    finished_at = clock()
    if not isinstance(finished_at, datetime) or finished_at.tzinfo is None:
        raise ValueError("record refused: clock must return a timezone-aware datetime")
    recorded_at = finished_at.astimezone(UTC).isoformat()

    if not isinstance(result, dict) or not is_human_readable_result(result):
        raise ValueError(
            "record refused: the catalogue runner returned an empty result"
        )
    if result.get("error") not in (None, False, 0, ""):
        raise ValueError("record refused: the catalogue runner returned an error")
    observation = _observation(service_id, result, recorded_at)
    receipt = {
        "service": service_id,
        "input_hash": input_hash,
        "output_hash": canonical_hash(result),
        "delivered_at": recorded_at,
        "payment": {
            "status": "read_only_recording",
            "note": "No payment, signature, transaction, or network write was made.",
        },
    }
    output = {
        "request": request_payload,
        "receipt": receipt,
        "observation": observation,
        "result": result,
    }
    definition = RUN_DEFINITIONS[service_id]
    path = Path(out_path)
    command_payload = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    body = {
        "task_id": definition["task_id"],
        "question": definition["question"],
        "category": definition["category"],
        "agent_arm": {
            "name": "agent",
            "seconds": elapsed,
            "output": output,
            "output_hash": canonical_hash(output),
            "cost": {
                "amount": "0",
                "unit": "USD",
                "note": "public read endpoints only; no API key, payment, or transaction",
            },
            "error": None,
        },
        "manual_arm": {
            "name": "manual",
            "seconds": None,
            "output": None,
            "output_hash": None,
            "cost": None,
            "error": SINGLE_READ,
        },
        "manual_steps": [
            f"python -m docket.advantage.record_run {service_id} --payload "
            f"'{command_payload}' --out {path.as_posix()}"
        ],
        "notes": (
            f"This is a {SINGLE_READ}. {observation['does_not_show']} Re-running reads "
            "new live state and is expected to produce different times, blocks, outputs, "
            "and hashes."
        ),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    blob = json.dumps(body, sort_keys=True, indent=2, ensure_ascii=False)
    path.write_text(blob + "\n", encoding="utf-8", newline="\n")
    return body


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("service_id", choices=tuple(RUN_DEFINITIONS))
    parser.add_argument(
        "--payload", required=True, help="JSON object passed to Service.run"
    )
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        payload = json.loads(args.payload)
    except json.JSONDecodeError as exc:
        parser.error(f"--payload is not JSON: {exc}")
    if not isinstance(payload, dict):
        parser.error("--payload must be a JSON object")
    record(
        args.service_id,
        payload,
        out_path=args.out,
        clock=lambda: datetime.now(UTC),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
