"""The rebalancing executor: one position, watched, and the calls that reset its range.

The official category reads "Manages LP ranges, resets positions automatically". This is
what performs it. Every tick it reads the position and its pool at one block, hands both
to `agents/pancake/keeper.evaluate`, and — when the keeper says a reset is due — builds
the calls, puts each of them to the chain as an `eth_call` and an `eth_estimateGas`, and
returns them with what the chain said attached.

**A simulation that reverts is never an action.** The whole point of the preflight is that
a batch which cannot land does not reach a signer. A call the chain refused comes back as
`alert` carrying the revert reason; a call that could not be put to the chain at all comes
back as `alert` too, because an unread preflight is not a passed one.

**A call is simulated when its preconditions hold, and deferred when they do not.** The
close and the collect are asked of the chain from the position's holder, who is authorised
over the token whichever way the approval went; the approvals are asked from the session,
which needs no balance to grant one. The swap and the mint spend tokens the collect has
not released yet, so at this block they would revert for a reason that says nothing about
whether they are right — `TRANSFER_FROM_FAILED` from a session holding nothing is not a
finding. Those two carry `ok: None` and name the call they wait on. Simulating them anyway
would end every real tick as an alert, and reporting a dependency as a refusal is the same
mistake as reporting an outage as one. `docket/sessions/executor.py` re-simulates every
call from its real sender immediately before sending it, which is the check that matters.

**The owner's ERC-721 approval is not a prepared call.** Lane B's loop sends everything in
`decision.prepared` from the session, and an ERC-721 approval sent by anyone but the NFT's
holder reverts. So the approval is read rather than drafted: `getApproved` and
`isApprovedForAll` decide whether the session may act at all, and an unapproved position
comes back as an `alert` carrying `evidence["needs_nft_approval"]` for the browser step
that collects it.

**Observations persist through the activation's own result.** Time out of range can only
be measured against earlier readings, and a persistent executor is stateless between
passes. So each evaluation returns the list it built under `evidence["observations"]` and
reads the previous one back from `result.last_decision.evidence`, which
`docket/jobs/tick.py` writes on every pass including a noop. A position outside its range
with nothing carried forward still says so in its own summary, because the first pass of a
new watch and a watch whose carry-over broke look identical from the outside.

**What the session may spend travels in the evidence.** `SessionPolicy.allows` is handed
`evidence["token_amounts"]` and `evidence["slippage_bps"]`, and sees zero spend without
them. Both are derived here from the calldata that is actually being offered rather than
carried beside it.
"""

from web3 import Web3

from ...agents.pancake.keeper import (
    Q192,
    SWAP_NOTE,
    KeeperPolicy,
    npm_approval_reader,
    npm_encoder,
    rebalance_calls,
    recost_swap,
    swap_plan,
)
from ...agents.pancake.keeper import (
    evaluate as keeper_evaluate,
)
from ...agents.pancake.pools import PoolClient, is_plausible
from ...agents.pancake.positions import NPM, PositionReader
from ...escrow.chain import Rpc
from ...execution.simulate import BscQuoteReader
from . import register
from .base import Decision, PreparedCall
from .bounds import (
    carried_evidence,
    defer,
    now_utc,
    policy_field,
    simulate_call,
    token_spend,
    touched_tokens,
    with_simulation,
    within_session_policy,
)

CATEGORY = "rebalancing"
# Which call each deferred one waits on. A call that spends tokens the close has not
# released yet cannot be asked of the chain at this block, and naming what it waits on is
# the difference between "not yet" and "no".
_COLLECT = "session_collects_to_fund_the_swap_and_the_mint"
_SWAPS = (
    "session_balances_the_inventory_on_v2",
    "session_balances_the_inventory_on_v3",
)


