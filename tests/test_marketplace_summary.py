"""The counters, and the one defect they exist to make impossible.

The home page used to carry `0 settlements ever run` as typed markup while the README,
the claims ledger and the operational record all described an approved canary that had
settled 0.50 USDT. Nothing tied the page to the store, so the page could contradict
every other public document and every test still passed. These tests are that tie: the
shell may carry no counter of its own, the served page must carry the counted one, and a
settled row belonging to the internal canary may never be reported as a public paid hire.
"""

import re
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from docket.advantage.v3.report import report as v3_report
from docket.api import create_app
from docket.api.summary import (
    CANARY_PAYER,
    NOT_MEASURED,
    home_page,
    listing_facts,
    marketplace_summary,
)
from docket.hire.admission import resolve_admission
from docket.marketplace.registry import all_records
from docket.store import Store

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "docket" / "api" / "web"
PUBLIC_PAYER = "0x1111111111111111111111111111111111111111"
SUMMARY_KEYS = {
    "services_total",
    "services_paid_stock",
    "public_paid_hires",
    "canary_settlements",
    "erc8004_identities",
    "v3_families",
    "external_listings_by_level",
    "activations_by_state",
    "deployed_commit",
    "generated_at",
}


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / "summary.sqlite3")


def _reserve(store, *, nonce, payer, service_id="range-doctor"):
    reserved, _ = store.reserve_payment(
        nonce=nonce,
        payment_id=f"pay-{nonce}",
        service_id=service_id,
        payer=payer,
        recipient="0xe55816904796341bf8535e25f6c8b647927fc946",
        asset="0x55d398326f99059fF775485246999027B3197955",
        amount="500000000000000000",
        resource=f"https://docket.example/hire/{service_id}",
        input_hash=f"0xin-{nonce}",
    )
    assert reserved
    return f"pay-{nonce}"


def _settle(store, *, nonce, payer, service_id="range-doctor"):
    """Drive one payment through the exact states the hire route drives it through."""
    payment_id = _reserve(store, nonce=nonce, payer=payer, service_id=service_id)
    store.record_payment_output(
        payment_id, output_hash=f"0xout-{nonce}", result={"nonce": nonce}
    )
    assert store.begin_payment_settlement(payment_id)
    store.finish_payment(
        payment_id,
        transaction_id=f"0xtx-{nonce}",
        network="eip155:56",
        receipt={"payment": {"status": "settled"}},
    )
    return payment_id


def _summary(store, **kwargs):
    return marketplace_summary(
        store, v3_report=v3_report(), services=all_records(), **kwargs
    )


def test_the_summary_returns_exactly_the_contracted_keys(store):
    assert set(_summary(store)) == SUMMARY_KEYS


def test_the_canary_payer_is_the_address_the_runbook_records():
    """A payer address hard-coded in one file and rotated in another is the silent
    failure this rule has: the runbook is the record, so the constant is pinned to it."""
    runbook = (ROOT / "docs" / "deployment-runbook.md").read_text(encoding="utf-8")

    assert CANARY_PAYER == CANARY_PAYER.lower()
    assert CANARY_PAYER in runbook.lower()


def test_a_canary_settlement_is_never_reported_as_a_public_paid_hire(store):
    _settle(store, nonce="canary-1", payer=CANARY_PAYER)
    _settle(store, nonce="canary-2", payer=CANARY_PAYER.upper().replace("0X", "0x"))
    _settle(store, nonce="public-1", payer=PUBLIC_PAYER)

    summary = _summary(store)

    assert summary["canary_settlements"] == 2
    assert summary["public_paid_hires"] == 1


def test_a_payment_that_never_reached_settled_is_counted_as_neither(store):
    """`verified`, `output_ready` and `settling` are in-flight, and `failed_no_charge` is
    a payment that was deliberately not taken. Counting any of them would publish a
    settlement that never happened."""
    _reserve(store, nonce="in-flight", payer=PUBLIC_PAYER)
    output_ready = _reserve(store, nonce="output", payer=PUBLIC_PAYER)
    store.record_payment_output(
        output_ready, output_hash="0xout-output", result={"ok": True}
    )
    failed = _reserve(store, nonce="failed", payer=PUBLIC_PAYER)
    store.fail_payment(failed, status="failed_no_charge", error="admission closed")

    summary = _summary(store)

    assert summary["public_paid_hires"] == 0
    assert summary["canary_settlements"] == 0


