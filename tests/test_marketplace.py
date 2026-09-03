"""The ontology that joins what Docket sells to what Docket can show for it.

Docket had two disconnected halves: a registry of agents nobody could hire, and a
catalogue of services with no identity, no category and no evidence attached. These
tests hold the seam closed — every hireable service has exactly one record, every
record names its limitations, every figure on it carries the population it was
measured against, and a category is only ever Docket's own declaration about a
service Docket runs.
"""

import json
import re
from dataclasses import asdict
from pathlib import Path

import pytest

from docket.advantage.harness import load
from docket.api.models import BANNED_FIELD_NAMES
from docket.hire.catalogue import SERVICES as HIRE_SERVICES
from docket.marketplace.models import (
    ACTIVATIONS,
    CATEGORIES,
    EVIDENCE_KINDS,
    Category,
    EvidenceRef,
    Metric,
    ServiceRecord,
    is_share_unit,
)
from docket.marketplace.registry import (
    CATEGORY_DECLARATION,
    EMPTY_CATEGORY,
    SERVICES,
    all_records,
    category_counts,
    get_record,
    records_in,
)


def _metric(**overrides) -> Metric:
    """A count that satisfies every rule, so each test can break exactly one of them."""
    fields = {
        "name": "Positions read",
        "unit": "position NFTs",
        "window": "one recorded run on one wallet",
        "observed_at": "2026-08-08",
        "method": "advantage task 01, agent arm",
        "numerator": 14,
        "denominator": 14,
    }
    fields.update(overrides)
    return Metric(**fields)


def _strings(record: ServiceRecord) -> list[str]:
    """Every word a reader can see on one record, including the ones it reads through
    to the hire catalogue for."""
    values = [
        record.service_id,
        record.name,
        record.what_you_get,
        record.limitations,
        record.activation,
        record.evidence_modality,
        record.identity_line,
    ]
    for metric in record.metrics:
        values += [
            metric.name,
            metric.unit,
            metric.window,
            metric.method,
            metric.render(),
        ]
    for ref in record.evidence:
        values += [ref.kind, ref.url, ref.label]
    return values


# ------------------------------------------------------------------ categories


def test_the_categories_are_exactly_bnbs_four():
    """Four job categories, no more: an invented fifth would be Docket describing a
    market rather than the one it was asked about."""
    assert {c.value for c in Category} == {
        "rebalancing",
        "grid_trading",
        "yield_optimisation",
        "health_factor",
    }
    assert len(CATEGORIES) == 4
    assert [entry.category for entry in CATEGORIES] == list(Category)


def test_every_category_names_the_job_in_words_a_stranger_reads():
    for entry in CATEGORIES:
        assert entry.job.strip(), f"{entry.category} has no job label"
        assert entry.does.strip(), (
            f"{entry.category} does not say what an agent in it does"
        )
    assert [entry.job for entry in CATEGORIES] == [
        "Keep LP earning",
        "Run a capped grid",
        "Move idle liquidity",
        "Protect a loan",
    ]


def test_a_category_is_docket_declaring_a_label_not_measuring_one():
    """The registry records nothing about what job an agent does. A category on a service
    Docket runs is therefore Docket's own label, and it has to say so in the same breath —
    otherwise it reads as a measured property of the agent."""
    declaration = CATEGORY_DECLARATION.lower()
    assert "docket" in declaration
    assert "declar" in declaration
    assert "third-party" in declaration or "registry agent" in declaration
    assert "not measured" in declaration


def test_the_declaration_separates_the_two_layers_that_share_the_four_names():
    """/categories and /api/agents both use these four names and mean different things by
    them. The declaration travels on both /categories and /services, so it is where a
    reader is told which claim they are looking at — and it has to name how a third-party
    category is arrived at, not merely admit that one exists."""
    declaration = CATEGORY_DECLARATION.lower()
    assert "/categories" in declaration and "/api/agents" in declaration
    for source in (
        "capability_source",
        "provider_declared",
        "registration_metadata",
        "docket_classified",
    ):
        assert source in declaration, source
    assert "reading of published prose" in declaration
    assert "hireable" in declaration


