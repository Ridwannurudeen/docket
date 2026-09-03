"""Turn a completed capture into the input envelope the stage-two lock will accept.

The capture freezes bytes; the lock wants a structured envelope built from them. Nothing
bridged the two, which meant the Aug 26 morning would have ended with valid evidence on disk
and no way to register it — and the capture cannot be repeated.

The whole design rule here is **derive, never restate**. Every gate, partition and truth value
this module produces is computed with the validator's own functions, imported from `spec`
rather than reimplemented. That is why the private names are used: a second implementation of
`_yield_first_failed_gate` would agree with the first exactly until the day it did not, and
the day it did not would be the day the input lock refused evidence that cannot be recaptured.
The round-trip test runs the real validator over this module's output for the same reason.

What this module cannot derive, it refuses to invent. The eight-case calibration set is
authored, not observed, so it must be supplied; there is no default and no placeholder.
"""

import base64
import hashlib
import json
import os
import tempfile
from pathlib import Path

from .calibration import assemble_evaluator_calibration, verify_calibration_capture
from .spec import (
    REPO_ROOT,
    YIELD_SOURCE_URLS,
    PairedSpec,
    _range_successor_public_position,
    _range_successor_source_frame,
    _range_successor_stratum,
    _range_successor_truth,
    _token_allowlist,
    _validate_inputs,
    _yield_first_failed_gate,
    _yield_number,
    is_range_successor_family,
    is_warden_family,
    lock_inputs,
    range_selected_positions,
    save,
)

# The registered case terms. The validator refuses anything else, so these are named here to
# be read against it rather than tuned.
POSITION_VALUE_USD = 10000
SWITCHING_COST_USD = 25
DECISION_HORIZON_DAYS = 30


class AssemblyRefused(RuntimeError):
    """The capture cannot produce a lockable envelope, so no envelope is produced."""


def _envelope_bytes(envelope: dict) -> bytes:
    return (json.dumps(envelope, indent=2, sort_keys=True) + "\n").encode("utf-8")


