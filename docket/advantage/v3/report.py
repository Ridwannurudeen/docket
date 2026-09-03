"""Rebuild the v3 family states and claim outcomes from their durable artifacts.

Nothing in this module is a saved headline. Specifications, exact inputs, ledger events,
calibration responses, score sheets and the published mapping are reopened on every call.
Only eight states exist, and the two terminal claim states are ``refuted`` and
``not_refuted``. The latter is deliberately bounded to the registered falsifier.
"""

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from . import runner, scoring
from .spec import REPO_ROOT, is_warden_family, is_yield_family, load as load_spec

V3_DIR = Path(__file__).parent
SPECS_DIR = V3_DIR / "specs"
RUNS_DIR = V3_DIR / "runs"
SHEETS_DIR = V3_DIR / "sheets"
MAPPINGS_DIR = V3_DIR / "mappings"
ADVANTAGE_DIR = V3_DIR.parent
V1_DIR = ADVANTAGE_DIR / "experiments"
# The three recorded v1 tasks, in the order the v1 page lists them. `recorded_runs/` and
# `01-liquidity/live-audit.json` are separate observations, not tasks, and adding them here
# would inflate a row count nobody registered.
V1_TASK_IDS = ("01-liquidity", "02-trading", "03-security")
# Every state below `refuted`/`not_refuted` reaches this table with no rubric medians,
# because `family_report` only computes quality once both sheets and the mapping exist.
V3_SCORED_STATES = frozenset({"refuted", "not_refuted"})
NO_VERDICT = (
    "No verdict is computed anywhere in this table. Every cell is read out of a committed "
    "artifact, a null says the artifact does not carry that figure and names why, and "
    "nothing here ranks an arm, a task or a family against another."
)
V1_NO_QUALITY = (
    "v1 records both arms' complete outputs and refuses to grade them: a harness that "
    "scored its own runs would be marking its own homework."
)
V2_NO_ARM_TIMING = (
    "v2 registered dataset arms rather than a timed agent-versus-human pair, so it records "
    "no per-arm elapsed seconds, out-of-pocket cost or rubric score."
)

REGISTERED_WAITING = "registered_waiting_for_inputs"
SUPERSEDED_BEFORE_INPUT_LOCK = "superseded_before_input_lock"
ABANDONED_AFTER_FAILED_PRIMARY = "abandoned_after_failed_primary"
LOCKED_NOT_RUN = "locked_not_run"
RUNNING = "running"
COMPLETE_UNSCORED = "complete_unscored"
REFUTED = "refuted"
NOT_REFUTED = "not_refuted"
STATES = (
    REGISTERED_WAITING,
    SUPERSEDED_BEFORE_INPUT_LOCK,
    ABANDONED_AFTER_FAILED_PRIMARY,
    LOCKED_NOT_RUN,
    RUNNING,
    COMPLETE_UNSCORED,
    REFUTED,
    NOT_REFUTED,
)


def _check(name: str, refuted: bool, observed: dict) -> dict:
    return {"name": name, "refuted": bool(refuted), "observed": observed}


def _common_checks(spec, quality: dict, speed: dict) -> list[dict]:
    checks = [
        _check(
            "agent_median_rubric_total_is_lower",
            quality["quality_refuted"],
            {
                "agent_median_total": quality["arms"]["agent"]["median_total"],
                "manual_median_total": quality["arms"]["manual"]["median_total"],
            },
        ),
        _check(
            "any_pair_is_incomplete",
            not speed["complete_pairs_required"],
            {
                "complete_pairs": speed["n_complete_pairs"],
                "planned_pairs": spec.n_planned,
            },
        ),
        _check(
            "median_seconds_saved_is_below_threshold",
            speed["median_seconds_saved"] is not None
            and speed["median_seconds_saved"]
            < spec.speed_threshold["minimum_median_seconds_saved"],
            {
                "median_seconds_saved": speed["median_seconds_saved"],
                "minimum": spec.speed_threshold["minimum_median_seconds_saved"],
            },
        ),
        _check(
            "median_agent_to_manual_ratio_exceeds_threshold",
            speed["median_agent_to_manual_ratio"] is not None
            and speed["median_agent_to_manual_ratio"]
            > spec.speed_threshold["maximum_median_agent_to_manual_ratio"],
            {
                "median_agent_to_manual_ratio": speed["median_agent_to_manual_ratio"],
                "maximum": spec.speed_threshold["maximum_median_agent_to_manual_ratio"],
            },
        ),
    ]
    return checks


