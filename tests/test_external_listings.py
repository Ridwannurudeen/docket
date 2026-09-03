"""The classification rule table, and the committed census the API ships with.

The rule table is the one place Docket puts a category on somebody else's agent, so the
tests here are about what it refuses as much as what it matches: a venue name is not a
job, a tie assigns nothing, and every answer names the rules behind it.
"""

import json
from pathlib import Path

import pytest

from docket.marketplace.external import (
    CATEGORY_RULES,
    LEVELS,
    ExternalListing,
    at_least,
    capability_text,
    classify,
    endpoints_from_metadata,
    listing_from_registry,
    load_seed,
    unverified,
)
from docket.marketplace.models import Category
from docket.store import Store

SEED = (
    Path(__file__).resolve().parents[1]
    / "docket"
    / "marketplace"
    / "seed"
    / "external-listings-2026-09-03.json"
)


def _card(name: str, description: str, **extra) -> dict:
    return {
        "agent_id": "56:0x8004a169fb4a3325136eb29fa0ceb6d2e539a432:1",
        "token_id": "1",
        "chain_id": 56,
        "name": name,
        "description": description,
        **extra,
    }


@pytest.mark.parametrize(
    "name, description, expected",
    [
        (
            "Range Keeper",
            "Watches a concentrated liquidity position and reports when it drifts.",
            Category.REBALANCING,
        ),
        (
            "Grid Trader",
            "Places a grid of orders inside a band.",
            Category.GRID_TRADING,
        ),
        (
            "Yield Router",
            "Ranks markets by supply rate and says what moving would cost.",
            Category.YIELD_OPTIMISATION,
        ),
        (
            "Health Guard",
            "Reads a borrower's health factor before the position is liquidated.",
            Category.HEALTH_FACTOR,
        ),
    ],
)
def test_each_of_the_four_jobs_is_recognised_from_its_own_vocabulary(
    name, description, expected
):
    category, source, rationale = classify(_card(name, description))

    assert category is expected
    assert source == "docket_classified"
    assert expected.value in rationale


def test_a_protocol_name_is_not_a_job():
    """Venus is deliberately absent from the table: the BSC agents naming it split between
    lending-health monitors and yield rankers, so it identifies neither shelf."""
    assert not any(
        "venus" in term or "pancake" in term
        for terms in CATEGORY_RULES.values()
        for term in terms
    )
    category, _, rationale = classify(
        _card("Venus Thing", "An agent for Venus on BNB Chain.")
    )

    assert category is None
    assert "no term in the category rule table" in rationale


def test_a_tie_between_two_categories_assigns_nothing_and_names_both():
    category, _, rationale = classify(
        _card("Both", "Places a grid of orders and watches the health factor.")
    )

    assert category is None
    assert "no rule-count margin" in rationale
    assert "grid_trading" in rationale and "health_factor" in rationale


def test_a_strict_rule_count_margin_decides_and_prints_the_losing_side():
    """HeyAnon's registration matches two collateral rules and one yield rule. The margin
    rule is the whole decision, and the rationale has to show what it decided against."""
    category, _, rationale = classify(
        _card(
            "Venus powered by HeyAnon",
            "Validates collateral ratios, checks borrow limits, and answers APR queries.",
        )
    )

    assert category is Category.HEALTH_FACTOR
    assert "yield_optimisation" in rationale
    assert "collateral ratio*" in rationale and "borrow limit*" in rationale


def test_a_registration_that_declares_its_own_category_outranks_the_rule_table():
    category, source, rationale = classify(
        _card(
            "Guardian",
            "Places a grid of orders.",
            categories=["health-factor-monitoring"],
        )
    )

    assert category is Category.HEALTH_FACTOR
    assert source == "registration_metadata"
    assert "declares" in rationale


