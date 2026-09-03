"""The two-sided marketplace: finding somebody else's agent, and getting yours listed.

Six routes on one `APIRouter`, registered by a single line in `create_app`. They are
deliberately not built from the pydantic models in `api/models.py`: those models describe
Docket's own snapshot and its own services, and a listing about a third party is a
different object with a different contract. Errors here are flat `{error_code, message}`
as the lane contract specifies, which is not the nested `{"error": {...}}` the snapshot
routes return — the divergence is on purpose and is documented in llms.txt so a client
knows which shape to expect from which prefix.

Search is answered locally first and only then from the registry. The store holds every
listing Docket has ever hydrated or verified; a query that the store cannot fill is
completed by one paced `search_agents` page, whose results are written back as cache rows
at level None. Being findable in an index is not an observation, so a hydrated row starts
with no level at all and moves only when `POST /api/agents/{id}/verify` records evidence.

Two bounds sit on the network paths. `POST /api/agents/{id}/verify` spends from the same
per-IP allowance the existing re-probe route spends from, because it makes the same kind
of request to the same kind of third-party host. On-demand registry hydration spends from
an allowance of this router's own, so a stranger cannot turn Docket's search box into an
unmetered proxy onto 8004scan.
"""

import hashlib
import json
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from ..marketplace import providers as provider_flow
from ..marketplace.external import (
    LEVELS,
    ExternalListing,
    listing_from_registry,
    load_seed,
)
from ..marketplace.models import Category
from ..marketplace.verification import (
    LEVEL_PREREQUISITE,
    _now as verification_now,
    apply_result,
    send as guarded_send,
    verify_listing,
)
from ..scan8004 import Scan8004Client, canonical_agent_id, lookup_owner_onchain
from ..store import Store

DEFAULT_LIMIT = 20
MAX_LIMIT = 100
# Deep paging over a table this size is a scan with nothing at the end of it, and an
# unbounded OFFSET is a free way to make the database work.
MAX_OFFSET = 10_000
# A search box, not a document upload. Bounded before it reaches a LIKE pattern.
MAX_QUERY_CHARS = 200
CHAIN_ID = 56
SEED_PATH = (
    Path(__file__).resolve().parents[1]
    / "marketplace"
    / "seed"
    / "external-listings-2026-09-03.json"
)
# The registry-hydration allowance. Wider than the hire allowance because a reader typing
# in a search box is doing something cheap and legitimate, and narrow enough that the
# route cannot be used to relay a sweep: 60 lookups an hour is one every minute.
LOOKUP_ATTEMPTS = 60
LOOKUP_WINDOW_S = 3600
MAX_ALLOWANCE_CLIENTS = 2048


def _error(
    status_code: int, error_code: str, message: str, headers=None
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error_code": error_code, "message": message},
        headers=headers,
    )


@dataclass
class MarketplaceContext:
    """Everything the router needs, handed in rather than reached for.

    `spend_probe` is `create_app`'s own per-IP allowance, bound to the same attempts and
    window the re-probe route uses, so a caller cannot get a second budget by asking for
    the same work through a different path.
    """

    db_path: Path
    spend_probe: Callable[[str], int | None]
    probe_attempts: int
    probe_window_seconds: int
    seed_path: Path | None = SEED_PATH
    search_client: Callable[[], Scan8004Client] = Scan8004Client
    rpc: Callable[[str], dict] = lookup_owner_onchain
    http: Callable[..., dict] = guarded_send
    chain_id: int = CHAIN_ID
    # Stamped onto every hydrated row. Ordering falls back to `updated_at` within a level,
    # and a row stored with no timestamp sorts unpredictably against one that has one.
    now: Callable[[], str] = verification_now
    lookups: "OrderedDict[str, tuple[float, int]]" = field(default_factory=OrderedDict)


