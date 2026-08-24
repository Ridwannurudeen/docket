"""The registration half of v3, including the refusals that make it a real lock.

V3 is the repeated agent-versus-human report. These tests distinguish the stage-one
protocol identity from the later composite input lock, verify the referenced bytes rather
than trusting a filled-in field, and bind the objective rules the three families must use
before any input or output exists.
"""

import hashlib
import json
from base64 import b64decode, b64encode
from pathlib import Path

import pytest

import docket.advantage.v3.spec as spec_module
from docket.advantage.v3.spec import (
    MANUAL_FIRST,
    PairedSpec,
    assert_runnable,
    load,
    lock_inputs,
    save,
)
from docket.hire.receipts import canonical_hash

ROOT = Path(__file__).resolve().parents[1]
SPECS_DIR = ROOT / "docket" / "advantage" / "v3" / "specs"
REGISTERED = sorted(SPECS_DIR.glob("*.json"))
INPUT_REF = "docket/advantage/v3/inputs/x.json"


@pytest.fixture(autouse=True)
def _register_the_minimal_test_protocol_validator(monkeypatch):
    """Core lock tests use spec id ``t`` to isolate two-stage mechanics. Production ids
    still require one of the three explicit family validators."""
    monkeypatch.setitem(
        spec_module.INPUT_VALIDATORS,
        "t",
        lambda _spec, _body, _cases, _repo_root: None,
    )


def _criterion(name: str) -> dict:
    return {
        "name": name,
        "score_3_means": "all registered facts are present and correct",
        "score_2_means": "the registered decision is correct and one named fact is absent",
        "score_1_means": "only the registered decision is present and correct",
        "score_0_means": "the decision is absent or wrong",
    }


def _valid(**overrides) -> dict:
    body = {
        "spec_id": "t",
        "question": "q?",
        "category": "yield/LP",
        "claim": "the hired arm scores no lower and clears the registered speed threshold",
        "falsifier": "a lower median rubric total refutes the quality limb",
        "arms": {
            arm: {
                "what_it_does": "does the registered task",
                "who_runs_it": "the registered runner",
                "what_is_recorded": "seconds, cost, output and failures",
            }
            for arm in ("agent", "manual")
        },
        "case_selection": {
            "population": "the bounded registered population",
            "truth_source": "the frozen source bytes and formulas",
            "rule": "five cases selected by the registered deterministic rule",
            "chosen_by": "the rule, before either arm runs",
            "excluded": "nothing is replaced after selection",
        },
        "quality_rubric": {
            "scale": "0-3 per criterion; only the criterion-specific anchors apply",
            "criteria": [_criterion("a"), _criterion("b")],
        },
        "scoring": {
            "evaluators": 2,
            "evaluator_roster": [
                {"evaluator_id": "one"},
                {"evaluator_id": "two"},
            ],
            "blinded": True,
            "randomisation": "assignments come from the frozen seed",
            "disagreement": "both sheets are published without post-hoc adjudication",
            "selection_rule": "the two named seats are fixed and cannot be replaced",
            "calibration": "both pass the same frozen examples before seeing outputs",
        },
        "speed_threshold": {
            "formula": "median(manual_seconds - agent_seconds) and median(agent/manual)",
            "material_if": "both registered inequalities pass over complete pairs",
            "minimum_median_seconds_saved": 30.0,
            "maximum_median_agent_to_manual_ratio": 0.5,
            "requires_complete_pairs": True,
        },
        "timing": {
            "clock": "harness-owned monotonic clock",
            "start_event": "the harness reveals the frozen case",
            "stop_event": "the harness receives the immutable final answer",
            "interruptions": "the clock never pauses and no interruption is subtracted",
            "operator_control": "the manual operator cannot start, stop or edit the clock",
            "timeout_seconds": 1200,
        },
        "measures": {
            "time": "elapsed monotonic seconds from the registered events",
            "cost": "out-of-pocket amount and unit only",
        },
        "execution_protocol": {
            "arm_block_order": MANUAL_FIRST,
            "blinding_seed_recipe": "the registered byte recipe",
            "blinding_parity": "even_a_is_agent",
            "normalisation_version": "test.v1: a, b",
            "score_sheet_hash_recipe": "canonical hash of the parsed sheet",
            "sheets_per_seat": 1,
            "agent_endpoint": "https://docket.gudman.xyz/hire/test-service",
            "agent_service_id": "test-service",
            "agent_request_contract": "the harness derives the request from locked inputs",
        },
        "n_planned": 5,
        "stopping_rule": "every frozen primary case once per arm; no scored retry",
        "registration_provenance": (
            "Git history is the registration witness: the first commit containing this "
            "exact stage-one protocol hash establishes that it predates later input and "
            "run commits. No independently attested wall-clock time is claimed."
        ),
        "protocol_correction": {
            "status": "corrected_before_input_lock",
            "supersedes_stage_one_protocol_hash": "0x" + "1" * 64,
            "reason": "The earlier stage-one protocol could not be executed as written.",
        },
        "inputs_ref": INPUT_REF,
    }
    return body | overrides


def _input_record(spec: PairedSpec) -> dict:
    if spec.spec_id == "v3-03-warden-security":
        shared_cases = [
            {
                "case_id": f"calibration-{case}",
                "input": {"payload": f"calibration payload {case}"},
                "expected_hostile": case <= 4,
                # A published vendor class: the synthetic snapshot these records are
                # locked against declares class-0..class-3, and a calibration key may
                # only name classes the vendor actually published.
                "expected_classes": ["class-0"] if case <= 4 else [],
            }
            for case in range(1, 9)
        ]
    elif spec.spec_id == "v3-01-range-doctor":
        shared_cases = []
        ticks = (0, 10, -11, 0, 10, -11, 0, 10)
        for case, current_tick in enumerate(ticks, start=1):
            inputs = {
                "current_tick": current_tick,
                "tick_lower": -10,
                "tick_upper": 10,
                "fee_usd_24h": 20 + case,
                "protocol_fee_usd_24h": 5,
                "tvl_usd": 36500,
                "declared_position_value_usd": 10000,
                "estimated_recenter_cost_usd": 25,
            }
            shared_cases.append(
                {
                    "case_id": f"calibration-{case}",
                    "input": inputs,
                    "expected": spec_module._computed_calibration_truth(
                        spec.spec_id, inputs
                    ),
                }
            )
    elif spec.spec_id == "v3-02-yield-router":
        allowlist = [f"0x{number:040x}" for number in (101, 102)]
        shared_cases = []
        for case in range(1, 9):
            current_pool = {
                "id": f"0x{case:040x}",
                "token0": {"id": allowlist[0]},
                "token1": {"id": allowlist[1]},
                "tvlUSD": "100000",
                "volumeUSD24h": "1000",
                "feeUSD24h": "100",
                "protocolFeeUSD24h": "10",
            }
            if case == 5:
                current_pool["token0"] = {"id": f"0x{999:040x}"}
            elif case == 6:
                current_pool["tvlUSD"] = "5000"
            elif case == 7:
                current_pool["volumeUSD24h"] = "6000000"
            elif case == 8:
                current_pool["protocolFeeUSD24h"] = None
            destination_pool = {
                "id": f"0x{1000 + case:040x}",
                "token0": {"id": allowlist[0]},
                "token1": {"id": allowlist[1]},
                "tvlUSD": "100000",
                "volumeUSD24h": "1000",
                "feeUSD24h": "200",
                "protocolFeeUSD24h": "20",
            }
            inputs = {
                "allowlist": allowlist,
                "current_pool": current_pool,
                "destination_pool": destination_pool,
                "position_value_usd": 10000,
                "switching_cost_usd": 25,
                "decision_horizon_days": 30,
            }
            shared_cases.append(
                {
                    "case_id": f"calibration-{case}",
                    "input": inputs,
                    "expected": spec_module._computed_calibration_truth(
                        spec.spec_id, inputs
                    ),
                }
            )
    else:
        shared_cases = [
            {
                "case_id": f"calibration-{case}",
                "input": {"case": case},
                "expected": {"answer": case},
            }
            for case in range(1, 9)
        ]
    shared_record = {
        "spec_id": spec.spec_id,
        "cases": shared_cases,
    }
    if spec.spec_id == "v3-03-warden-security":
        shared_record["class_vocabulary"] = [f"class-{number}" for number in range(4)]
    shared_body = json.dumps(shared_record, sort_keys=True).encode()
    calibration = []
    for number, evaluator in enumerate(spec.scoring["evaluator_roster"], start=1):
        if spec.spec_id == "v3-03-warden-security":
            results = [
                {
                    **shared_case,
                    "predicted_hostile": shared_case["expected_hostile"],
                    "predicted_classes": shared_case["expected_classes"],
                }
                for shared_case in shared_cases
            ]
        else:
            results = [
                {
                    **shared_case,
                    "submitted": shared_case["expected"],
                }
                for shared_case in shared_cases
            ]
        calibration.append(
            {
                "evaluator_id": evaluator["evaluator_id"],
                "model_build": f"test-model-{number}",
                "session_id": f"test-session-{number}",
                "rubric_anchor_hash": canonical_hash(spec.quality_rubric["criteria"]),
                "calibration_results": results,
            }
        )
    return {
        "spec_id": spec.spec_id,
        "stage_one_protocol_hash": spec.stage_one_protocol_hash,
        "calibration_set": {
            "sha256": hashlib.sha256(shared_body).hexdigest(),
            "body_base64": b64encode(shared_body).decode(),
        },
        "evaluator_calibration": calibration,
        "cases": [
            {"case_id": f"case-{number + 1}"} for number in range(spec.n_planned)
        ],
    }


