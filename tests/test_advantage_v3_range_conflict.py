"""The conflict exclusion, attacked from both sides.

The experiment party controls a live PancakeSwap v3 position, and the Range population
enumerates every live position on chain. Registering an exclusion in prose was not enough:
the validator's own equality check between the manifest and the parsed sources meant an
honest manifest that omitted the controlled position *failed the lock*, while a manifest
that quietly included it locked cleanly. Honesty was the thing that broke.

So these tests are not "is the controlled position excluded". They are the mutations a
suite that only asked that question would wave through. The two that matter most are the
over-exclusion case — inventing a conflict deletes an honest position and moves which token
id wins the draw, which is the same attack pointed the other way — and the ordering case,
which is the only one that can tell "recorded before classification" from "classified and
then discarded".

The Transfer topic below is split around its `0x` for the reason the correction ledger
gives: bare `0x`-plus-64-hex is also the shape of a private key, and the repository blocks
that pattern rather than asking each time which it is.
"""

import hashlib
import json
from base64 import b64encode
from pathlib import Path

import pytest
from test_advantage_v3_spec import SPECS_DIR, _input_record, _source_ref

from docket.advantage.v3.spec import (
    RANGE_MASTER_CHEF,
    YIELD_SOURCE_URLS,
    PairedSpec,
    assert_runnable,
    load,
    lock_inputs,
    save,
)

RANGE_MANAGER = "0x46A15B0b27311cedF172AB29E4f4766fbE7F4364"
CONTROLLED_WALLET = "0xe55816904796341bf8535e25f6c8b647927fc946"
CONTROLLED_TOKEN = 7141050
TRANSFER_TOPIC = (
    "0x" + "ddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
)
GOOD_POOL = f"0x{201:040x}"
BAD_POOL = f"0x{202:040x}"
UNKNOWN_POOL = f"0x{909:040x}"
POOL_TOKENS = [f"0x{number:040x}" for number in (101, 102)]
STRANGER = f"0x{7777:040x}"
REASON = "experiment_party_controlled"


def _row(token_id, *, pool=GOOD_POOL, liquidity=1, tick=0, beneficiary=None):
    row = {
        "position_manager": RANGE_MANAGER,
        "token_id": token_id,
        "pool_id": pool,
        "liquidity": liquidity,
        "current_tick": tick,
        "tick_lower": -10,
        "tick_upper": 10,
    }
    if beneficiary is not None:
        row["staking_beneficiary"] = beneficiary
    return row