def _spend_lookup(windows, client_ip: str) -> int | None:
    """One registry lookup from this peer's allowance, or seconds until it resets.

    Keyed on the peer address only, for the reason `routes._spend_window` gives:
    `X-Forwarded-For` is caller-controlled and reading it would make the bound a header
    anyone can rewrite.
    """
    now = time.monotonic()
    while windows:
        _, (oldest_started, _) = next(iter(windows.items()))
        if now - oldest_started < LOOKUP_WINDOW_S:
            break
        windows.popitem(last=False)
    current = windows.get(client_ip)
    if current is None:
        if len(windows) >= MAX_ALLOWANCE_CLIENTS:
            windows.popitem(last=False)
        started, used = now, 0
        windows[client_ip] = (started, used)
    else:
        started, used = current
    if used >= LOOKUP_ATTEMPTS:
        return int(LOOKUP_WINDOW_S - (now - started)) + 1
    windows[client_ip] = (started, used + 1)
    return None


def _resolved_id(agent_id: str) -> tuple[str | None, JSONResponse | None]:
    """The canonical agent id, or the refusal to answer with.

    Every path that takes an `{agent_id}` goes through this, so a bare token id and its
    full form reach the same stored row on every route rather than only on the one that
    remembered to normalise.
    """
    try:
        return canonical_agent_id(agent_id), None
    except (TypeError, ValueError) as exc:
        return None, _error(422, "invalid_agent_id", str(exc))


def _positive_int(raw, *, name: str, default: int, maximum: int):
    """Parse a bound integer in-route, so a bad one is refused in this router's own shape.

    FastAPI would coerce these and answer its own 422 through the app-level validation
    handler, which emits the nested `{"error": {...}}` envelope every other route uses —
    a client told to branch on `error_code` under `/api/` would find neither key.
    """
    if raw is None:
        return default, None
    text = str(raw).strip()
    if not text.isdigit() or not text.isascii():
        return None, _error(
            422, f"invalid_{name}", f"{name} must be a non-negative whole number."
        )
    return min(int(text), maximum), None