def _write_inputs(root: Path, spec: PairedSpec, body: bytes | None = None) -> Path:
    path = root / INPUT_REF
    path.parent.mkdir(parents=True, exist_ok=True)
    if body is None:
        body = (json.dumps(_input_record(spec), sort_keys=True) + "\n").encode()
    path.write_bytes(body)
    return path


def _source_ref(root: Path, ref: str, body: bytes) -> dict:
    path = root / ref
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)
    return {"ref": ref, "sha256": hashlib.sha256(body).hexdigest()}


# ------------------------------------------------------------------ the refusals


def test_a_spec_must_compare_an_agent_against_a_human():
    with pytest.raises(ValueError, match="arms are"):
        PairedSpec(**_valid(arms={"agent": {}, "keyword_null": {}}))


def test_an_arm_nobody_can_rerun_is_refused():
    thin = {"agent": {"what_it_does": "", "who_runs_it": "", "what_is_recorded": ""}}
    with pytest.raises(ValueError, match="the agent arm leaves"):
        PairedSpec(**_valid(arms=_valid()["arms"] | thin))


def test_one_pair_per_task_is_refused_because_that_is_v1():
    with pytest.raises(ValueError, match="fewer than 3"):
        PairedSpec(**_valid(n_planned=1))


def test_every_rubric_criterion_requires_its_own_middle_anchors():
    """The old global 1-versus-2 rule asked whether a gap changed a reader's action. That
    judgement varied by reader, so every criterion now has to define all four scores."""
    criteria = [_criterion("a"), _criterion("b")]
    criteria[0]["score_2_means"] = ""
    with pytest.raises(ValueError, match="score_2_means"):
        PairedSpec(
            **_valid(
                quality_rubric={
                    "scale": "0-3 using only the criterion anchors",
                    "criteria": criteria,
                }
            )
        )


def test_scoring_requires_two_distinct_blinded_model_seats():
    """Seat ids bind the two published score sheets; they do not prove two people or
    independent operators, so the protocol must not request identity attestations."""
    scoring = _valid()["scoring"]
    with pytest.raises(ValueError, match="fewer than 2"):
        PairedSpec(**_valid(scoring=scoring | {"evaluators": 1}))
    with pytest.raises(ValueError, match="roster has 1 seat ids"):
        PairedSpec(
            **_valid(
                scoring=scoring | {"evaluator_roster": scoring["evaluator_roster"][:1]}
            )
        )
    duplicated = [dict(row) for row in scoring["evaluator_roster"]]
    duplicated[0]["evaluator_id"] = duplicated[1]["evaluator_id"]
    with pytest.raises(ValueError, match="seat ids are not distinct"):
        PairedSpec(**_valid(scoring=scoring | {"evaluator_roster": duplicated}))
    with pytest.raises(ValueError, match="not blinded"):
        PairedSpec(**_valid(scoring=scoring | {"blinded": False}))


def test_material_speed_requires_fixed_absolute_and_relative_thresholds():
    threshold = _valid()["speed_threshold"]
    with pytest.raises(ValueError, match="seconds saved"):
        PairedSpec(
            **_valid(speed_threshold=threshold | {"minimum_median_seconds_saved": 0})
        )
    with pytest.raises(ValueError, match="agent/manual ratio"):
        PairedSpec(
            **_valid(
                speed_threshold=threshold | {"maximum_median_agent_to_manual_ratio": 1}
            )
        )
    with pytest.raises(ValueError, match="fast failures"):
        PairedSpec(
            **_valid(speed_threshold=threshold | {"requires_complete_pairs": False})
        )


def test_manual_timing_requires_a_fixed_positive_timeout_and_external_controls():
    timing = _valid()["timing"]
    with pytest.raises(ValueError, match="operator_control"):
        PairedSpec(**_valid(timing=timing | {"operator_control": ""}))
    with pytest.raises(ValueError, match="positive integer"):
        PairedSpec(**_valid(timing=timing | {"timeout_seconds": 0}))


def test_a_blank_falsifier_or_selection_truth_source_is_refused():
    with pytest.raises(ValueError, match="falsifier is empty"):
        PairedSpec(**_valid(falsifier="   "))
    selection = _valid()["case_selection"]
    with pytest.raises(ValueError, match="truth_source"):
        PairedSpec(**_valid(case_selection=selection | {"truth_source": ""}))


def test_the_record_cannot_be_edited_through_a_reference_its_caller_kept():
    rubric = _valid()["quality_rubric"]
    spec = PairedSpec(**_valid(quality_rubric=rubric))
    before = spec.spec_hash
    rubric["criteria"].append(_criterion("smuggled"))
    assert spec.quality_rubric["criteria"] != rubric["criteria"]
    assert spec.spec_hash == before


def test_a_locked_protocol_mutated_through_its_own_nested_dict_refuses_to_run(
    tmp_path,
):
    """Frozen dataclasses do not freeze their nested dicts. The cached stage-one identity
    must catch a write through the spec object itself before the harness can run it."""
    stage_one = PairedSpec(**_valid())
    _write_inputs(tmp_path, stage_one)
    locked = lock_inputs(stage_one, repo_root=tmp_path)
    locked.quality_rubric["criteria"][0]["score_3_means"] = "whatever happened"

    with pytest.raises(ValueError, match="protocol was mutated after construction"):
        assert_runnable(locked, repo_root=tmp_path)
    with pytest.raises(ValueError, match="protocol was mutated after construction"):
        save(locked, tmp_path / "mutated.json", repo_root=tmp_path)


# ------------------------------------------------------- the two-stage input lock


