"""Bind delivered work to its input with hashes a caller can recompute alone.

Hashes are SHA-256 over canonical JSON: sorted keys, no separator whitespace,
``ensure_ascii=False`` and UTF-8. A receipt asserts delivery, not correctness.
A ``settled`` payment block means the configured facilitator returned a successful
v2 settlement and transaction id; it is not Docket's own chain-finality proof.
"""

import hashlib
import json
from datetime import datetime, timezone


def canonical_hash(obj) -> str:
    """SHA-256 over canonical JSON, ``0x``-prefixed and key-order independent."""
    blob = json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "0x" + hashlib.sha256(blob.encode("utf-8")).hexdigest()


def is_human_readable_result(result) -> bool:
    """Whether a non-empty JSON result contains text a person can actually read."""
    if not isinstance(result, dict) or not result:
        return False

    def readable(value) -> bool:
        if isinstance(value, str):
            return bool(value.strip()) and any(
                character.isalpha() for character in value
            )
        if isinstance(value, dict):
            return any(readable(item) for item in value.values())
        if isinstance(value, list):
            return any(readable(item) for item in value)
        return False

    return readable(result)


def build_receipt(service_id: str, request_payload, result, *, payment: dict) -> dict:
    """Bind one result and its payment evidence to the request that produced it."""
    return {
        "service": service_id,
        "input_hash": canonical_hash(request_payload),
        "output_hash": canonical_hash(result),
        "delivered_at": datetime.now(timezone.utc).isoformat(),
        "payment": payment,
    }
