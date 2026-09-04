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
import time

from ..escrow.chain import Rpc
from ..hire.catalogue import SERVICES
from ..sessions.executor import ExecutionFailed, execute
from ..sessions.keys import SessionsUnavailable
from ..sessions.policy import SessionPolicy
from ..sessions.policy import NATIVE_TOKEN
from ..sessions.spend import UnmeasuredSpend, batch_spend, received_tokens
from ..sessions.sweep import (
    SweepFailed,
    outstanding_allowances,
    residual_balances,
    revoke_allowances,
    sweep,
)
from ..store import StaleActivation, Store
from .executors import EXECUTORS, load_executors
from .executors.allowlists import defaults_for
from .models import PERSISTENT, NextAction
from .service import ActivationService

logger = logging.getLogger("docket.jobs.tick")

# One page at a time, and every page: a tick that has fallen behind still has to reach the
# activation at the end of the queue, and holding the writer for the whole backlog in one
# statement is what a page size is for.
TICK_PAGE = 100
MAX_TICK_PAGES = 50
# A pass stops STARTING activations after this long and finishes the one in hand. One
# activation can legitimately take about thirteen minutes — eight sends each waiting up to
# ninety seconds for a receipt, plus a sweep — so a queue of them is unbounded in wall
# clock, and a `oneshot` unit with a finite `TimeoutStartSec` would be SIGTERMed somewhere
# in the middle rather than between two of them. The budget is where the pass chooses its
# own stopping point; the timer brings it back in a minute and it resumes at the front of
# the queue it did not reach.
PASS_BUDGET_SECONDS = 20 * 60
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


def _reconcile_reservations(session, rpc, pending_sends=()) -> bool:
    """Replace the remembered approvals with what the tokens actually say.

    Our record is of what we intended to grant; the allowance on the token is what can
    actually be pulled. An allowance somebody consumed while we were not looking would
    otherwise be held against the lifetime cap for ever, and one that failed to land would
    be held when nothing was ever granted.
    """
    before = session.reserved_atomic
    unresolved = set()
    failed = set()
    for entry in pending_sends:
        token = entry.get("approval_token")
        spender = entry.get("approval_spender")
        if not token or not spender:
            continue
        pair = (token, spender)
        tx_hash = entry.get("tx_hash")
        if not tx_hash:
            unresolved.add(pair)
            continue
        try:
            receipt = rpc(lambda w3, tx_hash=tx_hash: w3.eth.get_transaction_receipt(tx_hash))
        except Exception:
            receipt = None
        if receipt is None:
            unresolved.add(pair)
        elif int(receipt["status"]) != 1:
            failed.add(pair)
    live = {
        token: dict(spenders)
        for token, spenders in outstanding_allowances(session, rpc).items()
    }
    for token, spender in unresolved:
        amount = int((before.get(token) or {}).get(spender, 0))
        if amount:
            live.setdefault(token, {})[spender] = amount
    for token, spenders in before.items():
        for spender, amount in spenders.items():
            if (token, spender) in unresolved or (token, spender) in failed:
                continue
            decrease = int(amount) - int((live.get(token) or {}).get(spender, 0))
            if decrease > 0:
                session.spent_atomic[token] = session.spent_atomic.get(token, 0) + decrease
    session.reserved_atomic = live
    return before != live


def _session_for(service, activation, rpc):
    """The unlocked session, with every token a sweep has to look for filled in.

    Three sources, unioned, because each alone leaves money behind. The policy's own
    allowlist is what the session may SPEND, which is not what it can hold. The union kept
    on `session.received_tokens` is everything a past pass saw it receive — read from the
    activation, not from the last decision, because the last decision is overwritten every
    minute and a swap on one pass followed by a quiet pass would forget the output token
    entirely. And the category's default token table catches anything a service is known
    to touch that neither of the other two happened to name.
    """
    session = service.open_session(activation)
    if session is None:
        return None
    session.received_tokens = _sweepable_tokens(activation)
    session.reserved_atomic = {
        token: {spender: int(amount) for spender, amount in spenders.items()}
        for token, spenders in (
            (activation.session or {}).get("reserved_atomic") or {}
        ).items()
    }
    if session.reserved_atomic:
        _reconcile_reservations(
            session,
            rpc,
            (activation.result or {}).get("pending_sends", {}).values(),
        )
    return session


