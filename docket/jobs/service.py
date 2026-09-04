"""Everything an activation can be asked to do, and what each answer costs.

The router above this file proves the owner asked. This file decides whether what they
asked for is legal, does it, and writes the result down. Nothing here reads a header or
returns a status code, and nothing in the router knows a state name — the split is
deliberate, because the state machine is the part that has to be testable without a
web server in front of it.

Three things are refused rather than assumed:

**A payment Docket did not itself take.** A one-shot activation on the paid tier binds an
`hire_payments` row the buyer settled through `POST /hire/{service_id}`. Binding checks
four facts — the row exists, it settled, it is bound to this service, and its `input_hash`
equals the canonical hash of these inputs — because a payment for different work is not
payment for this work however honestly it was made.

**A funding transfer Docket did not watch happen.** A persistent activation moves to
`funded` only when a mined receipt carries a log that matches the requirement: the right
token contract, the right event, the session address as the recipient, and at least the
amount asked for. A transaction hash on its own proves nothing.

**A session key with no master password.** `SessionsUnavailable` propagates. A persistent
activation that cannot be given a key is refused outright rather than created without one
and left looking live.
"""

import os
from datetime import UTC, datetime

from web3 import Web3
from web3.exceptions import TransactionNotFound

from ..hire.receipts import build_receipt, canonical_hash
from ..marketplace.registry import get_record
from ..sessions.keys import (
    Session,
    SessionsUnavailable,
    create_session_key,
    master_password_from_env,
    unlock,
)
from ..sessions.policy import SessionPolicy
from ..store import StaleActivation
from .auth import new_nonce
from .executors.allowlists import (
    FILLABLE_FIELDS,
    defaults_for,
)
from .executors.base import PreparedCall
from .models import (
    ONE_SHOT,
    PERSISTENT,
    Activation,
    IllegalTransition,
    NextAction,
    Quote,
    Receipt,
    new_activation_id,
)

# Event signatures, hashed here the way `escrow/settle.py` hashes its error signatures:
# from the text, so the constant and the thing it identifies cannot drift apart.
TRANSFER_TOPIC = "0x" + Web3.keccak(text="Transfer(address,address,uint256)").hex()
APPROVAL_TOPIC = "0x" + Web3.keccak(text="Approval(address,address,uint256)").hex()
# What the owner sends alongside the notional so the session can pay for its own gas.
# 0.01 BNB, which covers roughly a hundred router calls at the 0.05 gwei BSC has been
# settling at and is a small enough float to lose.
DEFAULT_GAS_ALLOWANCE_WEI = 10**16
# How long a browser is told to wait between polls while the tick does something it
# alone can do. The job timer runs every minute, so this is a poll, not a deadline.
SESSION_POLL_SECONDS = 5


class ActivationNotFound(LookupError):
    """No activation with this id exists."""


class UnknownService(LookupError):
    """No hireable service with this id, or none Docket declares a category for."""


class MissingFields(ValueError):
    """The request body omits a field the service's own schema requires."""

    def __init__(self, service_id: str, fields: list[str]) -> None:
        super().__init__(f"{service_id} requires {', '.join(fields)}")
        self.fields = fields


class PolicyViolation(ValueError):
    """Something offered as proof does not bind to what it was offered for."""


class ActivationExpired(ValueError):
    """The policy's own expiry has passed; the activation is closed."""


class SimulationFailed(ValueError):
    """A prepared call the chain refused. It is not handed to a browser to sign."""


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _log_field(value) -> str:
    if isinstance(value, (bytes, bytearray)):
        return "0x" + bytes(value).hex()
    text = str(value)
    return (text if text.startswith("0x") else "0x" + text).lower()


def _receipt_or_none(tx_hash):
    """A reader that answers None for a transaction the chain has not mined.

    Returned as a closure so the `TransactionNotFound` is swallowed inside the retrying
    wrapper rather than outside it: not-yet-mined is an answer, not an outage, and it
    must not cost a walk over every endpoint to hear.
    """

    def read(w3):
        try:
            return w3.eth.get_transaction_receipt(tx_hash)
        except TransactionNotFound:
            return None

    return read


def _topic_address(topic: str) -> str:
    """The 20-byte address inside a 32-byte indexed topic."""
    return "0x" + topic[-40:]