# --------------------------------------------------------------------- metrics


def test_a_rate_without_its_denominator_is_refused():
    """13 of 35 published as a share "of probed" when 14 were probed is the bug this
    rule exists to make impossible: a share cannot be constructed without its base."""
    with pytest.raises(ValueError):
        Metric(
            name="Endpoints that answered",
            unit="%",
            window="one sweep",
            observed_at="2026-08-07",
            method="one GET per declared endpoint",
            value=92.857,
        )


@pytest.mark.parametrize(
    "unit",
    [
        "%",
        "percent",
        "percentage",
        "pct",
        "share",
        "% of attempted",
        "share of the snapshot",
        "response rate",
        "ratio",
        "proportion",
        "bps",
        "basis points",
    ],
)
def test_a_share_is_recognised_by_how_it_is_spelled_not_by_an_exact_match(unit):
    """An allowlist of exact spellings is open at the back: `pct` is as much a rate as `%`,
    and one that did not happen to be listed would construct with no base at all. The guard
    matches the way a share is written, so a new spelling is caught rather than admitted."""
    assert is_share_unit(unit)
    with pytest.raises(ValueError):
        Metric(
            name="Endpoints that answered",
            unit=unit,
            window="one sweep",
            observed_at="2026-08-07",
            method="one GET per declared endpoint",
            value=92.857,
        )


@pytest.mark.parametrize(
    "unit",
    ["seconds", "position NFTs the wallet held", "receipts in the chain", "vectors"],
)
def test_a_measured_quantity_is_not_mistaken_for_a_share(unit):
    assert not is_share_unit(unit)
    Metric(
        name="Elapsed",
        unit=unit,
        window="one recorded run",
        observed_at="2026-08-08",
        method="advantage task 01",
        value=43.063,
    )


def test_a_numerator_without_its_denominator_is_refused():
    with pytest.raises(ValueError):
        _metric(denominator=None)


def test_a_denominator_without_its_numerator_is_refused():
    with pytest.raises(ValueError):
        _metric(numerator=None)


def test_a_count_may_stand_alone_because_it_is_not_a_share_of_anything():
    elapsed = Metric(
        name="Elapsed",
        unit="seconds",
        window="one recorded run",
        observed_at="2026-08-08",
        method="advantage task 01",
        value=43.063,
        numerator=None,
        denominator=None,
    )
    assert elapsed.render() == "43.063 seconds"


def test_a_metric_carrying_a_denominator_always_renders_it():
    assert _metric().render() == "14 of 14 position NFTs"
    share = _metric(
        name="Answered", unit="%", numerator=13, denominator=14, value=92.857
    )
    assert share.render() == "13 of 14 (92.857%)"


def test_a_metric_with_no_figure_at_all_is_refused():
    with pytest.raises(ValueError):
        _metric(numerator=None, denominator=None)


@pytest.mark.parametrize("field", ["name", "unit", "window", "observed_at", "method"])
def test_a_metric_must_say_what_when_and_how_it_was_measured(field):
    """A figure whose window or method is blank cannot be read, and cannot be contested."""
    with pytest.raises(ValueError):
        _metric(**{field: "  "})


# -------------------------------------------------------------------- evidence


def test_evidence_points_at_something_docket_itself_serves():
    ref = EvidenceRef(
        kind="advantage_task",
        url="/advantage#01-liquidity",
        label="Task 01, both arms in full",
    )
    assert ref.url.startswith("/")


def test_evidence_may_not_point_off_site():
    """Every claim behind a service card has to be checkable from this origin. An
    off-site link is a citation Docket cannot keep honest, and it would put a third-party
    request on a page that makes none."""
    with pytest.raises(ValueError):
        EvidenceRef(kind="advantage_task", url="https://example.test/report", label="x")


def test_evidence_kinds_are_a_closed_vocabulary():
    assert EVIDENCE_KINDS == frozenset({"advantage_task"})
    with pytest.raises(ValueError):
        EvidenceRef(kind="testimonial", url="/advantage", label="x")


