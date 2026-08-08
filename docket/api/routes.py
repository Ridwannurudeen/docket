"""Read-only handlers over one stored snapshot.

Nothing here writes, sweeps, or probes: a caller can hammer this API without
changing what Docket has observed. Every figure is drawn from `coverage_report`
so `/stats` and `/agents` can never disagree about what was measured, and every
response that carries a count carries the snapshot it was counted in.

Errors are `{"error": {"code", "message"}}` at every status. FastAPI's default
`{"detail": ...}` is registered away deliberately — an agent that has been told
one error shape should never receive two.

The hire routes are the one exception to "nothing here writes": they run work.
They still write nothing Docket has observed, and they are deliberately built so
a caller with no account, no key and no wallet gets real work back on the first
request — payment is additive, and a missing `DOCKET_PAY_TO` disables the priced
tier rather than the service.
"""

import os
import time
from dataclasses import asdict
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from ..advantage.harness import compare, load
from ..coverage import _PROBE_KINDS, _latest_observations, coverage_report
from ..hire.catalogue import SERVICES, get_service
from ..hire.receipts import build_receipt
from ..hire.x402 import build_challenge, parse_payment_header, verify_authorization
from ..signals import signals_for
from ..store import Store
from .models import (
    AgentDetail,
    AgentSummary,
    CatalogueResponse,
    Coverage,
    EndpointObservation,
    ListResponse,
    ServiceListing,
    StatsResponse,
)

DEFAULT_DB_PATH = "data/agents.sqlite3"
# Ships inside the package (see pyproject's package-data), so an installed Docket serves the
# same documents a checkout does.
STATIC_DIR = Path(__file__).parent / "static"
# The human pages and their assets. Ships in the package too, so an installed Docket serves the
# same web UI a checkout does. Everything here is authored as served: no build step, no bundler.
WEB_DIR = Path(__file__).parent / "web"
# The recorded experiments behind /advantage. Ships in the package too, so the report an
# installed Docket serves is the one committed to the repository.
EXPERIMENTS_DIR = Path(__file__).parent.parent / "advantage" / "experiments"
# Stated on /advantage.json, for the same reason PROBE_METHOD is stated on /stats: a
# timing whose method is unstated cannot be read, and this one is a ratio between two
# arms clocked differently per task.
ADVANTAGE_METHOD = (
    "Each task was run once by hiring an agent and once by hand. Elapsed seconds and "
    "out-of-pocket cost are reported separately and no hourly rate is applied to either, "
    "so no figure here depends on what someone's time is worth. No quality score is "
    "assigned to either arm: both outputs travel in full with the SHA-256 that binds "
    "them, and a reader grades them. `manual_steps` is what a reader repeats to contest "
    "a manual timing. One run each — every figure is a single observation, not a mean. "
    "Where an agent arm answered faster and returned less, or answered something other "
    "than the question asked, that is stated in the same experiment's `notes`."
)
# A time.monotonic() difference carries binary float residue: a run clocked at 43.063s is
# stored as 43.062999999994645. Publishing that verbatim asserts thirteen decimals nobody
# measured, so displayed timings are rounded to the millisecond. This rounds what is
# served, never what was observed — the experiment files keep the raw value, and a reader
# recomputing a ratio from them gets the same answer either way.
DISPLAYED_SECONDS_DP = 3
CHAIN_ID = 56
DEFAULT_LIMIT = 50
MAX_LIMIT = 100
# How much work one caller may take per hour. The allowance counts EVERY hire, not
# only the ones served without an authorization: hire/x402.py never remembers a
# nonce, so one valid signature verifies for ever, and an allowance that a payer
# stepped past would let a single replayed signature buy unlimited work. So the
# allowance is what bounds this service, and an authorization changes the receipt
# rather than the allowance — Docket does not settle, and a signature it cannot
# mark as spent must not buy work a free caller could not have had.
FREE_TIER_HIRES = 20
FREE_TIER_WINDOW_S = 3600
# Stated on every /stats response: a number about liveness is unreadable without it.
PROBE_METHOD = (
    "One GET per declared A2A or MCP endpoint, single attempt, 8s timeout, redirects not "
    "followed, every target vetted by an SSRF guard before any connection is opened. "
    "`responded` means a host answered at any status — not that the agent behind the URL "
    "does anything useful."
)
_STATUS_CODES = {404: "not_found", 405: "method_not_allowed"}


