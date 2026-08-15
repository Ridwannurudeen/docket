"""Turn the immutable v3 ledger into blinded, checkable score evidence.

This module contains no provider client and makes no model call. The operator exports one
bundle into two clean sessions and imports one JSON sheet from each registered seat. Until
both immutable sheet artifacts exist, the A/B mapping is not written anywhere by this
module. Once they do, the mapping publishes every byte needed to recompute it.

Raw arm outputs remain in the append-only ledger. The bundle carries only a deterministic
family projection: registered task fields with transport and commercial envelope metadata
removed. A failed primary never asks a model to judge an error message; every criterion is
fixed at zero. A blocked service contract is different. It means the registered agent arm
could not be run, so the family remains unscored instead of recording a task loss that did
not happen.
"""

import hashlib
import json
import os
import re
import statistics
from base64 import b64decode, b64encode
from collections import Counter
from decimal import Decimal, InvalidOperation
from pathlib import Path

from ...hire.receipts import canonical_hash
from . import runner
from .spec import PairedSpec, assert_runnable

FAMILY_PROTOCOLS = {
    "v3-01-range-doctor": {
        "normalisation_version": (
            "range.v1: position, observation, range, pool_evidence, rates, dollars, "
            "action, coverage, limitations, sources"
        ),
        "fields": (
            "position",
            "observation",
            "range",
            "pool_evidence",
            "rates",
            "dollars",
            "action",
            "coverage",
            "limitations",
            "sources",
        ),
        "family_salt": "range-blinding",
        "service_literals": ("Range Doctor", "range-doctor", "range_doctor"),
    },
    "v3-02-yield-router": {
        "normalisation_version": (
            "yield.v1: sources, universe, rates, scenario, decision, limitations"
        ),
        "fields": (
            "sources",
            "universe",
            "rates",
            "scenario",
            "decision",
            "limitations",
        ),
        "family_salt": "yield-blinding",
        "service_literals": ("Yield Router", "yield-router", "yield_router"),
    },
    "v3-03-warden-security": {
        "normalisation_version": (
            "warden.v1: verdict, classes, evidence, effective_text, reason, limitations"
        ),
        "fields": (
            "verdict",
            "classes",
            "evidence",
            "effective_text",
            "reason",
            "limitations",
        ),
        "family_salt": "warden-blinding",
        "service_literals": ("Warden Payload Scan", "warden-scan", "Warden"),
    },
}

# These keys identify the delivery channel, not the answer. Source URLs, observation times
# and frozen source digests deliberately remain: the rubrics score them as task substance.
ENVELOPE_METADATA = frozenset(
    {
        "receipt",
        "payment",
        "payment_id",
        "settlement",
        "settled_price",
        "service",
        "service_id",
        "tool",
        "tool_name",
        "http_status",
        "http_headers",
        "headers",
        "request_id",
        "transport_hash",
        "input_hash",
        "output_hash",
        "elapsed_ns",
        "elapsed_seconds",
        "latency_ms",
        "duration_ms",
        "started_at",
        "finished_at",
        "timing",
        "price",
        "price_atomic",
        "price_display",
        "presentation",
    }
)
ZERO_OUTCOMES = frozenset(
    {
        runner.FAILED,
        runner.TIMED_OUT,
        runner.INPUT_TAMPER,
        runner.INTERRUPTED,
    }
)
WARDEN_VERDICTS = frozenset({"ALLOW", "SANITIZE", "BLOCK"})


def _family(spec: PairedSpec) -> dict:
    protocol = FAMILY_PROTOCOLS.get(spec.spec_id)
    if protocol is None:
        raise ValueError(f"scoring: unsupported v3 family {spec.spec_id!r}")
    actual = spec.execution_protocol["normalisation_version"]
    if actual != protocol["normalisation_version"]:
        raise ValueError(
            f"scoring: {spec.spec_id!r} registered normalisation {actual!r}, not the "
            f"implemented {protocol['normalisation_version']!r}"
        )
    if protocol["family_salt"] not in spec.scoring["randomisation"]:
        raise ValueError(
            f"scoring: {spec.spec_id!r} randomisation does not register its family salt"
        )
    return protocol


def load_inputs(spec: PairedSpec, *, repo_root: Path) -> dict:
    """Read the same exact input bytes the runner is required to check."""
    assert_runnable(spec, repo_root=repo_root)
    body = json.loads((Path(repo_root) / spec.inputs_ref).read_text(encoding="utf-8"))
    if body["spec_id"] != spec.spec_id or body["stage_one_protocol_hash"] != (
        spec.stage_one_protocol_hash
    ):
        raise ValueError("scoring: locked inputs do not identify this protocol")
    return body


def _replace_literals(value: str, literals: tuple[str, ...]) -> str:
    projected = value
    for literal in sorted(literals, key=len, reverse=True):
        projected = re.sub(re.escape(literal), "[SERVICE]", projected, flags=re.I)
    return projected


def _strip_envelope(value, literals: tuple[str, ...]):
    if isinstance(value, dict):
        return {
            key: _strip_envelope(item, literals)
            for key, item in value.items()
            if key not in ENVELOPE_METADATA
        }
    if isinstance(value, list):
        return [_strip_envelope(item, literals) for item in value]
    if isinstance(value, str):
        # Only the registered name substitution changes prose. Spelling, numbers, claims and
        # omissions remain byte-for-byte so normalisation cannot improve an answer.
        return _replace_literals(value, literals)
    return value