def _sweepable_tokens(activation) -> tuple[str, ...]:
    stored = (activation.session or {}).get("received_tokens") or ()
    try:
        defaults = defaults_for(activation.category)["token_allowlist"]
    except KeyError:
        defaults = ()
    seen = []
    for token in tuple(stored) + tuple(defaults):
        if token != NATIVE_TOKEN and token not in seen:
            seen.append(token)
    return tuple(seen)


def _remember_received(activation, decision, token_hints) -> None:
    """Add whatever this decision would pay the session to the durable union.

    From the executor's own evidence AND from the calldata, because an executor that
    forgets to declare an output token would otherwise strand it: the bytes say where the
    proceeds land whether or not anybody wrote it down.
    """
    found = list((activation.session or {}).get("received_tokens") or ())
    named = list(decision.evidence.get("received_tokens") or ())
    for call in decision.prepared:
        try:
            named.extend(received_tokens(call, token_hints=token_hints))
        except Exception:
            # A call whose bytes cannot be read is refused by `call_spend` a moment later
            # with a reason. It must not take the sweep list down with it here.
            continue
    for token in named:
        if token and token not in found:
            found.append(token)
    activation.session = {**(activation.session or {}), "received_tokens": found}


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
        # Approvals first. A session whose balances read zero but whose allowances stand
        # is one a spender can still pull from the moment that address is funded again,
        # and `revoked` would already have been served as the end of the story.
        zeroed = revoke_allowances(
            session, rpc, max_gas_price_wei=policy.max_gas_price_wei
        )
        if zeroed:
            activation.note(
                "set every outstanding approval to zero in " + ", ".join(zeroed),
                actor="chain",
            )
    except SweepFailed as exc:
        activation.note(f"the approvals were not fully revoked: {exc}", actor="docket")
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
    activation.session = {
        **(activation.session or {}),
        "reserved_atomic": {
            token: {spender: str(amount) for spender, amount in spenders.items()}
            for token, spenders in session.reserved_atomic.items()
        },
    }
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

    session = None
    if (activation.session or {}).get("reserved_atomic"):
        session = _session_for(service, activation, rpc)
    if session is not None:
        reconciled = {
            **(activation.session or {}),
            "spent_atomic": {
                token: str(amount) for token, amount in session.spent_atomic.items()
            },
            "reserved_atomic": {
                token: {spender: str(amount) for spender, amount in spenders.items()}
                for token, spenders in session.reserved_atomic.items()
            },
        }
        if reconciled != activation.session:
            activation.session = reconciled
            service.store.save_activation(activation, expected_updated_at=expected)
            expected = activation.updated_at

    decision = executor.evaluate(activation, reader=rpc)
    _record_decision(activation, decision)
    _remember_received(
        activation, decision, (decision.evidence.get("token_hints") or {})
    )
    if decision.kind in ("noop", "alert"):
        if decision.kind == "alert":
            activation.note(
                f"alert: {decision.summary} (block {decision.block})", actor="docket"
            )
        service.store.save_activation(activation, expected_updated_at=expected)
        return

    permitted, reason = executor.within_policy(activation, decision)
    if permitted and session is None:
        session = _session_for(service, activation, rpc)
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
            contract_allowlist=policy.contract_allowlist,
            token_hints=token_hints,
            owner=activation.owner,
            session=session.address,
            reserved_atomic=session.reserved_atomic,
        )
    except UnmeasuredSpend as exc:
        activation.note(
            f"the batch was not sent: unmeasured spend — {exc}", actor="docket"
        )
        service.store.save_activation(activation, expected_updated_at=expected)
        raise
    within_cap, cap_reason = policy.allows_total(
        spent=session.committed_atomic(), token_amounts=total
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

    # Rebound after every write, because `execute` persists before each broadcast and
    # the row's `updated_at` moves with it.
    checkpoint = {"at": expected}

    def persist() -> None:
        activation.session = {
            **(activation.session or {}),
            "spent_atomic": {
                token: str(amount) for token, amount in session.spent_atomic.items()
            },
            "reserved_atomic": {
                token: {spender: str(amount) for spender, amount in spenders.items()}
                for token, spenders in session.reserved_atomic.items()
            },
        }
        service.store.save_activation(
            activation, expected_updated_at=checkpoint["at"]
        )
        checkpoint["at"] = activation.updated_at

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
                    persist=persist,
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
        "reserved_atomic": {
            token: {spender: str(amount) for spender, amount in spenders.items()}
            for token, spenders in session.reserved_atomic.items()
        },
    }
    _save_sends(service.store, activation, checkpoint["at"])
    if failed is not None:
        raise failed


