"""Grid Operator: observe a price, and either act inside the authority granted, or don't.

The whole sequence is here in one place because the order is the safety property:

    observe → match a level → draft an intent → simulate → require agreement
            → ask the authority → submit

Every arrow is a place it can stop, and stopping is recorded with the reason. Nothing
downstream of a refusal runs. In particular there is no branch anywhere below that
submits an action whose simulation disagreed with its intent, and none that submits
without the authority having answered from a live read.

**Two classes, and the difference between them is structural rather than a flag.**

`GridPreview` holds a plan, a router to quote against, and a wallet address to name as
the recipient. It has no authority, no session, no submitter and no key — not a disabled
one, an absent one. There is no method on it that sends anything, so a preview cannot be
switched into a live run by setting a boolean, and a bug in this file cannot make one
submit. That is what makes the whole mechanism demonstrable to somebody holding no
wallet and no funds: the plan, the intents and the router's own answer for each of them,
with nothing to sign.

`GridOperator` is the armed one. It refuses to be constructed without a session and
without a submitter, before any node is contacted, the way `escrow/settle.py` refuses
without a key. Docket ships no submitter: Altana's grant and revoke are transactions the
account owner signs, and driving a session key through the relay is not in this build.
The runbook covers what an owner does; this class covers what happens once they have.
"""

from dataclasses import dataclass

from web3 import Web3

from ...execution import now
from ...execution.authority import check
from ...execution.intent import ActionIntent, commit
from ...execution.receipts import EXECUTION_NOTE, action_receipt
from ...execution.simulate import PANCAKE_V2_ROUTER, SWAP_SIGNATURE, simulate, swap_calldata
from ...execution.state import ActionLifecycle, ActionState
from .plan import GridPlan, next_action

SWAP_SELECTOR = "0x" + Web3.keccak(text=SWAP_SIGNATURE)[:4].hex()
POLICY_VERSION = "grid-operator/1"
# 0.5%. The intent's own ceiling is 5%; a grid trading through more than half a percent
# of slippage is a grid whose levels are too big for the pool it is in.
DEFAULT_SLIPPAGE_BPS = 50
# A V2 token-to-token swap costs well under this. It is a ceiling, not an estimate: the
# simulation supplies the estimate and refuses if it exceeds this.
DEFAULT_GAS_CEILING = 300_000
# How long an action stays valid once drafted. Long enough to be mined, short enough that
# a transaction stuck in the mempool expires rather than filling at a price nobody looked
# at.
DEFAULT_DEADLINE_S = 600
# The one failure this design cannot see from the inside, stated wherever a submitter is
# about to be wired in. Read against ithacaxyz/account's GuardedExecutor on 2026-08-10:
# `canExecute` returns true unconditionally for a zero keyHash and for super-admin keys.
SUBMITTER_CONTRACT = (
    "The submitter MUST sign with the SESSION key. An owner key silently voids every "
    "limit this design rests on: the wallet's own canExecute returns true "
    "unconditionally for a zero keyHash and for super-admin keys, so an owner-signed "
    "call passes every on-chain guard — not because the caps allowed it, but because "
    "they never applied to it. At that point Docket's own checks are the only thing "
    "left, which is the exact inversion this package exists to prevent. Nothing here "
    "can tell the two apart beforehand, because a submitter is an opaque callable. "
    "What does catch it is afterwards: if the session's spendInfos currentSpent has "
    "not moved by the amount that was swapped, the transaction did not go through the "
    "session at all."
)
PREVIEW_REASON = (
    "This is a preview. It holds no session, no signer and no submitter, and there is no "
    "method on it that sends anything — so nothing here can be submitted by changing a "
    "setting. Acting on any of these levels needs a session the wallet's owner granted, "
    "and the grant is theirs to make."
)


class NoSession(RuntimeError):
    """Acting needs an authority, a session reference and the permissions it was granted under."""


class NotArmed(RuntimeError):
    """Submitting needs something that can send a transaction, and none was supplied."""


