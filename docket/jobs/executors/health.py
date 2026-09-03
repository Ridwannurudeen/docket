"""The health-factor executor: one Venus account, watched, and the least remedy for it.

The official category reads "Protects lending positions from liquidation". This is what
performs it, and it performs it by doing arithmetic and preparing calls — never by
claiming an outcome. `agents/venus/guard.py` bans the vocabulary of a counterfactual from
everything it emits and the same rule holds here: a liquidation that did not happen is not
something anybody observed, so nothing below says a position was made safer or that
anything was avoided. It says the derived ratio was X at block B, that retiring Y of debt
puts it at Z, and here are the bytes that would retire Y.

**Venus publishes no health factor.** Every ratio here is Docket's own, derived by the
formula `guard.RATIO_METHOD` states. `min_health_factor` appears only as an alias carrying
that sentence with it.

**A simulation that reverts is never an action.** A call the chain refused comes back as
`alert` with the revert reason; a call the chain could not be asked about comes back as
`alert` too, because an unread preflight is not a passed one. The approval is put to the
chain; the call that spends under it is marked `deferred` against the approval rather than
reported as a failure, since it cannot succeed until that has landed.

**What the session may spend travels in the evidence.** `SessionPolicy.allows` is handed
`evidence["token_amounts"]` and `evidence["slippage_bps"]`, and sees zero spend without
them. The spend is read out of the approval this batch actually makes. The slippage is
zero, and that is a fact rather than an omission: neither `repayBorrowBehalf` nor `mint`
takes a minimum-out argument, so there is no price in either call to slip against.

**A collateral add is the owner's own transaction.** `mint(uint256)` credits its caller and
has no on-behalf form, so a session sending it would buy vTokens for itself while the
borrower's collateral stayed where it was. Both of its calls carry `owner_signs`, and
`within_policy` therefore asks nothing of the session about them.
"""

from ...agents.venus.markets import VenusReader
from ...agents.venus.shield import (
    ShieldPolicy,
    evaluate as shield_evaluate,
    rescue_calls,
)
from ...escrow.chain import Rpc
from . import register
from .base import Decision
from .bounds import (
    defer,
    now_utc,
    token_spend,
    policy_field,
    simulate_call,
    with_simulation,
    within_session_policy,
)

CATEGORY = "health_factor"
# The derived collateral ratio a request asks for when it names none. 1.25 leaves a
# quarter of the debt in weighted collateral above the point at which Venus reports a
# shortfall, which is where an account is liquidatable now.
DEFAULT_MIN_COLLATERAL_RATIO = 1.25
DEFAULT_MODE = "repay"


def shield_policy(activation) -> ShieldPolicy:
    """The shield's bounds, taken from the session policy where it has an opinion.

    Only the expiry is shared with the session: the ratio, the markets and the per-token
    caps are this service's own, because a session policy bounds what may leave a wallet
    and says nothing about what a lending position should look like.
    """
    inputs = activation.inputs or {}
    return ShieldPolicy(
        min_collateral_ratio=float(
            inputs.get("min_collateral_ratio", DEFAULT_MIN_COLLATERAL_RATIO)
        ),
        max_rescue_atomic={
            str(token): int(cap)
            for token, cap in (inputs.get("max_rescue_atomic") or {}).items()
        },
        allowed_vtokens=tuple(inputs.get("allowed_vtokens") or ()),
        mode=str(inputs.get("mode", DEFAULT_MODE)),
        expires_at=policy_field(
            activation.policy, "expires_at", inputs.get("expires_at")
        )
        or activation.expires_at,
    )


