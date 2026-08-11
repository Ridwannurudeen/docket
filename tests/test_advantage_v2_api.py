"""What the v2 report must not be able to become once it is served.

v1's report is guarded against drift and against quiet sanitisation, and both guards are
still there and still green. This file guards the four things v2 adds, each of which is a
property that would lapse silently the day nothing checked it.

**v1 is not touched.** The point of a second report is that the first one keeps saying what
it said. `/advantage.json` keeps its exact shape, its page carries no v2 content, and the
link between them runs one way: v2 names v1 as the prior version, and v1 does not know v2
exists.

**Nothing is served as an aggregate alone.** Every trial is in the document and on the page —
including the nine scans that failed, which are shown where they happened rather than
filtered out. An aggregate a reader cannot open is a number they can only believe.

**Every rate keeps its denominator.** The shape is walked recursively rather than spot-checked,
so a rate added later in a corner of the payload is held to it too.

**The falsifiers are evaluated, and one of them fired.** The refutation is the finding this
stage was built to be able to publish, so it is pinned: in the summary, on the page, and in
the experiment that produced it. A later edit that turned it into a survival, or lost it in
the detail, fails here.

And the no-verdict ban, which v1 enforces on its own page and which does not reach a new one
on its own. It is asserted over the whole rendered v2 page, hostile corpus and scan outputs
included.
"""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from docket.advantage.v2 import report, scoring
from docket.advantage.v2.spec import load
from docket.api import create_app
from docket.marketplace.registry import SERVICES
from docket.store import Store

ROOT = Path(__file__).resolve().parents[1]
V2 = ROOT / "docket" / "advantage" / "v2"
WEB = ROOT / "docket" / "api" / "web"
STATIC = ROOT / "docket" / "api" / "static"
EXPERIMENT_IDS = ("01-liquidity-arithmetic", "03-security-corpus", "04-grid-replay")
# The same four words v1's page is held to. They are re-stated rather than imported, because
# the ban has to survive v1's test file being read, moved or retired.
VERDICT_WORDS = ("best", "superior", "proves", "guaranteed")


@pytest.fixture
def client(tmp_path):
    db = tmp_path / "v2.sqlite3"
    store = Store(db)
    snapshot = store.begin_snapshot(chain_id=56, expected=0)
    store.finish_snapshot(snapshot, sampled=0, expected=0)
    return TestClient(create_app(db, snapshot_id=snapshot))


@pytest.fixture
def body(client):
    resp = client.get("/advantage/v2.json")
    assert resp.status_code == 200
    return resp.json()


@pytest.fixture
def page(client):
    resp = client.get("/advantage/v2", headers={"accept": "text/html"})
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/html")
    return resp.text


def rates(node, path="") -> list[tuple[str, dict]]:
    """Every `{numerator, denominator, value}` in the payload, wherever it is nested."""
    found = []
    if isinstance(node, dict):
        if "numerator" in node:
            found.append((path, node))
        for key, value in node.items():
            found += rates(value, f"{path}/{key}")
    elif isinstance(node, list):
        for index, value in enumerate(node):
            found += rates(value, f"{path}[{index}]")
    return found


def test_the_v2_document_carries_every_registration_and_its_whole_run(body):
    """A spec without its run is a promise and a run without its spec is a number. Both
    travel, the run cites the registration's hash, and the citation is checked here rather
    than assumed — a run pointing at a spec that has since been edited would still look
    perfectly well-formed."""
    assert [experiment["experiment_id"] for experiment in body["experiments"]] == list(
        EXPERIMENT_IDS
    )
    for experiment in body["experiments"]:
        spec = load(V2 / "specs" / f"{experiment['experiment_id']}.json")
        assert experiment["spec"] == spec.as_record()
        assert experiment["run"]["spec_hash"] == spec.spec_hash
        assert experiment["run"] == json.loads(
            (V2 / "runs" / f"{experiment['experiment_id']}.json").read_text(encoding="utf-8")
        )
        for field in ("claim", "falsifier", "stopping_rule", "dataset_sha256"):
            assert experiment["spec"][field].strip(), experiment["experiment_id"]
        assert len(experiment["spec"]["null_baselines"]) >= 2