def test_evidence_must_carry_a_label_a_reader_can_read():
    with pytest.raises(ValueError):
        EvidenceRef(kind="advantage_task", url="/advantage", label="   ")


# -------------------------------------------------------------- service records


def test_a_record_must_name_a_service_that_can_actually_be_hired():
    """The record describes an offer; an offer nobody can call is the split-brain again."""
    with pytest.raises(ValueError):
        ServiceRecord(
            service_id="no-such-service",
            category=None,
            agent_id=None,
            registration_uri=None,
            activation="one_shot",
            evidence_modality="live_read",
            metrics=(),
            evidence=(),
            limitations="stated",
        )


def test_every_record_states_its_limitations():
    for record in SERVICES.values():
        assert record.limitations.strip(), f"{record.service_id} states no limitations"


def test_a_record_may_not_omit_its_limitations():
    with pytest.raises(ValueError):
        ServiceRecord(
            service_id="range-doctor",
            category=None,
            agent_id=None,
            registration_uri=None,
            activation="one_shot",
            evidence_modality="live_read",
            metrics=(),
            evidence=(),
            limitations="  ",
        )


def test_activation_comes_from_the_closed_vocabulary():
    assert set(ACTIVATIONS) == {"one_shot", "monitor", "policy_action"}
    for record in SERVICES.values():
        assert record.activation in ACTIVATIONS
    with pytest.raises(ValueError):
        ServiceRecord(
            service_id="range-doctor",
            category=None,
            agent_id=None,
            registration_uri=None,
            activation="autonomous",
            evidence_modality="live_read",
            metrics=(),
            evidence=(),
            limitations="stated",
        )


def test_an_unbound_service_says_no_identity_is_bound():
    """Silence would read as an on-chain identity nobody registered."""
    record = ServiceRecord(
        service_id="range-doctor",
        category=None,
        agent_id=None,
        registration_uri=None,
        activation="one_shot",
        evidence_modality="live_read",
        metrics=(),
        evidence=(),
        limitations="stated",
    )
    assert record.agent_id is None
    assert "no bsc identity bound yet" in record.identity_line.lower()


def test_a_bound_service_names_the_identity_it_is_bound_to():
    record = ServiceRecord(
        service_id="solvent-signal",
        category=None,
        agent_id="56:0xreg:136384",
        registration_uri=None,
        activation="one_shot",
        evidence_modality="historical",
        metrics=(),
        evidence=(),
        limitations="stated",
    )
    assert "56:0xreg:136384" in record.identity_line


def test_the_record_reads_its_offer_through_to_the_hire_catalogue():
    """One copy of the price, the schema and the description. A second copy is a second
    thing to keep in step, and the one that goes stale is whichever a reader is looking at."""
    for service_id, record in SERVICES.items():
        offer = HIRE_SERVICES[service_id]
        assert record.name == offer.name
        assert record.what_you_get == offer.what_you_get
        assert record.input_schema == offer.input_schema
        assert record.price_display == offer.price_display
        assert record.price_atomic == offer.price_atomic
        assert record.asset == offer.asset
        assert record.typical_seconds == offer.typical_seconds


def test_evidence_modality_is_closed_and_populated_for_every_service():
    assert {
        service_id: record.evidence_modality for service_id, record in SERVICES.items()
    } == {
        "grid-operator": "live_read",
        "health-guard": "live_read",
        "range-doctor": "live_read",
        "solvent-signal": "historical",
        "warden-scan": "live_read",
        "yield-router": "live_read",
    }
    with pytest.raises(ValueError, match="evidence_modality"):
        ServiceRecord(
            service_id="range-doctor",
            category=None,
            agent_id=None,
            registration_uri=None,
            activation="one_shot",
            evidence_modality="testimonial",
            metrics=(),
            evidence=(),
            limitations="stated",
        )


def test_every_hireable_service_has_exactly_one_record_and_no_record_is_orphaned():
    """The seam, asserted in one line: a service a reader can find is a service a reader
    can hire, and back."""
    assert set(SERVICES) == set(HIRE_SERVICES)
    assert len(all_records()) == len(HIRE_SERVICES)