def test_counters_that_belong_to_tables_no_lane_has_built_yet_are_empty(store):
    """An absent table is a population that does not exist. It is reported as an empty
    mapping rather than as a zero nobody counted or an error a reader cannot act on."""
    summary = _summary(store)

    assert summary["activations_by_state"] == {}
    assert summary["external_listings_by_level"] == {}


def test_activation_states_are_counted_once_the_table_exists(store):
    with closing(sqlite3.connect(store.path)) as conn:  # the shape Lane B's SCHEMA adds
        with conn:
            conn.execute(
                "CREATE TABLE activations "
                "(activation_id TEXT PRIMARY KEY, state TEXT NOT NULL)"
            )
            conn.executemany(
                "INSERT INTO activations (activation_id, state) VALUES (?, ?)",
                [("act_1", "active"), ("act_2", "active"), ("act_3", "revoked")],
            )

    assert _summary(store)["activations_by_state"] == {"active": 2, "revoked": 1}


def test_paid_stock_is_resolved_against_the_latest_canary_not_the_static_limb(store):
    """`/services` re-resolves admission per request, so the counter beside it must too:
    a stale canary closes the shelf, and a rail reading the frozen constant would keep
    advertising a service the API refuses to sell."""
    services = all_records()
    summary = _summary(store)
    expected = sum(
        resolve_admission(
            record.offer, store.latest_canary_run(record.service_id)
        ).passes
        for record in services
    )

    assert summary["services_paid_stock"] == expected
    assert summary["services_total"] == len(services)


def test_identity_and_family_counts_follow_the_committed_records(store):
    summary = _summary(store)

    assert summary["erc8004_identities"] == sum(
        record.agent_id is not None and record.category is not None
        for record in all_records()
    )
    assert summary["v3_families"] == v3_report()["summary"]["n_families"]


def test_the_deployed_commit_prefers_the_release_marker_beside_the_package(
    store, tmp_path
):
    marker = tmp_path / "RELEASE-commit.txt"
    marker.write_text("4a632c01ebcfdccaed36e642cec2e74adbb69381\n", encoding="utf-8")

    assert (
        _summary(store, release_commit_path=marker)["deployed_commit"]
        == "4a632c01ebcfdccaed36e642cec2e74adbb69381"
    )


def test_an_absent_release_marker_falls_back_rather_than_inventing_an_identity(
    store, tmp_path
):
    resolved = _summary(store, release_commit_path=tmp_path / "absent.txt")[
        "deployed_commit"
    ]

    assert resolved == "source" or re.fullmatch(r"[0-9a-f]{40}", resolved)


def test_the_generated_timestamp_is_the_observation_it_was_given(store):
    observed = datetime(2026, 9, 3, 11, 50, 0, 123456, tzinfo=timezone.utc)

    assert _summary(store, now=observed)["generated_at"] == "2026-09-03T11:50:00Z"


# ------------------------------------------------------------------ the listings


def test_every_listing_answers_the_same_questions(store):
    facts = listing_facts(store, all_records())
    fields = {
        "job",
        "identity",
        "last_verification",
        "success_count",
        "measurement_window",
        "price",
        "custody",
        "permissions",
        "revocation",
        "evidence_url",
    }

    assert len(facts) == len(all_records())
    for listing in facts:
        assert fields <= set(listing), listing["service_id"]
        for field in fields:
            assert listing[field], f"{listing['service_id']} left {field} blank"


def test_an_unmeasured_listing_says_so_rather_than_dropping_the_row(store):
    facts = {
        listing["service_id"]: listing
        for listing in listing_facts(store, all_records())
    }
    range_doctor = facts["range-doctor"]

    assert range_doctor["last_verification"] == NOT_MEASURED
    assert range_doctor["success_count"] == NOT_MEASURED
    assert range_doctor["measurement_window"] == NOT_MEASURED
    # A service with no registration says that too, in the same field the others use.
    assert "No BSC identity registered" in facts["warden-scan"]["identity"]
    assert "311253" in range_doctor["identity"]


