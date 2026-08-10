import pydantic

from docket.api.models import (
    BANNED_FIELD_NAMES,
    AgentDetail,
    AgentSummary,
    CatalogueResponse,
    CategoryListing,
    CategoryResponse,
    Coverage,
    EvidenceLink,
    ListResponse,
    MetricFigure,
    ServiceCard,
    ServiceDetail,
    ServiceListing,
    ServicesResponse,
    StatsResponse,
)

ALL_MODELS = [
    Coverage,
    AgentSummary,
    AgentDetail,
    ListResponse,
    StatsResponse,
    ServiceListing,
    CatalogueResponse,
    MetricFigure,
    EvidenceLink,
    ServiceCard,
    ServiceDetail,
    ServicesResponse,
    CategoryListing,
    CategoryResponse,
]


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


def test_a_metric_cannot_be_served_without_the_way_it_was_measured():
    """The marketplace layer inherits the coverage discipline: a figure with no window,
    no date and no method is a number nobody can date or contest."""
    names = _field_names(MetricFigure)
    assert {"window", "observed_at", "method", "numerator", "denominator"} <= names
    for required in ("window", "observed_at", "method"):
        assert MetricFigure.model_fields[required].is_required(), required


def test_a_service_states_what_it_cannot_do():
    """`limitations` is required on the detail model, so a service cannot be published
    with the sentence a marketplace is most tempted to leave out."""
    assert "limitations" in _field_names(ServiceDetail)
    assert ServiceDetail.model_fields["limitations"].is_required()


def test_a_service_listing_declares_its_order_rather_than_implying_one():
    """An undeclared order is where an invented ranking hides."""
    assert "ordering" in _field_names(ServicesResponse)
    assert ServicesResponse.model_fields["ordering"].is_required()


def test_a_category_can_say_it_is_empty_and_must_say_which_it_is():
    names = _field_names(CategoryListing)
    assert {"service_count", "empty"} <= names
    # No default: a category serving no `empty` at all could be a bare shelf that says
    # nothing, which is the exact failure the field exists to prevent.
    assert CategoryListing.model_fields["empty"].is_required()


def test_the_service_layer_carries_the_identity_it_is_bound_to_or_says_it_is_not():
    names = _field_names(ServiceDetail)
    assert {"agent_id", "identity", "identity_note", "agent_path"} <= names
    assert ServiceDetail.model_fields["identity"].is_required()