def test_registration_provenance_is_served_per_experiment_and_visible_on_the_page(body, page):
    provenance = {
        experiment["experiment_id"]: experiment["registration_provenance"]
        for experiment in body["experiments"]
    }

    assert {experiment_id: item["state"] for experiment_id, item in provenance.items()} == {
        "01-liquidity-arithmetic": "self_attested",
        "03-security-corpus": "self_attested",
        "04-grid-replay": "git_provable",
    }
    assert provenance["01-liquidity-arithmetic"]["spec_commit"] == "b9578b8"
    assert provenance["01-liquidity-arithmetic"]["run_commit"] == "b9578b8"
    assert provenance["03-security-corpus"]["spec_commit"] == "9042e72"
    assert provenance["03-security-corpus"]["run_commit"] == "9042e72"
    assert provenance["04-grid-replay"]["spec_commit"] == "b47c307"
    assert provenance["04-grid-replay"]["run_commit"] == "9168194"
    assert provenance["04-grid-replay"]["spec_precedes_run"] is True
    assert provenance["01-liquidity-arithmetic"]["committed_run_producer"]["present"] is False
    assert provenance["03-security-corpus"]["committed_run_producer"]["present"] is False
    assert provenance["04-grid-replay"]["committed_run_producer"] == {
        "present": True,
        "path": "docket/advantage/v2/replay.py",
    }
    assert page.count("self_attested") >= 2
    assert "git_provable" in page
    assert "Every experiment here was registered before it was run" not in body["method"]
    assert "Each experiment below was registered before it was run" not in page


def test_every_rate_in_the_document_carries_the_counts_it_came_from(body):
    """Walked rather than spot-checked. A rate is three fields or it is a bare float wearing
    a dict, and a denominator of zero reports null rather than dividing."""
    found = rates(body)

    assert found, "no rates in the document at all"
    for path, rate in found:
        assert "denominator" in rate, path
        assert "value" in rate, path
        if rate["denominator"] == 0:
            assert rate["value"] is None, path
        else:
            assert rate["value"] == rate["numerator"] / rate["denominator"], path


def test_the_nulls_are_served_beside_every_agent_figure_with_a_margin(body):
    """A figure with no null beside it is a figure a reader has to go and contextualise
    themselves, and the margin over the null is the part they would have to compute. Both
    are in the same object as the headline they qualify."""
    for experiment in body["experiments"]:
        headline = experiment["headline"]
        spec_nulls = {baseline["name"] for baseline in experiment["spec"]["null_baselines"]}
        served = {null["name"] for null in headline["nulls"]}

        assert headline["statement"].strip(), experiment["experiment_id"]
        assert served, experiment["experiment_id"]
        assert served <= spec_nulls, experiment["experiment_id"]
        assert headline["margin"]["statement"].strip(), experiment["experiment_id"]


def test_the_security_margin_discloses_its_one_label_sensitivity(body, page):
    """The measured margin is two payloads, but the hardest benign control is contestable.
    Reclassifying that one payload as an attack moves the keyword arm and not the hire, so
    the claim survives by one payload. The corpus remains byte-identical because its digest
    is part of the registration; the sensitivity belongs beside the figure instead."""
    security = next(
        experiment
        for experiment in body["experiments"]
        if experiment["experiment_id"] == "03-security-corpus"
    )
    margin = security["headline"]["margin"]
    nulls = {null["name"]: null for null in security["headline"]["nulls"]}

    assert security["headline"]["figure"]["rate"] == {
        "numerator": 14,
        "denominator": 31,
        "value": 14 / 31,
    }
    assert nulls["keyword_match"]["figure"]["rate"] == {
        "numerator": 12,
        "denominator": 31,
        "value": 12 / 31,
    }
    assert margin["value"] == 2
    assert "2 payloads" in margin["statement"]
    sensitivity = margin["sensitivity"]
    assert sensitivity["payload_id"] == "benign-meeting-note"
    assert sensitivity["reclassification"] == "benign control to ROLE_OVERRIDE attack"
    assert sensitivity["warden_recall"] == {
        "numerator": 14,
        "denominator": 32,
        "value": 14 / 32,
    }
    assert sensitivity["keyword_match_recall"] == {
        "numerator": 13,
        "denominator": 32,
        "value": 13 / 32,
    }
    assert sensitivity["margin_payloads"] == 1
    assert sensitivity["corpus_edited"] is False
    assert "bytes are hashed into the registration" in sensitivity["statement"]
    assert sensitivity["statement"] in page
    assert nulls["flag_everything"]["precision"] == {
        "numerator": 31,
        "denominator": 47,
        "value": 31 / 47,
    }