def _waits_on(purpose: str, *, resuming: bool) -> str | None:
    """Which call in this batch a call cannot be asked about ahead of, if any.

    On a resumed batch the collect is not in the list at all — the session already holds
    the inventory — so the swap has nothing to wait for and is put to the chain like any
    other call. Deferring it against a call that is not there would report a preflight
    nobody could ever satisfy, and would hide a swap that genuinely cannot land. The mint
    still waits on the swap either way: it spends what the swap has not delivered yet.
    """
    if purpose in _SWAPS:
        return None if resuming else _COLLECT
    if purpose == "session_mints_replacement_to_owner":
        return (
            "the swap that precedes it"
            if resuming
            else f"{_COLLECT} and the swap that follows it"
        )
    return None
# How long a prepared batch stays valid. Ten minutes is `venus/guard.py`'s own default and
# is long enough for an owner to sign in a browser without being long enough for the price
# the minimums were computed against to become historical.
DEADLINE_S = 600
# How many prior observations travel forward. Enough to date a departure many ticks old
# without letting an activation's result grow without bound.
MAX_OBSERVATIONS = 288

# What a request supplies when it says nothing. Each matches the field's default in the
# catalogue's request schema, so a caller who accepted the defaults there gets the same
# policy here.
DEFAULT_OUT_OF_RANGE_MINUTES = 60
DEFAULT_MIN_NET_BENEFIT_MULTIPLE = 2.0
DEFAULT_MAX_SLIPPAGE_BPS = 50
DEFAULT_MAX_GAS_PRICE_WEI = 5_000_000_000
DEFAULT_MAX_NOTIONAL_USD = 1_000.0

def keeper_policy(activation) -> KeeperPolicy:
    """The keeper's bounds, taken from the session policy where it has an opinion.

    Three of the seven fields belong to the session the owner granted rather than to this
    service — its slippage bound, its gas ceiling and its expiry — so those are read from
    `activation.policy` first and fall back to the request only where no session exists.
    A bound that lived in two places and disagreed would be enforced by whichever copy the
    reader happened to look at.
    """
    inputs = activation.inputs or {}
    policy = activation.policy
    band = inputs.get("band_width_ticks")
    return KeeperPolicy(
        out_of_range_minutes=int(
            inputs.get("out_of_range_minutes", DEFAULT_OUT_OF_RANGE_MINUTES)
        ),
        min_net_benefit_multiple=float(
            inputs.get("min_net_benefit_multiple", DEFAULT_MIN_NET_BENEFIT_MULTIPLE)
        ),
        max_slippage_bps=int(
            policy_field(
                policy,
                "max_slippage_bps",
                inputs.get("max_slippage_bps", DEFAULT_MAX_SLIPPAGE_BPS),
            )
        ),
        max_gas_price_wei=int(
            policy_field(
                policy,
                "max_gas_price_wei",
                inputs.get("max_gas_price_wei", DEFAULT_MAX_GAS_PRICE_WEI),
            )
        ),
        max_notional_usd=float(
            inputs.get("max_notional_usd", DEFAULT_MAX_NOTIONAL_USD)
        ),
        band_width_ticks=None if band is None else int(band),
        expires_at=policy_field(policy, "expires_at", inputs.get("expires_at"))
        or activation.expires_at,
    )


def read_position(wallet, token_id, *, reader, pools, observation_block=None) -> dict:
    """One position, its pool and the pool's fee row, all at one block.

    The same three reads `doctor.report` makes for a single position, taken directly
    because the keeper needs the plausibility-gated pool row that `report` consumes
    internally and does not hand back. Everything is pinned to the block the wallet was
    read at, so the range and the price it is judged against are one moment.
    """
    read = reader.wallet_positions(
        wallet, token_id=int(token_id), observation_block=observation_block
    )
    if not read["positions"]:
        return {"read": read, "position": None, "pool": None, "pool_stats": None}
    position = read["positions"][0]
    pool = reader.pool_state(
        position["token0"],
        position["token1"],
        position["fee"],
        observation_block=read["observation_block"],
        archive_first=observation_block is not None,
    )
    pool_stats = None
    address = str(pool.get("address") or "").lower()
    if address:
        allowlist = pools.token_allowlist()
        row = next(
            (r for r in pools.top_pools() if str(r.get("id") or "").lower() == address),
            None,
        )
        if row is not None:
            ok, reason = is_plausible(row, allowlist)
            pool_stats = {"row": row, "plausible": ok, "reason": reason}
    return {"read": read, "position": position, "pool": pool, "pool_stats": pool_stats}


