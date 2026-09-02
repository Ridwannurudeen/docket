"""The deposit-adjusted record: what has to hold for a loss to be evidence, and what it must
never become.

06 refuses to publish a return and says why: its corpus records equity without recording
funding. This experiment supplies the missing term from outside that corpus, and the thing it
publishes is adverse — the account is down once the money paid into it is subtracted. Three
things are guarded here and each of them is a way an adverse figure can quietly stop being
true.

The first is the subtraction itself. Every term is a hex string an archive node returned, so
the test redoes the arithmetic from the frozen words rather than reading the answer off the
record — including the check the corpus cannot make for itself, that each deposit's Transfer
log equals the wallet's balance delta across its own block.

The second is the two things the figure is not, because a loss quoted without them reads as a
measurement of the agent and is not one. The wallet sent 113 transactions and the chain names
37 hashes, so the attribution gap is asserted by number; gas is outside every figure and the
exclusion runs one way, so the direction is asserted too.

The third is the regression 06 already carries, restated over this experiment because this is
the record that publishes percentages. The raw series divides to +2592.98% and the equity
series to +2558.36%, and neither may appear in this payload or on this page in any form. It is
walked as numbers rather than searched as text, because the digits of a percentage are also the
digits of a block number.

Nothing here touches a network. Every test reads the two frozen corpora, the registered spec,
the committed run and the served payload, all of them files in this repository.
"""

import hashlib
import json
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from docket.advantage.v2 import deposits
from docket.advantage.v2.spec import load
from docket.api import create_app
from docket.store import Store

ROOT = Path(__file__).resolve().parents[1]
FLOWS_PATH = ROOT / "docket/advantage/v2/corpus/trading/solvent-wallet-flows.json"
CHAIN_PATH = ROOT / "docket/advantage/v2/corpus/trading/solvent-receipts.json"
SPEC_PATH = ROOT / "docket/advantage/v2/specs/07-solvent-deposit-adjusted.json"
RUN_PATH = ROOT / "docket/advantage/v2/runs/07-solvent-deposit-adjusted.json"
SOLVENT_SPEC_PATH = ROOT / "docket/advantage/v2/specs/06-solvent-record.json"

FLOWS = json.loads(FLOWS_PATH.read_text(encoding="utf-8"))
CHAIN = json.loads(CHAIN_PATH.read_text(encoding="utf-8"))
RUN = json.loads(RUN_PATH.read_text(encoding="utf-8"))
READINGS = {
    reading["label"]: reading
    for reading in FLOWS["results"]["balance_and_nonce_readings"]
}
RECEIPTS = [envelope["receipt"] for envelope in CHAIN["receipts"]]

# The two quotients a reader gets for free, and the only reason they are computed anywhere in
# this repository is so that nothing else can serve them. The first divides the closing
# dollar-pegged balance by the opening one; the second does the same to the equity series 06
# reads. Both are funding artifacts: 1203.32 US dollars was paid into the account.
NAIVE_STABLES_RATIO = Decimal("1224.6128995729") / Decimal("45.4741981332")
NAIVE_EQUITY_RATIO = Decimal(str(RECEIPTS[-1]["equity_usd"])) / Decimal(
    str(RECEIPTS[0]["equity_usd"])
)


@pytest.fixture
def client(tmp_path):
    db = tmp_path / "deposits.sqlite3"
    store = Store(db)
    snapshot = store.begin_snapshot(chain_id=56, expected=0)
    store.finish_snapshot(snapshot, sampled=0, expected=0)
    return TestClient(create_app(db, snapshot_id=snapshot))


@pytest.fixture
def experiment(client):
    body = client.get("/advantage/v2.json").json()
    return next(
        item
        for item in body["experiments"]
        if item["experiment_id"] == "07-solvent-deposit-adjusted"
    )


