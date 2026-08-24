"""Run the v3 evidence path against an isolated, synthetic throwaway family."""

import argparse
import json
from contextlib import contextmanager
from datetime import datetime, timedelta
from importlib import resources
from pathlib import Path

import httpx

from ...hire.receipts import canonical_hash
from . import (
    assemble,
    calibration,
    calibration_driver,
    capture,
    orchestrator,
    report,
    runner,
    scoring,
    spec as spec_module,
)
from .spec import PairedSpec, load, lock_inputs, save

SPEC_ID = "v3-02-yield-router-REHEARSAL-NOT-REGISTERED"
AGENT_SERVICE_ID = "rehearsal-yield-router"
FAMILY_SALT = "rehearsal-blinding"
NORMALISATION_VERSION = (
    "rehearsal.v1: verdict, risk_level, threat_classes, detections, "
    "sanitized_payload, recommendation, checks"
)
PROJECTION_FIELDS = (
    "verdict",
    "risk_level",
    "threat_classes",
    "detections",
    "sanitized_payload",
    "recommendation",
    "checks",
)
TOKENS = tuple(f"0x{index:040x}" for index in range(1, 9))
WARDEN_SPEC_ID = "v3-04-warden-security-REHEARSAL-NOT-REGISTERED"
WARDEN_AGENT_SERVICE_ID = "rehearsal-warden-scan"
WARDEN_FAMILY_SALT = "warden-v4-rehearsal-blinding"


class RehearsalRefused(RuntimeError):
    """The isolated rehearsal cannot proceed without replacing prior evidence."""


@contextmanager
def _registered_rehearsal_family():
    if SPEC_ID in spec_module.INPUT_VALIDATORS or SPEC_ID in scoring.FAMILY_PROTOCOLS:
        raise RehearsalRefused(
            f"the throwaway family {SPEC_ID!r} is already registered"
        )
    protocol = {
        "normalisation_version": NORMALISATION_VERSION,
        "fields": PROJECTION_FIELDS,
        "family_salt": FAMILY_SALT,
        "service_literals": ("Rehearsal Yield Router", AGENT_SERVICE_ID),
    }
    spec_module.INPUT_VALIDATORS[SPEC_ID] = spec_module._validate_yield_inputs
    scoring.FAMILY_PROTOCOLS[SPEC_ID] = protocol
    try:
        yield
    finally:
        if (
            spec_module.INPUT_VALIDATORS.get(SPEC_ID)
            is spec_module._validate_yield_inputs
        ):
            del spec_module.INPUT_VALIDATORS[SPEC_ID]
        if scoring.FAMILY_PROTOCOLS.get(SPEC_ID) is protocol:
            del scoring.FAMILY_PROTOCOLS[SPEC_ID]


@contextmanager
def _registered_warden_rehearsal_family():
    if (
        WARDEN_SPEC_ID in spec_module.INPUT_VALIDATORS
        or WARDEN_SPEC_ID in scoring.FAMILY_PROTOCOLS
    ):
        raise RehearsalRefused(
            f"the throwaway family {WARDEN_SPEC_ID!r} is already registered"
        )
    protocol = dict(scoring.FAMILY_PROTOCOLS["v3-04-warden-security"])
    protocol["family_salt"] = WARDEN_FAMILY_SALT
    spec_module.INPUT_VALIDATORS[WARDEN_SPEC_ID] = spec_module._validate_warden_inputs
    scoring.FAMILY_PROTOCOLS[WARDEN_SPEC_ID] = protocol
    try:
        yield
    finally:
        if (
            spec_module.INPUT_VALIDATORS.get(WARDEN_SPEC_ID)
            is spec_module._validate_warden_inputs
        ):
            del spec_module.INPUT_VALIDATORS[WARDEN_SPEC_ID]
        if scoring.FAMILY_PROTOCOLS.get(WARDEN_SPEC_ID) is protocol:
            del scoring.FAMILY_PROTOCOLS[WARDEN_SPEC_ID]


