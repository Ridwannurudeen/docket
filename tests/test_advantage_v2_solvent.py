"""The trading record: what has to hold for it to be evidence, and what it must never become.

Docket published no trading record at all until this experiment. The one it publishes now is
somebody else's chain, and a chain is only evidence in as much as a reader can recompute it,
so the first thing guarded here is the recomputation itself — both limbs, over all 384
receipts, with the recipe pinned. The recipe is the part that could have gone quietly wrong:
it differs from this repository's own receipt digest in one argument, the two agree on every
receipt whose body is pure ASCII, and a verifier that guessed wrong reports a chain that
verifies almost everywhere. So the count of receipts the two recipes disagree on is asserted
by number, not just the count that verified.

The second thing guarded is the arithmetic that decides what the chain establishes. Three
fields say a seal executed — the agent's `outcome`, the chain's `verification.status`, and
`applies_state_change` — and three counts of 27 are not evidence that they name the same 27
seals. That is asserted as set equality, because a reliability figure assembled from three
fields that quietly disagree is a figure nobody can act on.

The third is a regression, and it is the reason this file is stricter than the others. The
raw equity series in this chain runs from 45.97 to 1222.05, and dividing one by the other
gives a figure this chain does not support in either direction: it contains at least three
steps larger than any trade recorded in it, and one reading of 0.0 between two identical
non-zero readings. No such quotient may ever appear in the served payload or on the page. The
check walks every numeric leaf rather than searching for a string, because the digits of a
percentage are also the digits of a transaction hash, and it walks the key names as well,
because a figure named `roi` is a return whatever it was computed from.

Nothing here touches a network. Every test reads the frozen corpus, the registered spec, the
committed run and one committed v1 artifact, all of them files in this repository.
"""

import hashlib
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from docket.advantage.v2 import solvent
from docket.advantage.v2.spec import load
from docket.api import create_app
from docket.store import Store

ROOT = Path(__file__).resolve().parents[1]
CORPUS_PATH = ROOT / "docket/advantage/v2/corpus/trading/solvent-receipts.json"
SPEC_PATH = ROOT / "docket/advantage/v2/specs/06-solvent-record.json"
RUN_PATH = ROOT / "docket/advantage/v2/runs/06-solvent-record.json"
V1_TRADING_PATH = ROOT / "docket/advantage/experiments/02-trading.json"

CORPUS = json.loads(CORPUS_PATH.read_text(encoding="utf-8"))
RUN = json.loads(RUN_PATH.read_text(encoding="utf-8"))
V1_TRADING = json.loads(V1_TRADING_PATH.read_text(encoding="utf-8"))
ENVELOPES = CORPUS["receipts"]
RECEIPTS = [envelope["receipt"] for envelope in ENVELOPES]

# What a reader gets by dividing the last equity reading by the first. It is not a return and
# it is not served; it is computed here only so that nothing else can serve it.
NAIVE_RATIO = RECEIPTS[-1]["equity_usd"] / RECEIPTS[0]["equity_usd"]
# A key carrying one of these over a number would be a return figure whatever produced it.
# The two disclosure keys are prose rather than figures — `no_return` and
# `no_return_published` are the sentence saying why there is none — so the word check runs
# over numeric leaves, and the second list runs over every key at any depth.
RETURN_WORDS = (
    "return",
    "roi",
    "pnl",
    "profit",
    "win_rate",
    "winrate",
    "drawdown",
    "yield",
)
RETURN_FIGURE_NAMES = frozenset(
    {"roi", "pnl", "win_rate", "winrate", "total_return", "return_pct", "drawdown"}
)
# `take_profit` is one of the five kinds SOLVENT names its own intents with, and a count of
# the seals carrying that kind is a count of seals. The word check stays broad and this is
# the one name exempted from it, by name rather than by loosening the list.
NOT_A_RETURN_FIGURE = frozenset({"take_profit"})


@pytest.fixture
def client(tmp_path):
    db = tmp_path / "solvent.sqlite3"
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
        if item["experiment_id"] == "06-solvent-record"
    )