def _save_sends(store, activation, expected) -> None:
    """Write back a pass that broadcast transactions, never dropping what it sent.

    A `StaleActivation` here is the one case where losing the write would lose money: the
    transactions are already on chain, and their record lives on the row this save was
    refused. So the row is re-read and the send records, receipts and spend are merged
    onto whatever the other writer left, rather than the whole pass being discarded.
    """
    try:
        store.save_activation(activation, expected_updated_at=expected)
        return
    except StaleActivation as exc:
        stale = exc
    current = store.get_activation(activation.activation_id)
    if current is None:
        # The row was deleted underneath the pass. There is nothing to merge onto, and
        # the original refusal is the honest thing to report — a bare `raise` here would
        # be a RuntimeError about no active exception, which says nothing at all.
        raise stale
    # Captured before anything is merged onto it: the note below moves `updated_at`, and
    # writing the moved value back as the expectation would refuse the merge itself.
    current_updated_at = current.updated_at
    merged = dict(current.result or {})
    ours = dict(activation.result or {})
    merged["pending_sends"] = {
        **(merged.get("pending_sends") or {}),
        **(ours.get("pending_sends") or {}),
    }
    settled = list(merged.get("settled_sends") or ())
    seen = {entry.get("tx_hash") for entry in settled}
    for entry in ours.get("settled_sends") or ():
        if entry.get("tx_hash") not in seen:
            settled.append(entry)
    merged["settled_sends"] = settled
    if "last_decision" in ours:
        merged["last_decision"] = ours["last_decision"]
    current.result = merged
    known = {receipt.to_dict().get("output_hash") for receipt in current.receipts}
    for receipt in activation.receipts:
        if receipt.output_hash not in known:
            current.add_receipt(receipt)
    received = list((current.session or {}).get("received_tokens") or ())
    for token in (activation.session or {}).get("received_tokens") or ():
        if token not in received:
            received.append(token)
    reservations = {
        token: {spender: str(amount) for spender, amount in spenders.items()}
        for token, spenders in (
            (current.session or {}).get("reserved_atomic") or {}
        ).items()
    }
    for token, spenders in (
        (activation.session or {}).get("reserved_atomic") or {}
    ).items():
        held = dict(reservations.get(token) or {})
        for spender, amount in spenders.items():
            held[spender] = str(max(int(held.get(spender, 0)), int(amount)))
        reservations[token] = held
    current.session = {
        **(current.session or {}),
        "spent_atomic": (activation.session or {}).get("spent_atomic") or {},
        "reserved_atomic": reservations,
        "received_tokens": received,
    }
    current.note(
        "another writer reached this activation first; the transactions this pass "
        "broadcast were merged onto its record rather than dropped",
        actor="docket",
    )
    store.save_activation(current, expected_updated_at=current_updated_at)


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
    """Advance every live persistent activation. Returns how many errored.

    Bounded by wall clock, not by count. One activation can legitimately hold this pass
    for about thirteen minutes, so the queue behind it is unbounded in time; after
    `PASS_BUDGET_SECONDS` the pass stops STARTING new ones and finishes the one in hand.
    That is why the unit's `TimeoutStartSec` is `infinity`: a finite one would SIGTERM a
    pass somewhere inside a batch rather than between two activations, and the timer
    cannot start a second instance of a `oneshot` while one is running.
    """
    load_executors()
    service = ActivationService(
        store,
        services=SERVICES if services is None else services,
        rpc=rpc,
        environment=environment,
    )
    errors = 0
    started = time.monotonic()
    for activation in _live_activations(store):
        if time.monotonic() - started > PASS_BUDGET_SECONDS:
            logger.info(
                "pass budget of %ds reached; the rest of the queue waits for the next "
                "timer rather than being cut off mid-transaction",
                PASS_BUDGET_SECONDS,
            )
            break
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