class MarkdownResponse(PlainTextResponse):
    media_type = "text/markdown"


def _published_seconds(value: float | None) -> float | None:
    """None-tolerant like `harness.compare`: an arm that was never timed has no timing to
    round, and inventing a 0.0 for it would be the same overclaim in the other direction."""
    return value if value is None else round(value, DISPLAYED_SECONDS_DP)


def _for_publication(experiment: dict) -> dict:
    """One experiment with its timings rounded for serving. Operates on the `asdict` copy,
    so the file on disk is untouched."""
    for arm in ("agent_arm", "manual_arm"):
        experiment[arm]["seconds"] = _published_seconds(experiment[arm]["seconds"])
    for field in ("seconds_agent", "seconds_manual"):
        experiment["deltas"][field] = _published_seconds(experiment["deltas"][field])
    return experiment


def _error(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code, content={"error": {"code": code, "message": message}}
    )


async def _http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    # Registered on Starlette's class, not FastAPI's subclass, so the router's own 404 on an
    # unknown path emits the contract shape too.
    if isinstance(exc.detail, dict):
        return _error(exc.status_code, exc.detail["code"], exc.detail["message"])
    code = _STATUS_CODES.get(exc.status_code, f"http_{exc.status_code}")
    return _error(exc.status_code, code, str(exc.detail))


async def _validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    first = exc.errors()[0]
    where = ".".join(str(part) for part in first["loc"][1:])
    return _error(422, "invalid_query_parameter", f"{where}: {first['msg']}")


def _coverage(report: dict, applied_filter: str | None = None) -> Coverage:
    return Coverage(
        snapshot_id=report["snapshot_id"],
        captured_at=report["captured_at"],
        sampled=report["sampled"],
        expected=report["expected"],
        dropped=report["dropped"],
        complete=report["complete"],
        filter=applied_filter,
    )


def _summary(agent: dict, signals: dict) -> AgentSummary:
    return AgentSummary(
        agent_id=agent["agent_id"],
        token_id=agent["token_id"],
        name=agent["name"],
        description=agent["description"],
        owner_address=agent["owner_address"],
        has_feedback=signals["has_feedback"],
        feedback_count=int(agent["total_feedbacks"]),
        declares_callable=signals["callable"],
        protocols=agent["supported_protocols"],
        x402=signals["x402"],
        publisher=signals["publisher"],
        placeholder_name=signals["placeholder_name"],
    )


def _responding_agent_ids(store: Store, snapshot_id: int) -> set[str]:
    return {
        obs["agent_id"]
        for obs in _latest_observations(store, snapshot_id)
        if obs["outcome"] == "responded"
    }