@pytest.fixture
def detail(client):
    resp = client.get(
        "/advantage/v2/07-solvent-deposit-adjusted", headers={"accept": "text/html"}
    )
    assert resp.status_code == 200
    return resp.text


def numbers(node, path="") -> list:
    """Every numeric leaf in the payload, with the path it sits at."""
    found = []
    if isinstance(node, dict):
        for key, value in node.items():
            found += numbers(value, f"{path}/{key}")
    elif isinstance(node, list):
        for index, value in enumerate(node):
            found += numbers(value, f"{path}[{index}]")
    elif isinstance(node, bool):
        pass
    elif isinstance(node, (int, float)):
        found.append((path, float(node)))
    return found


def test_the_corpus_is_raw_rpc_answers_with_the_endpoint_and_the_digest_that_fix_them():
    """A reconstruction is only evidence if a reader can repeat the calls behind it. The
    endpoint, the fetch time and a digest over the node's own answers are all on the file, and
    the answers themselves are the hex the node returned rather than numbers somebody typed."""
    results = FLOWS["results"]
    digest = hashlib.sha256(
        json.dumps(results, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()

    assert FLOWS["endpoint"].startswith("https://")
    assert FLOWS["chain_id"] == 56
    assert FLOWS["readings_sha256"] == digest
    assert len(results["balance_and_nonce_readings"]) == 6
    assert len(results["adjacent_block_readings"]) == 4
    assert len(results["deposit_transactions"]) == 2
    for reading in results["balance_and_nonce_readings"]:
        assert reading["block_timestamp"].startswith("0x")
        assert reading["transaction_count"].startswith("0x")
        assert set(reading["balance_of"]) == {"USDT", "USDC", "ETH"}
        for word in reading["balance_of"].values():
            assert len(word) == 66, word
    # Decimals are read from the token rather than assumed, and all three are 18.
    assert {
        symbol: int(word, 16) for symbol, word in results["token_decimals"].items()
    } == {"USDT": 18, "USDC": 18, "ETH": 18}
    # The wallet and both senders are externally owned accounts.
    assert set(results["code_at_address"].values()) == {"0x"}
    assert "eth_getLogs" in FLOWS["completeness"]
    assert "owner-attested" in FLOWS["completeness"]


def test_the_registered_spec_carries_the_digest_of_the_corpus_on_disk():
    """`load` re-hashes the spec's own fields on the way in; this asserts the other half, that
    the readings these tests subtract are the readings the registration was written against."""
    spec = load(SPEC_PATH)
    digest = hashlib.sha256(FLOWS_PATH.read_bytes()).hexdigest()

    assert spec.spec_id == "07-solvent-deposit-adjusted"
    assert (
        spec.dataset_ref
        == "docket/advantage/v2/corpus/trading/solvent-wallet-flows.json"
    )
    assert spec.dataset_sha256 == digest
    assert (ROOT / spec.dataset_ref).resolve() == FLOWS_PATH.resolve()
    assert spec.n_planned == 10
    assert RUN["spec_hash"] == spec.spec_hash
    assert RUN["spec_id"] == spec.spec_id
    assert RUN["dataset_sha256"] == digest


def test_the_spec_registers_the_deposit_rule_and_both_nulls_before_the_arithmetic():
    """The rule that decides what a deposit is has to be in the registration, not in the
    result. It is a rule about who sent the transaction, which is why no leg of a trade can
    enter the set — and the stopping rule says outright that the headline was already known."""
    spec = load(SPEC_PATH)
    names = [baseline["name"] for baseline in spec.null_baselines]

    assert names == ["count_the_balance_change_as_the_result", "hold_the_stables"]
    assert "tx.from != the wallet" in spec.metric["formula"]
    assert "no swap can enter this set" in spec.metric["formula"]
    assert "LOSS of 24.184588 US dollars" in spec.claim
    assert "not provably the agent's" in spec.claim
    assert "excludes gas" in spec.claim
    assert "no time-weighted return is published as a figure" in spec.claim
    assert "greater than or equal to zero" in spec.falsifier
    assert "were all known before this specification was written" in spec.stopping_rule
    assert "does not pretend to have been" in spec.stopping_rule


def test_the_two_deposits_recompute_from_the_frozen_transactions_and_their_receipts():
    """Twelve properties per deposit, redone here from the raw transaction and receipt rather
    than read off the record. The load-bearing one is the last: the amount the Transfer log
    carries is the wallet's balance delta across the block the transaction sits in, which is
    the only check that ties a log to the account's own balance."""
    measured = deposits.measure(FLOWS, CHAIN)
    decoded = measured["flows"]["deposits"]

    assert len(decoded) == 2
    for deposit in decoded:
        assert deposit["is_a_bare_external_deposit"] is True
        assert len(deposit["checks"]) == 12
        assert all(deposit["checks"].values()), deposit["tx_hash"]
        assert deposit["amount_usd"] == deposit["balance_delta_usd"]
        assert deposit["sender"].lower() != FLOWS["agent"]["wallet"].lower()
    assert [deposit["amount_usd"] for deposit in decoded] == [202.23708931, 1001.0862]
    assert [deposit["block_number"] for deposit in decoded] == [105868833, 106851265]
    assert measured["flows"]["external_deposits_usd"] == 1203.32328931
    assert measured["flows"]["external_withdrawals_usd"] == 0.0
    # The selector and the topic are derived from their signatures rather than transcribed.
    assert deposits.TRANSFER_SELECTOR == "0xa9059cbb"
    assert len(deposits.TRANSFER_TOPIC) == 66


def test_the_window_blocks_are_the_chains_own_seconds_and_the_neighbours_do_not_move_them():
    """Two blocks were picked out of two million and the figures rest on them, so neither may
    be a choice. Each carries the whole second one of the receipt chain's own endpoint
    receipts records — and because BSC produces more than one block a second here, the block
    either side of each is read too and has to give the same dollar-pegged balance."""
    measured = deposits.measure(FLOWS, CHAIN)
    window = measured["window"]
    evidence = measured["evidence"]

    assert window["open_block"] == 104992551
    assert window["close_block"] == 106969455
    assert window["opening_block_is_the_first_receipts_own_second"] is True
    assert window["closing_block_is_the_last_receipts_own_second"] is True
    assert window["first_receipt_ts"] == RECEIPTS[0]["ts"]
    assert window["last_receipt_ts"] == RECEIPTS[-1]["ts"]
    assert evidence["boundary_blocks_are_insensitive_to_the_neighbouring_block"] is True
    assert evidence["wallet_is_an_externally_owned_account"] is True
    assert [
        reading["stables_usd"] for reading in evidence["adjacent_block_readings"]
    ] == [
        45.4741981332,
        45.4741981332,
        1224.6128995729,
        1224.6128995729,
    ]


def test_the_headline_is_a_loss_and_every_term_of_it_is_read_from_a_pinned_block(
    experiment,
):
    """The subtraction, redone from the corpus's own hex words. Three terms and a result, each
    with the block it was read at, so a reader can check any of them without this record."""
    result = experiment["measurement"]["result"]
    scale = Decimal(10) ** 18
    opening = (
        Decimal(int(READINGS["window_open"]["balance_of"]["USDT"], 16))
        + Decimal(int(READINGS["window_open"]["balance_of"]["USDC"], 16))
    ) / scale
    closing = (
        Decimal(int(READINGS["window_close"]["balance_of"]["USDT"], 16))
        + Decimal(int(READINGS["window_close"]["balance_of"]["USDC"], 16))
    ) / scale
    paid_in = Decimal("202.23708931") + Decimal("1001.0862")

    assert result["opening_stables_usd"] == round(float(opening), 10)
    assert result["closing_stables_usd"] == round(float(closing), 10)
    assert result["external_deposits_usd"] == round(float(paid_in), 10)
    assert result["balance_change_usd"] == round(float(closing - opening), 10)
    assert result["deposit_adjusted_pnl_usd"] == round(
        float(closing - opening - paid_in), 10
    )
    assert result["deposit_adjusted_pnl_usd"] == -24.1845878704
    assert result["is_a_loss"] is True
    assert experiment["deposit_adjusted"]["published"] is True
    assert experiment["deposit_adjusted"]["is_a_loss"] is True


def test_both_percentages_carry_the_two_counts_they_were_computed_from(experiment):
    """One numerator, two denominators, and neither is served without its counts. The
    Modified Dietz weights are re-derived here from the block timestamps rather than read, and
    the figure is mark-free because the opening basket holds no ETH and the closing holds
    dust."""
    result = experiment["measurement"]["result"]
    dietz = result["modified_dietz"]
    opened = int(READINGS["window_open"]["block_timestamp"], 16)
    closed = int(READINGS["window_close"]["block_timestamp"], 16)
    span = Decimal(closed - opened)
    first = (
        Decimal(closed - int(READINGS["at_first_deposit"]["block_timestamp"], 16))
        / span
    )
    second = (
        Decimal(closed - int(READINGS["at_second_deposit"]["block_timestamp"], 16))
        / span
    )
    denominator = (
        Decimal("45.4741981332")
        + first * Decimal("202.23708931")
        + second * Decimal("1001.0862")
    )

    assert dietz["window_seconds"] == closed - opened == 890067
    assert [flow["weight"] for flow in dietz["weighted_flows"]] == [
        round(float(first), 10),
        round(float(second), 10),
    ]
    assert dietz["average_capital_usd"] == round(float(denominator), 10)
    assert dietz["return"] == {
        "numerator": -24.1845878704,
        "denominator": 217.880669017,
        "value": -24.1845878704 / 217.880669017,
    }
    assert round(dietz["return"]["value"] * 100, 2) == -11.10
    contributed = result["over_the_opening_balance_and_the_deposits"]
    assert contributed["numerator"] == -24.1845878704
    assert contributed["denominator"] == 1248.7974874432
    assert round(contributed["value"] * 100, 2) == -1.94
    # The opening basket holds no ETH at all and the closing basket holds dust, which is what
    # makes both of these exact without a price for anything.
    readings = {
        reading["label"]: reading
        for reading in experiment["measurement"]["evidence"]["balance_readings"]
    }
    assert readings["window_open"]["eth"] == 0.0
    assert readings["window_close"]["eth"] < 1e-6


def test_the_time_weighted_return_is_a_table_and_its_spread_does_not_settle_the_sign(
    experiment,
):
    """The one figure this window cannot supply. At the second deposit the account held ETH
    and no balanceOf prices it, so the return is served over a grid of marks — and the grid
    crosses zero, which is why no row of it is offered as the answer."""
    grid = experiment["measurement"]["time_weighted"]
    readings = {
        reading["label"]: reading
        for reading in experiment["measurement"]["evidence"]["balance_readings"]
    }

    assert grid["published_as_a_point_figure"] is False
    assert grid["eth_marks_usd"] == [1400, 1500, 1600, 1700, 1800]
    assert len(grid["rows"]) == 5
    assert grid["spread"]["crosses_zero"] is True
    assert grid["spread"]["lowest"] < -0.15 < 0.01 < grid["spread"]["highest"]
    assert all(len(row["sub_periods"]) == 3 for row in grid["rows"])
    # The boundary that needs the mark, and the two that do not.
    assert readings["before_second_deposit"]["eth"] > 0.1
    assert readings["at_second_deposit"]["eth"] > 0.1
    assert readings["before_first_deposit"]["eth"] == 0.0
    assert "did not price" in experiment["deposit_adjusted"]["time_weighted"] or (
        "no price source" in experiment["deposit_adjusted"]["time_weighted"]
    )


def test_the_loss_is_the_wallets_and_the_attribution_gap_is_counted_not_asserted(
    experiment,
):
    """The disclosure this record is dishonest without. The transaction count is the wallet's
    own and the hash set is the chain's own, so the gap between them is a measurement here —
    and the owner's sweep, which is sharper and is not this repository's, travels attributed
    beside it rather than folded in as though it had been reproduced."""
    attributed = experiment["measurement"]["attribution"]
    hashes = {
        (receipt["execution_seal"] or {}).get("tx_hash", "").lower()
        for receipt in RECEIPTS
        if (receipt["execution_seal"] or {}).get("tx_hash")
    }

    assert attributed["transaction_count_at_the_opening_block"] == 12
    assert attributed["transaction_count_at_the_closing_block"] == 125
    assert attributed["transactions_the_wallet_sent"] == 113
    assert attributed["distinct_tx_hashes_the_chain_names"] == len(hashes) == 37
    assert attributed["wallet_transactions_the_chain_names_no_hash_for"] == {
        "numerator": 76,
        "denominator": 113,
        "value": 76 / 113,
    }
    assert attributed["provably_the_agents"] is False
    assert attributed["owner_sweep"]["value_moving_transactions_found"] == 44
    assert attributed["owner_sweep"]["absent_from_the_chains_executions"] == 16
    assert attributed["owner_sweep"]["reproduced_by_this_module"] is False
    # Neither of the two largest absent transactions is anywhere in the chain, checked here.
    assert [
        entry["prefix"] for entry in attributed["the_two_largest_absent_transactions"]
    ] == [
        "0x07f88b70",
        "0xe4fd127c",
    ]
    for entry in attributed["the_two_largest_absent_transactions"]:
        assert entry["matches_a_hash_the_chain_names"] == []
    assert "not provably the agent's" in attributed["statement"]
    assert "cannot distinguish" in attributed["statement"]


def test_gas_is_excluded_in_one_direction_and_the_chain_could_not_have_carried_it(
    experiment,
):
    """The second disclosure. The exclusion has a direction — every fee made the account
    smaller — so the published loss is a floor, and saying so is the difference between an
    omission and a bound. The search for a native-coin field is run over the chain's own key
    paths rather than asserted, because the falsifier's fourth limb turns on its result."""
    gas = experiment["measurement"]["gas"]

    assert gas["key_paths_matching"] == []
    assert gas["the_chain_could_have_carried_the_fees"] is False
    assert gas["transactions_the_wallet_sent"] == 113
    # None of the 113 is on this record: the two transactions it carries are the deposits,
    # which other addresses sent, so their fees were not paid by this account.
    assert gas["wallet_transaction_hashes_on_this_record"] == 0
    assert gas["wallet_transaction_hashes_the_chain_names"] == 37
    assert "holds none of their hashes" in gas["statement"]
    assert "floor and not an estimate" in gas["statement"]
    # The one recorded cost the chain does carry, and what it would do to the result.
    assert gas["recorded_data_purchases"] == 980
    assert gas["recorded_data_purchase_cost_usdc"] == 5.0
    assert (
        gas["result_if_every_recorded_purchase_left_this_wallet_usd"] == -19.1845878704
    )
    assert gas["result_if_every_recorded_purchase_left_this_wallet_usd"] < 0


def test_both_nulls_are_computed_over_the_same_readings_and_the_margin_is_served(
    experiment,
):
    """Doing nothing is the arm a trading record has to be measured against, and it returns
    exactly zero here because every boundary and both flows are dollar-pegged. The other null
    is the free reading, and it is wrong by exactly the money that was paid in."""
    nulls = experiment["measurement"]["nulls"]
    headline = experiment["headline"]
    served = {null["name"]: null["figure"] for null in headline["nulls"]}

    assert nulls["hold_the_stables"]["result_usd"] == 0.0
    assert nulls["hold_the_stables"]["transactions_sent"] == 0
    assert nulls["hold_the_stables"]["closing_stables_usd"] == 1248.7974874432
    assert (
        nulls["count_the_balance_change_as_the_result"]["result_usd"] == 1179.1387014396
    )
    assert (
        nulls["count_the_balance_change_as_the_result"]["result_usd"]
        - experiment["measurement"]["result"]["deposit_adjusted_pnl_usd"]
        == 1203.32328931
    )
    assert set(served) == {"count_the_balance_change_as_the_result", "hold_the_stables"}
    assert served["hold_the_stables"]["usd"] == 0.0
    assert headline["margin"]["value"] == -24.1845878704
    assert "leaving the money alone" in headline["margin"]["statement"]


def test_the_falsifier_is_evaluated_clause_by_clause_and_none_of_its_limbs_fired(
    experiment,
):
    """Surviving is not a result in the agent's favour here either. The claim is the loss, so
    a falsifier that does not fire leaves the loss standing."""
    result = experiment["falsifier_result"]
    clauses = {check["clause"]: check for check in result["checks"]}

    assert set(clauses) == {
        "the_evidence_does_not_recompute",
        "the_deposit_adjusted_result_is_not_a_loss",
        "the_chain_names_every_transaction_the_wallet_sent",
        "a_receipt_carries_the_native_coin_or_its_fee",
    }
    assert result["refuted"] is False
    for clause, check in clauses.items():
        assert check["refuted"] is False, clause
        assert check["observed"].strip(), clause
    assert (
        "-24.184588" in clauses["the_deposit_adjusted_result_is_not_a_loss"]["observed"]
    )
    assert (
        "113"
        in clauses["the_chain_names_every_transaction_the_wallet_sent"]["observed"]
    )


def test_no_naive_unadjusted_return_is_emitted_anywhere_in_the_record_or_the_page(
    experiment, detail
):
    """The regression this experiment inherits from 06 and has to carry harder, because this
    is the record that publishes percentages. Dividing the closing dollar-pegged balance by
    the opening one gives +2592.98%, and dividing the last equity reading by the first gives
    +2558.36%; both are the deposits, not a return, and neither may be served in any form.

    Walked as numbers rather than searched as text, because the digits of a percentage are
    also the digits of a block number — and the rendered page is searched for the printed
    forms as well, since a figure a reader can read off the screen is a figure they will
    quote."""
    forbidden = [
        float(ratio) * multiplier - offset
        for ratio in (NAIVE_STABLES_RATIO, NAIVE_EQUITY_RATIO)
        for multiplier, offset in ((1, 0), (1, 1), (100, 0), (100, 100))
    ]

    for path, value in numbers(experiment):
        for banned in forbidden:
            assert abs(value - banned) > 1e-6, f"{path} serves {value}"
    for printed in (
        "2592.98",
        "2,592.98",
        "2558.36",
        "2,558.36",
        "2564.93",
        "2,564.93",
    ):
        assert printed not in detail, printed
    # What is served instead, and both of them are negative.
    assert experiment["measurement"]["result"]["deposit_adjusted_pnl_usd"] < 0
    assert experiment["measurement"]["result"]["modified_dietz"]["return"]["value"] < 0
    assert (
        experiment["measurement"]["result"][
            "over_the_opening_balance_and_the_deposits"
        ]["value"]
        < 0
    )


def test_this_record_adds_to_06_and_neither_refutes_nor_amends_it(experiment):
    """06's funding limb is about the fields inside 06's own corpus, and a wallet's
    transactions on BSC are not one of them. So this record is an addition and 06's claim and
    falsifier are the bytes they were: the digest its own run cites is asserted here, from
    this file, so an edit to either would show up as a mismatch rather than as prose."""
    solvent_spec = load(SOLVENT_SPEC_PATH)
    solvent_run = json.loads(
        (ROOT / "docket/advantage/v2/runs/06-solvent-record.json").read_text(
            encoding="utf-8"
        )
    )

    assert RUN["cross_reference"]["experiment_id"] == "06-solvent-record"
    assert RUN["cross_reference"]["refutes_06"] is False
    assert "This evidence is outside it" in RUN["cross_reference"]["statement"]
    assert solvent_run["spec_hash"] == solvent_spec.spec_hash
    assert "no receipt carries a funding field" in solvent_spec.claim
    assert "the funding limb is refuted" in solvent_spec.falsifier
    # 06 now points a reader at this record for the figure it declines to compute, and still
    # declines to compute it.
    statement = solvent_run["equity"]["no_return_published"]
    assert "07-solvent-deposit-adjusted" in statement
    assert (
        "A first-to-last reading of equity_usd is therefore not a return" in statement
    )
    assert "refutes nothing here" in statement


def test_the_page_carries_every_reading_the_subtraction_used(experiment, detail):
    """An aggregate a reader cannot open is a number they can only believe. Every block the
    account was read at is on the page with its balances, both deposits are there with their
    senders, and so are the three sentences the headline must not be quoted without."""
    measured = experiment["measurement"]

    for reading in measured["evidence"]["balance_readings"]:
        assert f">{reading['block_number']}</th>" in detail, reading["label"]
    for deposit in measured["flows"]["deposits"]:
        assert deposit["tx_hash"] in detail, deposit["tx_hash"]
        assert deposit["sender"] in detail, deposit["sender"]
    assert "45.474198" in detail
    assert "1,224.612900" in detail
    assert "1,203.323289" in detail
    assert "24.184588" in detail
    assert "12 of 12" in detail
    # The page escapes what it renders, so each disclosure is asserted through a fragment that
    # survives escaping rather than through the raw sentence.
    assert "transaction count advanced from 12 at the opening block to 125" in detail
    assert "at least 76 of the 113 appear nowhere in the record the agent published" in detail
    assert "floor and not an estimate" in detail
    assert "owner-attested and this module does not reproduce the sweep behind it" in detail
    assert "No time-weighted return is published as a figure" in detail
    assert "adds a figure beside 06 and refutes nothing in it" in detail
    assert "not provably the agent" in experiment["run"]["notice"]


def test_the_committed_record_says_what_the_report_recomputes(experiment):
    """The record on disk and the figures served are two statements of the same arithmetic.
    They are computed by the same module from the same corpora, so the only way they part is
    if one of them was edited by hand — which is exactly what this catches."""
    measured = experiment["measurement"]

    for section in (
        "window",
        "evidence",
        "flows",
        "result",
        "time_weighted",
        "attribution",
        "gas",
        "nulls",
    ):
        assert RUN[section] == measured[section], section
    assert RUN["readings_sha256"] == FLOWS["readings_sha256"]
    assert RUN["fetched_at"] == FLOWS["fetched_at"]
    assert RUN["endpoint"] == FLOWS["endpoint"]
    assert (
        RUN["receipt_chain_ref"]
        == "docket/advantage/v2/corpus/trading/solvent-receipts.json"
    )


def test_the_registration_is_served_as_self_attested_once_it_is_in_history(experiment):
    """The specification and the completed run first entered git together at b2411b3, so this is self-attested like 01 and 03 and not git-provable: git records
    that both existed at that commit, and nothing about their order. The producer is
    committed, so the run can be regenerated from the spec and the frozen corpus."""
    provenance = experiment["registration_provenance"]

    assert provenance["state"] == "self_attested"
    assert provenance["spec_commit"] == "b2411b3"
    assert provenance["run_commit"] == "b2411b3"
    assert provenance["spec_precedes_run"] is False
    assert provenance["committed_run_producer"] == {
        "present": True,
        "path": "docket/advantage/v2/deposits.py",
    }
    assert f"first entered git together at b2411b3" in provenance["statement"]
    assert "not on independent git history" in provenance["statement"]
