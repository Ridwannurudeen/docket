"""Preflight: what the chain says about this action, before anybody sends it.

The session authority answers "may this happen". This answers "should it" — and the two
are different questions with different failure modes. A swap to an allowlisted router,
inside a spend cap, signed by a session the owner granted, can still come back with a
tenth of what it should. The allowlist has no opinion about price, and neither does the
cap.

So every action is quoted against the router before it is sent, and the quote is
compared against the bounds the intent committed to. If they disagree, the action is not
submitted. There is no path in this package that submits an action whose simulation
disagreed, which is why `agrees` is a plain boolean rather than a score somebody could
weigh against something else.

Two shapes of preflight, and the record says which one ran. `router.getAmountsOut` is a
view call that needs no balance, no approval and no account, so it works in the preview
where there is no wallet at all. `eth_estimateGas` needs a sender that could really
execute the swap, so it runs only when one is supplied — and its absence is recorded
rather than papered over.

The calldata builder lives here rather than in the grid, beside the ABI it has to agree
with. Two copies of a router ABI is two things to keep in step, and the one that drifts
is whichever is further from the call.
"""

from dataclasses import dataclass

from web3 import Web3

from ..escrow.chain import Rpc
from . import now
from .intent import ActionIntent

# PancakeSwap V2 router on BSC mainnet, 21,936 bytes of code. Exact-input token-to-token
# swaps only: this build quotes and sends nothing else.
PANCAKE_V2_ROUTER = Web3.to_checksum_address("0x10ED43C718714eb63d5aA57B78B54704E256024E")
SWAP_SIGNATURE = "swapExactTokensForTokens(uint256,uint256,address[],address,uint256)"

ROUTER_ABI = [
    {
        "name": "getAmountsOut",
        "type": "function",
        "stateMutability": "view",
        "inputs": [
            {"name": "amountIn", "type": "uint256"},
            {"name": "path", "type": "address[]"},
        ],
        "outputs": [{"name": "amounts", "type": "uint256[]"}],
    },
    {
        "name": "swapExactTokensForTokens",
        "type": "function",
        "stateMutability": "nonpayable",
        "inputs": [
            {"name": "amountIn", "type": "uint256"},
            {"name": "amountOutMin", "type": "uint256"},
            {"name": "path", "type": "address[]"},
            {"name": "to", "type": "address"},
            {"name": "deadline", "type": "uint256"},
        ],
        "outputs": [{"name": "amounts", "type": "uint256[]"}],
    },
]
_encoder = Web3().eth.contract(abi=ROUTER_ABI)


def swap_calldata(
    *,
    amount_in: int,
    min_output: int,
    route: tuple[str, ...],
    recipient: str,
    deadline: int,
) -> bytes:
    """The exact bytes of one V2 exact-input swap.

    Addresses are checksummed before encoding so calldata built from a lowercased route
    is byte-identical to calldata built from a checksummed one — the bytes are hashed
    into the intent, and two spellings hashing differently would break the commitment for
    no reason anybody could see.

    `min_output` of zero is refused here as well as on the intent. This is the function
    that actually writes the floor into the transaction, and a floor of zero written here
    is a swap that accepts anything however carefully the record above it was worded.
    """
    if min_output <= 0:
        raise ValueError(
            "a swap with amountOutMin of 0 accepts any output at all, which is the one "
            "thing no action in this package is allowed to do"
        )
    path = [Web3.to_checksum_address(hop) for hop in route]
    return bytes.fromhex(
        _encoder.encode_abi(
            "swapExactTokensForTokens",
            args=[
                int(amount_in),
                int(min_output),
                path,
                Web3.to_checksum_address(recipient),
                int(deadline),
            ],
        )[2:]
    )


@dataclass(frozen=True)
class Simulation:
    """What the chain said, and which questions were actually put to it."""

    agrees: bool
    reason: str
    expected_output: int | None
    gas: int | None
    block_number: int | None
    checks: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.agrees and self.expected_output is None:
            raise ValueError(
                "a simulation cannot agree with an intent's output floor while knowing "
                "nothing about the output"
            )

    def as_record(self) -> dict:
        return {
            "agrees": self.agrees,
            "reason": self.reason,
            "expected_output": None if self.expected_output is None else str(self.expected_output),
            "gas": self.gas,
            "block_number": self.block_number,
            "checks": list(self.checks),
        }