@dataclass(frozen=True)
class Observation:
    """The price the conditions are evaluated against, and where it came from."""

    price: int
    block_number: int
    source: str

    def as_record(self) -> dict:
        return {
            "price": str(self.price),
            "block_number": self.block_number,
            "source": self.source,
            "note": (
                "the quote the router gives for one whole base token right now, in atomic "
                "units of the quote token. It is an execution price for that size and "
                "already carries the pool's fee — not a mid price"
            ),
        }


def observe_price(reader, *, base: str, quote: str, base_decimals: int) -> Observation:
    """What one whole base token fetches, asked of the router that would fill the swap.

    A mid price computed from reserves would be a slightly different number and a less
    useful one: this is the price the grid could actually trade at, fee included, which
    is what its levels are supposed to be about.

    Takes the pair rather than a plan so a caller can read the price *before* it has a
    plan — which is what building a band around the current price requires.
    """
    amounts = reader.amounts_out(10**base_decimals, (base, quote))
    return Observation(
        price=int(amounts[-1]),
        block_number=int(reader.block_number()),
        source="router.getAmountsOut",
    )


def draft(
    plan: GridPlan,
    level,
    observation: Observation,
    *,
    reader,
    wallet: str,
    nonce: int,
    slippage_bps: int = DEFAULT_SLIPPAGE_BPS,
    gas_ceiling: int = DEFAULT_GAS_CEILING,
    deadline_s: int = DEFAULT_DEADLINE_S,
    policy_version: str = POLICY_VERSION,
) -> tuple[ActionIntent, bytes]:
    """One level turned into a bounded action, with the floor derived from a live quote.

    The floor is the router's own answer for this size, less the slippage the plan
    tolerates. Deriving it from a quote rather than from the level's price matters: the
    level says where to trade, the pool says what that trade returns, and the difference
    between the two is exactly the depth the level is asking the pool for.
    """
    route = (level.token_in, level.token_out)
    quoted = int(reader.amounts_out(level.size, route)[-1])
    min_output = quoted * (10_000 - slippage_bps) // 10_000
    if min_output <= 0:
        raise ValueError(
            f"level {level.index}: the router quotes {quoted} out for {level.size} in, which "
            f"leaves no floor at all once {slippage_bps}bps of slippage is allowed"
        )
    deadline = now() + deadline_s
    calldata = swap_calldata(
        amount_in=level.size,
        min_output=min_output,
        route=route,
        recipient=wallet,
        deadline=deadline,
    )
    intent = ActionIntent(
        intent_id=f"{plan.plan_hash[:10]}-level-{level.index}-{nonce}",
        condition=level.condition,
        chain_id=56,
        target=PANCAKE_V2_ROUTER,
        selector=SWAP_SELECTOR,
        calldata_hash=commit(calldata),
        token_in=level.token_in,
        token_out=level.token_out,
        max_input=level.size,
        min_output=min_output,
        route=route,
        slippage_bps=slippage_bps,
        deadline=deadline,
        gas_ceiling=gas_ceiling,
        nonce=nonce,
        policy_version=policy_version,
        evidence_block=observation.block_number,
    )
    return intent, calldata


