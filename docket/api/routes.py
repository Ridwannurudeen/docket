"""Read-only handlers over one stored snapshot.

Nothing here writes, sweeps, or probes: a caller can hammer this API without
changing what Docket has observed. Every figure is drawn from `coverage_report`
so `/stats` and `/agents` can never disagree about what was measured, and every
response that carries a count carries the snapshot it was counted in.

Errors are `{"error": {"code", "message"}}` at every status. FastAPI's default
`{"detail": ...}` is registered away deliberately — an agent that has been told
one error shape should never receive two.
"""

from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from ..coverage import _PROBE_KINDS, _latest_observations, coverage_report
from ..signals import signals_for
from ..store import Store
from .models import (
    AgentDetail,
    AgentSummary,
    Coverage,
    EndpointObservation,
    ListResponse,
    StatsResponse,
)

DEFAULT_DB_PATH = "data/agents.sqlite3"
# Ships inside the package (see pyproject's package-data), so an installed Docket serves the
# same documents a checkout does.
STATIC_DIR = Path(__file__).parent / "static"
# The human pages and their assets. Ships in the package too, so an installed Docket serves the
# same web UI a checkout does. Everything here is authored as served: no build step, no bundler.
WEB_DIR = Path(__file__).parent / "web"
CHAIN_ID = 56
DEFAULT_LIMIT = 50
MAX_LIMIT = 100
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

    app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")
    return app