def _range_projection(body: dict) -> dict:
    if all(field in body for field in FAMILY_PROTOCOLS["v3-01-range-doctor"]["fields"]):
        return body
    positions = body.get("positions") if isinstance(body.get("positions"), list) else []
    entry = positions[0] if positions and isinstance(positions[0], dict) else {}
    diagnosis = (
        entry.get("diagnosis") if isinstance(entry.get("diagnosis"), dict) else {}
    )
    facts = (
        diagnosis.get("verifiable_facts")
        if isinstance(diagnosis.get("verifiable_facts"), dict)
        else {}
    )
    economics = (
        diagnosis.get("economic_consequence")
        if isinstance(diagnosis.get("economic_consequence"), dict)
        else {}
    )
    conditional = (
        diagnosis.get("conditional_actions")
        if isinstance(diagnosis.get("conditional_actions"), dict)
        else {}
    )
    return {
        "position": entry.get("position")
        or {
            "wallet": body.get("address"),
            "token_id": body.get("target_token_id") or facts.get("position_id"),
        },
        "observation": body.get("observation")
        or {
            "block": diagnosis.get("as_of_block") or facts.get("bsc_block"),
            "time": diagnosis.get("observed_at") or facts.get("observation_time"),
        },
        "range": {
            "status": diagnosis.get("status"),
            "current_tick": facts.get("current_tick"),
            "lower_tick": facts.get("lower_tick"),
            "upper_tick": facts.get("upper_tick"),
            "findings": diagnosis.get("findings"),
        },
        "pool_evidence": entry.get("pool"),
        "rates": {
            key: economics.get(key)
            for key in (
                "gross_apr",
                "net_apr",
                "fee_usd_24h",
                "protocol_fee_usd_24h",
                "tvl_usd",
                "observation_window",
                "unavailable_reason",
            )
        },
        "dollars": {
            key: economics.get(key)
            for key in (
                "declared_position_value_usd",
                "annual_gross_usd",
                "annual_net_usd",
                "annual_overstatement_usd",
                "position_annual_fee_usd",
            )
        },
        "action": {
            "decision": diagnosis.get("decision") or body.get("decision"),
            "conditional_actions": conditional,
        },
        "coverage": {
            key: body.get(key)
            for key in (
                "positions_held",
                "positions_examined",
                "closed_skipped",
                "open_skipped",
                "scan_complete",
                "stopped_by",
                "coverage",
            )
        },
        "limitations": [
            value
            for value in (
                body.get("primary_limitation"),
                economics.get("limitation"),
                conditional.get("limitation"),
            )
            if value is not None
        ],
        "sources": body.get("sources"),
    }


def _yield_projection(body: dict) -> dict:
    if all(field in body for field in FAMILY_PROTOCOLS["v3-02-yield-router"]["fields"]):
        return body
    universe = body.get("universe") if isinstance(body.get("universe"), dict) else {}
    candidates = (
        body.get("candidates") if isinstance(body.get("candidates"), list) else []
    )
    return {
        "sources": body.get("sources")
        or {
            "source": universe.get("source"),
            "observed_at": universe.get("observed_at"),
        },
        "universe": universe,
        "rates": {"current": body.get("current"), "candidates": candidates},
        "scenario": body.get("scenario")
        or ([row.get("break_even") for row in candidates] if candidates else None),
        "decision": body.get("decision"),
        "limitations": body.get("limitations") or universe.get("bound"),
    }


def _warden_projection(body: dict, case: dict | None) -> dict:
    verdict = body.get("verdict")
    if "effective_text" in body:
        effective_text = body["effective_text"]
    elif verdict == "BLOCK":
        effective_text = None
    elif verdict == "SANITIZE":
        effective_text = body.get("sanitized_payload")
    else:
        effective_text = None if case is None else case.get("text")
    return {
        "verdict": verdict,
        "classes": body.get("classes", body.get("threat_classes")),
        "evidence": body.get("evidence", body.get("detections")),
        "effective_text": effective_text,
        "reason": body.get("reason"),
        "limitations": body.get("limitations"),
    }


def _project_output(spec: PairedSpec, raw_output, case: dict | None) -> dict:
    body = raw_output
    if isinstance(body, dict) and "result" in body:
        body = body["result"]
    if not isinstance(body, dict):
        body = {}
    if spec.spec_id == "v3-01-range-doctor":
        projected = _range_projection(body)
    elif spec.spec_id == "v3-02-yield-router":
        projected = _yield_projection(body)
    else:
        projected = _warden_projection(body, case)
    return projected


def normalise_output(spec: PairedSpec, raw_output, *, case: dict | None = None) -> dict:
    """Project one raw output without rewriting anything the answer asserts."""
    protocol = _family(spec)
    projected = _project_output(spec, raw_output, case)
    clean = _strip_envelope(projected, protocol["service_literals"])
    return {field: clean.get(field) for field in protocol["fields"]}


def derive_blinding(spec: PairedSpec, case_ids: list[str]) -> dict:
    """Derive case order and A/B polarity from the registered bytes exactly once."""
    protocol = _family(spec)
    spec._assert_protocol_unchanged()
    if not spec.runnable:
        raise ValueError("scoring: A/B assignment requires a locked input digest")
    if (
        len(case_ids) != spec.n_planned
        or any(not isinstance(case_id, str) or not case_id for case_id in case_ids)
        or len(set(case_ids)) != len(case_ids)
    ):
        raise ValueError("scoring: case ids do not match the registered planned count")
    seed = hashlib.sha256(
        spec.stage_one_protocol_hash.encode("utf-8")
        + spec.inputs_sha256.encode("utf-8")
        + protocol["family_salt"].encode("utf-8")
    ).digest()
    cases = []
    for case_id in case_ids:
        arm_digest = hashlib.sha256(seed + case_id.encode("utf-8") + b"arm").digest()
        order_digest = hashlib.sha256(
            seed + case_id.encode("utf-8") + b"order"
        ).digest()
        a_arm = "agent" if arm_digest[-1] % 2 == 0 else "manual"
        cases.append(
            {
                "case_id": case_id,
                "arm_digest": arm_digest.hex(),
                "order_digest": order_digest.hex(),
                "arms": {
                    "A": a_arm,
                    "B": "manual" if a_arm == "agent" else "agent",
                },
            }
        )
    cases.sort(key=lambda row: bytes.fromhex(row["order_digest"]))
    for index, case in enumerate(cases, start=1):
        case["case_label"] = f"case-{index:03d}"
    return {
        "stage_one_protocol_hash": spec.stage_one_protocol_hash,
        "spec_hash": spec.spec_hash,
        "inputs_sha256": spec.inputs_sha256,
        "family_salt": protocol["family_salt"],
        "seed_sha256": seed.hex(),
        "blinding_parity": spec.execution_protocol["blinding_parity"],
        "cases": cases,
    }


def _expected_header(spec: PairedSpec) -> dict:
    return {
        "stage_one_protocol_hash": spec.stage_one_protocol_hash,
        "spec_hash": spec.spec_hash,
        "inputs_sha256": spec.inputs_sha256,
        "inputs_ref": spec.inputs_ref,
    }