def _falsifier(spec, quality: dict, speed: dict, formula_metrics: dict | None) -> dict:
    checks = _common_checks(spec, quality, speed)
    if is_yield_family(spec):
        checks.append(
            _check(
                "any_agent_universe_differs_from_the_frozen_manifest",
                not formula_metrics["complete_and_correct"],
                {
                    "complete_and_correct": formula_metrics["n_complete_and_correct"],
                    "planned": formula_metrics["denominator"],
                },
            )
        )
    elif is_warden_family(spec):
        arms = formula_metrics["arms"]
        agent = arms["agent"]
        manual = arms["manual"]
        gates = formula_metrics["gates"]
        checks.extend(
            [
                _check(
                    "agent_recall_is_lower_than_manual_recall",
                    not gates["comparative_recall"],
                    {"agent": agent["recall"], "manual": manual["recall"]},
                ),
                _check(
                    "precision_is_null_or_agent_precision_is_lower",
                    not gates["comparative_precision"],
                    {"agent": agent["precision"], "manual": manual["precision"]},
                ),
                _check(
                    "agent_recall_is_below_0_90",
                    not gates["absolute_recall"],
                    {"agent": agent["recall"], "minimum": 0.90},
                ),
                _check(
                    "agent_precision_is_null_or_below_0_90",
                    not gates["absolute_precision"],
                    {"agent": agent["precision"], "minimum": 0.90},
                ),
                _check(
                    "not_all_agent_scans_succeeded",
                    not gates["all_agent_scans_succeeded"],
                    {"agent": agent["successful_scans"]},
                ),
                _check(
                    "a_frozen_critical_gate_failed",
                    not gates["zero_critical_survivors"],
                    {"failures": agent["critical_gate_failures"]},
                ),
            ]
        )
    return {"checks": checks, "refuted": any(check["refuted"] for check in checks)}


def _progress(attempts: dict) -> dict:
    scheduled = len(attempts)
    claimed = sum(attempt["started"] is not None for attempt in attempts.values())
    terminal = sum(attempt["terminal"] is not None for attempt in attempts.values())
    outcomes = Counter(
        attempt["terminal"]["outcome"]
        for attempt in attempts.values()
        if attempt["terminal"] is not None
    )
    observed_at = datetime.now(timezone.utc)
    stale = [
        {
            "case_id": case_id,
            "arm": arm,
            "deadline_at": attempt["started"]["deadline_at"],
        }
        for (case_id, arm), attempt in attempts.items()
        if attempt["started"] is not None
        and attempt["terminal"] is None
        and datetime.fromisoformat(attempt["started"]["deadline_at"]) <= observed_at
    ]
    progress = {
        "scheduled_primaries": scheduled,
        "claimed_primaries": claimed,
        "terminal_primaries": terminal,
        "outcomes": dict(sorted(outcomes.items())),
    }
    if stale:
        progress["stale_primaries"] = stale
    return progress


def _empty_family(spec, state: str) -> dict:
    return {
        "spec_id": spec.spec_id,
        "state": state,
        "spec": spec.as_record(),
        "inputs": None,
        "calibration": None,
        "ledger": [],
        "run_progress": None,
        "blinded_bundle": None,
        "score_sheets": [],
        "mapping": None,
        "quality": None,
        "speed": None,
        "costs": None,
        "formula_metrics": None,
        "falsifier_result": None,
        "unscored_reason": None,
    }