def _stage_spec(root: Path) -> tuple[PairedSpec, Path]:
    packaged = (
        resources.files("docket.advantage") / "v3" / "specs" / "v3-02-yield-router.json"
    )
    registered = load(Path(str(packaged)))
    body = registered._stage_one_body()
    body.update(
        {
            "spec_id": SPEC_ID,
            "inputs_ref": "inputs/rehearsal-yield-cases.json",
            "registration_provenance": (
                "REHEARSAL ONLY. This throwaway family is created and consumed inside one "
                "command, has no registration claim, and must never replace a packaged v3 "
                "specification or its evidence."
            ),
            "protocol_correction": {
                "status": "corrected_before_input_lock",
                "supersedes_stage_one_protocol_hash": (
                    registered.stage_one_protocol_hash
                ),
                "reason": (
                    "REHEARSAL ONLY: derive an isolated protocol identity from the packaged "
                    "Yield registration before any synthetic input or arm output exists."
                ),
            },
        }
    )
    execution = dict(body["execution_protocol"])
    execution.update(
        {
            "agent_endpoint": (f"https://rehearsal.invalid/hire/{AGENT_SERVICE_ID}"),
            "agent_service_id": AGENT_SERVICE_ID,
            "agent_request_contract": (
                "A synthetic external endpoint accepts only the locked rehearsal input "
                "object and returns a hash-bound free-tier receipt."
            ),
            "normalisation_version": NORMALISATION_VERSION,
            "normalisation_rule": (
                "The rehearsal projects its synthetic answer into the seven fixed fields "
                "named by normalisation_version without rewriting their values."
            ),
        }
    )
    body["execution_protocol"] = execution
    scoring_protocol = dict(body["scoring"])
    scoring_protocol["randomisation"] = (
        "After the rehearsal input lock, derive the opaque A/B assignment with the "
        f"registered {FAMILY_SALT!r} family salt."
    )
    body["scoring"] = scoring_protocol
    spec = PairedSpec(**body)
    path = root / "specs" / f"{SPEC_ID}.json"
    save(spec, path, repo_root=root)
    return spec, path


def _pool(index: int, *, tvl=1_000_000.0, fee=500.0, volume=None) -> dict:
    return {
        "id": f"0x{(0xAA00 + index):040x}",
        "token0": {"id": TOKENS[index % len(TOKENS)]},
        "token1": {"id": TOKENS[(index + 1) % len(TOKENS)]},
        "tvlUSD": tvl,
        "volumeUSD24h": tvl / 10 if volume is None else volume,
        "feeUSD24h": fee,
        "protocolFeeUSD24h": 100.0,
    }


def _source_bytes() -> tuple[bytes, bytes]:
    pools = [_pool(index, fee=400.0 + 60 * index) for index in range(5)]
    pools.extend(
        (
            _pool(5, tvl=5_000.0),
            _pool(6, volume=999_000_000.0),
        )
    )
    tokens = {"tokens": [{"chainId": 56, "address": address} for address in TOKENS]}
    return (
        json.dumps(pools, sort_keys=True).encode("utf-8"),
        json.dumps(tokens, sort_keys=True).encode("utf-8"),
    )


class _CaptureClock:
    def __init__(self, current: datetime):
        self.current = current

    def __call__(self) -> datetime:
        return self.current

    def sleep(self, seconds: float) -> None:
        self.current += timedelta(seconds=seconds)


def _capture(spec: PairedSpec, spec_path: Path, root: Path) -> dict:
    schedule = capture.registered_schedule(spec)
    moment = datetime.fromisoformat(schedule["first_attempt_at"].replace("Z", "+00:00"))
    wall = _CaptureClock(moment - timedelta(minutes=10))
    raw = _source_bytes()

    def attempt(urls, *, ordinal, scheduled_at):
        observed = datetime.fromisoformat(scheduled_at.replace("Z", "+00:00"))
        observations = [
            {
                "url": urls[0],
                "status": 200,
                "transport_error": None,
                "body": raw[0],
                "observed_at": capture._stamp_at(observed + timedelta(seconds=1)),
            },
            {
                "url": urls[1],
                "status": 200,
                "transport_error": None,
                "body": raw[1],
                "observed_at": capture._stamp_at(observed + timedelta(seconds=2)),
            },
        ]
        return capture._attempt_record(urls, observations, ordinal, scheduled_at)

    capture_dir = root / "capture"
    code = capture.main(
        [str(spec_path), str(capture_dir)],
        now=wall.current,
        clock=wall,
        sleep=wall.sleep,
        attempt=attempt,
    )
    if code != 0:
        raise RehearsalRefused(f"production capture exited {code}")
    return assemble.load_capture(capture_dir)