def _envelope(root: Path, extra=()):
    """Five honest cases filling the five strata, plus whatever rows a test injects."""
    spec = load(SPECS_DIR / "v3-01-range-doctor.json")
    states = {
        1: ("in_range", 0, True),
        2: ("above_range", 20, True),
        3: ("below_range", -20, True),
        4: ("in_range", 0, False),
        5: ("in_range", 0, True),
    }
    in_range_ids = sorted(
        (1, 5),
        key=lambda token_id: hashlib.sha256(
            f"{spec.stage_one_protocol_hash}56{RANGE_MANAGER.lower()}{token_id}".encode()
        ).hexdigest(),
    )
    token_by_stratum = {1: in_range_ids[0], 2: 2, 3: 3, 4: 4, 5: in_range_ids[1]}
    cases = []
    for stratum, (status, tick, gate) in states.items():
        token_id = token_by_stratum[stratum]
        cases.append(
            {
                "case_id": f"range-{stratum}",
                "selection_stratum": stratum,
                "chain_id": 56,
                "position_manager": RANGE_MANAGER,
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
                    "pool_gate_passes": gate,
                    "first_failed_gate": None if gate else "token0_allowlist",
                    "current_tick": tick,
                    "tick_lower": -10,
                    "tick_upper": 10,
                    "fee_usd_24h": 20.0,
                    "protocol_fee_usd_24h": 10.0,
                    "tvl_usd": 36500.0,
                    "gross_apr": 0.2 if gate else None,
                    "net_apr": 0.1 if gate else None,
                    "annual_gross_usd": 2000 if gate else None,
                    "annual_net_usd": 1000 if gate else None,
                    "annual_overstatement_usd": 1000 if gate else None,
                    "cost_only_break_even_days": 9.125 if gate else None,
                    "positions_held": 1,
                    "positions_examined": 1,
                    "closed_skipped": 0,
                    "scan_complete": True,
                },
            }
        )

    scans = [
        {
            "wallet": case["wallet"],
            "positions_held": 1,
            "positions_examined": 1,
            "closed_skipped": 0,
            "scan_complete": True,
            "positions": [
                _row(
                    case["token_id"],
                    pool=BAD_POOL if case["selection_stratum"] == 4 else GOOD_POOL,
                    tick=case["truth"]["current_tick"],
                )
            ],
        }
        for case in cases
    ]
    wallets = [case["wallet"] for case in cases]
    for wallet, row in extra:
        wallets.append(wallet)
        scans.append(
            {
                "wallet": wallet,
                "positions_held": 1,
                "positions_examined": 1,
                "closed_skipped": 1 if row["liquidity"] <= 0 else 0,
                "scan_complete": True,
                "positions": [row],
            }
        )

    pairs = [(case["wallet"], case["token_id"]) for case in cases]
    pairs += [(wallet, row["token_id"]) for wallet, row in extra]
    transfer_body = json.dumps(
        {
            "from_block": 0,
            "to_block": 123,
            "selected_block": {"number": 123, "timestamp": "2026-08-21T12:00:00Z"},
            "predecessor_block": {"number": 122, "timestamp": "2026-08-21T11:59:59Z"},
            "latest_finalized_block": 123,
            "contracts": [RANGE_MANAGER, "0x556B9306565093C855AEA9AE92A594704c2Cd59e"],
            "complete": True,
            "logs": [
                {
                    "contract": RANGE_MANAGER,
                    "block_number": 100 + number,
                    "transaction_hash": f"0x{number + 1:064x}",
                    "log_index": number,
                    "topics": [
                        TRANSFER_TOPIC,
                        "0x" + "0" * 64,
                        "0x" + "0" * 24 + wallet[2:],
                        f"0x{token_id:064x}",
                    ],
                }
                for number, (wallet, token_id) in enumerate(pairs)
            ],
        }
    ).encode()
    enumeration_body = json.dumps(
        {
            "observation_block": 123,
            "observation_time": "2026-08-21T12:00:00Z",
            "complete": True,
            "wallet_scans": scans,
        }
    ).encode()
    pools_body = json.dumps(
        [
            {
                "id": pool,
                "token0": {
                    "id": POOL_TOKENS[0] if pool == GOOD_POOL else f"0x{999:040x}"
                },
                "token1": {"id": POOL_TOKENS[1]},
                "tvlUSD": "36500",
                "volumeUSD24h": "1000",
                "feeUSD24h": "20",
                "protocolFeeUSD24h": "10",
            }
            for pool in (GOOD_POOL, BAD_POOL)
        ]
    ).encode()
    tokens_body = json.dumps(
        {"tokens": [{"chainId": 56, "address": address} for address in POOL_TOKENS]}
    ).encode()

    manifest = {
        "candidate_wallets": wallets,
        "eligible_positions": [
            {
                "position_manager": case["position_manager"],
                "wallet": case["wallet"],
                "token_id": case["token_id"],
                "range_status": case["truth"]["range_status"],
                "liquidity": case["truth"]["liquidity"],
                "pool_gate_passes": case["truth"]["pool_gate_passes"],
            }
            for case in cases
        ],
        "conflict_exclusions": [],
        "source_refs": [
            _source_ref(root, "evidence/rx-transfers.json", transfer_body)
            | {"kind": "transfer_logs"},
            _source_ref(root, "evidence/rx-enumeration.json", enumeration_body)
            | {"kind": "position_enumeration"},
            _source_ref(
                root,
                "evidence/rx-pool-truth.json",
                json.dumps(
                    {
                        "source_snapshots": {
                            "pools": {
                                "url": YIELD_SOURCE_URLS["pools"],
                                "observed_at": "2026-08-21T12:00:01Z",
                                "attempt_ordinal": 1,
                                "sha256": hashlib.sha256(pools_body).hexdigest(),
                                "body_base64": b64encode(pools_body).decode(),
                            },
                            "token_list": {
                                "url": YIELD_SOURCE_URLS["token_list"],
                                "observed_at": "2026-08-21T12:00:02Z",
                                "attempt_ordinal": 1,
                                "sha256": hashlib.sha256(tokens_body).hexdigest(),
                                "body_base64": b64encode(tokens_body).decode(),
                            },
                        }
                    }
                ).encode(),
            )
            | {"kind": "pool_truth"},
        ],
    }
    for case in cases:
        case["source_refs"] = manifest["source_refs"]
    return spec, manifest, cases


