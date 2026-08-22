"""The bridge from frozen bytes to a lockable envelope, checked against the real validator.

These tests deliberately do not restate the validator's rules. They build a capture, run it
through the bridge, and hand the result to `spec.lock_inputs` — the same function the Aug 26
lock will call. A test that mirrored the rules by hand would pass while the two drifted, and
the drift would surface on the one morning the capture cannot be repeated.
"""

import base64
import hashlib
import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from docket.advantage.v3 import assemble, calibration, calibration_driver, capture
from docket.hire.receipts import canonical_hash
from docket.advantage.v3.spec import (
    _computed_calibration_truth,
    assert_runnable,
    load,
    lock_inputs,
    save,
)

SPEC_PATH = (
    Path(__file__).resolve().parents[1]
    / "docket/advantage/v3/specs/v3-02-yield-router.json"
)
SPEC = load(SPEC_PATH)
SCHEDULED = datetime.fromisoformat(
    capture.registered_schedule(SPEC)["first_attempt_at"].replace("Z", "+00:00")
)

TOKENS = [f"0x{(i + 1):040x}" for i in range(8)]


def _token_list() -> dict:
    return {
        "tokens": [{"chainId": 56, "address": address} for address in TOKENS]
        # A non-BSC token must be ignored rather than admitted to the allowlist.
        + [{"chainId": 1, "address": f"0x{99:040x}"}]
    }


def _pool(index: int, *, tvl=1_000_000.0, fee=500.0, protocol_fee=100.0, volume=None):
    return {
        "id": f"0x{(0xAA00 + index):040x}",
        "token0": {"id": TOKENS[index % len(TOKENS)]},
        "token1": {"id": TOKENS[(index + 1) % len(TOKENS)]},
        "tvlUSD": tvl,
        "volumeUSD24h": volume if volume is not None else tvl / 10,
        "feeUSD24h": fee,
        "protocolFeeUSD24h": protocol_fee,
    }


def _pools_body() -> list:
    """Five pools that pass every gate, plus two that each fail a different one."""
    rows = [_pool(i, fee=400.0 + 60 * i) for i in range(5)]
    rows.append(_pool(5, tvl=5_000.0))  # below the 10k TVL floor
    rows.append(_pool(6, volume=999_000_000.0))  # over the turnover ceiling
    return rows


def _calibration_set() -> bytes:
    """Eight scenarios whose expected truth is computed by the validator's own function.

    Which scenarios to pose is authored; what the right answer is, is not. Hand-computing the
    expected block would restate the rule the calibration exists to check.
    """
    # The registration requires the eight to span eligibility and at least three distinct
    # gate outcomes: a calibration that only ever saw eligible pools would not show whether an
    # evaluator can recognise an excluded one.
    off_allowlist = _pool(7)
    off_allowlist["token0"] = {"id": f"0x{0xDEAD:040x}"}
    current_pools = [_pool(i, fee=300.0 + 40 * i) for i in range(5)] + [
        _pool(5, tvl=5_000.0),  # tvl_floor
        _pool(6, volume=999_000_000.0),  # turnover_ceiling
        off_allowlist,  # token0_allowlist
    ]
    cases = []
    for i in range(8):
        scenario = {
            "allowlist": TOKENS,
            "current_pool": current_pools[i],
            "destination_pool": _pool((i + 1) % 5, fee=700.0),
            "position_value_usd": 10000,
            "switching_cost_usd": 25,
            "decision_horizon_days": 30,
        }
        cases.append(
            {
                "case_id": f"cal-{i:02d}",
                "input": scenario,
                "expected": _computed_calibration_truth(SPEC.spec_id, scenario),
            }
        )
    body = {"spec_id": SPEC.spec_id, "cases": cases}
    return json.dumps(body, sort_keys=True).encode("utf-8")


def _capture_result() -> dict:
    """A capture that failed once and then succeeded, in the real record shape."""
    pools = json.dumps(_pools_body()).encode("utf-8")
    tokens = json.dumps(_token_list()).encode("utf-8")

    def attempt(urls, *, ordinal, scheduled_at):
        start = datetime.fromisoformat(scheduled_at.replace("Z", "+00:00"))
        ok = ordinal == 2
        return {
            "attempt_ordinal": ordinal,
            "scheduled_at": scheduled_at,
            "pools_observed_at": capture._stamp_at(start + timedelta(seconds=1)),
            "token_list_observed_at": capture._stamp_at(start + timedelta(seconds=2)),
            "pools_status": 200 if ok else 503,
            "token_list_status": 200,
            "transport_errors": [None, None],
            "succeeded": ok,
            "_bodies": (pools, tokens) if ok else None,
        }

    return capture.run_registered_capture(
        SPEC, now=SCHEDULED, sleep=lambda _s: None, attempt=attempt
    )


