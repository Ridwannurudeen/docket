import json

import pytest

from docket.hire.receipts import (
    build_receipt,
    canonical_hash,
    is_human_readable_result,
)


def test_canonical_hash_is_key_order_independent():
    a = canonical_hash({"b": 1, "a": {"y": 2, "x": [1, 2]}})
    b = canonical_hash({"a": {"x": [1, 2], "y": 2}, "b": 1})
    assert a == b
    assert a.startswith("0x") and len(a) == 66


def test_canonical_hash_changes_when_content_changes():
    assert canonical_hash({"a": 1}) != canonical_hash({"a": 2})


def test_canonical_hash_rejects_non_finite_json_values():
    with pytest.raises(ValueError):
        canonical_hash({"decision": "complete", "score": float("nan")})


def test_canonical_hash_is_recomputable_by_a_third_party():
    """A caller must be able to verify the hash without Docket's code."""
    import hashlib

    obj = {"wallet": "0xabc", "limit": 5}
    blob = json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8")
    assert canonical_hash(obj) == "0x" + hashlib.sha256(blob).hexdigest()


def test_receipt_binds_input_and_output():
    payload = {"wallet": "0xabc"}
    result = {"positions": []}
    r = build_receipt("range-doctor", payload, result, payment={"status": "free_tier"})
    assert r["service"] == "range-doctor"
    assert r["input_hash"] == canonical_hash(payload)
    assert r["output_hash"] == canonical_hash(result)
    assert r["delivered_at"].endswith("+00:00")
    assert r["payment"]["status"] == "free_tier"


def test_human_readable_result_gate_rejects_empty_raw_json():
    """A syntactically valid object is not a delivered answer; settlement requires
    non-empty text a human can read, not merely JSON that parsed."""
    assert is_human_readable_result({}) is False
    assert is_human_readable_result({"counts": [1, 2]}) is False
    assert is_human_readable_result({"decision": "  "}) is False
    assert is_human_readable_result({"decision": "WAIT"}) is True


def test_receipt_records_only_the_settlement_evidence_it_is_given():
    payment = {
        "status": "settled",
        "payment_id": "0xpayment",
        "nonce": "0xnonce",
        "transaction_id": "0xtransaction",
    }
    receipt = build_receipt(
        "range-doctor", {"wallet": "0xabc"}, {"decision": "WAIT"}, payment=payment
    )

    assert receipt["payment"] == payment
    assert "finality" not in json.dumps(receipt).lower()