@pytest.fixture
def detail(client):
    resp = client.get(
        "/advantage/v2/06-solvent-record", headers={"accept": "text/html"}
    )
    assert resp.status_code == 200
    return resp.text


def numbers(node, path="") -> list[tuple[str, float]]:
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


def keys(node, path="") -> list[str]:
    found = []
    if isinstance(node, dict):
        for key, value in node.items():
            found.append(f"{path}/{key}")
            found += keys(value, f"{path}/{key}")
    elif isinstance(node, list):
        for index, value in enumerate(node):
            found += keys(value, f"{path}[{index}]")
    return found


def test_the_corpus_is_the_whole_chain_and_says_how_it_was_asked_for():
    """The query string is part of the citation. A bare /receipts returns the newest 250 and
    says nothing about it, so a reader who drops the limit recomputes a shorter chain that
    still links internally and still verifies — the one failure mode a hash chain cannot
    signal. The digest of the response body travels beside the digest of this file because
    they are different bytes and both are worth being able to check."""
    seqs = [receipt["seq"] for receipt in RECEIPTS]

    assert CORPUS["receipts_url"] == "https://solvent.gudman.xyz/receipts?limit=500"
    assert "?limit=" in CORPUS["provenance"]
    assert "newest 250" in CORPUS["provenance"]
    assert seqs == list(range(384))
    assert CORPUS["window"]["first_receipt_ts"] == RECEIPTS[0]["ts"]
    assert CORPUS["window"]["last_receipt_ts"] == RECEIPTS[-1]["ts"]
    assert CORPUS["window"]["n_receipts"] == len(RECEIPTS) == 384
    assert len(CORPUS["receipts_response_sha256"]) == 64


def test_the_registered_spec_carries_the_digest_of_the_corpus_on_disk():
    """`load` re-hashes the spec's own fields on the way in; this asserts the other half,
    that the chain these tests read is the chain the registration was written against."""
    spec = load(SPEC_PATH)
    digest = hashlib.sha256(CORPUS_PATH.read_bytes()).hexdigest()

    assert spec.spec_id == "06-solvent-record"
    assert (
        spec.dataset_ref == "docket/advantage/v2/corpus/trading/solvent-receipts.json"
    )
    assert spec.dataset_sha256 == digest
    assert (ROOT / spec.dataset_ref).resolve() == CORPUS_PATH.resolve()
    assert spec.n_planned == 384
    assert RUN["spec_hash"] == spec.spec_hash
    assert RUN["spec_id"] == spec.spec_id
    assert RUN["dataset_sha256"] == digest


def test_the_spec_registers_both_nulls_and_a_falsifier_with_the_claims_own_thresholds():
    """A claim saying "fewer than half" against a falsifier firing at "a majority" leaves a
    band where the claim is false and survives anyway. The two numbers are pinned together
    here so neither can be loosened alone."""
    spec = load(SPEC_PATH)
    names = [baseline["name"] for baseline in spec.null_baselines]

    assert names == ["count_every_seal_as_a_trade", "count_only_anchored_seals"]
    assert "fewer than half of its pre-trade commitments" in spec.claim
    assert "fewer than a tenth of its" in spec.claim
    assert "|confirmed| / |P| >= 0.5" in spec.falsifier
    assert "|anchored| / |S| >= 0.1" in spec.falsifier
    assert "no receipt carries a funding field" in spec.claim
    # The registration says outright that it was written knowing its own headline counts.
    assert "docs/plans/2026-09-02-final-week.md" in spec.stopping_rule
    assert "does not pretend to have been" in spec.stopping_rule