def _evaluator_calibration() -> list[dict]:
    """Both seats answering the shared eight, in the shape the registration demands.

    The answers are taken from the shared key because these tests are about the bridge, not
    about whether a model is any good — the real artifact records what the seats actually
    said, and the validator's seven-of-eight floor is what judges that.
    """
    shared = json.loads(_calibration_set().decode("utf-8"))["cases"]
    return [
        {
            "evaluator_id": seat["evaluator_id"],
            "model_build": "test-build",
            "session_id": f"session-{index}",
            "rubric_anchor_hash": canonical_hash(SPEC.quality_rubric["criteria"]),
            "calibration_results": [
                {
                    "case_id": case["case_id"],
                    "input": case["input"],
                    "expected": case["expected"],
                    "submitted": case["expected"],
                }
                for case in shared
            ],
        }
        for index, seat in enumerate(SPEC.scoring["evaluator_roster"])
    ]


def _calibration_capture(root: Path) -> Path:
    shared = json.loads(_calibration_set().decode("utf-8"))["cases"]
    for row in _evaluator_calibration():
        request = calibration.open_attempt(
            SPEC,
            root,
            evaluator_id=row["evaluator_id"],
            model_build=row["model_build"],
            session_id=row["session_id"],
            calibration_set=_calibration_set(),
        )
        answer = {
            "evaluator_id": row["evaluator_id"],
            "results": [
                {
                    "case_id": case["case_id"],
                    "submitted": case["expected"],
                }
                for case in shared
            ],
        }
        calibration.record_response(
            SPEC,
            root,
            evaluator_id=row["evaluator_id"],
            attempt_ordinal=request["attempt_ordinal"],
            raw_response=json.dumps(answer, sort_keys=True).encode("utf-8"),
        )
    return root


def _envelope(calibration_dir: Path) -> dict:
    return assemble.assemble_yield_envelope(
        SPEC,
        _capture_result(),
        calibration_dir=_calibration_capture(calibration_dir),
        calibration_set=_calibration_set(),
        evaluator_calibration=_evaluator_calibration(),
    )


def test_the_assembled_envelope_passes_the_real_input_lock(tmp_path):
    """The whole point. If this passes, the Aug 26 sequence works end to end; if it fails,
    it fails now, six days early, instead of on the morning with the bytes already frozen."""
    repo_root = _stage_repo(tmp_path, _envelope(tmp_path / "calibration"))
    spec = load(repo_root / "spec.json", repo_root=repo_root)
    locked = lock_inputs(spec, repo_root=repo_root)
    assert locked.runnable
    assert len(locked.inputs_sha256) == 64


def test_the_envelope_carries_the_capture_attempts_up_to_the_chosen_one(tmp_path):
    envelope = _envelope(tmp_path / "calibration")
    assert [a["attempt_ordinal"] for a in envelope["capture_log"]] == [1, 2]
    assert envelope["capture_log"][0]["pools_status"] == 503
    assert envelope["source_snapshots"]["pools"]["attempt_ordinal"] == 2


def test_the_embedded_bodies_are_the_captured_bytes_unchanged(tmp_path):
    """The lock hashes what the server sent. A re-encode would hash a different universe."""
    envelope = _envelope(tmp_path / "calibration")
    result = _capture_result()
    for name, index in (("pools", 0), ("token_list", 1)):
        snapshot = envelope["source_snapshots"][name]
        assert base64.b64decode(snapshot["body_base64"]) == result["_raw"][index]
        assert snapshot["sha256"] == hashlib.sha256(result["_raw"][index]).hexdigest()


def test_the_manifest_partitions_every_captured_pool_exactly_once(tmp_path):
    manifest = _envelope(tmp_path / "calibration")["truth_manifest"]
    excluded = [row["pool_id"] for row in manifest["excluded"]]
    assert set(manifest["included_pool_ids"]) | set(excluded) == set(
        manifest["raw_pool_ids"]
    )
    assert not set(manifest["included_pool_ids"]) & set(excluded)
    assert sorted(row["first_failed_gate"] for row in manifest["excluded"]) == [
        "turnover_ceiling",
        "tvl_floor",
    ]


def test_the_snapshot_urls_are_the_registered_constants(tmp_path):
    envelope = _envelope(tmp_path / "calibration")
    assert (
        envelope["source_snapshots"]["pools"]["url"]
        == "https://explorer.pancakeswap.com/api/cached/pools/v3/bsc/list/top"
    )