def _calibration_set(spec: PairedSpec) -> bytes:
    off_allowlist = _pool(7)
    off_allowlist["token0"] = {"id": f"0x{0xDEAD:040x}"}
    current = [_pool(index, fee=300.0 + 40 * index) for index in range(5)]
    current.extend(
        (
            _pool(5, tvl=5_000.0),
            _pool(6, volume=999_000_000.0),
            off_allowlist,
        )
    )
    cases = []
    for index, current_pool in enumerate(current):
        scenario = {
            "allowlist": list(TOKENS),
            "current_pool": current_pool,
            "destination_pool": _pool((index + 1) % 5, fee=700.0),
            "position_value_usd": 10000,
            "switching_cost_usd": 25,
            "decision_horizon_days": 30,
        }
        cases.append(
            {
                "case_id": f"rehearsal-cal-{index + 1:02d}",
                "input": scenario,
                "expected": spec_module._computed_calibration_truth(
                    "v3-02-yield-router", scenario
                ),
            }
        )
    return json.dumps({"spec_id": spec.spec_id, "cases": cases}, sort_keys=True).encode(
        "utf-8"
    )


def _capture_calibration(
    spec: PairedSpec, root: Path, calibration_set: bytes
) -> list[dict]:
    shared = json.loads(calibration_set.decode("utf-8"))["cases"]
    expected = {case["case_id"]: case["expected"] for case in shared}

    def synthetic_seat(prompt: bytes) -> bytes:
        request = json.loads(prompt.decode("utf-8"))
        return json.dumps(
            {
                "evaluator_id": request["evaluator_id"],
                "results": [
                    {"case_id": case["case_id"], "submitted": expected[case["case_id"]]}
                    for case in request["cases"]
                ],
            },
            sort_keys=True,
        ).encode("utf-8")

    calibration_dir = root / "calibration"
    for index, seat in enumerate(spec.scoring["evaluator_roster"], start=1):
        calibration_driver.run_seat(
            spec,
            calibration_dir,
            evaluator_id=seat["evaluator_id"],
            model_build=f"synthetic-rehearsal-seat-{index}",
            session_id=f"rehearsal-session-{index}",
            calibration_set=calibration_set,
            call_seat=synthetic_seat,
        )
    return calibration.assemble_evaluator_calibration(
        spec, calibration_dir, calibration_set
    )


def _lock(
    spec: PairedSpec,
    spec_path: Path,
    capture_result: dict,
    root: Path,
) -> PairedSpec:
    calibration_set = _calibration_set(spec)
    evaluator_calibration = _capture_calibration(spec, root, calibration_set)
    envelope = assemble.assemble_yield_envelope(
        spec,
        capture_result,
        calibration_dir=root / "calibration",
        calibration_set=calibration_set,
        evaluator_calibration=evaluator_calibration,
    )
    for case in envelope["cases"]:
        case["input"] = {
            "case_id": case["case_id"],
            "pool_id": case["pool_id"],
            "decision": case["truth"]["decision"],
        }
    assemble.write_envelope(spec, envelope, repo_root=root)
    locked = lock_inputs(spec, repo_root=root)
    save(locked, spec_path, repo_root=root)
    return locked


def _synthetic_output(payload: dict) -> dict:
    return {
        "verdict": "ALLOW",
        "risk_level": "REHEARSAL",
        "threat_classes": ["synthetic_fixture"],
        "detections": [{"pool_id": payload["pool_id"]}],
        "sanitized_payload": "not applicable in this synthetic rehearsal",
        "recommendation": payload["decision"],
        "checks": {"locked_case": payload["case_id"], "complete": True},
    }