def marketplace_router(context: MarketplaceContext) -> APIRouter:
    router = APIRouter()
    _load_seed_if_empty(context)

    def store() -> Store:
        return Store(context.db_path)

    def client_ip(request: Request) -> str:
        return request.client.host if request.client else "unknown"

    def hydrate(rows: list[dict], *, source: str) -> list[dict]:
        """Cache registry results as listings and return them.

        Written at level None: 8004scan holding a row is not an observation Docket made,
        and a hydrated listing must not sort above one whose `ownerOf` actually answered.
        A row already held is left alone, so hydration never overwrites evidence.

        `source` separates the two shapes the index serves. A SEARCH page carries no
        endpoints — only the per-agent card does — so a row built from one is stored as
        `registry_index_list` and upgraded by `upgrade_from_card` before anything is
        verified against it. Storing both under one name left rows that could never pass
        `endpoint_detected` looking like agents that declare no endpoint.
        """
        held = store()
        listings = []
        for row in rows:
            agent_id = str(row.get("agent_id") or "")
            if not agent_id:
                continue
            existing = held.external_listing(agent_id)
            if existing:
                listings.append(existing)
                continue
            listing = listing_from_registry(
                row, chain_id=context.chain_id, updated_at=context.now()
            )
            payload = replace(listing, source=source).to_json()
            held.upsert_external_listing(payload)
            listings.append(payload)
        return listings

    def upgrade_from_card(listing: dict, request: Request):
        """Fetch the per-agent card once for a row built from a search page.

        Returns `(listing, refusal)`. Spends from the lookup allowance, because it is one
        more request to the index. A row that has already been upgraded, or that came from
        a card in the first place, is returned untouched and spends nothing.
        """
        if listing.get("source") != "registry_index_list":
            return listing, None
        resets_in = _spend_lookup(context.lookups, client_ip(request))
        if resets_in is not None:
            return listing, _error(
                429,
                "lookup_rate_limited",
                f"This listing was found on a search page and its endpoints have not been "
                f"read yet, and this caller has used its allowance of {LOOKUP_ATTEMPTS} "
                f"registry lookups per {LOOKUP_WINDOW_S} seconds; retry in {resets_in}s.",
                headers={"Retry-After": str(resets_in)},
            )
        token_id = listing["agent_id"].rsplit(":", 1)[1]
        try:
            card = _registry_agent(context, token_id)
        except Exception as exc:
            return listing, _error(
                502,
                "registry_unavailable",
                f"The registry index did not answer for {listing['agent_id']!r}: "
                f"{type(exc).__name__}.",
            )
        upgraded = replace(
            listing_from_registry(
                card, chain_id=context.chain_id, updated_at=context.now()
            ),
            verification=ExternalListing.from_json(listing).verification,
            source="registry_index",
        ).to_json()
        store().upsert_external_listing(upgraded)
        return upgraded, None

    @router.get("/api/agents")
    async def search_agents_route(
        request: Request,
        q: str | None = None,
        category: str | None = None,
        level: str | None = None,
        limit: str | None = None,
        offset: str | None = None,
    ):
        """Listings Docket holds, completed from the BSC registry when a query needs it."""
        if category is not None and category not in {c.value for c in Category}:
            return _error(
                422,
                "invalid_category",
                f"{category!r} is not one of {[c.value for c in Category]}.",
            )
        if level is not None and level not in LEVELS:
            return _error(
                422,
                "invalid_level",
                f"{level!r} is not one of {list(LEVELS)}. A listing that has only been "
                "seen in the registry index carries no level at all.",
            )
        if q is not None and len(q) > MAX_QUERY_CHARS:
            return _error(
                422,
                "invalid_query",
                f"q is at most {MAX_QUERY_CHARS} characters; got {len(q)}.",
            )
        limit, refusal = _positive_int(
            limit, name="limit", default=DEFAULT_LIMIT, maximum=MAX_LIMIT
        )
        if refusal is not None:
            return refusal
        offset, refusal = _positive_int(
            offset, name="offset", default=0, maximum=MAX_OFFSET
        )
        if refusal is not None:
            return refusal
        limit = max(limit, 1)
        held = store()
        items, total = held.search_external_listings(
            query=q, category=category, level=level, limit=limit, offset=offset
        )
        lookup = {"attempted": False, "hydrated": 0, "reason": None}
        if level is not None:
            # A level filter is a question about what Docket has observed, and the index
            # can only add rows it has observed nothing about. Asking it would spend the
            # allowance to fetch listings this query is guaranteed to exclude.
            lookup["reason"] = (
                "a level filter selects on what Docket observed, and the registry index "
                "can only add listings with no level at all"
            )
        elif q and len(items) < limit:
            resets_in = _spend_lookup(context.lookups, client_ip(request))
            if resets_in is not None:
                lookup["reason"] = (
                    f"this caller has used its allowance of {LOOKUP_ATTEMPTS} registry "
                    f"lookups per {LOOKUP_WINDOW_S} seconds; it resets in {resets_in}s"
                )
            else:
                lookup["attempted"] = True
                try:
                    rows = await run_in_threadpool(_registry_page, context, q, limit)
                except Exception as exc:
                    lookup["reason"] = (
                        f"the registry index did not answer: {type(exc).__name__}"
                    )
                else:
                    before = held.external_listing_count()
                    hydrate(rows, source="registry_index_list")
                    lookup["hydrated"] = held.external_listing_count() - before
                    items, total = held.search_external_listings(
                        query=q,
                        category=category,
                        level=level,
                        limit=limit,
                        offset=offset,
                    )
        return {
            "items": items,
            "total": total,
            "limit": limit,
            "offset": offset,
            "filters": {"q": q, "category": category, "level": level},
            "registry_lookup": lookup,
            "levels": list(LEVELS),
            "listings_by_level": held.external_listings_by_level(),
        }

    @router.get("/api/agents/{agent_id}")
    async def get_listing(request: Request, agent_id: str):
        agent_id, refusal = _resolved_id(agent_id)
        if refusal is not None:
            return refusal
        held = store()
        listing = held.external_listing(agent_id)
        if not listing:
            resets_in = _spend_lookup(context.lookups, client_ip(request))
            if resets_in is not None:
                return _error(
                    429,
                    "lookup_rate_limited",
                    f"This caller has used its allowance of {LOOKUP_ATTEMPTS} registry "
                    f"lookups per {LOOKUP_WINDOW_S} seconds; retry in {resets_in}s.",
                    headers={"Retry-After": str(resets_in)},
                )
            token_id = agent_id.rsplit(":", 1)[1]
            try:
                detail = await run_in_threadpool(_registry_agent, context, token_id)
            except Exception as exc:
                # An upstream 404 means the index does not hold this agent, which is an
                # answer about the agent. Reporting it as an outage would tell a caller to
                # retry something that will keep saying no.
                if _is_upstream_not_found(exc):
                    return _error(
                        404,
                        "listing_not_found",
                        f"The registry index holds no agent {agent_id!r} on chain "
                        f"{context.chain_id}.",
                    )
                return _error(
                    502,
                    "registry_unavailable",
                    f"The registry index did not answer for {agent_id!r}: "
                    f"{type(exc).__name__}.",
                )
            hydrated = hydrate([detail], source="registry_index")
            if not hydrated:
                return _error(
                    404,
                    "listing_not_found",
                    f"The registry index holds no agent {agent_id!r} on chain "
                    f"{context.chain_id}.",
                )
            listing = hydrated[0]
        else:
            listing, refusal = await run_in_threadpool(
                upgrade_from_card, listing, request
            )
            if refusal is not None and listing.get("source") == "registry_index_list":
                return refusal
        return {
            "listing": listing,
            "levels": list(LEVELS),
            "level_prerequisites": LEVEL_PREREQUISITE,
        }

    @router.get("/api/agents/{agent_id}/verification")
    async def get_verification(agent_id: str):
        agent_id, refusal = _resolved_id(agent_id)
        if refusal is not None:
            return refusal
        held = store()
        listing = held.external_listing(agent_id)
        if not listing:
            return _error(
                404,
                "listing_not_found",
                f"No listing for {agent_id!r}. Fetch it once at GET /api/agents/{agent_id}.",
            )
        return {
            "agent_id": agent_id,
            "verification": listing.get("verification"),
            "hireable": listing.get("hireable"),
            # What THIS deployment recorded. A listing seeded from the committed census
            # carries that census's evidence in `verification.evidence` and has no runs
            # here until somebody verifies it against this instance.
            "runs": held.iter_verification_runs(agent_id),
            "runs_note": (
                "runs are the level attempts this deployment recorded. A seeded listing "
                "carries the evidence it arrived with in verification.evidence"
            ),
            "levels": list(LEVELS),
            "level_prerequisites": LEVEL_PREREQUISITE,
        }

    @router.post("/api/agents/{agent_id}/verify")
    async def run_verification(agent_id: str, request: Request):
        """Re-run every level against this listing and record what each one observed."""
        agent_id, refusal = _resolved_id(agent_id)
        if refusal is not None:
            return refusal
        payload, failure = await _json_body(request)
        if failure is not None:
            return failure
        if payload != {}:
            return _error(
                400, "invalid_json", "Verification requires an empty JSON object."
            )
        held = store()
        held_listing = held.external_listing(agent_id)
        if not held_listing:
            return _error(
                404,
                "listing_not_found",
                f"No listing for {agent_id!r}. Fetch it once at GET /api/agents/{agent_id}.",
            )
        # A row built from a search page has no endpoints and would fail
        # `endpoint_detected` for a reason that is about Docket's cache rather than about
        # the agent. Read its card once, then verify what it actually declares.
        held_listing, refusal = await run_in_threadpool(
            upgrade_from_card, held_listing, request
        )
        if refusal is not None and held_listing.get("source") == "registry_index_list":
            return refusal
        peer = client_ip(request)
        resets_in = context.spend_probe(peer)
        if resets_in is not None:
            return _error(
                429,
                "verify_rate_limited",
                f"This caller has used its shared free-work allowance of "
                f"{context.probe_attempts} attempts per "
                f"{context.probe_window_seconds} seconds; retry in {resets_in}s.",
                headers={"Retry-After": str(resets_in)},
            )
        listing = ExternalListing.from_json(held_listing)

        def run() -> dict:
            fresh = Store(context.db_path)
            result = verify_listing(
                listing, store=fresh, http=context.http, rpc=context.rpc
            )
            updated = apply_result(listing, result)
            fresh.upsert_external_listing(updated.to_json())
            return {
                "agent_id": agent_id,
                "level": result.level,
                "previous_level": result.previous_level,
                "verified_at": result.verified_at,
                "chain_read_failed": result.outage,
                "evidence": result.evidence,
                "listing": updated.to_json(),
                "requested_from_ip_hash": hashlib.sha256(
                    peer.encode("utf-8")
                ).hexdigest(),
            }

        return await run_in_threadpool(run)

    @router.post("/api/providers/claim")
    async def provider_claim(request: Request):
        """Mint a nonce, or spend one to prove ownership.

        `{agent_id}` mints. `{agent_id, nonce, signature}` spends: Docket recovers the
        signer of the exact sentence it printed and holds it against `ownerOf` on chain
        56. A nonce is single use and can be spent here or on POST /api/providers/listings,
        never on both.
        """
        payload, failure = await _json_body(request)
        if failure is not None:
            return failure
        if not isinstance(payload, dict):
            return _error(400, "invalid_json", "Send a JSON object.")
        agent_id = payload.get("agent_id")
        if not isinstance(agent_id, str) or not agent_id.strip():
            return _error(400, "invalid_agent_id", "agent_id is required.")
        held = store()
        signature = payload.get("signature")
        if signature is None:
            # Minting writes a row and costs nothing to ask for, so it is metered like
            # every other write-shaped anonymous call on this router. Unmetered, one
            # caller could fill `provider_claims` with nonces nobody will ever sign.
            resets_in = _spend_lookup(context.lookups, client_ip(request))
            if resets_in is not None:
                return _error(
                    429,
                    "claim_rate_limited",
                    f"This caller has used its allowance of {LOOKUP_ATTEMPTS} claim "
                    f"nonces and registry lookups per {LOOKUP_WINDOW_S} seconds; retry "
                    f"in {resets_in}s.",
                    headers={"Retry-After": str(resets_in)},
                )
            try:
                issued = await run_in_threadpool(
                    provider_flow.issue_claim_nonce, agent_id.strip(), store=held
                )
            except provider_flow.ClaimError as exc:
                return _error(_claim_status(exc.code), exc.code, exc.message)
            return JSONResponse(status_code=201, content=issued)
        nonce = payload.get("nonce")
        if not isinstance(nonce, str) or not isinstance(signature, str):
            return _error(
                400,
                "invalid_signature",
                "Spending a claim needs the nonce Docket issued and the signature over "
                "its message, both as strings.",
            )
        try:
            claim = await run_in_threadpool(
                _verify_claim, context, agent_id.strip(), signature, nonce
            )
        except provider_flow.ClaimError as exc:
            return _error(_claim_status(exc.code), exc.code, exc.message)
        return {
            "agent_id": claim.agent_id,
            "owner": claim.owner,
            "nonce": claim.nonce,
            "verified_at": claim.verified_at,
            "token_uri": claim.token_uri,
        }

    @router.post("/api/providers/listings")
    async def provider_listing(request: Request):
        """Spend a nonce and write the owner's own description of their agent."""
        payload, failure = await _json_body(request)
        if failure is not None:
            return failure
        if not isinstance(payload, dict):
            return _error(400, "invalid_json", "Send a JSON object.")
        agent_id = payload.get("agent_id")
        nonce = payload.get("nonce")
        signature = payload.get("signature")
        if not all(
            isinstance(value, str) and value.strip()
            for value in (agent_id, nonce, signature)
        ):
            return _error(
                400,
                "invalid_claim",
                "agent_id, nonce and signature are required, all as strings.",
            )
        try:
            # Validated BEFORE the nonce is spent. A submission refused for a typo used to
            # burn the nonce on the way in, sending the owner back to their wallet to sign
            # again over a spelling mistake.
            provider_flow.validate_listing_fields(
                capabilities=payload.get("capabilities"),
                category=payload.get("category"),
                price=payload.get("price"),
                payment_method=payload.get("payment_method"),
                sample_input=payload.get("sample_input"),
                output_schema=payload.get("output_schema"),
            )
            claim = await run_in_threadpool(
                _verify_claim, context, agent_id.strip(), signature, nonce
            )
            listing = await run_in_threadpool(_submit, context, claim, payload)
        except provider_flow.ClaimError as exc:
            return _error(_claim_status(exc.code), exc.code, exc.message)
        return JSONResponse(
            status_code=201,
            content={
                "listing": listing.to_json(),
                "next_step": (
                    "This listing stands at level registered and is not hireable. Run "
                    f"POST /api/agents/{listing.agent_id}/verify to have Docket observe "
                    "the endpoint your registration names."
                ),
            },
        )

    return router


