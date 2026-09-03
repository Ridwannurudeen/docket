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


def test_the_seed_loads_into_an_empty_store_and_is_queryable_by_category(tmp_path):
    store = Store(tmp_path / "d.sqlite3")
    for listing in load_seed(SEED):
        store.upsert_external_listing(listing.to_json())

    for member in Category:
        rows, total = store.search_external_listings(category=member.value, limit=50)
        assert total >= 2, member.value
        assert all(row["category"] == member.value for row in rows)
    assert sum(store.external_listings_by_level().values()) == len(load_seed(SEED))
