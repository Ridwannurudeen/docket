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
from datetime import datetime, timezone

import httpx

from ..agents.pancake import doctor

# $U (ERC-8183, 18 decimals) on BSC mainnet. Priced in the asset whose
# TransferWithAuthorization this build can actually verify — see hire/x402.py.
U_TOKEN = "0xcE24439F2D9C6a2289F741120FE202248B666666"
# How many of a wallet's position NFTs a hire reads by default. Ten is the
# measured point where the read finishes in tens of seconds rather than minutes.
RANGE_DOCTOR_LIMIT = 10
# The pair the grid preview defaults to, and the band it draws around the current price
# when a caller supplies none. WBNB/USDT is the deepest V2 pair on BSC, and both sides are
# 18 decimals there — USDT is 6 on Ethereum and 18 here, which is the trap this constant
# exists to keep out of the arithmetic.
GRID_BASE = "0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c"
GRID_QUOTE = "0x55d398326f99059fF775485246999027B3197955"
GRID_BASE_DECIMALS = 18
GRID_BAND_PCT = 10
# Even on purpose. The default band is centred on the observed price, and an odd number
# of levels puts one exactly on it — which has no side and is dropped, so a caller who
# asked for five would be handed four and a footnote. An even count straddles the centre
# and comes back symmetric: half buys below, half sells above.
GRID_LEVELS = 6
# 25 USDT a level. Small enough to be a demonstration rather than a position.
GRID_SIZE_PER_LEVEL = 25 * 10**18
# The two Venus markets the health guard is allowed to draft actions in, with their
# underlyings named beside them. Both pairs were read from BSC mainnet on 2026-08-10 and
# the preview re-reads each vToken's own underlying() and refuses where the two disagree —
# a policy naming the wrong token would draft an action paying the right contract in the
# wrong asset, and no later bound catches that.
VENUS_VUSDT = "0xfD5840Cd36d94D7229439859C0112a4185BC0255"
VENUS_VUSDC = "0xecA88125a5ADbe82614ffC12D0DB554E2e2867C8"
VENUS_USDT = "0x55d398326f99059fF775485246999027B3197955"
VENUS_USDC = "0x8AC76a51cc950d9822D68b83fE1Ad97B32Cd580d"
# 100 of each, 18 decimals on BSC. A demonstration rather than a position, the same
# reasoning the grid's level size carries.
GUARD_CAP = 100 * 10**18
# One US dollar, 1e18-scaled as the comptroller reports shortfall. A trigger of zero is
# refused by the policy itself, because it would hold of every account including one that
# owes nothing due.
GUARD_TRIGGER_USD = 10**18
# What the yield comparison assumes when a caller supplies neither. Both are stated on the
# response rather than buried: the break-even is only as good as the cost it was given.
ROUTER_POSITION_USD = 10_000.0
ROUTER_SWITCHING_COST_USD = 15.0
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


def _run_grid_operator(payload: dict) -> dict:
    """A preview, and structurally only a preview.

    `GridPreview` is the class with no session, no signer and no submitter, and it is
    what this hire runs. There is no argument to this function that turns it into the
    armed operator, because the armed operator is a different class that refuses to be
    constructed without a session the wallet's owner granted.

    Every grid input defaults, so `{"wallet": "0x..."}` alone returns the whole
    mechanism: the band is read from the pair's current price and centred on it. A caller
    who wants their own band supplies it and nothing is inferred.
    """
    from ..agents.grid.operator import GridPreview, observe_price
    from ..agents.grid.plan import build_plan
    from ..execution.simulate import BscQuoteReader

    reader = BscQuoteReader()
    base = payload.get("base") or GRID_BASE
    quote = payload.get("quote") or GRID_QUOTE
    base_decimals = int(payload.get("base_decimals") or GRID_BASE_DECIMALS)
    observed = observe_price(reader, base=base, quote=quote, base_decimals=base_decimals)

    reference = payload.get("reference")
    reference = observed.price if reference is None else int(reference)
    lower = payload.get("lower")
    upper = payload.get("upper")
    plan = build_plan(
        lower=reference * (100 - GRID_BAND_PCT) // 100 if lower is None else int(lower),
        upper=reference * (100 + GRID_BAND_PCT) // 100 if upper is None else int(upper),
        levels=int(payload.get("levels") or GRID_LEVELS),
        size_per_level=int(payload.get("size_per_level") or GRID_SIZE_PER_LEVEL),
        base=base,
        quote=quote,
        base_decimals=base_decimals,
        reference=reference,
    )
    filled = tuple(int(index) for index in payload.get("filled") or ())
    return GridPreview(plan, reader=reader, wallet=payload["wallet"]).preview(filled=filled)