def test_the_hash_chain_verifies_end_to_end_under_the_registered_recipe():
    """Both limbs, recomputed here from the committed corpus rather than read off the record.
    Content catches a body edited after it was hashed; linkage catches a receipt moved,
    inserted or dropped. Only both together say the chain is what it says it is."""
    measured = solvent.verify_chain(ENVELOPES)

    assert measured["content_hashes_recomputed"] == {
        "numerator": 384,
        "denominator": 384,
        "value": 1.0,
    }
    assert measured["linkage_recomputed"] == {
        "numerator": 383,
        "denominator": 383,
        "value": 1.0,
    }
    assert measured["content_failures"] == []
    assert measured["linkage_failures"] == []
    assert measured["genesis_prev_hash"] == solvent.ZERO_HASH
    assert measured["genesis_prev_hash_is_the_zero_word"] is True
    assert measured["verifies"] is True
    assert measured["head_seq"] == 383
    # The head this corpus computes is the head v1's manual arm read on 2026-08-08.
    assert (
        measured["head_hash"]
        == V1_TRADING["manual_arm"]["output"]["recomputed_head_hash"]
    )


def test_the_recipe_is_pinned_where_the_two_candidates_can_actually_disagree():
    """The recipe differs from this repository's own receipt digest in `ensure_ascii` alone,
    so the two agree on every pure-ASCII receipt and can only part on the rest. 57 of 384 is
    where the recipe was decided, and a verifier that had guessed the other one would have
    reported 327 of 384 — a chain that verifies almost everywhere, which is the worst thing a
    verifier can report. Both counts are asserted so neither can drift into the other."""
    from docket.hire.receipts import canonical_hash

    measured = solvent.verify_chain(ENVELOPES)
    disagreeing = [
        envelope["receipt"]["seq"]
        for envelope in ENVELOPES
        if canonical_hash(envelope["receipt"]) != envelope["hash"]
    ]

    assert measured["receipts_the_two_recipes_disagree_on"] == 57
    assert measured["ascii_insensitive_recipe_agrees"] == {
        "numerator": 327,
        "denominator": 384,
        "value": 327 / 384,
    }
    assert len(disagreeing) == 57
    assert all(
        solvent.receipt_hash(envelope["receipt"]) == envelope["hash"]
        for envelope in ENVELOPES
    )
    assert "ensure_ascii=True" in solvent.RECEIPT_HASH_RECIPE


def test_the_verified_prefix_matches_the_anchor_value_read_on_chain_in_august():
    """The chain can be internally consistent and still be one nobody else ever saw. This is
    the one check it cannot make for itself: Docket's v1 task 02 read the anchor transaction
    on chain on 2026-08-08, 25 days before this corpus was fetched, and its metadata value is
    the chain head at seq 381. The transaction itself was mined on 2026-06-28. That committed record and this corpus are independent, so
    the corpus cannot have been written to satisfy it."""
    manual = V1_TRADING["manual_arm"]["output"]
    cross = solvent.anchor_cross_check(ENVELOPES, V1_TRADING)
    by_seq = {envelope["receipt"]["seq"]: envelope["hash"] for envelope in ENVELOPES}

    assert cross["anchored_seq"] == 381
    assert cross["anchored_hash_matches_this_corpus"] is True
    assert cross["head_hash_matches_this_corpus"] is True
    assert cross["receipts_past_the_anchor"] == [382, 383]
    # The value in the transaction, as v1 read it off the explorer: bare uppercase hex.
    assert (
        by_seq[381].removeprefix("0x").upper() == manual["anchor_tx"]["metadata_value"]
    )
    assert manual["anchor_tx"]["status"] == "Success"
    assert "no transaction fixes when they were written" in cross["statement"]


def test_the_three_fields_that_say_a_seal_executed_name_the_same_seals():
    """Three counts of 27 are not evidence that three fields agree about which 27. If the
    agent's own outcome, the chain's confirmation and the state-change flag ever named
    different sets, every reliability figure assembled from them would be unreadable and
    nothing else here would notice."""
    seals = [r for r in RECEIPTS if r["phase"] == "execution_seal"]
    by_outcome = {
        r["seq"] for r in seals if r["execution_seal"].get("outcome") == "executed_now"
    }
    by_status = {
        r["seq"]
        for r in seals
        if (r["execution_seal"].get("verification") or {}).get("status") == 1
    }
    by_state_change = {
        r["seq"]
        for r in seals
        if r["execution_seal"].get("applies_state_change") is True
    }
    confirmed = {r["seq"] for r in seals if solvent.is_confirmed_execution(r)}
    tx_hashes = [
        r["execution_seal"]["tx_hash"]
        for r in seals
        if r["execution_seal"].get("tx_hash")
    ]

    assert len(seals) == 51
    assert by_outcome == by_status == by_state_change == confirmed
    assert len(confirmed) == 27
    assert len(tx_hashes) == 37
    assert len(set(tx_hashes)) == 37