class _RpcPositionReader(PositionReader):
    """A `PositionReader` whose every read runs through a supplied `Rpc`.

    `VenusReader` already takes an `rpc=` and needs no wrapper; `PositionReader` has only
    an injected-`Web3` seam, which an `Rpc` is not. Overriding the one method both of its
    public reads funnel through is narrower than reaching into either of them, and it is
    what lets the tick loop's own failover — rather than a second connection pool this
    module opened for itself — carry the position read.
    """

    def __init__(self, rpc) -> None:
        super().__init__()
        self._through = rpc

    def _call(self, do, *, observation_block=None):
        return self._through(do)


class RangeKeeperExecutor:
    """Watches one v3 position and prepares the reset when the policy says one is due."""

    category = CATEGORY

    def __init__(self, *, pools=None, rpc=None, quotes=None, clock=now_utc) -> None:
        self._pools = pools
        self._rpc = rpc
        self._quotes = quotes
        self._clock = clock

    def _pool_client(self):
        return self._pools if self._pools is not None else PoolClient()

    def _rpc_handle(self):
        return self._rpc if self._rpc is not None else Rpc()

    def _position_reader(self, reader):
        """The position reader for this pass, and the RPC to run everything else through.

        `docket/jobs/tick.py` hands `evaluate` the loop's own `escrow.chain.Rpc` — a bare
        callable, not a reader — so the readers are built from it here. A reader object
        passed straight in is used as given, which is the seam the tests read through.
        """
        if reader is None:
            return PositionReader(), self._rpc_handle()
        if hasattr(reader, "wallet_positions"):
            return reader, self._rpc_handle()
        rpc = self._rpc if self._rpc is not None else reader
        return _RpcPositionReader(reader), rpc

    def _quote_handle(self, rpc):
        """The router quote source, the seam `agents/grid/operator.py` reads through.

        `BscQuoteReader.amounts_out` is a view call that needs no balance, no approval
        and no account, so the leg can be priced at a block where the session holds
        nothing at all — which is every block before the burn lands.
        """
        if self._quotes is not None:
            return self._quotes
        return BscQuoteReader(rpc=rpc)

    def evaluate(self, activation, *, reader=None) -> Decision:
        inputs = activation.inputs or {}
        now = self._clock()
        reader, rpc = self._position_reader(reader)
        state = read_position(
            inputs["wallet"],
            inputs["token_id"],
            reader=reader,
            pools=self._pool_client(),
            # A persistent watch always reads the head. A pinned block is a
            # reproducibility lever for a one-off diagnosis; on a watch it would freeze
            # every tick at one moment and the position would never appear to move.
            observation_block=(
                None if activation.kind == "persistent" else inputs.get("observation_block")
            ),
        )
        read = state["read"]
        observations = list(carried_evidence(activation).get("observations") or [])
        if state["position"] is None:
            return Decision(
                kind="alert",
                summary=(
                    f"Position {inputs['token_id']} was not found among the "
                    f"{read['positions_held']} PancakeSwap v3 position NFTs "
                    f"{inputs['wallet']} holds at block {read['observation_block']}."
                ),
                prepared=(),
                evidence={"read": read, "observations": observations},
                observed_at=read["observation_time"],
                block=read["observation_block"],
            )

        position = dict(state["position"])
        if inputs.get("declared_position_value_usd") is not None:
            position["declared_position_value_usd"] = float(
                inputs["declared_position_value_usd"]
            )
        try:
            policy = keeper_policy(activation)
        except (ValueError, KeyError, TypeError) as exc:
            # A request whose policy will not construct is a misconfigured watch, not a
            # crash: the tick loop would otherwise count it as an error every five minutes
            # and the owner would see nothing saying why.
            return Decision(
                kind="alert",
                summary=(
                    f"This watch's policy is not usable, so nothing was evaluated: "
                    f"{type(exc).__name__}: {exc}."
                ),
                prepared=(),
                evidence={"read": read, "observations": observations},
                observed_at=read["observation_time"],
                block=read["observation_block"],
            )
        try:
            gas_price_wei = int(rpc(lambda w3: w3.eth.gas_price))
        except Exception as exc:
            return Decision(
                kind="alert",
                summary=(
                    f"Position {position['token_id']}'s reset could not be priced: the gas "
                    f"price could not be read ({type(exc).__name__}: {exc})."
                ),
                prepared=(),
                evidence={"read": read, "observations": observations},
                observed_at=read["observation_time"],
                block=read["observation_block"],
            )

        session_address = ((activation.session or {}).get("address") or "").strip()
        if position["liquidity"] == 0 and session_address:
            # A closed position whose tokens are still in the session is a reset that
            # stopped halfway, not a position with nothing left to do.
            try:
                position["session_inventory"] = session_inventory(
                    position, session=session_address, rpc=rpc
                )
            except Exception as exc:
                evidence_note = f"{type(exc).__name__}: {exc}"
                position["session_inventory_unreadable"] = evidence_note

        decision = keeper_evaluate(
            position,
            state["pool"],
            state["pool_stats"],
            policy,
            history=observations,
            now=now,
            gas_price_wei=gas_price_wei,
            bnb_usd=float(inputs.get("bnb_usd") or 0.0),
        )
        observations = (
            observations
            + [
                {
                    "observed_at": read["observation_time"],
                    "block": read["observation_block"],
                    "tick": (state["pool"] or {}).get("tick"),
                    "in_range": (decision.evidence.get("diagnosis") or {}).get(
                        "in_range", True
                    ),
                }
            ]
        )[-MAX_OBSERVATIONS:]
        evidence = dict(decision.evidence)
        evidence["observations"] = observations
        evidence["gas_price_wei"] = str(gas_price_wei)
        evidence["swap_note"] = SWAP_NOTE

        if decision.kind != "action":
            summary = decision.summary
            if decision.evidence.get("resuming"):
                held = decision.evidence["resuming"]["session_inventory"]
                summary += (
                    " This position is already burnt and its inventory is sitting in "
                    f"Docket's session ({held['token0']} of token0, {held['token1']} of "
                    "token1). It stays there until the reset completes or the session is "
                    "revoked, which sweeps it back to you."
                )
            # A staked position never reaches a diagnosis, so both keys are read
            # defensively rather than assumed.
            diagnosed = decision.evidence.get("diagnosis") or {}
            timing = decision.evidence.get("time_out_of_range") or {}
            if (
                diagnosed.get("in_range") is False
                and timing.get("prior_observations") == 0
            ):
                summary += (
                    " No earlier observation is carried forward on this activation yet, so "
                    "no elapsed time outside the range is claimed — the first pass of a "
                    "watch has nothing to measure against."
                )
            return Decision(
                kind=decision.kind,
                summary=summary,
                prepared=(),
                evidence=evidence,
                observed_at=read["observation_time"],
                block=read["observation_block"],
            )

        # An empty string is not an address. Lane B writes the session record before the
        # key exists, so `{"address": ""}` is the shape of "not funded yet".
        session = ((activation.session or {}).get("address") or "").strip()
        if not session:
            return Decision(
                kind="alert",
                summary=(
                    decision.summary
                    + " No session address exists on this activation yet, so no call is "
                    "prepared: the owner funds a session before Docket can send anything."
                ),
                prepared=(),
                evidence=evidence,
                observed_at=read["observation_time"],
                block=read["observation_block"],
            )

        token0 = Web3.to_checksum_address(position["token0"])
        token1 = Web3.to_checksum_address(position["token1"])
        holder = Web3.to_checksum_address(inputs["wallet"])
        try:
            approved = session_may_move(
                position, holder=holder, session=session, rpc=rpc
            )
        except Exception as exc:
            approved = None
            evidence["nft_approval_unreadable"] = f"{type(exc).__name__}: {exc}"
        if approved is not True:
            # The approval is the owner's to make and no session can make it for them, so
            # it is reported rather than drafted. Lane B's funding step reads this.
            evidence["needs_nft_approval"] = {
                "contract": NPM,
                "token_id": position["token_id"],
                "session": Web3.to_checksum_address(session),
                "holder": holder,
            }
            return Decision(
                kind="alert",
                summary=(
                    decision.summary
                    + f" Docket's session {session} is not approved over position NFT "
                    f"{position['token_id']}, so no call is prepared. Approve it from the "
                    "wallet that holds the position — only its holder can — and the watch "
                    "prepares the reset on its next pass."
                ),
                prepared=(),
                evidence=evidence,
                observed_at=read["observation_time"],
                block=read["observation_block"],
            )

        try:
            prepared, sim_evidence = self._prepare(
                position=position,
                pool=state["pool"],
                decision=decision,
                policy=policy,
                holder=holder,
                session=session,
                now=now,
                rpc=rpc,
            )
        except Exception as exc:
            # A quote that could not be taken is not a reset that was refused. Reporting it
            # as an action would offer minimums computed from nothing.
            evidence["preflight"] = {
                "verdict": "unreadable",
                "reason": f"{type(exc).__name__}: {exc}",
                "block": None,
                "amounts": None,
            }
            return Decision(
                kind="alert",
                summary=(
                    decision.summary
                    + " No call is prepared: the position manager could not quote what "
                    f"closing this position releases ({type(exc).__name__}: {exc})."
                ),
                prepared=(),
                evidence=evidence,
                observed_at=read["observation_time"],
                block=read["observation_block"],
            )
        evidence["preflight"] = sim_evidence
        # The decision was authorised against a cost assumed before any venue existed.
        # Now that the leg has been priced, the same test is run again against what it
        # will actually cost — a reset whose margin was thin can stop clearing the
        # multiple its owner set, and acting on the ex-ante figure would be acting on a
        # number nobody is going to pay.
        economics = sim_evidence["economics"]
        evidence["economics"] = economics
        multiple = economics.get("net_benefit_multiple")
        if multiple is not None and multiple < policy.min_net_benefit_multiple:
            return Decision(
                kind="alert",
                summary=(
                    f"Position {position['token_id']}'s reset is not offered at the venue "
                    f"it would actually use: priced on "
                    f"{economics.get('swap_venue', 'that venue')} the recovery covers the "
                    f"cost {multiple:.2f} times against the "
                    f"{policy.min_net_benefit_multiple:.2f} the policy requires, where the "
                    "assumption it was authorised against cleared it."
                ),
                prepared=(),
                evidence=evidence,
                observed_at=read["observation_time"],
                block=read["observation_block"],
            )
        evidence["token_amounts"] = token_spend(prepared)
        # Per call as well as in total: `docket/jobs/tick.py` hands one mapping to
        # `execute` for every call in the batch and `SessionPolicy.allows` accumulates it
        # each time, so a loop that charged the batch total per call would count an
        # approval six times. The per-call breakdown is what a correct charge reads.
        evidence["token_amounts_by_call"] = [
            {"purpose": call.purpose, "spends": token_spend([call])}
            for call in prepared
        ]
        evidence["slippage_bps"] = policy.max_slippage_bps
        # The addresses the spend accounting cannot read out of calldata, and the tokens a
        # revoke has to look for afterwards. Both are derived from the batch that was
        # actually built rather than listed beside it.
        evidence["token_hints"] = {
            "position_tokens": {str(position["token_id"]): [token0, token1]}
        }
        # Both sides of the pair: the swap pays one of them in, the collect sweeps fees in
        # both, and whatever the mint does not consume stays in the session until revoke.
        evidence["received_tokens"] = [token0, token1]
        evidence["touched_tokens"] = list(touched_tokens(prepared))
        if sim_evidence["verdict"] != "passed":
            # No prepared calls on an alert. A batch that did not pass its preflight is
            # not a batch anybody may send, and `Decision` refuses to carry one.
            return Decision(
                kind="alert",
                summary=(
                    decision.summary
                    + " The prepared calls were not offered: "
                    + sim_evidence["reason"]
                ),
                prepared=(),
                evidence=evidence,
                observed_at=read["observation_time"],
                block=read["observation_block"],
            )
        return Decision(
            kind="action",
            summary=decision.summary,
            prepared=prepared,
            evidence=evidence,
            observed_at=read["observation_time"],
            block=read["observation_block"],
        )

    def _prepare(self, *, position, pool, decision, policy, holder, session, now, rpc):
        """Build the batch, choose the swap's venue, then ask the chain what it can."""
        deadline = int(now.timestamp()) + DEADLINE_S
        resume = bool(decision.evidence.get("resuming"))
        if resume:
            held = decision.evidence["resuming"]["session_inventory"]
            burn0, burn1 = int(held["token0"]), int(held["token1"])
        else:
            burn0, burn1 = burn_quote(
                position, owner=holder, deadline=deadline, rpc=rpc
            )
        plan = swap_plan(
            burn0,
            burn1,
            sqrt_price_x96=int(pool["sqrt_price_x96"]),
            slippage_bps=policy.max_slippage_bps,
        )
        token0 = Web3.to_checksum_address(position["token0"])
        token1 = Web3.to_checksum_address(position["token1"])
        swap = None
        venue_record = {"needed": plan["needed"], "reason": plan["reason"]}
        if plan["needed"]:
            swap, venue_record = self._choose_venue(
                plan,
                pool=pool,
                token0=token0,
                token1=token1,
                policy=policy,
                fee=int(position["fee"]),
                rpc=rpc,
            )
        calls = rebalance_calls(
            position,
            new_tick_lower=decision.new_tick_lower,
            new_tick_upper=decision.new_tick_upper,
            recipient=holder,
            session=session,
            deadline=deadline,
            amounts={
                "max_slippage_bps": policy.max_slippage_bps,
                "burn0": burn0,
                "burn1": burn1,
                "resume": resume,
                "swap": swap,
            },
        )
        block = 0
        verdict = "passed"
        reason = "every call whose preconditions hold at this block was accepted"
        simulated: list[PreparedCall] = []
        for call in calls:
            waits_on = _waits_on(call.purpose, resuming=resume)
            if waits_on is not None:
                # It spends tokens the close has not released yet. Asking the chain would
                # get TRANSFER_FROM_FAILED from a session holding nothing, which is a fact
                # about the ordering and not about the call.
                simulated.append(
                    with_simulation(call, defer(call, depends_on=waits_on, block=block))
                )
                continue
            # The position-manager calls are asked as the holder: the holder is authorised
            # over the token whichever way the approval went, so asking from that address
            # answers whether the calldata, the token id and the minimums hold at this
            # price rather than whether an approval exists yet.
            sender = holder if call.to == NPM else session
            record, outcome = simulate_call(call, sender=sender, rpc=rpc)
            block = record["block"] or block
            simulated.append(with_simulation(call, record))
            if outcome != "passed" and verdict == "passed":
                verdict = outcome
                reason = f"{call.purpose}: {record['revert_reason']}"
        prepared = tuple(simulated)
        return prepared, {
            "verdict": verdict,
            "reason": reason,
            "block": block,
            "resumed": resume,
            "amounts": {
                "burn0": str(burn0),
                "burn1": str(burn1),
                "swap": swap,
                "swap_plan": _stringify(plan),
                "venue": venue_record,
                "note": SWAP_NOTE,
            },
            "economics": recost_swap(
                decision.evidence["economics"],
                venue=(swap or {}).get("venue", "none"),
                fee=int(position["fee"]),
                shortfall_bps=venue_record.get("v2_shortfall_bps"),
            )
            if swap is not None
            else decision.evidence["economics"],
        }

    def _choose_venue(self, plan, *, pool, token0, token1, policy, fee, rpc):
        """Which router the leg goes through, and the floor it is held to.

        PancakeSwap V2 is quoted first because it is the venue the rest of Docket's
        execution plane already uses. Its quote is then held against the price the
        position's own v3 pool is trading at: a pair that exists on V2 in name can be thin
        enough there to lose most of a position, and an `amountOutMin` derived from that
        quote would be a floor under a number that was already wrong. Where V2 falls short
        of the policy's own slippage bound the leg is routed into the v3 pool the position
        was minted in instead, whose floor comes from that pool's price less its fee tier
        and the same bound.
        """
        route = (
            (token0, token1) if plan["token_in"] == "token0" else (token1, token0)
        )
        amount_in = plan["amount_in"]
        fair = expected_out(
            amount_in,
            token_in=plan["token_in"],
            sqrt_price_x96=int(pool["sqrt_price_x96"]),
        )
        bound = 10_000 - policy.max_slippage_bps
        quoted = None
        quote_error = None
        try:
            quoted = int(self._quote_handle(rpc).amounts_out(amount_in, route)[-1])
        except Exception as exc:  # a venue that cannot quote is a venue not used
            quote_error = f"{type(exc).__name__}: {exc}"
        shortfall_bps = (
            None if quoted is None or fair <= 0 else (fair - quoted) * 10_000 // fair
        )
        record = {
            "needed": True,
            "route": list(route),
            "amount_in": str(amount_in),
            "pool_price_out": str(fair),
            "v2_quote": None if quoted is None else str(quoted),
            "v2_quote_error": quote_error,
            "v2_shortfall_bps": None if shortfall_bps is None else int(shortfall_bps),
            "slippage_bps": policy.max_slippage_bps,
        }
        if quoted is not None and quoted * 10_000 >= fair * bound:
            record["venue"] = "v2"
            record["reason"] = (
                f"PancakeSwap V2 quotes {quoted} against the {fair} this position's own "
                f"pool prices the trade at, {shortfall_bps}bps short of it and inside the "
                f"{policy.max_slippage_bps}bps the policy allows"
            )
            return {
                "venue": "v2",
                "token_in": plan["token_in"],
                "amount_in": amount_in,
                # Floored against the pool's own price rather than against the venue's
                # quote. The quote is already inside the bound, so `fair * bound` is the
                # tighter of the two — and it is the number that does not move when the
                # venue's own book does between the quote and the block this lands in.
                "min_output": fair * bound // 10_000,
            }, record
        # The v3 leg trades in the position's own pool, so the pool's price IS the quote.
        # Its floor is that price less the pool's fee tier and the policy's bound, and the
        # router enforces it by reverting rather than by anyone trusting it.
        record["venue"] = "v3"
        record["reason"] = (
            "PancakeSwap V2 "
            + (
                f"could not quote this route ({quote_error})"
                if quoted is None
                else f"quotes {quoted} against the {fair} this position's own pool prices "
                f"the trade at — {shortfall_bps}bps short, outside the "
                f"{policy.max_slippage_bps}bps the policy allows"
            )
            + ", so the leg is routed through the v3 SwapRouter into that pool instead"
        )
        return {
            "venue": "v3",
            "token_in": plan["token_in"],
            "amount_in": amount_in,
            "min_output": fair * bound // 10_000 * (1_000_000 - fee) // 1_000_000,
        }, record

    def within_policy(self, activation, decision: Decision) -> tuple[bool, str]:
        """Whether the session the owner granted covers every call this decision offers."""
        gas_price = int(decision.evidence.get("gas_price_wei") or 0)
        return within_session_policy(
            activation.policy,
            decision.prepared,
            gas_price_wei=gas_price,
            now=self._clock(),
        )