def _write(root: Path, spec, manifest, cases):
    path = root / spec.inputs_ref
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            _input_record(spec) | {"selection_manifest": manifest, "cases": cases}
        ),
        encoding="utf-8",
    )


def _exclusion(wallet, token_id):
    return {
        "position_manager": RANGE_MANAGER,
        "wallet": wallet,
        "token_id": token_id,
        "excluded_reason": REASON,
    }


def test_a_frame_with_no_party_position_still_locks(tmp_path):
    """The control. Without it the suite cannot tell a working exclusion from a lock that
    rejects everything."""
    spec, manifest, cases = _envelope(tmp_path)
    _write(tmp_path, spec, manifest, cases)
    assert_runnable(lock_inputs(spec, repo_root=tmp_path), repo_root=tmp_path)


def test_the_controlled_position_is_recorded_and_the_frame_still_locks(tmp_path):
    """The positive control, and the one most likely to be got wrong.

    The obvious implementation removes the position and leaves the manifest/enumeration
    equality to fail, at which point the tempting fix is to loosen that equality to a
    subset — which reopens the hole the exclusion exists to close.
    """
    spec, manifest, cases = _envelope(
        tmp_path, extra=[(CONTROLLED_WALLET, _row(CONTROLLED_TOKEN))]
    )
    manifest["conflict_exclusions"] = [_exclusion(CONTROLLED_WALLET, CONTROLLED_TOKEN)]
    _write(tmp_path, spec, manifest, cases)
    assert_runnable(lock_inputs(spec, repo_root=tmp_path), repo_root=tmp_path)


@pytest.mark.parametrize(
    "declare, expected",
    [
        (False, "conflict exclusions differ"),
        (True, "differs from archive enumeration"),
    ],
    ids=["undeclared", "declared-and-kept"],
)
def test_a_controlled_position_left_in_the_eligible_frame_is_refused(
    tmp_path, declare, expected
):
    """Both routes back in, because they fail at different guards.

    Leaving it undeclared trips the conflict equality. Declaring it honestly and *also*
    keeping it in the eligible frame trips the frame equality instead — a manifest cannot
    have it both ways, and neither ordering of the two guards lets it through.
    """
    spec, manifest, cases = _envelope(
        tmp_path, extra=[(CONTROLLED_WALLET, _row(CONTROLLED_TOKEN))]
    )
    manifest["eligible_positions"].append(
        {
            "position_manager": RANGE_MANAGER,
            "wallet": CONTROLLED_WALLET,
            "token_id": CONTROLLED_TOKEN,
            "range_status": "in_range",
            "liquidity": 1,
            "pool_gate_passes": True,
        }
    )
    if declare:
        manifest["conflict_exclusions"] = [
            _exclusion(CONTROLLED_WALLET, CONTROLLED_TOKEN)
        ]
    _write(tmp_path, spec, manifest, cases)
    with pytest.raises(ValueError, match=expected):
        lock_inputs(spec, repo_root=tmp_path)


