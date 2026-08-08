"""The work Docket sells, stated so a stranger's agent can hire it without asking anyone.

Each entry answers, in the order a caller needs it: what arrives, what to send,
how long to wait, and what it costs. A service that cannot say those four things
in machine-readable form is not hireable by an agent that has never seen this
site — which is the only kind of caller that matters here.

What a service may claim is bounded the same way the rest of Docket is bounded.
`what_you_get` describes work performed, never a result achieved: the Range
Doctor reads positions and states what it read. A test bans the vocabulary of
promised outcomes outright, because the description is the contract and prose
drifts where a test does not.

`run` is bounded on purpose. Reading one position NFT costs four RPC round trips
and a wallet holding 155 of them took roughly five minutes unbounded on
2026-08-08, against 15.4 seconds for the newest ten. A hire that runs for five
minutes is a hire that times out, so the default reads a bounded slice — and the
report it returns carries `positions_held` and `positions_examined`, so a
truncated read announces itself rather than passing for the whole wallet.
"""

from collections.abc import Callable
from dataclasses import dataclass

from ..agents.pancake import doctor

# $U (ERC-8183, 18 decimals) on BSC mainnet. Priced in the asset whose
# TransferWithAuthorization this build can actually verify — see hire/x402.py.
U_TOKEN = "0xcE24439F2D9C6a2289F741120FE202248B666666"
# How many of a wallet's position NFTs a hire reads by default. Ten is the
# measured point where the read finishes in tens of seconds rather than minutes.
RANGE_DOCTOR_LIMIT = 10


@dataclass(frozen=True)
class Service:
    """One hireable unit of work. Frozen: the catalogue a caller reads at `GET /hire`
    and the terms a receipt is issued against must be the same object, unmutated."""

    id: str
    name: str
    what_you_get: str
    input_schema: dict
    typical_seconds: int
    price_display: str
    price_atomic: int
    asset: str
    run: Callable[[dict], dict]


def _run_range_doctor(payload: dict) -> dict:
    """`limit` is read explicitly rather than with `or`, so an explicit 0 stays 0
    instead of silently becoming the default."""
    limit = payload.get("limit")
    return doctor.report(
        payload["wallet"], limit=RANGE_DOCTOR_LIMIT if limit is None else int(limit)
    )


SERVICES: dict[str, Service] = {
    "range-doctor": Service(
        id="range-doctor",
        name="Range Doctor",
        what_you_get=(
            "A read-only diagnosis of the PancakeSwap v3 liquidity positions a BSC wallet holds "
            "or has staked: for each one, whether the current tick sits inside its range and "
            "where in that range it sits, the pool's own 24h net fee rate when the pool's "
            "reported figures clear a plausibility gate, and conditional next steps that each "
            "name the belief they rest on and what acting costs in gas and realised impermanent "
            "loss. Every finding carries the numbers it was computed from, so you can check it "
            "against the chain yourself. Nothing is signed, approved, or moved."
        ),
        input_schema={
            "wallet": {
                "type": "string",
                "required": True,
                "description": "the 0x-prefixed BSC address whose v3 positions to read",
            },
            "limit": {
                "type": "integer",
                "required": False,
                "default": RANGE_DOCTOR_LIMIT,
                "description": (
                    "how many of the wallet's position NFTs to read, newest first; the response "
                    "reports positions_held and positions_examined so a bounded read is visible"
                ),
            },
        },
        typical_seconds=30,
        price_display="0.01 $U",
        price_atomic=10**16,
        asset=U_TOKEN,
        run=_run_range_doctor,
    ),
}


def get_service(service_id: str) -> Service | None:
    return SERVICES.get(service_id)