@pytest.mark.parametrize("digest", ["0xabc", "a" * 63, "A" * 64, "z" * 64])
def test_a_nonblank_string_is_not_an_input_digest(digest):
    """The old test blessed ``0xabc``. Only the repository's raw-file digest convention
    can represent a lock; anything else is refused before runnability is considered."""
    with pytest.raises(ValueError, match="bare lowercase 64-hex"):
        PairedSpec(**_valid(inputs_sha256=digest))


def test_a_well_formed_fake_digest_does_not_make_a_spec_runnable(tmp_path):
    spec = PairedSpec(**_valid(inputs_sha256="0" * 64))
    _write_inputs(tmp_path, spec)
    with pytest.raises(ValueError, match="digest mismatch"):
        assert_runnable(spec, repo_root=tmp_path)


def test_lock_inputs_hashes_the_referenced_file_s_exact_bytes(tmp_path):
    stage_one = PairedSpec(**_valid())
    path = _write_inputs(tmp_path, stage_one)
    locked = lock_inputs(stage_one, repo_root=tmp_path)

    assert locked.inputs_sha256 == hashlib.sha256(path.read_bytes()).hexdigest()
    assert locked.runnable is True
    assert_runnable(locked, repo_root=tmp_path)


def test_a_hashed_empty_or_wrong_protocol_case_file_cannot_be_locked(tmp_path):
    """A digest proves byte identity, not that the bytes are the registered experiment.
    The input envelope therefore binds both protocol identity and exact planned count."""
    stage_one = PairedSpec(**_valid())
    empty = _input_record(stage_one) | {"cases": []}
    _write_inputs(tmp_path, stage_one, json.dumps(empty).encode())
    with pytest.raises(ValueError, match="exactly 5 cases"):
        lock_inputs(stage_one, repo_root=tmp_path)

    wrong_protocol = _input_record(stage_one) | {
        "stage_one_protocol_hash": "0x" + "0" * 64
    }
    _write_inputs(tmp_path, stage_one, json.dumps(wrong_protocol).encode())
    with pytest.raises(ValueError, match="different stage-one protocol"):
        lock_inputs(stage_one, repo_root=tmp_path)


def test_an_unknown_family_cannot_fall_through_generic_input_validation(tmp_path):
    spec = PairedSpec(**_valid(spec_id="unregistered-family"))
    input_path = tmp_path / spec.inputs_ref
    input_path.parent.mkdir(parents=True, exist_ok=True)
    input_path.write_text(json.dumps(_input_record(spec)), encoding="utf-8")

    with pytest.raises(ValueError, match="has no registered input validator"):
        lock_inputs(spec, repo_root=tmp_path)


def test_model_calibration_is_computed_against_one_shared_answer_key(tmp_path):
    """A model seat cannot embed easier expected values in its responses; both owner-run
    seats must answer the one published, hash-bound calibration set."""
    spec = PairedSpec(**_valid())
    record = _input_record(spec)
    seat = record["evaluator_calibration"][0]
    seat["calibration_results"][0]["expected"] = {"answer": "rewritten"}
    _write_inputs(tmp_path, spec, json.dumps(record).encode())

    with pytest.raises(ValueError, match="contradicts the shared answer key"):
        lock_inputs(spec, repo_root=tmp_path)


def test_registered_calibration_truth_is_recomputed_from_family_inputs(tmp_path):
    """A common answer key still proves nothing if its author can make the expected
    calculations self-consistent but false; registered families recompute that truth."""
    spec = load(SPECS_DIR / "v3-01-range-doctor.json")
    record = _input_record(spec)
    shared = json.loads(b64decode(record["calibration_set"]["body_base64"]))
    shared["cases"][0]["expected"]["net_apr"] = 999
    raw = json.dumps(shared, sort_keys=True).encode()
    record["calibration_set"] = {
        "sha256": hashlib.sha256(raw).hexdigest(),
        "body_base64": b64encode(raw).decode(),
    }
    input_path = tmp_path / spec.inputs_ref
    input_path.parent.mkdir(parents=True, exist_ok=True)
    input_path.write_text(json.dumps(record), encoding="utf-8")

    with pytest.raises(ValueError, match="contradicts its family formulas"):
        lock_inputs(spec, repo_root=tmp_path)


def _warden_fixture(root: Path) -> tuple[PairedSpec, dict, Path]:
    """A complete Warden envelope that locks, so a refusal below is the mutation's doing."""
    spec = load(SPECS_DIR / "v3-03-warden-security.json")
    vendor = _source_ref(
        root,
        "evidence/vendor.json",
        b'{"classes":["class-0","class-1","class-2","class-3"]}\n',
    )
    cases = []
    for number in range(12):
        hostile = number < 8
        critical = number < 2
        label = f"class-{number % 4}"
        cases.append(
            {
                "case_id": f"warden-{number + 1}",
                "payload_id": f"payload-{number + 1}",
                "text": f"payload {number + 1}",
                "expected_verdict": "BLOCK" if hostile else "ALLOW",
                "labels": [label] if hostile else [],
                "evidence_spans": (
                    [{"label": label, "start": 0, "end": 7}] if hostile else []
                ),
                "hostile": hostile,
                "critical": critical,
                "survival_predicates": (
                    [
                        {
                            "kind": "literal",
                            "pattern": "payload",
                            "label": label,
                            "evidence_start": 0,
                            "evidence_end": 7,
                        }
                    ]
                    if critical
                    else []
                ),
            }
        )
    record = _input_record(spec) | {"vendor_snapshot": vendor, "cases": cases}
    path = root / spec.inputs_ref
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record), encoding="utf-8")
    return spec, record, path


def _rewrite_calibration(record: dict, mutate) -> None:
    """Apply `mutate` to the shared answer key and rehash it, the way a real edit would."""
    shared = json.loads(b64decode(record["calibration_set"]["body_base64"]))
    mutate(shared)
    raw = json.dumps(shared, sort_keys=True).encode()
    record["calibration_set"] = {
        "sha256": hashlib.sha256(raw).hexdigest(),
        "body_base64": b64encode(raw).decode(),
    }


def test_a_calibration_answer_key_outside_the_vendor_vocabulary_is_refused(tmp_path):
    """The held-out labels are checked against the vendor's published classes. The
    calibration key was not, so both seats could clear the micro-F1 floor on a class the
    vendor never published — inside the artifact that exists to be recomputed by a reader."""
    spec, record, path = _warden_fixture(tmp_path)
    target = json.loads(b64decode(record["calibration_set"]["body_base64"]))["cases"][0]

    def rewrite(shared):
        shared["cases"][0]["expected_classes"] = ["class-invented-after-the-fact"]

    _rewrite_calibration(record, rewrite)
    for seat in record["evaluator_calibration"]:
        for result in seat["calibration_results"]:
            if result["case_id"] == target["case_id"]:
                result["expected_classes"] = ["class-invented-after-the-fact"]
                result["predicted_classes"] = ["class-invented-after-the-fact"]
    path.write_text(json.dumps(record), encoding="utf-8")

    with pytest.raises(ValueError, match="published vendor class"):
        lock_inputs(spec, repo_root=tmp_path)


def test_a_seat_predicting_a_class_the_vendor_never_published_is_refused(tmp_path):
    """A prediction is scored against the vendor's vocabulary too. A seat that answers
    outside it is not a seat with a low score; it answered a different question."""
    spec, record, path = _warden_fixture(tmp_path)
    record["evaluator_calibration"][0]["calibration_results"][0][
        "predicted_classes"
    ] = ["class-invented-after-the-fact"]
    path.write_text(json.dumps(record), encoding="utf-8")

    with pytest.raises(ValueError, match="published vendor class"):
        lock_inputs(spec, repo_root=tmp_path)


