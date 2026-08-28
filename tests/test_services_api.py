"""The category-first layer, and the fact plane it sits on top of.

`/services` exists so a reader who found a job can reach the control that runs it, and
`/agents` exists so the same reader can inspect what was observed. This file holds both
halves of that: the new layer says everything a caller needs to activate a service
without asking anyone, and the raw plane underneath it is asserted to be untouched.

The identity cross-link is the awkward part and is tested in all three of its states.
Five services now carry ERC-8004 identities, while this file's small snapshot fixture
holds only SOLVENT. A link that 404s is a dead end; a silent omission reads as no
identity at all. So the response says which of the two it is.
"""

import re
from dataclasses import replace

import pydantic
import pytest
from fastapi.testclient import TestClient

from docket.api import create_app
from docket.api.models import BANNED_FIELD_NAMES, ServiceCard
from docket.hire.catalogue import get_service as get_hire_service
from docket.marketplace.models import CATEGORIES, Category, is_share_unit
from docket.marketplace.registry import (
    EMPTY_CATEGORY,
    SERVICES,
    category_counts,
    records_in,
)
from docket.store import Store

SOLVENT_AGENT_ID = "56:0x8004a169fb4a3325136eb29fa0ceb6d2e539a432:136384"
UNRELATED = {
    "agent_id": "56:0xreg:1",
    "token_id": "1",
    "chain_id": 56,
    "name": "OpenOdds.Ai",
    "supported_protocols": ["A2A"],
    "total_feedbacks": 2,
}
BOUND = {
    "agent_id": SOLVENT_AGENT_ID,
    "token_id": "136384",
    "chain_id": 56,
    "name": "SOLVENT",
    "supported_protocols": ["A2A"],
    "total_feedbacks": 1,
}


def _client(tmp_path, rows):
    db = tmp_path / "s.sqlite3"
    store = Store(db)
    sid = store.begin_snapshot(chain_id=56, expected=len(rows))
    store.upsert_agents(rows, sid)
    store.finish_snapshot(sid, sampled=len(rows), expected=len(rows))
    return TestClient(create_app(db, snapshot_id=sid))


@pytest.fixture
def client(tmp_path):
    """The live shape: the bound identity is NOT in the served snapshot, because the
    snapshot Docket serves was swept from agents with at least one feedback record."""
    return _client(tmp_path, [UNRELATED])


@pytest.fixture
def client_holding_the_identity(tmp_path):
    return _client(tmp_path, [UNRELATED, BOUND])


def _values(node) -> list[str]:
    if isinstance(node, str):
        return [node]
    if isinstance(node, dict):
        return [s for key, value in node.items() for s in _values(key) + _values(value)]
    if isinstance(node, list):
        return [s for item in node for s in _values(item)]
    return []


# ------------------------------------------------------------------ categories


def test_categories_are_bnbs_four_with_the_job_each_one_gets_done(client):
    body = client.get("/categories").json()
    assert [c["category"] for c in body["categories"]] == [
        e.category.value for e in CATEGORIES
    ]
    for entry in body["categories"]:
        assert entry["job"].strip()
        assert entry["does"].strip()


def test_a_category_counts_only_what_is_actually_in_it(client):
    for entry in client.get("/categories").json()["categories"]:
        expected = len(records_in(Category(entry["category"])))
        assert entry["service_count"] == expected, entry["category"]


def test_a_stocked_category_carries_no_empty_sentence_and_every_shelf_is_stocked(
    client,
):
    """All four shelves have a service in them now, so `empty` is null on all four."""
    body = client.get("/categories").json()
    assert [e["service_count"] for e in body["categories"]] == [1, 1, 1, 1]
    for entry in body["categories"]:
        assert entry["empty"] is None, entry["category"]


def test_the_empty_shelf_sentence_is_still_what_a_bare_category_would_serve(
    client, monkeypatch
):
    """Shipping four categories over empty shelves scores worse than an honest narrow
    scope, and that guard has to survive the shelves being stocked — otherwise it quietly
    stops being tested at the moment it stops firing. The registry is emptied here so the
    route's own bare-shelf branch is exercised: it says it is bare, says why, names no
    date, and it is the API's sentence rather than one the page authored."""
    monkeypatch.setattr("docket.api.routes.records_in", lambda category: [])
    body = client.get("/categories").json()
    for entry in body["categories"]:
        assert entry["service_count"] == 0
        assert entry["empty"] == EMPTY_CATEGORY
        lowered = entry["empty"].lower()
        assert "no service here yet" in lowered
        for promise in ("coming soon", "soon", "shortly", "next release"):
            assert promise not in lowered, f"{entry['category']} promises: {promise}"


def test_categories_state_that_the_category_is_dockets_own_declaration(client):
    declaration = client.get("/categories").json()["declaration"].lower()
    assert "docket" in declaration and "declar" in declaration


