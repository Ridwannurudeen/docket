"""The response contract an evaluator's agent parses.

Docket publishes observations, never judgements. `BANNED_FIELD_NAMES` is the list
of words that would turn an observation into a verdict, and a contract test
asserts no model here uses one — the field names are the promise, so they are
enforced rather than reviewed.

Every response carrying a count also carries `Coverage`, so no figure can be
quoted without the snapshot and sample size it came from.
"""

import pydantic

# A reader judges; Docket does not. Names that would claim otherwise are refused at the model.
BANNED_FIELD_NAMES = frozenset(
    {
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


class AgentDetail(AgentSummary):
    endpoints: list[str]
    observations: list[EndpointObservation]
    coverage: Coverage


class ListResponse(pydantic.BaseModel):
    items: list[AgentSummary]
    total: int
    limit: int
    offset: int
    coverage: Coverage


class StatsResponse(pydantic.BaseModel):
    coverage: Coverage
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
    # request actually reached. A blocked or unresolved target is evaluated and never attempted.
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


class CatalogueResponse(pydantic.BaseModel):
    services: list[ServiceListing]


class ErrorBody(pydantic.BaseModel):
    error: dict[str, str]