class ActivationService:
    """The state machine, its side effects, and nothing about HTTP."""

    def __init__(
        self,
        store,
        *,
        services,
        rpc=None,
        now=None,
        pay_to=None,
        master_password=None,
        environment=None,
    ) -> None:
        self.store = store
        self.services = services
        self.rpc = rpc
        self.now = _now if now is None else now
        self.pay_to = pay_to
        self._master_password = master_password
        self._environment = os.environ if environment is None else environment

    # -- reading ---------------------------------------------------------------

    def get(self, activation_id: str) -> Activation:
        activation = self.store.get_activation(activation_id)
        if activation is None:
            raise ActivationNotFound(activation_id)
        return activation

    def prepared_calls(self, activation_id: str) -> tuple[PreparedCall, ...]:
        """The calls the browser is being asked to sign, if the chain agreed to them.

        A call whose stored simulation says the chain refused it is never handed over. It
        would be signed, sent, and reverted at the owner's expense, and the owner would
        have no way to know Docket already knew.
        """
        activation = self.get(activation_id)
        calls = tuple(
            PreparedCall.from_dict(call)
            for call in activation.next_action.detail.get("calls", ())
        )
        refused = [call for call in calls if not call.simulation.get("ok")]
        if refused:
            raise SimulationFailed(
                f"{len(refused)} of {len(calls)} prepared calls did not simulate: "
                + "; ".join(
                    f"{call.purpose}: "
                    f"{call.simulation.get('revert_reason') or 'no reason recorded'}"
                    for call in refused
                )
            )
        return calls

    # -- creating --------------------------------------------------------------

    def quote(self, service_id, kind, owner, inputs, policy) -> Activation:
        """Price the work and draft the activation, touching nothing.

        Returns an unsaved activation in `quoted`. `create` is this plus the owner's
        proof and a row; keeping them apart means a caller can be shown the terms before
        it signs anything, which is the whole point of a quote.
        """

        service = self.services.get(service_id)
        record = get_record(service_id)
        if service is None or record is None or record.category is None:
            raise UnknownService(service_id)
        if kind not in (ONE_SHOT, PERSISTENT):
            raise ValueError(
                f"unknown activation kind {kind!r}; expected one_shot or persistent"
            )
        if not isinstance(inputs, dict):
            raise ValueError("inputs must be a JSON object")
        missing = [
            name
            for name, field in service.input_schema.items()
            if field.get("required") and inputs.get(name) is None
        ]
        if missing:
            raise MissingFields(service_id, missing)

        session_policy = None
        policy_source = None
        if kind == PERSISTENT:
            session_policy, policy_source = self.resolve_policy(
                record.category.value, policy
            )
        elif policy is not None:
            raise PolicyViolation(
                "a one-shot activation reads and returns; it holds no session key, so a "
                "session policy would bound nothing"
            )

        # Priced only where a price can actually be collected: the x402 rail settles one
        # request against one authorization, and there is no shape in it for a standing
        # session. A persistent activation is therefore quoted free rather than quoted a
        # figure nothing in this build would ever charge.
        if kind == ONE_SHOT and service.paid_stock and self.pay_to:
            quote = Quote(
                asset=service.asset,
                amount_atomic=str(service.price_atomic),
                amount_display=service.price_display,
                pay_to=self.pay_to,
                payment_scheme="x402-exact",
            )
        else:
            quote = Quote(
                asset=service.asset,
                amount_atomic="0",
                amount_display="free",
                pay_to=None,
                payment_scheme="free_tier",
            )

        moment = self.now()
        return Activation(
            activation_id=new_activation_id(),
            service_id=service_id,
            category=record.category.value,
            kind=kind,
            owner=Web3.to_checksum_address(owner),
            state="quoted",
            quote=quote,
            policy=(
                None
                if session_policy is None
                else {**session_policy.to_dict(), "policy_source": policy_source}
            ),
            session=None,
            inputs=inputs,
            result=None,
            receipts=(),
            events=(),
            next_action=NextAction(
                "connect_wallet",
                {"message": "sign the create message with the owner wallet"},
            ),
            auth_nonce=new_nonce(),
            created_at=moment,
            updated_at=moment,
            expires_at=None if session_policy is None else session_policy.expires_at,
        )

    def resolve_policy(self, category, policy) -> tuple[SessionPolicy, str]:
        """The bounds this session will run under, and where they came from.

        A browser cannot compose a `contract_allowlist` for a category it did not write:
        which contracts a rebalancing session has to call is a property of the work Docket
        does, not of the owner's intentions. So a body that leaves the three allowlists out
        gets this category's own, from the same table the executors act against, and the
        activation records that they were Docket's rather than the owner's.

        Everything else the caller sent is kept and validated as sent. Filling in an
        allowlist is answering a question the caller could not have answered; overriding a
        cap they did set would be answering one they already had.
        """
        if policy is None:
            policy = {}
        if not isinstance(policy, dict):
            raise PolicyViolation("policy must be a JSON object")
        try:
            defaults = defaults_for(category)
        except KeyError as exc:
            raise PolicyViolation(
                f"Docket publishes no session defaults for {category}"
            ) from exc
        filled = [field for field in FILLABLE_FIELDS if not policy.get(field)]
        merged = {**{field: defaults[field] for field in filled}, **policy}
        for field, value in defaults.items():
            merged.setdefault(field, value)
        if "expires_at" not in merged:
            raise PolicyViolation(
                "a session policy must say when it expires; Docket does not choose how "
                "long to hold somebody's money"
            )
        session_policy = SessionPolicy.from_dict(merged)
        session_policy.validate()
        source = "docket_defaults" if len(filled) == len(FILLABLE_FIELDS) else (
            "owner" if not filled else "mixed"
        )
        return session_policy, source

    def validate_request(
        self, service_id, *, kind, owner, inputs, policy=None, nft_approvals=()
    ) -> None:
        """Everything `create` would refuse, checked without writing anything.

        Called before the nonce is spent. A malformed body used to cost the caller its
        signature: the nonce was consumed, then the policy was rejected, and the owner had
        to sign again for a mistake the server could have caught first.
        """
        activation = self.quote(service_id, kind, owner, inputs, policy)
        if kind == PERSISTENT:
            self._checked_approvals(
                SessionPolicy.from_dict(activation.policy), nft_approvals
            )

    def create(
        self, service_id, *, kind, owner, inputs, policy=None, nft_approvals=()
    ) -> Activation:
        """Persist a quoted activation the owner has already proved it asked for.

        The signature is verified by the router before this is called, and the walk
        through `awaiting_wallet` to `authorized` records that: the owner's wallet is the
        thing that connected, and the recovered signature is what authorized it.
        """
        activation = self.quote(service_id, kind, owner, inputs, policy)
        moment = self.now()
        activation.transition(
            "awaiting_wallet",
            reason="the owner's wallet was named and a create message issued",
            actor="user",
            at=moment,
        )
        activation.transition(
            "authorized",
            reason=f"the create signature recovered to {activation.owner}",
            actor="docket",
            at=moment,
        )

        if kind == PERSISTENT:
            # No key is minted here, and this process could not mint one: it never reads
            # the session master password. The tick does, on its next pass. Until then the
            # activation says so rather than showing an address that does not exist.
            activation.transition(
                "awaiting_session",
                reason=(
                    "the owner authorized a session; Docket's job runner will create the "
                    "key on its next pass"
                ),
                actor="docket",
                at=moment,
            )
            activation.session = None
            activation.next_action = NextAction(
                "wait",
                {
                    "reason": "session being created",
                    "poll_seconds": SESSION_POLL_SECONDS,
                    "nft_approvals": [
                        {
                            "contract": approval["contract"],
                            "token_id": str(approval["token_id"]),
                        }
                        for approval in self._checked_approvals(
                            SessionPolicy.from_dict(activation.policy), nft_approvals
                        )
                    ],
                },
            )
        elif activation.quote.payment_scheme == "x402-exact":
            activation.next_action = NextAction(
                "sign_payment",
                {
                    "resource": f"/hire/{service_id}",
                    "asset": activation.quote.asset,
                    "amount_atomic": activation.quote.amount_atomic,
                    "pay_to": activation.quote.pay_to,
                    "then": (
                        "settle the x402 hire, then approve this activation with the "
                        "payment_id the hire returned"
                    ),
                },
            )
        else:
            activation.next_action = NextAction(
                "none",
                {"then": "approve this activation to run it on the free tier"},
            )

        self.store.create_activation(activation)
        return activation

    def mint_session(self, activation) -> None:
        """Give one `awaiting_session` activation its key. Runs only in the tick.

        The whole point of the split: a web process that never holds the master password
        cannot be made to hand out a session key, however it is talked into misbehaving.
        The key exists in one process, on one timer, behind one file the operator owns.
        """
        policy = SessionPolicy.from_dict(activation.policy)
        # A pass killed between writing the row and saving the activation leaves a key
        # that exists and an activation that does not know about it. Minting a second one
        # would strand the first for ever, so an unrevoked row is adopted, not replaced.
        existing = self.store.get_session(activation.activation_id)
        if existing and existing["revoked_at"] is None:
            address = existing["address"]
            activation.note(
                f"adopting the session key {address}, which an earlier pass created "
                "before it could record it",
                actor="docket",
                at=self.now(),
            )
        else:
            address, keystore_json = create_session_key(self.master_password())
            self.store.create_session(
                activation.activation_id,
                address=address,
                keystore_json=keystore_json,
            )
        activation.session = {
            "address": address,
            "funded_atomic": {},
            "spent_atomic": {},
        }
        approvals = (activation.next_action.detail or {}).get("nft_approvals") or ()
        activation.next_action = self._funding_action(activation, policy, approvals)
        activation.note(
            f"the session key {address} was created; it holds only what the owner funds "
            "it with",
            actor="docket",
            at=self.now(),
        )

    # -- mutating --------------------------------------------------------------

    def approve(self, activation_id, *, tx_hash=None, payment_id=None) -> Activation:
        """Take the owner's proof and move as far as it justifies."""
        activation, expected = self._load_open(activation_id)
        if activation.kind == PERSISTENT:
            if activation.state == "paused":
                activation.transition(
                    "active",
                    reason="the owner resumed the session",
                    actor="user",
                    at=self.now(),
                )
                activation.next_action = NextAction(
                    "wait", {"then": "Docket's tick evaluates this session again"}
                )
            elif activation.state == "needs_approval":
                self._apply_signed_action(activation, tx_hash)
            else:
                self._apply_funding(activation, tx_hash)
        elif activation.quote.payment_scheme == "x402-exact":
            self._bind_payment(activation, payment_id)
        else:
            self._run_free_tier(activation)
        self.store.save_activation(activation, expected_updated_at=expected)
        return activation

    def pause(self, activation_id) -> Activation:
        activation, expected = self._load_open(activation_id)
        activation.transition(
            "paused",
            reason="the owner paused the session; Docket sends nothing while it is paused",
            actor="user",
            at=self.now(),
        )
        activation.next_action = NextAction(
            "none", {"then": "approve this activation to resume it"}
        )
        self.store.save_activation(activation, expected_updated_at=expected)
        return activation

    def cancel(self, activation_id) -> Activation:
        """Stop an activation before it finishes.

        A one-shot that has not run yet is refunded — nothing was charged, and the state
        says so rather than implying money moved. A persistent one is revoked, because
        cancelling a session that holds a float without returning the float would leave
        the owner worse off than not cancelling.
        """
        activation, expected = self._load_open(activation_id)
        if activation.kind == PERSISTENT:
            self._begin_closing(
                activation,
                closing_to="revoked",
                reason="the owner cancelled the session",
                actor="user",
            )
        else:
            activation.transition(
                "refunded",
                reason=(
                    "the owner cancelled before the work ran; nothing was settled and "
                    "nothing is owed"
                ),
                actor="user",
                at=self.now(),
            )
            activation.next_action = NextAction("none", {})
        self.store.save_activation(activation, expected_updated_at=expected)
        return activation

    def revoke(self, activation_id) -> Activation:
        activation, expected = self._load_open(activation_id)
        self._begin_closing(
            activation,
            closing_to="revoked",
            reason="the owner revoked the session",
            actor="user",
        )
        self.store.save_activation(activation, expected_updated_at=expected)
        return activation

    def expire(self, activation_id) -> Activation:
        """Mark a session whose policy has run out for closing. The tick sweeps it."""
        activation, expected = self._load_open(activation_id, check_expiry=False)
        self._expire(activation)
        self.store.save_activation(activation, expected_updated_at=expected)
        return activation

    # -- internals -------------------------------------------------------------

    def _load_open(self, activation_id, *, check_expiry=True):
        activation = self.get(activation_id)
        expected = activation.updated_at
        if activation.is_terminal:
            raise IllegalTransition(
                f"{activation_id} is {activation.state} and cannot be changed further"
            )
        if check_expiry and self.has_expired(activation):
            self._expire(activation)
            self.store.save_activation(activation, expected_updated_at=expected)
            raise ActivationExpired(
                f"{activation_id} expired at {activation.expires_at}"
            )
        return activation, expected

    def has_expired(self, activation) -> bool:
        if activation.expires_at is None:
            return False
        return datetime.now(UTC) >= datetime.fromisoformat(
            activation.expires_at
        )

    def _expire(self, activation) -> None:
        self._begin_closing(
            activation,
            closing_to="expired",
            reason=f"the session policy expired at {activation.expires_at}",
            actor="docket",
        )

    def _begin_closing(self, activation, *, closing_to, reason, actor) -> None:
        """Record that closing was asked for. It is not the end of the story.

        Nothing is swept here. This runs in the web process, which holds no key and can
        open no session, so it would be free to say "revoked" while the float sat at an
        address nobody could reach. The activation goes to `revoking` instead, and the
        tick has to prove the balances are back before it may say anything stronger.
        """
        activation.transition(
            "revoking",
            reason=f"{reason}; the float is swept and verified before this closes",
            actor=actor,
            at=self.now(),
        )
        activation.next_action = NextAction(
            "wait",
            {
                "reason": "returning the session float to the owner",
                "poll_seconds": SESSION_POLL_SECONDS,
                "closing_to": closing_to,
            },
        )

    def finish_closing(self, activation, residual) -> bool:
        """Close a `revoking` activation, but only against balances that read zero.

        `residual` is what the session still holds, read at a block after the sweep. A
        sweep that was broadcast is not a sweep that landed, and "we sent it" is the
        weaker claim of the two — so the state that means "your money is back" is only
        reachable from a reading that says it is.
        """
        closing_to = (activation.next_action.detail or {}).get("closing_to") or "revoked"
        if residual:
            activation.note(
                "still holding "
                + ", ".join(
                    f"{amount} of {token}" for token, amount in sorted(residual.items())
                )
                + "; the sweep is retried on the next pass",
                actor="chain",
                at=self.now(),
            )
            return False
        self.store.mark_session_revoked(activation.activation_id)
        activation.transition(
            closing_to,
            reason="the session holds nothing: every balance read zero after the sweep",
            actor="chain",
            at=self.now(),
        )
        activation.next_action = NextAction("none", {})
        return True

    def open_session(self, activation) -> Session | None:
        row = self.store.get_session(activation.activation_id)
        if not row or row["revoked_at"] is not None:
            return None
        policy = SessionPolicy.from_dict(activation.policy)
        stored = activation.session or {}
        return Session(
            address=row["address"],
            account=unlock(row["keystore_json"], self.master_password()),
            funded_atomic={
                token: int(amount)
                for token, amount in (stored.get("funded_atomic") or {}).items()
            },
            spent_atomic={
                token: int(amount)
                for token, amount in (stored.get("spent_atomic") or {}).items()
            },
            token_allowlist=tuple(policy.token_allowlist),
        )

    def master_password(self) -> str:
        if self._master_password is None:
            self._master_password = master_password_from_env(self._environment)
        return self._master_password

    def _require_rpc(self):
        if self.rpc is None:
            raise SessionsUnavailable(
                "this process has no RPC configured, so nothing on chain can be read or "
                "sent for an activation"
            )
        return self.rpc

    def _funding_action(self, activation, policy, nft_approvals) -> NextAction:
        """What the owner has to send before the session can act.

        One requirement per capped token, sized at the cap: the cap is the loss ceiling,
        and funding above it would put money at the session address that no bound
        protects. NFT approvals are named by the caller and are checked against the
        policy's own contract allowlist, so an activation cannot ask an owner to approve
        a contract its session may not call.
        """
        requirements = [
            {
                "kind": "fund_session",
                "token": Web3.to_checksum_address(token),
                "amount_atomic": str(amount),
                "satisfied": False,
                "tx_hash": None,
            }
            for token, amount in sorted(policy.total_cap_atomic.items())
            if token != "BNB"
        ]
        for approval in self._checked_approvals(policy, nft_approvals):
            requirements.append(
                {
                    "kind": "approve_nft",
                    "contract": approval["contract"],
                    "token_id": str(approval["token_id"]),
                    "satisfied": False,
                    "tx_hash": None,
                }
            )
        return self._pending_funding(activation, requirements)

    def _checked_approvals(self, policy, nft_approvals) -> list[dict]:
        """Every NFT approval the caller asked for, checked against the policy.

        Checked at create time rather than when the tick builds the funding step, so a
        caller learns its request is impossible in the response to that request instead of
        a minute later in an event nobody is watching.
        """
        if isinstance(nft_approvals, (str, bytes)) or not isinstance(
            nft_approvals, (list, tuple)
        ):
            raise PolicyViolation("nft_approvals must be a list of objects")
        allowed = {
            Web3.to_checksum_address(address) for address in policy.contract_allowlist
        }
        checked = []
        for approval in nft_approvals:
            if not isinstance(approval, dict) or not {
                "contract",
                "token_id",
            } <= approval.keys():
                raise PolicyViolation(
                    "every nft approval must name a contract and a token_id"
                )
            try:
                contract = Web3.to_checksum_address(approval["contract"])
                token_id = int(approval["token_id"])
            except Exception as exc:
                raise PolicyViolation(
                    f"nft approval {approval!r} does not name a contract and a token id"
                ) from exc
            if contract not in allowed:
                raise PolicyViolation(
                    f"{contract} is not in the policy's contract allowlist, so the "
                    "session could not use an approval on it"
                )
            checked.append({"contract": contract, "token_id": token_id})
        return checked

    def _pending_funding(self, activation, requirements) -> NextAction:
        outstanding = [item for item in requirements if not item["satisfied"]]
        if not outstanding:
            return NextAction(
                "wait",
                {"then": "Docket's tick evaluates this session on its next pass"},
            )
        kind = (
            "fund_session"
            if any(item["kind"] == "fund_session" for item in outstanding)
            else "approve_nft"
        )
        return NextAction(
            kind,
            {
                "session_address": activation.session["address"],
                "gas_allowance_wei": str(DEFAULT_GAS_ALLOWANCE_WEI),
                "requirements": requirements,
            },
        )

    def _mined_receipt(self, tx_hash) -> dict:
        """The receipt for one transaction, or a refusal a caller can act on.

        A hash the chain has not mined yet is the ordinary case, not an exception: an
        owner who approves a second after sending has done nothing wrong. web3 raises
        `TransactionNotFound` for it, and the failover in `escrow.chain.Rpc` would turn
        that into a multi-endpoint retry and then a `RuntimeError` no route knows how to
        translate. Caught here so it comes back as one sentence naming both readings —
        not yet mined, or the node did not answer — because from off chain the two are
        genuinely indistinguishable.
        """
        try:
            # `TransactionNotFound` is caught inside the callable, not outside it. The
            # failover in `escrow.chain.Rpc` retries every endpoint on any exception, so
            # letting it out here would walk four nodes with pauses between them to
            # rediscover the ordinary answer "not mined yet" — on the request path, while
            # an owner waits.
            receipt = self._require_rpc()(_receipt_or_none(tx_hash))
        except SessionsUnavailable:
            raise
        except Exception as exc:
            raise PolicyViolation(
                f"{tx_hash} is not a mined transaction Docket could read: it is not "
                f"mined yet, or no node answered ({type(exc).__name__}). Nothing moved; "
                "approve again once it has landed."
            ) from exc
        if receipt is None:
            raise PolicyViolation(
                f"{tx_hash} has no receipt on chain, so it is not mined yet. Nothing "
                "moved; approve again once it has landed."
            )
        return receipt

    def _apply_funding(self, activation, tx_hash) -> None:
        if not tx_hash:
            raise PolicyViolation(
                "a persistent activation moves to funded only against a mined "
                "transaction; approve it with the tx_hash of the funding transfer"
            )
        requirements = list(activation.next_action.detail.get("requirements", ()))
        if not requirements:
            raise IllegalTransition(
                f"{activation.activation_id} has no outstanding funding requirement"
            )
        receipt = self._mined_receipt(tx_hash)
        if int(receipt["status"]) != 1:
            raise PolicyViolation(
                f"{tx_hash} did not succeed on chain, so it funds nothing"
            )
        logs = [
            {
                "address": Web3.to_checksum_address(log["address"]),
                "topics": [_log_field(topic) for topic in log["topics"]],
                "data": _log_field(log["data"]),
            }
            for log in receipt["logs"]
        ]
        session_address = Web3.to_checksum_address(activation.session["address"])
        matched = None
        for requirement in requirements:
            if requirement["satisfied"]:
                continue
            if self._log_satisfies(requirement, logs, session_address):
                requirement["satisfied"] = True
                requirement["tx_hash"] = _log_field(tx_hash)
                matched = requirement
                break
        if matched is None:
            raise PolicyViolation(
                f"{tx_hash} carries no log matching an outstanding requirement of "
                f"{activation.activation_id}"
            )

        moment = self.now()
        if matched["kind"] == "fund_session":
            funded = dict(activation.session.get("funded_atomic") or {})
            funded[matched["token"]] = matched["amount_atomic"]
            activation.session = {**activation.session, "funded_atomic": funded}
            activation.note(
                f"{tx_hash} funded the session with {matched['amount_atomic']} of "
                f"{matched['token']}",
                actor="chain",
                at=moment,
            )
        else:
            activation.note(
                f"{tx_hash} approved token {matched['token_id']} of "
                f"{matched['contract']} to the session",
                actor="chain",
                at=moment,
            )

        activation.next_action = self._pending_funding(activation, requirements)
        if all(item["satisfied"] for item in requirements):
            activation.transition(
                "funded",
                reason="every funding requirement is satisfied on chain",
                actor="chain",
                at=moment,
            )
            activation.transition(
                "active",
                reason="the session is funded and Docket's tick will evaluate it",
                actor="docket",
                at=moment,
            )

    def _apply_signed_action(self, activation, tx_hash) -> None:
        """Close the loop on an action the owner signed themselves.

        The tick hands an owner a prepared call when the session may not send it. What
        comes back is a transaction hash, and the same rule applies as to funding: a hash
        is not evidence. The receipt has to be mined and successful before the session
        goes back to active, or a reverted attempt would read as a completed one.
        """
        if not tx_hash:
            raise PolicyViolation(
                "this activation is waiting on a transaction the owner signs; approve "
                "it with the tx_hash of that transaction"
            )
        receipt = self._mined_receipt(tx_hash)
        if int(receipt["status"]) != 1:
            raise PolicyViolation(
                f"{tx_hash} did not succeed on chain, so the action did not happen"
            )
        prepared = activation.next_action.detail.get("calls", ())
        self._proves_a_prepared_call(activation, tx_hash, prepared)
        moment = self.now()
        activation.add_receipt(
            Receipt(
                service=activation.service_id,
                input_hash=canonical_hash(list(prepared)),
                output_hash=canonical_hash(
                    {
                        "tx_hash": _log_field(tx_hash),
                        "block_number": int(receipt["blockNumber"]),
                        "status": int(receipt["status"]),
                    }
                ),
                delivered_at=moment,
                payment=None,
                execution={
                    "tx_hash": _log_field(tx_hash),
                    "status": int(receipt["status"]),
                    "gas_used": int(receipt["gasUsed"]),
                    "block_number": int(receipt["blockNumber"]),
                    "signed_by": "owner",
                    "purpose": activation.next_action.detail.get(
                        "purpose", "an action the owner signed"
                    ),
                },
            )
        )
        activation.transition(
            "active",
            reason=f"the owner signed and sent {tx_hash}, which succeeded on chain",
            actor="chain",
            at=moment,
        )
        activation.next_action = NextAction(
            "wait", {"then": "Docket's tick evaluates this session on its next pass"}
        )

    def _proves_a_prepared_call(self, activation, tx_hash, prepared) -> None:
        """Whether this transaction is one of the calls Docket actually asked for.

        A mined, successful transaction is not evidence on its own: any transaction the
        owner happened to send would satisfy that, including one to somewhere else
        entirely. So the sender, the target and the calldata are read back and compared
        against what was handed over to be signed. Docket asked for a specific action; a
        different action is a different thing, however well it succeeded.
        """
        if not prepared:
            return
        transaction = self._require_rpc()(
            lambda w3: w3.eth.get_transaction(tx_hash)
        )
        if transaction is None:
            raise PolicyViolation(
                f"{tx_hash} has a receipt and no transaction body, so what it did cannot "
                "be checked against what was asked for"
            )
        sender = _log_field(transaction["from"])
        target = _log_field(transaction["to"])
        data = _log_field(transaction["input"])
        if sender != _log_field(activation.owner):
            raise PolicyViolation(
                f"{tx_hash} was sent by {transaction['from']}, not by this activation's "
                "owner"
            )
        for call in prepared:
            if target == _log_field(call["to"]) and data == _log_field(call["data"]):
                return
        raise PolicyViolation(
            f"{tx_hash} calls {transaction['to']} with bytes that are not any of the "
            f"{len(prepared)} calls Docket prepared, so it is not the action that was "
            "approved"
        )

    def _log_satisfies(self, requirement, logs, session_address) -> bool:
        if requirement["kind"] == "fund_session":
            token = Web3.to_checksum_address(requirement["token"])
            wanted = int(requirement["amount_atomic"])
            return any(
                log["address"] == token
                and len(log["topics"]) == 3
                and log["topics"][0] == TRANSFER_TOPIC
                and Web3.to_checksum_address(_topic_address(log["topics"][2]))
                == session_address
                and len(log["data"]) > 2
                and int(log["data"], 16) >= wanted
                for log in logs
            )
        contract = Web3.to_checksum_address(requirement["contract"])
        token_id = int(requirement["token_id"])
        return any(
            log["address"] == contract
            and len(log["topics"]) == 4
            and log["topics"][0] == APPROVAL_TOPIC
            and Web3.to_checksum_address(_topic_address(log["topics"][2]))
            == session_address
            and int(log["topics"][3], 16) == token_id
            for log in logs
        )

    def _bind_payment(self, activation, payment_id) -> None:
        if not payment_id:
            raise PolicyViolation(
                "this activation is priced, so approving it needs the payment_id of a "
                "settled hire"
            )
        payment = self.store.payment_by_id(payment_id)
        if not payment:
            raise PolicyViolation(f"no payment {payment_id} is recorded")
        if payment["status"] != "settled":
            raise PolicyViolation(
                f"payment {payment_id} is {payment['status']}, not settled"
            )
        if payment["service_id"] != activation.service_id:
            raise PolicyViolation(
                f"payment {payment_id} bought {payment['service_id']}, not "
                f"{activation.service_id}"
            )
        if payment["input_hash"] != canonical_hash(activation.inputs):
            raise PolicyViolation(
                f"payment {payment_id} is bound to a different request body"
            )
        if payment["payer"].lower() != activation.owner.lower():
            raise PolicyViolation(
                f"payment {payment_id} was made by {payment['payer']}, not by this "
                "activation's owner"
            )
        receipt = payment.get("receipt")
        result = payment.get("result")
        if not isinstance(receipt, dict) or not isinstance(result, dict):
            raise PolicyViolation(
                f"payment {payment_id} settled without a stored result and receipt"
            )

        moment = self.now()
        activation.transition(
            "paid_or_reserved",
            reason=f"bound to settled payment {payment_id}",
            actor="user",
            at=moment,
        )
        activation.transition(
            "queued",
            reason="the paid result is ready to deliver",
            actor="docket",
            at=moment,
        )
        activation.transition(
            "running", reason="delivering the settled result", actor="docket", at=moment
        )
        activation.result = result
        activation.add_receipt(Receipt.from_hire(receipt))
        activation.transition(
            "completed",
            reason=f"delivered against payment {payment_id}",
            actor="docket",
            at=moment,
        )
        activation.next_action = NextAction("none", {})

    def _run_free_tier(self, activation) -> None:
        service = self.services.get(activation.service_id)
        if service is None:
            raise UnknownService(activation.service_id)
        moment = self.now()
        activation.transition(
            "paid_or_reserved",
            reason="the free tier reserves the run; nothing is charged",
            actor="docket",
            at=moment,
        )
        activation.transition(
            "queued", reason="queued to run", actor="docket", at=moment
        )
        activation.transition(
            "running",
            reason=f"running {activation.service_id}",
            actor="docket",
            at=moment,
        )
        try:
            result = service.run(activation.inputs)
            receipt = build_receipt(
                activation.service_id, activation.inputs, result, payment=None
            )
        except Exception as exc:
            activation.transition(
                "failed",
                reason=f"{activation.service_id} failed: {type(exc).__name__}: {exc}",
                actor="docket",
                at=self.now(),
            )
            activation.next_action = NextAction("none", {})
            return
        activation.result = result
        activation.add_receipt(Receipt.from_hire(receipt))
        activation.transition(
            "completed",
            reason=f"{activation.service_id} returned a result",
            actor="docket",
            at=self.now(),
        )
        activation.next_action = NextAction("none", {})


__all__ = [
    "ActivationExpired",
    "ActivationNotFound",
    "ActivationService",
    "IllegalTransition",
    "MissingFields",
    "PolicyViolation",
    "SessionsUnavailable",
    "SimulationFailed",
    "StaleActivation",
    "UnknownService",
]