def test_a_controlled_position_recorded_nowhere_is_refused(tmp_path):
    """Kills the subset-loosened equality: silently dropping it must not lock."""
    spec, manifest, cases = _envelope(
        tmp_path, extra=[(CONTROLLED_WALLET, _row(CONTROLLED_TOKEN))]
    )
    _write(tmp_path, spec, manifest, cases)
    with pytest.raises(ValueError, match="conflict exclusions differ"):
        lock_inputs(spec, repo_root=tmp_path)


def test_inventing_a_conflict_is_refused(tmp_path):
    """Over-exclusion is the same attack pointed the other way.

    Labelling an honest position experiment-party-controlled deletes it from the frame and
    moves which token id wins the lowest-hash draw. A suite that only tested the other
    direction would license it.
    """
    spec, manifest, cases = _envelope(tmp_path)
    victim = manifest["eligible_positions"][0]
    manifest["conflict_exclusions"] = [_exclusion(victim["wallet"], victim["token_id"])]
    _write(tmp_path, spec, manifest, cases)
    with pytest.raises(ValueError, match="conflict exclusions differ"):
        lock_inputs(spec, repo_root=tmp_path)


def test_the_token_id_prong_catches_a_transferred_position(tmp_path):
    """A listed token held by an unlisted wallet — the post-transfer case. Kills a
    wallet-only check."""
    spec, manifest, cases = _envelope(
        tmp_path, extra=[(STRANGER, _row(CONTROLLED_TOKEN))]
    )
    manifest["conflict_exclusions"] = [_exclusion(STRANGER, CONTROLLED_TOKEN)]
    _write(tmp_path, spec, manifest, cases)
    assert_runnable(lock_inputs(spec, repo_root=tmp_path), repo_root=tmp_path)


def test_the_wallet_prong_catches_a_newly_minted_position(tmp_path):
    """An unlisted token held by a listed wallet. Kills a token-only check."""
    spec, manifest, cases = _envelope(
        tmp_path, extra=[(CONTROLLED_WALLET, _row(918273))]
    )
    manifest["conflict_exclusions"] = [_exclusion(CONTROLLED_WALLET, 918273)]
    _write(tmp_path, spec, manifest, cases)
    assert_runnable(lock_inputs(spec, repo_root=tmp_path), repo_root=tmp_path)


def test_the_staking_prong_catches_a_farmed_position(tmp_path):
    """Held by MasterChef, beneficiary listed. Kills an ownerOf-only check."""
    spec, manifest, cases = _envelope(
        tmp_path,
        extra=[(RANGE_MASTER_CHEF, _row(514243, beneficiary=CONTROLLED_WALLET))],
    )
    manifest["conflict_exclusions"] = [_exclusion(RANGE_MASTER_CHEF, 514243)]
    _write(tmp_path, spec, manifest, cases)
    assert_runnable(lock_inputs(spec, repo_root=tmp_path), repo_root=tmp_path)


def test_a_farm_row_without_a_beneficiary_is_refused(tmp_path):
    """The prong has to be checkable, not skippable. A farm-held row naming no beneficiary
    makes the staking check unanswerable, so the lock fails rather than treating
    unanswerable as clean."""
    spec, manifest, cases = _envelope(
        tmp_path, extra=[(RANGE_MASTER_CHEF, _row(514243))]
    )
    _write(tmp_path, spec, manifest, cases)
    with pytest.raises(ValueError, match="staking_beneficiary"):
        lock_inputs(spec, repo_root=tmp_path)


def test_the_exclusion_precedes_classification(tmp_path):
    """The only test that distinguishes 'recorded before classification' from 'classified
    and then discarded'.

    The controlled position names a pool absent from the frozen pool truth. An
    implementation that classifies first has to look that pool up, and raises about a
    missing pool row instead of excluding the position.
    """
    spec, manifest, cases = _envelope(
        tmp_path, extra=[(CONTROLLED_WALLET, _row(CONTROLLED_TOKEN, pool=UNKNOWN_POOL))]
    )
    manifest["conflict_exclusions"] = [_exclusion(CONTROLLED_WALLET, CONTROLLED_TOKEN)]
    _write(tmp_path, spec, manifest, cases)
    assert_runnable(lock_inputs(spec, repo_root=tmp_path), repo_root=tmp_path)