class _RunClock:
    def __init__(self):
        self.calls = 0
        self.current = 0

    def __call__(self) -> int:
        slot_index = self.calls // 2
        ending = self.calls % 2 == 1
        self.calls += 1
        if ending:
            self.current += 40_000_000_000 if slot_index < 5 else 1_000_000_000
        return self.current


def _run_arms(spec: PairedSpec, root: Path) -> None:
    def stub_endpoint(url, *, json, headers, timeout, client=None):
        if url != spec.execution_protocol["agent_endpoint"]:
            raise AssertionError("the rehearsal called an unregistered endpoint")
        result = _synthetic_output(json)
        return httpx.Response(
            200,
            json={
                "result": result,
                "receipt": {
                    "service": AGENT_SERVICE_ID,
                    "input_hash": canonical_hash(json),
                    "output_hash": canonical_hash(result),
                    "payment": {
                        "status": "free_tier",
                        "amount": "0",
                        "asset": "REHEARSAL",
                    },
                },
            },
        )

    def invoke(slot, revealed):
        if slot.arm == "manual":
            return {"raw_output": _synthetic_output(revealed["input"])}
        return orchestrator.hire_agent(spec, revealed, hire=stub_endpoint)

    terminals = orchestrator.run_remaining(
        spec,
        root / "runs",
        repo_root=root,
        invoke=invoke,
        clock=_RunClock(),
    )
    if len(terminals) != spec.n_planned * 2 or any(
        terminal.get("outcome") != runner.SUCCEEDED for terminal in terminals
    ):
        raise RehearsalRefused("not every registered rehearsal slot succeeded")


def _score(spec: PairedSpec, root: Path) -> None:
    ledger = runner.ledger_path(spec, root / "runs")
    bundle = scoring.build_blinded_bundle(spec, ledger, repo_root=root)
    for seat in spec.scoring["evaluator_roster"]:
        rows = []
        for case in bundle["cases"]:
            for output in case["outputs"]:
                if not output["judgment_required"]:
                    continue
                for criterion in spec.quality_rubric["criteria"]:
                    rows.append(
                        {
                            "case_label": case["case_label"],
                            "arm_label": output["arm_label"],
                            "criterion": criterion["name"],
                            "score": 3,
                            "rationale": "The synthetic output carries every fixture field.",
                            "evidence_quote": "synthetic rehearsal evidence",
                        }
                    )
        sheet = {
            "spec_id": spec.spec_id,
            "spec_hash": spec.spec_hash,
            "evaluator_id": seat["evaluator_id"],
            "blinded_bundle_hash": canonical_hash(bundle),
            "scores": rows,
        }
        raw = (json.dumps(sheet, sort_keys=True) + "\n").encode("utf-8")
        scoring.ingest_score_sheet(spec, bundle, raw, root / "sheets")
    scoring.publish_mapping(
        spec,
        bundle,
        root / "sheets",
        root / "mappings",
        repo_root=root,
    )