class BscQuoteReader:
    """Router quotes and gas estimates over the endpoint failover already in use.

    `escrow.chain.Rpc` is reused rather than copied, for the reason its own docstring
    gives: the failover shape already exists in three places here and a fourth would be
    the one that goes stale.
    """

    def __init__(self, router: str = PANCAKE_V2_ROUTER, rpc=None) -> None:
        self.router = Web3.to_checksum_address(router)
        self._rpc = rpc if rpc is not None else Rpc()

    def block_number(self) -> int:
        return self._rpc(lambda w3: w3.eth.block_number)

    def amounts_out(self, amount_in: int, route) -> list[int]:
        path = [Web3.to_checksum_address(hop) for hop in route]
        return self._rpc(
            lambda w3: (
                w3.eth.contract(address=self.router, abi=ROUTER_ABI)
                .functions.getAmountsOut(int(amount_in), path)
                .call()
            )
        )

    def estimate_gas(self, sender: str, target: str, calldata: bytes) -> int:
        return self._rpc(
            lambda w3: w3.eth.estimate_gas(
                {
                    "from": Web3.to_checksum_address(sender),
                    "to": Web3.to_checksum_address(target),
                    "data": calldata,
                }
            )
        )


def simulate(
    intent: ActionIntent,
    calldata: bytes,
    *,
    reader,
    sender: str | None = None,
    now_override: int | None = None,
) -> Simulation:
    """Whether the chain, right now, agrees with every bound this intent committed to.

    The order is chosen so the cheapest and most decisive question is asked first: bytes
    that are not the committed bytes are refused before a single call goes out, because
    at that point the record and the transaction are describing two different actions and
    nothing measured about one says anything about the other.
    """
    checks: list[str] = ["intent.matches"]
    if not intent.matches(calldata):
        return Simulation(
            agrees=False,
            reason=(
                "the calldata does not match the intent's commitment: these bytes are not "
                "the action that was reasoned about"
            ),
            expected_output=None,
            gas=None,
            block_number=None,
            checks=tuple(checks),
        )

    moment = now() if now_override is None else now_override
    if intent.deadline <= moment:
        return Simulation(
            agrees=False,
            reason=(
                f"the intent's deadline {intent.deadline} has passed at {moment}: the "
                "router would take this transaction and revert on it"
            ),
            expected_output=None,
            gas=None,
            block_number=None,
            checks=tuple(checks),
        )

    checks.append("router.getAmountsOut")
    try:
        amounts = reader.amounts_out(intent.max_input, intent.route)
        block = reader.block_number()
    except Exception as exc:
        return Simulation(
            agrees=False,
            reason=f"the router could not quote this route: {type(exc).__name__}: {exc}",
            expected_output=None,
            gas=None,
            block_number=None,
            checks=tuple(checks),
        )

    expected = int(amounts[-1])
    if expected < intent.min_output:
        return Simulation(
            agrees=False,
            reason=(
                f"the router quotes {expected} out, below the intent's min_output of "
                f"{intent.min_output}: the price has moved against this action since it "
                "was drafted"
            ),
            expected_output=expected,
            gas=None,
            block_number=block,
            checks=tuple(checks),
        )

    gas = None
    if sender is not None:
        checks.append("eth_estimateGas")
        try:
            gas = int(reader.estimate_gas(sender, intent.target, calldata))
        except Exception as exc:
            return Simulation(
                agrees=False,
                reason=f"the swap could not be estimated: {type(exc).__name__}: {exc}",
                expected_output=expected,
                gas=None,
                block_number=block,
                checks=tuple(checks),
            )
        if gas > intent.gas_ceiling:
            return Simulation(
                agrees=False,
                reason=(
                    f"the swap estimates at {gas} gas, above the intent's gas_ceiling of "
                    f"{intent.gas_ceiling}"
                ),
                expected_output=expected,
                gas=gas,
                block_number=block,
                checks=tuple(checks),
            )

    return Simulation(
        agrees=True,
        reason=(
            f"the router quotes {expected} out against a floor of {intent.min_output}, at "
            f"block {block}"
        ),
        expected_output=expected,
        gas=gas,
        block_number=block,
        checks=tuple(checks),
    )