class HealthShieldExecutor:
    """Watches one Venus account and prepares the least remedy the policy permits."""

    category = CATEGORY

    def __init__(self, *, rpc=None, clock=now_utc) -> None:
        self._rpc = rpc
        self._clock = clock

    def _rpc_handle(self):
        return self._rpc if self._rpc is not None else Rpc()

    def evaluate(self, activation, *, reader=None) -> Decision:
        inputs = activation.inputs or {}
        now = self._clock()
        # `docket/jobs/tick.py` hands `evaluate` the loop's own `escrow.chain.Rpc` — a
        # bare callable, not a reader — so the reader is built from it here. `VenusReader`
        # already takes an `rpc=`, so no wrapper is needed. A reader object passed straight
        # in is used as given, which is the seam the tests read through.
        if reader is None:
            reader, rpc = VenusReader(), self._rpc_handle()
        elif hasattr(reader, "account"):
            rpc = self._rpc_handle()
        else:
            rpc = self._rpc if self._rpc is not None else reader
            reader = VenusReader(rpc=reader)
        state = reader.account(inputs["wallet"])
        policy = shield_policy(activation)
        decision = shield_evaluate(state, policy, now=now)
        evidence = dict(decision.evidence)
        try:
            gas_price_wei = int(rpc(lambda w3: w3.eth.gas_price))
        except Exception as exc:
            gas_price_wei = 0
            evidence["gas_price_unavailable"] = f"{type(exc).__name__}: {exc}"
        evidence["gas_price_wei"] = str(gas_price_wei)
        evidence["token_amounts"] = {}
        # Neither Venus write takes a minimum-out argument, so there is no price in
        # either call to slip against. Zero is the fact, not a default nobody set.
        evidence["slippage_bps"] = 0
        evidence["slippage_bps_means"] = (
            "repayBorrowBehalf and mint take no minimum-out argument, so no part of "
            "this remedy is exposed to a price moving between drafting and landing"
        )

        if decision.kind != "action":
            return Decision(
                kind=decision.kind,
                summary=decision.summary,
                prepared=(),
                evidence=evidence,
                observed_at=now.isoformat(),
                block=state.as_of_block,
            )

        owner_signs_only = decision.remedy["mode"] == "add_collateral"
        session = (activation.session or {}).get("address")
        if session is None and not owner_signs_only:
            return Decision(
                kind="alert",
                summary=(
                    decision.summary
                    + " No session address exists on this activation yet, so no call is "
                    "prepared: the owner funds a session before Docket can repay on their "
                    "behalf."
                ),
                prepared=(),
                evidence=evidence,
                observed_at=now.isoformat(),
                block=state.as_of_block,
            )

        # The borrower is the account that was read, not whoever created the activation:
        # `repayBorrowBehalf` names the account whose debt is retired, and building that
        # calldata from a different address would retire somebody else's.
        calls = rescue_calls(
            state,
            decision,
            session=session or state.address,
            borrower=state.address,
        )
        # A collateral add credits its sender, so the only address for which sending it
        # changes anything is the borrower's own.
        sender = state.address if owner_signs_only else session
        approve, spend = calls
        record, outcome = simulate_call(approve, sender=sender, rpc=rpc)
        prepared = (
            with_simulation(approve, record),
            with_simulation(
                spend,
                defer(
                    spend,
                    depends_on=(
                        f"{approve.purpose} and on {sender} holding "
                        f"{decision.remedy['amount_atomic']} atomic units of "
                        f"{decision.remedy['underlying']}"
                    ),
                    block=record["block"] or 0,
                ),
            ),
        )
        evidence["preflight"] = {
            "verdict": outcome,
            "reason": record["revert_reason"]
            or "the approval the remedy spends under was accepted at this block",
            "block": record["block"],
            "simulated_from": sender,
        }
        evidence["token_amounts"] = token_spend(prepared)
        if outcome != "passed":
            # No prepared calls on an alert. A batch whose approval the chain refused is
            # not a batch anybody may send, and `Decision` refuses to carry one.
            return Decision(
                kind="alert",
                summary=(
                    decision.summary
                    + " The prepared calls were not offered: "
                    + f"{approve.purpose}: {record['revert_reason']}"
                ),
                prepared=(),
                evidence=evidence,
                observed_at=now.isoformat(),
                block=state.as_of_block,
            )
        return Decision(
            kind="action",
            summary=decision.summary,
            prepared=prepared,
            evidence=evidence,
            observed_at=now.isoformat(),
            block=state.as_of_block,
        )

    def within_policy(self, activation, decision: Decision) -> tuple[bool, str]:
        """Whether the session the owner granted covers every call this decision offers."""
        gas_price = int(decision.evidence.get("gas_price_wei") or 0)
        return within_session_policy(
            activation.policy,
            decision.prepared,
            gas_price_wei=gas_price,
            now=self._clock(),
        )


register(CATEGORY, HealthShieldExecutor())

__all__ = [
    "CATEGORY",
    "HealthShieldExecutor",
    "shield_policy",
]