def test_every_published_figure_carries_the_denominator_it_was_computed_over(
    experiment,
):
    """Each headline count, by both denominators a reader might mean. A share of seals and a
    share of stated intentions answer different questions and the record serves both."""
    measured = experiment["measurement"]
    execution = measured["execution"]

    assert measured["phases"] == {
        "cycle_summary": 278,
        "pre_trade_commit": 55,
        "execution_seal": 51,
        "n_receipts": 384,
        "phases_partition_the_chain": True,
    }
    assert execution["confirmed_over_seals"] == {
        "numerator": 27,
        "denominator": 51,
        "value": 27 / 51,
    }
    assert execution["confirmed_over_commitments"] == {
        "numerator": 27,
        "denominator": 55,
        "value": 27 / 55,
    }
    assert execution["outcomes"] == {
        "executed_now": 27,
        "unresolved": 22,
        "failed": 1,
        "no_outcome_recorded": 1,
    }
    assert sum(execution["outcomes"].values()) == 51
    assert execution["seals_with_a_tx_hash"] == {
        "numerator": 37,
        "denominator": 51,
        "value": 37 / 51,
    }
    assert execution["seals_with_a_tx_hash_and_no_confirmation"] == {
        "numerator": 10,
        "denominator": 51,
        "value": 10 / 51,
    }
    assert execution["seals_with_a_pre_trade_anchor"] == {
        "numerator": 1,
        "denominator": 51,
        "value": 1 / 51,
    }
    assert measured["nulls"]["count_every_seal_as_a_trade"] == {
        "numerator": 51,
        "denominator": 51,
        "value": 1.0,
    }
    assert measured["nulls"]["count_only_anchored_seals"] == {
        "numerator": 1,
        "denominator": 51,
        "value": 1 / 51,
    }
    assert measured["regime"] == {
        "risk-off": 383,
        "qualification": 1,
        "n_receipts": 384,
    }
    assert measured["commitment_binding"][
        "seals_bound_to_a_commitment_in_the_chain"
    ] == {"numerator": 51, "denominator": 51, "value": 1.0}
    assert measured["commitment_binding"]["commitments_never_sealed"] == [
        30,
        31,
        32,
        33,
    ]
    assert measured["commitment_binding"]["binding_is_on_chain"] is False


def test_sizing_is_parsed_from_the_intent_key_and_agrees_with_the_intent_beside_it(
    experiment,
):
    """Two independent statements of the same number: the notional in the key, and the
    notional in the intents block. They are cross-checked rather than one being trusted, and
    the confirmed trades turn out to be the small ones — the median confirmed notional is two
    dollars against ninety-two across all seals, because the seals that did not confirm are
    the larger exits."""
    sizing = experiment["measurement"]["sizing"]

    assert sizing["intent_keys_that_did_not_parse"] == []
    assert sizing["seqs_where_the_key_and_the_intent_disagree"] == []
    assert sizing["over_all_seals"]["n"] == 51
    assert sizing["over_confirmed_executions"]["n"] == 27
    assert sizing["over_confirmed_executions"]["median"] == 2.0
    assert sizing["over_all_seals"]["median"] == 92.66
    assert sizing["largest_intent_notional_usd"] == 99.75
    assert sizing["kind_over_all_seals"] == {
        "qualify": 18,
        "enter": 10,
        "exit": 19,
        "deleverage": 1,
        "take_profit": 3,
    }
    assert sizing["kind_over_confirmed_executions"] == {
        "qualify": 15,
        "enter": 6,
        "exit": 5,
        "deleverage": 1,
    }
    assert sum(sizing["kind_over_all_seals"].values()) == 51
    assert sum(sizing["kind_over_confirmed_executions"].values()) == 27