def test_03_serves_the_post_run_claim_re_registration_disclosure(body, page):
    security = next(
        experiment
        for experiment in body["experiments"]
        if experiment["experiment_id"] == "03-security-corpus"
    )
    changes = security["registration_provenance"]["post_run_re_registrations"]

    assert changes == [
        {
            "field": "claim",
            "commit": "adb352b",
            "timing": "after_run",
            "falsifier_changed": False,
            "spec_hash_citations_changed": 48,
            "observations_changed": False,
            "statement": (
                "The claim was rewritten after the run at adb352b. Its falsifier is "
                "byte-identical to the one that predates the run. The run-record diff "
                "repoints 48 spec_hash citations and changes no observation."
            ),
        }
    ]
    assert changes[0]["statement"] in page


def test_every_falsifier_result_is_computed_and_one_of_them_fired(body):
    """Nothing evaluated these before. Now each is checked clause by clause against the
    measured figures, all three in one shape, and the one that fired is named in the summary
    before a reader reaches the experiment that produced it."""
    results = {
        experiment["experiment_id"]: experiment["falsifier_result"]
        for experiment in body["experiments"]
    }

    for experiment_id, result in results.items():
        assert result["checks"], experiment_id
        assert result["refuted"] == any(check["refuted"] for check in result["checks"])
        for check in result["checks"]:
            assert check["clause"].strip() and check["observed"].strip(), experiment_id
    assert results["04-grid-replay"]["refuted"] is True
    assert results["01-liquidity-arithmetic"]["refuted"] is False
    assert results["03-security-corpus"]["refuted"] is False
    assert body["summary"]["claims_refuted"] == ["04-grid-replay"]
    assert body["summary"]["n_claims_refuted"] == 1
    assert "refuted" in body["summary"]["statement"]


def test_the_replay_is_stated_as_a_replay_everywhere_a_reader_can_land(body, page):
    """It is not a trading record, and a reader who lands on one arm rather than on the
    document has to meet that sentence there too."""
    replay = next(
        experiment
        for experiment in body["experiments"]
        if experiment["experiment_id"] == "04-grid-replay"
    )
    notice = replay["run"]["notice"]

    assert "not a trading record" in notice
    for arm in ("replay", "buy_and_hold", "random_entry"):
        assert replay["run"][arm]["method"].startswith(notice), arm
    assert notice in page
    assert "centralised" in replay["run"]["method"]


def test_the_page_shows_every_run_including_the_ones_that_failed(page, body):
    """Aggregates alone are what this report exists not to be. Every pool row, every payload
    and every trigger is on the page, and the nine failed scans are shown where they happened
    rather than filtered into a footnote."""
    liquidity, security, replay = body["experiments"]

    for pool in liquidity["run"]["pools"]:
        assert pool["pair"] in page, pool["pool"]
    for entry in security["run"]["payloads"]:
        assert entry["arm_name"] in page, entry["arm_name"]
    for trigger in replay["run"]["replay"]["triggers"]:
        assert str(trigger["open_time"]) in page, trigger["level_index"]

    failed = [
        trial
        for entry in security["run"]["payloads"]
        for trial in entry["trials"]
        if trial["error"] is not None
    ]
    assert len(failed) == 9
    assert page.count(">failed</span>") == len(failed)


def test_the_page_carries_the_headline_figures_with_their_denominators(page):
    """The page is rendered from the same payload the JSON serves, so this is not a drift
    check so much as a check that the rendering did not drop the halves of a rate that make
    it readable. A share with no counts in front of it is the number that gets quoted."""
    assert "14 of 31" in page
    assert "12 of 31" in page
    assert "31 of 47" in page
    assert "2 payloads" in page
    assert "0 of 5 buy levels" in page or "0 of 5" in page


def test_the_page_reaches_no_verdict(page):
    """v1's page is held to this and the ban does not reach a second page by itself. It is
    asserted over the whole rendered document — the hostile corpus, the scan outputs and the
    prose alike — because the words would be as much of a claim in a rendered payload as in
    an authored sentence."""
    lowered = page.lower()

    for word in VERDICT_WORDS:
        assert word not in lowered, f"the v2 page reaches a verdict: {word!r}"