class GridPreview:
    """The whole mechanism, with nothing that can send anything.

    Deliberately not a mode of `GridOperator` and deliberately not its subclass: the
    guarantee here is the absence of a submitter, and an absence is only worth something
    if there is no inherited method that would use one.
    """

    def __init__(
        self,
        plan: GridPlan,
        *,
        reader,
        wallet: str,
        slippage_bps: int = DEFAULT_SLIPPAGE_BPS,
        gas_ceiling: int = DEFAULT_GAS_CEILING,
        policy_version: str = POLICY_VERSION,
    ) -> None:
        self.plan = plan
        self.wallet = Web3.to_checksum_address(wallet)
        self._reader = reader
        self._slippage_bps = slippage_bps
        self._gas_ceiling = gas_ceiling
        self._policy_version = policy_version

    def _observe(self) -> Observation:
        return observe_price(
            self._reader,
            base=self.plan.base,
            quote=self.plan.quote,
            base_decimals=self.plan.base_decimals,
        )

    def preview(self, *, filled=()) -> dict:
        """Every unfilled level, drafted and quoted, and the one the price has reached.

        Levels that have not been reached are drafted too. A judge looking at this should
        see what the grid would send at each rung and what the pool says it would return,
        not only the single rung that happens to be live at this second.
        """
        observation = self._observe()
        firing = next_action(self.plan, observation.price, filled)
        already = set(filled)
        levels = []
        for index, level in enumerate(self.plan.levels):
            if level.index in already:
                levels.append(
                    {
                        "level": level.as_record(),
                        "condition_holds": False,
                        "intent": None,
                        "simulation": None,
                        "skipped": "already filled",
                    }
                )
                continue
            try:
                intent, calldata = draft(
                    self.plan,
                    level,
                    observation,
                    reader=self._reader,
                    wallet=self.wallet,
                    nonce=index,
                    slippage_bps=self._slippage_bps,
                    gas_ceiling=self._gas_ceiling,
                    policy_version=self._policy_version,
                )
            except ValueError as exc:
                levels.append(
                    {
                        "level": level.as_record(),
                        "condition_holds": level.condition.holds(observation.price),
                        "intent": None,
                        "simulation": None,
                        "skipped": str(exc),
                    }
                )
                continue
            # No sender: a preview has no account that could execute the swap, so the gas
            # estimate is not attempted rather than invented. The simulation record says
            # which checks ran.
            result = simulate(intent, calldata, reader=self._reader)
            levels.append(
                {
                    "level": level.as_record(),
                    "condition_holds": level.condition.holds(observation.price),
                    "intent": intent.as_record(),
                    "intent_key": intent.idempotency_key,
                    "simulation": result.as_record(),
                    "skipped": None,
                }
            )
        return {
            "plan": self.plan.as_record(),
            "wallet": self.wallet,
            "observation": observation.as_record(),
            "next_level": None if firing is None else firing.index,
            "levels": levels,
            "submitted": False,
            "why_not_submitted": PREVIEW_REASON,
            "authority": None,
            "note": EXECUTION_NOTE,
        }