def test_a_stem_rule_covers_its_inflections_and_a_phrase_rule_does_not_run_on():
    """`rebalanc*` is one rule for rebalance/rebalances/rebalancing; `ltv` is a whole word
    and must not match inside a longer token."""
    assert (
        classify(_card("A", "It rebalances the position."))[0] is Category.REBALANCING
    )
    assert classify(_card("A", "It is rebalancing the position."))[0] is (
        Category.REBALANCING
    )
    assert classify(_card("A", "The value is ltvxyz."))[0] is None


def test_capability_text_reads_tags_skills_and_mcp_tool_names():
    text = capability_text(
        {
            "name": "N",
            "description": "D",
            "tags": ["DeFi Yield Optimizer"],
            "skills": [{"id": "s", "name": "grid planner", "description": "x"}],
            "services": {"mcp": {"tools": ["getBorrowAPR"]}},
        }
    )

    for fragment in ("N", "D", "DeFi Yield Optimizer", "grid planner", "getBorrowAPR"):
        assert fragment in text


def test_a_web_homepage_is_recorded_but_is_not_an_invocable_endpoint():
    listing = listing_from_registry(
        _card(
            "A",
            "Rebalancing agent.",
            services={
                "web": {"endpoint": "https://example.test"},
                "a2a": {"endpoint": "https://example.test/a2a"},
            },
        )
    )

    assert [row["kind"] for row in listing.endpoints] == ["a2a", "web"]
    assert [row["url"] for row in listing.invocable_endpoints] == [
        "https://example.test/a2a"
    ]


def test_a_non_http_endpoint_is_not_recorded_as_one():
    assert (
        endpoints_from_metadata({"services": {"a2a": {"endpoint": "ipfs://x"}}}) == ()
    )
    assert endpoints_from_metadata({"services": {"a2a": {"endpoint": "   "}}}) == ()


def test_a_registry_listing_starts_with_no_level_and_is_not_hireable():
    """Being in an index is not an observation, and it must not sort above `registered`."""
    listing = listing_from_registry(_card("A", "Grid agent."))

    assert listing.verification == unverified()
    assert listing.level is None
    assert listing.hireable is False
    assert at_least(None, "registered") is False


def test_a_listing_cannot_be_hireable_below_docket_tested():
    with pytest.raises(ValueError, match="hireable requires level docket_tested"):
        ExternalListing(
            agent_id="56:0xreg:1",
            chain_id=56,
            name="A",
            owner=None,
            registration_uri=None,
            endpoints=(),
            declared_category=None,
            classified_category=None,
            capability_source="docket_classified",
            price=None,
            payment_method=None,
            verification={"level": "live", "evidence": [], "verified_at": "now"},
            hireable=True,
        )


def test_a_level_outside_the_vocabulary_is_refused_at_the_constructor():
    with pytest.raises(ValueError, match="is not one of"):
        ExternalListing(
            agent_id="56:0xreg:1",
            chain_id=56,
            name="A",
            owner=None,
            registration_uri=None,
            endpoints=(),
            declared_category=None,
            classified_category=None,
            capability_source="docket_classified",
            price=None,
            payment_method=None,
            verification={"level": "audited", "evidence": [], "verified_at": "now"},
            hireable=False,
        )


def _verified(level: str, evidence: list) -> ExternalListing:
    return ExternalListing(
        agent_id="56:0xreg:43129",
        chain_id=56,
        name="A",
        owner=None,
        registration_uri=None,
        endpoints=(),
        declared_category=None,
        classified_category=None,
        capability_source="docket_classified",
        price=None,
        payment_method=None,
        verification={
            "level": level,
            "evidence": evidence,
            "verified_at": "2026-09-03T00:00:00+00:00",
        },
        hireable=at_least(level, "docket_tested"),
    )