def assemble_warden_envelope(
    spec: PairedSpec,
    heldout_cases: bytes,
    vendor_snapshot: bytes,
    *,
    calibration_dir: Path,
    calibration_set: bytes,
) -> dict:
    """Build Warden inputs from authored cases and both captured evaluator seats."""
    if not is_warden_family(spec):
        raise AssemblyRefused("lock-warden accepts only Warden security families")
    try:
        heldout = json.loads(heldout_cases.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AssemblyRefused("the Warden held-out source is not UTF-8 JSON") from exc
    if not isinstance(heldout, dict) or not isinstance(heldout.get("cases"), list):
        raise AssemblyRefused("the Warden held-out source has no cases array")
    snapshot_ref = heldout.get("vendor_snapshot_ref")
    snapshot_sha256 = heldout.get("vendor_snapshot_sha256")
    if not isinstance(snapshot_ref, str) or not snapshot_ref.strip():
        raise AssemblyRefused("the Warden held-out source names no vendor snapshot")
    actual_snapshot_sha256 = hashlib.sha256(vendor_snapshot).hexdigest()
    if snapshot_sha256 != actual_snapshot_sha256:
        raise AssemblyRefused(
            "the supplied Warden vendor snapshot differs from the one the held-out "
            "cases name"
        )
    try:
        evaluator_calibration = assemble_evaluator_calibration(
            spec, calibration_dir, calibration_set
        )
    except ValueError as exc:
        raise AssemblyRefused(str(exc)) from exc
    envelope = {
        "spec_id": spec.spec_id,
        "stage_one_protocol_hash": spec.stage_one_protocol_hash,
        "vendor_snapshot": {
            "ref": snapshot_ref,
            "sha256": actual_snapshot_sha256,
        },
        "calibration_set": {
            "sha256": hashlib.sha256(calibration_set).hexdigest(),
            "body_base64": base64.b64encode(calibration_set).decode("ascii"),
        },
        "evaluator_calibration": evaluator_calibration,
        "cases": heldout["cases"],
    }
    try:
        verify_calibration_capture(spec, envelope, calibration_dir)
    except ValueError as exc:
        raise AssemblyRefused(str(exc)) from exc
    return envelope


def assemble_range_envelope(
    spec: PairedSpec,
    source_refs: list[dict],
    *,
    repo_root: Path,
    calibration_dir: Path,
    calibration_set: bytes,
    evaluator_calibration: list[dict],
) -> dict:
    """Build successor Range inputs from a complete enumerable frame and pool truth."""
    if not is_range_successor_family(spec):
        raise AssemblyRefused("lock-range accepts only enumerable Range successors")
    try:
        wallets, positions, conflicts, frame = _range_successor_source_frame(
            spec, source_refs, repo_root
        )
        selected = range_selected_positions(spec, positions)
    except ValueError as exc:
        raise AssemblyRefused(str(exc)) from exc
    cases = []
    for position in selected:
        stratum = _range_successor_stratum(position)
        cases.append(
            {
                "case_id": f"range-{stratum}-{position['token_id']}",
                "selection_stratum": stratum,
                "chain_id": 56,
                "position_manager": position["position_manager"],
                "wallet": position["wallet"],
                "token_id": position["token_id"],
                "observation_block": frame["observation_block"],
                "observation_time": frame["observation_time"],
                "declared_position_value_usd": POSITION_VALUE_USD,
                "estimated_recenter_cost_usd": SWITCHING_COST_USD,
                "decision_horizon_days": DECISION_HORIZON_DAYS,
                "source_refs": source_refs,
                "truth": _range_successor_truth(position),
            }
        )
    envelope = {
        "spec_id": spec.spec_id,
        "stage_one_protocol_hash": spec.stage_one_protocol_hash,
        "selection_manifest": {
            "candidate_wallets": sorted(wallets),
            "eligible_positions": [
                _range_successor_public_position(position) for position in positions
            ],
            "conflict_exclusions": conflicts,
            "source_refs": source_refs,
        },
        "cases": cases,
        "calibration_set": {
            "sha256": hashlib.sha256(calibration_set).hexdigest(),
            "body_base64": base64.b64encode(calibration_set).decode("ascii"),
        },
        "evaluator_calibration": evaluator_calibration,
    }
    try:
        verify_calibration_capture(spec, envelope, calibration_dir)
        _validate_inputs(spec, _envelope_bytes(envelope), repo_root)
    except ValueError as exc:
        raise AssemblyRefused(str(exc)) from exc
    return envelope


def range_pool_truth(capture_result: dict) -> dict:
    """Bind the first successful registered pool capture and every prior failure."""
    if not capture_result.get("captured"):
        raise AssemblyRefused(
            "the Range pool capture did not complete, so no pool truth can be locked"
        )
    raw = capture_result.get("_raw")
    if not isinstance(raw, tuple) or len(raw) != 2:
        raise AssemblyRefused(
            "the Range pool capture carries no exact raw pools and token-list bytes"
        )
    attempts = capture_result.get("attempts")
    if not isinstance(attempts, list) or not attempts:
        raise AssemblyRefused("the Range pool capture has no attempt history")
    chosen = attempts[-1]
    capture_log = [
        {
            "attempt_ordinal": attempt["attempt_ordinal"],
            "scheduled_at": attempt["scheduled_at"],
            "pools_status": attempt["pools_status"],
            "token_list_status": attempt["token_list_status"],
        }
        for attempt in attempts
    ]
    return {
        "capture_log": capture_log,
        "source_snapshots": {
            "pools": _snapshot("pools", raw[0], chosen["pools_observed_at"], chosen),
            "token_list": _snapshot(
                "token_list", raw[1], chosen["token_list_observed_at"], chosen
            ),
        },
    }


def _range_source_ref(path: Path, kind: str, repo_root: Path) -> dict:
    resolved_root = Path(repo_root).resolve()
    resolved = Path(path).resolve()
    try:
        relative = resolved.relative_to(resolved_root)
    except ValueError as exc:
        raise AssemblyRefused(
            f"the {kind} source must be stored inside {resolved_root}"
        ) from exc
    raw = resolved.read_bytes()
    return {
        "kind": kind,
        "ref": relative.as_posix(),
        "sha256": hashlib.sha256(raw).hexdigest(),
    }


def assemble_yield_envelope(
    spec: PairedSpec,
    capture_result: dict,
    *,
    calibration_dir: Path,
    calibration_set: bytes,
    evaluator_calibration: list[dict],
) -> dict:
    """Build the complete stage-two input envelope from a successful capture.

    `calibration_set` and `evaluator_calibration` are supplied rather than derived because
    neither is observable from the capture: the first is the authored eight-case answer key,
    the second is what each model seat actually answered when run against it. Generating
    either here would be inventing the evidence the calibration exists to provide.
    """
    if not capture_result.get("captured"):
        raise AssemblyRefused(
            "the capture did not complete, so there is nothing to lock. The registration "
            "says the protocol must be recommitted rather than assembled from a later run."
        )
    raw = capture_result.get("_raw")
    if raw is None:
        raise AssemblyRefused(
            "the capture result carries no raw bodies — assemble from the capture itself, "
            "not from its written summary, or the frozen bytes cannot be embedded"
        )

    attempts = capture_result["attempts"]
    chosen = attempts[-1]
    pools_body, token_body = (json.loads(part.decode("utf-8")) for part in raw)

    snapshots = {
        "pools": _snapshot("pools", raw[0], chosen["pools_observed_at"], chosen),
        "token_list": _snapshot(
            "token_list", raw[1], chosen["token_list_observed_at"], chosen
        ),
    }

    # The validator wants exactly the attempts up to and including the chosen one, carrying
    # only the fields it names. The richer record — transport errors, per-URL times — stays in
    # capture-attempts.json, where it is audit trail rather than registered input.
    capture_log = [
        {
            "attempt_ordinal": attempt["attempt_ordinal"],
            "scheduled_at": attempt["scheduled_at"],
            "pools_status": attempt["pools_status"],
            "token_list_status": attempt["token_list_status"],
        }
        for attempt in attempts
    ]

    pool_rows = _pool_rows(pools_body)
    allowlist = _token_allowlist(token_body, "Yield token-list source")
    manifest, included, rows_by_id = _partition(pool_rows, allowlist)
    if len(included) < spec.n_planned:
        raise AssemblyRefused(
            f"only {len(included)} pools passed the registered gates but the family plans "
            f"{spec.n_planned} cases. The captured universe cannot fill the registration."
        )

    selected = sorted(
        included,
        key=lambda pool_id: hashlib.sha256(
            f"{spec.stage_one_protocol_hash}{pool_id.lower()}".encode()
        ).hexdigest(),
    )[: spec.n_planned]

    envelope = {
        "spec_id": spec.spec_id,
        "stage_one_protocol_hash": spec.stage_one_protocol_hash,
        "source_snapshots": snapshots,
        "capture_log": capture_log,
        "truth_manifest": manifest,
        "cases": _cases(selected, included, rows_by_id),
        "calibration_set": {
            "sha256": hashlib.sha256(calibration_set).hexdigest(),
            "body_base64": base64.b64encode(calibration_set).decode("ascii"),
        },
        "evaluator_calibration": evaluator_calibration,
    }
    try:
        verify_calibration_capture(spec, envelope, calibration_dir)
    except ValueError as exc:
        raise AssemblyRefused(str(exc)) from exc
    return envelope


def _snapshot(name: str, body: bytes, observed_at: str, chosen: dict) -> dict:
    return {
        # The registered constant, not the URL the capture happened to call. If the two ever
        # disagreed the capture would already have failed its own check; taking the constant
        # here means the envelope cannot record a URL nobody registered.
        "url": YIELD_SOURCE_URLS[name],
        "observed_at": observed_at,
        "attempt_ordinal": chosen["attempt_ordinal"],
        "sha256": hashlib.sha256(body).hexdigest(),
        "body_base64": base64.b64encode(body).decode("ascii"),
    }


def _pool_rows(pools_body):
    if isinstance(pools_body, list):
        return pools_body
    if isinstance(pools_body, dict) and isinstance(pools_body.get("rows"), list):
        return pools_body["rows"]
    raise AssemblyRefused("the captured pools snapshot is not a list or rows envelope")


def _partition(pool_rows: list, allowlist: set[str]):
    """Apply the registered gates in their registered order, keeping source order."""
    raw_ids, included, excluded, rows_by_id = [], [], [], {}
    for row in pool_rows:
        pool_id = str(row.get("id") or "").lower()
        raw_ids.append(pool_id)
        rows_by_id[pool_id] = row
        failed_gate = _yield_first_failed_gate(row, allowlist)
        if failed_gate is None:
            included.append(pool_id)
        else:
            # reason and first_failed_gate are the same label by registration: an exclusion
            # whose prose differed from its gate could describe a filter that never ran.
            excluded.append(
                {
                    "pool_id": pool_id,
                    "first_failed_gate": failed_gate,
                    "reason": failed_gate,
                }
            )
    manifest = {
        "raw_pool_ids": raw_ids,
        "included_pool_ids": included,
        "excluded": excluded,
    }
    return manifest, included, rows_by_id


def _cases(selected: list[str], included: list[str], rows_by_id: dict) -> list[dict]:
    net_rates = {
        pool_id: (
            _yield_number(rows_by_id[pool_id], "feeUSD24h")
            - _yield_number(rows_by_id[pool_id], "protocolFeeUSD24h")
        )
        * 365
        / _yield_number(rows_by_id[pool_id], "tvlUSD")
        for pool_id in included
    }
    # Ties break on the id, so the best pool is a function of the captured numbers alone and
    # not of dictionary ordering.
    best_pool = min(included, key=lambda pool_id: (-net_rates[pool_id], pool_id))
    best_rate = net_rates[best_pool]

    cases = []
    for index, pool_id in enumerate(selected, start=1):
        current_rate = net_rates[pool_id]
        extra_per_day = POSITION_VALUE_USD * (best_rate - current_rate) / 365
        days_to_recover = (
            SWITCHING_COST_USD / extra_per_day if extra_per_day > 0 else None
        )
        destination = best_pool if extra_per_day > 0 else None
        cases.append(
            {
                "case_id": f"yield-{index:02d}-{pool_id[2:10]}",
                "pool_id": pool_id,
                "position_value_usd": POSITION_VALUE_USD,
                "switching_cost_usd": SWITCHING_COST_USD,
                "decision_horizon_days": DECISION_HORIZON_DAYS,
                "truth": {
                    "current_net_apr": current_rate,
                    "destination_pool_id": destination,
                    "destination_net_apr": best_rate if destination else None,
                    "extra_usd_per_day": extra_per_day,
                    "days_to_recover": days_to_recover,
                    "decision": (
                        "MOVE"
                        if days_to_recover is not None
                        and days_to_recover <= DECISION_HORIZON_DAYS
                        else "STAY"
                    ),
                },
            }
        )
    return cases


def load_capture(directory: Path) -> dict:
    """Rebuild a capture result from what the capture wrote, checking the bytes still match.

    Assembly happens after the capture, from files. Re-reading them without confirming the
    digests would let an edited body be assembled into an envelope that then gets locked —
    the digest would be of the edit, and every later check would agree with it.
    """
    directory = Path(directory)
    result = json.loads(
        (directory / "capture-attempts.json").read_text(encoding="utf-8")
    )
    if not result.get("captured"):
        raise AssemblyRefused(
            f"{directory} holds an incomplete capture: {result.get('why', 'no reason recorded')}"
        )
    bodies = []
    for name, filename in (
        ("pools", "pools.raw.json"),
        ("token_list", "token-list.raw.json"),
    ):
        body = (directory / filename).read_bytes()
        recorded = result[name]["sha256"]
        actual = hashlib.sha256(body).hexdigest()
        if actual != recorded:
            raise AssemblyRefused(
                f"{filename} no longer hashes to what the capture recorded "
                f"({actual} != {recorded}). These are not the captured bytes."
            )
        bodies.append(body)
    result["_raw"] = tuple(bodies)
    return result


def write_envelope(
    spec: PairedSpec, envelope: dict, *, repo_root: Path = REPO_ROOT
) -> Path:
    """Write the envelope where the spec's `inputs_ref` says it lives.

    Deterministic bytes: the lock hashes this file, so key order and separators are part of
    the digest and cannot be left to chance.
    """
    path = Path(repo_root) / spec.inputs_ref
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = _envelope_bytes(envelope)
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False
        ) as temporary:
            temporary_path = Path(temporary.name)
            temporary.write(raw)
            temporary.flush()
            os.fsync(temporary.fileno())
        try:
            os.link(temporary_path, path)
        except FileExistsError as exc:
            raise AssemblyRefused(
                f"{spec.inputs_ref} already exists. Overwriting frozen inputs is how a "
                "second capture quietly replaces the registered one."
            ) from exc
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
    return path