# -------------------------------------------------------------------- services


def test_services_lists_every_service_docket_runs(client):
    body = client.get("/services").json()
    assert body["total"] == len(SERVICES)
    assert [s["service_id"] for s in body["services"]] == sorted(SERVICES)
    assert body["category"] is None


def test_services_are_ordered_by_id_and_never_by_a_docket_ranking(client):
    ids = [s["service_id"] for s in client.get("/services").json()["services"]]
    assert ids == sorted(ids)
    assert "ordered by service id" in client.get("/services").json()["ordering"].lower()


def test_filtering_by_category_returns_that_category_and_its_total(client):
    body = client.get("/services?category=rebalancing").json()
    assert body["category"] == "rebalancing"
    assert body["total"] == len(records_in(Category.REBALANCING))
    for card in body["services"]:
        assert card["category"] == "rebalancing"


def test_an_empty_category_returns_an_empty_list_rather_than_someone_elses_service(
    client,
):
    for category in Category:
        body = client.get(f"/services?category={category.value}").json()
        assert body["total"] == len(body["services"])
        for card in body["services"]:
            assert card["category"] == category.value


def test_an_unknown_category_is_refused_and_names_the_four(client):
    resp = client.get("/services?category=lending")
    assert resp.status_code == 422
    error = resp.json()["error"]
    assert error["code"] == "invalid_query_parameter"
    for value in (c.value for c in Category):
        assert value in error["message"], value


def test_a_service_outside_the_four_is_listed_rather_than_hidden_or_filed_wrongly(
    client,
):
    """warden-scan is a security service. It is not one of BNB's four jobs, and it is not
    going to be squeezed into one to fill a shelf."""
    cards = {s["service_id"]: s for s in client.get("/services").json()["services"]}
    assert cards["warden-scan"]["category"] is None
    assert cards["warden-scan"]["category_job"] is None


def test_every_card_carries_what_it_costs_and_how_to_run_it(client):
    for card in client.get("/services").json()["services"]:
        assert card["price_display"] == "0.50 USDT"
        assert card["price_atomic"] == 5 * 10**17
        assert card["asset"]
        assert card["paid_stock"] is False
        assert len(card["admission"]) == 4
        assert card["typical_seconds"] > 0
        assert card["hire_path"] == f"/hire/{card['service_id']}"
        assert card["hire_method"] == "POST"
        assert card["activation"] and card["activation_means"]


def test_every_card_carries_its_closed_evidence_modality(
    client, client_holding_the_identity
):
    cards = {
        card["service_id"]: card for card in client.get("/services").json()["services"]
    }
    expected = {
        "grid-operator": "live_read",
        "health-guard": "live_read",
        "range-doctor": "live_read",
        "solvent-signal": "historical",
        "warden-scan": "live_read",
        "yield-router": "live_read",
    }
    assert {
        service_id: card["evidence_modality"] for service_id, card in cards.items()
    } == expected
    for service_id, modality in expected.items():
        assert (
            client.get(f"/services/{service_id}").json()["evidence_modality"]
            == modality
        )

    agent = client_holding_the_identity.get(f"/agents/{SOLVENT_AGENT_ID}").json()
    assert agent["associated_services"][0]["evidence_modality"] == "historical"


def test_service_card_requires_a_non_null_evidence_modality(client):
    card = client.get("/services/range-doctor").json()
    schema = ServiceCard.model_json_schema()
    assert "evidence_modality" in schema["required"]
    assert schema["properties"]["evidence_modality"]["type"] == "string"

    without_modality = {
        key: value for key, value in card.items() if key != "evidence_modality"
    }
    with pytest.raises(pydantic.ValidationError, match="evidence_modality"):
        ServiceCard.model_validate(without_modality)
    with pytest.raises(pydantic.ValidationError, match="evidence_modality"):
        ServiceCard.model_validate({**card, "evidence_modality": None})


@pytest.mark.parametrize(
    "service_id", ["range-doctor", "grid-operator", "health-guard"]
)
def test_controlled_example_defaults_do_not_make_an_empty_body_valid(
    client, monkeypatch, service_id
):
    service = get_hire_service(service_id)

    def forbidden_run(payload):
        raise AssertionError("an empty body reached the service runner")

    monkeypatch.setattr(
        "docket.api.routes.get_service",
        lambda requested: (
            replace(service, run=forbidden_run)
            if requested == service_id
            else get_hire_service(requested)
        ),
    )
    response = client.post(f"/hire/{service_id}", json={})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "missing_field"
    assert "wallet" in response.json()["error"]["message"]


# ---------------------------------------------------------------------- detail


