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

**Every call in the batch is put to the chain, and carries its own answer.** Nothing is
skipped and nothing is assumed: each of the eight calls gets an `eth_call` and an
`eth_estimateGas` from the address expected to send it, and `simulation.ok` is what the
chain said about that call rather than an inference from its neighbours. The three
position-manager calls are asked from the *holder* of the position NFT, who is authorised
over the token whether or not the session approval has landed, so the calldata, the token
id and the minimums are validated against the live price. `docket/sessions/executor.py`
re-simulates every call from its real sender at send time; nothing here is a substitute
for that, and a batch is a sequence whose later calls depend on state its earlier ones
create.

**Observations have to persist, and today nothing persists them.** Time out of range can
only be measured against earlier readings. Each evaluation returns the list it built under
`evidence["observations"]` and reads the previous one from `activation.result`. As of
`build/pivot-B` the tick loop writes neither — it returns without saving on a `noop`, and
never assigns `activation.result` at all — so on that branch the history is always empty
and the watch never reaches its threshold. Rather than fail silently, a position that is
outside its range with no carried-forward observation says so in its own summary.

**What the session may spend travels in the evidence.** `SessionPolicy.allows` is handed
`evidence["token_amounts"]` and `evidence["slippage_bps"]`, and sees zero spend without
them. Both are derived here from the calldata that is actually being offered rather than
carried beside it.
"""

from web3 import Web3

from ...agents.pancake.keeper import (
    SWAP_NOTE,
    KeeperPolicy,
    evaluate as keeper_evaluate,
    npm_encoder,
    rebalance_calls,
    swap_plan,
)
from ...agents.pancake.pools import PoolClient, is_plausible
from ...agents.pancake.positions import NPM, PositionReader
from ...escrow.chain import Rpc
from ...execution.simulate import BscQuoteReader
from . import register
from .base import Decision, PreparedCall
from .bounds import (
    now_utc,
    token_spend,
    policy_field,
    simulate_call,
    with_simulation,
    within_session_policy,
)

CATEGORY = "rebalancing"
# How long a prepared batch stays valid. Ten minutes is `venus/guard.py`'s own default and
# is long enough for an owner to sign in a browser without being long enough for the price
# the minimums were computed against to become historical.
DEADLINE_S = 600
# How many prior observations travel forward. Enough to date a departure many ticks old
# without letting an activation's result grow without bound.
MAX_OBSERVATIONS = 288
Q192 = 2**192

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
            observation_block=inputs.get("observation_block"),
        )
        read = state["read"]
        observations = list((activation.result or {}).get("observations") or [])
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
        policy = keeper_policy(activation)
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
                    "in_range": decision.evidence["diagnosis"]["in_range"],
                }
            ]
        )[-MAX_OBSERVATIONS:]
        evidence = dict(decision.evidence)
        evidence["observations"] = observations
        evidence["gas_price_wei"] = str(gas_price_wei)
        evidence["swap_note"] = SWAP_NOTE

        if decision.kind != "action":
            summary = decision.summary
            if (
                not decision.evidence["diagnosis"]["in_range"]
                and decision.evidence["time_out_of_range"]["prior_observations"] == 0
            ):
                summary += (
                    " No earlier observation was carried forward on this activation, so no "
                    "elapsed time outside the range is claimed and none can accumulate "
                    "until the tick loop persists evidence['observations'] into "
                    "activation.result."
                )
            return Decision(
                kind=decision.kind,
                summary=summary,
                prepared=(),
                evidence=evidence,
                observed_at=read["observation_time"],
                block=read["observation_block"],
            )

        session = (activation.session or {}).get("address")
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

        try:
            prepared, sim_evidence = self._prepare(
                position=position,
                pool=state["pool"],
                decision=decision,
                policy=policy,
                holder=Web3.to_checksum_address(inputs["wallet"]),
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
        evidence["token_amounts"] = token_spend(prepared)
        evidence["slippage_bps"] = policy.max_slippage_bps
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
        """Build the whole batch, then ask the chain about every call in it."""
        deadline = int(now.timestamp()) + DEADLINE_S
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
        if plan["needed"]:
            route = (
                (token0, token1) if plan["token_in"] == "token0" else (token1, token0)
            )
            # The router's own live quote, taken the way `agents/grid/operator.py` takes
            # one: a view call, so it answers at a block where the session holds nothing.
            quoted_out = int(
                self._quote_handle(rpc).amounts_out(plan["amount_in"], route)[-1]
            )
            swap = {
                "token_in": plan["token_in"],
                "amount_in": plan["amount_in"],
                "quoted_out": quoted_out,
                "route": list(route),
            }
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
                "swap": swap,
            },
        )
        block = 0
        verdict = "passed"
        reason = "every call in the batch was accepted at this block"
        simulated: list[PreparedCall] = []
        for call in calls:
            # The position-manager calls are asked as the holder: the holder is authorised
            # over the token whether or not the ERC-721 approval has landed, so asking from
            # that address answers whether the calldata, the token id and the minimums hold
            # at this price rather than whether an approval exists yet.
            sender = holder if call.to == NPM else session
            record, outcome = simulate_call(call, sender=sender, rpc=rpc)
            block = record["block"] or block
            simulated.append(with_simulation(call, record))
            if outcome != "passed" and verdict == "passed":
                verdict = outcome
                reason = f"{call.purpose}: {record['revert_reason']}"
        return tuple(simulated), {
            "verdict": verdict,
            "reason": reason,
            "block": block,
            "amounts": {
                "burn0": str(burn0),
                "burn1": str(burn1),
                "swap": swap,
                # Atomic figures travel as strings, the way every other atomic amount in
                # Docket does. `bool` subclasses `int`, so it is excluded explicitly —
                # a `needed` of "True" reads as a string nobody can branch on.
                "swap_plan": {
                    key: (
                        str(value)
                        if isinstance(value, int) and not isinstance(value, bool)
                        else value
                    )
                    for key, value in plan.items()
                },
                "note": SWAP_NOTE,
            },
        }

    def within_policy(self, activation, decision: Decision) -> tuple[bool, str]:
        """Whether the session the owner granted covers every call this decision offers."""
        gas_price = int(decision.evidence.get("gas_price_wei") or 0)
        return within_session_policy(
            activation.policy,
            decision.prepared,
            gas_price_wei=gas_price,
            now=self._clock(),
        )


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