def test_two_seats_reporting_one_session_are_refused(tmp_path):
    """Two seats are two observations only if they were two runs. One session id reported
    twice is a single run counted twice, and the roster's second seat attests nothing."""
    spec, record, path = _warden_fixture(tmp_path)
    seats = record["evaluator_calibration"]
    seats[1]["session_id"] = seats[0]["session_id"]
    path.write_text(json.dumps(record), encoding="utf-8")

    with pytest.raises(ValueError, match="distinct session"):
        lock_inputs(spec, repo_root=tmp_path)


def test_malformed_token_addresses_cannot_pass_by_matching_empty_strings():
    """Missing addresses once normalized to the same empty string. A malformed source
    is invalid input, not an ordinary not-on-the-allowlist exclusion."""
    with pytest.raises(ValueError, match="needs a 20-byte address"):
        spec_module._token_allowlist(
            {"tokens": [{"chainId": 56}]}, "test token-list source"
        )

    malformed_pool = {
        "token0": {},
        "token1": {"id": f"0x{1:040x}"},
        "tvlUSD": "10000",
        "volumeUSD24h": "1",
        "feeUSD24h": "1",
        "protocolFeeUSD24h": "0",
    }
    with pytest.raises(ValueError, match="invalid token0 id"):
        spec_module._yield_first_failed_gate(malformed_pool, {"", f"0x{1:040x}"})

    malformed_pool["token0"] = {"id": f"0x{2:040x}"}
    malformed_pool["token1"] = {}
    with pytest.raises(ValueError, match="invalid token1 id"):
        spec_module._yield_first_failed_gate(malformed_pool, {f"0x{1:040x}"})

    malformed_pool["token1"] = {"id": f"0x{1:040x}"}
    assert (
        spec_module._yield_first_failed_gate(malformed_pool, {f"0x{1:040x}"})
        == "token0_allowlist"
    )


def test_a_late_source_snapshot_cannot_slide_under_a_registered_attempt():
    """The stage-one schedule permits only three fixed capture windows; an arbitrary
    later timestamp requires a new protocol rather than a self-consistent input hash."""
    raw = b"[]"
    with pytest.raises(ValueError, match="outside its registered capture attempt"):
        spec_module._validate_source_snapshot(
            {
                "url": "https://explorer.pancakeswap.com/api/cached/pools/v3/bsc/list/top",
                "observed_at": "2026-08-26T13:00:00Z",
                "attempt_ordinal": 1,
                "sha256": hashlib.sha256(raw).hexdigest(),
                "body_base64": b64encode(raw).decode(),
            },
            "pools",
        )


def test_a_snapshot_from_the_superseded_yield_moment_is_refused():
    raw = b"[]"
    with pytest.raises(ValueError, match="outside its registered capture attempt"):
        spec_module._validate_source_snapshot(
            {
                "url": "https://explorer.pancakeswap.com/api/cached/pools/v3/bsc/list/top",
                "observed_at": "2026-08-21T12:00:01Z",
                "attempt_ordinal": 1,
                "sha256": hashlib.sha256(raw).hexdigest(),
                "body_base64": b64encode(raw).decode(),
            },
            "pools",
        )


def test_registered_families_refuse_a_generic_envelope_without_their_truth_schema(
    tmp_path,
):
    """The four claims need family truth artifacts; planned case ids alone cannot
    establish a Range position, a complete Yield partition, or Warden security labels."""
    expected = {
        "v3-01-range-doctor": "selection_manifest",
        "v3-02-yield-router": "pools and token_list snapshots",
        "v3-03-warden-security": "vendor_snapshot",
        "v3-04-warden-security": "vendor_snapshot",
    }
    for path in REGISTERED:
        spec = load(path)
        input_path = tmp_path / spec.inputs_ref
        input_path.parent.mkdir(parents=True, exist_ok=True)
        input_path.write_text(json.dumps(_input_record(spec)), encoding="utf-8")
        with pytest.raises(ValueError, match=expected[spec.spec_id]):
            lock_inputs(spec, repo_root=tmp_path)


