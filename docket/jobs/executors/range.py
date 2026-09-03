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

**Some calls cannot be simulated at this block, and say so.** `mint` needs the tokens the
burn has not released yet, so it is marked `deferred` against the call it waits on rather
than being reported as a failure. The three position-manager calls are simulated from the
*owner*, who is authorised over the token whether or not the session approval has landed —
that validates the calldata, the token id and the minimums against the live price, which
is what a preflight is for. `docket/sessions/executor.py` re-simulates every call from its
real sender at send time; nothing here is a substitute for that.

**Observations persist through the activation's own result.** Time out of range can only be
measured against earlier readings, and the tick loop is stateless. So each evaluation
returns the observation list it built under `evidence["observations"]`, and expects the
previous one at `activation.result["observations"]`. That is the contract between this
executor and whatever persists an activation's result.
"""

from web3 import Web3

from ...agents.pancake.keeper import (
    KeeperPolicy,
    evaluate as keeper_evaluate,
    npm_encoder,
    rebalance_calls,
)
from ...agents.pancake.pools import PoolClient, is_plausible
from ...agents.pancake.positions import NPM, PositionReader
from ...escrow.chain import Rpc
from . import register
from .base import Decision, PreparedCall
from .bounds import (
    defer,
    now_utc,
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

SWAP_MODEL = (
    "A range drawn around the current tick holds both tokens and the closed position holds "
    "one, so half of it is modelled as traded before the mint. The split is computed from "
    "the pool's own sqrtPriceX96 in integers — no float and no price feed — and the bought "
    "side is then reduced by the pool's fee tier and the policy's slippage bound. The trade "
    "itself is not among the calls below; the mint's desired amounts describe the inventory "
    "expected after it."
)


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


def post_swap_inventory(
    burn0: int, burn1: int, *, sqrt_price_x96: int, fee: int, slippage_bps: int
) -> dict:
    """What the wallet is expected to hold at mint time, in atomic units.

    A v3 pool stores `sqrt(price) * 2**96`, so `amount0 * sqrtP**2 // 2**192` converts
    token0 into token1 at the pool's own price with no float anywhere in it — which is why
    this does not go through `tickmath`, whose docstring bans its float path from
    transaction sizing. Half the one-sided inventory changes hands, and the bought side is
    reduced by the pool's fee tier and the slippage bound so the mint's minimums are
    computed against an amount the swap can actually deliver.
    """
    haircut = (10_000 - slippage_bps) * (1_000_000 - fee)
    scale = 10_000 * 1_000_000
    if burn1 == 0 and burn0 > 0:
        sold = burn0 // 2
        bought = sold * sqrt_price_x96 * sqrt_price_x96 // Q192 * haircut // scale
        return {
            "desired0": burn0 - sold,
            "desired1": bought,
            "swap": {"token": "token0", "sold": sold, "bought": bought},
        }
    if burn0 == 0 and burn1 > 0:
        sold = burn1 // 2
        bought = sold * Q192 // (sqrt_price_x96 * sqrt_price_x96) * haircut // scale
        return {
            "desired0": bought,
            "desired1": burn1 - sold,
            "swap": {"token": "token1", "sold": sold, "bought": bought},
        }
    return {"desired0": burn0, "desired1": burn1, "swap": None}


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


class RangeKeeperExecutor:
    """Watches one v3 position and prepares the reset when the policy says one is due."""

    category = CATEGORY

    def __init__(self, *, pools=None, rpc=None, clock=now_utc) -> None:
        self._pools = pools
        self._rpc = rpc
        self._clock = clock

    def _pool_client(self):
        return self._pools if self._pools is not None else PoolClient()

    def _rpc_handle(self):
        return self._rpc if self._rpc is not None else Rpc()

    def evaluate(self, activation, *, reader=None) -> Decision:
        inputs = activation.inputs or {}
        now = self._clock()
        reader = reader if reader is not None else PositionReader()
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
            gas_price_wei = int(self._rpc_handle()(lambda w3: w3.eth.gas_price))
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
        evidence["swap_model"] = SWAP_MODEL

        if decision.kind != "action":
            return Decision(
                kind=decision.kind,
                summary=decision.summary,
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
        if sim_evidence["verdict"] != "passed":
            return Decision(
                kind="alert",
                summary=(
                    decision.summary
                    + " The prepared calls were not offered: "
                    + sim_evidence["reason"]
                ),
                prepared=prepared,
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

    def _prepare(self, *, position, pool, decision, policy, holder, session, now):
        """Build the batch, then ask the chain about every call it can answer for."""
        deadline = int(now.timestamp()) + DEADLINE_S
        burn0, burn1 = burn_quote(
            position, owner=holder, deadline=deadline, rpc=self._rpc_handle()
        )
        inventory = post_swap_inventory(
            burn0,
            burn1,
            sqrt_price_x96=int(pool["sqrt_price_x96"]),
            fee=int(position["fee"]),
            slippage_bps=policy.max_slippage_bps,
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
                "desired0": inventory["desired0"],
                "desired1": inventory["desired1"],
            },
        )
        rpc = self._rpc_handle()
        block = 0
        verdict = "passed"
        reason = "every call the chain could be asked about at this block was accepted"
        simulated: list[PreparedCall] = []
        for call in calls:
            if call.purpose == "session_mints_replacement_to_owner":
                record = defer(
                    call,
                    depends_on="session_closes_position and the swap it names",
                    block=block,
                )
                simulated.append(with_simulation(call, record))
                continue
            # The position-manager calls are put to the chain as the owner: the owner is
            # authorised over the token whether or not the ERC-721 approval has landed, so
            # asking from that address answers whether the calldata, the token id and the
            # minimums hold at this price rather than whether an approval exists yet.
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
                "desired0": str(inventory["desired0"]),
                "desired1": str(inventory["desired1"]),
                "swap": inventory["swap"],
                "model": SWAP_MODEL,
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


register(RangeKeeperExecutor())

__all__ = [
    "CATEGORY",
    "RangeKeeperExecutor",
    "burn_quote",
    "keeper_policy",
    "post_swap_inventory",
    "read_position",
]