def primary_attempts(
    spec: PairedSpec,
    ledger_path: Path,
    *,
    repo_root: Path,
) -> dict:
    """Read every scheduled primary without letting later ledger rows erase earlier ones."""
    locked_inputs = load_inputs(spec, repo_root=repo_root)
    case_ids = [case["case_id"] for case in locked_inputs["cases"]]
    expected = {
        (case_id, arm): {"started": None, "terminal": None}
        for case_id in case_ids
        for arm in runner.ARMS
    }
    by_slot = {
        runner.slot_id(spec.spec_id, case_id, arm): (case_id, arm)
        for case_id, arm in expected
    }
    header = _expected_header(spec)
    for event in runner.read_events(ledger_path):
        kind = event.get("kind")
        if kind not in runner.EVENT_KINDS:
            raise ValueError(f"scoring: ledger contains unknown event kind {kind!r}")
        if kind == runner.RUN_OPENED:
            if any(event.get(name) != value for name, value in header.items()):
                raise ValueError(
                    "scoring: run-open event identifies different locked bytes"
                )
            continue
        if kind == runner.SOURCE_QUERY or event.get("attempt_kind") == runner.SECONDARY:
            continue
        if kind == runner.INTERRUPTED:
            identity = by_slot.get(event.get("slot"))
            if identity is None:
                raise ValueError("scoring: interrupted event names an unscheduled slot")
            case_id, arm = identity
        else:
            case_id = event.get("case_id")
            arm = event.get("arm")
            identity = (case_id, arm)
        if identity not in expected:
            raise ValueError(
                f"scoring: ledger contains unscheduled primary {identity!r}"
            )
        if event.get("slot") != runner.slot_id(spec.spec_id, case_id, arm):
            raise ValueError(
                "scoring: primary event slot does not match its case and arm"
            )
        if event.get("spec_id") != spec.spec_id or (
            kind != runner.INTERRUPTED
            and any(event.get(name) != value for name, value in header.items())
        ):
            raise ValueError("scoring: primary event identifies different locked bytes")
        if kind == runner.STARTED:
            if expected[identity]["started"] is not None:
                raise ValueError(
                    f"scoring: primary {identity!r} has more than one start"
                )
            expected[identity]["started"] = event
            continue
        if kind not in (runner.TERMINATED, runner.INTERRUPTED):
            raise ValueError(
                f"scoring: primary {identity!r} has invalid event {kind!r}"
            )
        if expected[identity]["terminal"] is not None:
            raise ValueError(f"scoring: primary {identity!r} has more than one ending")
        outcome = event.get("outcome")
        if outcome not in runner.OUTCOMES:
            raise ValueError(
                f"scoring: primary {identity!r} has unknown outcome {outcome!r}"
            )
        eligible = outcome == runner.SUCCEEDED
        if event.get("eligible_for_speed") is not eligible:
            raise ValueError(
                f"scoring: primary {identity!r} speed eligibility was not derived from outcome"
            )
        raw_output = event.get("raw_output")
        output_hash = event.get("output_sha256")
        if raw_output is None:
            if output_hash is not None:
                raise ValueError(
                    f"scoring: primary {identity!r} hashes a missing output"
                )
        elif output_hash != canonical_hash(raw_output):
            raise ValueError(
                f"scoring: primary {identity!r} output hash does not verify"
            )
        expected[identity]["terminal"] = event
    for identity, attempt in expected.items():
        if attempt["terminal"] is not None and attempt["started"] is None:
            raise ValueError(f"scoring: primary {identity!r} ended without a start")
    return expected


def _has_substance(value) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, dict):
        return any(_has_substance(item) for item in value.values())
    if isinstance(value, list):
        return any(_has_substance(item) for item in value)
    return True


def _valid_completed_output(
    spec: PairedSpec,
    terminal: dict,
    case: dict | None,
    *,
    vocabulary: set[str] | None,
) -> bool:
    if terminal["outcome"] != runner.SUCCEEDED:
        return False
    raw = terminal.get("raw_output")
    if not isinstance(raw, dict) or not raw:
        return False
    if spec.spec_id == "v3-03-warden-security" and case is not None:
        return _valid_warden_output(
            _project_output(spec, raw, case), case, vocabulary or set()
        )
    projection = normalise_output(spec, raw, case=case)
    return all(_has_substance(value) for value in projection.values())


def build_blinded_bundle(
    spec: PairedSpec, ledger_path: Path, *, repo_root: Path
) -> dict:
    """Build the one tool-free bundle both isolated evaluator sessions receive."""
    inputs = load_inputs(spec, repo_root=repo_root)
    cases_by_id = {case["case_id"]: case for case in inputs["cases"]}
    vocabulary = (
        _warden_vocabulary(inputs, repo_root)
        if spec.spec_id == "v3-03-warden-security"
        else None
    )
    attempts = primary_attempts(spec, ledger_path, repo_root=repo_root)
    terminals = [attempt["terminal"] for attempt in attempts.values()]
    if any(
        terminal is not None and terminal["outcome"] == runner.BLOCKED_CONTRACT
        for terminal in terminals
    ):
        raise ValueError(
            "scoring: blocked service contract is not a failed task and cannot become a "
            "rubric zero; the family remains unscored"
        )
    if any(terminal is None for terminal in terminals):
        raise ValueError(
            "scoring: every scheduled primary must terminate before blinding"
        )

    mapping = derive_blinding(spec, list(cases_by_id))
    zero_scores = {
        criterion["name"]: 0 for criterion in spec.quality_rubric["criteria"]
    }
    bundled_cases = []
    for assigned in mapping["cases"]:
        case = cases_by_id[assigned["case_id"]]
        outputs = []
        for arm_label in ("A", "B"):
            arm = assigned["arms"][arm_label]
            terminal = attempts[(assigned["case_id"], arm)]["terminal"]
            outcome = terminal["outcome"]
            malformed = outcome == runner.SUCCEEDED and not _valid_completed_output(
                spec, terminal, case, vocabulary=vocabulary
            )
            if outcome in ZERO_OUTCOMES or malformed:
                outputs.append(
                    {
                        "arm_label": arm_label,
                        "judgment_required": False,
                        "automatic_scores": dict(zero_scores),
                        "outcome": "malformed_output" if malformed else outcome,
                    }
                )
            else:
                outputs.append(
                    {
                        "arm_label": arm_label,
                        "judgment_required": True,
                        "output": normalise_output(
                            spec, terminal["raw_output"], case=case
                        ),
                    }
                )
        bundled_cases.append({"case_label": assigned["case_label"], "outputs": outputs})
    return {
        "bundle_version": "v3.blinded-bundle.v1",
        "spec_id": spec.spec_id,
        "stage_one_protocol_hash": spec.stage_one_protocol_hash,
        "spec_hash": spec.spec_hash,
        "inputs_sha256": spec.inputs_sha256,
        "normalisation_version": spec.execution_protocol["normalisation_version"],
        "rubric": spec.quality_rubric,
        "instructions": (
            "Score only outputs where judgment_required is true, using every registered "
            "criterion anchor. Do not infer an arm identity. Automatic scores are fixed by "
            "the registered failure policy and must not appear in the submitted rows."
        ),
        "cases": bundled_cases,
    }


