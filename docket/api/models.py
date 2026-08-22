"""The response contract an evaluator's agent parses.

Docket publishes observations, never judgements. `BANNED_FIELD_NAMES` is the list
of words that would turn an observation into a verdict, and a contract test
asserts no model here uses one — the field names are the promise, so they are
enforced rather than reviewed.

Every response carrying a count also carries `Coverage`, so no figure can be
quoted without the snapshot and sample size it came from.
"""

from typing import Literal

import pydantic

# A reader judges; Docket does not. Names that would claim otherwise are refused at the model.
BANNED_FIELD_NAMES = frozenset(
    {
        # The word a shop front reaches for first, and the one Docket has least standing
        # to use: it ranks nothing, so it cannot know which anything is. Banned as a field
        # name and, through the scans that iterate this set, as a value.
        "best",
        "safe",
        "trusted",
        "verified",
        "verified_by_docket",
        "recommended",
        "rank",
        "trust_score",
        "score",
        "rating",
        "endorsed",
        "certified",
    }
)


class Coverage(pydantic.BaseModel):
    """What population a figure was drawn from. Required, never defaulted: a count whose
    coverage was optional would eventually be published without it."""

    snapshot_id: int
    captured_at: str | None
    # Computed by the server from the exact snapshot this process is serving. A caller should
    # not have to infer operational freshness from its own clock and a timestamp.
    snapshot_age_seconds: int | None
    sampled: int
    expected: int
    dropped: int
    complete: bool
    # Which query the SNAPSHOT was swept from: "all", or the predicate that narrowed it, e.g.
    # "min_feedbacks>=1". Null where the sweep predated this field and never recorded one.
    # Required, never defaulted, and never inferred: `complete` is measured against `expected`,
    # which is a total for this query alone, so without it 506 of 506 reads as a whole-registry
    # census. `filter` below is the other question — which subset of the snapshot is in THIS
    # response — and the two are not interchangeable.
    population: str | None
    # What subset of the snapshot this response describes, e.g. "has_feedback=true".
    filter: str | None = None


class AgentSummary(pydantic.BaseModel):
    agent_id: str
    token_id: str
    name: str | None
    description: str | None
    owner_address: str | None
    has_feedback: bool
    feedback_count: int
    declares_callable: bool
    protocols: list[str]
    x402: bool
    # The first token of the name this agent declared, or "owner:0x..." where the registry
    # generated the name. A grouping heuristic over a self-declared string, NOT verified
    # minter provenance — see `signals.name_family`.
    name_family: str
    placeholder_name: bool


class EndpointObservation(pydantic.BaseModel):
    """One probe of one URL. `responded` means a host answered at any status — it is not
    evidence that the agent behind the URL does anything useful."""

    url: str
    kind: str
    observed_at: str | None
    outcome: str | None
    status_code: int | None
    elapsed_ms: int | None
    detail: str | None


class ListResponse(pydantic.BaseModel):
    items: list[AgentSummary]
    total: int
    limit: int
    offset: int
    coverage: Coverage


class RefreshStatus(pydantic.BaseModel):
    status: Literal["ok", "refused", "error"]
    timestamp: str


class StatsResponse(pydantic.BaseModel):
    coverage: Coverage
    refresh_status: RefreshStatus | None
    # A LOWER BOUND on the chain's size — the largest total any sweep recorded — and the scale
    # `coverage.complete` is silent about, since a snapshot swept from a filtered query is
    # complete the moment it reaches the end of that query. Read it as "at least this many were
    # registered when some sweep last measured": where every sweep on record was filtered this
    # is a filtered total and the chain is larger, and it may equal the served snapshot's own
    # `expected`. Null where no sweep has recorded a total at all.
    registry_total: int | None
    with_feedback: int
    callable_declared: int
    endpoints_resolved: int
    # `evaluated` is every endpoint liveness considered; `attempted` is the subset an HTTP
    # request was actually issued to — issued, not arrived: a timeout is attempted and
    # nothing was reached. A blocked or unresolved target is evaluated and never attempted.
    endpoints_evaluated: int
    endpoints_attempted: int
    endpoints_responded: int
    # Both rates, each named for its own denominator, so neither can be requoted against a
    # population it was not divided by.
    responded_pct_of_attempted: float
    responded_pct_of_evaluated: float
    blocked_by_policy: int
    unresolved: int
    distinct_name_families: int
    top_name_families: list[dict]
    probe_method: str