def test_each_family_schema_accepts_only_a_complete_synthetic_input_artifact(tmp_path):
    """Temporary fixtures exercise all three positive validation paths without creating,
    selecting or locking any official v3 input artifact in the repository."""
    range_spec = load(SPECS_DIR / "v3-01-range-doctor.json")
    range_tokens = [f"0x{number:040x}" for number in (101, 102)]
    good_pool = f"0x{201:040x}"
    bad_pool = f"0x{202:040x}"
    range_pool_rows = [
        {
            "id": good_pool,
            "token0": {"id": range_tokens[0]},
            "token1": {"id": range_tokens[1]},
            "tvlUSD": "36500",
            "volumeUSD24h": "1000",
            "feeUSD24h": "20",
            "protocolFeeUSD24h": "10",
        },
        {
            "id": bad_pool,
            "token0": {"id": f"0x{999:040x}"},
            "token1": {"id": range_tokens[1]},
            "tvlUSD": "36500",
            "volumeUSD24h": "1000",
            "feeUSD24h": "20",
            "protocolFeeUSD24h": "10",
        },
    ]
    range_pools_body = json.dumps(range_pool_rows).encode()
    range_tokens_body = json.dumps(
        {"tokens": [{"chainId": 56, "address": address} for address in range_tokens]}
    ).encode()
    range_pool_truth = {
        "source_snapshots": {
            "pools": {
                "url": "https://explorer.pancakeswap.com/api/cached/pools/v3/bsc/list/top",
                "observed_at": "2026-08-21T12:00:01Z",
                "attempt_ordinal": 1,
                "sha256": hashlib.sha256(range_pools_body).hexdigest(),
                "body_base64": b64encode(range_pools_body).decode(),
            },
            "token_list": {
                "url": "https://tokens.pancakeswap.finance/pancakeswap-extended.json",
                "observed_at": "2026-08-21T12:00:02Z",
                "attempt_ordinal": 1,
                "sha256": hashlib.sha256(range_tokens_body).hexdigest(),
                "body_base64": b64encode(range_tokens_body).decode(),
            },
        }
    }
    range_pool_source = _source_ref(
        tmp_path,
        "evidence/range-pool-truth.json",
        json.dumps(range_pool_truth).encode(),
    ) | {"kind": "pool_truth"}
    range_cases = []
    states = {
        1: ("in_range", 0, True),
        2: ("above_range", 20, True),
        3: ("below_range", -20, True),
        4: ("in_range", 0, False),
        5: ("in_range", 0, True),
    }
    manager = "0x46A15B0b27311cedF172AB29E4f4766fbE7F4364"
    in_range_ids = sorted(
        (1, 5),
        key=lambda token_id: hashlib.sha256(
            f"{range_spec.stage_one_protocol_hash}56{manager.lower()}{token_id}".encode()
        ).hexdigest(),
    )
    token_by_stratum = {1: in_range_ids[0], 2: 2, 3: 3, 4: 4, 5: in_range_ids[1]}
    for stratum, (status, current_tick, gate_passes) in states.items():
        token_id = token_by_stratum[stratum]
        range_cases.append(
            {
                "case_id": f"range-{stratum}",
                "selection_stratum": stratum,
                "chain_id": 56,
                "position_manager": manager,
                "wallet": f"0x{token_id:040x}",
                "token_id": token_id,
                "observation_block": 123,
                "observation_time": "2026-08-21T12:00:00Z",
                "declared_position_value_usd": 10000,
                "estimated_recenter_cost_usd": 25,
                "decision_horizon_days": 30,
                "source_refs": [],
                "truth": {
                    "range_status": status,
                    "liquidity": 1,
                    "pool_gate_passes": gate_passes,
                    "first_failed_gate": None if gate_passes else "token0_allowlist",
                    "current_tick": current_tick,
                    "tick_lower": -10,
                    "tick_upper": 10,
                    "fee_usd_24h": 20.0,
                    "protocol_fee_usd_24h": 10.0,
                    "tvl_usd": 36500.0,
                    "gross_apr": 0.2 if gate_passes else None,
                    "net_apr": 0.1 if gate_passes else None,
                    "annual_gross_usd": 2000 if gate_passes else None,
                    "annual_net_usd": 1000 if gate_passes else None,
                    "annual_overstatement_usd": 1000 if gate_passes else None,
                    "cost_only_break_even_days": 9.125 if gate_passes else None,
                    "positions_held": 1,
                    "positions_examined": 1,
                    "closed_skipped": 0,
                    "scan_complete": True,
                },
            }
        )
    range_input = tmp_path / range_spec.inputs_ref
    range_input.parent.mkdir(parents=True, exist_ok=True)
    transfer_source_body = {
        "from_block": 0,
        "to_block": 123,
        "selected_block": {
            "number": 123,
            "timestamp": "2026-08-21T12:00:00Z",
        },
        "predecessor_block": {
            "number": 122,
            "timestamp": "2026-08-21T11:59:59Z",
        },
        "latest_finalized_block": 123,
        "contracts": [
            manager,
            "0x556B9306565093C855AEA9AE92A594704c2Cd59e",
        ],
        "complete": True,
        "logs": [
            {
                "contract": manager,
                "block_number": 100 + number,
                "transaction_hash": f"0x{number + 1:064x}",
                "log_index": number,
                "topics": [
                    "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef",
                    "0x" + "0" * 64,
                    "0x" + "0" * 24 + case["wallet"][2:],
                    f"0x{case['token_id']:064x}",
                ],
            }
            for number, case in enumerate(range_cases)
        ],
    }
    transfer_source = _source_ref(
        tmp_path,
        "evidence/range-transfer-logs.json",
        json.dumps(transfer_source_body).encode(),
    ) | {"kind": "transfer_logs"}
    enumeration_source_body = {
        "observation_block": 123,
        "observation_time": "2026-08-21T12:00:00Z",
        "complete": True,
        "wallet_scans": [
            {
                "wallet": case["wallet"],
                "positions_held": 1,
                "positions_examined": 1,
                "closed_skipped": 0,
                "scan_complete": True,
                "positions": [
                    {
                        "position_manager": manager,
                        "token_id": case["token_id"],
                        "pool_id": bad_pool
                        if case["selection_stratum"] == 4
                        else good_pool,
                        "liquidity": 1,
                        "current_tick": case["truth"]["current_tick"],
                        "tick_lower": -10,
                        "tick_upper": 10,
                    }
                ],
            }
            for case in range_cases
        ],
    }
    enumeration_source = _source_ref(
        tmp_path,
        "evidence/range-position-enumeration.json",
        json.dumps(enumeration_source_body).encode(),
    ) | {"kind": "position_enumeration"}
    selection_manifest = {
        "candidate_wallets": [case["wallet"] for case in range_cases],
        "eligible_positions": [
            {
                "position_manager": case["position_manager"],
                "wallet": case["wallet"],
                "token_id": case["token_id"],
                "range_status": case["truth"]["range_status"],
                "liquidity": case["truth"]["liquidity"],
                "pool_gate_passes": case["truth"]["pool_gate_passes"],
            }
            for case in range_cases
        ],
        # None of the synthetic wallets or token ids is party-controlled, so the derived
        # conflict set is empty and the manifest must say so rather than omit the field.
        "conflict_exclusions": [],
        "source_refs": [transfer_source, enumeration_source, range_pool_source],
    }
    for case in range_cases:
        case["source_refs"] = selection_manifest["source_refs"]
    range_input.write_text(
        json.dumps(
            _input_record(range_spec)
            | {"selection_manifest": selection_manifest, "cases": range_cases}
        ),
        encoding="utf-8",
    )
    locked_range = lock_inputs(range_spec, repo_root=tmp_path)
    assert_runnable(locked_range, repo_root=tmp_path)
    (tmp_path / range_pool_source["ref"]).write_bytes(b'{"changed":true}\n')
    with pytest.raises(ValueError, match="source does not match its digest"):
        assert_runnable(locked_range, repo_root=tmp_path)
    malformed_transfer_body = json.loads(json.dumps(transfer_source_body))
    malformed_transfer_body["logs"][0]["topics"][2] = (
        "0x" + "f" * 24 + range_cases[0]["wallet"][2:]
    )
    malformed_transfer = _source_ref(
        tmp_path,
        "evidence/range-malformed-transfer.json",
        json.dumps(malformed_transfer_body).encode(),
    ) | {"kind": "transfer_logs"}
    malformed_manifest = json.loads(json.dumps(selection_manifest))
    malformed_manifest["source_refs"][0] = malformed_transfer
    malformed_cases = json.loads(json.dumps(range_cases))
    for case in malformed_cases:
        case["source_refs"] = malformed_manifest["source_refs"]
    range_input.write_text(
        json.dumps(
            _input_record(range_spec)
            | {"selection_manifest": malformed_manifest, "cases": malformed_cases}
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="transfer log is malformed"):
        lock_inputs(range_spec, repo_root=tmp_path)

    irrelevant_transfer = _source_ref(
        tmp_path, "evidence/range-irrelevant.json", b'{"frozen":true}\n'
    ) | {"kind": "transfer_logs"}
    invalid_manifest = json.loads(json.dumps(selection_manifest))
    invalid_manifest["source_refs"][0] = irrelevant_transfer
    invalid_cases = json.loads(json.dumps(range_cases))
    for case in invalid_cases:
        case["source_refs"] = invalid_manifest["source_refs"]
    range_input.write_text(
        json.dumps(
            _input_record(range_spec)
            | {"selection_manifest": invalid_manifest, "cases": invalid_cases}
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="transfer-log source is missing"):
        lock_inputs(range_spec, repo_root=tmp_path)

    yield_spec = load(SPECS_DIR / "v3-02-yield-router.json")
    pool_ids = [f"0x{number:040x}" for number in range(1, 7)]
    token_addresses = [f"0x{number:040x}" for number in range(101, 103)]
    pool_rows = [
        {
            "id": pool_id,
            "token0": {"id": token_addresses[0]},
            "token1": {"id": token_addresses[1]},
            "tvlUSD": "1000000",
            "volumeUSD24h": "100000",
            "feeUSD24h": str(100 + number),
            "protocolFeeUSD24h": "25",
        }
        for number, pool_id in enumerate(pool_ids)
    ]
    selected = sorted(
        pool_ids,
        key=lambda pool_id: hashlib.sha256(
            f"{yield_spec.stage_one_protocol_hash}{pool_id.lower()}".encode()
        ).hexdigest(),
    )[:5]
    pools_source = json.dumps(pool_rows).encode()
    tokens_source = json.dumps(
        {"tokens": [{"chainId": 56, "address": address} for address in token_addresses]}
    ).encode()
    net_rates = {
        row["id"]: (float(row["feeUSD24h"]) - float(row["protocolFeeUSD24h"]))
        * 365
        / float(row["tvlUSD"])
        for row in pool_rows
    }
    best_pool = pool_ids[-1]
    yield_cases = []
    for number, pool_id in enumerate(selected):
        extra_per_day = 10000 * (net_rates[best_pool] - net_rates[pool_id]) / 365
        days_to_recover = 25 / extra_per_day if extra_per_day > 0 else None
        yield_cases.append(
            {
                "case_id": f"yield-{number + 1}",
                "pool_id": pool_id,
                "position_value_usd": 10000,
                "switching_cost_usd": 25,
                "decision_horizon_days": 30,
                "truth": {
                    "current_net_apr": net_rates[pool_id],
                    "destination_pool_id": best_pool if extra_per_day > 0 else None,
                    "destination_net_apr": (
                        net_rates[best_pool] if extra_per_day > 0 else None
                    ),
                    "extra_usd_per_day": extra_per_day,
                    "days_to_recover": days_to_recover,
                    "decision": "MOVE"
                    if days_to_recover is not None and days_to_recover <= 30
                    else "STAY",
                },
            }
        )
    yield_record = _input_record(yield_spec) | {
        "capture_log": [
            {
                "attempt_ordinal": 1,
                "scheduled_at": "2026-08-26T12:00:00Z",
                "pools_status": 200,
                "token_list_status": 200,
            }
        ],
        "source_snapshots": {
            "pools": {
                "url": "https://explorer.pancakeswap.com/api/cached/pools/v3/bsc/list/top",
                "observed_at": "2026-08-26T12:00:01Z",
                "attempt_ordinal": 1,
                "sha256": hashlib.sha256(pools_source).hexdigest(),
                "body_base64": b64encode(pools_source).decode(),
            },
            "token_list": {
                "url": "https://tokens.pancakeswap.finance/pancakeswap-extended.json",
                "observed_at": "2026-08-26T12:00:02Z",
                "attempt_ordinal": 1,
                "sha256": hashlib.sha256(tokens_source).hexdigest(),
                "body_base64": b64encode(tokens_source).decode(),
            },
        },
        "truth_manifest": {
            "raw_pool_ids": pool_ids,
            "included_pool_ids": pool_ids,
            "excluded": [],
        },
        "cases": yield_cases,
    }
    yield_input = tmp_path / yield_spec.inputs_ref
    yield_input.parent.mkdir(parents=True, exist_ok=True)
    yield_input.write_text(json.dumps(yield_record), encoding="utf-8")
    assert_runnable(lock_inputs(yield_spec, repo_root=tmp_path), repo_root=tmp_path)

    warden_spec = load(SPECS_DIR / "v3-03-warden-security.json")
    vendor = _source_ref(
        tmp_path,
        "evidence/vendor.json",
        b'{"classes":["class-0","class-1","class-2","class-3"]}\n',
    )
    warden_cases = []
    for number in range(12):
        hostile = number < 8
        critical = number < 2
        label = f"class-{number % 4}"
        evidence = {"label": label, "start": 0, "end": 7}
        warden_cases.append(
            {
                "case_id": f"warden-{number + 1}",
                "payload_id": f"payload-{number + 1}",
                "text": f"payload {number + 1}",
                "expected_verdict": "BLOCK" if hostile else "ALLOW",
                "labels": [label] if hostile else [],
                "evidence_spans": [evidence] if hostile else [],
                "hostile": hostile,
                "critical": critical,
                "survival_predicates": (
                    [
                        {
                            "kind": "literal",
                            "pattern": "payload",
                            "label": label,
                            "evidence_start": 0,
                            "evidence_end": 7,
                        }
                    ]
                    if critical
                    else []
                ),
            }
        )
    warden_record = _input_record(warden_spec) | {
        "vendor_snapshot": vendor,
        "cases": warden_cases,
    }
    warden_input = tmp_path / warden_spec.inputs_ref
    warden_input.parent.mkdir(parents=True, exist_ok=True)
    warden_input.write_text(json.dumps(warden_record), encoding="utf-8")
    assert_runnable(lock_inputs(warden_spec, repo_root=tmp_path), repo_root=tmp_path)

    overlap_record = json.loads(json.dumps(warden_record))
    shared_calibration = json.loads(
        b64decode(overlap_record["calibration_set"]["body_base64"])
    )
    shared_calibration["cases"][0]["input"]["payload"] = warden_cases[0]["text"]
    overlap_body = json.dumps(shared_calibration, sort_keys=True).encode()
    overlap_record["calibration_set"] = {
        "sha256": hashlib.sha256(overlap_body).hexdigest(),
        "body_base64": b64encode(overlap_body).decode(),
    }
    warden_input.write_text(json.dumps(overlap_record), encoding="utf-8")
    with pytest.raises(ValueError, match="overlap the held-out set"):
        lock_inputs(warden_spec, repo_root=tmp_path)

    fragment_record = json.loads(json.dumps(warden_record))
    fragment_record["cases"][0]["survival_predicates"][0]["pattern"] = "pay"
    warden_input.write_text(json.dumps(fragment_record), encoding="utf-8")
    with pytest.raises(ValueError, match="does not match its source evidence"):
        lock_inputs(warden_spec, repo_root=tmp_path)

    invalid_truth_record = json.loads(json.dumps(warden_record))
    invalid_truth_record["cases"][0]["expected_verdict"] = "REWRITE"
    warden_input.write_text(json.dumps(invalid_truth_record), encoding="utf-8")
    with pytest.raises(ValueError, match="expected_verdict is invalid"):
        lock_inputs(warden_spec, repo_root=tmp_path)


def test_changing_only_input_whitespace_breaks_the_lock(tmp_path):
    spec_path = tmp_path / "spec.json"
    stage_one = PairedSpec(**_valid())
    record = _input_record(stage_one)
    path = _write_inputs(
        tmp_path,
        stage_one,
        (json.dumps(record, separators=(",", ":")) + "\n").encode(),
    )
    save(stage_one, spec_path, repo_root=tmp_path)
    locked = lock_inputs(stage_one, repo_root=tmp_path)
    save(locked, spec_path, repo_root=tmp_path)

    path.write_bytes((json.dumps(record, indent=2) + "\n").encode())
    with pytest.raises(ValueError, match="digest mismatch"):
        assert_runnable(locked, repo_root=tmp_path)
    with pytest.raises(ValueError, match="digest mismatch"):
        load(spec_path, repo_root=tmp_path)


def test_locking_inputs_preserves_stage_one_identity_and_changes_composite_identity(
    tmp_path,
):
    stage_one = PairedSpec(**_valid())
    _write_inputs(tmp_path, stage_one)
    locked = lock_inputs(stage_one, repo_root=tmp_path)

    assert locked.stage_one_protocol_hash == stage_one.stage_one_protocol_hash
    assert locked.spec_hash != stage_one.spec_hash


def test_stage_two_cannot_appear_at_a_path_without_a_saved_stage_one(tmp_path):
    """A stable hash in one file does not establish that git saw the protocol first.
    Saving a lock therefore requires the stage-one record at that same path."""
    stage_one = PairedSpec(**_valid())
    _write_inputs(tmp_path, stage_one)
    locked = lock_inputs(stage_one, repo_root=tmp_path)

    with pytest.raises(ValueError, match="must update its saved stage-one record"):
        save(locked, tmp_path / "brand-new-locked.json", repo_root=tmp_path)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("claim", "a more flattering claim"),
        ("stopping_rule", "stop when the result looks good"),
        ("inputs_ref", "docket/advantage/v3/inputs/other.json"),
    ],
)
def test_stage_two_may_change_only_the_input_digest(tmp_path, field, value):
    spec_path = tmp_path / "spec.json"
    stage_one = PairedSpec(**_valid())
    _write_inputs(tmp_path, stage_one)
    save(stage_one, spec_path, repo_root=tmp_path)
    locked = lock_inputs(stage_one, repo_root=tmp_path)
    changed = _valid(inputs_sha256=locked.inputs_sha256) | {field: value}

    with pytest.raises(ValueError, match="stage two may change only inputs_sha256"):
        save(PairedSpec(**changed), spec_path, repo_root=tmp_path)


