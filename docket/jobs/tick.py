"""One pass over every persistent activation, run by a timer every five minutes.

The shape is chosen for the failure it has to survive: one owner's activation going wrong
must not stop the next owner's. Each activation is taken on its own, its failure is logged
and recorded on the activation, and the loop carries on. What the exit code says is
whether any of them errored, so the systemd unit shows red for a real fault and green for
a pass where nothing needed doing.

A category with no executor registered is not an error. Lane D's executors land after this
loop does, and a tick that died on the gap would take every activation down with it for
the days in between. It is recorded as an `alert` event on the activation instead, which
is what an owner reading the activation should see: nothing is watching this yet.

Nothing here holds a key. The session is opened by `ActivationService` and handed to
`docket.sessions.executor.execute`, which is the only code in Docket that signs.
"""

import argparse
import logging
import os

from ..escrow.chain import Rpc
from ..hire.catalogue import SERVICES
from ..sessions.executor import ExecutionFailed, execute
from ..sessions.policy import SessionPolicy
from ..sessions.spend import UnmeasuredSpend, batch_spend
from ..store import Store
from .executors import EXECUTORS
from .models import PERSISTENT, NextAction
from .service import ActivationService

logger = logging.getLogger("docket.jobs.tick")

# One page of work per pass. A tick that fell behind would otherwise try to catch up in a
# single run and hold the writer for the whole of it; the next pass is five minutes away.
TICK_BATCH = 200
# States a persistent activation can be in and still be the tick's business. `paused` is
# here so an expiry is still noticed while paused; nothing else happens to it.
LIVE_STATES = ("active", "paused", "needs_approval")


def _record_decision(activation, decision) -> None:
    """Carry the executor's own observations forward onto the activation.

    A persistent executor is stateless between passes: the tick constructs it, asks it
    once, and drops it. Anything it measured — how long a position has been out of range,
    what the last price was, which rung of a grid is filled — has to live on the
    activation or it does not live anywhere, and the next pass starts blind.

    So `result.last_decision.evidence` is the executor's carry-over state and is written
    on EVERY pass, including a noop: a pass that observed nothing worth acting on still
    observed something, and it is usually the run of quiet observations that the next
    decision is made from. Other keys of `result` are left alone, because a one-shot's
    result lives in the same field.
    """
    previous = dict(activation.result or {})
    was = (previous.get("last_decision") or {}).get("kind")
    previous["last_decision"] = {
        "kind": decision.kind,
        "summary": decision.summary,
        "observed_at": decision.observed_at,
        "block": decision.block,
        "evidence": decision.evidence,
    }
    activation.result = previous
    if was != decision.kind:
        activation.note(
            f"the executor's reading changed from "
            f"{was or 'nothing observed yet'} to {decision.kind}: {decision.summary} "
            f"(block {decision.block})",
            actor="docket",
        )