BALANCE_OF = "0x70a08231"


def session_inventory(position: dict, *, session: str, rpc) -> dict:
    """What the session already holds of this position's two tokens.

    Read whenever the position's liquidity is zero, because that is the state a batch
    leaves behind when it closed the position and then stopped: the NFT is empty and the
    money is in the session. Without this read the watch would call it `closed` and go
    quiet on a position whose owner is mid-reset.
    """
    holder = Web3.to_checksum_address(session)[2:].rjust(64, "0")
    out = {}
    for name in ("token0", "token1"):
        raw = rpc(
            lambda w3, token=position[name]: w3.eth.call(
                {"to": Web3.to_checksum_address(token), "data": BALANCE_OF + holder}
            )
        )
        out[name] = int.from_bytes(bytes(raw)[-32:], "big") if raw else 0
    return out


def session_may_move(position: dict, *, holder: str, session: str, rpc) -> bool:
    """Whether the session is already authorised over this position NFT.

    Two reads because ERC-721 grants two ways: `getApproved` for the single token, and
    `isApprovedForAll` for the holder's whole collection. Either is enough, and neither is
    something Docket can grant itself — which is the point of asking rather than drafting.
    """
    token_id = int(position["token_id"])
    operator = Web3.to_checksum_address(session)
    approved = rpc(
        lambda w3: w3.eth.call(
            {
                "to": NPM,
                "data": npm_approval_reader.encode_abi("getApproved", args=[token_id]),
            }
        )
    )
    if Web3.to_checksum_address(bytes(approved)[-20:]) == operator:
        return True
    blanket = rpc(
        lambda w3: w3.eth.call(
            {
                "to": NPM,
                "data": npm_approval_reader.encode_abi(
                    "isApprovedForAll",
                    args=[Web3.to_checksum_address(holder), operator],
                ),
            }
        )
    )
    return int.from_bytes(bytes(blanket)[-32:], "big") == 1