def test_stage_two_cannot_rewrite_the_registered_rubric(tmp_path):
    spec_path = tmp_path / "spec.json"
    stage_one = PairedSpec(**_valid())
    _write_inputs(tmp_path, stage_one)
    save(stage_one, spec_path, repo_root=tmp_path)
    locked = lock_inputs(stage_one, repo_root=tmp_path)
    rubric = _valid()["quality_rubric"]
    rubric["criteria"][0]["score_3_means"] = "whatever the output happened to do"
    changed = PairedSpec(
        **_valid(inputs_sha256=locked.inputs_sha256, quality_rubric=rubric)
    )

    with pytest.raises(ValueError, match="stage two may change only inputs_sha256"):
        save(changed, spec_path, repo_root=tmp_path)


def test_a_locked_record_cannot_be_rewritten_after_the_transition(tmp_path):
    spec_path = tmp_path / "spec.json"
    stage_one = PairedSpec(**_valid())
    _write_inputs(tmp_path, stage_one)
    save(stage_one, spec_path, repo_root=tmp_path)
    locked = lock_inputs(stage_one, repo_root=tmp_path)
    save(locked, spec_path, repo_root=tmp_path)

    edited = PairedSpec(**_valid(inputs_sha256=locked.inputs_sha256, claim="edited"))
    with pytest.raises(ValueError, match="already input-locked"):
        save(edited, spec_path, repo_root=tmp_path)