def test_a_recorded_canary_fills_the_verification_fields_from_the_run(store):
    started = datetime(2026, 8, 30, 4, 17, tzinfo=timezone.utc)
    finished = started + timedelta(seconds=42)
    run_id = store.begin_canary_run(
        "range-doctor", "https://docket.example/hire/range-doctor", started.isoformat()
    )
    store.finish_canary_run(
        run_id,
        verdict="passed",
        checks=[
            {
                "leg": "challenge",
                "checked": ["offer present"],
                "observed": {"exact_offer_present": True},
                "evidence": {"status_code": 402},
                "status": "passed",
            }
        ],
        finished_at=finished.isoformat(),
    )
    failed_id = store.begin_canary_run(
        "range-doctor",
        "https://docket.example/hire/range-doctor",
        (started + timedelta(days=1)).isoformat(),
    )
    store.finish_canary_run(failed_id, verdict="failed", checks=[])

    listing = next(
        row
        for row in listing_facts(store, all_records())
        if row["service_id"] == "range-doctor"
    )

    assert listing["last_verification"] == "2026-08-30 04:17 UTC"
    assert listing["success_count"] == "1/2 recorded canary runs passed"
    assert (
        listing["measurement_window"] == "2026-08-30 04:17 UTC to 2026-08-31 04:17 UTC"
    )


# ------------------------------------------------------------------- the rendering


def test_the_home_shell_types_no_counter_of_its_own():
    """Every counted quantity on the page is a marker, never a digit. A number typed
    beside one of these nouns is exactly the drift that made the page contradict the
    README, so it is refused at the shell."""
    shell = (WEB / "index.html").read_text(encoding="utf-8")
    # The lookbehind keeps the label `ERC-8004 identities` from reading as a count.
    typed = re.search(
        r"(?<![-\w.])\d[\d,]*\s+"
        r"(?:settlements?|paid hires?|identities|services|families)",
        shell,
    )

    assert typed is None, (
        f"the home shell types a counter: {typed and typed.group(0)!r}"
    )
    assert "settlements ever run" not in shell
    assert "No settlement has occurred" not in shell
    for marker in (
        "<!-- summary-public-paid-hires -->",
        "<!-- summary-canary-settlements -->",
        "<!-- summary-services-paid-stock -->",
        "<!-- summary-services-total -->",
        "<!-- summary-erc8004-identities -->",
        "<!-- summary-category-services -->",
        "<!-- summary-v3-families -->",
        "<!-- summary-generated-at -->",
        "<!-- summary-deployed-commit -->",
        "<!-- marketplace-listings -->",
    ):
        assert marker in shell, marker


def test_a_shell_missing_a_marker_is_refused_rather_than_served_blank(store):
    summary = _summary(store)

    with pytest.raises(ValueError, match="summary-public-paid-hires"):
        home_page("<html></html>", summary, [])


def test_the_served_home_carries_the_counted_numbers_without_scripting(tmp_path):
    db = tmp_path / "served.sqlite3"
    store = Store(db)
    snapshot = store.begin_snapshot(chain_id=56, expected=0)
    store.finish_snapshot(snapshot, sampled=0, expected=0)
    _settle(store, nonce="canary-1", payer=CANARY_PAYER)
    _settle(store, nonce="public-1", payer=PUBLIC_PAYER)
    client = TestClient(create_app(db, snapshot_id=snapshot))

    served = client.get("/", headers={"accept": "text/html"}).text
    plain = " ".join(re.sub(r"<[^>]+>", " ", served).split())
    summary = client.get("/api/marketplace/summary").json()

    assert "<script" not in served
    assert set(summary) == SUMMARY_KEYS
    assert summary["public_paid_hires"] == 1
    assert summary["canary_settlements"] == 1
    assert f"{summary['public_paid_hires']} Public paid hires" in plain
    assert f"{summary['canary_settlements']} Internal canary settlements" in plain
    assert f"{summary['services_paid_stock']} Services open for paid hiring" in plain
    assert f"{summary['erc8004_identities']} ERC-8004 identities" in plain
    assert f"{summary['v3_families']} Registered paired families" in plain
    assert f"{summary['services_total']} services" in plain
    # The category heading counts categorised services, not registered identities: the
    # two are equal today and are not the same question.
    categorised = sum(1 for record in all_records() if record.category is not None)
    assert f"{categorised} runnable category services." in plain
    assert "<!-- summary-" not in served