def test_the_zero_equity_reading_is_disclosed_as_a_read_failure_and_excluded(
    experiment,
):
    """One receipt reads 0.0 between two readings of 45.85. Treating that as a wipeout would
    invent a drawdown; deleting it would hide a defect in the series. It is named, its
    neighbours are named, and it is excluded from the step series with the exclusion
    stated."""
    equity = experiment["measurement"]["equity"]

    assert equity["read_failures"] == [
        {
            "seq": 31,
            "ts": "2026-06-19T20:30:02.982701+00:00",
            "equity_usd": 0.0,
            "previous_equity_usd": 45.85,
            "next_equity_usd": 45.85,
        }
    ]
    assert equity["n_steps_considered"] == 381
    assert all(
        31 not in (step["from_seq"], step["to_seq"]) for step in equity["largest_steps"]
    )
    assert (
        "0.0 between two identical non-zero readings" in equity["no_return_published"]
    )


def test_the_steps_no_trade_explains_are_published_with_the_bound_that_found_them(
    experiment,
):
    """The bound is the chain's own largest intended notional, so it is a property of the
    data and not a threshold chosen to produce three hits. What the rule finds is steps no
    single recorded trade explains; it does not say which were deposits, and two of the three
    sit beside a near-cancelling step of the opposite sign, which is what a failed read looks
    like."""
    equity = experiment["measurement"]["equity"]
    unexplained = equity["steps_no_recorded_trade_explains"]

    assert equity["notional_bound_usd"] == 99.75
    assert [step["step_usd"] for step in unexplained] == [201.74, 100.09, 997.87]
    assert [step["to_seq"] for step in unexplained] == [134, 225, 363]
    assert all(abs(step["step_usd"]) > 99.75 for step in unexplained)
    opposing = {step["step_usd"] for step in equity["largest_steps"]}
    assert -99.33 in opposing and -93.16 in opposing


def test_the_funding_limb_reads_each_candidate_rather_than_matching_a_word(experiment):
    """A word list cannot decide whether a field records money moving. `btc_funding_rate` is
    the rate perpetual longs pay shorts — a market observation this agent bought, on an
    instrument it never held. So the list narrows 324 key paths to two, both are read out on
    the record, and a candidate this module has no reading for would fire the limb rather
    than pass silently."""
    funding = experiment["measurement"]["equity"]["funding_fields"]

    assert funding["candidates"] == [
        "inference_proof.input.signals.btc_funding_rate",
        "signals.btc_funding_rate",
    ]
    assert set(funding["readings"]) == set(funding["candidates"])
    assert funding["unread_candidates"] == []
    assert funding["fields_recording_money_into_or_out_of_the_account"] == []
    assert "deposit" in funding["words_searched"]
    assert "withdraw" in funding["words_searched"]
    assert len(experiment["measurement"]["equity"]["key_paths"]) == 324
    assert solvent.funding_fields(["balance.deposit_usd"])["unread_candidates"] == [
        "balance.deposit_usd"
    ]


def test_the_falsifier_is_evaluated_clause_by_clause_and_none_of_its_limbs_fired(
    experiment,
):
    """Surviving is not a result in the agent's favour here. The claim is written as the
    unflattering statement, so a falsifier that does not fire means the unflattering
    statement stands — and the registration says so in those words."""
    result = experiment["falsifier_result"]
    clauses = {check["clause"]: check for check in result["checks"]}

    assert set(clauses) == {
        "hash_chain_does_not_verify",
        "confirmed_executions_reach_half_the_commitments",
        "anchored_seals_reach_a_tenth_of_the_seals",
        "a_receipt_carries_a_funding_field",
    }
    assert result["refuted"] is False
    for clause, check in clauses.items():
        assert check["refuted"] is False, clause
        assert check["observed"].strip(), clause
    assert (
        "27 of 55"
        in clauses["confirmed_executions_reach_half_the_commitments"]["observed"]
    )
    assert "1 of 51" in clauses["anchored_seals_reach_a_tenth_of_the_seals"]["observed"]


