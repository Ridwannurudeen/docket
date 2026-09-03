"""One pass over every live persistent activation, run by a timer every minute.

This process is the only one that reads `DOCKET_SESSION_KEY_FILE`. The web process holds
no master password and can therefore mint no key, open no session and sweep nothing: it
records what the owner asked for and leaves the three things that need a key here. That is
the whole reason `awaiting_session` and `revoking` exist as states rather than as moments
inside a request.

So a pass does four things, in this order:

  * `revoking` — sweep the float back, then read the balances again. The activation
    closes only when they read zero. "We broadcast the sweep" is the weaker claim and is
    never served as the end of the story.
  * expired — a policy past its own expiry is moved to `revoking`, wherever it was.
  * `awaiting_session` — mint the keystore and ask the owner to fund the address.
  * `active` — evaluate, and send what the policy permits.

One owner's activation going wrong must not stop the next owner's. Each is taken on its
own, its failure is written onto it and logged, and the loop carries on. The exit code
says whether any of them errored, so the unit shows red for a real fault and green for a
pass where nothing needed doing.
"""

import argparse
import logging
import os

from ..escrow.chain import Rpc
from ..hire.catalogue import SERVICES
from ..sessions.executor import ExecutionFailed, execute
from ..sessions.keys import SessionsUnavailable
from ..sessions.policy import SessionPolicy
from ..sessions.spend import UnmeasuredSpend, batch_spend
from ..sessions.sweep import SweepFailed, residual_balances, sweep
from ..store import Store
from .executors import EXECUTORS, load_executors
from .models import PERSISTENT, NextAction
from .service import ActivationService

logger = logging.getLogger("docket.jobs.tick")

# One page at a time, and every page: a tick that has fallen behind still has to reach the
# activation at the end of the queue, and holding the writer for the whole backlog in one
# statement is what a page size is for.
TICK_PAGE = 100
MAX_TICK_PAGES = 50
# States a persistent activation can be in and still be the tick's business.
LIVE_STATES = ("revoking", "awaiting_session", "active", "paused", "needs_approval")


def _live_activations(store):
    """Every live persistent activation, oldest state first, paginated."""
    for state in LIVE_STATES:
        offset = 0
        for _ in range(MAX_TICK_PAGES):
            page = store.list_activations(state=state, limit=TICK_PAGE, offset=offset)
            if not page:
                break
            for activation in page:
                if activation.kind == PERSISTENT:
                    yield activation
            if len(page) < TICK_PAGE:
                break
            offset += TICK_PAGE


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


def _session_for(service, activation, rpc):
    """The unlocked session, with the tokens a sweep has to look for filled in."""
    session = service.open_session(activation)
    if session is None:
        return None
    received = ((activation.result or {}).get("last_decision") or {}).get(
        "evidence"
    ) or {}
    session.received_tokens = tuple(received.get("received_tokens") or ())
    return session


def _close(service, activation, rpc) -> None:
    """Sweep a `revoking` session and close it only against balances that read zero."""
    expected = activation.updated_at
    session = _session_for(service, activation, rpc)
    if session is None:
        # Nothing was ever minted, or the key is already closed. There is no float to
        # return, so the reading is trivially empty and the activation may close.
        service.finish_closing(activation, {})
        service.store.save_activation(activation, expected_updated_at=expected)
        return
    policy = SessionPolicy.from_dict(activation.policy)
    try:
        sent = sweep(
            session,
            activation.owner,
            rpc,
            max_gas_price_wei=policy.max_gas_price_wei,
        )
        if sent:
            activation.note(
                "swept back to the owner in " + ", ".join(sent), actor="chain"
            )
    except SweepFailed as exc:
        activation.note(f"the session was not fully swept: {exc}", actor="docket")
    residual = residual_balances(session, rpc)
    service.finish_closing(activation, residual)
    service.store.save_activation(activation, expected_updated_at=expected)


def _mint(service, activation) -> None:
    """Give one `awaiting_session` activation its key and ask the owner to fund it."""
    expected = activation.updated_at
    service.mint_session(activation)
    service.store.save_activation(activation, expected_updated_at=expected)


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
    session = _session_for(service, activation, rpc) if permitted else None
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
            owner=activation.owner,
            session=session.address,
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


def _note_failure(store, activation_id, exc) -> None:
    """Write the failure onto the activation it happened to.

    An error that only reaches the journal is an error the owner reading their own
    activation cannot see, and "nothing has happened for six hours" is exactly the state
    a session must never be able to reach silently. Re-read first, because whatever failed
    may have left the in-memory copy half-changed.
    """
    try:
        activation = store.get_activation(activation_id)
        if activation is None or activation.is_terminal:
            return
        expected = activation.updated_at
        activation.note(
            f"this pass did not complete: {type(exc).__name__}: {exc}", actor="docket"
        )
        store.save_activation(activation, expected_updated_at=expected)
    except Exception:
        logger.exception("could not record the failure on %s", activation_id)


def run_once(store: Store, *, rpc=None, services=None, environment=None) -> int:
    """Advance every live persistent activation. Returns how many errored."""
    load_executors()
    service = ActivationService(
        store,
        services=SERVICES if services is None else services,
        rpc=rpc,
        environment=environment,
    )
    errors = 0
    for activation in _live_activations(store):
        try:
            if activation.state == "revoking":
                _close(service, activation, rpc)
                continue
            if service.has_expired(activation):
                service.expire(activation.activation_id)
                logger.info(
                    "activation %s expired and is closing", activation.activation_id
                )
                continue
            if activation.state == "awaiting_session":
                _mint(service, activation)
                continue
            if activation.state == "active":
                _evaluate(service, activation, rpc)
        except Exception as exc:
            errors += 1
            logger.error(
                "activation %s failed this pass: %s: %s",
                activation.activation_id,
                type(exc).__name__,
                exc,
            )
            _note_failure(store, activation.activation_id, exc)
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


__all__ = ["SessionsUnavailable", "main", "run_once"]