def test_the_served_home_lists_every_catalogue_service_with_the_same_fields(tmp_path):
    db = tmp_path / "listings.sqlite3"
    store = Store(db)
    snapshot = store.begin_snapshot(chain_id=56, expected=0)
    store.finish_snapshot(snapshot, sampled=0, expected=0)
    client = TestClient(create_app(db, snapshot_id=snapshot))

    served = client.get("/", headers={"accept": "text/html"}).text
    cards = re.findall(r'<article class="listing-card".*?</article>', served, re.S)

    assert len(cards) == len(all_records())
    for card in cards:
        for label in (
            "<dt>Job</dt>",
            "<dt>BSC identity</dt>",
            "<dt>Last successful verification</dt>",
            "<dt>Successful runs</dt>",
            "<dt>Measurement window</dt>",
            "<dt>Price</dt>",
            "<dt>Custody</dt>",
            "<dt>Required permissions</dt>",
            "<dt>Cancellation and revocation</dt>",
            "<dt>Evidence</dt>",
        ):
            assert label in card, label
        assert "/activate?service=" in card
        assert "/service?id=" in card


def test_the_advantage_report_opens_with_the_one_page_summary(tmp_path):
    """Three additive reports, none superseding another, meant a reader had to open all
    three and hold them side by side to learn what had actually been measured. The
    summary is that comparison, built from the same payloads the JSON routes return."""
    db = tmp_path / "advantage.sqlite3"
    store = Store(db)
    snapshot = store.begin_snapshot(chain_id=56, expected=0)
    store.finish_snapshot(snapshot, sampled=0, expected=0)
    client = TestClient(create_app(db, snapshot_id=snapshot))

    served = client.get("/advantage", headers={"accept": "text/html"}).text
    section = re.search(r'<section class="one-page".*?</section>', served, re.S).group(
        0
    )
    rows = re.findall(r'<th scope="row" class="mono">([^<]+)</th>', section)

    assert "Agent Advantage, one page" in section
    assert section.index("Agent Advantage, one page") < served.index('id="method"')
    for family in v3_report()["families"]:
        assert family["spec_id"] in rows, family["spec_id"]
        assert family["state"] in section, family["state"]
    for task_id in ("01-liquidity", "02-trading", "03-security"):
        assert task_id in rows, task_id
    # The three absent-value words, each meaning something different from the others.
    for marker in ("unscored", "not run", "not recorded"):
        assert marker in section, marker
    # `$U` is the v1 records' own name for the asset; the page writes it as USDT
    # everywhere, and one asset under two spellings is two assets to a reader.
    assert "$U<" not in section and "$U " not in section


def test_the_advantage_shell_carries_the_marker_rather_than_the_table():
    """Authored HTML cannot state one number while the artifacts state another if it
    states no number at all."""
    shell = (WEB / "advantage.html").read_text(encoding="utf-8")

    assert "<!-- advantage-one-page -->" in shell
    assert '<section class="one-page"' not in shell


def test_a_shell_without_the_one_page_marker_is_refused():
    from docket.advantage.v2.report import report as v2_report
    from docket.api.advantage_pages import advantage_one_page

    with pytest.raises(ValueError, match="one-page summary marker"):
        advantage_one_page(
            "<html></html>",
            experiments=[],
            advantage_v2=v2_report(),
            advantage_v3=v3_report(),
        )


def test_the_goal_cards_route_to_the_four_official_categories():
    shell = (WEB / "index.html").read_text(encoding="utf-8")
    explore = re.search(r'<section[^>]+id="explore".*?</section>', shell, re.S).group(0)
    goals = re.findall(
        r'<a class="goal-card" href="([^"]+)">\s*<span class="goal-title">([^<]+)<',
        explore,
    )

    assert goals == [
        ("/activate?category=rebalancing", "Keep my LP position in range"),
        ("/activate?category=grid_trading", "Automate a trading grid"),
        ("/activate?category=yield_optimisation", "Move liquidity to better yield"),
        ("/activate?category=health_factor", "Protect my lending position"),
    ]