def test_missing_traversing_and_directory_input_references_fail_closed(tmp_path):
    missing = PairedSpec(**_valid())
    with pytest.raises(ValueError, match="missing inputs"):
        lock_inputs(missing, repo_root=tmp_path)
    with pytest.raises(ValueError, match="repository-relative"):
        PairedSpec(**_valid(inputs_ref="../outside.json"))

    directory = tmp_path / INPUT_REF
    directory.mkdir(parents=True)
    with pytest.raises(ValueError, match="is not a file"):
        lock_inputs(PairedSpec(**_valid()), repo_root=tmp_path)


# --------------------------------------------------------- round trip and tamper


def test_stage_one_and_composite_hash_tampering_are_refused(tmp_path):
    path = tmp_path / "s.json"
    save(PairedSpec(**_valid()), path, repo_root=tmp_path)
    record = json.loads(path.read_text(encoding="utf-8"))
    record["stage_one_protocol_hash"] = "0x" + "0" * 64
    path.write_text(json.dumps(record), encoding="utf-8")
    with pytest.raises(ValueError, match="stage-one protocol digest"):
        load(path, repo_root=tmp_path)

    composite_path = tmp_path / "composite.json"
    save(PairedSpec(**_valid()), composite_path, repo_root=tmp_path)
    record = json.loads(composite_path.read_text(encoding="utf-8"))
    record["spec_hash"] = "0x" + "0" * 64
    composite_path.write_text(json.dumps(record), encoding="utf-8")
    with pytest.raises(ValueError, match="composite digest"):
        load(composite_path, repo_root=tmp_path)


def test_save_and_load_round_trip_to_the_same_two_digests(tmp_path):
    spec = PairedSpec(**_valid())
    path = tmp_path / "s.json"
    save(spec, path, repo_root=tmp_path)
    restored = load(path, repo_root=tmp_path)
    assert restored.stage_one_protocol_hash == spec.stage_one_protocol_hash
    assert restored.spec_hash == spec.spec_hash


# ------------------------------------------------- the three registered families


def test_all_four_families_are_registered_but_no_input_is_locked():
    """Repair precedes input selection. A registered family therefore carries the stable
    protocol identity but must still refuse to run until a later git-witnessed lock."""
    assert [p.stem for p in REGISTERED] == [
        "v3-01-range-doctor",
        "v3-02-yield-router",
        "v3-03-warden-security",
        "v3-04-warden-security",
    ]
    specs = [load(p) for p in REGISTERED]
    assert any(spec.category == "security" for spec in specs)
    for spec in specs:
        assert spec.n_planned >= 5
        assert spec.runnable is False
        assert spec.inputs_sha256 == ""
        assert not (ROOT / spec.inputs_ref).exists()
        with pytest.raises(ValueError, match="no locked inputs"):
            assert_runnable(spec)


def test_registered_protocol_hashes_are_independently_recomputable():
    for path in REGISTERED:
        record = json.loads(path.read_text(encoding="utf-8"))
        protocol = {
            key: value
            for key, value in record.items()
            if key not in {"inputs_sha256", "stage_one_protocol_hash", "spec_hash"}
        }
        assert canonical_hash(protocol) == record["stage_one_protocol_hash"]
        composite = {
            key: value
            for key, value in record.items()
            if key not in {"stage_one_protocol_hash", "spec_hash"}
        }
        assert canonical_hash(composite) == record["spec_hash"]


def test_registration_provenance_claims_only_what_git_can_witness():
    for spec in map(load, REGISTERED):
        provenance = spec.registration_provenance.lower()
        assert "git history" in provenance
        assert "first commit" in provenance
        assert "no independently attested" in provenance
        assert "wall-clock" in provenance


def test_each_family_is_legibly_a_correction_before_input_lock():
    """`protocol_correction` carries only the immediate predecessor, so the whole chain is
    written down here rather than lost.

    First correction: the bundles withheld truth despite exact anchors, and the runner did
    not own scheduling. Second: the evaluator seats were named after specific models, the
    working assignment changed, and a seat id asserting a build that did not answer in it
    is a false record. Range later excluded the experiment party's live position from its
    on-chain population, and Yield later recommitted its registered moment after the first
    capture failed without locking inputs.

    The digests below are written without their `0x` prefix and joined in code. They are
    SHA-256 protocol identities, but bare `0x`-plus-64-hex is also the shape of a private
    key, and the repository blocks that pattern rather than asking each time which it is.
    """
    # The complete chain per family, oldest first. Recording only the origin and the
    # immediate predecessor lost a link the moment Range was corrected a third time: the
    # hash between them stopped appearing anywhere in the tree, recoverable only by the
    # git archaeology this test exists to make unnecessary.
    chains = {
        "v3-01-range-doctor": [
            "8f1510c01610b6b77d6ab80add73e740b64b2d0f73ca8fd3ad6a33a0744f888d",
            "6f72298498a43b840f82da1802fe2e5a44586d46e75c4ce5d7cf7fe249764cac",
            "dfbd387a3e7fc54e45aee6c437bffc5acab985a5d9e2be68b5fe5f0b95d39abf",
            "c49c7dd8bec5dcd7d625657e0c2ee0c2968b30aa1550092a25ba6598a0a60a1a",
            "361f830f06518511dfc45c8ec9bd49474e6c370dd8d0c29a6f16becb6d22ef74",
        ],
        "v3-02-yield-router": [
            "49ad6b20381fb72ec20600b283203d5aee399406c6a7314eadac6eefe2b6c730",
            "a90a364ed2e8df21e189b292c49b53294bbd653ec7b56e02457c663286d2825f",
            "52930b5854db990fbde1fe2f66e63b1f1ab0b396b07f6f0a07eab9833840d7a7",
        ],
        "v3-03-warden-security": [
            "ed5bbe50edb9ff8675f5d6e11a82a41f6019e94b8f75f6813932f1ba792a5bda",
            "38953631ae932a439e7d824a689aea58c465bd9a92fb8f635295ee79e6ea5bbc",
        ],
        "v3-04-warden-security": [
            "ed5bbe50edb9ff8675f5d6e11a82a41f6019e94b8f75f6813932f1ba792a5bda",
            "38953631ae932a439e7d824a689aea58c465bd9a92fb8f635295ee79e6ea5bbc",
            "cd4c698f55c316fdedaa2eb52d80091c3a08d004175d7d156527f224c4e941eb",
        ],
    }
    # What each family's most recent correction was actually about.
    subject = {
        "v3-01-range-doctor": "false statement",
        "v3-02-yield-router": "registered source capture",
        "v3-03-warden-security": "seat",
        "v3-04-warden-security": "distinct post-pilot",
    }
    for spec in map(load, REGISTERED):
        correction = spec.protocol_correction
        assert correction["status"] == "corrected_before_input_lock"
        chain = chains[spec.spec_id]
        assert correction["supersedes_stage_one_protocol_hash"] == "0x" + chain[-1]
        # A correction has to say what changed and why, not merely that something did.
        assert len(correction["reason"]) > 200
        assert subject[spec.spec_id] in correction["reason"].lower()
        # At least two deep, every link distinct, and none of them the current identity.
        assert len(chain) >= 2
        assert len(set(chain)) == len(chain)
        assert spec.stage_one_protocol_hash not in {"0x" + link for link in chain}
        # Only legitimate before a lock. After one it would be a protocol swapped out from
        # under evidence already frozen against it.
        assert spec.inputs_sha256 == ""