def test_a_closed_controlled_position_still_reconciles_the_scan(tmp_path):
    """Excluding before the liquidity check must not break the scanner's own arithmetic.

    `closed_skipped` is the scanner's attestation about what it saw, and it counted the
    controlled position whether or not this protocol wants it. Dropping the row without
    counting it would fail an honest manifest — the exact shape of bug the exclusion was
    written to avoid.
    """
    spec, manifest, cases = _envelope(
        tmp_path, extra=[(CONTROLLED_WALLET, _row(CONTROLLED_TOKEN, liquidity=0))]
    )
    manifest["conflict_exclusions"] = [_exclusion(CONTROLLED_WALLET, CONTROLLED_TOKEN)]
    _write(tmp_path, spec, manifest, cases)
    assert_runnable(lock_inputs(spec, repo_root=tmp_path), repo_root=tmp_path)


@pytest.mark.parametrize(
    "wallets, token_ids",
    [
        ([STRANGER], [4242]),
        ([STRANGER], [CONTROLLED_TOKEN]),
        ([CONTROLLED_WALLET], [4242]),
    ],
    ids=["neither", "wallet-missing", "token-missing"],
)
def test_a_registration_that_omits_either_half_cannot_lock(
    tmp_path, wallets, token_ids
):
    """Each half of the floor is load-bearing on its own.

    An earlier version of this test omitted the wallet and the token id together, so
    deleting the wallet half of the check changed nothing that any test could see. Mutating
    the implementation is what found that; reading it would not have.
    """
    spec, manifest, cases = _envelope(tmp_path)
    record = spec.as_record()
    record.pop("stage_one_protocol_hash")
    record.pop("spec_hash")
    record["case_selection"]["conflict_exclusion"] = {
        "excluded_reason": REASON,
        "wallets": wallets,
        "token_ids": token_ids,
    }
    thinned = PairedSpec(**record)
    save(thinned, tmp_path / "specs" / "v3-01-range-doctor.json", repo_root=tmp_path)
    _write(tmp_path, thinned, manifest, cases)
    with pytest.raises(
        ValueError, match="does not match the positions this build knows"
    ):
        lock_inputs(thinned, repo_root=tmp_path)


def test_a_free_text_exclusion_reason_is_refused(tmp_path):
    spec, manifest, cases = _envelope(
        tmp_path, extra=[(CONTROLLED_WALLET, _row(CONTROLLED_TOKEN))]
    )
    manifest["conflict_exclusions"] = [
        _exclusion(CONTROLLED_WALLET, CONTROLLED_TOKEN) | {"excluded_reason": "ours"}
    ]
    _write(tmp_path, spec, manifest, cases)
    with pytest.raises(ValueError, match="contradicts the parsed sources"):
        lock_inputs(spec, repo_root=tmp_path)


def test_the_registered_wallets_are_lowercase_and_cover_the_known_position():
    """What a reader checks without running anything."""
    spec = load(SPECS_DIR / "v3-01-range-doctor.json")
    exclusion = spec.case_selection["conflict_exclusion"]
    assert exclusion["excluded_reason"] == REASON
    assert CONTROLLED_WALLET in exclusion["wallets"]
    assert CONTROLLED_TOKEN in exclusion["token_ids"]
    assert all(wallet == wallet.lower() for wallet in exclusion["wallets"])
    excluded = spec.case_selection["excluded"].lower()
    for clause in (
        "can never fill a stratum",
        "cannot change after protocol lock",
        "ownerof",
        "masterchefv3",
        "staking beneficiary",
    ):
        assert clause in excluded


