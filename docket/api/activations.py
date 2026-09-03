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
from ..jobs.models import KINDS
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
from ..store import ACTIVATION_NONCE_TTL_SECONDS, MAX_ACTIVATION_PAGE

# One megabyte, the same ceiling `POST /hire/{service_id}` reads a body under. An
# activation body is a service request plus a policy; nothing legitimate approaches it.
MAX_BODY_BYTES = 1_048_576


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

    @router.get("/api/activations", response_model=None)
    async def list_activations(request: Request) -> JSONResponse:
        # Checksummed before it becomes a filter: an activation is stored under its
        # checksummed owner, and a wallet that hands back a lowercase address would
        # otherwise be told it owns nothing.
        owner = _checksum_or_none(request.query_params.get("owner"))
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

        message = create_message(service_id, str(payload["nonce"]))
        if not verify_owner_signature(owner, message, str(payload["owner_signature"])):
            return _error(
                401,
                "bad_signature",
                f"owner_signature did not recover to {owner} over {message!r}.",
            )
        if not await run_in_threadpool(
            store.consume_activation_nonce,
            str(payload["nonce"]),
            _checksum_or_none(owner) or owner,
        ):
            return _error(
                409,
                "stale_nonce",
                "That nonce was already spent or has expired. Ask "
                "/api/activations/nonce for another and sign the message it returns.",
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
        activation = await run_in_threadpool(store.get_activation, activation_id)
        if activation is None:
            return _error(
                404, "activation_not_found", f"No activation {activation_id!r}."
            )
        message = action_message(activation_id, action, nonce)
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
