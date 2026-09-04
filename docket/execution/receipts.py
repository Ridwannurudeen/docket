"""What an action was, bound to everything that let it happen.

The hire receipts bind a result to the request that produced it. An action receipt has
more to bind, because more had to be true: the observation the condition was evaluated
against, the policy the intent was drafted under, what the simulation said, what the
authority said and where it read it, every state the action passed through, and the
transaction hash if one was ever sent.

Same recipe as `hire/receipts.py` — SHA-256 over canonical JSON — so a holder recomputes
it without Docket's cooperation, and every integer travels as a decimal string because a
wei figure does not survive a JSON parser that uses doubles.

`EXECUTION_NOTE` rides on every one of these and is the sentence a marketplace is most
tempted to leave off. A confirmed transaction shows an action executed as authorised. It
does not show the action was worth taking.
"""

from datetime import UTC, datetime

from ..hire.receipts import canonical_hash

EXECUTION_NOTE = (
    "A confirmed transaction shows this action executed exactly as it was authorised: "
    "the calldata matches the commitment, the output cleared the floor the intent set, "
    "and the session permitted it on chain. It does not show the action was worth "
    "taking. A grid level filling at its own price is a fill, not a gain, and whether "
    "the position ends up ahead depends on what the market does next. Docket records "
    "what happened and does not grade it."
)
# What the cap figures on a receipt do and do not say. The remaining cap is read before
# the action; the figure after it is only knowable once the transaction has validated on
# chain, which is a later read and a different receipt.
CAP_NOTE = (
    "remaining_before is the session's own on-chain figure read before this action, and "
    "committed is the most this action could consume of it. The remaining figure "
    "afterwards is not here because it is not knowable yet: the cap moves when the "
    "transaction validates, which is a read taken later."
)


def action_receipt(
    *,
    intent,
    plan_hash: str,
    observation: dict,
    simulation: dict,
    lifecycle: dict,
    authority: dict | None = None,
    cap: dict | None = None,
    tx_hash: str | None = None,
) -> dict:
    """One action, with everything a holder needs to check it against the chain.

    `authority` is the session status as it was read, `source` field and all, so a reader
    can tell at a glance whether the limits behind this action were the chain's or a
    stub's. It is None where nothing was asked, which is what a preview looks like.
    """
    body = {
        "intent": intent.as_record(),
        "intent_key": intent.idempotency_key,
        "plan_hash": plan_hash,
        "policy_version": intent.policy_version,
        "observation": observation,
        "simulation": simulation,
        "authority": authority,
        "cap": None if cap is None else cap | {"note": CAP_NOTE},
        "lifecycle": lifecycle,
        "tx_hash": tx_hash,
        "note": EXECUTION_NOTE,
    }
    return body | {
        "issued_at": datetime.now(UTC).isoformat(),
        "receipt_hash": canonical_hash(body),
    }
