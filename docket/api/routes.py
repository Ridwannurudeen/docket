"""Read-only handlers over one stored snapshot.

Nothing here writes, sweeps, or probes: a caller can hammer this API without
changing what Docket has observed. Every figure is drawn from `coverage_report`
so `/stats` and `/agents` can never disagree about what was measured, and every
response that carries a count carries the snapshot it was counted in.

Errors are `{"error": {"code", "message"}}` at every status. FastAPI's default
`{"detail": ...}` is registered away deliberately — an agent that has been told
one error shape should never receive two.

The hire routes are the exception to "nothing here writes": they run work and
persist payment state. Unadmitted services remain free previews/research/beta.
An admitted service settles only after a facilitator verifies the authorization
and Docket has durably bound a non-empty result to its input; missing owner
settlement configuration disables paid stock rather than preview access.
"""

import hmac
import os
import time
from dataclasses import asdict, replace
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    PlainTextResponse,
    RedirectResponse,
)
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from ..advantage.harness import compare, load
from ..advantage.v2.page import fill as fill_v2_page
from ..advantage.v2.report import report as advantage_v2_report
from ..advantage.v3.page import fill as fill_v3_page
from ..advantage.v3.report import report as advantage_v3_report
from ..coverage import _PROBE_KINDS, _latest_observations, coverage_report
from ..escrow import constants as escrow_constants
from ..escrow.chain import JobNotFound, JobReader
from ..escrow.flow import hire_calls
from ..hire.admission import CANARY_MAX_AGE_SECONDS, resolve_admission
from ..hire.catalogue import SERVICES, PaidStockAdmission, get_service
from ..hire.comparison import compare as compare_services_table
from ..hire.receipts import (
    build_receipt,
    canonical_hash,
    is_human_readable_result,
)
from ..hire.x402 import (
    Facilitator,
    FacilitatorClient,
    build_challenge,
    facilitator_envelope,
    parse_payment_header,
    verify_payment,
)
from ..marketplace.models import CATEGORIES, Category, ServiceRecord
from ..marketplace.registry import (
    CATEGORY_DECLARATION,
    EMPTY_CATEGORY,
    all_records,
    get_record,
    records_in,
)
from ..signals import signals_for
from ..store import Store
from .models import (
    AgentDetail,
    AgentSummary,
    CatalogueResponse,
    CategoryListing,
    CategoryResponse,
    Coverage,
    EndpointObservation,
    EvidenceLink,
    ListResponse,
    MetricFigure,
    ServiceCard,
    ServiceDetail,
    ServiceListing,
    ServicesResponse,
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
# Retired by the name_family rename, and refused by name rather than ignored. FastAPI drops
# query parameters it does not declare, so leaving this unhandled answers a caller who asked
# for one publisher's agents with the ENTIRE snapshot and `filter: null` — a narrower request
# served wider, with nothing in the body saying so. /llms.txt taught clients this parameter.
RETIRED_FILTER = "publisher"
DEFAULT_LIMIT = 50
MAX_LIMIT = 100
# How much admitted paid work one caller may preview before receiving a 402. A
# settled authorization bypasses this in-memory allowance because its nonce has a
# durable database state; unadmitted stock never shows a payment challenge.
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
# Stated on every /services response. Docket publishes no ranking, so the only orders
# available to it are the ones a reader can predict — and an order that reorders itself
# between requests would be read as one.
SERVICE_ORDERING = (
    "Ordered by service id, ascending. Docket ranks nothing: there is no relevance, "
    "quality or popularity order here, and there is no order a reader cannot reproduce."
)
# The three states of the cross-link from a service into the fact plane. Each says which
# case it is, because a missing link and an absent identity are different facts.
IDENTITY_UNBOUND = (
    "There is no agent record to cross-link to: no ERC-8004 identity has been registered "
    "for this service, on BSC or anywhere else."
)
IDENTITY_IN_SNAPSHOT = (
    "The snapshot Docket serves holds this agent. Its declared endpoints and every "
    "observation Docket made of them are at the agent path below."
)
IDENTITY_OUTSIDE_SNAPSHOT = (
    "The snapshot Docket serves does not hold this agent, so there is no /agents record to "
    "open for it here. Docket's default sweep covers the agents carrying at least one "
    "feedback record, which is a small slice of the registry — an identity outside that "
    "slice is registered on chain and is simply not in what Docket indexed."
)
IDENTITY_NO_SNAPSHOT = (
    "Docket is serving no completed snapshot just now, so it cannot say whether this agent "
    "is in one. The identity above is the binding; the index is what is missing."
)


class MarkdownResponse(PlainTextResponse):
    media_type = "text/markdown"


def _metric_figure(metric) -> MetricFigure:
    """`display` carries the denominator inside the string, so a card cannot render the
    numerator alone however it is templated."""
    return MetricFigure(
        name=metric.name,
        unit=metric.unit,
        window=metric.window,
        observed_at=metric.observed_at,
        method=metric.method,
        value=metric.value,
        numerator=metric.numerator,
        denominator=metric.denominator,
        display=metric.render(),
    )


def _category_job(category: Category | None) -> str | None:
    if category is None:
        return None
    return next(entry.job for entry in CATEGORIES if entry.category is category)


def _card(record: ServiceRecord, admission: PaidStockAdmission) -> ServiceCard:
    return ServiceCard(
        service_id=record.service_id,
        name=record.name,
        category=None if record.category is None else record.category.value,
        category_job=_category_job(record.category),
        what_you_get=record.what_you_get,
        price_display=record.price_display,
        price_atomic=record.price_atomic,
        asset=record.asset,
        paid_stock=admission.passes,
        stock_status=record.stock_status,
        admission=asdict(admission),
        typical_seconds=record.typical_seconds,
        activation=record.activation,
        activation_means=record.activation_means,
        metrics=[_metric_figure(metric) for metric in record.metrics],
        agent_id=record.agent_id,
        identity=record.identity_line,
        hire_method="POST",
        hire_path=f"/hire/{record.service_id}",
    )


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


def _jsonable(value):
    """Contract args carry bytes (`optParams`, `evidence`); JSON does not. Render them
    as hex so a caller can paste the value straight back into an encoder."""
    if isinstance(value, (bytes, bytearray)):
        return "0x" + value.hex()
    return value


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


async def _validation_error(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    first = exc.errors()[0]
    where = ".".join(str(part) for part in first["loc"][1:])
    return _error(422, "invalid_query_parameter", f"{where}: {first['msg']}")


def _snapshot_age_seconds(captured_at: str | None) -> int | None:
    if captured_at is None:
        return None
    try:
        captured = datetime.fromisoformat(captured_at.replace("Z", "+00:00"))
    except ValueError:
        return None
    if captured.tzinfo is None:
        return None
    age = (
        datetime.now(timezone.utc) - captured.astimezone(timezone.utc)
    ).total_seconds()
    return None if age < 0 else int(age)


def _coverage(report: dict, applied_filter: str | None = None) -> Coverage:
    return Coverage(
        snapshot_id=report["snapshot_id"],
        captured_at=report["captured_at"],
        snapshot_age_seconds=_snapshot_age_seconds(report["captured_at"]),
        sampled=report["sampled"],
        expected=report["expected"],
        dropped=report["dropped"],
        complete=report["complete"],
        population=report["population"],
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
        name_family=signals["name_family"],
        placeholder_name=signals["placeholder_name"],
    )


def _responding_agent_ids(store: Store, snapshot_id: int) -> set[str]:
    return {
        obs["agent_id"]
        for obs in _latest_observations(store, snapshot_id)
        if obs["outcome"] == "responded"
    }


def create_app(
    db_path: str | Path = DEFAULT_DB_PATH,
    snapshot_id: int | None = None,
    facilitator: Facilitator | None = None,
) -> FastAPI:
    """Serve one immutable observation snapshot plus persistent paid-hire state.

    The snapshot is resolved once so a listing and its stats describe the same capture,
    even mid-sweep. Hire writes are confined to payment lifecycle records.
    """
    db_path = Path(db_path)
    store = Store(db_path)
    if snapshot_id is None:
        # The newest COMPLETE sweep, never merely the newest row. An explicit snapshot_id is
        # still honoured, so an operator can inspect a partial capture on purpose.
        snapshot_id = store.latest_complete_snapshot_id(CHAIN_ID)
    served_snapshot = store.snapshot(snapshot_id) if snapshot_id is not None else {}
    snapshot_captured_at = served_snapshot.get("finished_at") or served_snapshot.get(
        "started_at"
    )
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
    # v2 is assembled once, here, and the page is rendered from the same payload the JSON route
    # returns — so a figure on one and a figure on the other cannot be two transcriptions. Built
    # at startup rather than per request for the reason the docs above are: what a reader is
    # served must not change under them between two requests to the same process.
    advantage_v2 = advantage_v2_report()
    advantage_v2_page = fill_v2_page(
        (WEB_DIR / "advantage-v2.html").read_text(encoding="utf-8"), advantage_v2
    )
    # V3 follows the same one-object boundary. Its state is reconstructed once from the durable
    # artifacts, then both representations stay pinned to that startup view until restart.
    advantage_v3 = advantage_v3_report()
    advantage_v3_page = fill_v3_page(
        (WEB_DIR / "advantage-v3.html").read_text(encoding="utf-8"), advantage_v3
    )
    # Unset means no recipient exists to name in a challenge, so the priced tier is
    # off and the free tier serves unmetered. Read once here rather than per
    # request: the terms a caller is quoted must not change under it mid-session.
    pay_to = os.environ.get("DOCKET_PAY_TO") or None
    if facilitator is None and os.environ.get("DOCKET_ENABLE_SETTLEMENT") == "1":
        facilitator_url = os.environ.get("DOCKET_FACILITATOR_URL")
        if not facilitator_url or not pay_to:
            raise RuntimeError(
                "DOCKET_ENABLE_SETTLEMENT=1 requires DOCKET_FACILITATOR_URL and DOCKET_PAY_TO"
            )
        facilitator = FacilitatorClient(facilitator_url)
    canary_token = None
    canary_token_file = os.environ.get("DOCKET_CANARY_TOKEN_FILE")
    canary_service_id = os.environ.get("DOCKET_CANARY_SERVICE_ID") or "range-doctor"
    if canary_token_file:
        canary_token = Path(canary_token_file).read_text(encoding="ascii").strip()
        if not canary_token:
            raise RuntimeError(
                "DOCKET_CANARY_TOKEN_FILE must contain a non-empty token"
            )
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
                        f"No complete snapshot has been ingested into {db_path.name} yet. "
                        "A sweep that has begun but not finished is not served. Run the "
                        "ingest sweep to completion, then retry."
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

    def _effective_admission(service_id: str) -> PaidStockAdmission:
        service = get_service(service_id)
        if service is None:
            raise KeyError(service_id)
        return resolve_admission(service, store.latest_canary_run(service_id))

    def _canary_authorized(request: Request, service_id: str) -> tuple[bool, bool]:
        supplied = request.headers.get("x-docket-canary")
        if supplied is None:
            return False, False
        if canary_token is None or service_id != canary_service_id:
            return True, False
        return True, hmac.compare_digest(
            supplied.encode("utf-8"), canary_token.encode("ascii")
        )

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
            "canary": "/canary",
            "openapi": "/openapi.json",
            "stats": "/stats",
            "agents": "/agents",
            "categories": "/categories",
            "services": "/services",
            "hire": "/hire",
            "escrow": "/escrow",
            "advantage": "/advantage.json",
            "advantage_v2": "/advantage/v2.json",
            "advantage_v3": "/advantage/v3.json",
            "health": "/health",
        }

    # Kept out of the schema: /llms.txt and the OpenAPI document describe the machine contract,
    # and a page a human reads is not an endpoint an agent should be told to call.
    @app.get("/research", include_in_schema=False)
    def research_page() -> FileResponse:
        """The raw registry browser. It moved from /browse when the home became the shop
        front: this is the fact plane, and it is now framed as the place to research the
        registry rather than as the site's own listing."""
        return FileResponse(WEB_DIR / "research.html")

    @app.get("/browse", include_in_schema=False)
    def browse(request: Request) -> RedirectResponse:
        """Moved, not removed. /browse was published, so it keeps landing on the page it
        named — permanently, and at one canonical URL rather than two that drift.

        The query travels with it. Every filter on that page lives in the query string, so
        a narrowed view is a link somebody sends; dropping it would answer a request for
        one slice with the whole snapshot and say nothing about having done so — the same
        defect as the retired `publisher` filter, and this status is permanent, so a
        browser would go on applying the broken mapping from its own cache.
        """
        query = request.url.query
        return RedirectResponse(
            f"/research?{query}" if query else "/research", status_code=308
        )

    @app.get("/agent", include_in_schema=False)
    def agent_page() -> FileResponse:
        return FileResponse(WEB_DIR / "agent.html")

    @app.get("/service", include_in_schema=False)
    def service_page() -> FileResponse:
        """One service: what it does, what it cannot do, the evidence behind it, and the
        control that runs it. The activation step the site did not have."""
        return FileResponse(WEB_DIR / "service.html")

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
            "snapshot_captured_at": snapshot_captured_at,
            "snapshot_age_seconds": _snapshot_age_seconds(snapshot_captured_at),
        }

    @app.get("/canary", response_model=None)
    def canary_history(service_id: str = "range-doctor", limit: int = 30) -> dict:
        service = get_service(service_id)
        if service is None:
            raise HTTPException(
                404,
                detail={
                    "code": "service_not_found",
                    "message": f"No service {service_id!r}. GET /hire lists every service.",
                },
            )
        try:
            history = list(store.iter_canary_runs(service_id, limit))
        except ValueError as exc:
            raise HTTPException(
                422,
                detail={"code": "invalid_query_parameter", "message": str(exc)},
            ) from exc
        admission = resolve_admission(service, history[0] if history else {})
        return {
            "service_id": service_id,
            "admission_max_age_seconds": CANARY_MAX_AGE_SECONDS,
            "latest": history[0] if history else None,
            "history": history,
            "admission": asdict(admission),
            "paid_stock": admission.passes,
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
        return {
            "method": ADVANTAGE_METHOD,
            "page": "/advantage",
            "experiments": experiments,
        }

    @app.get("/advantage/v2.json")
    def advantage_v2_json() -> dict:
        """The second report: hashed experiments with registration provenance stated per
        experiment, every run behind them, and each registered falsifier evaluated against
        what was measured. Git establishes 04's specification-before-run ordering; 01 and 03
        are self-attested because each specification and completed run first entered git
        together.

        Additive. `/advantage.json` above is untouched and stays the prior version rather
        than a superseded one, and this document links back to it in `prior_version`. What
        is new here is the shape rather than the subject: a hashed specification cited by its
        run, null baselines computed and served beside every agent figure, every trial
        including the ones that failed, and — the thing nothing served until now — the
        result of each falsifier, computed. One of the three claims is refuted, and `summary`
        says which before the experiments begin.
        """
        return advantage_v2

    @app.get("/advantage/v2", include_in_schema=False)
    def advantage_v2_page_route() -> HTMLResponse:
        """The v2 report as a page, rendered from the payload above rather than authored
        beside it. Reads no live data and needs no scripting, as v1's page does not."""
        return HTMLResponse(advantage_v2_page)

    @app.get("/advantage/v3.json")
    def advantage_v3_json() -> dict:
        """The paired v3 evaluation reconstructed from its registered specifications and
        whatever durable input, ledger, model-seat and mapping artifacts exist at startup.

        Its state vocabulary is closed: registered_waiting_for_inputs, locked_not_run,
        running, complete_unscored, refuted and not_refuted. The two terminal claim states
        remain bounded to the registered falsifier and frozen inputs.
        """
        return advantage_v3

    @app.get("/advantage/v3", include_in_schema=False)
    def advantage_v3_page_route() -> HTMLResponse:
        """The v3 page rendered from the exact object returned by the JSON route."""
        return HTMLResponse(advantage_v3_page)

    @app.get("/stats", response_model=StatsResponse)
    def stats() -> StatsResponse:
        report = coverage_report(Store(db_path), _serving())
        return StatsResponse(
            coverage=_coverage(report),
            registry_total=report["registry_total"],
            with_feedback=report["with_feedback"],
            callable_declared=report["callable"],
            endpoints_resolved=report["endpoints_resolved"],
            endpoints_evaluated=report["endpoints_evaluated"],
            endpoints_attempted=report["endpoints_attempted"],
            endpoints_responded=report["endpoints_responded"],
            responded_pct_of_attempted=report["responded_pct_of_attempted"],
            responded_pct_of_evaluated=report["responded_pct_of_evaluated"],
            blocked_by_policy=report["blocked"],
            unresolved=report["unresolved"],
            distinct_name_families=report["distinct_name_families"],
            top_name_families=report["top_name_families"],
            probe_method=PROBE_METHOD,
        )

    @app.get("/agents", response_model=ListResponse)
    def list_agents(
        request: Request,
        has_feedback: bool | None = None,
        declares_callable: bool | None = None,
        responded: bool | None = None,
        name_family: str | None = None,
        limit: int = DEFAULT_LIMIT,
        offset: int = 0,
    ) -> ListResponse:
        # Before _serving(), so a caller learns their request is malformed whatever state the
        # store is in — and refused even when the filter would have matched nothing, or a
        # client learns the wrong name from a request that happened to look fine.
        if RETIRED_FILTER in request.query_params:
            raise HTTPException(
                422,
                detail={
                    "code": "invalid_query_parameter",
                    "message": (
                        f"{RETIRED_FILTER}: no such filter. It was renamed to name_family, "
                        "which groups agents by the first token of a self-declared name and "
                        "never carried minter provenance. Send name_family instead — this "
                        "request is refused rather than answered with the whole snapshot."
                    ),
                },
            )
        sid = _serving()
        limit = min(max(limit, 1), MAX_LIMIT)
        offset = max(offset, 0)
        store = Store(db_path)
        responders = (
            _responding_agent_ids(store, sid) if responded is not None else set()
        )

        matched: list[AgentSummary] = []
        for agent in store.iter_agents(sid):
            signals = signals_for(agent)
            if has_feedback is not None and signals["has_feedback"] != has_feedback:
                continue
            if (
                declares_callable is not None
                and signals["callable"] != declares_callable
            ):
                continue
            if name_family is not None and signals["name_family"] != name_family:
                continue
            if responded is not None and (agent["agent_id"] in responders) != responded:
                continue
            matched.append(_summary(agent, signals))

        applied = {
            "has_feedback": has_feedback,
            "declares_callable": declares_callable,
            "responded": responded,
            "name_family": name_family,
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
            associated_services=[
                _card(record, _effective_admission(record.service_id))
                for record in all_records()
                if record.agent_id is not None
                and record.agent_id.lower() == agent["agent_id"].lower()
            ],
        )

    def _identity_link(record: ServiceRecord) -> tuple[str | None, str]:
        """Where this service's bound identity can be inspected, and why it cannot be when
        it cannot. Deliberately not routed through `_serving()`: the marketplace does not
        depend on a snapshot, and a service should not 503 because no sweep has landed."""
        if record.agent_id is None:
            return None, IDENTITY_UNBOUND
        if snapshot_id is None:
            return None, IDENTITY_NO_SNAPSHOT
        # Drained into a dict rather than short-circuited with any(): a suspended
        # iter_agents generator holds its sqlite connection open for the whole request.
        #
        # Keyed on the lowercased id, and the STORED id is what gets linked. An agent_id
        # carries an address, and an address that differs only in case is the same
        # address — every one of the 104,006 rows on this database is lowercase, but that
        # is 8004scan's formatting rather than a guarantee, and matching case-sensitively
        # would answer "not in the served snapshot" about an agent that is in it.
        held = {
            row["agent_id"].lower(): row["agent_id"]
            for row in Store(db_path).iter_agents(snapshot_id)
        }
        stored = held.get(record.agent_id.lower())
        if stored is not None:
            return f"/agents/{stored}", IDENTITY_IN_SNAPSHOT
        return None, IDENTITY_OUTSIDE_SNAPSHOT

    @app.get("/categories", response_model=CategoryResponse)
    def categories() -> CategoryResponse:
        """BNB's four jobs, each with what it gets done and how many services stand in it.

        A zero here is the honest answer and not a gap being papered over: Docket lists a
        service where it runs the work and can show a recorded run behind it, and it will
        not stock a shelf with registry agents whose job nothing on chain states.
        """
        listings = []
        for entry in CATEGORIES:
            stocked = records_in(entry.category)
            listings.append(
                CategoryListing(
                    category=entry.category.value,
                    job=entry.job,
                    does=entry.does,
                    service_count=len(stocked),
                    empty=None if stocked else EMPTY_CATEGORY,
                    services_path=f"/services?category={entry.category.value}",
                )
            )
        return CategoryResponse(categories=listings, declaration=CATEGORY_DECLARATION)

    @app.get("/services", response_model=ServicesResponse)
    def list_services(category: Category | None = None) -> ServicesResponse:
        """The services Docket runs, optionally narrowed to one job.

        `category` is typed as the closed set, so anything else is refused with 422
        invalid_query_parameter naming the four permitted values rather than answered with
        the whole catalogue. Services outside those four are listed with a null category:
        filing one under a job it does not do would be the fabrication this layer exists
        to avoid.
        """
        records = all_records() if category is None else records_in(category)
        return ServicesResponse(
            services=[
                _card(record, _effective_admission(record.service_id))
                for record in records
            ],
            total=len(records),
            category=None if category is None else category.value,
            ordering=SERVICE_ORDERING,
            declaration=CATEGORY_DECLARATION,
        )

    @app.get("/services/{service_id}", response_model=ServiceDetail)
    def get_service_detail(service_id: str) -> ServiceDetail:
        """One service in full: what arrives, what to send, what it costs, what has been
        observed of it, what it cannot do, and where its identity can be read."""
        record = get_record(service_id)
        if record is None:
            raise HTTPException(
                404,
                detail={
                    "code": "service_not_found",
                    "message": (
                        f"No service {service_id!r} in Docket's marketplace. GET /services "
                        "lists every service it runs; GET /categories lists the four jobs."
                    ),
                },
            )
        agent_path, identity_note = _identity_link(record)
        return ServiceDetail(
            **_card(record, _effective_admission(record.service_id)).model_dump(),
            registration_uri=record.registration_uri,
            input_schema=record.input_schema,
            limitations=record.limitations,
            evidence=[
                EvidenceLink(kind=ref.kind, url=ref.url, label=ref.label)
                for ref in record.evidence
            ],
            agent_path=agent_path,
            identity_note=identity_note,
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
                    paid_stock=(admission := _effective_admission(svc.id)).passes,
                    stock_status=svc.stock_status,
                    admission=asdict(admission),
                )
                for svc in SERVICES.values()
            ]
        )

    @app.get("/compare", response_model=None)
    def compare_services() -> dict:
        """Every service side by side, including the ones with nothing to show.

        `/hire` says what each service does and what it costs, which leaves a buyer to work
        out for themselves which have ever been run against a human. Three have and three
        have not, and a table where those look the same is worse than no table. Live
        admission is read the same way `/hire` reads it, so the two cannot disagree about
        which services are actually for sale.
        """
        table = compare_services_table(
            [
                replace(svc, admission=_effective_admission(svc.id))
                for svc in SERVICES.values()
            ]
        )
        table["admission_max_age_seconds"] = CANARY_MAX_AGE_SECONDS
        return table

    @app.get("/escrow", response_model=None)
    def escrow_terms() -> dict:
        """The second hire rail: funds held in escrow for a real job, rather than paid
        per call. Static — the addresses and the window are read from chain once and
        written down, not fetched per request.

        Docket publishes the sequence; the buyer signs it. Nothing here asks for a key.
        """
        c = escrow_constants
        sequence = hire_calls(
            provider="0x0000000000000000000000000000000000000000",
            budget_atomic=10**16,
            expires_in_s=7 * 86400,
            description="<your job description>",
        )
        return {
            "rail": "erc-8183-escrow",
            "chain_id": c.CHAIN_ID,
            "what_this_is": (
                "An on-chain escrow hire. You fund a job, the provider delivers, and the "
                "budget moves to them once a dispute window closes. Use /hire instead if "
                "you want a single call answered now and paid for now."
            ),
            "contracts": {
                "commerce": c.COMMERCE,
                "router": c.ROUTER,
                "policy": c.POLICY,
            },
            "payment_token": {
                "address": c.PAYMENT_TOKEN,
                "symbol": c.PAYMENT_TOKEN_SYMBOL,
                "decimals": c.PAYMENT_TOKEN_DECIMALS,
                "note": "You also need BNB for gas. The kernel takes no platform fee today.",
            },
            "dispute_window_seconds": c.DISPUTE_WINDOW_S,
            "dispute_window_plain": (
                "7 days. There is no early-accept path in this policy, so a funded job "
                "cannot be settled sooner however willing both sides are. Budget for it "
                "before you fund, not after."
            ),
            "hire_sequence": [
                {
                    "step": s["step"],
                    "to": s["to"],
                    "function": s["function"],
                    "args": {k: _jsonable(v) for k, v in s["args"].items()},
                    "needs": s["needs"],
                    "note": s["note"],
                }
                for s in sequence
            ],
            "sequence_note": (
                "This is a template, not signable bytes: each step gives the target, the "
                "function and the argument shape, with your own values to fill in. Nothing "
                "here is pre-encoded, because two of the arguments cannot be known from a "
                "template — the job id does not exist until createJob lands (those steps "
                "carry needs: ['job_id']), and expiredAt depends on when you send it. "
                "Encode against the target contract's own ABI once you have both."
            ),
            "buyer_lever": {
                "function": "dispute(uint256 jobId)",
                "to": c.POLICY,
                "note": (
                    "Your one lever during the window, and it is client-only. A disputed "
                    "job goes to the policy's voters "
                    f"({c.VOTE_QUORUM} of {c.ACTIVE_VOTERS} to reject)."
                ),
            },
            "settlement": {
                "function": "settle(uint256 jobId, bytes evidence)",
                "to": c.ROUTER,
                "permissionless": True,
                "note": (
                    "Anyone may call this once the window has elapsed and the job is "
                    "undisputed, so Docket closes jobs it brokered without the buyer "
                    "coming back. Check any job with GET /escrow/job/{job_id}."
                ),
            },
            "docket_does_not": [
                "ask for, hold, or proxy your private key",
                "take custody of escrowed funds at any point",
                "sign anything on your behalf",
                "have any way to shorten or waive the dispute window",
            ],
            "verified_on": c.VERIFIED_ON,
            "evidence": c.EVIDENCE,
        }

    @app.get("/escrow/job/{job_id}", response_model=None)
    def escrow_job(job_id: int) -> JSONResponse | dict:
        """One job's live state, read from chain at request time."""
        try:
            return JobReader().job_state(job_id)
        except JobNotFound:
            return _error(
                404,
                "job_not_found",
                f"No ERC-8183 job {job_id} on chain {escrow_constants.CHAIN_ID}. "
                "GET /escrow carries the addresses and the sequence that creates one.",
            )
        except Exception:
            # An unreachable node is not an absent job. Reporting it as 404 would tell a
            # caller their job does not exist, which is a different and worse untruth.
            return _error(
                502,
                "chain_unreachable",
                f"Could not read chain {escrow_constants.CHAIN_ID} just now. The job may "
                "well exist; Docket could not reach a node to check. Retry.",
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
        payment_header_present = any(
            request.headers.get(name) for name in ("x-payment", "payment-signature")
        )
        canary_header_present, canary_authorized = _canary_authorized(
            request, service.id
        )
        if canary_header_present and not canary_authorized:
            return _error(
                403,
                "canary_unauthorized",
                "The canary credential was not accepted. No work ran and no charge was attempted.",
            )
        payment_payload = parse_payment_header(request.headers)
        input_hash = canonical_hash(payload)
        resource_url = str(request.url)
        paid_stock = _effective_admission(service.id).passes

        if payment_header_present and (paid_stock or canary_authorized):
            if pay_to is None or facilitator is None:
                return _error(
                    503,
                    "settlement_unavailable",
                    "This service passed its admission gate, but live settlement is not "
                    "owner-enabled on this process. No work ran and no charge was attempted.",
                )
            challenge = build_challenge(service, pay_to, resource=resource_url)
            if payment_payload is None:
                return JSONResponse(
                    status_code=402,
                    content={
                        **challenge,
                        "error": {
                            "code": "payment_invalid",
                            "message": (
                                "The payment header is not a base64-encoded JSON "
                                "PaymentPayload. No work ran and no charge was attempted."
                            ),
                        },
                    },
                )
            requirements = challenge["accepts"][0]
            verified, reason = verify_payment(
                payment_payload,
                expected_requirements=requirements,
                expected_resource=challenge["resource"],
            )
            if verified is None:
                return JSONResponse(
                    status_code=402,
                    content={
                        **challenge,
                        "error": {
                            "code": "payment_invalid",
                            "message": f"The payment was not accepted: {reason}.",
                        },
                    },
                )

            existing = store.payment_by_nonce(verified.nonce)
            if existing:
                same_binding = (
                    existing["payment_id"] == verified.payment_id
                    and existing["service_id"] == service.id
                    and existing["input_hash"] == input_hash
                    and existing["recipient"].lower() == pay_to.lower()
                    and existing["asset"].lower() == service.asset.lower()
                    and existing["amount"] == str(service.price_atomic)
                    and existing["resource"] == resource_url
                )
                if not same_binding:
                    return _error(
                        409,
                        "authorization_replay",
                        "That authorization nonce is already bound to different work.",
                    )
                if existing["status"] == "settled":
                    return _error(
                        409,
                        "authorization_replay",
                        "That authorization already settled and cannot be replayed.",
                    )
                if existing["status"] == "settlement_unknown":
                    return _error(
                        409,
                        "settlement_pending_reconciliation",
                        "A settlement call was already attempted and its outcome is unknown. "
                        "Docket will not retry it automatically.",
                    )
                if existing["status"] in {"failed_no_charge", "settlement_failed"}:
                    return _error(
                        409,
                        "authorization_spent",
                        "That authorization already reached a terminal no-replay state.",
                    )
                return _error(
                    409,
                    "payment_in_progress",
                    "That authorization is already reserved or settling.",
                )

            envelope = facilitator_envelope(payment_payload, requirements)
            try:
                verification = facilitator.verify(envelope)
            except Exception as exc:
                return _error(
                    502,
                    "payment_verification_unavailable",
                    f"The configured facilitator could not verify the payment: "
                    f"{type(exc).__name__}: {exc}. No work ran and no charge was attempted.",
                )
            if (
                verification.get("isValid") is not True
                or str(verification.get("payer", "")).lower() != verified.payer.lower()
            ):
                invalid_reason = verification.get("invalidReason") or (
                    "payer or validity mismatch"
                )
                return JSONResponse(
                    status_code=402,
                    content={
                        **challenge,
                        "error": {
                            "code": "payment_not_verified",
                            "message": (
                                f"The facilitator rejected the payment: {invalid_reason}."
                            ),
                        },
                    },
                )

            reserved, existing = store.reserve_payment(
                nonce=verified.nonce,
                payment_id=verified.payment_id,
                service_id=service.id,
                payer=verified.payer,
                recipient=pay_to,
                asset=service.asset,
                amount=str(service.price_atomic),
                resource=resource_url,
                input_hash=input_hash,
            )
            if not reserved:
                return _error(
                    409,
                    (
                        "payment_in_progress"
                        if existing.get("payment_id") == verified.payment_id
                        else "authorization_replay"
                    ),
                    "Another request reserved that authorization before this one.",
                )

            try:
                result = service.run(payload)
            except ValueError as exc:
                store.fail_payment(
                    verified.payment_id, status="failed_no_charge", error=str(exc)
                )
                return _error(
                    422,
                    "invalid_field",
                    f"{service.id} could not read that request: {exc}. No settlement ran.",
                )
            except Exception as exc:
                store.fail_payment(
                    verified.payment_id,
                    status="failed_no_charge",
                    error=f"{type(exc).__name__}: {exc}",
                )
                return _error(
                    502,
                    "service_failed",
                    f"{service.id} could not complete: {type(exc).__name__}: {exc}. "
                    "No settlement ran.",
                )

            if not is_human_readable_result(result):
                store.fail_payment(
                    verified.payment_id,
                    status="failed_no_charge",
                    error="empty or non-readable result",
                )
                return _error(
                    502,
                    "empty_result",
                    "The service produced no non-empty human-readable result. No settlement ran.",
                )

            output_hash = canonical_hash(result)
            store.record_payment_output(
                verified.payment_id, output_hash=output_hash, result=result
            )
            if not canary_authorized and not _effective_admission(service.id).passes:
                store.fail_payment(
                    verified.payment_id,
                    status="failed_no_charge",
                    error="paid admission closed before settlement",
                )
                return _error(
                    503,
                    "service_de_admitted",
                    "The service left paid admission before settlement. The result was not "
                    "delivered and no settlement ran.",
                )
            if not store.begin_payment_settlement(verified.payment_id):
                return _error(
                    409,
                    "payment_in_progress",
                    "The authorization did not enter settlement from its bound output state.",
                )
            try:
                settlement = facilitator.settle(envelope)
            except Exception as exc:
                store.fail_payment(
                    verified.payment_id,
                    status="settlement_unknown",
                    error=f"{type(exc).__name__}: {exc}",
                )
                return _error(
                    502,
                    "settlement_unknown",
                    "The one settlement call returned no usable response. Its outcome may be "
                    "unknown, so Docket recorded it and will not retry automatically.",
                )

            if settlement.get("success") is not True:
                settlement_error = str(
                    settlement.get("errorReason") or "facilitator refused settlement"
                )
                store.fail_payment(
                    verified.payment_id,
                    status="settlement_failed",
                    error=settlement_error,
                )
                return _error(
                    502,
                    "settlement_failed",
                    f"The facilitator did not settle this authorization: {settlement_error}.",
                )

            transaction_id = str(settlement.get("transaction") or "")
            network = str(settlement.get("network") or "")
            settlement_payer = str(settlement.get("payer") or "")
            if (
                not transaction_id
                or network != requirements["network"]
                or settlement_payer.lower() != verified.payer.lower()
            ):
                store.fail_payment(
                    verified.payment_id,
                    status="settlement_unknown",
                    error="successful response omitted or contradicted transaction binding",
                )
                return _error(
                    502,
                    "settlement_unknown",
                    "The facilitator reported success without the expected payer, network and "
                    "transaction binding. Docket will not retry automatically.",
                )

            payment = {
                "status": "settled",
                "asset": service.asset,
                "amount": str(service.price_atomic),
                "payer": verified.payer,
                "recipient": pay_to,
                "nonce": verified.nonce,
                "payment_id": verified.payment_id,
                "transaction_id": transaction_id,
                "network": network,
                "evidence": "configured facilitator x402 v2 settlement response",
            }
            receipt = build_receipt(service.id, payload, result, payment=payment)
            store.finish_payment(
                verified.payment_id,
                transaction_id=transaction_id,
                network=network,
                receipt=receipt,
            )
            return {"result": result, "receipt": receipt}

        client_ip = request.client.host if request.client else "unknown"
        payment_available = (
            paid_stock and pay_to is not None and facilitator is not None
        )
        resets_in = _spend_allowance(client_ip) if payment_available else None
        if resets_in is not None:
            return JSONResponse(
                status_code=402,
                content={
                    **build_challenge(service, pay_to, resource=resource_url),
                    "error": {
                        "code": "free_tier_exhausted",
                        "message": (
                            f"This caller has used its allowance of {FREE_TIER_HIRES} hires "
                            f"per hour; it resets in {resets_in}s. Present the exact x402 "
                            "authorization above to request a settled personalized result."
                        ),
                    },
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
            if payment_available:
                _refund_allowance(client_ip)
            return _error(
                422, "invalid_field", f"{service.id} could not read that request: {exc}"
            )
        # Everything else is the deliberate other side of that boundary: the request was
        # readable, the work was attempted on this caller's behalf, and upstream resources
        # were spent on it. That hire stays spent whether or not it finished.
        except Exception as exc:
            return _error(
                502,
                "service_failed",
                f"{service.id} could not complete: {type(exc).__name__}: {exc}",
            )

        payment = (
            {
                "status": "not_for_sale",
                "stock_status": service.stock_status,
                "authorization_used": False,
            }
            if payment_header_present and not paid_stock
            else {"status": "free_tier"}
        )
        return {
            "result": result,
            "receipt": build_receipt(service.id, payload, result, payment=payment),
        }

    app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")
    return app
