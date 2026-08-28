import hashlib
import json
from pathlib import Path

import pytest

from docket.advantage.v3 import capture, rehearsal, runner, scoring
import docket.advantage.v3.spec as spec_module
from docket.advantage.v3.spec import (
    RANGE_CONTROLLED_TOKEN_IDS,
    RANGE_CONTROLLED_WALLETS,
    is_range_family,
    load,
    range_sample_indices,
)
from docket.hire.receipts import canonical_hash


ROOT = Path(__file__).resolve().parents[1]
SPECS = ROOT / "docket/advantage/v3/specs"
PREDECESSOR = SPECS / "v3-01-range-doctor.json"
SUCCESSOR = SPECS / "v3-05-range-doctor.json"
DRY_RUN = ROOT / "docs/deliberation/RANGE-REPLACEMENT-DRYRUN-2026-08-15.md"
FEASIBILITY = ROOT / "docket/advantage/v3/provenance/range-v3-05-feasibility.json"


def test_range_successor_is_distinct_disclosed_and_input_locked():
    predecessor_raw = PREDECESSOR.read_bytes()
    predecessor = load(PREDECESSOR)
    successor = load(SUCCESSOR)

    assert hashlib.sha256(predecessor_raw).hexdigest() == (
        "2146cbf9c7886f3d1059d496f0469d3fcff01aed1e18e5fb48813c7a4421826f"
    )
    assert predecessor_raw == PREDECESSOR.read_bytes()
    assert predecessor.stage_one_protocol_hash == (
        "0x5436fe80f16558d06f2f8f09f2eb4bbad6a2f3e26e5bbbbbafd143b7f14d2fce"
    )
    assert predecessor.inputs_sha256 == ""
    assert successor.spec_id == "v3-05-range-doctor"
    assert successor.inputs_sha256 == hashlib.sha256(
        (ROOT / successor.inputs_ref).read_bytes()
    ).hexdigest()
    assert successor.runnable
    assert is_range_family(successor)
    assert successor.n_planned == 3
    assert successor.protocol_correction["supersedes_stage_one_protocol_hash"] == (
        predecessor.stage_one_protocol_hash
    )
    provenance = successor.pilot_provenance
    assert provenance["prior_spec_id"] == predecessor.spec_id
    assert provenance["prior_stage_one_protocol_hash"] == (
        predecessor.stage_one_protocol_hash
    )
    assert provenance["original_registration_passed"] is False
    assert provenance["dry_run_preregistered_nothing"] is True
    evidence = provenance["evidence"]["range_replacement_dry_run"]
    assert evidence["ref"] == (
        "docs/deliberation/RANGE-REPLACEMENT-DRYRUN-2026-08-15.md"
    )
    assert evidence["sha256"] == hashlib.sha256(DRY_RUN.read_bytes()).hexdigest()
    feasibility = provenance["evidence"]["live_feasibility"]
    assert feasibility["ref"] == (
        "docket/advantage/v3/provenance/range-v3-05-feasibility.json"
    )
    assert feasibility["sha256"] == hashlib.sha256(FEASIBILITY.read_bytes()).hexdigest()
    feasibility_record = json.loads(FEASIBILITY.read_text(encoding="utf-8"))
    assert feasibility_record["measured_probe"] == {
        "getPool_calls": 2,
        "ownerOf_calls": 8,
        "positions_calls": 8,
        "slot0_calls": 2,
        "tokenByIndex_calls": 8,
        "totalSupply_calls": 2,
        "userPositionInfos_calls": 0,
    }
    assert (
        feasibility_record["separate_farm_probe"][
            "included_in_measured_elapsed_seconds"
        ]
        is False
    )
    assert feasibility_record["final_archive_recheck"] == {
        "at": "2026-08-24T17:45:14Z",
        "draft_stage_one_protocol_hash": (
            "0xf1e432fad8765f7e101d536253c38fb5813f07e8b0fd63099b6908bf929af3ae"
        ),
        "header_matched": True,
        "sampled_tokenByIndex_calls": 8,
        "scope": (
            "The eight indices came from this superseded draft hash. Recording this "
            "recheck changes the evidence digest and final stage-one hash; no indexed "
            "chain read is made after final recomputation."
        ),
        "totalSupply": 4_908_719,
    }
    frame_hash = successor.case_selection["frame_definition"]["observation_block_hash"]
    assert feasibility_record["header_probe"]["hash"] == frame_hash
    assert frame_hash == feasibility_record["observation_block_hash"]
    assert successor.case_selection["conflict_exclusion"] == {
        "excluded_reason": "experiment_party_controlled",
        "token_ids": sorted(RANGE_CONTROLLED_TOKEN_IDS),
        "wallets": sorted(RANGE_CONTROLLED_WALLETS),
    }


