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
    publisher: str
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
    with_feedback: int
    callable_declared: int
    endpoints_resolved: int
    endpoints_probed: int
    endpoints_responded: int
    # Named for its denominator so the number cannot be requoted against the whole registry.
    responded_pct_of_probed: float
    blocked_by_policy: int
    unresolved: int
    distinct_publishers: int
    top_publishers: list[dict]
    probe_method: str


class ErrorBody(pydantic.BaseModel):
    error: dict[str, str]