def test_every_family_registers_objective_anchors_disclosed_model_seats_and_timing():
    """The seats are two models run by one operator, not independent evaluators; the
    published keys and sheets make their scoring checkable without that stronger claim."""
    for spec in map(load, REGISTERED):
        assert spec.speed_threshold["minimum_median_seconds_saved"] == 30.0
        assert spec.speed_threshold["maximum_median_agent_to_manual_ratio"] == 0.5
        assert spec.speed_threshold["requires_complete_pairs"] is True
        # Model-neutral by registration. The seats were once named after specific models,
        # and the working assignment changed — leaving a seat id asserting a build that did
        # not answer in it. The identity of the answering build is carried by `model_build`
        # and `session_id` in the calibration record, which is evidence rather than a label.
        assert [row["evaluator_id"] for row in spec.scoring["evaluator_roster"]] == [
            "seat-a",
            "seat-b",
        ]
        assert all(
            set(row) == {"evaluator_id"} for row in spec.scoring["evaluator_roster"]
        )
        assert "one operator" in spec.scoring["selection_rule"].lower()
        assert "not independent" in spec.scoring["selection_rule"].lower()
        assert "never pauses" in spec.timing["interruptions"]
        assert "cannot start, stop" in spec.timing["operator_control"]
        for criterion in spec.quality_rubric["criteria"]:
            assert all(
                criterion[f"score_{score}_means"].strip() for score in (3, 2, 1, 0)
            )


def test_range_pairs_the_exact_position_and_scores_dollar_correctness():
    spec = load(SPECS_DIR / "v3-01-range-doctor.json")
    procedure = spec.arms["agent"]["what_it_does"]
    assert "token_id" in procedure and "observation_block" in procedure
    assert "2026-08-21T12:00:00Z" in spec.case_selection["chosen_by"]
    economics = next(
        row
        for row in spec.quality_rubric["criteria"]
        if row["name"] == "economic_consequence"
    )
    assert "tolerance" in economics["score_3_means"]
    assert "wrong" in economics["score_0_means"]
    assert "estimated_recenter_cost_usd" in procedure
    assert "cost_only_break_even_days" in spec.case_selection["truth_source"]
    assert "removing each chosen token id" in spec.case_selection["rule"]
    assert "first failed gate" in spec.case_selection["truth_source"]


def test_yield_uses_a_complete_frozen_universe_and_probability_sample():
    spec = load(SPECS_DIR / "v3-02-yield-router.json")
    selection = spec.case_selection
    assert "top-pools response" in selection["population"]
    assert "SHA-256" in selection["truth_source"]
    assert "take the first five" in selection["rule"]
    assert "stage_one_protocol_hash" in selection["rule"]
    assert "2026-08-26T12:00:00Z" in selection["chosen_by"]
    assert any(
        row["name"] == "universe_complete_and_correct"
        for row in spec.quality_rubric["criteria"]
    )


def test_warden_defines_every_denominator_and_the_high_stakes_ship_gate():
    spec = load(SPECS_DIR / "v3-03-warden-security.json")
    combined = " ".join(
        [spec.claim, spec.falsifier, spec.failure_policy, spec.stopping_rule]
    ).lower()
    for term in (
        "precision",
        "recall",
        "frozen hostile",
        "successful scans",
        "12/12",
        "critical",
        "zero",
        "no scored retry",
    ):
        assert term in combined
    assert "either arm's precision is null" in spec.falsifier.lower()


# ------------------------------------------- the choices a runner must not make for itself


def test_the_runner_may_not_choose_which_arm_block_runs_first():
    """An operator who has seen the service's answer cannot produce an independent manual
    arm for the cases that follow. Registering only "manual first within a pair" would still
    allow that, so the whole manual block precedes the whole agent block, and the order is
    part of the protocol rather than a line in the runner."""
    protocol = _valid()["execution_protocol"]
    with pytest.raises(ValueError, match="arm_block_order must be"):
        PairedSpec(
            **_valid(
                execution_protocol=protocol
                | {"arm_block_order": "alternating_per_case"}
            )
        )


def test_the_runner_may_not_choose_the_blinding_polarity():
    """Even-means-agent is a free choice. Unregistered, it is settled by whichever code runs
    first, and "reproducible A/B" then means only "reproducible by that code"."""
    protocol = _valid()["execution_protocol"]
    with pytest.raises(ValueError, match="blinding_parity"):
        PairedSpec(**_valid(execution_protocol=protocol | {"blinding_parity": ""}))


def test_a_second_score_sheet_from_one_seat_is_refused_by_the_protocol():
    """A replacement sheet is a sheet whose first result was unwelcome."""
    protocol = _valid()["execution_protocol"]
    with pytest.raises(ValueError, match="one score sheet per seat"):
        PairedSpec(**_valid(execution_protocol=protocol | {"sheets_per_seat": 2}))


def test_every_execution_choice_must_be_registered_not_merely_present():
    for missing in sorted(spec_module.EXECUTION_FIELDS):
        protocol = dict(_valid()["execution_protocol"])
        protocol[missing] = ""
        with pytest.raises(ValueError, match="execution_protocol leaves"):
            PairedSpec(**_valid(execution_protocol=protocol))


def test_the_execution_protocol_is_covered_by_the_stage_one_hash():
    """If it were outside the protocol hash, amending it would leave the registration
    looking untouched — which is exactly the silent post-registration change the two-stage
    lock exists to make visible."""
    base = PairedSpec(**_valid())
    changed = PairedSpec(
        **_valid(
            execution_protocol=_valid()["execution_protocol"]
            | {"normalisation_version": "test.v2: a, b, c"}
        )
    )
    assert base.stage_one_protocol_hash != changed.stage_one_protocol_hash


def test_all_four_registered_families_fix_the_same_execution_protocol():
    """The four families differ in what they measure, not in how the evidence is produced.
    A per-family order or polarity would be a place for one family's result to be shaped."""
    protocols = [load(path).execution_protocol for path in REGISTERED]
    assert {p["arm_block_order"] for p in protocols} == {MANUAL_FIRST}
    assert {p["blinding_parity"] for p in protocols} == {"even_a_is_agent"}
    assert {int(p["sheets_per_seat"]) for p in protocols} == {1}
    # The projection is the one part that must differ: the families return different shapes.
    assert len({p["normalisation_version"] for p in protocols}) == 3
    for protocol in protocols:
        # The honest limit of prompt-level blinding travels with the registration.
        assert (
            "not cryptographically unguessable"
            in protocol["blinding_limitation"].lower()
        )