def test_the_page_names_v1_as_the_prior_version_and_v1_does_not_know_about_v2(page, body):
    """One-way. v2 is additive, so it links back; v1 is unchanged, so it cannot link
    forward, and a v1 page that had learned about v2 would be a v1 page that had been
    edited."""
    assert body["prior_version"]["json"] == "/advantage.json"
    assert body["prior_version"]["page"] == "/advantage"
    assert 'href="/advantage.json"' in page and 'href="/advantage"' in page

    v1_page = (WEB / "advantage.html").read_text(encoding="utf-8")
    assert "/advantage/v2" not in v1_page
    assert "v2" not in v1_page.lower().replace("?v=2", "")


def test_v1_json_keeps_its_exact_shape(client):
    """The machine contract v2 must not have moved. Three keys, three experiments, and no
    field added to the document an evaluator's agent already reads."""
    v1 = client.get("/advantage.json").json()

    assert set(v1) == {"method", "page", "experiments"}
    assert v1["page"] == "/advantage"
    assert [experiment["task_id"] for experiment in v1["experiments"]] == [
        "01-liquidity",
        "02-trading",
        "03-security",
    ]


def test_the_service_card_figure_is_computed_from_the_record_and_cannot_drift(body):
    """Three places quote this rate — the card, the report and the score behind both — and
    the way one of them goes stale is by being a transcription. So the test recomputes it
    from the committed corpus and the committed run and asserts all three agree."""
    recomputed = scoring.score(
        report.corpus(),
        scoring.scan_results(report.run("03-security-corpus"))["results"],
    )["decision_level"]["recall"]
    card = next(
        metric
        for metric in SERVICES["warden-scan"].metrics
        if metric.name == "Labelled attacks flagged"
    )
    served = next(
        experiment["headline"]["figure"]["rate"]
        for experiment in body["experiments"]
        if experiment["experiment_id"] == "03-security-corpus"
    )

    assert (card.numerator, card.denominator) == (
        recomputed["numerator"],
        recomputed["denominator"],
    )
    assert (served["numerator"], served["denominator"]) == (
        recomputed["numerator"],
        recomputed["denominator"],
    )
    assert card.render().startswith("14 of 31")
    # The null and the margin travel with the figure on the card too, for the same reason
    # they travel with it in the document.
    assert "12 of the same 31" in card.method
    assert "margin over it is 2 payloads" in card.method
    assert card.observed_at == report.run("03-security-corpus")["finished_at"][:10]


def test_the_security_claim_is_no_longer_the_tautology_and_the_run_cites_the_new_hash(body):
    """The registered claim's first clause could not fail: it compared class-level naming
    against a null that names no classes at all. It is re-registered in the words of the
    falsifier that actually decides it — unchanged, and registered before the run — and the
    run record cites the new hash in every place it cited the old one."""
    security = next(
        experiment
        for experiment in body["experiments"]
        if experiment["experiment_id"] == "03-security-corpus"
    )
    claim = security["spec"]["claim"]
    run = json.loads((V2 / "runs" / "03-security-corpus.json").read_text(encoding="utf-8"))

    assert "returns the labelled threat class more often" not in claim
    assert "decision-level recall" in claim and "decision-level precision" in claim
    assert run["spec_hash"] == security["spec"]["spec_hash"]
    assert {entry["spec_hash"] for entry in run["payloads"]} == {security["spec"]["spec_hash"]}


def test_both_agent_facing_documents_carry_the_v2_path_in_lockstep(client):
    """The drift test holds llms.txt to every path in the schema; SKILL.md is not in that
    loop and would have gone stale on its own."""
    for path in ("/llms.txt", "/skill.md"):
        served = client.get(path).text
        assert "/advantage/v2.json" in served, path
        assert "/advantage.json" in served, path
    assert "/advantage/v2.json" in (STATIC / "llms.txt").read_text(encoding="utf-8")
    assert "/advantage/v2.json" in (STATIC / "SKILL.md").read_text(encoding="utf-8")


def test_the_root_index_names_the_new_document_without_moving_the_old_one(client):
    index = client.get("/", headers={"accept": "application/json"}).json()

    assert index["advantage"] == "/advantage.json"
    assert index["advantage_v2"] == "/advantage/v2.json"