def test_records_are_listed_in_one_declared_order():
    """Never a Docket-invented ranking: service id, ascending, and nothing else."""
    ids = [record.service_id for record in all_records()]
    assert ids == sorted(ids)


def test_records_in_a_category_are_only_the_ones_declared_into_it():
    for category in Category:
        for record in records_in(category):
            assert record.category is category


def test_get_record_returns_none_rather_than_inventing_one():
    assert get_record("no-such-service") is None
    assert get_record("range-doctor") is SERVICES["range-doctor"]


def test_no_record_carries_a_verdict_word_anywhere_in_it():
    """The no-verdict contract binds values, not only field names. Matched on word
    boundaries: warden-scan's own description is about UNTRUSTED text, which carries
    "trusted" inside it while saying the opposite."""
    for record in SERVICES.values():
        for value in _strings(record):
            lowered = value.lower()
            for word in BANNED_FIELD_NAMES:
                assert not re.search(rf"\b{re.escape(word)}\b", lowered), (
                    f"{record.service_id} carries verdict language {word!r} in {value[:60]!r}"
                )


def test_every_metric_on_every_record_survives_the_denominator_rule():
    """Constructed at import, so this is really an assertion that the rule was applied
    to the real inventory and not only to the test fixtures."""
    for record in SERVICES.values():
        for metric in record.metrics:
            assert metric.window.strip() and metric.observed_at.strip()
            assert metric.method.strip()
            if metric.numerator is not None:
                assert metric.denominator is not None
            assert (
                str(metric.denominator or "") in metric.render()
                or metric.numerator is None
            )


# ------------------------------------------------------------- the inventory
#
# The three records as they actually stand, asserted rather than described. These are
# the tests that have to be edited on purpose when Stage 3 stocks a shelf or registers
# an identity — which is the point of writing them this way.


def _experiment(task_id: str) -> dict:
    """The recorded run a metric cites, read from the file /advantage serves."""
    path = Path(__file__).resolve().parents[1] / "docket" / "advantage" / "experiments"
    return asdict(load(next(path.glob(f"{task_id}*.json"))))


def _figure(record: ServiceRecord, name: str) -> Metric:
    return next(metric for metric in record.metrics if metric.name == name)


def test_all_four_categories_are_stocked_and_each_holds_exactly_one_service():
    """The inventory as it now stands. Four shelves, one service each, and the hard part
    was never the count — it was that each card has to be readable against what the
    service actually does. A shelf filled with something that does less than its card
    claims is worse than one left honestly empty, so the two tests below read the two new
    cards against their own limits."""
    assert category_counts() == {
        Category.REBALANCING: 1,
        Category.GRID_TRADING: 1,
        Category.YIELD_OPTIMISATION: 1,
        Category.HEALTH_FACTOR: 1,
    }
    assert [r.service_id for r in records_in(Category.REBALANCING)] == ["range-doctor"]
    assert [r.service_id for r in records_in(Category.GRID_TRADING)] == [
        "grid-operator"
    ]
    assert [r.service_id for r in records_in(Category.YIELD_OPTIMISATION)] == [
        "yield-router"
    ]
    assert [r.service_id for r in records_in(Category.HEALTH_FACTOR)] == [
        "health-guard"
    ]


def test_the_health_factor_card_says_venus_publishes_no_health_factor():
    """The one category named after a figure the protocol it reads does not have. Saying
    so in the card's own limitations is the whole difference between filling a shelf and
    fabricating one."""
    record = SERVICES["health-guard"]
    lowered = record.limitations.lower()
    for phrase in (
        "venus publishes no health factor",
        "derived here rather than read",
        "repay and supply-collateral only",
        "borrowing and withdrawing are not encoded",
        "a liquidation that did not happen",
        "single recorded read; no paired run against a person",
        # Custody, stated rather than implied.
        "docket never holds a key to your wallet",
        "revoking it sweeps its balance back to you at any time",
        "never transferred to docket",
        "always yours to sign",
        "exact amount and never unlimited",
        "not rules a chain enforces",
        "how much you fund the session with",
        # What a mined transaction does not prove.
        "not by itself evidence of how much was retired",
    ):
        assert phrase in lowered, phrase
    # The preview posture is gone rather than merely outweighed: this service prepares
    # calls, and a card still calling itself structurally only a preview would be wrong.
    for gone in ("structurally only a preview", "no execution path for a venus call"):
        assert gone not in lowered, gone
    assert record.activation == "one_shot"
    assert record.agent_id is not None


