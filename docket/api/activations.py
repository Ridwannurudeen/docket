"""The activation API: the door a browser drives, and the only place signatures are read.

Every mutating route follows the same five steps, in this order and for these reasons:

  1. Load the activation. A caller that names one that does not exist learns that before
     anything else is checked.
  2. Recover the owner from the signature over the exact message the server issued. An
     unrecoverable signature is `bad_signature`; one that recovers to somebody else is
     `not_owner`. The two are different facts and are reported as different codes.
  3. Spend the nonce, in one atomic statement. This is what makes a signature single-use:
     two requests holding the same one cannot both get past it, and the loser is told
     `stale_nonce` rather than quietly replaying the winner's work.
  4. Do the thing, in `ActivationService`, which knows nothing about HTTP.
  5. Serve the activation back, carrying its fresh nonce for the next call.

Errors are `{"error_code", "message"}` — the shape the pivot plan fixed for this router,
which is deliberately not the `{"error": {...}}` envelope the rest of the API uses. Bodies
are read and validated by hand rather than through a pydantic model, because a model's
own 422 would arrive in the other shape and a client would face two contracts on one path.
"""

import json
from datetime import datetime, timezone

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool
from web3 import Web3

from ..escrow.chain import Rpc
from ..jobs.auth import (
    action_message,
    create_message,
    new_nonce,
    recover_signer,
    same_address,
    verify_owner_signature,
)
from ..jobs.executors.allowlists import defaults_for, token_hints_for
from ..jobs.models import KINDS
from ..marketplace.registry import get_record
from ..jobs.service import (
    ActivationExpired,
    ActivationNotFound,
    ActivationService,
    IllegalTransition,
    MissingFields,
    PolicyViolation,
    SessionsUnavailable,
    SimulationFailed,
    StaleActivation,
    UnknownService,
)
from ..store import (
    ACTIVATION_NONCE_TTL_SECONDS,
    MAX_ACTIVATION_PAGE,
    MAX_OPEN_ACTIVATIONS_PER_OWNER,
)

# One megabyte, the same ceiling `POST /hire/{service_id}` reads a body under. An
# activation body is a service request plus a policy; nothing legitimate approaches it.
MAX_BODY_BYTES = 1_048_576
# A service request body and a session policy, each bounded on its own. The whole-body
# ceiling above is generous because it is shared with the hire route; these two are
# the fields an activation actually stores and serves back, forever, to anyone who
# reads the activation.
MAX_INPUTS_BYTES = 16_384
MAX_POLICY_BYTES = 8_192
# States in which an activation is still Docket's problem: it occupies a slot, and for
# a persistent one a keystore and a slice of every tick.
OPEN_STATES = (
    "quoted",
    "awaiting_wallet",
    "authorized",
    "awaiting_session",
    "paid_or_reserved",
    "queued",
    "running",
    "needs_approval",
    "funded",
    "active",
    "paused",
    "revoking",
)


def _error(status_code: int, error_code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error_code": error_code, "message": message},
    )


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _checksum_or_none(owner) -> str | None:
    """One spelling of an address, so a lowercase wallet and a checksummed one are the
    same owner. Anything that is not an address stays None and filters nothing."""
    if not owner:
        return None
    try:
        return Web3.to_checksum_address(owner)
    except Exception:
        return None


async def _read_json(request: Request):
    """The body as an object, or the error a caller can act on."""
    declared = request.headers.get("content-length")
    if declared is not None and declared.isdigit() and int(declared) > MAX_BODY_BYTES:
        return None, _error(
            413,
            "invalid_json",
            f"The request body must be at most {MAX_BODY_BYTES} bytes.",
        )
    raw = await request.body()
    if len(raw) > MAX_BODY_BYTES:
        return None, _error(
            413,
            "invalid_json",
            f"The request body must be at most {MAX_BODY_BYTES} bytes.",
        )
    try:
        payload = json.loads(raw or b"{}")
    except ValueError:
        return None, _error(400, "invalid_json", "The body must be valid JSON.")
    if not isinstance(payload, dict):
        return None, _error(400, "invalid_json", "The body must be a JSON object.")
    return payload, None


def _oversized(value, ceiling: int, field: str):
    """Refuse a field that would be stored and served back for ever, before storing it."""
    if value is None:
        return None
    try:
        size = len(json.dumps(value, ensure_ascii=False).encode("utf-8"))
    except (TypeError, ValueError):
        return _error(400, "invalid_json", f"{field} is not JSON Docket can store.")
    if size > ceiling:
        return _error(
            413,
            "invalid_json",
            f"{field} is {size} bytes; the limit is {ceiling}.",
        )
    return None