def _stage_warden_spec(root: Path) -> tuple[PairedSpec, Path]:
    packaged = (
        resources.files("docket.advantage")
        / "v3"
        / "specs"
        / "v3-04-warden-security.json"
    )
    registered = load(Path(str(packaged)))
    body = registered._stage_one_body()
    body.update(
        {
            "spec_id": WARDEN_SPEC_ID,
            "inputs_ref": "inputs/warden-v4-rehearsal-cases.json",
            "registration_provenance": (
                "REHEARSAL ONLY. This synthetic Warden family is created and consumed "
                "inside one scratch tree. It is not the registered v3-04 validation and "
                "cannot produce a public Warden result."
            ),
            "protocol_correction": {
                "status": "corrected_before_input_lock",
                "supersedes_stage_one_protocol_hash": (
                    registered.stage_one_protocol_hash
                ),
                "reason": (
                    "REHEARSAL ONLY: derive an isolated Warden protocol identity from the "
                    "packaged v3-04 registration before synthetic calibration, input lock "
                    "or arm output exists; no registered attempt is consumed."
                ),
            },
        }
    )
    execution = dict(body["execution_protocol"])
    execution.update(
        {
            "agent_endpoint": (
                f"https://rehearsal.invalid/hire/{WARDEN_AGENT_SERVICE_ID}"
            ),
            "agent_service_id": WARDEN_AGENT_SERVICE_ID,
            "agent_request_contract": (
                "A synthetic endpoint accepts only the locked payload and returns a "
                "hash-bound free-tier Warden-shaped result."
            ),
        }
    )
    body["execution_protocol"] = execution
    scoring_protocol = dict(body["scoring"])
    scoring_protocol["randomisation"] = scoring_protocol["randomisation"].replace(
        "warden-v4-blinding", WARDEN_FAMILY_SALT
    )
    body["scoring"] = scoring_protocol
    spec = PairedSpec(**body)
    path = root / "specs" / f"{WARDEN_SPEC_ID}.json"
    save(spec, path, repo_root=root)
    return spec, path