def test_service_detail_carries_everything_needed_to_activate_it(client):
    body = client.get("/services/range-doctor").json()
    assert body["service_id"] == "range-doctor"
    assert body["input_schema"]["wallet"]["required"] is True
    assert body["limitations"].strip()
    assert body["hire_path"] == "/hire/range-doctor"
    assert body["evidence"] and body["evidence"][0]["url"].startswith("/")


def test_all_four_category_cards_carry_recorded_metrics(client):
    cards = {
        card["service_id"]: card for card in client.get("/services").json()["services"]
    }
    for service_id in (
        "range-doctor",
        "grid-operator",
        "health-guard",
        "yield-router",
    ):
        assert cards[service_id]["metrics"], service_id
    for service_id in ("grid-operator", "health-guard", "yield-router"):
        assert all(
            "single recorded read; no paired run against a person" in metric["window"]
            for metric in cards[service_id]["metrics"]
        )


def test_an_unknown_service_is_a_404_naming_the_catalogue(client):
    resp = client.get("/services/no-such-thing")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "service_not_found"
    assert "/services" in resp.json()["error"]["message"]


def test_a_service_with_no_identity_says_so_instead_of_leaving_it_blank(client):
    body = client.get("/services/warden-scan").json()
    assert body["agent_id"] is None
    assert "no bsc identity bound yet" in body["identity"].lower()
    assert body["agent_path"] is None


def test_a_bound_identity_outside_the_served_snapshot_says_where_it_is_not(client):
    """This fixture's bound identity is not in the snapshot Docket serves. Offering
    a /agents link to it would be a dead end; saying nothing would read as unbound."""
    body = client.get("/services/solvent-signal").json()
    assert body["agent_id"] == SOLVENT_AGENT_ID
    assert SOLVENT_AGENT_ID in body["identity"]
    assert "not an endorsement" in body["identity"].lower()
    assert "evidence of paid stock" in body["identity"].lower()
    assert "produced a result" in body["identity"].lower()
    assert body["agent_path"] is None
    note = body["identity_note"].lower()
    assert "not in" in note and "snapshot" in note
    assert "feedback" in note, "the note must say which population the sweep covered"


def test_a_bound_identity_inside_the_snapshot_is_linked_to_its_own_record(
    client_holding_the_identity,
):
    body = client_holding_the_identity.get("/services/solvent-signal").json()
    assert body["agent_path"] == f"/agents/{SOLVENT_AGENT_ID}"
    linked = client_holding_the_identity.get(body["agent_path"])
    assert linked.status_code == 200
    assert linked.json()["agent_id"] == SOLVENT_AGENT_ID


def test_an_identity_stored_in_another_case_is_still_the_same_agent(tmp_path):
    """An agent_id carries an address, and an address differing only in case is the same
    address. Every row on the live database is lowercase, but that is the upstream's
    formatting — matching case-sensitively would deny an agent that is right there, and
    the link has to point at the id the snapshot actually stores."""
    checksummed = "56:0x8004A169FB4a3325136EB29fA0ceB6D2e539a432:136384"
    client = _client(tmp_path, [UNRELATED, {**BOUND, "agent_id": checksummed}])
    body = client.get("/services/solvent-signal").json()
    assert body["agent_path"] == f"/agents/{checksummed}"
    assert client.get(body["agent_path"]).status_code == 200


# --------------------------------------------------------- the honesty contract


def test_every_rate_in_a_service_response_carries_its_denominator(client):
    """A share whose base is missing is the Stage 0 bug. It cannot leave this API."""
    seen = 0
    for service_id in SERVICES:
        for metric in client.get(f"/services/{service_id}").json()["metrics"]:
            seen += 1
            assert metric["window"].strip() and metric["observed_at"].strip()
            assert metric["method"].strip()
            # The same predicate the model guards with, so this test cannot go on
            # checking three spellings after the guard has learned more.
            if is_share_unit(metric["unit"]):
                assert metric["denominator"] is not None, metric["name"]
            if metric["numerator"] is not None:
                assert metric["denominator"] is not None, metric["name"]
                assert f"of {metric['denominator']}" in metric["display"], metric[
                    "name"
                ]
    assert seen, "no metric was checked, so this test proved nothing"


def test_no_service_response_carries_a_verdict_word(client):
    paths = ["/categories", "/services"] + [f"/services/{s}" for s in SERVICES]
    for path in paths:
        for value in _values(client.get(path).json()):
            lowered = value.lower()
            for word in BANNED_FIELD_NAMES:
                assert not re.search(rf"\b{re.escape(word)}\b", lowered), (
                    f"{path} carries verdict language {word!r}"
                )