def test_a_docket_tested_listing_serialises_both_facts_and_neither_implies_the_other():
    """`docket_tested` hangs off `live`, so it says a sample invocation returned a
    schema-valid result and says nothing about payment. The listing has to carry both
    facts: a reader who saw only the level would have to guess, and the guess a shop front
    invites is the flattering one."""
    row = {
        "level": "payment_tested",
        "ok": False,
        "at": "2026-09-03T00:00:00+00:00",
        "detail": {
            "message": "the endpoint answered without an x402 payment challenge"
        },
    }
    payload = _verified(
        "docket_tested",
        [row, {"level": "docket_tested", "ok": True, "at": "x", "detail": {}}],
    ).to_json()

    assert payload["verification"]["level"] == "docket_tested"
    assert payload["verification"]["payment_tested"] is False
    assert payload["verification"]["payment_tested_evidence"] == row
    assert payload["hireable"] is True


def test_payment_tested_is_true_only_where_its_own_evidence_row_passed():
    passed = _verified(
        "payment_tested",
        [{"level": "payment_tested", "ok": True, "at": "x", "detail": {"paid": False}}],
    ).to_json()

    assert passed["verification"]["payment_tested"] is True
    assert passed["verification"]["payment_tested_evidence"]["detail"]["paid"] is False


def test_a_listing_with_no_evidence_says_false_and_shows_no_row_to_back_it():
    """False covers "asked and none" and "never asked", and only the row tells them apart.
    A boolean alone would let a listing nothing was ever run against read as one that was
    asked for a price and had none."""
    payload = listing_from_registry(_card("A", "Grid agent.")).to_json()

    assert payload["verification"]["level"] is None
    assert payload["verification"]["payment_tested"] is False
    assert payload["verification"]["payment_tested_evidence"] is None


def test_the_payment_boolean_is_derived_from_evidence_not_read_from_the_input():
    """Stored beside the evidence it would drift from it. A listing asserting a payment
    reading its own evidence does not support must not serialise that assertion."""
    lying = _verified(
        "live",
        [{"level": "payment_tested", "ok": False, "at": "x", "detail": {}}],
    )
    forged = dict(lying.verification, payment_tested=True)
    payload = ExternalListing.from_json(
        {**lying.to_json(), "verification": forged}
    ).to_json()

    assert payload["verification"]["payment_tested"] is False


def test_every_seeded_listing_carries_the_payment_boolean_beside_its_level():
    for listing in load_seed(SEED):
        payload = listing.to_json()
        assert isinstance(payload["verification"]["payment_tested"], bool)
        assert payload["verification"]["payment_tested"] == listing.payment_tested
        if payload["verification"]["payment_tested"]:
            assert payload["verification"]["payment_tested_evidence"]["ok"] is True


def test_a_listing_survives_a_round_trip_through_json():
    original = listing_from_registry(
        _card("A", "Grid agent.", services={"a2a": {"endpoint": "https://a.test/a2a"}})
    )
    restored = ExternalListing.from_json(original.to_json())

    assert restored == original


def test_the_committed_seed_loads_and_every_listing_in_it_is_readable():
    listings = load_seed(SEED)

    assert len(listings) >= 8, "the census target is at least eight listings"
    for listing in listings:
        assert listing.agent_id.startswith("56:")
        assert listing.capability_source in (
            "provider_declared",
            "registration_metadata",
            "docket_classified",
        )
        assert listing.level in (None, *LEVELS)
        assert listing.hireable == at_least(listing.level, "docket_tested")


def test_the_seed_meets_the_census_targets_it_was_written_for():
    listings = load_seed(SEED)
    by_category: dict[str, int] = {}
    for listing in listings:
        if listing.category is None or not at_least(listing.level, "endpoint_detected"):
            continue
        by_category[listing.category.value] = (
            by_category.get(listing.category.value, 0) + 1
        )

    assert set(by_category) == {member.value for member in Category}
    for category, count in by_category.items():
        assert count >= 2, (
            f"{category} has {count} listing(s) at endpoint_detected or above"
        )
    assert any(at_least(listing.level, "docket_tested") for listing in listings)


def test_the_seed_carries_its_own_method_and_never_claims_docket_verified():
    payload = json.loads(SEED.read_text(encoding="utf-8"))

    assert payload["method"]["registry"].startswith("8004scan")
    assert "no payment presented" in payload["method"]["endpoint"]
    assert payload["generated_at"].startswith("2026-09-03")
    assert not any(
        row["verification"]["level"] == "docket_verified" for row in payload["listings"]
    )