def test_range_successor_binds_the_frame_before_any_draw():
    spec = load(SUCCESSOR)
    frame = spec.case_selection["frame_definition"]

    assert spec.speed_threshold["formula"].startswith(
        "For the three valid complete pairs"
    )
    assert spec.speed_threshold["material_if"].startswith(
        "All three pairs have valid completed outputs"
    )
    assert spec.timing["timeout_seconds"] == 1200
    assert "timeout at 1,200 seconds" in spec.stopping_rule
    assert frame["version"] == "range.enumerable-1024.v1"
    assert frame["observation_block"] == 117841891
    assert frame["observation_block_hash"] == (
        "0x5881782f547a332f473be1d4b1279912799bc11d3955e1015a3d27a48320b9ff"
    )
    assert frame["observation_time"] == "2026-08-24T16:42:59Z"
    assert frame["sample_size"] == 1024
    assert frame["pool_truth_sources"] == spec_module.YIELD_SOURCE_URLS
    assert frame["source_methods"] == [
        "eth_blockNumber",
        "eth_getBlockByNumber",
        "totalSupply",
        "tokenByIndex",
        "ownerOf",
        "userPositionInfos_if_farm_held",
        "positions_if_conflict_free",
        "getPool_and_slot0_per_unique_live_pool",
    ]
    assert "eth_getLogs" not in frame["source_methods"]
    assert [row["name"] for row in frame["strata"]] == [
        "passing_gate_in_range",
        "passing_gate_out_of_range",
        "nonzero_liquidity_failed_gate",
    ]
    assert frame["selection_rule"] == {
        "digest": "SHA-256",
        "order": "ascending_digest",
        "preimage": (
            "UTF8(stage_one_protocol_hash || '|56|' || lowercase(position_manager) "
            "|| '|' || decimal(token_id) || '|' || stratum_name)"
        ),
        "take": "one_per_stratum",
    }
    assert capture.registered_schedule(spec) == {
        "first_attempt_at": "2026-08-26T12:10:00Z",
        "pools_url": spec_module.YIELD_SOURCE_URLS["pools"],
        "token_list_url": spec_module.YIELD_SOURCE_URLS["token_list"],
    }

    indices = range_sample_indices(spec, 4_908_719)
    assert [row["index"] for row in indices[:3]] == [4664798, 4178655, 2820423]
    assert len(indices) == 1024
    assert len({row["index"] for row in indices}) == 1024
    assert [row["sample_ordinal"] for row in indices] == list(range(1024))
    assert indices == range_sample_indices(spec, 4_908_719)

    collision_frame = range_sample_indices(spec, 1024)
    assert {row["index"] for row in collision_frame} == set(range(1024))
    assert any(
        row["derivation_counter"] != row["sample_ordinal"] for row in collision_frame
    )


def test_range_successor_is_registered_in_every_runtime_dispatch():
    spec = load(SUCCESSOR)

    assert spec.spec_id in scoring.FAMILY_PROTOCOLS
    assert scoring.FAMILY_PROTOCOLS[spec.spec_id]["family_salt"] == (
        "range-v5-blinding"
    )
    schedule = runner.registered_capture_schedule(spec)
    assert [
        slot.scheduled_at.isoformat().replace("+00:00", "Z") for slot in schedule
    ] == (spec.case_selection["frame_definition"]["pool_truth_capture_attempts"])


def test_range_successor_hashes_recompute_without_touching_the_predecessor():
    predecessor_bytes = PREDECESSOR.read_bytes()
    record = json.loads(SUCCESSOR.read_text(encoding="utf-8"))
    protocol = {
        key: value
        for key, value in record.items()
        if key not in {"inputs_sha256", "stage_one_protocol_hash", "spec_hash"}
    }
    composite = {
        key: value
        for key, value in record.items()
        if key not in {"stage_one_protocol_hash", "spec_hash"}
    }

    assert canonical_hash(protocol) == record["stage_one_protocol_hash"]
    assert canonical_hash(composite) == record["spec_hash"]
    assert PREDECESSOR.read_bytes() == predecessor_bytes