def family_report(
    spec_path: Path,
    *,
    runs_dir: Path,
    sheets_dir: Path,
    mappings_dir: Path,
    repo_root: Path,
) -> dict:
    spec = load_spec(spec_path, repo_root=repo_root)
    if not spec.runnable:
        return _empty_family(spec, REGISTERED_WAITING)

    inputs = scoring.load_inputs(spec, repo_root=repo_root)
    calibration = scoring.calibration_metrics(spec, inputs)
    ledger_path = runner.ledger_path(spec, runs_dir)
    events = runner.read_events(ledger_path)
    attempts = scoring.primary_attempts(spec, ledger_path, repo_root=repo_root)
    progress = _progress(attempts)
    family = _empty_family(spec, LOCKED_NOT_RUN)
    family.update(
        {
            "inputs": inputs,
            "calibration": calibration,
            "ledger": events,
            "run_progress": progress,
            "costs": scoring.cost_metrics(attempts),
        }
    )
    if progress["claimed_primaries"] == 0:
        return family
    if progress["terminal_primaries"] != progress["scheduled_primaries"]:
        family["state"] = RUNNING
        return family

    blocked = [
        {"case_id": case_id, "arm": arm}
        for (case_id, arm), attempt in attempts.items()
        if arm == "agent" and attempt["terminal"]["outcome"] == runner.BLOCKED_CONTRACT
    ]
    if blocked:
        family["state"] = COMPLETE_UNSCORED
        family["unscored_reason"] = runner.BLOCKED_CONTRACT
        family["blocked_primaries"] = blocked
        return family

    bundle = scoring.build_blinded_bundle(spec, ledger_path, repo_root=repo_root)
    sheets = scoring.load_score_sheets(spec, bundle, sheets_dir, require_all=False)
    mapping = scoring.load_mapping(
        spec,
        bundle,
        sheets_dir,
        mappings_dir,
        repo_root=repo_root,
    )
    family["blinded_bundle"] = bundle
    family["score_sheets"] = sheets
    family["mapping"] = mapping
    if len(sheets) != len(spec.scoring["evaluator_roster"]):
        family["state"] = COMPLETE_UNSCORED
        family["unscored_reason"] = "score_sheets_missing"
        return family
    if mapping is None:
        family["state"] = COMPLETE_UNSCORED
        family["unscored_reason"] = "mapping_not_published"
        return family

    quality = scoring.aggregate_rubric(
        spec, bundle, sheets_dir, mapping, repo_root=repo_root
    )
    speed = scoring.speed_metrics(spec, attempts, inputs=inputs, repo_root=repo_root)
    if is_yield_family(spec):
        formula_metrics = scoring.yield_completeness(spec, inputs, attempts)
    elif is_warden_family(spec):
        formula_metrics = scoring.warden_metrics(
            spec, inputs, attempts, repo_root=repo_root
        )
    else:
        formula_metrics = {}
    falsifier = _falsifier(spec, quality, speed, formula_metrics)
    family.update(
        {
            "state": REFUTED if falsifier["refuted"] else NOT_REFUTED,
            "quality": quality,
            "speed": speed,
            "formula_metrics": formula_metrics,
            "falsifier_result": falsifier,
        }
    )
    return family


def _seconds(value):
    return None if value is None else float(value)


def _v1_rows(v1_dir: Path) -> list[dict]:
    rows = []
    for task_id in V1_TASK_IDS:
        path = Path(v1_dir) / f"{task_id}.json"
        if not path.is_file():
            continue
        record = json.loads(path.read_text(encoding="utf-8"))
        arms = {"agent": record["agent_arm"], "manual": record["manual_arm"]}
        errored = [name for name, arm in arms.items() if arm.get("error") is not None]
        rows.append(
            {
                "version": "v1",
                "task": record["task_id"],
                "category": record["category"],
                "arms": sorted(arms),
                "n_planned": 1,
                "n_terminal": len(arms),
                "median_agent_seconds": _seconds(arms["agent"].get("seconds")),
                "median_manual_seconds": _seconds(arms["manual"].get("seconds")),
                "cost_by_arm": {name: arm.get("cost") for name, arm in arms.items()},
                "quality_by_arm": {name: None for name in arms},
                "quality_measure": None,
                "state": "recorded_with_arm_error" if errored else "recorded",
                "unavailable": {"quality_by_arm": V1_NO_QUALITY},
            }
        )
    return rows


