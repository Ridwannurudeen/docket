"""The work Docket runs and may admit for sale, stated for a stranger's agent.

Each entry answers, in the order a caller needs it: what arrives, what to send,
how long to wait, and the term that applies after admission. A service that cannot
say those four things in machine-readable form is not hireable by an agent that has
never seen this site — which is the only kind of caller that matters here.

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

import base64
import hashlib
import json
import math
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone

import httpx

from ..advantage.v3 import report as v3_report
from ..agents.pancake import doctor
from ..agents.pancake.positions import MAX_EXAMINED

# $U (ERC-8183, 18 decimals) on BSC mainnet. Priced in the asset whose
# TransferWithAuthorization this build can actually verify — see hire/x402.py.
USDT_TOKEN = "0x55d398326f99059fF775485246999027B3197955"
HIRE_PRICE_DISPLAY = "0.50 USDT"
HIRE_PRICE_ATOMIC = 5 * 10**17
CONTROLLED_EXAMPLE_WALLET = "0xe55816904796341bf8535e25f6c8b647927fc946"
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

SERVICE_BENCHMARK_FAMILIES = {
    "range-doctor": "v3-05-range-doctor",
    "yield-router": "v3-02-yield-router",
    "warden-scan": "v3-04-warden-security",
}


def _benchmark_family(service_id: str, payload: dict) -> dict | None:
    spec_id = SERVICE_BENCHMARK_FAMILIES.get(service_id)
    if spec_id is None:
        return None
    family = next(
        (family for family in payload["families"] if family["spec_id"] == spec_id),
        None,
    )
    if family is None:
        raise RuntimeError(f"v3 report is missing mapped family {spec_id}")
    registered_service = family["spec"]["execution_protocol"]["agent_service_id"]
    if registered_service != service_id:
        raise RuntimeError(
            f"v3 family {spec_id} is registered for {registered_service}, not {service_id}"
        )
    if family["state"] == v3_report.SUPERSEDED_BEFORE_INPUT_LOCK:
        raise RuntimeError(f"v3 family {spec_id} is superseded and cannot benchmark a hire")
    return family


@dataclass(frozen=True)
class PaidStockAdmission:
    """The four facts every personalized paid hire must establish before it is sold."""

    fresh_paired_benchmark: bool
    cold_canary: bool
    decision_grade_presenter: bool
    true_settlement: bool

    @property
    def passes(self) -> bool:
        return all(
            (
                self.fresh_paired_benchmark,
                self.cold_canary,
                self.decision_grade_presenter,
                self.true_settlement,
            )
        )


NO_PAID_ADMISSION = PaidStockAdmission(False, False, False, False)
RANGE_ADMISSION = PaidStockAdmission(False, False, True, False)
# Warden shares Range's position: a decision-grade presenter exists, and the other three
# limbs are owner-gated or wait on a run that has not happened.
WARDEN_ADMISSION = PaidStockAdmission(False, False, True, False)
# Grid, Yield and Health each gained a decision-grade presenter. The limb is per service and
# is the only one of the four they hold: none has a paired benchmark, a passing cold canary
# or settlement, so none is paid stock and the flag changes nothing a buyer can reach.
PREVIEW_ADMISSION = PaidStockAdmission(False, False, True, False)


@dataclass(frozen=True)
class Service:
    """One hireable unit of work. Frozen: the catalogue a caller reads at `GET /hire`
    and the terms a receipt is issued against must be the same object, unmutated."""

    id: str
    name: str
    job_summary: str
    what_you_get: str
    input_schema: dict
    typical_seconds: int
    price_display: str
    price_atomic: int
    asset: str
    stock_status: str
    admission: PaidStockAdmission
    run: Callable[[dict], dict]

    @property
    def paid_stock(self) -> bool:
        return self.admission.passes


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
                    f"{resp.status_code} from {url}",
                    request=resp.request,
                    response=resp,
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


def _declared_number(payload: dict, field: str, *, allow_zero: bool) -> float | None:
    value = payload.get(field)
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError(f"{field} must be a finite number")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be a finite number") from exc
    if not math.isfinite(number) or number < 0 or (number == 0 and not allow_zero):
        boundary = "zero or greater" if allow_zero else "greater than zero"
        raise ValueError(f"{field} must be finite and {boundary}")
    return number


def _declared_integer(
    payload: dict, field: str, default: int | None = None
) -> int | None:
    value = payload.get(field)
    if value is None:
        return default
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{field} must be an integer")
    return value


def _decode_source_snapshot(snapshot: dict, name: str) -> tuple[object, dict]:
    required = {"url", "observed_at", "sha256", "body_base64"}
    if not isinstance(snapshot, dict) or not required <= set(snapshot):
        raise ValueError(f"{name} must carry url, observed_at, sha256 and body_base64")
    if not all(
        isinstance(snapshot[field], str) and snapshot[field].strip()
        for field in ("url", "observed_at", "sha256", "body_base64")
    ):
        raise ValueError(f"{name} source fields must be nonblank strings")
    try:
        raw = base64.b64decode(snapshot["body_base64"], validate=True)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name}.body_base64 is invalid") from exc
    digest = hashlib.sha256(raw).hexdigest()
    if snapshot["sha256"] != digest:
        raise ValueError(f"{name}.sha256 does not match the exact response bytes")
    try:
        body = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{name} is not a UTF-8 JSON response") from exc
    return body, {
        "url": snapshot["url"],
        "observed_at": snapshot["observed_at"],
        "sha256": digest,
    }


def _pool_rows(body: object, name: str) -> list[dict]:
    if isinstance(body, list):
        rows = body
    elif isinstance(body, dict) and isinstance(body.get("rows"), list):
        rows = body["rows"]
    else:
        raise ValueError(f"{name} must be an array or an object with a rows array")
    if not all(isinstance(row, dict) for row in rows):
        raise ValueError(f"{name} contains a non-object pool row")
    return rows


def _allowlist(body: object, name: str) -> set[str]:
    if not isinstance(body, dict) or not isinstance(body.get("tokens"), list):
        raise ValueError(f"{name} must contain a tokens array")
    return {
        str(token["address"]).lower()
        for token in body["tokens"]
        if isinstance(token, dict)
        and token.get("chainId") == 56
        and token.get("address")
    }


def _run_range_doctor(payload: dict) -> dict:
    """Validate declared economics before any upstream read, then time this exact run."""
    raw_token_id = payload.get("token_id")
    if isinstance(raw_token_id, bool):
        raise ValueError("token_id must be a positive integer")
    try:
        token_id = None if raw_token_id is None else int(raw_token_id)
    except (TypeError, ValueError) as exc:
        raise ValueError("token_id must be a positive integer") from exc
    if token_id is not None and (
        token_id <= 0 or (isinstance(raw_token_id, float) and raw_token_id != token_id)
    ):
        raise ValueError("token_id must be a positive integer")

    position_value = _declared_number(
        payload, "declared_position_value_usd", allow_zero=False
    )
    recenter_cost = _declared_number(
        payload, "estimated_recenter_cost_usd", allow_zero=True
    )
    if (position_value is not None or recenter_cost is not None) and token_id is None:
        raise ValueError(
            "token_id is required when declaring a position value or recenter cost"
        )
    if token_id is not None and payload.get("limit") is not None:
        raise ValueError("limit cannot be combined with an exact token_id")

    # A paired experiment needs both arms answering about the same chain state, and "latest"
    # moves between them. Without this the buyer can ask *what is true now* but not *what was
    # true at the moment we both looked*, and only the second is reproducible.
    raw_block = payload.get("observation_block")
    if isinstance(raw_block, bool):
        raise ValueError("observation_block must be a positive integer block number")
    try:
        observation_block = None if raw_block is None else int(raw_block)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            "observation_block must be a positive integer block number"
        ) from exc
    if observation_block is not None and (
        observation_block <= 0
        or (isinstance(raw_block, float) and raw_block != observation_block)
    ):
        raise ValueError("observation_block must be a positive integer block number")

    snapshot_fields = ("pool_snapshot", "token_list_snapshot", "source_refs")
    supplied_snapshots = [payload.get(field) is not None for field in snapshot_fields]
    if any(supplied_snapshots) and not all(supplied_snapshots):
        raise ValueError(
            "pool_snapshot, token_list_snapshot and source_refs must be supplied together"
        )
    frozen = all(supplied_snapshots)
    pool_rows = None
    token_allowlist = None
    source_evidence = None
    if frozen:
        from ..agents.pancake.positions import NPM

        manager = payload.get("position_manager")
        if not isinstance(manager, str) or manager.lower() != NPM.lower():
            raise ValueError("position_manager must name PancakeSwap v3 NPM on BSC")
        if (
            not isinstance(payload["source_refs"], list)
            or not payload["source_refs"]
            or not all(isinstance(source, dict) for source in payload["source_refs"])
        ):
            raise ValueError("source_refs must be a nonempty array")
        pools_body, pools_evidence = _decode_source_snapshot(
            payload["pool_snapshot"], "pool_snapshot"
        )
        tokens_body, tokens_evidence = _decode_source_snapshot(
            payload["token_list_snapshot"], "token_list_snapshot"
        )
        pool_rows = _pool_rows(pools_body, "pool_snapshot")
        token_allowlist = _allowlist(tokens_body, "token_list_snapshot")
        source_evidence = {
            "pools": pools_evidence,
            "token_list": tokens_evidence,
            "source_refs": payload["source_refs"],
        }

    decision_horizon = _declared_integer(payload, "decision_horizon_days")
    if decision_horizon is not None and decision_horizon <= 0:
        raise ValueError("decision_horizon_days must be a positive integer")

    limit = payload.get("limit")
    started = time.perf_counter()
    report_kwargs = {
        "limit": (
            None
            if token_id is not None
            else RANGE_DOCTOR_LIMIT
            if limit is None
            else int(limit)
        ),
        "token_id": token_id,
        "observation_block": observation_block,
        "declared_position_value_usd": position_value,
        "estimated_recenter_cost_usd": recenter_cost,
    }
    if decision_horizon is not None:
        report_kwargs["decision_horizon_days"] = decision_horizon
    if frozen:
        report_kwargs.update(
            {
                "pool_rows": pool_rows,
                "token_allowlist": token_allowlist,
                "source_evidence": source_evidence,
            }
        )
    result = doctor.report(payload["wallet"], **report_kwargs)
    elapsed = max(0.0, time.perf_counter() - started)
    return result | {
        "measured_value": {
            "this_run_seconds": elapsed,
            "paired_manual_seconds": None,
            "quality_result": None,
            "report_url": None,
            "benchmark_unavailable_reason": (
                "The preregistered v3 paired report has not run, so no paired manual time, "
                "quality result, or v3 report link exists yet."
            ),
        }
    }


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
    base_decimals = _declared_integer(payload, "base_decimals", GRID_BASE_DECIMALS)
    observed = observe_price(
        reader, base=base, quote=quote, base_decimals=base_decimals
    )

    reference = payload.get("reference")
    reference = (
        observed.price if reference is None else _declared_integer(payload, "reference")
    )
    lower = payload.get("lower")
    upper = payload.get("upper")
    plan = build_plan(
        lower=(
            reference * (100 - GRID_BAND_PCT) // 100
            if lower is None
            else _declared_integer(payload, "lower")
        ),
        upper=(
            reference * (100 + GRID_BAND_PCT) // 100
            if upper is None
            else _declared_integer(payload, "upper")
        ),
        levels=_declared_integer(payload, "levels", GRID_LEVELS),
        size_per_level=_declared_integer(
            payload, "size_per_level", GRID_SIZE_PER_LEVEL
        ),
        base=base,
        quote=quote,
        base_decimals=base_decimals,
        reference=reference,
    )
    raw_filled = payload.get("filled")
    if raw_filled is not None and not isinstance(raw_filled, list):
        raise ValueError("filled must be an array of integer level indexes")
    if any(
        not isinstance(index, int) or isinstance(index, bool)
        for index in (raw_filled or ())
    ):
        raise ValueError("filled must be an array of integer level indexes")
    filled = tuple(raw_filled or ())
    return GridPreview(plan, reader=reader, wallet=payload["wallet"]).preview(
        filled=filled
    )


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
                vtoken=VENUS_VUSDT,
                underlying=VENUS_USDT,
                max_repay=GUARD_CAP,
                max_supply=0,
            ),
            MarketPolicy(
                vtoken=VENUS_VUSDC,
                underlying=VENUS_USDC,
                max_repay=0,
                max_supply=GUARD_CAP,
            ),
        ),
        trigger_shortfall_usd=GUARD_TRIGGER_USD if trigger is None else int(trigger),
    )
    return HealthGuardPreview(reader=VenusReader(), policy=policy).preview(
        payload["wallet"]
    )


def _run_yield_router(payload: dict) -> dict:
    """The whole comparison with no wallet anywhere in it, which is the point of it.

    `pool` names the pool the caller's capital is in. With none supplied the deepest pool
    in the eligible set stands in as the baseline — the explorer serves its rows by TVL
    descending, so that is the first of them — and the choice is stated on the response
    rather than implied, because a comparison against an unnamed baseline is a delta
    against nothing.
    """
    draft_fields = ("wallet", "token_in", "token_out", "amount", "cap")
    supplied = {field for field in draft_fields if payload.get(field) is not None}
    if supplied and supplied != set(draft_fields):
        raise ValueError(
            "drafting requires wallet, token_in, token_out, amount and cap together"
        )
    amount = _declared_integer(payload, "amount")
    cap = _declared_integer(payload, "cap")

    from ..agents.pancake.pools import PoolClient
    from ..agents.yield_router.router import YieldRouterPreview
    from ..agents.yield_router.universe import eligible_pools
    from ..execution.simulate import BscQuoteReader

    pool_snapshot = payload.get("pool_snapshot")
    token_snapshot = payload.get("token_list_snapshot")
    if (pool_snapshot is None) != (token_snapshot is None):
        raise ValueError(
            "pool_snapshot and token_list_snapshot must be supplied together"
        )
    if pool_snapshot is not None:
        pools_body, pools_evidence = _decode_source_snapshot(
            pool_snapshot, "pool_snapshot"
        )
        tokens_body, tokens_evidence = _decode_source_snapshot(
            token_snapshot, "token_list_snapshot"
        )
        rows = _pool_rows(pools_body, "pool_snapshot")
        allowlist = _allowlist(tokens_body, "token_list_snapshot")
    else:
        with PoolClient() as client:
            rows, pools_raw = client.top_pools_snapshot()
            allowlist, tokens_raw = client.token_allowlist_snapshot()
        observed_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        pools_evidence = {
            "url": (
                "https://explorer.pancakeswap.com/api/cached/pools/v3/bsc/list/top"
            ),
            "observed_at": observed_at,
            "sha256": hashlib.sha256(pools_raw).hexdigest(),
        }
        tokens_evidence = {
            "url": "https://tokens.pancakeswap.finance/pancakeswap-extended.json",
            "observed_at": observed_at,
            "sha256": hashlib.sha256(tokens_raw).hexdigest(),
        }
    sources = {"pools": pools_evidence, "token_list": tokens_evidence}
    universe = eligible_pools(
        rows,
        allowlist,
        source=pools_evidence["url"],
        observed_at=pools_evidence["observed_at"],
    )
    if not universe.included:
        return {
            "current": None,
            "candidates": [],
            "universe": universe.as_record(),
            "sources": sources,
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
    wallet = payload.get("wallet")
    out = YieldRouterPreview(
        universe=universe,
        current=current,
        reader=BscQuoteReader() if wallet is not None else None,
    ).preview(
        position_size_usd=float(
            payload.get("position_size_usd")
            if payload.get("position_size_usd") is not None
            else ROUTER_POSITION_USD
        ),
        switching_cost_usd=float(
            payload.get("switching_cost_usd")
            if payload.get("switching_cost_usd") is not None
            else ROUTER_SWITCHING_COST_USD
        ),
        **({} if horizon is None else {"horizon_days": int(horizon)}),
        wallet=wallet,
        token_in=payload.get("token_in"),
        token_out=payload.get("token_out"),
        amount=amount,
        cap=cap,
    )
    return out | {
        "current_pool_chosen_by": chosen_by,
        "sources": sources,
    }


SERVICES: dict[str, Service] = {
    "range-doctor": Service(
        id="range-doctor",
        name="Range Doctor",
        job_summary=(
            "Diagnoses one wallet's PancakeSwap v3 position range and fee economics."
        ),
        what_you_get=(
            "A read-only diagnosis of the PancakeSwap v3 liquidity positions a BSC wallet holds "
            "or has staked: for each one, whether the current tick sits inside its range and "
            "where in that range it sits, the pool's gross and protocol-adjusted net 24h fee "
            "rates when its reported figures clear a plausibility gate, and conditional wait "
            "and recenter paths. Name one token id and declare its USD value and estimated "
            "recenter cost to add fixed-notional dollar effects and cost-only break-even; those "
            "two inputs are labelled as the caller's rather than derived from an unverified "
            "price feed. Every finding carries the numbers it was computed from, so you can "
            "check it against the chain yourself. Nothing is signed, approved, or moved."
        ),
        input_schema={
            "wallet": {
                "type": "string",
                "required": True,
                "default": CONTROLLED_EXAMPLE_WALLET,
                "example_note": (
                    "Docket's own controlled position — replace with your address"
                ),
                "description": "the 0x-prefixed BSC address whose v3 positions to read",
            },
            "limit": {
                "type": "integer",
                "required": False,
                "description": (
                    "how many open positions to return. It bounds the answer, not the reading: "
                    "closed positions no longer consume it, so a wallet whose older positions "
                    "are all closed still gets its open ones back. Up to "
                    f"{MAX_EXAMINED} position NFTs are read in one call whatever this is set to; "
                    "the response carries positions_held, positions_examined, closed_skipped "
                    "and scan_complete, so a bounded read always says what it did not reach"
                ),
            },
            "token_id": {
                "type": "integer",
                "required": False,
                "default": 7141050,
                "description": (
                    "one exact PancakeSwap v3 position NFT to diagnose. The wallet is still "
                    "enumerated for coverage, the selected NFT is returned even when closed, "
                    "and this cannot be combined with limit"
                ),
            },
            "declared_position_value_usd": {
                "type": "number",
                "required": False,
                "default": 50.55,
                "description": (
                    "the positive caller-declared USD value of the exact token_id, used for "
                    "fixed-notional dollar effects. Requires token_id; it is not derived from "
                    "a token price feed"
                ),
            },
            "estimated_recenter_cost_usd": {
                "type": "number",
                "required": False,
                "default": 1.0,
                "description": (
                    "the caller-declared non-negative USD cost of recentering the exact "
                    "token_id, including every gas, swap fee and price-impact component the "
                    "caller wants counted. Requires token_id and is not derived by Docket"
                ),
            },
            "observation_block": {
                "type": "integer",
                "required": False,
                "advanced": True,
                "description": (
                    "read the position and its pool at this BSC block instead of the latest "
                    "one. Both are read at the same block either way, so a diagnosis never "
                    "compares a position from one moment against a price from another. Give "
                    "it when the answer has to be reproducible — two readers at different "
                    "times get the same result only if they name the same block. Public "
                    "dataseeds prune, so an older block may return a stated read failure "
                    "naming an archive node as the remedy rather than an empty result"
                ),
            },
            "position_manager": {
                "type": "string",
                "required": False,
                "advanced": True,
                "description": (
                    "the PancakeSwap v3 NPM address; required with frozen source snapshots"
                ),
            },
            "decision_horizon_days": {
                "type": "integer",
                "required": False,
                "default": 30,
                "description": "the positive horizon for the cost-only break-even comparison",
            },
            "pool_snapshot": {
                "type": "object",
                "required": False,
                "advanced": True,
                "description": (
                    "exact top-pools HTTP response bytes as base64 with URL, observation "
                    "time and bare SHA-256; supplied with token_list_snapshot and source_refs"
                ),
            },
            "token_list_snapshot": {
                "type": "object",
                "required": False,
                "advanced": True,
                "description": (
                    "exact token-list HTTP response bytes as base64 with URL, observation "
                    "time and bare SHA-256; supplied with pool_snapshot and source_refs"
                ),
            },
            "source_refs": {
                "type": "array",
                "items": {"type": "object"},
                "required": False,
                "advanced": True,
                "description": "the frozen typed source references bound to this position",
            },
        },
        typical_seconds=30,
        price_display=HIRE_PRICE_DISPLAY,
        price_atomic=HIRE_PRICE_ATOMIC,
        asset=USDT_TOKEN,
        stock_status="candidate",
        admission=RANGE_ADMISSION,
        run=_run_range_doctor,
    ),
    "grid-operator": Service(
        id="grid-operator",
        name="Grid Operator Preview",
        job_summary="Builds a read-only PancakeSwap V2 grid preview for one wallet.",
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
                "default": CONTROLLED_EXAMPLE_WALLET,
                "example_note": (
                    "Docket's own controlled wallet — replace with your address"
                ),
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
                "items": {"type": "integer"},
                "required": False,
                "description": "level indexes already filled, which are not drafted again",
            },
        },
        typical_seconds=25,
        price_display=HIRE_PRICE_DISPLAY,
        price_atomic=HIRE_PRICE_ATOMIC,
        asset=USDT_TOKEN,
        stock_status="preview",
        admission=PREVIEW_ADMISSION,
        run=_run_grid_operator,
    ),
    "health-guard": Service(
        id="health-guard",
        name="Venus Health Guard Preview",
        job_summary=(
            "Reads one wallet's Venus Core Pool position and drafts bounded protective actions."
        ),
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
                "default": CONTROLLED_EXAMPLE_WALLET,
                "example_note": (
                    "Docket's controlled wallet has no Venus position, so the honest result "
                    "is no position — replace with your address"
                ),
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
        price_display=HIRE_PRICE_DISPLAY,
        price_atomic=HIRE_PRICE_ATOMIC,
        asset=USDT_TOKEN,
        stock_status="preview",
        admission=PREVIEW_ADMISSION,
        run=_run_health_guard,
    ),
    "yield-router": Service(
        id="yield-router",
        name="Yield Router Preview",
        job_summary=(
            "Compares an eligible PancakeSwap v3 pool set and states switching break-even."
        ),
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
            "says which, so no order here is an opinion Docket formed. The comparison needs "
            "no wallet; drafting a swap leg requires the wallet, token pair, amount and cap "
            "declared together. Nothing is signed, approved, submitted or moved."
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
            "wallet": {
                "type": "string",
                "required": False,
                "description": (
                    "the recipient for an optional drafted swap leg. Supply it together "
                    "with token_in, token_out, amount and cap; omit all five for comparison only"
                ),
            },
            "token_in": {
                "type": "string",
                "required": False,
                "description": (
                    "the token the optional draft would spend; supply it with wallet, "
                    "token_out, amount and cap"
                ),
            },
            "token_out": {
                "type": "string",
                "required": False,
                "description": (
                    "the token the optional draft would buy; it must be held by the "
                    "destination pool and supplied with wallet, token_in, amount and cap"
                ),
            },
            "amount": {
                "type": "integer",
                "required": False,
                "description": (
                    "the exact atomic-unit input for the optional draft; supply it with "
                    "wallet, token_in, token_out and cap"
                ),
            },
            "cap": {
                "type": "integer",
                "required": False,
                "description": (
                    "the maximum atomic-unit input the optional draft may name; the amount "
                    "is refused rather than trimmed when it exceeds this"
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
            "pool_snapshot": {
                "type": "object",
                "required": False,
                "description": (
                    "exact top-pools HTTP response bytes as base64 with URL, observation "
                    "time and bare SHA-256; supplied together with token_list_snapshot"
                ),
            },
            "token_list_snapshot": {
                "type": "object",
                "required": False,
                "description": (
                    "exact token-list HTTP response bytes as base64 with URL, observation "
                    "time and bare SHA-256; supplied together with pool_snapshot"
                ),
            },
        },
        typical_seconds=12,
        price_display=HIRE_PRICE_DISPLAY,
        price_atomic=HIRE_PRICE_ATOMIC,
        asset=USDT_TOKEN,
        stock_status="preview",
        admission=PREVIEW_ADMISSION,
        run=_run_yield_router,
    ),
    "solvent-signal": Service(
        id="solvent-signal",
        name="SOLVENT Last Published Regime Signal",
        job_summary=(
            "Relays SOLVENT's last published historical regime signal and provenance."
        ),
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
        price_display=HIRE_PRICE_DISPLAY,
        price_atomic=HIRE_PRICE_ATOMIC,
        asset=USDT_TOKEN,
        stock_status="research",
        admission=NO_PAID_ADMISSION,
        run=_run_solvent_signal,
    ),
    "warden-scan": Service(
        id="warden-scan",
        name="Warden Payload Scan",
        job_summary="Scans one untrusted payload and returns Warden's live telemetry.",
        what_you_get=(
            "This hire makes a live upstream call; the recorded run is evidence, not freshness. "
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
        price_display=HIRE_PRICE_DISPLAY,
        price_atomic=HIRE_PRICE_ATOMIC,
        asset=USDT_TOKEN,
        stock_status="beta",
        # One of four limbs now holds: the result is presented as a decision with its
        # detections, their sources and the sanitized text, rather than as raw JSON. The other
        # three remain false and are the reason this is still beta rather than paid stock —
        # settlement is owner-gated, the canary cannot exercise a paid leg until it is, and no
        # paired benchmark has run. Flipping the presenter limb alone changes nothing a buyer
        # can reach, which is the point of requiring all four.
        admission=WARDEN_ADMISSION,
        run=_run_warden_scan,
    ),
}


def get_service(service_id: str) -> Service | None:
    return SERVICES.get(service_id)