def _registry_page(context: MarketplaceContext, query: str, limit: int) -> list[dict]:
    """One page of the narrowed registry query. Never the whole registry."""
    with context.search_client() as client:
        rows, _ = client.search_agents(
            context.chain_id, query=query, limit=limit, offset=0
        )
    return rows


def _registry_agent(context: MarketplaceContext, token_id: str) -> dict:
    with context.search_client() as client:
        return client.get_agent(context.chain_id, token_id)


def _verify_claim(
    context: MarketplaceContext, agent_id: str, signature: str, nonce: str
):
    return provider_flow.verify_claim(
        agent_id,
        signature,
        nonce=nonce,
        store=Store(context.db_path),
        rpc=context.rpc,
    )


def _submit(context: MarketplaceContext, claim, payload: dict) -> ExternalListing:
    return provider_flow.submit_listing(
        claim,
        capabilities=str(payload.get("capabilities") or ""),
        category=payload.get("category"),
        price=payload.get("price"),
        payment_method=payload.get("payment_method"),
        sample_input=payload.get("sample_input"),
        output_schema=payload.get("output_schema"),
        store=Store(context.db_path),
    )


# Which HTTP status each refusal carries. Written out rather than defaulted, so a new
# code has to be classified rather than arriving as a 400 nobody chose.
_CLAIM_STATUS = {
    "stale_nonce": 409,
    "bad_signature": 401,
    "not_owner": 403,
    "not_registered": 404,
    "chain_unavailable": 503,
    "invalid_agent_id": 422,
    "invalid_category": 422,
    "invalid_payment_method": 422,
    "invalid_capabilities": 422,
    "invalid_sample_input": 422,
    "invalid_output_schema": 422,
    "invalid_price": 422,
}