class ServiceListing(pydantic.BaseModel):
    """One hireable service as `GET /hire` publishes it. Everything a caller needs to build a
    request without asking anyone: what arrives, what to send, how long to wait, what it costs."""

    id: str
    name: str
    what_you_get: str
    input_schema: dict
    typical_seconds: int
    price_display: str
    price_atomic: int
    asset: str
    paid_stock: bool
    stock_status: str
    admission: dict[str, bool]


class CatalogueResponse(pydantic.BaseModel):
    services: list[ServiceListing]


class MetricFigure(pydantic.BaseModel):
    """One observed figure about a service, with everything needed to read it.

    `numerator` and `denominator` travel together or not at all, and a share cannot be
    built without them — enforced in `marketplace.models.Metric`, which is what builds
    these. `display` is the same figure as text with its denominator inside the string,
    so a card cannot render a rate stripped of its base.
    """

    name: str
    unit: str
    window: str
    observed_at: str
    method: str
    value: float | None
    numerator: int | None
    denominator: int | None
    display: str


class EvidenceLink(pydantic.BaseModel):
    """A pointer at something this origin already serves, so the claim behind a service
    can be opened and checked here rather than taken on trust."""

    kind: str
    url: str
    label: str


class ServiceCard(pydantic.BaseModel):
    """One service as a marketplace listing shows it: the job, the offer, and the way to
    run it. `category` is Docket's own declaration about a service Docket runs, never a
    property measured on an agent — the response that carries these says so."""

    service_id: str
    name: str
    category: str | None
    category_job: str | None
    what_you_get: str
    price_display: str
    price_atomic: int
    asset: str
    paid_stock: bool
    stock_status: str
    admission: dict[str, bool]
    typical_seconds: int
    activation: str
    activation_means: str
    metrics: list[MetricFigure]
    agent_id: str | None
    identity: str
    hire_method: str
    hire_path: str


class AgentDetail(AgentSummary):
    """Registry facts plus Docket services explicitly bound to this identity.

    `associated_services` is Docket's marketplace overlay, not something inferred from
    the agent's registration. It is required so a missing join cannot look like an empty one.
    """

    endpoints: list[str]
    observations: list[EndpointObservation]
    coverage: Coverage
    associated_services: list[ServiceCard]


class ServiceDetail(ServiceCard):
    """Everything a caller needs to activate one service, plus what it cannot do.

    `agent_path` is the cross-link into the fact plane, and it is null unless the bound
    identity is actually in the snapshot being served — a link that 404s is a dead end,
    and `identity_note` says which case this is.
    """

    registration_uri: str | None
    input_schema: dict
    limitations: str
    evidence: list[EvidenceLink]
    agent_path: str | None
    identity_note: str


class ServicesResponse(pydantic.BaseModel):
    services: list[ServiceCard]
    total: int
    category: str | None
    ordering: str
    declaration: str


class CategoryListing(pydantic.BaseModel):
    """One job category. `empty` is prose where nothing stands in it yet and null where
    something does: a count of zero is a fact, and the reason for it is the part a
    reader actually needs."""

    category: str
    job: str
    does: str
    service_count: int
    empty: str | None
    services_path: str


class CategoryResponse(pydantic.BaseModel):
    categories: list[CategoryListing]
    declaration: str


class ErrorBody(pydantic.BaseModel):
    error: dict[str, str]