def test_the_yield_card_bounds_its_own_superlative_and_promises_no_execution():
    """ "Highest available APR" is a claim about a population. The card names the
    population, and says the half of a move this build does not draft."""
    record = SERVICES["yield-router"]
    lowered = record.limitations.lower()
    for phrase in (
        "bounded by the stated eligible set",
        "highest within that set at that moment",
        "supplied by the caller and is not derived",
        "not built in this stage",
        "no execution guarantee of any kind",
        "one day, not a forecast",
        "single recorded read; no paired run against a person",
    ):
        assert phrase in lowered, phrase
    assert record.activation == "one_shot"
    assert record.agent_id is not None


def test_each_new_category_service_publishes_only_its_single_recorded_read():
    for service_id in ("health-guard", "grid-operator", "yield-router"):
        record = SERVICES[service_id]
        assert record.metrics
        assert record.evidence
        assert record.evidence_modality == "live_read"
        assert all(metric.denominator is not None for metric in record.metrics)
        assert all(
            "single recorded read; no paired run against a person" in metric.window
            for metric in record.metrics
        )
        assert record.registration_uri is not None
        assert "bound to the bsc erc-8004 agent" in record.identity_line.lower()


def test_the_grid_service_says_a_hire_previews_rather_than_trades():
    """The card that fills a category has to be read hardest. It states in its own
    limitations that the hire cannot move anything, that acting needs a session the owner
    grants and the chain enforces, and that a fill is not a gain."""
    record = SERVICES["grid-operator"]
    lowered = record.limitations.lower()
    for phrase in (
        "structurally only a preview",
        "no session key",
        "cannot move anything",
        "docket never holds the owner key",
        "refuse more, never less",
        "a fill and not a gain",
        "single recorded read; no paired run against a person",
    ):
        assert phrase in lowered, phrase
    assert record.activation == "one_shot"
    assert "acts on chain" not in record.activation_means.lower()


def test_the_empty_shelves_say_why_and_promise_nothing():
    lowered = EMPTY_CATEGORY.lower()
    assert "no service here yet" in lowered
    for promise in ("coming soon", "shortly", "next release", "will be"):
        assert promise not in lowered, promise


def test_an_empty_shelf_points_at_the_other_layer_without_selling_it():
    """A zero on this shelf means Docket runs no service for this job. Left there alone it
    reads as "nobody on BSC does this", which the marketplace layer disproves — so the
    sentence names that layer, and in the same breath refuses to present anything in it as
    hireable on the strength of being in a registry."""
    lowered = EMPTY_CATEGORY.lower()
    assert "/api/agents" in lowered
    assert "hireable on the strength of being in the registry" in lowered
    assert "placeholder" in lowered


def test_range_doctor_is_declared_into_rebalancing_because_that_is_its_subject():
    record = SERVICES["range-doctor"]
    assert record.category is Category.REBALANCING
    assert record.activation == "one_shot"


def test_the_two_services_outside_the_four_are_listed_rather_than_filed_wrongly():
    """warden-scan is a security service and solvent-signal relays a dated read. Neither
    is one of BNB's four jobs, and neither is hidden for it."""
    for service_id in ("warden-scan", "solvent-signal"):
        assert SERVICES[service_id].category is None
        assert service_id in {record.service_id for record in all_records()}


def test_five_services_carry_identities_and_warden_scan_remains_unbound():
    bound = {
        service_id
        for service_id, record in SERVICES.items()
        if record.agent_id is not None
    }
    assert bound == {
        "grid-operator",
        "health-guard",
        "range-doctor",
        "solvent-signal",
        "yield-router",
    }
    assert SERVICES["warden-scan"].agent_id is None
    assert "no bsc identity bound yet" in SERVICES["warden-scan"].identity_line.lower()