@pytest.mark.parametrize(
    ("mutation", "message"),
    (
        ("conflict_outcome", "before outcome fields"),
        ("eth_getLogs", "call accounting"),
        ("pool_binding", "does not match its frozen pool row"),
    ),
)
def test_range_successor_rejects_post_conflict_reads_and_log_calls(
    tmp_path, mutation, message
):
    root = tmp_path / mutation
    root.mkdir()
    with rehearsal._registered_range_rehearsal_family():
        spec, _ = rehearsal._stage_range_spec(root)
        refs = rehearsal._range_sources(spec, root)
    frame_path = root / refs[0]["ref"]
    frame = json.loads(frame_path.read_text(encoding="utf-8"))
    if mutation == "conflict_outcome":
        controlled = next(row for row in frame["rows"] if row["token_id"] == 7141050)
        controlled["liquidity"] = 1
    elif mutation == "eth_getLogs":
        frame["rpc_call_accounting"]["eth_getLogs"] = 1
        frame["rpc_call_accounting"]["total"] += 1
    else:
        live = next(row for row in frame["rows"] if row.get("liquidity", 0) > 0)
        live["token0"] = "0x0000000000000000000000000000000000000008"
    raw = (json.dumps(frame, indent=2, sort_keys=True) + "\n").encode("utf-8")
    frame_path.write_bytes(raw)
    refs[0]["sha256"] = hashlib.sha256(raw).hexdigest()

    with pytest.raises(ValueError, match=message):
        spec_module._range_successor_source_frame(spec, refs, root)


def test_range_successor_binds_the_first_successful_pool_capture(tmp_path):
    root = tmp_path / "capture-log"
    root.mkdir()
    with rehearsal._registered_range_rehearsal_family():
        spec, _ = rehearsal._stage_range_spec(root)
        refs = rehearsal._range_sources(spec, root)
    pool_path = root / refs[1]["ref"]
    truth = json.loads(pool_path.read_text(encoding="utf-8"))
    for snapshot, second in zip(
        truth["source_snapshots"].values(), (1, 2), strict=True
    ):
        snapshot["attempt_ordinal"] = 2
        snapshot["observed_at"] = f"2026-08-26T12:11:0{second}Z"
    truth["capture_log"] = [
        {
            "attempt_ordinal": 1,
            "scheduled_at": "2026-08-26T12:10:00Z",
            "pools_status": 503,
            "token_list_status": 200,
        },
        {
            "attempt_ordinal": 2,
            "scheduled_at": "2026-08-26T12:11:00Z",
            "pools_status": 200,
            "token_list_status": 200,
        },
    ]

    def write_pool(body):
        raw = (json.dumps(body, indent=2, sort_keys=True) + "\n").encode("utf-8")
        pool_path.write_bytes(raw)
        refs[1]["sha256"] = hashlib.sha256(raw).hexdigest()

    write_pool(truth)
    spec_module._range_successor_source_frame(spec, refs, root)

    missing_first = json.loads(json.dumps(truth))
    missing_first["capture_log"] = missing_first["capture_log"][1:]
    write_pool(missing_first)
    with pytest.raises(ValueError, match="capture log must reach"):
        spec_module._range_successor_source_frame(spec, refs, root)

    prior_success = json.loads(json.dumps(truth))
    prior_success["capture_log"][0]["pools_status"] = 200
    write_pool(prior_success)
    with pytest.raises(ValueError, match="first successful capture"):
        spec_module._range_successor_source_frame(spec, refs, root)


def test_range_successor_case_ids_and_coverage_are_locked(tmp_path):
    root = tmp_path / "case-binding"
    root.mkdir()
    with rehearsal._registered_range_rehearsal_family():
        spec, spec_path = rehearsal._stage_range_spec(root)
        locked = rehearsal._lock_range(spec, spec_path, root)
        input_path = root / locked.inputs_ref
        envelope = json.loads(input_path.read_text(encoding="utf-8"))
        for case in envelope["cases"]:
            assert case["case_id"] == (
                f"range-{case['selection_stratum']}-{case['token_id']}"
            )
            assert {
                key: case["truth"][key]
                for key in (
                    "frame_sample_size",
                    "frame_unique_indices",
                    "frame_complete",
                )
            } == {
                "frame_sample_size": 1024,
                "frame_unique_indices": 1024,
                "frame_complete": True,
            }
        envelope["cases"][0]["case_id"] = "range-manipulated-id"
        raw = (json.dumps(envelope, indent=2, sort_keys=True) + "\n").encode("utf-8")
        with pytest.raises(ValueError, match="contradicts its frozen frame"):
            spec_module._validate_inputs(locked, raw, root)