def test_agent_listings_stay_raw_while_detail_carries_the_reverse_marketplace_link(
    client,
):
    """The listing stays registry-only; detail names Docket's explicit service join."""
    listing = client.get("/agents").json()
    assert set(listing) == {"items", "total", "limit", "offset", "coverage"}
    item = listing["items"][0]
    assert set(item) == {
        "agent_id",
        "token_id",
        "name",
        "description",
        "owner_address",
        "has_feedback",
        "feedback_count",
        "declares_callable",
        "protocols",
        "x402",
        "name_family",
        "placeholder_name",
    }
    detail = client.get(f"/agents/{item['agent_id']}").json()
    assert set(detail) == set(item) | {
        "endpoints",
        "observations",
        "latest_on_demand_observation",
        "coverage",
        "associated_services",
    }
    assert detail["associated_services"] == []
    assert detail["latest_on_demand_observation"] is None


def test_a_bound_agent_exposes_the_service_page_and_hire_action(
    client_holding_the_identity,
):
    detail = client_holding_the_identity.get(f"/agents/{SOLVENT_AGENT_ID}").json()
    assert len(detail["associated_services"]) == 1
    service = detail["associated_services"][0]
    assert service["service_id"] == "solvent-signal"
    assert service["name"] == "SOLVENT Last Published Regime Signal"
    assert service["hire_method"] == "POST"
    assert service["hire_path"] == "/hire/solvent-signal"
    assert service["paid_stock"] is False
    assert service["stock_status"] == "research"


def test_the_machine_front_door_points_at_the_new_layer(client):
    body = client.get("/").json()
    assert body["categories"] == "/categories"
    assert body["services"] == "/services"


def test_llms_txt_documents_the_service_paths(client):
    """The drift guard requires every OpenAPI path in llms.txt; this says the three new
    ones are documented as workflows and not merely listed."""
    body = client.get("/llms.txt").text
    for path in ("/categories", "/services", "/services/{service_id}"):
        assert path in body, path
    assert "ordered by service id" in body.lower()


def test_agent_docs_explain_the_reverse_marketplace_link(client):
    llms = client.get("/llms.txt").text
    skill = client.get("/skill.md").text
    assert "associated_services" in llms
    assert "associated_services" in skill
    assert (
        "Nothing on that plane carries a category, a service or a hire path" not in llms
    )


def test_llms_txt_names_every_service_a_caller_can_hire(client):
    """The existing drift guard requires every OpenAPI *path* in llms.txt, which is a
    weaker promise than it looks: `/hire/{service_id}` is one path however many services
    stand behind it. So a service added to the catalogue is invisible to an agent that
    only ever reads the documentation, unless the documentation names it. This binds the
    prose to the stock."""
    body = client.get("/llms.txt").text
    for service_id in SERVICES:
        assert service_id in body, f"/llms.txt never names {service_id}"


def test_llms_txt_does_not_describe_an_inventory_docket_no_longer_has(client):
    """Prose goes stale where a test does not look. The count of stocked shelves is the
    single most quotable claim on this site and the easiest one to leave behind after a
    category is filled, so it is checked against the registry rather than reviewed."""
    # Whitespace-normalised: llms.txt is wrapped prose, and a sentence that happens to
    # break across two lines is still the same claim.
    body = " ".join(client.get("/llms.txt").text.lower().split())
    words = {0: "none", 1: "one", 2: "two", 3: "three", 4: "four"}
    stocked = sum(1 for count in category_counts().values() if count)
    empty = len(Category) - stocked
    assert f"{words[stocked]} of the four have a service in them" in body
    # Both branches are held, because the count moves in both directions and the sentence
    # for an all-stocked inventory is exactly as easy to leave behind as the other one.
    if empty:
        assert f"the other {words[empty]} return service_count 0" in body
    else:
        assert "no category returns service_count 0 today" in body


def test_llms_txt_does_not_describe_an_identity_inventory_docket_no_longer_has(client):
    """The same rot as the stocked-shelf count, four paragraphs further down, and this one
    had no guard: it once said five of six were unbound after four identities were minted.
    A count that is derivable from the registry should be
    checked against it rather than reviewed."""
    body = " ".join(client.get("/llms.txt").text.lower().split())
    words = {0: "none", 1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six"}
    unbound = sum(1 for record in SERVICES.values() if record.agent_id is None)
    verb = "is" if unbound == 1 else "are"
    assert (
        f"{words[unbound]} of the {words[len(SERVICES)]} services {verb} in this state"
        in body
    )


def test_skill_md_teaches_the_category_first_route(client):
    body = client.get("/skill.md").text
    for path in ("/categories", "/services"):
        assert path in body, path


def test_agent_docs_describe_the_new_service_and_comparison_fields(client):
    for path in ("/llms.txt", "/skill.md"):
        body = client.get(path).text
        for field in (
            "advanced",
            "evidence_modality",
            "freshness",
            "example_note",
            "typical_seconds_basis",
        ):
            assert field in body, f"{path} does not describe {field}"
        for modality in (
            "live_read",
            "preview",
            "historical",
            "paired_benchmark",
            "replay",
        ):
            assert modality in body, f"{path} does not name {modality}"