@pytest.mark.parametrize(
    "wallets, token_ids",
    [
        ([CONTROLLED_WALLET, STRANGER], [CONTROLLED_TOKEN]),
        ([CONTROLLED_WALLET], [CONTROLLED_TOKEN, 4242]),
    ],
    ids=["padded-wallet", "padded-token"],
)
def test_a_padded_registration_cannot_lock(tmp_path, wallets, token_ids):
    """A floor stops the list being written short. Nothing stopped it being written long.

    Adding an honest third party's wallet to the controlled list deletes their positions
    from the draw deterministically, and the claim that we control it is publicly
    undisprovable — unlike a fabricated enumeration, no reader re-deriving from chain can
    catch it. Padding also hands over a free parameter: iterate paddings, keep the one
    whose induced draw you like. So the check is equality, not containment.
    """
    spec, manifest, cases = _envelope(tmp_path)
    record = spec.as_record()
    record.pop("stage_one_protocol_hash")
    record.pop("spec_hash")
    record["case_selection"]["conflict_exclusion"] = {
        "excluded_reason": REASON,
        "wallets": wallets,
        "token_ids": token_ids,
    }
    padded = PairedSpec(**record)
    save(padded, tmp_path / "specs" / "v3-01-range-doctor.json", repo_root=tmp_path)
    _write(tmp_path, padded, manifest, cases)
    with pytest.raises(
        ValueError, match="does not match the positions this build knows"
    ):
        lock_inputs(padded, repo_root=tmp_path)


def test_one_token_cannot_be_excluded_under_one_holder_and_drawn_under_another(
    tmp_path,
):
    """The symmetry claim held at the manifest level and failed one level down.

    Listing the same token id twice — once under the controlled wallet, once under an
    honest one — let the conflicted copy be declared while the second copy stayed in the
    drawable frame. Both equality directions passed, because they compare sets of
    identities and each set was internally consistent. `ownerOf` is unique on chain, so
    this only arises from a fabricated enumeration, but nothing here was checking.
    """
    spec, manifest, cases = _envelope(
        tmp_path,
        extra=[
            (CONTROLLED_WALLET, _row(CONTROLLED_TOKEN)),
            (STRANGER, _row(CONTROLLED_TOKEN, pool=BAD_POOL)),
        ],
    )
    manifest["conflict_exclusions"] = [_exclusion(CONTROLLED_WALLET, CONTROLLED_TOKEN)]
    manifest["eligible_positions"].append(
        {
            "position_manager": RANGE_MANAGER,
            "wallet": STRANGER,
            "token_id": CONTROLLED_TOKEN,
            "range_status": "in_range",
            "liquidity": 1,
            "pool_gate_passes": False,
        }
    )
    _write(tmp_path, spec, manifest, cases)
    with pytest.raises(ValueError, match="repeats a position identity"):
        lock_inputs(spec, repo_root=tmp_path)


def test_the_duplicate_check_holds_in_the_other_scan_order(tmp_path):
    """The same fabrication with the honest holder enumerated first.

    Guarding only the conflicted-side insertion caught this when the controlled copy was
    scanned first and missed it entirely when it was scanned second — the wallet scans are
    a dict of the fabricator's own making, so the order is theirs to choose. Both
    insertions check the other collection.
    """
    spec, manifest, cases = _envelope(
        tmp_path,
        extra=[
            (STRANGER, _row(CONTROLLED_TOKEN, pool=BAD_POOL)),
            (CONTROLLED_WALLET, _row(CONTROLLED_TOKEN)),
        ],
    )
    manifest["conflict_exclusions"] = [_exclusion(CONTROLLED_WALLET, CONTROLLED_TOKEN)]
    manifest["eligible_positions"].append(
        {
            "position_manager": RANGE_MANAGER,
            "wallet": STRANGER,
            "token_id": CONTROLLED_TOKEN,
            "range_status": "in_range",
            "liquidity": 1,
            "pool_gate_passes": False,
        }
    )
    _write(tmp_path, spec, manifest, cases)
    with pytest.raises(ValueError, match="repeats a position identity"):
        lock_inputs(spec, repo_root=tmp_path)