def _is_upstream_not_found(exc: Exception) -> bool:
    """Whether an index failure was the index answering "no such agent".

    `Scan8004Client._get` raises `httpx.HTTPStatusError` for a 404, and a 404 is an answer
    about the agent rather than a failure of the road to it. Reported as an outage it would
    tell a caller to retry something that will keep saying no.
    """
    response = getattr(exc, "response", None)
    return getattr(response, "status_code", None) == 404


def _claim_status(code: str) -> int:
    return _CLAIM_STATUS.get(code, 400)


async def _json_body(request: Request):
    """The request body, read through the hire route's own limits and content-type check.

    Reused rather than reimplemented: the size cap, the duplicated-Content-Length check
    and the JSON parsing are already correct there and must not fork. Only the error
    envelope is translated, because this router answers flat `{error_code, message}`.
    """
    from .routes import _read_hire_json

    payload, failure = await _read_hire_json(request)
    if failure is None:
        return payload, None
    detail = json.loads(bytes(failure.body))["error"]
    return None, _error(failure.status_code, detail["code"], detail["message"])


def _load_seed_if_empty(context: MarketplaceContext) -> int:
    """Seed the committed census into an empty table, and never over a populated one.

    Loaded at construction rather than per request, and guarded on the table being empty,
    so a running deployment that has verified listings is never overwritten by the file
    the wheel shipped with.
    """
    if context.seed_path is None or not Path(context.seed_path).is_file():
        return 0
    held = Store(context.db_path)
    if held.external_listing_count():
        return 0
    listings = load_seed(Path(context.seed_path))
    for listing in listings:
        held.upsert_external_listing(listing.to_json())
    return len(listings)