def test_the_bound_identity_is_written_the_way_a_snapshot_stores_one():
    """Lowercased, three parts, chain first. The registry address is checksummed
    everywhere it is quoted for a human; an agent_id is not, and a mixed-case one would
    never match a row in /agents."""
    for record in SERVICES.values():
        if record.agent_id is None:
            continue
        assert record.agent_id == record.agent_id.lower()
        chain, address, token = record.agent_id.split(":")
        assert chain == "56"
        assert address.startswith("0x") and len(address) == 42
        assert token.isdecimal()


def test_only_category_services_claim_registration_documents_docket_serves():
    """The four committed documents are exact service URIs. SOLVENT and Warden have no
    repository-backed document URI, so neither receives an invented one."""
    for service_id in ("range-doctor", "grid-operator", "yield-router", "health-guard"):
        assert SERVICES[service_id].registration_uri == (
            f"https://docket.gudman.xyz/registrations/{service_id}.json"
        )
    assert SERVICES["solvent-signal"].registration_uri is None
    assert SERVICES["warden-scan"].registration_uri is None


def test_each_service_points_at_its_own_recorded_run():
    """warden-scan cites the v1 task and both dated v2 corpus experiments. Each run remains
    openable, and the post-deploy measurement does not replace the earlier record."""
    expected = {
        "grid-operator": ["/services/grid-operator"],
        "health-guard": ["/services/health-guard"],
        "range-doctor": ["/advantage#01-liquidity"],
        "solvent-signal": ["/advantage#02-trading"],
        "warden-scan": [
            "/advantage#03-security",
            "/advantage/v2#03-security-corpus",
            "/advantage/v2#05-security-corpus-postfix",
        ],
        "yield-router": ["/services/yield-router"],
    }
    for service_id, urls in expected.items():
        assert [ref.url for ref in SERVICES[service_id].evidence] == urls


def test_the_timings_on_a_record_are_the_timings_in_the_experiment_it_cites():
    """The figures are transcribed, so they are checked against the file rather than
    trusted. A record that drifts from the run it cites is a record that cites nothing."""
    for service_id, task_id in (
        ("range-doctor", "01"),
        ("solvent-signal", "02"),
        ("warden-scan", "03"),
    ):
        elapsed = _figure(SERVICES[service_id], "Elapsed")
        recorded = _experiment(task_id)["agent_arm"]["seconds"]
        assert elapsed.value == round(recorded, 3), service_id


def test_range_doctors_figures_are_the_ones_the_hire_itself_returned():
    result = _experiment("01")["agent_arm"]["output"]["result"]
    read = _figure(SERVICES["range-doctor"], "Position NFTs read")
    assert (read.numerator, read.denominator) == (
        result["positions_examined"],
        result["positions_held"],
    )
    skipped = _figure(SERVICES["range-doctor"], "Positions counted but not detailed")
    assert (skipped.numerator, skipped.denominator) == (
        result["closed_skipped"],
        result["positions_examined"],
    )


def test_category_read_figures_are_regenerated_from_the_committed_json():
    root = (
        Path(__file__).resolve().parents[1] / "docket" / "advantage" / "recorded_runs"
    )
    files = {
        "health-guard": "05-health-guard-read.json",
        "grid-operator": "06-grid-preview-read.json",
        "yield-router": "07-yield-router-read.json",
    }
    runs = {
        service_id: json.loads((root / filename).read_text(encoding="utf-8"))
        for service_id, filename in files.items()
    }

    health = runs["health-guard"]
    health_result = health["agent_arm"]["output"]["result"]
    health_coverage = _figure(
        SERVICES["health-guard"], "Entered markets carrying a borrow"
    )
    assert (health_coverage.numerator, health_coverage.denominator) == (
        sum(int(row["borrow_balance"]) > 0 for row in health_result["account"]["rows"]),
        health_result["account"]["markets_entered"],
    )

    grid = runs["grid-operator"]
    grid_result = grid["agent_arm"]["output"]["result"]
    grid_coverage = _figure(SERVICES["grid-operator"], "Levels quoted and hash-bound")
    assert (grid_coverage.numerator, grid_coverage.denominator) == (
        sum(
            bool(
                level["intent"]
                and level["simulation"]
                and level["simulation"]["agrees"]
            )
            for level in grid_result["levels"]
        ),
        grid_result["plan"]["requested_levels"],
    )

    route = runs["yield-router"]
    route_result = route["agent_arm"]["output"]["result"]
    route_coverage = _figure(SERVICES["yield-router"], "Pools clearing the stated gate")
    assert (route_coverage.numerator, route_coverage.denominator) == (
        route_result["universe"]["size"],
        route_result["universe"]["considered"],
    )