def test_both_agent_facing_documents_say_what_docket_tested_does_not_mean():
    """The wording is the whole safeguard for a client that reads a level and stops there.
    Pinned in both documents, because a reader arrives at one or the other."""
    static = Path(__file__).resolve().parents[1] / "docket" / "api" / "static"
    for name in ("llms.txt", "SKILL.md"):
        body = " ".join((static / name).read_text(encoding="utf-8").split())
        assert "schema-valid structured result" in body, name
        assert "does not mean a payment was tested" in body.lower(), name
        assert "payment_tested_evidence" in body, name
        assert "payment_tested: false" in body.lower(), name


def test_the_census_document_states_the_same_thing_about_its_one_tested_agent():
    doc = " ".join(
        (
            Path(__file__).resolve().parents[1]
            / "docs"
            / "marketplace"
            / "verification-2026-09-03.md"
        )
        .read_text(encoding="utf-8")
        .split()
    )

    assert "does not imply a payment was tested" in doc
    assert "payment_tested: false" in doc


CENSUS = (
    Path(__file__).resolve().parents[1]
    / "docs"
    / "marketplace"
    / "census-2026-09-03.json"
)
DOC = (
    Path(__file__).resolve().parents[1]
    / "docs"
    / "marketplace"
    / "verification-2026-09-03.md"
)


def test_the_census_document_quotes_the_figures_its_own_json_recorded():
    """Every figure in the document is a count the runner wrote. Hand-transcribed numbers
    rot silently and this table is the one a reader checks, so the two are held together
    rather than reviewed apart."""
    counts = json.loads(CENSUS.read_text(encoding="utf-8"))["counts"]
    doc = DOC.read_text(encoding="utf-8")

    for figure in (
        f"{counts['registry_total_when_the_pass_ran']:,}",
        str(counts["matched_by_search"]),
        str(counts["declaring_a2a_or_mcp"]),
        str(counts["selected_by_classification"]),
        str(counts["verified"]),
        str(counts["live_answering_2xx"]),
        str(counts["declaring_x402_support"]),
    ):
        assert figure in doc, figure
    assert counts["by_level"]["docket_tested"] == 1
    assert counts["by_level"].get("payment_tested", 0) == 0
    for category, count in counts["by_category"].items():
        assert f"{category} {count}" in doc, category


def test_every_agent_the_census_verified_is_named_in_the_document():
    census = json.loads(CENSUS.read_text(encoding="utf-8"))
    doc = DOC.read_text(encoding="utf-8")

    for row in census["results"]:
        assert f"| {row['token_id']} |" in doc, row["token_id"]
    assert len(census["results"]) == census["counts"]["verified"]


def test_the_seed_holds_exactly_what_the_census_verified():
    census = json.loads(CENSUS.read_text(encoding="utf-8"))
    seeded = {listing.agent_id for listing in load_seed(SEED)}

    assert seeded == {
        row["agent_id"] for row in census["results"] if row.get("agent_id")
    }


def test_the_stores_level_ordering_matches_the_level_vocabulary():
    """The rank lives in store.py because that module imports nothing from the domain, so
    the two definitions are bound here instead of by an import."""
    from docket.store import EXTERNAL_LEVELS

    assert EXTERNAL_LEVELS == LEVELS


def test_the_seed_loads_into_an_empty_store_and_is_queryable_by_category(tmp_path):
    store = Store(tmp_path / "d.sqlite3")
    for listing in load_seed(SEED):
        store.upsert_external_listing(listing.to_json())

    for member in Category:
        rows, total = store.search_external_listings(category=member.value, limit=50)
        assert total >= 2, member.value
        assert all(row["category"] == member.value for row in rows)
    assert sum(store.external_listings_by_level().values()) == len(load_seed(SEED))