def test_an_incomplete_capture_cannot_be_assembled():
    """Three failures means recommit, not assemble from whatever is on disk."""
    failed = {"captured": False, "attempts": [], "why": "three failures"}
    with pytest.raises(assemble.AssemblyRefused, match="did not complete"):
        assemble.assemble_yield_envelope(
            SPEC,
            failed,
            calibration_dir=Path("unused"),
            calibration_set=_calibration_set(),
            evaluator_calibration=_evaluator_calibration(),
        )


def test_too_few_eligible_pools_is_refused_rather_than_padded(tmp_path):
    """A captured universe that cannot fill the registration is a real outcome. Padding it
    with gated-out pools would answer the registered question with unregistered data."""
    thin = _capture_result()
    thin["_raw"] = (
        json.dumps([_pool(i) for i in range(3)]).encode("utf-8"),
        thin["_raw"][1],
    )
    with pytest.raises(assemble.AssemblyRefused, match="cannot fill the registration"):
        assemble.assemble_yield_envelope(
            SPEC,
            thin,
            calibration_dir=tmp_path / "calibration",
            calibration_set=_calibration_set(),
            evaluator_calibration=_evaluator_calibration(),
        )


def test_existing_inputs_are_never_overwritten(tmp_path):
    """Overwriting frozen inputs is how a second capture quietly replaces the first."""
    envelope = _envelope(tmp_path / "calibration")
    repo_root = _stage_repo(tmp_path, envelope)
    spec = load(repo_root / "spec.json", repo_root=repo_root)
    with pytest.raises(assemble.AssemblyRefused, match="already exists"):
        assemble.write_envelope(spec, envelope, repo_root=repo_root)


def _stage_repo(tmp_path: Path, envelope: dict) -> Path:
    """A throwaway repo root holding the spec and its written envelope."""
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    save(SPEC, repo_root / "spec.json", repo_root=repo_root)
    spec = load(repo_root / "spec.json", repo_root=repo_root)
    assemble.write_envelope(spec, envelope, repo_root=repo_root)
    return repo_root


def test_a_written_capture_can_be_read_back_and_assembled(tmp_path):
    """Assembly happens later, from files. The round trip through disk must survive."""
    result = _capture_result()
    capture.write_capture(dict(result), tmp_path)
    reloaded = assemble.load_capture(tmp_path)
    assert reloaded["_raw"] == result["_raw"]
    envelope = assemble.assemble_yield_envelope(
        SPEC,
        reloaded,
        calibration_dir=_calibration_capture(tmp_path / "calibration"),
        calibration_set=_calibration_set(),
        evaluator_calibration=_evaluator_calibration(),
    )
    assert len(envelope["cases"]) == SPEC.n_planned


def test_cli_verifies_the_supplied_calibration_capture(tmp_path, monkeypatch):
    capture_dir = tmp_path / "capture"
    capture.write_capture(dict(_capture_result()), capture_dir)
    calibration_dir = _calibration_capture(tmp_path / "calibration")
    calibration_set = tmp_path / "calibration-set.json"
    calibration_set.write_bytes(_calibration_set())
    evaluator_calibration = tmp_path / "evaluator-calibration.json"
    evaluator_calibration.write_text(
        json.dumps(_evaluator_calibration()), encoding="utf-8"
    )
    written = []

    def record_write(_spec, envelope):
        written.append(envelope)
        return tmp_path / "inputs.json"

    monkeypatch.setattr(assemble, "write_envelope", record_write)

    code = assemble.main(
        [
            str(SPEC_PATH),
            str(capture_dir),
            str(calibration_set),
            str(evaluator_calibration),
            str(calibration_dir),
        ]
    )

    assert code == 0
    assert len(written) == 1


def test_an_uncaptured_calibration_edit_is_refused(tmp_path):
    calibration_dir = _calibration_capture(tmp_path / "calibration")
    edited = _evaluator_calibration()
    edited[0]["calibration_results"][0]["submitted"] = {"decision": "MOVE"}

    with pytest.raises(
        assemble.AssemblyRefused, match="differs from what the binding attempt"
    ):
        assemble.assemble_yield_envelope(
            SPEC,
            _capture_result(),
            calibration_dir=calibration_dir,
            calibration_set=_calibration_set(),
            evaluator_calibration=edited,
        )