def expected_out(amount_in: int, *, token_in: str, sqrt_price_x96: int) -> int:
    """What the position's own pool prices this trade at, in integers.

    The yardstick a venue's quote is held against. A pair can exist on PancakeSwap V2 and
    still be thin enough there to lose most of a position — the fixture pair in the tests
    quotes 30% down for one unit and 97% down for a hundred — so a quote is only usable
    once it has been compared with the price the position is actually marked at.
    """
    if token_in == "token0":
        return amount_in * sqrt_price_x96 * sqrt_price_x96 // Q192
    return amount_in * Q192 // (sqrt_price_x96 * sqrt_price_x96)


def burn_quote(position: dict, *, owner: str, deadline: int, rpc) -> tuple[int, int]:
    """What closing this position releases, quoted by the position manager itself.

    `decreaseLiquidity` returns `(amount0, amount1)`, so the exact figures come from an
    `eth_call` of the probe below rather than from arithmetic here. The probe carries
    zero minimums because it is a question and not a transaction — the minimums on the
    call that is actually offered are computed from these numbers and the policy's
    slippage bound. Asking the owner is what makes the answer available: the owner is
    authorised over the token whether or not the session approval has landed.

    This is `execution/simulate.py`'s discipline applied to a position rather than a swap.
    Nothing here derives an amount it could ask the chain for, which is also why
    `tickmath` — float64, and banned by its own docstring from transaction sizing — is
    not reached from this module at all.
    """
    probe = npm_encoder.encode_abi(
        "decreaseLiquidity",
        args=[(int(position["token_id"]), int(position["liquidity"]), 0, 0, deadline)],
    )
    raw = rpc(
        lambda w3: w3.eth.call(
            {
                "from": Web3.to_checksum_address(owner),
                "to": NPM,
                "data": probe,
                "value": 0,
            }
        )
    )
    body = bytes(raw)
    if len(body) < 64:
        raise ValueError(
            f"decreaseLiquidity answered {len(body)} bytes, which is not the two uint256 "
            "amounts it returns; no reset is sized from it"
        )
    return int.from_bytes(body[:32], "big"), int.from_bytes(body[32:64], "big")


register(CATEGORY, RangeKeeperExecutor())

__all__ = [
    "CATEGORY",
    "RangeKeeperExecutor",
    "burn_quote",
    "keeper_policy",
    "read_position",
]


def _stringify(plan: dict) -> dict:
    """Atomic figures travel as strings; `bool` subclasses `int` and must not."""
    return {
        key: (
            str(value)
            if isinstance(value, int) and not isinstance(value, bool)
            else value
        )
        for key, value in plan.items()
    }