def _run_health_guard(payload: dict) -> dict:
    """A preview, and structurally only a preview.

    `HealthGuardPreview` is the only class in its module: there is no armed counterpart to
    construct by mistake, and this build ships no path that submits a Venus call at all.
    The caps below bound what the drafted actions may commit; the trigger is the shortfall
    Venus has to be reporting before anything is drafted.
    """
    from ..agents.venus.guard import GuardPolicy, HealthGuardPreview, MarketPolicy
    from ..agents.venus.markets import VenusReader

    trigger = payload.get("trigger_shortfall_usd")
    policy = GuardPolicy(
        markets=(
            MarketPolicy(
                vtoken=VENUS_VUSDT, underlying=VENUS_USDT, max_repay=GUARD_CAP, max_supply=0
            ),
            MarketPolicy(
                vtoken=VENUS_VUSDC, underlying=VENUS_USDC, max_repay=0, max_supply=GUARD_CAP
            ),
        ),
        trigger_shortfall_usd=GUARD_TRIGGER_USD if trigger is None else int(trigger),
    )
    return HealthGuardPreview(reader=VenusReader(), policy=policy).preview(payload["wallet"])


def _run_yield_router(payload: dict) -> dict:
    """The whole comparison with no wallet anywhere in it, which is the point of it.

    `pool` names the pool the caller's capital is in. With none supplied the deepest pool
    in the eligible set stands in as the baseline — the explorer serves its rows by TVL
    descending, so that is the first of them — and the choice is stated on the response
    rather than implied, because a comparison against an unnamed baseline is a delta
    against nothing.
    """
    from ..agents.pancake.pools import PoolClient
    from ..agents.yield_router.router import YieldRouterPreview
    from ..agents.yield_router.universe import eligible_pools

    with PoolClient() as client:
        rows = client.top_pools()
        allowlist = client.token_allowlist()
    universe = eligible_pools(
        rows,
        allowlist,
        source="explorer.pancakeswap.com/api/cached/pools/v3/bsc/list/top",
        observed_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )
    if not universe.included:
        return {
            "current": None,
            "candidates": [],
            "universe": universe.as_record(),
            "note": (
                "no pool in this snapshot cleared the gate, so there is nothing to compare "
                "and no highest to name. Every row that was turned away is listed with its "
                "reason under universe.excluded"
            ),
        }

    # Three outcomes, and each one gets its own sentence. A named pool that is not in the
    # set has to say so: substituting the baseline silently and then reporting "no pool was
    # named" would be a false statement in served output about the very figure every delta
    # below is measured from. Matched case-insensitively, because the explorer serves ids
    # lowercase and a caller pasting a checksummed address is naming the same pool.
    wanted = payload.get("pool")
    matched = (
        None
        if wanted is None
        else next(
            (
                row
                for row in universe.included
                if str(row.get("id") or "").lower() == str(wanted).lower()
            ),
            None,
        )
    )
    current = universe.included[0] if matched is None else matched
    if matched is not None:
        chosen_by = f"the pool id you named ({wanted})"
    elif wanted is not None:
        chosen_by = (
            f"you named {wanted} and it is not in the eligible set, so the first row of "
            "that set stands in as the baseline instead and every delta below is measured "
            "from that pool rather than yours. Whether the one you named was turned away, "
            "and for what reason, is under universe.excluded — it may also simply not be "
            "in this snapshot"
        )
    else:
        chosen_by = (
            "no pool was named, so the first row of the eligible set stands in as the "
            "baseline. The explorer serves its rows by TVL descending, so that is the "
            "deepest pool in the set and not a pool anybody is known to be in"
        )
    horizon = payload.get("horizon_days")
    out = YieldRouterPreview(universe=universe, current=current).preview(
        position_size_usd=float(payload.get("position_size_usd") or ROUTER_POSITION_USD),
        switching_cost_usd=float(
            payload.get("switching_cost_usd")
            if payload.get("switching_cost_usd") is not None
            else ROUTER_SWITCHING_COST_USD
        ),
        **({} if horizon is None else {"horizon_days": int(horizon)}),
    )
    return out | {"current_pool_chosen_by": chosen_by}


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
    "grid-operator": Service(
        id="grid-operator",
        name="Grid Operator Preview",
        what_you_get=(
            "A deterministic PancakeSwap V2 grid, built from a band you give it — or drawn "
            "around the pair's current price if you give it none — and previewed against BSC "
            "mainnet as it stands right now. You get the exact price levels and their "
            "spacing, which token each level spends and how much of it, the condition each "
            "level fires on, and for every level the full action record that acting would "
            "commit to: the router's own live quote for that trade, the minimum output the "
            "action would insist on, a hash of the exact calldata that binds it, a deadline, "
            "a gas ceiling and a slippage bound. Nothing is signed, approved, submitted or "
            "held. This is a preview and structurally only a preview: the object that runs "
            "it holds no session key, no signer and no submitter, and has no method that "
            "sends a transaction, so it cannot move anything. Acting on a level needs a "
            "session the wallet's owner grants on chain, with a spend cap, a call allowlist "
            "and an expiry that the session validator enforces at validation time — Docket "
            "never holds the owner key and cannot grant or revoke on their behalf. Every "
            "figure comes back with the block it was read at, so you can check any of it "
            "against the chain yourself."
        ),
        input_schema={
            "wallet": {
                "type": "string",
                "required": True,
                "description": (
                    "the 0x-prefixed BSC address the previewed swaps name as recipient; it is "
                    "read and never touched"
                ),
            },
            "lower": {
                "type": "integer",
                "required": False,
                "description": (
                    "bottom of the band, in atomic units of the quote token per one whole "
                    f"base token; defaults to {GRID_BAND_PCT}% below the observed price"
                ),
            },
            "upper": {
                "type": "integer",
                "required": False,
                "description": (
                    f"top of the band, same units; defaults to {GRID_BAND_PCT}% above the "
                    "observed price"
                ),
            },
            "levels": {
                "type": "integer",
                "required": False,
                "default": GRID_LEVELS,
                "description": "how many price levels the band is divided into, at least two",
            },
            "size_per_level": {
                "type": "integer",
                "required": False,
                "default": GRID_SIZE_PER_LEVEL,
                "description": (
                    "what each level commits, in atomic units of the quote token; a sell "
                    "level commits what that is worth in the base token at its own price"
                ),
            },
            "base": {
                "type": "string",
                "required": False,
                "default": GRID_BASE,
                "description": "the token being priced",
            },
            "quote": {
                "type": "string",
                "required": False,
                "default": GRID_QUOTE,
                "description": "the token it is priced in",
            },
            "base_decimals": {
                "type": "integer",
                "required": False,
                "default": GRID_BASE_DECIMALS,
                "description": "decimals of the base token; 18 for WBNB, and 18 for USDT on BSC",
            },
            "reference": {
                "type": "integer",
                "required": False,
                "description": (
                    "the price levels are sided against — below it they buy, above it they "
                    "sell; defaults to the observed price"
                ),
            },
            "filled": {
                "type": "array",
                "required": False,
                "description": "level indexes already filled, which are not drafted again",
            },
        },
        typical_seconds=25,
        price_display="0.01 $U",
        price_atomic=10**16,
        asset=U_TOKEN,
        run=_run_grid_operator,
    ),
    "health-guard": Service(
        id="health-guard",
        name="Venus Health Guard Preview",
        what_you_get=(
            "A read-only report on what Venus Core Pool publishes about one BSC address's "
            "lending position, and on what can honestly be derived from it. Venus publishes "
            "liquidity and shortfall in USD and publishes no health factor at all — so you "
            "get its own two figures verbatim, with the call and the block they came from, "
            "and a collateral ratio computed here whose exact formula, inputs and scales are "
            "stated inline beside it, together with a cross-check of that derivation against "
            "Venus's own liquidity figure so you can see whether the two agree. For every "
            "market the account has entered: supplied and borrowed balances, the collateral "
            "factor, the exchange rate and the oracle price, each labelled with the call that "
            "produced it. Where Venus reports a shortfall, you also get conservative draft "
            "actions — repay and supply-collateral only, never borrow and never withdraw — "
            "each fully bounded, with the exact contract and function, a hash of the calldata "
            "that binds it, a cap, a floor, a deadline and a gas ceiling. Nothing is signed, "
            "approved, submitted or held: the object that produces this holds no session key, "
            "no signer and no submitter, it has no armed counterpart class in this build, and "
            "no execution path for a Venus call exists here at all. Every figure comes back "
            "with the block it was read at, so you can check any of it against the chain "
            "yourself."
        ),
        input_schema={
            "wallet": {
                "type": "string",
                "required": True,
                "description": (
                    "the 0x-prefixed BSC address whose Venus position to read; it is read "
                    "and never touched"
                ),
            },
            "trigger_shortfall_usd": {
                "type": "integer",
                "required": False,
                "default": GUARD_TRIGGER_USD,
                "description": (
                    "the shortfall Venus has to be reporting, 1e18-scaled USD as the "
                    "comptroller reports it, before any action is drafted; zero is refused"
                ),
            },
        },
        typical_seconds=40,
        price_display="0.01 $U",
        price_atomic=10**16,
        asset=U_TOKEN,
        run=_run_health_guard,
    ),
    "yield-router": Service(
        id="yield-router",
        name="Yield Router Preview",
        what_you_get=(
            "A comparison of PancakeSwap v3 pools on BSC at the rates they were observed at, "
            "bounded by a set you can reproduce. The eligible universe is built from "
            "PancakeSwap's own explorer snapshot and stated in full: its size, its source, "
            "the moment it was read, the thresholds it was gated on, and every pool that did "
            "not make it together with the reason it was left out. Each pool in the set "
            "carries its fee rate net of the protocol's own reported cut — the gross figure "
            "overstates what a liquidity provider keeps by about half again — beside the "
            "gross one, with the window the rate was observed over and the TVL it is a rate "
            "against, plus liquidity, 24h volume and turnover. For every candidate you get a "
            "break-even: how many days the extra yield takes to repay what moving costs, "
            "against a stated horizon, with the arithmetic written out and the cost named as "
            "the input you supplied rather than a figure Docket derived. A pool with a higher "
            "rate whose break-even runs past that horizon is shown with that fact attached "
            "rather than dropped. Ordering is by one named observed metric and the payload "
            "says which, so no order here is an opinion Docket formed. No wallet is needed "
            "for any of it, and nothing is signed, approved, submitted or moved."
        ),
        input_schema={
            "pool": {
                "type": "string",
                "required": False,
                "description": (
                    "the pool id your capital is in, as the explorer spells it. With none "
                    "given the first row of the eligible set stands in as the baseline and "
                    "the response says so"
                ),
            },
            "position_size_usd": {
                "type": "number",
                "required": False,
                "default": ROUTER_POSITION_USD,
                "description": "the size the break-even is computed for, in USD",
            },
            "switching_cost_usd": {
                "type": "number",
                "required": False,
                "default": ROUTER_SWITCHING_COST_USD,
                "description": (
                    "what moving costs, in USD, covering gas on every leg plus the swap's "
                    "own fee and price impact; supplied rather than derived, because Docket "
                    "reads no BNB price here"
                ),
            },
            "horizon_days": {
                "type": "integer",
                "required": False,
                "default": 30,
                "description": (
                    "the horizon a break-even is judged against; every input is on the "
                    "response, so another horizon can be applied without asking"
                ),
            },
        },
        typical_seconds=12,
        price_display="0.01 $U",
        price_atomic=10**16,
        asset=U_TOKEN,
        run=_run_yield_router,
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