def create_app(db_path: str | Path = DEFAULT_DB_PATH, snapshot_id: int | None = None) -> FastAPI:
    """Serve one snapshot read-only. Resolved once here rather than per request: a listing and
    the stats beside it must describe the same capture, even mid-sweep."""
    db_path = Path(db_path)
    if snapshot_id is None:
        snapshot_id = Store(db_path).latest_snapshot_id(CHAIN_ID)
    # Read once, at startup: a missing document should fail the app that ships it, not the one
    # request that happened to ask for it.
    llms_body = (STATIC_DIR / "llms.txt").read_text(encoding="utf-8")
    skill_body = (STATIC_DIR / "SKILL.md").read_text(encoding="utf-8")
    # Same reasoning, and `load` raises on a file missing a field rather than defaulting
    # it: a half-read experiment served as a whole one is the failure this report can
    # least afford. Sorted so the three tasks arrive in the order they are numbered.
    experiments = [
        _for_publication({**asdict(exp), "deltas": compare(exp)})
        for exp in (load(path) for path in sorted(EXPERIMENTS_DIR.glob("*.json")))
    ]
    # Unset means no recipient exists to name in a challenge, so the priced tier is
    # off and the free tier serves unmetered. Read once here rather than per
    # request: the terms a caller is quoted must not change under it mid-session.
    pay_to = os.environ.get("DOCKET_PAY_TO") or None
    # Per app instance, so one process's allowances never outlive it. {ip: (window_start, used)}.
    hires: dict[str, tuple[float, int]] = {}

    app = FastAPI(
        title="Docket",
        version="0.1.0",
        description=(
            "Read-only observations about ERC-8004 agents registered on BSC. Docket reports "
            "what it measured and how much of the registry it covered. It does not rate, "
            "endorse, or vouch for any agent."
        ),
    )
    # GET only. `HEAD` was advertised here while no route served it, so a preflight promised a
    # method that 405s — the wrong inconsistency for a project whose claim is honest description.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["GET"],
        allow_credentials=False,
    )
    app.add_exception_handler(StarletteHTTPException, _http_error)
    app.add_exception_handler(RequestValidationError, _validation_error)

    def _serving() -> int:
        if snapshot_id is None:
            raise HTTPException(
                503,
                detail={
                    "code": "no_snapshot",
                    "message": (
                        f"No snapshot has been ingested into {db_path.name} yet. "
                        "Run the ingest sweep, then retry."
                    ),
                },
            )
        return snapshot_id

    def _spend_allowance(client_ip: str) -> int | None:
        """Take one hire from this IP's allowance. Returns None when it was there to take,
        or the seconds until the allowance resets when it was not.

        Keyed on the peer address only. `X-Forwarded-For` is caller-controlled, and reading
        it here would turn the allowance into a header anyone can rewrite.
        """
        if pay_to is None:
            return None
        now = time.monotonic()
        started, used = hires.get(client_ip, (now, 0))
        if now - started >= FREE_TIER_WINDOW_S:
            started, used = now, 0
        if used >= FREE_TIER_HIRES:
            hires[client_ip] = (started, used)
            return int(FREE_TIER_WINDOW_S - (now - started)) + 1
        hires[client_ip] = (started, used + 1)
        return None

    def _refund_allowance(client_ip: str) -> None:
        """Give back a hire that was debited and then never ran.

        The debit lands before the work rather than after, so that concurrent requests
        cannot all clear the check and start together — which is what makes a refund
        necessary rather than optional. A request Docket could not read returned the
        caller nothing, and an allowance charged for work that never ran is the same
        class of overclaim as reporting a settlement that never happened.
        """
        if client_ip not in hires:
            return
        started, used = hires[client_ip]
        hires[client_ip] = (started, max(used - 1, 0))

    @app.get("/")
    def root(request: Request):
        """One URL, two audiences. A browser says it wants HTML and gets the page; anything
        asking for JSON — or asking for nothing in particular — gets the service index
        unchanged, so the machine contract is untouched by the human one."""
        if "text/html" in request.headers.get("accept", ""):
            return FileResponse(WEB_DIR / "index.html")
        return {
            "service": "docket",
            "description": (
                "Read-only observations about ERC-8004 agents on BSC. Docket reports what it "
                "measured; a reader judges."
            ),
            "snapshot_id": snapshot_id,
            "llms_txt": "/llms.txt",
            "openapi": "/openapi.json",
            "stats": "/stats",
            "agents": "/agents",
            "hire": "/hire",
            "advantage": "/advantage.json",
            "health": "/health",
        }

    # Kept out of the schema: /llms.txt and the OpenAPI document describe the machine contract,
    # and a page a human reads is not an endpoint an agent should be told to call.
    @app.get("/browse", include_in_schema=False)
    def browse() -> FileResponse:
        return FileResponse(WEB_DIR / "browse.html")

    @app.get("/agent", include_in_schema=False)
    def agent_page() -> FileResponse:
        return FileResponse(WEB_DIR / "agent.html")

    @app.get("/advantage", include_in_schema=False)
    def advantage_page() -> FileResponse:
        """The report as a page. Unlike the rest of the web UI this one reads no live data:
        the experiments are a fixed record, so the page is the record rather than a shell
        that fetches it, and it says the same thing with scripting off."""
        return FileResponse(WEB_DIR / "advantage.html")

    @app.get("/health")
    def health() -> dict:
        return {
            "status": "ok" if snapshot_id is not None else "no_snapshot",
            "snapshot_id": snapshot_id,
        }

    @app.get("/llms.txt", response_class=PlainTextResponse)
    def llms_txt() -> str:
        """Orientation for a machine. Declared in the schema too: an agent told not to invent
        endpoints must be able to see that the documentation is itself one."""
        return llms_body

    @app.get("/skill.md", response_class=MarkdownResponse)
    def skill_md() -> str:
        return skill_body

    @app.get("/advantage.json")
    def advantage() -> dict:
        """The same three experiments the page at /advantage renders, as data.

        Two front doors over one record: an evaluator's agent reads the outputs, the
        hashes, the manual steps and the notes without a browser, and sees the same
        figures a human sees. `deltas` is the harness's own comparison — elapsed
        seconds, both costs, and the ratio between the timings. It carries no verdict,
        and neither does anything else here.
        """
        return {"method": ADVANTAGE_METHOD, "page": "/advantage", "experiments": experiments}

    @app.get("/stats", response_model=StatsResponse)
    def stats() -> StatsResponse:
        report = coverage_report(Store(db_path), _serving())
        return StatsResponse(
            coverage=_coverage(report),
            with_feedback=report["with_feedback"],
            callable_declared=report["callable"],
            endpoints_resolved=report["endpoints_resolved"],
            endpoints_probed=report["endpoints_probed"],
            endpoints_responded=report["endpoints_responded"],
            responded_pct_of_probed=report["responded_pct"],
            blocked_by_policy=report["blocked"],
            unresolved=report["unresolved"],
            distinct_publishers=report["distinct_publishers"],
            top_publishers=report["top_publishers"],
            probe_method=PROBE_METHOD,
        )

    @app.get("/agents", response_model=ListResponse)
    def list_agents(
        has_feedback: bool | None = None,
        declares_callable: bool | None = None,
        responded: bool | None = None,
        publisher: str | None = None,
        limit: int = DEFAULT_LIMIT,
        offset: int = 0,
    ) -> ListResponse:
        sid = _serving()
        limit = min(max(limit, 1), MAX_LIMIT)
        offset = max(offset, 0)
        store = Store(db_path)
        responders = _responding_agent_ids(store, sid) if responded is not None else set()

        matched: list[AgentSummary] = []
        for agent in store.iter_agents(sid):
            signals = signals_for(agent)
            if has_feedback is not None and signals["has_feedback"] != has_feedback:
                continue
            if declares_callable is not None and signals["callable"] != declares_callable:
                continue
            if publisher is not None and signals["publisher"] != publisher:
                continue
            if responded is not None and (agent["agent_id"] in responders) != responded:
                continue
            matched.append(_summary(agent, signals))

        applied = {
            "has_feedback": has_feedback,
            "declares_callable": declares_callable,
            "responded": responded,
            "publisher": publisher,
        }
        label = ", ".join(
            f"{key}={str(value).lower() if isinstance(value, bool) else value}"
            for key, value in applied.items()
            if value is not None
        )
        return ListResponse(
            items=matched[offset : offset + limit],
            total=len(matched),
            limit=limit,
            offset=offset,
            coverage=_coverage(coverage_report(store, sid), label or None),
        )

    @app.get("/agents/{agent_id:path}", response_model=AgentDetail)
    def get_agent(agent_id: str) -> AgentDetail:
        sid = _serving()
        store = Store(db_path)
        # Drained into a dict rather than short-circuited: a suspended iter_agents generator
        # holds its sqlite connection open for the rest of the request.
        agents = {row["agent_id"]: row for row in store.iter_agents(sid)}
        agent = agents.get(agent_id)
        if agent is None:
            raise HTTPException(
                404,
                detail={
                    "code": "agent_not_found",
                    "message": (
                        f"No agent {agent_id!r} in snapshot {sid}. "
                        "List the ids this snapshot holds at GET /agents."
                    ),
                },
            )

        kinds: dict[str, str] = {}
        for row in store.iter_endpoints(sid):
            if row["agent_id"] != agent_id:
                continue
            # One URL is often registered under several kinds. The probeable one wins: liveness
            # only ever probes a2a/mcp, so filing the observation beside it under `service`
            # would misstate why the request was made at all.
            if kinds.get(row["url"]) not in _PROBE_KINDS:
                kinds[row["url"]] = row["kind"]
        observations = [
            EndpointObservation(
                url=obs["url"],
                kind=kinds.get(obs["url"], "unknown"),
                observed_at=obs["observed_at"],
                outcome=obs["outcome"],
                status_code=obs["status_code"],
                elapsed_ms=obs["elapsed_ms"],
                detail=obs["detail"],
            )
            for obs in _latest_observations(store, sid)
            if obs["agent_id"] == agent_id
        ]
        return AgentDetail(
            **_summary(agent, signals_for(agent)).model_dump(),
            endpoints=sorted(kinds),
            observations=observations,
            coverage=_coverage(coverage_report(store, sid)),
        )

    @app.get("/hire", response_model=CatalogueResponse)
    def hire_catalogue() -> CatalogueResponse:
        """What Docket sells, in the order a caller needs it: what arrives, what to send,
        how long to wait, what it costs. Static — no snapshot, no store, no network."""
        return CatalogueResponse(
            services=[
                ServiceListing(
                    id=svc.id,
                    name=svc.name,
                    what_you_get=svc.what_you_get,
                    input_schema=svc.input_schema,
                    typical_seconds=svc.typical_seconds,
                    price_display=svc.price_display,
                    price_atomic=svc.price_atomic,
                    asset=svc.asset,
                )
                for svc in SERVICES.values()
            ]
        )

    @app.post("/hire/{service_id}", response_model=None)
    async def hire(service_id: str, request: Request) -> JSONResponse | dict:
        """Run one service and return the result bound to a receipt.

        Ordered so a caller learns what is wrong before anything is spent on its behalf:
        an unknown service and a malformed request cost no allowance, and the work runs
        only once the request is known to be servable.
        """
        service = get_service(service_id)
        if service is None:
            return _error(
                404,
                "service_not_found",
                f"No service {service_id!r}. GET /hire lists every service Docket offers.",
            )
        try:
            payload = await request.json()
        except ValueError:
            payload = None
        if not isinstance(payload, dict):
            return _error(
                400,
                "invalid_json",
                f'The body must be a JSON object, e.g. {{"wallet": "0x…"}}. '
                f"GET /hire carries {service.id}'s full input schema.",
            )
        missing = [
            name
            for name, field in service.input_schema.items()
            if field.get("required") and payload.get(name) is None
        ]
        if missing:
            return _error(
                422,
                "missing_field",
                f"{service.id} requires {', '.join(missing)}. "
                "GET /hire carries the full input schema.",
            )

        # Read before the allowance is spent so a rejected authorization can be named in
        # the 402 — a payer whose signature is wrong needs to know which field to fix.
        authorization = parse_payment_header(request.headers)
        verdict = None
        if authorization is not None and pay_to is not None:
            verdict = verify_authorization(
                authorization, expected_to=pay_to, expected_value=service.price_atomic
            )

        client_ip = request.client.host if request.client else "unknown"
        resets_in = _spend_allowance(client_ip)
        if resets_in is not None:
            message = (
                f"This caller has used its allowance of {FREE_TIER_HIRES} hires per hour; it "
                f"resets in {resets_in}s. Docket verifies payment authorizations and does not "
                "settle them, so signing the offer below does not raise the allowance."
            )
            if verdict is not None and not verdict[0]:
                message += f" The authorization presented was also not accepted: {verdict[1]}."
            return JSONResponse(
                status_code=402,
                content={
                    **build_challenge(service, pay_to, resource=str(request.url)),
                    "error": {"code": "free_tier_exhausted", "message": message},
                },
            )

        try:
            result = service.run(payload)
        # The wallet in the payload reaches an address parser and an RPC, so both a caller's
        # typo and an upstream outage surface here. Reported as the contract shape at a
        # status that says whose problem it is, never as an untyped 500 — and the two
        # statuses divide the allowance between them.
        #
        # A ValueError means the request itself could not be read, so the caller received
        # nothing and is charged nothing. Docket may already have fetched pool metadata
        # before reaching the address parser — measured at 1.6s on 2026-08-08 — but that
        # is Docket's own cost, not work done on this caller's behalf, and billing an
        # allowance for it would charge for work never performed.
        except ValueError as exc:
            _refund_allowance(client_ip)
            return _error(422, "invalid_field", f"{service.id} could not read that request: {exc}")
        # Everything else is the deliberate other side of that boundary: the request was
        # readable, the work was attempted on this caller's behalf, and upstream resources
        # were spent on it. That hire stays spent whether or not it finished.
        except Exception as exc:
            return _error(
                502,
                "service_failed",
                f"{service.id} could not complete: {type(exc).__name__}: {exc}",
            )

        if verdict is not None and verdict[0]:
            payment = {
                "status": "verified_unsettled",
                "asset": service.asset,
                "amount": str(service.price_atomic),
                "payer": str(authorization["message"]["from"]),
                "settlement": "not performed by Docket",
            }
        elif verdict is not None:
            payment = {"status": "free_tier", "authorization_rejected": verdict[1]}
        else:
            payment = {"status": "free_tier"}
        return {
            "result": result,
            "receipt": build_receipt(service.id, payload, result, payment=payment),
        }

    app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")
    return app