def test_no_unadjusted_return_figure_is_emitted_anywhere_in_the_record_or_the_page(
    experiment, detail
):
    """The regression this experiment exists to hold. The raw series runs from 45.97 to
    1222.05 and the quotient is a funding artifact: the chain holds three steps larger than
    any trade in it and one failed balance read, so no return, percentage or win rate may be
    served from it in any direction.

    Walked as numbers rather than searched as text, because the digits of a percentage are
    also the digits of a transaction hash — and walked as key names too, because a field
    called `roi` is a return whatever produced it."""
    forbidden = (
        NAIVE_RATIO,
        NAIVE_RATIO * 100,
        NAIVE_RATIO - 1,
        (NAIVE_RATIO - 1) * 100,
    )

    for path, value in numbers(experiment):
        for banned in forbidden:
            assert abs(value - banned) > 1e-6, f"{path} serves {value}"
        leaf = path.rsplit("/", 1)[-1].casefold()
        if leaf in NOT_A_RETURN_FIGURE:
            continue
        assert not any(word in leaf for word in RETURN_WORDS), path
    for path in keys(experiment):
        assert path.rsplit("/", 1)[-1].casefold() not in RETURN_FIGURE_NAMES, path
    assert experiment["no_return"]["published"] is False
    assert "is therefore not a return" in experiment["no_return"]["statement"]
    assert (
        "no receipt carries any field recording money"
        in (experiment["no_return"]["statement"])
    )
    assert experiment["no_return"]["first_equity_reading"]["equity_usd"] == 45.97
    assert experiment["no_return"]["last_equity_reading"]["equity_usd"] == 1222.05
    # The page escapes what it renders, so the sentence is asserted through a fragment that
    # survives escaping rather than through the raw string.
    assert "A first-to-last reading of equity_usd is therefore not a return" in detail
    assert "No return figure is served" in detail


def test_the_page_carries_every_seal_and_the_chain_it_was_recomputed_from(
    experiment, detail
):
    """An aggregate a reader cannot open is a number they can only believe. Every seal is on
    the page with its outcome, and so is the recomputation the integrity claim rests on."""
    measured = experiment["measurement"]

    for seal in measured["seals"]:
        assert f">{seal['seq']}</th>" in detail, seal["seq"]
        if seal["tx_hash"]:
            assert seal["tx_hash"] in detail, seal["seq"]
    assert "384 of 384" in detail
    assert "383 of 383" in detail
    assert "27 of 51" in detail
    assert "27 of 55" in detail
    assert "1 of 51" in detail
    assert "51 of 51" in detail
    assert measured["chain"]["head_hash"] in detail
    assert "sit past the anchor: they link to the anchored prefix by hash" in detail
    assert measured["chain"]["anchor_cross_check"]["anchor_tx_hash"] in detail
    assert experiment["run"]["notice"] in detail
    assert "not a return record" in experiment["run"]["notice"]


def test_the_committed_record_says_what_the_report_recomputes(experiment):
    """The record on disk and the figures served are two statements of the same arithmetic.
    They are computed by the same module from the same corpus, so the only way they part is
    if one of them was edited by hand — which is exactly what this catches."""
    measured = experiment["measurement"]

    for section in (
        "phases",
        "execution",
        "commitment_binding",
        "sizing",
        "regime",
        "nulls",
        "seals",
        "equity",
        "chain",
    ):
        assert RUN[section] == measured[section], section
    assert RUN["receipts_response_sha256"] == CORPUS["receipts_response_sha256"]
    assert RUN["fetched_at"] == CORPUS["fetched_at"]


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
        "path": "docket/advantage/v2/solvent.py",
    }
    assert f"first entered git together at b2411b3" in provenance["statement"]
    assert "not on independent git history" in provenance["statement"]
