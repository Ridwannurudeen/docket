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

Two services relay an upstream verbatim rather than reshaping it. SOLVENT's
`signal_hash` covers the body SOLVENT published, and Warden's response is the
evidence a caller reasons about; re-serialising either would leave the buyer
holding a hash it can no longer check and a verdict Docket had edited. When the
upstream fails, `run` raises: the hire route turns that into a 502 naming the
failure, which is worth more than a half-result that looks like an answer.
"""

import time
from collections.abc import Callable
from dataclasses import dataclass

import httpx

from ..agents.pancake import doctor

# $U (ERC-8183, 18 decimals) on BSC mainnet. Priced in the asset whose
# TransferWithAuthorization this build can actually verify — see hire/x402.py.
U_TOKEN = "0xcE24439F2D9C6a2289F741120FE202248B666666"
# How many of a wallet's position NFTs a hire reads by default. Ten is the
# measured point where the read finishes in tens of seconds rather than minutes.
RANGE_DOCTOR_LIMIT = 10
SOLVENT_SIGNAL_URL = "https://solvent.gudman.xyz/signal"
WARDEN_SCAN_URL = "https://warden.gudman.xyz/api/demo/scan"
UPSTREAM_TIMEOUT_S = 30.0
# One retry, no more. Both hosts answered in about a second once reached, so a
# second failure is the upstream rather than the road to it.
UPSTREAM_ATTEMPTS = 2
UPSTREAM_RETRY_PAUSE_S = 1.0


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


def _call_upstream(method: str, url: str, body: dict | None = None) -> dict:
    """One request, and one retry when the failure could be the road rather than the host.

    On 2026-08-08 the first call to each of these hosts from this machine returned
    nothing at all — DNS, not the service, which then answered three times in a
    row. A transport error and a 429 or 5xx are therefore worth asking twice; any
    other status is not, because a 404 does not become a 200 on the second try.
    """
    last: Exception | None = None
    for attempt in range(UPSTREAM_ATTEMPTS):
        try:
            resp = httpx.request(method, url, json=body, timeout=UPSTREAM_TIMEOUT_S)
            if resp.status_code == 429 or resp.status_code >= 500:
                last = httpx.HTTPStatusError(
                    f"{resp.status_code} from {url}", request=resp.request, response=resp
                )
            else:
                resp.raise_for_status()
                return resp.json()
        except httpx.TransportError as exc:
            last = exc
        if attempt < UPSTREAM_ATTEMPTS - 1:
            time.sleep(UPSTREAM_RETRY_PAUSE_S)
    raise last  # type: ignore[misc]


def _run_solvent_signal(payload: dict) -> dict:
    """Relayed as served: `signal_hash` is computed over the body SOLVENT published,
    so a Docket-shaped copy of it would be a payload whose own hash no longer checks."""
    return _call_upstream("GET", SOLVENT_SIGNAL_URL)


def _run_warden_scan(payload: dict) -> dict:
    """Only the declared field travels upstream; whatever else a caller sent stays here."""
    return _call_upstream("POST", WARDEN_SCAN_URL, {"payload": payload["payload"]})


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
    "solvent-signal": Service(
        id="solvent-signal",
        name="SOLVENT Last Published Regime Signal",
        what_you_get=(
            "SOLVENT's last published daily regime read, relayed byte for byte, together with "
            "the provenance chain that dates it: the regime and the thesis recorded with it, "
            "the receipt sequence number and receipt hash the read was cut from, the head hash "
            "of the receipt chain, the last daily anchor's on-chain transaction, a signal_hash "
            "over the whole body, and the receipts, verify and inference-commitment URLs — so "
            "the chain can be recomputed and the anchor checked on chain without asking Docket "
            "or SOLVENT for anything. This is a historical record, not a live feed: SOLVENT "
            "completed its scored window on 2026-06-28 and has published nothing since, which "
            "as of 2026-08-08 makes the read about six weeks old. Every payload states its own "
            "generated_at and degraded flag, so a caller can always date what it received. What "
            "the chain establishes is narrow and worth stating exactly: it shows this read "
            "existed at that position in a hash chain whose head is anchored on chain, which is "
            "what makes the claim impossible to back-date. It does not show the call was "
            "correct, that the strategy made money, or that anything happened next; and the "
            "newest receipts can sit past the last daily anchor, so a caller should read both "
            "positions from the payload to see whether its own read is anchor-covered or only "
            "chain-consistent. A regime read describes conditions as SOLVENT scored them; it is "
            "not a trade recommendation, and Docket relays it without re-scoring it."
        ),
        input_schema={},
        typical_seconds=2,
        price_display="0.01 $U",
        price_atomic=10**16,
        asset=U_TOKEN,
        run=_run_solvent_signal,
    ),
    "warden-scan": Service(
        id="warden-scan",
        name="Warden Payload Scan",
        what_you_get=(
            "Warden's verdict on one piece of untrusted text — ALLOW, SANITIZE or BLOCK — with "
            "the threat classes it matched, the individual detections and confidences behind "
            "them, its sanitized rendering of the text, and the per-layer checks that produced "
            "the decision, relayed exactly as Warden returned it. This is telemetry, not an "
            "enforcement boundary: the free hosted path is offered as-is, with no availability "
            "or completeness promise, and that limitation is Warden's own documented position "
            "rather than a caveat Docket added. Nothing here intercepts the text or stops it "
            "reaching anything; what to do about a verdict stays with the caller."
        ),
        input_schema={
            "payload": {
                "type": "string",
                "required": True,
                "description": "the untrusted text to scan, sent to Warden unmodified",
            },
        },
        typical_seconds=5,
        price_display="0.01 $U",
        price_atomic=10**16,
        asset=U_TOKEN,
        run=_run_warden_scan,
    ),
}


def get_service(service_id: str) -> Service | None:
    return SERVICES.get(service_id)