def _warden_sources(spec: PairedSpec, root: Path) -> tuple[bytes, bytes, bytes]:
    packaged = resources.files("docket.advantage") / "v3" / "sources"
    calibration_body = json.loads(
        (packaged / "warden-v4-calibration-set.json").read_text(encoding="utf-8")
    )
    calibration_body["spec_id"] = spec.spec_id
    calibration_set = (
        json.dumps(calibration_body, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    ).encode("utf-8")
    heldout = (packaged / "warden-v4-heldout-cases.json").read_bytes()
    vendor = (packaged / "warden-v4-vendor-snapshot.json").read_bytes()
    source_dir = root / "docket/advantage/v3/sources"
    source_dir.mkdir(parents=True)
    (source_dir / "warden-v4-vendor-snapshot.json").write_bytes(vendor)
    return calibration_set, heldout, vendor


def _lock_warden(spec: PairedSpec, spec_path: Path, root: Path) -> PairedSpec:
    calibration_set, heldout, vendor = _warden_sources(spec, root)
    shared = json.loads(calibration_set.decode("utf-8"))["cases"]

    def synthetic_seat(prompt: bytes) -> bytes:
        request = json.loads(prompt.decode("utf-8"))
        return json.dumps(
            {
                "evaluator_id": request["evaluator_id"],
                "results": [
                    {
                        "case_id": case["case_id"],
                        "predicted_hostile": case["expected_hostile"],
                        "predicted_verdict": case["expected_verdict"],
                        "predicted_classes": case["expected_classes"],
                    }
                    for case in shared
                ],
            },
            sort_keys=True,
        ).encode("utf-8")

    calibration_dir = root / "calibration"
    for index, seat in enumerate(spec.scoring["evaluator_roster"], start=1):
        calibration_driver.run_seat(
            spec,
            calibration_dir,
            evaluator_id=seat["evaluator_id"],
            model_build=f"synthetic-warden-seat-{index}",
            session_id=f"warden-rehearsal-session-{index}",
            calibration_set=calibration_set,
            call_seat=synthetic_seat,
        )
    envelope = assemble.assemble_warden_envelope(
        spec,
        heldout,
        vendor,
        calibration_dir=calibration_dir,
        calibration_set=calibration_set,
    )
    assemble.write_envelope(spec, envelope, repo_root=root)
    locked = lock_inputs(spec, repo_root=root)
    save(locked, spec_path, repo_root=root)
    return locked


def _warden_output(case: dict) -> dict:
    verdict = case["expected_verdict"]
    return {
        "verdict": verdict,
        "risk_level": "NONE" if verdict == "ALLOW" else "REGISTERED_FIXTURE",
        "threat_classes": case["labels"],
        "detections": [
            {"class": label, "source": "synthetic rehearsal"}
            for label in case["labels"]
        ],
        "sanitized_payload": (
            "Synthetic rehearsal removed every registered hostile span."
            if verdict == "SANITIZE"
            else None
        ),
        "recommendation": "Continue" if verdict == "ALLOW" else "Apply the verdict",
        "checks": {"synthetic": True, "all_applicable": True},
    }


class _WardenRunClock:
    def __init__(self):
        self.calls = 0
        self.current = 0

    def __call__(self) -> int:
        slot_index = self.calls // 2
        ending = self.calls % 2 == 1
        self.calls += 1
        if ending:
            self.current += 40_000_000_000 if slot_index < 12 else 1_000_000_000
        return self.current


def _run_warden_arms(spec: PairedSpec, root: Path) -> None:
    inputs = scoring.load_inputs(spec, repo_root=root)
    truth_by_text = {case["text"]: case for case in inputs["cases"]}

    def stub_endpoint(url, *, json, headers, timeout, client=None):
        if url != spec.execution_protocol["agent_endpoint"]:
            raise AssertionError("the rehearsal called an unregistered endpoint")
        result = _warden_output(truth_by_text[json["payload"]])
        return httpx.Response(
            200,
            json={
                "result": result,
                "receipt": {
                    "service": WARDEN_AGENT_SERVICE_ID,
                    "input_hash": canonical_hash(json),
                    "output_hash": canonical_hash(result),
                    "payment": {
                        "status": "free_tier",
                        "amount": "0",
                        "asset": "REHEARSAL",
                    },
                },
            },
        )

    def invoke(slot, revealed):
        if slot.arm == "manual":
            return {"raw_output": _warden_output(truth_by_text[revealed["text"]])}
        return orchestrator.hire_agent(spec, revealed, hire=stub_endpoint)

    terminals = orchestrator.run_remaining(
        spec,
        root / "runs",
        repo_root=root,
        invoke=invoke,
        clock=_WardenRunClock(),
    )
    if len(terminals) != spec.n_planned * 2 or any(
        terminal.get("outcome") != runner.SUCCEEDED for terminal in terminals
    ):
        raise RehearsalRefused("not every registered Warden rehearsal slot succeeded")


def run_warden(output: Path) -> dict:
    """Run the full Warden path under a scratch-only synthetic family identity."""
    root = Path(output)
    if root.exists():
        raise RehearsalRefused(
            f"{root} already exists; rehearsal evidence is first-write"
        )
    root.mkdir(parents=True)
    with _registered_warden_rehearsal_family():
        spec, spec_path = _stage_warden_spec(root)
        locked = _lock_warden(spec, spec_path, root)
        _run_warden_arms(locked, root)
        _score(locked, root)
        payload = report.report(
            specs_dir=root / "specs",
            runs_dir=root / "runs",
            sheets_dir=root / "sheets",
            mappings_dir=root / "mappings",
            repo_root=root,
        )
        report_path = root / "advantage-v3.json"
        report_path.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        return payload


def run(output: Path) -> dict:
    """Create one isolated rehearsal tree and return its production v3 report."""
    root = Path(output)
    if root.exists():
        raise RehearsalRefused(
            f"{root} already exists; rehearsal evidence is first-write"
        )
    root.mkdir(parents=True)
    with _registered_rehearsal_family():
        spec, spec_path = _stage_spec(root)
        capture_result = _capture(spec, spec_path, root)
        locked = _lock(spec, spec_path, capture_result, root)
        _run_arms(locked, root)
        _score(locked, root)
        payload = report.report(
            specs_dir=root / "specs",
            runs_dir=root / "runs",
            sheets_dir=root / "sheets",
            mappings_dir=root / "mappings",
            repo_root=root,
        )
        report_path = root / "advantage-v3.json"
        report_path.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the v3 pipeline against a rehearsal-only throwaway family."
    )
    parser.add_argument("out", help="new directory for all throwaway evidence")
    args = parser.parse_args(argv)
    try:
        run(Path(args.out))
    except (OSError, RehearsalRefused, ValueError) as refusal:
        print(f"rehearsal refused: {refusal}")
        return 2
    path = Path(args.out) / "advantage-v3.json"
    print(f"rehearsal complete: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