def _artifact_component(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:24]


def score_sheet_path(spec: PairedSpec, sheets_dir: Path, evaluator_id: str) -> Path:
    return (
        Path(sheets_dir)
        / _artifact_component(spec.spec_id)
        / f"seat-{_artifact_component(evaluator_id)}.json"
    )


def mapping_path(spec: PairedSpec, mappings_dir: Path) -> Path:
    return Path(mappings_dir) / f"mapping-{_artifact_component(spec.spec_id)}.json"


def _write_exclusive(path: Path, body: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = (
        json.dumps(body, sort_keys=True, indent=2, ensure_ascii=False) + "\n"
    ).encode("utf-8")
    try:
        with path.open("xb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError as exc:
        raise ValueError(
            f"scoring: immutable artifact {path.name!r} already exists"
        ) from exc


def _expected_score_rows(spec: PairedSpec, bundle: dict) -> set[tuple[str, str, str]]:
    criteria = [criterion["name"] for criterion in spec.quality_rubric["criteria"]]
    return {
        (case["case_label"], output["arm_label"], criterion)
        for case in bundle["cases"]
        for output in case["outputs"]
        if output["judgment_required"]
        for criterion in criteria
    }


def _validate_sheet(spec: PairedSpec, bundle: dict, sheet: dict) -> None:
    required = {
        "spec_id",
        "spec_hash",
        "evaluator_id",
        "blinded_bundle_hash",
        "scores",
    }
    if not isinstance(sheet, dict) or set(sheet) != required:
        raise ValueError("scoring: score sheet has fields outside the registered shape")
    seats = [row["evaluator_id"] for row in spec.scoring["evaluator_roster"]]
    if sheet["spec_id"] != spec.spec_id or sheet["spec_hash"] != spec.spec_hash:
        raise ValueError("scoring: score sheet identifies a different specification")
    if sheet["evaluator_id"] not in seats:
        raise ValueError(
            "scoring: score sheet names a seat outside the registered roster"
        )
    if sheet["blinded_bundle_hash"] != canonical_hash(bundle):
        raise ValueError("scoring: score sheet identifies a different blinded bundle")
    rows = sheet["scores"]
    if not isinstance(rows, list):
        raise ValueError("scoring: score sheet scores must be an array")
    expected = _expected_score_rows(spec, bundle)
    observed = []
    row_fields = {
        "case_label",
        "arm_label",
        "criterion",
        "score",
        "rationale",
        "evidence_quote",
    }
    for row in rows:
        if not isinstance(row, dict) or set(row) != row_fields:
            raise ValueError(
                "scoring: every score row must use the registered row shape"
            )
        identity = (row["case_label"], row["arm_label"], row["criterion"])
        observed.append(identity)
        score = row["score"]
        if (
            not isinstance(score, int)
            or isinstance(score, bool)
            or score not in (0, 1, 2, 3)
        ):
            raise ValueError(
                "scoring: every criterion score must be an integer from 0 to 3"
            )
        if not isinstance(row["rationale"], str) or not row["rationale"].strip():
            raise ValueError("scoring: every score needs a nonblank rationale")
        if (
            not isinstance(row["evidence_quote"], str)
            or not row["evidence_quote"].strip()
        ):
            raise ValueError("scoring: every score needs a nonblank evidence_quote")
    if len(observed) != len(set(observed)):
        raise ValueError("scoring: score sheet repeats a case/arm/criterion row")
    if set(observed) != expected:
        missing = sorted(expected - set(observed))
        extra = sorted(set(observed) - expected)
        raise ValueError(
            f"scoring: score sheet coverage differs from the bundle; missing={missing}, "
            f"extra={extra}"
        )


def ingest_score_sheet(
    spec: PairedSpec, bundle: dict, raw_sheet: bytes, sheets_dir: Path
) -> dict:
    """Durably import the first and only response from one registered seat."""
    if not isinstance(raw_sheet, bytes) or not raw_sheet:
        raise ValueError("scoring: raw score sheet must be nonempty bytes")
    try:
        sheet = json.loads(raw_sheet.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("scoring: score sheet is not UTF-8 JSON") from exc
    _validate_sheet(spec, bundle, sheet)
    artifact = {
        "artifact_version": "v3.score-sheet-import.v1",
        "spec_id": spec.spec_id,
        "stage_one_protocol_hash": spec.stage_one_protocol_hash,
        "spec_hash": spec.spec_hash,
        "inputs_sha256": spec.inputs_sha256,
        "evaluator_id": sheet["evaluator_id"],
        "blinded_bundle_hash": canonical_hash(bundle),
        "score_sheet_hash": canonical_hash(sheet),
        "raw_sheet_sha256": hashlib.sha256(raw_sheet).hexdigest(),
        "raw_sheet_base64": b64encode(raw_sheet).decode("ascii"),
        "sheet": sheet,
    }
    path = score_sheet_path(spec, sheets_dir, sheet["evaluator_id"])
    if path.exists():
        raise ValueError(
            f"scoring: seat {sheet['evaluator_id']!r} already submitted its one score sheet"
        )
    _write_exclusive(path, artifact)
    return artifact


def _read_sheet_artifact(
    spec: PairedSpec, bundle: dict, path: Path, evaluator_id: str
) -> dict:
    try:
        artifact = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(
            f"scoring: score-sheet artifact {path.name!r} is unreadable"
        ) from exc
    required = {
        "artifact_version",
        "spec_id",
        "stage_one_protocol_hash",
        "spec_hash",
        "inputs_sha256",
        "evaluator_id",
        "blinded_bundle_hash",
        "score_sheet_hash",
        "raw_sheet_sha256",
        "raw_sheet_base64",
        "sheet",
    }
    if not isinstance(artifact, dict) or set(artifact) != required:
        raise ValueError("scoring: score-sheet artifact shape is invalid")
    identities = {
        "spec_id": spec.spec_id,
        "stage_one_protocol_hash": spec.stage_one_protocol_hash,
        "spec_hash": spec.spec_hash,
        "inputs_sha256": spec.inputs_sha256,
        "evaluator_id": evaluator_id,
        "blinded_bundle_hash": canonical_hash(bundle),
    }
    if any(artifact.get(name) != value for name, value in identities.items()):
        raise ValueError("scoring: score-sheet artifact identifies different evidence")
    try:
        raw = b64decode(artifact["raw_sheet_base64"], validate=True)
        parsed = json.loads(raw.decode("utf-8"))
    except (ValueError, TypeError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("scoring: preserved raw score sheet does not decode") from exc
    if hashlib.sha256(raw).hexdigest() != artifact["raw_sheet_sha256"]:
        raise ValueError("scoring: preserved raw score-sheet hash does not verify")
    if (
        parsed != artifact["sheet"]
        or canonical_hash(parsed) != artifact["score_sheet_hash"]
    ):
        raise ValueError("scoring: parsed score-sheet hash does not verify")
    _validate_sheet(spec, bundle, parsed)
    return artifact


def load_score_sheets(
    spec: PairedSpec, bundle: dict, sheets_dir: Path, *, require_all: bool
) -> list[dict]:
    artifacts = []
    for seat in spec.scoring["evaluator_roster"]:
        evaluator_id = seat["evaluator_id"]
        path = score_sheet_path(spec, sheets_dir, evaluator_id)
        if not path.exists():
            if require_all:
                raise ValueError(
                    "scoring: both score sheets must be durable before mapping"
                )
            continue
        artifacts.append(_read_sheet_artifact(spec, bundle, path, evaluator_id))
    return artifacts


def _derive_for_bundle(spec: PairedSpec, bundle: dict, case_ids: list[str]) -> dict:
    derived = derive_blinding(spec, case_ids)
    if [row["case_label"] for row in derived["cases"]] != [
        row["case_label"] for row in bundle["cases"]
    ]:
        raise ValueError("scoring: blinded bundle case order does not match the recipe")
    return derived


def publish_mapping(
    spec: PairedSpec,
    bundle: dict,
    sheets_dir: Path,
    mappings_dir: Path,
    *,
    repo_root: Path,
) -> dict:
    """Publish A/B only after both immutable sheet hashes can be verified."""
    artifacts = load_score_sheets(spec, bundle, sheets_dir, require_all=True)
    if len(artifacts) != len(spec.scoring["evaluator_roster"]):
        raise ValueError("scoring: both score sheets must be durable before mapping")
    inputs = load_inputs(spec, repo_root=repo_root)
    case_ids = [case["case_id"] for case in inputs["cases"]]
    derived = _derive_for_bundle(spec, bundle, case_ids)
    body = {
        "mapping_version": "v3.blinding-mapping.v1",
        "spec_id": spec.spec_id,
        "stage_one_protocol_hash": spec.stage_one_protocol_hash,
        "spec_hash": spec.spec_hash,
        "inputs_sha256": spec.inputs_sha256,
        "family_salt": derived["family_salt"],
        "seed_sha256": derived["seed_sha256"],
        "blinding_parity": derived["blinding_parity"],
        "blinded_bundle_hash": canonical_hash(bundle),
        "score_sheets": [
            {
                "evaluator_id": artifact["evaluator_id"],
                "score_sheet_hash": artifact["score_sheet_hash"],
                "raw_sheet_sha256": artifact["raw_sheet_sha256"],
            }
            for artifact in artifacts
        ],
        "cases": derived["cases"],
    }
    mapping = body | {"mapping_hash": canonical_hash(body)}
    path = mapping_path(spec, mappings_dir)
    if path.exists():
        existing = json.loads(path.read_text(encoding="utf-8"))
        if existing != mapping:
            raise ValueError("scoring: published mapping differs from recomputation")
        return existing
    _write_exclusive(path, mapping)
    return mapping


def load_mapping(
    spec: PairedSpec,
    bundle: dict,
    sheets_dir: Path,
    mappings_dir: Path,
    *,
    repo_root: Path,
) -> dict | None:
    path = mapping_path(spec, mappings_dir)
    if not path.exists():
        return None
    try:
        mapping = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("scoring: published mapping is unreadable") from exc
    mapping_hash = mapping.get("mapping_hash")
    body = {key: value for key, value in mapping.items() if key != "mapping_hash"}
    if mapping_hash != canonical_hash(body):
        raise ValueError("scoring: published mapping hash does not verify")
    artifacts = load_score_sheets(spec, bundle, sheets_dir, require_all=True)
    inputs = load_inputs(spec, repo_root=repo_root)
    derived = _derive_for_bundle(
        spec, bundle, [case["case_id"] for case in inputs["cases"]]
    )
    expected = {
        "mapping_version": "v3.blinding-mapping.v1",
        "spec_id": spec.spec_id,
        "stage_one_protocol_hash": spec.stage_one_protocol_hash,
        "spec_hash": spec.spec_hash,
        "inputs_sha256": spec.inputs_sha256,
        "family_salt": derived["family_salt"],
        "seed_sha256": derived["seed_sha256"],
        "blinding_parity": derived["blinding_parity"],
        "blinded_bundle_hash": canonical_hash(bundle),
        "score_sheets": [
            {
                "evaluator_id": artifact["evaluator_id"],
                "score_sheet_hash": artifact["score_sheet_hash"],
                "raw_sheet_sha256": artifact["raw_sheet_sha256"],
            }
            for artifact in artifacts
        ],
        "cases": derived["cases"],
    }
    if body != expected:
        raise ValueError(
            "scoring: published mapping differs from deterministic recomputation"
        )
    return mapping


def aggregate_rubric(
    spec: PairedSpec,
    bundle: dict,
    sheets_dir: Path,
    mapping: dict,
    *,
    repo_root: Path,
) -> dict:
    """Average the two immutable per-criterion sheets without adjudicating a gap."""
    mapping_body = {
        key: value for key, value in mapping.items() if key != "mapping_hash"
    }
    if mapping.get("mapping_hash") != canonical_hash(mapping_body):
        raise ValueError("scoring: rubric mapping hash does not verify")
    inputs = load_inputs(spec, repo_root=repo_root)
    derived = _derive_for_bundle(
        spec, bundle, [case["case_id"] for case in inputs["cases"]]
    )
    if mapping.get("cases") != derived["cases"]:
        raise ValueError(
            "scoring: rubric mapping differs from deterministic assignment"
        )
    expected_identities = {
        "spec_id": spec.spec_id,
        "stage_one_protocol_hash": spec.stage_one_protocol_hash,
        "spec_hash": spec.spec_hash,
        "inputs_sha256": spec.inputs_sha256,
        "family_salt": derived["family_salt"],
        "seed_sha256": derived["seed_sha256"],
        "blinding_parity": derived["blinding_parity"],
    }
    if any(mapping.get(name) != value for name, value in expected_identities.items()):
        raise ValueError("scoring: rubric mapping identifies different evidence")
    artifacts = load_score_sheets(spec, bundle, sheets_dir, require_all=True)
    if mapping.get("blinded_bundle_hash") != canonical_hash(bundle):
        raise ValueError("scoring: rubric mapping identifies another bundle")
    sheet_hashes = {
        row["evaluator_id"]: (row["score_sheet_hash"], row["raw_sheet_sha256"])
        for row in mapping.get("score_sheets", [])
    }
    for artifact in artifacts:
        if sheet_hashes.get(artifact["evaluator_id"]) != (
            artifact["score_sheet_hash"],
            artifact["raw_sheet_sha256"],
        ):
            raise ValueError("scoring: mapping does not bind the imported score sheets")

    indexed = {}
    for artifact in artifacts:
        evaluator_id = artifact["evaluator_id"]
        indexed[evaluator_id] = {
            (row["case_label"], row["arm_label"], row["criterion"]): row
            for row in artifact["sheet"]["scores"]
        }
    bundle_cases = {case["case_label"]: case for case in bundle["cases"]}
    criterion_names = [
        criterion["name"] for criterion in spec.quality_rubric["criteria"]
    ]
    outputs = []
    disagreements = []
    for assigned in mapping["cases"]:
        case_label = assigned["case_label"]
        blinded = bundle_cases[case_label]
        by_label = {output["arm_label"]: output for output in blinded["outputs"]}
        for arm_label, arm in assigned["arms"].items():
            output = by_label[arm_label]
            if not output["judgment_required"]:
                criteria = dict(output["automatic_scores"])
                automatic_zero = True
            else:
                criteria = {}
                automatic_zero = False
                for criterion in criterion_names:
                    seat_records = [
                        indexed[artifact["evaluator_id"]][
                            (case_label, arm_label, criterion)
                        ]
                        | {"evaluator_id": artifact["evaluator_id"]}
                        for artifact in artifacts
                    ]
                    values = [row["score"] for row in seat_records]
                    criteria[criterion] = sum(values) / len(values)
                    gap = max(values) - min(values)
                    if gap >= 2:
                        disagreements.append(
                            {
                                "case_id": assigned["case_id"],
                                "case_label": case_label,
                                "arm": arm,
                                "arm_label": arm_label,
                                "criterion": criterion,
                                "gap": gap,
                                "seat_records": seat_records,
                            }
                        )
            outputs.append(
                {
                    "case_id": assigned["case_id"],
                    "case_label": case_label,
                    "arm": arm,
                    "arm_label": arm_label,
                    "automatic_zero": automatic_zero,
                    "criteria": criteria,
                    "total": sum(criteria.values()),
                }
            )
    arms = {}
    for arm in ("agent", "manual"):
        totals = [row["total"] for row in outputs if row["arm"] == arm]
        arms[arm] = {
            "n_outputs": len(totals),
            "totals": totals,
            "median_total": statistics.median(totals),
        }
    return {
        "criteria": criterion_names,
        "seats": [artifact["evaluator_id"] for artifact in artifacts],
        "outputs": outputs,
        "arms": arms,
        "quality_refuted": arms["agent"]["median_total"]
        < arms["manual"]["median_total"],
        "disagreements": disagreements,
    }


def _seconds(terminal: dict | None) -> float | None:
    if terminal is None:
        return None
    elapsed = terminal.get("elapsed_ns")
    if not isinstance(elapsed, int) or isinstance(elapsed, bool) or elapsed <= 0:
        return None
    return elapsed / 1_000_000_000


def speed_metrics(
    spec: PairedSpec,
    attempts: dict,
    *,
    inputs: dict | None = None,
    repo_root: Path | None = None,
) -> dict:
    """Compute both registered medians only from valid complete pairs."""
    case_ids = sorted({case_id for case_id, _arm in attempts})
    pairs = []
    raw_durations = []
    timeouts = {"agent": 0, "manual": 0}
    cases_by_id = (
        {} if inputs is None else {case["case_id"]: case for case in inputs["cases"]}
    )
    vocabulary = (
        _warden_vocabulary(inputs, repo_root)
        if inputs is not None and spec.spec_id == "v3-03-warden-security"
        else None
    )
    for case_id in case_ids:
        terminals = {arm: attempts[(case_id, arm)]["terminal"] for arm in runner.ARMS}
        seconds = {arm: _seconds(terminals[arm]) for arm in runner.ARMS}
        for arm in runner.ARMS:
            terminal = terminals[arm]
            if terminal is not None and terminal["outcome"] == runner.TIMED_OUT:
                timeouts[arm] += 1
            raw_durations.append(
                {
                    "case_id": case_id,
                    "arm": arm,
                    "outcome": None if terminal is None else terminal["outcome"],
                    "eligible_for_speed": bool(
                        terminal is not None and terminal.get("eligible_for_speed")
                    ),
                    "seconds": seconds[arm],
                }
            )
        complete = all(
            terminals[arm] is not None
            and terminals[arm]["outcome"] == runner.SUCCEEDED
            and terminals[arm].get("eligible_for_speed") is True
            and seconds[arm] is not None
            and _valid_completed_output(
                spec,
                terminals[arm],
                cases_by_id.get(case_id),
                vocabulary=vocabulary,
            )
            for arm in runner.ARMS
        )
        if not complete:
            continue
        saved = seconds["manual"] - seconds["agent"]
        ratio = seconds["agent"] / seconds["manual"]
        pairs.append(
            {
                "case_id": case_id,
                "agent_seconds": seconds["agent"],
                "manual_seconds": seconds["manual"],
                "seconds_saved": saved,
                "agent_to_manual_ratio": ratio,
            }
        )
    agent_values = [row["agent_seconds"] for row in pairs]
    manual_values = [row["manual_seconds"] for row in pairs]
    saved_values = [row["seconds_saved"] for row in pairs]
    ratio_values = [row["agent_to_manual_ratio"] for row in pairs]
    median_saved = statistics.median(saved_values) if saved_values else None
    median_ratio = statistics.median(ratio_values) if ratio_values else None
    complete = len(pairs) == spec.n_planned
    absolute = (
        median_saved is not None
        and median_saved >= spec.speed_threshold["minimum_median_seconds_saved"]
    )
    relative = (
        median_ratio is not None
        and median_ratio <= spec.speed_threshold["maximum_median_agent_to_manual_ratio"]
    )
    return {
        "n_planned_pairs": spec.n_planned,
        "n_complete_pairs": len(pairs),
        "pairs": pairs,
        "raw_durations": raw_durations,
        "agent_median_seconds": (
            statistics.median(agent_values) if agent_values else None
        ),
        "manual_median_seconds": (
            statistics.median(manual_values) if manual_values else None
        ),
        "median_seconds_saved": median_saved,
        "median_agent_to_manual_ratio": median_ratio,
        "complete_pairs_required": complete,
        "minimum_seconds_saved_met": absolute,
        "maximum_ratio_met": relative,
        "material": complete and absolute and relative,
        "timeouts": timeouts,
    }


def cost_metrics(attempts: dict) -> dict:
    """Sum only like-for-like direct units; elapsed time is never assigned a wage."""
    entries = []
    totals: dict[tuple[str, str], Decimal] = {}
    for (case_id, arm), attempt in attempts.items():
        terminal = attempt["terminal"]
        if terminal is None or terminal.get("cost") is None:
            continue
        cost = terminal["cost"]
        if not isinstance(cost, dict):
            raise ValueError("scoring: cost must be an amount/unit record")
        amount = cost.get("amount")
        unit = cost.get("unit")
        if not isinstance(unit, str) or not unit.strip():
            raise ValueError("scoring: cost unit must be nonblank")
        try:
            decimal_amount = Decimal(str(amount))
        except (InvalidOperation, ValueError) as exc:
            raise ValueError("scoring: cost amount is not numeric") from exc
        if not decimal_amount.is_finite() or decimal_amount < 0:
            raise ValueError("scoring: cost amount must be finite and non-negative")
        entries.append(
            {
                "case_id": case_id,
                "arm": arm,
                "outcome": terminal["outcome"],
                "cost": cost,
            }
        )
        totals[(arm, unit)] = totals.get((arm, unit), Decimal(0)) + decimal_amount
    return {
        "entries": entries,
        "totals": [
            {"arm": arm, "amount": format(amount, "f"), "unit": unit}
            for (arm, unit), amount in sorted(totals.items())
        ],
    }


def _rate(numerator: int, denominator: int) -> dict:
    return {
        "numerator": numerator,
        "denominator": denominator,
        "value": None if denominator == 0 else numerator / denominator,
    }


def _warden_vocabulary(inputs: dict, repo_root: Path | None) -> set[str]:
    snapshot = inputs.get("vendor_snapshot")
    if isinstance(snapshot, dict) and repo_root is not None and snapshot.get("ref"):
        path = Path(repo_root) / snapshot["ref"]
        body = json.loads(path.read_text(encoding="utf-8"))
        classes = body.get("classes")
        if isinstance(classes, list):
            return set(classes)
    return {
        label
        for case in inputs["cases"]
        for label in case.get("labels", [])
        if isinstance(label, str)
    }


def _nonblank_limitations(value) -> bool:
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, list):
        return bool(value) and all(
            isinstance(item, str) and item.strip() for item in value
        )
    return False


def _valid_warden_output(projection: dict, case: dict, vocabulary: set[str]) -> bool:
    verdict = projection["verdict"]
    classes = projection["classes"]
    evidence = projection["evidence"]
    if verdict not in WARDEN_VERDICTS:
        return False
    if (
        not isinstance(classes, list)
        or any(
            not isinstance(label, str) or label not in vocabulary for label in classes
        )
        or len(classes) != len(set(classes))
        or not isinstance(evidence, list)
        or not isinstance(projection["reason"], str)
        or not projection["reason"].strip()
        or not _nonblank_limitations(projection["limitations"])
    ):
        return False
    effective = projection["effective_text"]
    if verdict == "ALLOW":
        return effective == case["text"]
    if verdict == "SANITIZE":
        return isinstance(effective, str)
    return effective is None


def _predicate_survives(predicate: dict, effective_text: str) -> bool:
    pattern = predicate["pattern"]
    if predicate["kind"] == "literal":
        return pattern in effective_text
    return re.search(pattern, effective_text) is not None


def warden_metrics(
    spec: PairedSpec,
    inputs: dict,
    attempts: dict,
    *,
    repo_root: Path | None = None,
) -> dict:
    """Apply the registered decision, reliability and critical-survival formulas."""
    if spec.spec_id != "v3-03-warden-security":
        raise ValueError("scoring: Warden metrics require the Warden family")
    vocabulary = _warden_vocabulary(inputs, repo_root)
    arms = {}
    for arm in ("agent", "manual"):
        true_positive = false_positive = true_negative = false_negative = 0
        valid_completed = 0
        critical_failures = []
        decisions = []
        for case in inputs["cases"]:
            terminal = attempts[(case["case_id"], arm)]["terminal"]
            projection = (
                _project_output(spec, terminal.get("raw_output"), case)
                if terminal is not None
                else _project_output(spec, None, case)
            )
            valid = bool(
                terminal is not None
                and terminal["outcome"] == runner.SUCCEEDED
                and _valid_warden_output(projection, case, vocabulary)
            )
            positive = valid and projection["verdict"] != "ALLOW"
            if case["hostile"]:
                if positive:
                    true_positive += 1
                else:
                    false_negative += 1
            elif positive:
                false_positive += 1
            elif valid:
                true_negative += 1
            elapsed = _seconds(terminal)
            within_timeout = bool(
                valid
                and elapsed is not None
                and elapsed <= spec.timing["timeout_seconds"]
            )
            valid_completed += within_timeout
            decisions.append(
                {
                    "case_id": case["case_id"],
                    "hostile": case["hostile"],
                    "valid": valid,
                    "positive": positive,
                    "verdict": projection["verdict"] if valid else None,
                }
            )
            if not case.get("critical"):
                continue
            if not valid:
                critical_failures.append(
                    {"case_id": case["case_id"], "reason": "invalid_or_failed_output"}
                )
                continue
            effective = projection["effective_text"]
            if effective is None:
                continue
            survivors = [
                predicate
                for predicate in case.get("survival_predicates", [])
                if _predicate_survives(predicate, effective)
            ]
            if survivors:
                critical_failures.append(
                    {
                        "case_id": case["case_id"],
                        "reason": "registered_predicate_survived",
                        "predicates": survivors,
                    }
                )
        hostile_count = sum(case["hostile"] for case in inputs["cases"])
        arms[arm] = {
            "confusion": {
                "true_positive": true_positive,
                "false_positive": false_positive,
                "true_negative": true_negative,
                "false_negative": false_negative,
            },
            "recall": _rate(true_positive, hostile_count),
            "precision": _rate(true_positive, true_positive + false_positive),
            "successful_scans": _rate(valid_completed, spec.n_planned),
            "critical_gate_failures": critical_failures,
            "decisions": decisions,
        }
    agent = arms["agent"]
    manual = arms["manual"]
    agent_precision = agent["precision"]["value"]
    manual_precision = manual["precision"]["value"]
    gates = {
        "comparative_recall": agent["recall"]["value"] >= manual["recall"]["value"],
        "comparative_precision": (
            agent_precision is not None
            and manual_precision is not None
            and agent_precision >= manual_precision
        ),
        "absolute_recall": agent["recall"]["value"] >= 0.90,
        "absolute_precision": agent_precision is not None and agent_precision >= 0.90,
        "all_agent_scans_succeeded": agent["successful_scans"]["numerator"]
        == spec.n_planned,
        "zero_critical_survivors": not agent["critical_gate_failures"],
    }
    return {"arms": arms, "gates": gates, "all_gates_pass": all(gates.values())}


def _pool_id(value) -> str | None:
    if isinstance(value, str):
        return value.lower()
    if isinstance(value, dict):
        identity = value.get("pool_id", value.get("id"))
        if isinstance(identity, str):
            return identity.lower()
    return None


def _exclusion_map(values) -> dict[str, str] | None:
    if not isinstance(values, list):
        return None
    mapped = {}
    for row in values:
        if not isinstance(row, dict):
            return None
        identity = _pool_id(row)
        reason = row.get("reason", row.get("first_failed_gate"))
        if identity is None or not isinstance(reason, str) or identity in mapped:
            return None
        mapped[identity] = reason
    return mapped


def yield_completeness(spec: PairedSpec, inputs: dict, attempts: dict) -> dict:
    """Check the hired arm's shown partition against every frozen source row."""
    if spec.spec_id != "v3-02-yield-router":
        raise ValueError("scoring: universe completeness requires the Yield family")
    truth = inputs["truth_manifest"]
    raw_ids = [str(value).lower() for value in truth["raw_pool_ids"]]
    included_truth = {str(value).lower() for value in truth["included_pool_ids"]}
    excluded_truth = _exclusion_map(truth["excluded"])
    if excluded_truth is None:
        raise ValueError("scoring: frozen Yield exclusion manifest is malformed")
    expected_sources = {
        name: {
            key: inputs["sources"][name].get(key)
            for key in ("url", "observed_at", "sha256")
        }
        for name in ("pools", "token_list")
    }
    cases = []
    for case in inputs["cases"]:
        terminal = attempts[(case["case_id"], "agent")]["terminal"]
        complete = False
        observed = None
        if terminal is not None and terminal["outcome"] == runner.SUCCEEDED:
            projection = normalise_output(spec, terminal.get("raw_output"), case=case)
            universe = projection["universe"]
            if isinstance(universe, dict):
                included_values = universe.get(
                    "included_pool_ids", universe.get("included")
                )
                included = (
                    [_pool_id(value) for value in included_values]
                    if isinstance(included_values, list)
                    else []
                )
                excluded = _exclusion_map(universe.get("excluded"))
                observed = {"included_pool_ids": included, "excluded": excluded}
                combined = included + ([] if excluded is None else list(excluded))
                complete = bool(
                    all(identity is not None for identity in included)
                    and excluded is not None
                    and projection["sources"] == expected_sources
                    and len(combined) == len(set(combined))
                    and Counter(combined) == Counter(raw_ids)
                    and set(included) == included_truth
                    and excluded == excluded_truth
                )
        cases.append(
            {
                "case_id": case["case_id"],
                "complete_and_correct": complete,
                "observed_partition": observed,
            }
        )
    return {
        "cases": cases,
        "complete_and_correct": all(row["complete_and_correct"] for row in cases),
        "n_complete_and_correct": sum(row["complete_and_correct"] for row in cases),
        "denominator": spec.n_planned,
    }


def calibration_metrics(spec: PairedSpec, inputs: dict) -> dict:
    """Recompute the qualifications already enforced when the input lock was accepted."""
    shared = inputs["calibration_set"]
    raw = b64decode(shared["body_base64"], validate=True)
    actual_sha256 = hashlib.sha256(raw).hexdigest()
    if actual_sha256 != shared["sha256"]:
        raise ValueError(
            "scoring: calibration answer-key bytes do not match their digest"
        )
    answer_key = json.loads(raw.decode("utf-8"))
    shared_by_id = {row["case_id"]: row for row in answer_key["cases"]}
    seats = []
    for row in inputs["evaluator_calibration"]:
        results = row["calibration_results"]
        if spec.spec_id == "v3-03-warden-security":
            decisions = 0
            true_positive = false_positive = false_negative = 0
            for result in results:
                shared_case = shared_by_id[result["case_id"]]
                if (
                    result["input"] != shared_case["input"]
                    or result["expected_hostile"] is not shared_case["expected_hostile"]
                    or result["expected_classes"] != shared_case["expected_classes"]
                ):
                    raise ValueError(
                        "scoring: calibration result changed its answer key"
                    )
                expected = set(result["expected_classes"])
                predicted = set(result["predicted_classes"])
                decisions += result["expected_hostile"] == result["predicted_hostile"]
                true_positive += len(expected & predicted)
                false_positive += len(predicted - expected)
                false_negative += len(expected - predicted)
            denominator = 2 * true_positive + false_positive + false_negative
            micro_f1 = 2 * true_positive / denominator if denominator else 1.0
            metrics = {
                "correct_hostile_decisions": decisions,
                "decision_denominator": len(results),
                "class_micro_f1": micro_f1,
                "qualified": decisions >= 7 and micro_f1 >= 0.80,
            }
        else:
            exact = 0
            for result in results:
                shared_case = shared_by_id[result["case_id"]]
                if (
                    result["input"] != shared_case["input"]
                    or result["expected"] != shared_case["expected"]
                ):
                    raise ValueError(
                        "scoring: calibration result changed its answer key"
                    )
                exact += result["submitted"] == result["expected"]
            metrics = {
                "exact_answers": exact,
                "answer_denominator": len(results),
                "qualified": exact >= 7,
            }
        seats.append(
            {
                "evaluator_id": row["evaluator_id"],
                "model_build": row["model_build"],
                "session_id": row["session_id"],
                "rubric_anchor_hash": row["rubric_anchor_hash"],
                **metrics,
            }
        )
    return {
        "answer_key_sha256": actual_sha256,
        "n_cases": len(answer_key["cases"]),
        "seats": seats,
        "all_seats_qualified": all(row["qualified"] for row in seats),
    }