def test_an_edited_body_is_refused_rather_than_assembled(tmp_path):
    """Without this check an edited body would be embedded, the lock would hash the edit, and
    every later verification would agree with it. The tampering would become the record."""
    capture.write_capture(dict(_capture_result()), tmp_path)
    (tmp_path / "pools.raw.json").write_bytes(b'[{"id":"0xdeadbeef"}]')
    with pytest.raises(assemble.AssemblyRefused, match="not the captured bytes"):
        assemble.load_capture(tmp_path)


def test_an_incomplete_written_capture_is_refused(tmp_path):
    capture.write_capture(
        {"captured": False, "attempts": [], "why": "three failures"}, tmp_path
    )
    with pytest.raises(assemble.AssemblyRefused, match="incomplete capture"):
        assemble.load_capture(tmp_path)


WARDEN_SPEC_PATH = (
    Path(__file__).resolve().parents[1]
    / "docket/advantage/v3/specs/v3-03-warden-security.json"
)
WARDEN_SPEC = load(WARDEN_SPEC_PATH)
WARDEN_SOURCE_DIR = Path(__file__).resolve().parents[1] / "docket/advantage/v3/sources"


def _stage_warden_lock(tmp_path: Path, monkeypatch) -> tuple[Path, Path, Path]:
    repo_root = tmp_path / "warden-repo"
    spec_path = repo_root / "docket/advantage/v3/specs/v3-03-warden-security.json"
    source_dir = repo_root / "docket/advantage/v3/sources"
    source_dir.mkdir(parents=True)
    save(WARDEN_SPEC, spec_path, repo_root=repo_root)
    for name in (
        "warden-heldout-cases.json",
        "warden-calibration-set.json",
        "warden-vendor-snapshot.json",
    ):
        (source_dir / name).write_bytes((WARDEN_SOURCE_DIR / name).read_bytes())

    calibration_set = (source_dir / "warden-calibration-set.json").read_bytes()
    shared = json.loads(calibration_set)["cases"]
    calibration_dir = repo_root / "calibration"
    for index, seat in enumerate(WARDEN_SPEC.scoring["evaluator_roster"]):
        evaluator_id = seat["evaluator_id"]

        def answer(_prompt, *, evaluator_id=evaluator_id):
            return json.dumps(
                {
                    "evaluator_id": evaluator_id,
                    "results": [
                        {
                            "case_id": case["case_id"],
                            "predicted_hostile": case["expected_hostile"],
                            "predicted_classes": case["expected_classes"],
                        }
                        for case in shared
                    ],
                },
                sort_keys=True,
            ).encode("utf-8")

        calibration_driver.run_seat(
            WARDEN_SPEC,
            calibration_dir,
            evaluator_id=evaluator_id,
            model_build=f"synthetic-build-{index}",
            session_id=f"synthetic-session-{index}",
            calibration_set=calibration_set,
            call_seat=answer,
        )
    monkeypatch.setattr(assemble, "REPO_ROOT", repo_root)
    return repo_root, spec_path, calibration_dir


def _warden_lock_args(repo_root: Path, spec_path: Path, calibration_dir: Path):
    source_dir = repo_root / "docket/advantage/v3/sources"
    return [
        "lock-warden",
        str(spec_path),
        str(source_dir / "warden-heldout-cases.json"),
        str(source_dir / "warden-vendor-snapshot.json"),
        str(source_dir / "warden-calibration-set.json"),
        str(calibration_dir),
    ]


def test_lock_warden_cli_builds_captured_inputs_and_saves_the_real_lock(
    tmp_path, monkeypatch
):
    repo_root, spec_path, calibration_dir = _stage_warden_lock(tmp_path, monkeypatch)

    code = assemble.main(_warden_lock_args(repo_root, spec_path, calibration_dir))

    assert code == 0
    input_path = repo_root / WARDEN_SPEC.inputs_ref
    assert input_path.is_file()
    locked = load(spec_path, repo_root=repo_root)
    assert len(locked.inputs_sha256) == 64
    assert locked.inputs_sha256 == hashlib.sha256(input_path.read_bytes()).hexdigest()
    assert_runnable(locked, repo_root=repo_root)


def test_lock_warden_refuses_before_writing_when_capture_verification_fails(
    tmp_path, monkeypatch
):
    repo_root, spec_path, calibration_dir = _stage_warden_lock(tmp_path, monkeypatch)

    def refuse(*_args, **_kwargs):
        raise ValueError("capture verification sentinel")

    monkeypatch.setattr(assemble, "verify_calibration_capture", refuse)

    code = assemble.main(_warden_lock_args(repo_root, spec_path, calibration_dir))

    assert code == 2
    assert not (repo_root / WARDEN_SPEC.inputs_ref).exists()
    assert load(spec_path, repo_root=repo_root).inputs_sha256 == ""