def _evaluate(service: ActivationService, activation, rpc) -> None:
    """Advance one active activation as far as its executor and policy allow."""
    executor = EXECUTORS.get(activation.category)
    expected = activation.updated_at
    if executor is None:
        activation.note(
            f"alert: no executor is registered for {activation.category}, so nothing "
            "evaluated this session on this pass",
            actor="docket",
        )
        service.store.save_activation(activation, expected_updated_at=expected)
        return

    decision = executor.evaluate(activation, reader=rpc)
    _record_decision(activation, decision)
    if decision.kind in ("noop", "alert"):
        if decision.kind == "alert":
            activation.note(
                f"alert: {decision.summary} (block {decision.block})", actor="docket"
            )
        service.store.save_activation(activation, expected_updated_at=expected)
        return

    permitted, reason = executor.within_policy(activation, decision)
    session = service.open_session(activation) if permitted else None
    if not permitted or session is None:
        activation.transition(
            "needs_approval",
            reason=(
                f"{decision.summary}; Docket's session may not send it "
                f"({reason if not permitted else 'the session key is gone'}), so the "
                "owner is asked to sign it"
            ),
            actor="docket",
        )
        activation.next_action = NextAction(
            "sign_transaction",
            {
                "purpose": decision.summary,
                "observed_at": decision.observed_at,
                "block": decision.block,
                "calls": [call.to_dict() for call in decision.prepared],
            },
        )
        service.store.save_activation(activation, expected_updated_at=expected)
        return

    policy = SessionPolicy.from_dict(activation.policy)
    token_hints = decision.evidence.get("token_hints") or {}
    slippage_bps = decision.evidence.get("slippage_bps")

    # One question about the whole batch before any of it goes out. Asked from the same
    # derived numbers each call will be charged, so the answer here and the answers
    # inside `execute` cannot disagree — and a batch that would be refused three
    # transactions in is refused at zero instead, rather than leaving a position
    # half-rebalanced.
    try:
        total = batch_spend(
            decision.prepared,
            token_allowlist=policy.token_allowlist,
            token_hints=token_hints,
        )
    except UnmeasuredSpend as exc:
        activation.note(
            f"the batch was not sent: unmeasured spend — {exc}", actor="docket"
        )
        service.store.save_activation(activation, expected_updated_at=expected)
        raise
    within_cap, cap_reason = policy.allows_total(
        spent=session.spent_atomic, token_amounts=total
    )
    if not within_cap:
        activation.transition(
            "needs_approval",
            reason=(
                f"{decision.summary}; the batch of {len(decision.prepared)} calls was "
                f"not sent because {cap_reason}, so the owner is asked to sign it"
            ),
            actor="docket",
        )
        activation.next_action = NextAction(
            "sign_transaction",
            {
                "purpose": decision.summary,
                "observed_at": decision.observed_at,
                "block": decision.block,
                "batch_spend_atomic": {
                    token: str(amount) for token, amount in total.items()
                },
                "calls": [call.to_dict() for call in decision.prepared],
            },
        )
        service.store.save_activation(activation, expected_updated_at=expected)
        return

    failed = None
    for call in decision.prepared:
        try:
            activation.add_receipt(
                execute(
                    activation,
                    call,
                    session=session,
                    rpc=rpc,
                    policy=policy,
                    token_hints=token_hints,
                    slippage_bps=slippage_bps,
                )
            )
        except ExecutionFailed as exc:
            failed = exc
            break
    activation.session = {
        **(activation.session or {}),
        "spent_atomic": {
            token: str(amount) for token, amount in session.spent_atomic.items()
        },
    }
    service.store.save_activation(activation, expected_updated_at=expected)
    if failed is not None:
        raise failed


def run_once(store: Store, *, rpc=None, services=None, environment=None) -> int:
    """Advance every live persistent activation. Returns how many errored."""
    service = ActivationService(
        store,
        services=SERVICES if services is None else services,
        rpc=rpc,
        environment=environment,
    )
    errors = 0
    for state in LIVE_STATES:
        for activation in store.list_activations(state=state, limit=TICK_BATCH):
            if activation.kind != PERSISTENT:
                continue
            try:
                if service.has_expired(activation):
                    service.expire(activation.activation_id)
                    logger.info("expired activation %s", activation.activation_id)
                    continue
                if activation.state != "active":
                    continue
                _evaluate(service, activation, rpc)
            except Exception as exc:
                errors += 1
                logger.error(
                    "activation %s failed this pass: %s: %s",
                    activation.activation_id,
                    type(exc).__name__,
                    exc,
                )
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="docket.jobs.tick",
        description="Advance every live persistent activation by one pass.",
    )
    parser.add_argument(
        "--db",
        default=os.environ.get("DOCKET_DB", ""),
        help="the SQLite database to work in; defaults to $DOCKET_DB",
    )
    arguments = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    if not arguments.db.strip():
        logger.error("DOCKET_DB is required")
        return 1
    errors = run_once(Store(arguments.db.strip()), rpc=Rpc())
    print(f"Docket jobs tick: {errors} activations errored")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