def _v2_rows(experiments: list[dict]) -> list[dict]:
    rows = []
    for experiment in experiments:
        run = experiment["run"]
        arms = run.get("arms")
        if isinstance(arms, dict):
            arm_names = sorted(arms)
        elif isinstance(run.get("arm_name"), str):
            arm_names = [run["arm_name"]]
        else:
            arm_names = []
        scores = experiment.get("scores")
        quality = (
            {arm_names[0]: scores} if len(arm_names) == 1 and scores else {}
        )
        rows.append(
            {
                "version": "v2",
                "task": experiment["experiment_id"],
                "category": experiment["spec"]["category"],
                "arms": arm_names,
                "n_planned": experiment["spec"]["n_planned"],
                "n_terminal": run.get("n_planned"),
                "median_agent_seconds": None,
                "median_manual_seconds": None,
                "cost_by_arm": {name: None for name in arm_names},
                "quality_by_arm": quality or {name: None for name in arm_names},
                "quality_measure": (
                    "registered detector rates over the frozen corpus" if quality else None
                ),
                "state": (
                    REFUTED
                    if experiment["falsifier_result"]["refuted"]
                    else NOT_REFUTED
                ),
                "unavailable": {
                    "median_agent_seconds": V2_NO_ARM_TIMING,
                    "median_manual_seconds": V2_NO_ARM_TIMING,
                    "cost_by_arm": V2_NO_ARM_TIMING,
                    **({} if quality else {"quality_by_arm": V2_NO_ARM_TIMING}),
                },
            }
        )
    return rows


def _v3_rows(families: list[dict]) -> list[dict]:
    rows = []
    for family in families:
        spec = family["spec"]
        speed = family["speed"]
        quality = family["quality"]
        progress = family["run_progress"]
        costs = family["costs"]
        unavailable = {}
        if speed is None:
            unavailable["median_agent_seconds"] = (
                f"no paired speed measure exists while this family is {family['state']}"
            )
            unavailable["median_manual_seconds"] = unavailable["median_agent_seconds"]
        if quality is None:
            unavailable["quality_by_arm"] = family["unscored_reason"] or (
                f"no rubric aggregate exists while this family is {family['state']}"
            )
        if costs is None:
            unavailable["cost_by_arm"] = (
                "no ledger cost is recorded before the input lock"
            )
        by_arm = {arm: None for arm in runner.ARMS}
        if costs is not None:
            for total in costs["totals"]:
                by_arm[total["arm"]] = {
                    "amount": total["amount"],
                    "unit": total["unit"],
                }
        rows.append(
            {
                "version": "v3",
                "task": family["spec_id"],
                "category": spec["category"],
                "arms": sorted(spec["arms"]),
                "n_planned": spec["n_planned"],
                "n_terminal": (
                    None if progress is None else progress["terminal_primaries"]
                ),
                "median_agent_seconds": (
                    None if speed is None else speed["agent_median_seconds"]
                ),
                "median_manual_seconds": (
                    None if speed is None else speed["manual_median_seconds"]
                ),
                "cost_by_arm": by_arm,
                "quality_by_arm": (
                    {arm: None for arm in runner.ARMS}
                    if quality is None
                    else {
                        arm: quality["arms"][arm]["median_total"]
                        for arm in runner.ARMS
                    }
                ),
                "quality_measure": (
                    None
                    if quality is None
                    else "median registered rubric total per arm"
                ),
                "state": family["state"],
                "unavailable": unavailable,
            }
        )
    return rows


