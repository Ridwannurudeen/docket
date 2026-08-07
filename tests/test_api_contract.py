import pydantic

from docket.api.models import (
    BANNED_FIELD_NAMES,
    AgentDetail,
    AgentSummary,
    Coverage,
    ListResponse,
    StatsResponse,
)

ALL_MODELS = [Coverage, AgentSummary, AgentDetail, ListResponse, StatsResponse]


def _field_names(model: type[pydantic.BaseModel]) -> set[str]:
    return set(model.model_fields)


def test_no_model_exposes_a_verdict_field():
    """Docket serves observations. A verdict field would make it an authority it has not earned."""
    for model in ALL_MODELS:
        offending = _field_names(model) & BANNED_FIELD_NAMES
        assert not offending, f"{model.__name__} exposes verdict field(s): {offending}"


def test_banned_names_cover_the_obvious_temptations():
    for name in ("safe", "trusted", "verified_by_docket", "recommended", "rank", "trust_score"):
        assert name in BANNED_FIELD_NAMES


def test_every_statistic_carries_its_coverage():
    """StatsResponse must not be able to report a count without the snapshot it came from."""
    required = {"snapshot_id", "captured_at", "sampled", "expected", "dropped"}
    assert required <= _field_names(Coverage)
    assert "coverage" in _field_names(StatsResponse)
    assert Coverage.model_fields["snapshot_id"].is_required()


def test_list_response_states_its_coverage_too():
    assert "coverage" in _field_names(ListResponse)


def test_agent_summary_uses_observation_language():
    names = _field_names(AgentSummary)
    assert {"has_feedback", "declares_callable"} <= names


def test_agent_detail_carries_timestamped_observations():
    names = _field_names(AgentDetail)
    assert "observations" in names
    assert "endpoints" in names
