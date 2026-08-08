"""What was delivered, bound to what was asked for, in a form the caller can check alone.

A receipt is only worth something if the party it is issued to can verify it
without the issuer's cooperation. So the hashes here are plain SHA-256 over
canonical JSON — sorted keys, no separator whitespace, UTF-8 — which any language
computes in three lines. A caller re-hashes the body it sent and the result it
received; if either digest differs from the receipt, the receipt is describing
something else.

`ensure_ascii=False` is part of the recipe, not an implementation detail: it
hashes non-ASCII text as its UTF-8 bytes rather than as `\\uXXXX` escapes, so a
third party must pass the same flag. Every field Docket puts in a payload today
is ASCII, where the two settings agree — but a wallet label arriving from
elsewhere would not be, and a hash whose recipe is ambiguous is not checkable.

A receipt records delivery and nothing else. It does not assert the work is
correct, and the `payment` block it carries states only what Docket actually
established — verifying a signature is not settling a transfer, and the two are
never allowed to share a word here.
"""

import hashlib
import json
from datetime import datetime, timezone


def canonical_hash(obj) -> str:
    """SHA-256 over canonical JSON, `0x`-prefixed.

    Key order must not change the digest: the caller serialised its request with
    whatever ordering its JSON library chose, and re-hashing has to land on the
    same value.
    """
    blob = json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "0x" + hashlib.sha256(blob.encode("utf-8")).hexdigest()


def build_receipt(service_id: str, request_payload, result, *, payment: dict) -> dict:
    """Bind one result to the request that produced it.

    `payment` travels as the caller's own dict rather than a status string so the
    reason a hire was served — free tier, or an authorization Docket verified and
    did not settle — stays attached to the delivery it applies to.
    """
    return {
        "service": service_id,
        "input_hash": canonical_hash(request_payload),
        "output_hash": canonical_hash(result),
        "delivered_at": datetime.now(timezone.utc).isoformat(),
        "payment": payment,
    }