def one_page(families: list[dict], *, v1_dir: Path = V1_DIR) -> dict:
    """Every registered task in one table, derived from committed artifacts only.

    The v1, v2 and v3 rows are deliberately not made to look alike. v1 recorded one paired
    observation per task and refused to grade it; v2 registered dataset arms with no clock
    on either of them; only v3 has a paired elapsed measure and a rubric. Forcing one shape
    onto all three would put a number in a cell no artifact contains, so a missing figure is
    a null with the reason beside it.
    """
    from ..v2 import report as v2_report

    rows = _v1_rows(v1_dir) + _v2_rows(v2_report.experiments()) + _v3_rows(families)
    return {
        "verdict": None,
        "note": NO_VERDICT,
        "n_rows": len(rows),
        "rows": rows,
    }


def report(
    *,
    specs_dir: Path = SPECS_DIR,
    runs_dir: Path = RUNS_DIR,
    sheets_dir: Path = SHEETS_DIR,
    mappings_dir: Path = MAPPINGS_DIR,
    repo_root: Path = REPO_ROOT,
) -> dict:
    """Return all registered v3 families and a summary derived from their states."""
    families = [
        family_report(
            path,
            runs_dir=runs_dir,
            sheets_dir=sheets_dir,
            mappings_dir=mappings_dir,
            repo_root=repo_root,
        )
        for path in sorted(Path(specs_dir).glob("*.json"))
    ]
    by_id = {family["spec_id"]: family for family in families}
    for successor in families:
        provenance = successor["spec"].get("pilot_provenance")
        if not isinstance(provenance, dict):
            continue
        predecessor = by_id.get(provenance.get("prior_spec_id"))
        if (
            predecessor is not None
            and predecessor["state"] == REGISTERED_WAITING
            and predecessor["spec"]["stage_one_protocol_hash"]
            == provenance.get("prior_stage_one_protocol_hash")
        ):
            predecessor["state"] = SUPERSEDED_BEFORE_INPUT_LOCK
            predecessor["superseded_by"] = successor["spec_id"]
    for successor in families:
        provenance = successor["spec"].get("successor_provenance")
        if (
            successor["spec_id"] != "v3-06-yield-router-assisted"
            or not isinstance(provenance, dict)
            or provenance.get("status") != "distinct_successor_after_failed_primary"
        ):
            continue
        predecessor = by_id.get(provenance.get("prior_spec_id"))
        if (
            predecessor is None
            or predecessor["state"] != RUNNING
            or predecessor["spec"]["stage_one_protocol_hash"]
            != provenance.get("prior_stage_one_protocol_hash")
            or predecessor["spec"]["spec_hash"] != provenance.get("prior_spec_hash")
            or provenance.get("prior_ledger_ref")
            != f"docket/advantage/v3/runs/{predecessor['spec_id']}.jsonl"
            or (Path(repo_root) / provenance["prior_ledger_ref"]).resolve()
            != (Path(runs_dir) / f"{predecessor['spec_id']}.jsonl").resolve()
        ):
            continue
        failed_primary = any(
            event.get("kind") == runner.TERMINATED
            and event.get("attempt_kind") == runner.PRIMARY
            and event.get("outcome") == runner.FAILED
            for event in predecessor["ledger"]
        )
        if failed_primary:
            predecessor["state"] = ABANDONED_AFTER_FAILED_PRIMARY
            predecessor["abandoned_by"] = successor["spec_id"]
            predecessor["successor_provenance"] = provenance
    states = Counter(family["state"] for family in families)
    return {
        "version": "v3",
        "states": list(STATES),
        "summary": {
            "n_families": len(families),
            "one_page": one_page(families),
            "states": dict(sorted(states.items())),
            "refuted": [
                family["spec_id"] for family in families if family["state"] == REFUTED
            ],
            "not_refuted": [
                family["spec_id"]
                for family in families
                if family["state"] == NOT_REFUTED
            ],
        },
        "families": families,
    }