def main(argv: list[str] | None = None) -> int:
    """Assemble frozen evidence, with explicit lock commands for corrected families."""
    import argparse
    import sys

    from .spec import load

    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments and arguments[0] == "lock-range":
        parser = argparse.ArgumentParser(
            description="Assemble and lock the enumerable Range successor."
        )
        parser.add_argument("command")
        parser.add_argument("spec", help="path to the Range successor specification")
        parser.add_argument("frame", help="path to the complete enumerable frame")
        parser.add_argument("capture_dir", help="directory holding the pool capture")
        parser.add_argument("pool_truth", help="first-write path for bound pool truth")
        parser.add_argument("calibration_set", help="path to the eight-case key")
        parser.add_argument(
            "evaluator_calibration", help="both seats' calibration results JSON"
        )
        parser.add_argument(
            "calibration_dir", help="directory holding both seat capture artifacts"
        )
        args = parser.parse_args(arguments)
        try:
            spec_path = Path(args.spec)
            spec = load(spec_path, repo_root=REPO_ROOT)
            pool_truth_path = Path(args.pool_truth)
            truth = range_pool_truth(load_capture(Path(args.capture_dir)))
            truth_raw = (json.dumps(truth, indent=2, sort_keys=True) + "\n").encode(
                "utf-8"
            )
            pool_truth_path.parent.mkdir(parents=True, exist_ok=True)
            try:
                with pool_truth_path.open("xb") as handle:
                    handle.write(truth_raw)
                    handle.flush()
                    os.fsync(handle.fileno())
            except FileExistsError as exc:
                if pool_truth_path.read_bytes() != truth_raw:
                    raise AssemblyRefused(
                        f"{pool_truth_path} already contains different pool truth"
                    ) from exc
            source_refs = [
                _range_source_ref(
                    Path(args.frame), "enumerable_position_frame", REPO_ROOT
                ),
                _range_source_ref(pool_truth_path, "pool_truth", REPO_ROOT),
            ]
            envelope = assemble_range_envelope(
                spec,
                source_refs,
                repo_root=REPO_ROOT,
                calibration_dir=Path(args.calibration_dir),
                calibration_set=Path(args.calibration_set).read_bytes(),
                evaluator_calibration=json.loads(
                    Path(args.evaluator_calibration).read_text(encoding="utf-8")
                ),
            )
            raw = _envelope_bytes(envelope)
            _validate_inputs(spec, raw, REPO_ROOT)
            input_path = Path(REPO_ROOT) / spec.inputs_ref
            try:
                write_envelope(spec, envelope, repo_root=REPO_ROOT)
            except AssemblyRefused:
                if not input_path.is_file() or input_path.read_bytes() != raw:
                    raise
            locked = lock_inputs(spec, repo_root=REPO_ROOT)
            temporary_spec = None
            try:
                with tempfile.NamedTemporaryFile(
                    dir=spec_path.parent,
                    prefix=f".{spec_path.name}.",
                    suffix=".tmp",
                    delete=False,
                ) as temporary:
                    temporary_spec = Path(temporary.name)
                    temporary.write(spec_path.read_bytes())
                    temporary.flush()
                    os.fsync(temporary.fileno())
                save(locked, temporary_spec, repo_root=REPO_ROOT)
                temporary_spec.replace(spec_path)
            finally:
                if temporary_spec is not None:
                    temporary_spec.unlink(missing_ok=True)
        except (AssemblyRefused, OSError, ValueError) as refusal:
            print(f"assembly refused: {refusal}")
            return 2
        print(
            f"locked {input_path} with inputs_sha256={locked.inputs_sha256}. "
            "Commit the frame, capture-bound pool truth, input and specification together."
        )
        return 0

    if arguments and arguments[0] == "lock-warden":
        parser = argparse.ArgumentParser(
            description="Assemble and lock the authored Warden held-out family."
        )
        parser.add_argument("command")
        parser.add_argument("spec", help="path to the Warden specification JSON")
        parser.add_argument("heldout_cases", help="path to the twelve held-out cases")
        parser.add_argument(
            "vendor_snapshot", help="path to the frozen vendor snapshot"
        )
        parser.add_argument("calibration_set", help="path to the eight-case key")
        parser.add_argument(
            "calibration_dir", help="directory holding both seat capture artifacts"
        )
        args = parser.parse_args(arguments)
        try:
            spec = load(Path(args.spec), repo_root=REPO_ROOT)
            envelope = assemble_warden_envelope(
                spec,
                Path(args.heldout_cases).read_bytes(),
                Path(args.vendor_snapshot).read_bytes(),
                calibration_dir=Path(args.calibration_dir),
                calibration_set=Path(args.calibration_set).read_bytes(),
            )
            raw = _envelope_bytes(envelope)
            _validate_inputs(spec, raw, REPO_ROOT)
            input_path = Path(REPO_ROOT) / spec.inputs_ref
            try:
                write_envelope(spec, envelope, repo_root=REPO_ROOT)
            except AssemblyRefused:
                if not input_path.is_file() or input_path.read_bytes() != raw:
                    raise
            locked = lock_inputs(spec, repo_root=REPO_ROOT)
            spec_path = Path(args.spec)
            temporary_spec = None
            try:
                with tempfile.NamedTemporaryFile(
                    dir=spec_path.parent,
                    prefix=f".{spec_path.name}.",
                    suffix=".tmp",
                    delete=False,
                ) as temporary:
                    temporary_spec = Path(temporary.name)
                    temporary.write(spec_path.read_bytes())
                    temporary.flush()
                    os.fsync(temporary.fileno())
                save(locked, temporary_spec, repo_root=REPO_ROOT)
                temporary_spec.replace(spec_path)
            finally:
                if temporary_spec is not None:
                    temporary_spec.unlink(missing_ok=True)
        except (AssemblyRefused, OSError, ValueError) as refusal:
            print(f"assembly refused: {refusal}")
            return 2
        print(
            f"locked {input_path} with inputs_sha256={locked.inputs_sha256}. "
            "Commit the input and updated specification together."
        )
        return 0

    parser = argparse.ArgumentParser(description=main.__doc__.splitlines()[0])
    parser.add_argument("spec", help="path to the stage-one specification JSON")
    parser.add_argument("capture_dir", help="directory the capture wrote")
    parser.add_argument(
        "calibration_set", help="the authored eight-case calibration set JSON"
    )
    parser.add_argument(
        "evaluator_calibration", help="both seats' calibration results JSON"
    )
    parser.add_argument(
        "calibration_dir", help="directory holding both seats' capture artifacts"
    )
    args = parser.parse_args(arguments)

    spec = load(Path(args.spec))
    try:
        envelope = assemble_yield_envelope(
            spec,
            load_capture(Path(args.capture_dir)),
            calibration_dir=Path(args.calibration_dir),
            calibration_set=Path(args.calibration_set).read_bytes(),
            evaluator_calibration=json.loads(
                Path(args.evaluator_calibration).read_text(encoding="utf-8")
            ),
        )
        path = write_envelope(spec, envelope)
    except AssemblyRefused as refusal:
        print(f"assembly refused: {refusal}")
        return 2

    print(
        f"wrote {path} — {len(envelope['cases'])} cases from "
        f"{len(envelope['truth_manifest']['raw_pool_ids'])} captured pools "
        f"({len(envelope['truth_manifest']['included_pool_ids'])} eligible). "
        "Review it, then lock and commit."
    )
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised through main()
    raise SystemExit(main())