def test_solvents_anchor_figure_is_the_one_the_manual_arm_recomputed():
    experiment = _experiment("02")
    anchored = _figure(
        SERVICES["solvent-signal"], "Receipts covered by the last on-chain anchor"
    )
    assert anchored.numerator == experiment["manual_arm"]["output"]["anchored_count"]
    assert (
        anchored.denominator
        == experiment["agent_arm"]["output"]["result"]["source"]["receipt_count"]
    )


def test_warden_scans_record_carries_the_run_it_lost():
    """The unflattering figure is the one that has to survive. One of four vectors, with
    the denominator attached, and the three that got through said in the limitations."""
    experiment = _experiment("03")
    named = _figure(SERVICES["warden-scan"], "Hostile vectors named")
    assert named.numerator == len(
        experiment["agent_arm"]["output"]["result"]["detections"]
    )
    assert named.denominator == len(experiment["manual_arm"]["output"]["vectors"])
    assert named.render().startswith("1 of 4")
    limitations = SERVICES["warden-scan"].limitations.lower()
    assert "three of those four survive verbatim" in limitations
    assert "one observation, not a pattern" in limitations


def test_warden_card_recomputes_both_dated_corpus_measurements():
    record = SERVICES["warden-scan"]
    old = _figure(record, "Labelled attacks flagged")
    postfix = _figure(
        record, "Labelled attacks flagged after the 2026-08-24 detector deploy"
    )

    assert (old.numerator, old.denominator) == (14, 31)
    assert "exact source revision and deploy date were not recorded" in old.method
    assert (postfix.numerator, postfix.denominator) == (15, 30)
    assert "15 of 16" in postfix.method
    assert "16 of the 141 logical scans failed" in postfix.method
    assert "1 hostile payload was unscored" in postfix.method
    assert "0583853ed7fca7d03c98a5cc4c2383cc6b149248" in postfix.method
    assert "cannot qualify the held-out v3-04 gate" in postfix.method
    assert "warden remains beta" in record.limitations.lower()


def test_range_doctor_states_the_limits_its_own_audit_named():
    """The audit-named limits stay; the custody model is stated beside them.

    "read-only" left this card when the watch gained prepared calls. What replaces it is
    not softer — it is the specific shape of the authority: no key to the wallet, a
    session the owner grants and revokes, and a position NFT that never moves to Docket.
    """
    limitations = SERVICES["range-doctor"].limitations.lower()
    for phrase in (
        "v3",
        "tokensowed",
        "ticks rather than prices",
        # Custody, stated rather than implied.
        "docket never holds a key to your wallet",
        "revoking it sweeps its balance back to you at any time",
        "no position nft is ever transferred to docket",
        # The caps are Docket's own checks, not a chain's. Saying otherwise would make a
        # Python gate read as a guarantee the chain stands behind.
        "not rules a chain enforces",
        "how much you fund the session with",
        "stay there until you revoke",
        # What the watch cannot know.
        "realises impermanent loss",
        "a departure between two reads is not dated",
        "not a forecast",
        "single recorded read; no paired run against a person",
    ):
        assert phrase in limitations, phrase
    # The old posture is gone rather than merely outweighed: this service prepares calls.
    assert "read-only: nothing is signed" not in limitations


def test_solvent_signal_is_sold_as_a_dated_record_rather_than_a_live_one():
    limitations = SERVICES["solvent-signal"].limitations.lower()
    assert "historical record, not a live feed" in limitations
    assert "2026-06-28" in limitations
    assert "has published nothing since" in limitations