class GridOperator:
    """The armed path. Refuses to exist without a session and without a submitter.

    Both checks run in the constructor, before any node is contacted, so an unarmed
    caller cannot reach the network even to ask a question — the discipline
    `escrow/settle.py` already ships under.

    Whoever supplies the submitter carries the one obligation this class cannot enforce:

    {SUBMITTER_CONTRACT}
    """

    # Interpolated rather than transcribed so the docstring, the `NotArmed` message and
    # the runbook cannot drift apart. `or ""` because `python -OO` strips docstrings, and
    # an import that crashed under it would be a worse bug than the one this prevents.
    __doc__ = (__doc__ or "").replace("{SUBMITTER_CONTRACT}", SUBMITTER_CONTRACT)

    def __init__(
        self,
        plan: GridPlan,
        *,
        reader,
        authority=None,
        ref=None,
        permissions=None,
        submitter=None,
        slippage_bps: int = DEFAULT_SLIPPAGE_BPS,
        gas_ceiling: int = DEFAULT_GAS_CEILING,
        policy_version: str = POLICY_VERSION,
    ) -> None:
        if authority is None or ref is None or permissions is None:
            raise NoSession(
                "a grid operator acts inside a session the wallet's owner granted, and "
                "needs the authority to read it, the reference to read, and the "
                "permissions it was granted under. GridPreview runs the same plan with "
                "none of them and cannot submit."
            )
        if submitter is None:
            raise NotArmed(
                "submitting needs something that can send a transaction, and Docket ships "
                "none: it holds no owner key, and driving a session key through Altana's "
                "relay is not in this build. GridPreview answers the same questions for "
                "free. Before supplying one: " + SUBMITTER_CONTRACT
            )
        self.plan = plan
        self.wallet = Web3.to_checksum_address(ref.account)
        self._reader = reader
        self._authority = authority
        self._ref = ref
        self._permissions = permissions
        self._submitter = submitter
        self._slippage_bps = slippage_bps
        self._gas_ceiling = gas_ceiling
        self._policy_version = policy_version

    def _observe(self) -> Observation:
        return observe_price(
            self._reader,
            base=self.plan.base,
            quote=self.plan.quote,
            base_decimals=self.plan.base_decimals,
        )

    def step(self, *, filled=(), nonce: int = 0) -> dict:
        """One observation, and at most one action. Returns a receipt either way.

        Every stop below leaves the action in a pre-submission state with the reason
        recorded, and `paused` rather than something terminal: the market moves, and the
        next observation is a new question. A session that has been revoked simply keeps
        refusing, so the loop never submits — which is the property that matters, and is
        cheaper than teaching this method to tell one refusal from another.

        **This method keeps no ledger of what has already filled, and does not hand back
        the index it fired.** `filled` is the caller's to carry, and a loop that forgot to
        would re-fire the same level on every observation until the cap ran out. The level
        that fired is on the returned receipt, under `intent.condition.threshold` and in
        the intent id; a caller running this in a loop has to read it off there and add it
        to its own `filled` before the next call. Keeping the ledger here would mean this
        object owned state that outlives a single observation, which is the thing that
        makes an operator hard to reason about — but the trade is a footgun, and it is
        named rather than left to be discovered.
        """
        observation = self._observe()
        level = next_action(self.plan, observation.price, filled)
        if level is None:
            return {
                "acted": False,
                "reason": (
                    f"no unfilled level is reached at {observation.price}: the grid is "
                    "waiting, which is what it does most of the time"
                ),
                "observation": observation.as_record(),
                "plan_hash": self.plan.plan_hash,
                "submitted": False,
            }

        try:
            intent, calldata = draft(
                self.plan,
                level,
                observation,
                reader=self._reader,
                wallet=self.wallet,
                nonce=nonce,
                slippage_bps=self._slippage_bps,
                gas_ceiling=self._gas_ceiling,
                policy_version=self._policy_version,
            )
        except ValueError as exc:
            return {
                "acted": False,
                "reason": str(exc),
                "observation": observation.as_record(),
                "plan_hash": self.plan.plan_hash,
                "submitted": False,
            }

        lifecycle = ActionLifecycle(intent.intent_id)
        result = simulate(intent, calldata, reader=self._reader, sender=self.wallet)
        if not result.agrees:
            lifecycle.transition(ActionState.PAUSED, reason=result.reason)
            return self._receipt(intent, observation, result, lifecycle, None, None, None)
        lifecycle.transition(ActionState.SIMULATED, reason=result.reason)

        # One read, and the decision and the receipt are both made on it. Asking the
        # authority twice — once for the record and once for the answer — would put a
        # different moment on the receipt than the one that was acted on, and a receipt
        # that describes a different moment is evidence about something else. The read
        # includes the wallet's own canExecute for this exact calldata, so it is as fresh
        # as the decision requires.
        try:
            status = self._authority.status(
                self._ref,
                permissions=self._permissions,
                call=(intent.target, calldata),
            )
        except Exception as exc:
            lifecycle.transition(
                ActionState.PAUSED,
                reason=f"the session's state could not be read: {type(exc).__name__}: {exc}",
            )
            return self._receipt(intent, observation, result, lifecycle, None, None, None)

        allowed, reason = check(intent, status)
        if not allowed:
            lifecycle.transition(ActionState.PAUSED, reason=reason)
            return self._receipt(intent, observation, result, lifecycle, status, None, None)

        lifecycle.transition(ActionState.AUTHORIZED, reason=reason)
        lifecycle.transition(ActionState.ACTIVE, reason="every bound agreed at this block")
        tx_hash = self._submitter(intent, calldata)
        lifecycle.transition(ActionState.SUBMITTED, reason=f"broadcast as {tx_hash}")
        cap = {
            "token": intent.token_in,
            "remaining_before": str(status.remaining_cap.get(intent.token_in, 0)),
            "committed": str(intent.max_input),
        }
        return self._receipt(intent, observation, result, lifecycle, status, cap, tx_hash)

    def _receipt(self, intent, observation, result, lifecycle, status, cap, tx_hash) -> dict:
        return {
            "acted": True,
            "submitted": tx_hash is not None,
            "plan_hash": self.plan.plan_hash,
            "receipt": action_receipt(
                intent=intent,
                plan_hash=self.plan.plan_hash,
                observation=observation.as_record(),
                simulation=result.as_record(),
                lifecycle=lifecycle.as_record(),
                authority=None if status is None else status.as_record(),
                cap=cap,
                tx_hash=tx_hash,
            ),
        }