def _service_error(exc: Exception) -> JSONResponse:
    """One translation table from what the state machine raises to what a client reads."""
    if isinstance(exc, ActivationNotFound):
        return _error(404, "activation_not_found", f"No activation {exc.args[0]!r}.")
    if isinstance(exc, UnknownService):
        return _error(
            404,
            "service_not_found",
            f"No activatable service {exc.args[0]!r}. GET /services lists every service "
            "Docket runs and the category it declares for each.",
        )
    if isinstance(exc, MissingFields):
        return _error(422, "missing_field", str(exc))
    if isinstance(exc, ActivationExpired):
        return _error(409, "expired", str(exc))
    if isinstance(exc, SimulationFailed):
        return _error(409, "simulation_failed", str(exc))
    if isinstance(exc, IllegalTransition):
        return _error(409, "illegal_transition", str(exc))
    if isinstance(exc, PolicyViolation):
        return _error(409, "policy_violation", str(exc))
    if isinstance(exc, StaleActivation):
        return _error(409, "illegal_transition", str(exc))
    if isinstance(exc, SessionsUnavailable):
        return _error(503, "sessions_unavailable", str(exc))
    if isinstance(exc, ValueError):
        return _error(422, "policy_violation", str(exc))
    raise exc


def activations_router(
    store, *, services, pay_to=None, rpc=None, now=None
) -> APIRouter:
    """Every activation route, closed over the one store the application opened."""
    shared_rpc = Rpc() if rpc is None else rpc
    clock = _utc_now if now is None else now

    def _service() -> ActivationService:
        return ActivationService(
            store,
            services=services,
            rpc=shared_rpc,
            now=clock,
            pay_to=pay_to,
        )

    router = APIRouter()

    # Declared before `/{activation_id}`, or `nonce` would match the id parameter and a
    # caller asking for a nonce would be told no such activation exists.
    @router.get("/api/activations/nonce", response_model=None)
    async def activation_nonce(request: Request) -> JSONResponse:
        """Issue one single-use nonce, and the exact message to sign for a create."""
        try:
            owner = Web3.to_checksum_address(
                request.query_params.get("owner", "").strip()
            )
        except Exception:
            return _error(
                422,
                "missing_field",
                "owner is required and must be an address: "
                "/api/activations/nonce?owner=0x…",
            )
        service_id = request.query_params.get("service_id", "").strip()
        nonce = new_nonce()
        message = create_message(service_id, nonce) if service_id else None
        expires_at = await run_in_threadpool(
            store.issue_activation_nonce,
            nonce=nonce,
            owner=owner,
            message=message or "",
        )
        return JSONResponse(
            status_code=200,
            content={
                "nonce": nonce,
                "message": message,
                "expires_at": expires_at,
                "expires_in_seconds": ACTIVATION_NONCE_TTL_SECONDS,
                "sign": (
                    "personal_sign this exact message with the owner wallet and send it "
                    "as owner_signature"
                    if message
                    else "call again with &service_id=… to be given the exact message "
                    "this nonce must be signed against"
                ),
            },
        )

    @router.get("/api/activations/policy-defaults", response_model=None)
    async def policy_defaults(request: Request) -> JSONResponse:
        """The session policy skeleton for one service's category.

        A browser has no way to know which contracts a category's session must call, so
        it asks. What comes back validates as-is once `expires_at` is added, and the caps
        are a starting point an owner is expected to raise knowingly rather than a
        recommendation.
        """
        service_id = request.query_params.get("service_id", "").strip()
        if not service_id:
            return _error(
                422,
                "missing_field",
                "service_id is required: /api/activations/policy-defaults?service_id=…",
            )
        record = get_record(service_id)
        if record is None or record.category is None:
            return _error(
                404,
                "service_not_found",
                f"No activatable service {service_id!r}.",
            )
        try:
            defaults = defaults_for(record.category.value)
        except KeyError:
            return _error(
                404,
                "service_not_found",
                f"Docket publishes no session defaults for {record.category.value}.",
            )
        return JSONResponse(
            status_code=200,
            content={
                "service_id": service_id,
                "category": record.category.value,
                "policy": defaults,
                "token_hints": token_hints_for(record.category.value),
                "you_must_add": ["expires_at"],
                "note": (
                    "Send this as `policy` with an `expires_at` added, or omit the three "
                    "allowlists from your own policy and Docket fills them from here. "
                    "The caps are a small starting point, not a recommendation: the loss "
                    "ceiling of a session is the float you fund it with."
                ),
            },
        )

    @router.get("/api/activations", response_model=None)
    async def list_activations(request: Request) -> JSONResponse:
        # Checksummed before it becomes a filter: an activation is stored under its
        # checksummed owner, and a wallet that hands back a lowercase address would
        # otherwise be told it owns nothing.
        # Required, not optional. Without it this route enumerates every activation on
        # the site, which is a directory of who is running what — and the plan writes the
        # route as `?owner=0x..` for that reason. A `state=` filter alone is not a
        # narrowing anybody is entitled to.
        owner = _checksum_or_none(request.query_params.get("owner"))
        if owner is None:
            return _error(
                422,
                "missing_field",
                "owner is required and must be an address: "
                "/api/activations?owner=0x…",
            )
        state = request.query_params.get("state") or None
        try:
            limit = int(request.query_params.get("limit", 50))
            offset = int(request.query_params.get("offset", 0))
        except ValueError:
            return _error(
                422, "missing_field", "limit and offset must be whole numbers."
            )
        if not 1 <= limit <= MAX_ACTIVATION_PAGE or offset < 0:
            return _error(
                422,
                "missing_field",
                f"limit must be between 1 and {MAX_ACTIVATION_PAGE} and offset cannot "
                "be negative.",
            )
        rows = await run_in_threadpool(
            store.list_activations, owner, state, limit, offset
        )
        total = await run_in_threadpool(store.count_activations, owner, state)
        return JSONResponse(
            status_code=200,
            content={
                "activations": [activation.to_dict() for activation in rows],
                "total": total,
                "limit": limit,
                "offset": offset,
            },
        )

    @router.post("/api/activations", response_model=None)
    async def create_activation(request: Request) -> JSONResponse:
        payload, error = await _read_json(request)
        if error is not None:
            return error
        missing = [
            field
            for field in ("service_id", "kind", "owner", "owner_signature", "nonce")
            if not str(payload.get(field) or "").strip()
        ]
        if missing:
            return _error(
                422,
                "missing_field",
                f"a create request requires {', '.join(missing)}",
            )
        service_id = str(payload["service_id"])
        kind = str(payload["kind"])
        owner = str(payload["owner"])
        if kind not in KINDS:
            return _error(
                422, "missing_field", f"kind must be one of {', '.join(KINDS)}"
            )
        inputs = payload.get("inputs") or {}
        if not isinstance(inputs, dict):
            return _error(400, "invalid_json", "inputs must be a JSON object.")
        oversized = _oversized(inputs, MAX_INPUTS_BYTES, "inputs") or _oversized(
            payload.get("policy"), MAX_POLICY_BYTES, "policy"
        )
        if oversized is not None:
            return oversized
        open_activations = await run_in_threadpool(
            store.open_activation_count,
            _checksum_or_none(owner) or owner,
            OPEN_STATES,
        )
        if open_activations >= MAX_OPEN_ACTIVATIONS_PER_OWNER:
            return _error(
                422,
                "too_many_activations",
                f"This owner already has {open_activations} activations that have not "
                f"finished; the limit is {MAX_OPEN_ACTIVATIONS_PER_OWNER}. Cancel or "
                "revoke one before starting another.",
            )

        message = create_message(service_id, str(payload["nonce"]))
        if not verify_owner_signature(owner, message, str(payload["owner_signature"])):
            return _error(
                401,
                "bad_signature",
                f"owner_signature did not recover to {owner} over {message!r}.",
            )
        # Validated before the nonce is spent: a malformed body must not cost the caller
        # its signature and a fresh round-trip to the wallet.
        try:
            await run_in_threadpool(
                lambda: _service().validate_request(
                    service_id,
                    kind=kind,
                    owner=owner,
                    inputs=inputs,
                    policy=payload.get("policy"),
                    nft_approvals=tuple(payload.get("nft_approvals") or ()),
                )
            )
        except Exception as exc:
            return _service_error(exc)

        spent, issued_message = await run_in_threadpool(
            store.consume_activation_nonce,
            str(payload["nonce"]),
            _checksum_or_none(owner) or owner,
        )
        if not spent:
            return _error(
                409,
                "stale_nonce",
                "That nonce was already spent or has expired. Ask "
                "/api/activations/nonce for another and sign the message it returns.",
            )
        # A nonce issued against one service may not be spent on another. The server
        # recorded exactly what it told the caller to sign; if that named a service, that
        # is the service this nonce buys.
        if issued_message and issued_message != message:
            return _error(
                409,
                "stale_nonce",
                f"That nonce was issued for {issued_message!r} and cannot be spent on "
                f"{message!r}.",
            )
        try:
            activation = await run_in_threadpool(
                lambda: _service().create(
                    service_id,
                    kind=kind,
                    owner=owner,
                    inputs=inputs,
                    policy=payload.get("policy"),
                    nft_approvals=tuple(payload.get("nft_approvals") or ()),
                )
            )
        except Exception as exc:
            return _service_error(exc)
        return JSONResponse(status_code=201, content=activation.to_dict())

    @router.get("/api/activations/{activation_id}", response_model=None)
    async def read_activation(activation_id: str) -> JSONResponse:
        activation = await run_in_threadpool(store.get_activation, activation_id)
        if activation is None:
            return _error(
                404, "activation_not_found", f"No activation {activation_id!r}."
            )
        return JSONResponse(status_code=200, content=activation.to_dict())

    @router.get("/api/activations/{activation_id}/prepared", response_model=None)
    async def prepared(activation_id: str) -> JSONResponse:
        try:
            calls = await run_in_threadpool(_service().prepared_calls, activation_id)
        except Exception as exc:
            return _service_error(exc)
        return JSONResponse(
            status_code=200, content={"calls": [call.to_dict() for call in calls]}
        )

    async def _mutate(activation_id: str, action: str, request: Request, apply):
        payload, error = await _read_json(request)
        if error is not None:
            return error
        signature = str(payload.get("owner_signature") or "")
        nonce = str(payload.get("nonce") or "")
        if not signature or not nonce:
            return _error(
                422,
                "missing_field",
                "owner_signature and nonce are required on every mutating call.",
            )
        # The evidence the call carries is part of what was signed. A signature over
        # "approve this activation" alone would authorise approving it against any
        # transaction hash a middle could substitute afterwards.
        binds = str(payload.get("tx_hash") or payload.get("payment_id") or "")
        activation = await run_in_threadpool(store.get_activation, activation_id)
        if activation is None:
            return _error(
                404, "activation_not_found", f"No activation {activation_id!r}."
            )
        message = action_message(activation_id, action, nonce, binds)
        recovered = recover_signer(message, signature)
        if recovered is None:
            return _error(
                401,
                "bad_signature",
                f"owner_signature is not a signature over {message!r}.",
            )
        # Recovered, but to whom? A valid signature from somebody who is not the owner is
        # a different fact from an unreadable one, and reporting both as `bad_signature`
        # would hide an attempt to act on another owner's activation behind a typo.
        if not same_address(activation.owner, recovered):
            return _error(
                403,
                "not_owner",
                f"{recovered} signed that message; {activation_id} belongs to "
                f"{activation.owner}.",
            )
        if not await run_in_threadpool(
            store.rotate_auth_nonce,
            activation_id,
            expected_nonce=nonce,
            new_nonce=new_nonce(),
        ):
            return _error(
                409,
                "stale_nonce",
                "That nonce is not this activation's current one. Read the activation "
                "again and sign its auth_nonce.",
            )
        try:
            updated = await run_in_threadpool(lambda: apply(payload))
        except Exception as exc:
            return _service_error(exc)
        return JSONResponse(status_code=200, content=updated.to_dict())

    @router.post("/api/activations/{activation_id}/approve", response_model=None)
    async def approve(activation_id: str, request: Request) -> JSONResponse:
        return await _mutate(
            activation_id,
            "approve",
            request,
            lambda payload: _service().approve(
                activation_id,
                tx_hash=payload.get("tx_hash"),
                payment_id=payload.get("payment_id"),
            ),
        )

    @router.post("/api/activations/{activation_id}/pause", response_model=None)
    async def pause(activation_id: str, request: Request) -> JSONResponse:
        return await _mutate(
            activation_id,
            "pause",
            request,
            lambda payload: _service().pause(activation_id),
        )

    @router.post("/api/activations/{activation_id}/cancel", response_model=None)
    async def cancel(activation_id: str, request: Request) -> JSONResponse:
        return await _mutate(
            activation_id,
            "cancel",
            request,
            lambda payload: _service().cancel(activation_id),
        )

    @router.post("/api/activations/{activation_id}/revoke", response_model=None)
    async def revoke(activation_id: str, request: Request) -> JSONResponse:
        return await _mutate(
            activation_id,
            "revoke",
            request,
            lambda payload: _service().revoke(activation_id),
        )

    return router
